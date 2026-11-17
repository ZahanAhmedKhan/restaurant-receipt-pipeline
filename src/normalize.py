"""Item normalization: messy description -> standard item, pack size -> standard unit.

Example:
    'CHKN BRST 10LB', quantity 2, unit CS, line total 65.00
    -> item 'chicken breast', 2 x 10 lb = 20 lb, 3.25 per lb

Rules live in mart.item_mapping (see sql/005_item_mapping.sql).
"""

import re
from decimal import ROUND_HALF_UP, Decimal

LB_PER_KG = Decimal("2.20462")
LB_PER_OZ = Decimal("0.0625")
L_PER_GAL = Decimal("3.78541")

# Pack size printed in a description: a number followed by a unit, e.g. 10LB, 50 LB, 4.5KG
PACK_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(LB|KG|OZ|CT|DZ|GAL|L)\b", re.I)

# Receipt units that mean "the quantity itself is a weight"
WEIGHT_UNITS = {"LB", "KG"}


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
def to_standard(amount, unit):
    """Convert an amount in a pack/receipt unit to (amount, standard unit).

    Weight -> lb, count -> each, volume -> L. Returns (None, None) if unknown.
    """
    unit = (unit or "").upper()
    if unit == "LB":
        return amount, "lb"
    if unit == "KG":
        return amount * LB_PER_KG, "lb"
    if unit == "OZ":
        return amount * LB_PER_OZ, "lb"
    if unit in ("CT", "EA"):
        return amount, "each"
    if unit == "DZ":
        return amount * 12, "each"
    if unit == "GAL":
        return amount * L_PER_GAL, "L"
    if unit == "L":
        return amount, "L"
    return None, None


def parse_pack_size(description):
    """'CHKN BRST 10LB' -> (Decimal('10'), 'LB'). The last match wins
    ('GRND BEEF 80/20 10LB' -> 10 LB). Returns (None, None) if none found."""
    matches = PACK_PATTERN.findall(description or "")
    if not matches:
        return None, None
    size, unit = matches[-1]
    return Decimal(size), unit.upper()


# ---------------------------------------------------------------------------
# Mapping rules
# ---------------------------------------------------------------------------
def pattern_to_regex(pattern):
    """Turn an ILIKE pattern ('%CHKN%BRST%') into a Python regex."""
    parts = []
    for char in pattern:
        if char == "%":
            parts.append(".*")
        elif char == "_":
            parts.append(".")
        else:
            parts.append(re.escape(char))
    return re.compile("".join(parts), re.I | re.S)


def find_rule(description, rules):
    """Return the matching rule with the longest pattern, or None.

    rules: list of dicts with at least 'description_pattern'.
    """
    if not description:
        return None
    best = None
    for rule in rules:
        if pattern_to_regex(rule["description_pattern"]).fullmatch(description):
            if best is None or len(rule["description_pattern"]) > len(best["description_pattern"]):
                best = rule
    return best


# ---------------------------------------------------------------------------
# One line
# ---------------------------------------------------------------------------
def standard_quantity(quantity, receipt_unit, description, rule):
    """How much of the item's standard unit this line bought, or None if unknown."""
    if quantity is None or rule is None:
        return None
    wanted_unit = rule["standard_unit"]
    receipt_unit = (receipt_unit or "").upper()

    if receipt_unit in WEIGHT_UNITS:
        # Sold by weight: the quantity itself is the weight
        amount, unit = to_standard(quantity, receipt_unit)
    else:
        # Sold by the pack/case: quantity x pack size
        pack_size, pack_unit = rule.get("pack_size"), rule.get("pack_unit")
        if pack_size is None:
            pack_size, pack_unit = parse_pack_size(description)
        if pack_size is None:
            # No pack size: one unit is one 'each' (e.g. FOIL ROLL 18IN, EA)
            pack_size, pack_unit = Decimal("1"), "EA"
        per_pack, unit = to_standard(Decimal(pack_size), pack_unit)
        amount = quantity * per_pack if per_pack is not None else None

    if amount is None or unit is None:
        return None
    if wanted_unit == "kg" and unit == "lb":
        amount, unit = amount / LB_PER_KG, "kg"
    if unit != wanted_unit:
        return None            # e.g. rule says lb but the pack is counted in each
    return amount.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def normalize_line(description, quantity, receipt_unit, line_total, rules):
    """Return {"item_name", "standard_quantity", "unit_price_standard"} for one line.

    Unmatched descriptions give item_name None (the mart uses UNMAPPED).
    """
    rule = find_rule(description, rules)
    if rule is None:
        return {"item_name": None, "standard_quantity": None, "unit_price_standard": None}
    std_qty = standard_quantity(quantity, receipt_unit, description, rule)
    unit_price = None
    if std_qty and line_total is not None:
        unit_price = (line_total / std_qty).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return {"item_name": rule["item_name"], "standard_quantity": std_qty,
            "unit_price_standard": unit_price}


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
RULE_COLUMNS = ["description_pattern", "item_name", "category", "standard_unit", "pack_size", "pack_unit"]


def load_rules(conn):
    rows = conn.execute(
        f"SELECT {', '.join(RULE_COLUMNS)} FROM mart.item_mapping ORDER BY mapping_id"
    ).fetchall()
    return [dict(zip(RULE_COLUMNS, row)) for row in rows]


def upsert_items(conn, rules):
    """One dim_item row per item name used in the rules."""
    for rule in rules:
        conn.execute(
            """
            INSERT INTO mart.dim_item (item_name, category, standard_unit)
            VALUES (%s, %s, %s)
            ON CONFLICT (item_name) DO UPDATE
                SET category = EXCLUDED.category, standard_unit = EXCLUDED.standard_unit
            """,
            (rule["item_name"], rule["category"], rule["standard_unit"]),
        )


def normalize_facts(conn):
    """Set item_key, standard_quantity and unit_price_standard on every fact row.

    Run inside the mart build transaction (after the facts are inserted).
    Returns the number of fact rows that matched an item.
    """
    rules = load_rules(conn)
    upsert_items(conn, rules)
    item_keys = dict(conn.execute("SELECT item_name, item_key FROM mart.dim_item").fetchall())

    facts = conn.execute(
        """
        SELECT f.purchase_key, l.description, f.quantity, l.unit_raw, f.line_total
        FROM mart.fact_purchase_line f
        JOIN clean.receipt_line l ON l.line_id = f.line_id
        """
    ).fetchall()

    updates = []
    for purchase_key, description, quantity, unit_raw, line_total in facts:
        result = normalize_line(description, quantity, unit_raw, line_total, rules)
        if result["item_name"] is None:
            continue
        updates.append((item_keys[result["item_name"]], result["standard_quantity"],
                        result["unit_price_standard"], purchase_key))

    with conn.cursor() as cursor:
        cursor.executemany(
            """
            UPDATE mart.fact_purchase_line
            SET item_key = %s, standard_quantity = %s, unit_price_standard = %s
            WHERE purchase_key = %s
            """,
            updates,
        )
    return len(updates)


def unmapped_descriptions(conn):
    """Approved-line descriptions with no mapping rule: (description, lines, spend)."""
    return conn.execute(
        """
        SELECT l.description, count(*) AS lines, sum(f.line_total) AS spend
        FROM mart.fact_purchase_line f
        JOIN mart.dim_item i ON i.item_key = f.item_key
        JOIN clean.receipt_line l ON l.line_id = f.line_id
        WHERE i.item_name = 'UNMAPPED'
        GROUP BY l.description
        ORDER BY spend DESC NULLS LAST
        """
    ).fetchall()


def add_rule(conn, description_pattern, item_name, category, standard_unit,
             pack_size=None, pack_unit=None):
    """Add a mapping rule (from the Items page)."""
    conn.execute(
        f"INSERT INTO mart.item_mapping ({', '.join(RULE_COLUMNS)}) VALUES (%s, %s, %s, %s, %s, %s)",
        (description_pattern.strip().upper(), item_name.strip().lower(), category or None,
         standard_unit, pack_size, pack_unit or None),
    )
