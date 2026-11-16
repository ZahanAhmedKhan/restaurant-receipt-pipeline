"""Turn raw OCR text into structured receipt fields.

Output (same keys as the ground-truth JSON):
    {
        "vendor": "HARBOR FRESH FOODS",
        "date": "06/14/2026",            # raw text; clean.py turns it into a date
        "receipt_number": "HF-10234",
        "lines": [
            {"description": "CHKN BRST 10LB", "quantity": "2", "unit": "CS",
             "unit_price": "32.50", "line_total": "65.00"},
        ],
        "subtotal": "65.00", "tax": "0.00", "total": "65.00",
    }

Numbers are returned as clean digit strings ("32.50"); clean.py converts them
to Decimal. Anything we can't read confidently becomes None. We never guess.
"""

import re

# Units our suppliers print. Matched case-insensitively ("cs" == "CS").
KNOWN_UNITS = {"CS", "BAG", "JUG", "EA", "LB", "BX", "KG", "DZ", "GAL", "CT", "PK"}

# Letters OCR often reads instead of digits. Only applied to number tokens.
DIGIT_FIXES = {"O": "0", "o": "0", "@": "0", "l": "1", "I": "1", "|": "1"}

# Money: digits, a dot, exactly two decimals (e.g. 1234.56)
MONEY_PATTERN = re.compile(r"^\d{1,7}\.\d{2}$")
# Quantity: whole number or decimal weight (e.g. 3 or 14.62)
QUANTITY_PATTERN = re.compile(r"^\d{1,5}(\.\d{1,3})?$")

# Header lines. ^ and $ with re.MULTILINE match at the start/end of each line.
RECEIPT_NUMBER_PATTERN = re.compile(r"^\s*(?:INVOICE|RECEIPT)\s*(?:#|NO\.?)?\s*[:;]?\s*(\S+)", re.I | re.M)
DATE_PATTERN = re.compile(r"^\s*DATE\s*[:;]?\s*(.+?)\s*$", re.I | re.M)
SUBTOTAL_PATTERN = re.compile(r"^\s*SUB\s*-?\s*TOTAL\s*[:;]?\s*(\S+)\s*$", re.I | re.M)
TAX_PATTERN = re.compile(r"^\s*TAX\s*[:;]?\s*(\S+)\s*$", re.I | re.M)
TOTAL_PATTERN = re.compile(r"^\s*TOTAL\s*[:;]?\s*(\S+)\s*$", re.I | re.M)

# The column header line that starts the item list
ITEMS_HEADER_PATTERN = re.compile(r"^\s*QTY\b.*DESCRIPTION", re.I)
# The item list ends at the first SUBTOTAL / TAX / TOTAL line,
# even if OCR garbled the number after it
ITEMS_END_PATTERN = re.compile(r"^\s*(?:SUB\s*-?\s*TOTAL|TAX|TOTAL)\b", re.I)
# Lines made only of dashes, equals signs or underscores
SEPARATOR_PATTERN = re.compile(r"^[\s\-=_~.]+$")


# ---------------------------------------------------------------------------
# Small helpers for numbers
# ---------------------------------------------------------------------------
def fix_digits(token):
    """Apply the common OCR letter->digit fixes and drop a trailing comma."""
    token = token.strip().rstrip(",")
    fixed = ""
    for char in token:
        fixed += DIGIT_FIXES.get(char, char)
    return fixed


def parse_money(token):
    """'1,234.56' -> '1234.56'. Returns None if it doesn't look like money."""
    if token is None:
        return None
    value = fix_digits(token)
    # Thousands separators: 1,234.56
    if re.fullmatch(r"\d{1,3}(,\d{3})+\.\d{2}", value):
        value = value.replace(",", "")
    if MONEY_PATTERN.match(value):
        return value
    return None


def parse_quantity(token):
    """'3' -> '3', '14.62' -> '14.62'. Returns None if unreadable."""
    if token is None:
        return None
    value = fix_digits(token)
    if QUANTITY_PATTERN.match(value):
        return value
    return None


def first_match(pattern, text):
    """Return group 1 of the first match, or None."""
    match = pattern.search(text)
    if match:
        return match.group(1)
    return None


# ---------------------------------------------------------------------------
# Header fields
# ---------------------------------------------------------------------------
def parse_vendor(lines):
    """The vendor name is the first non-empty line of the receipt."""
    for line in lines:
        text = line.strip()
        if text and not SEPARATOR_PATTERN.match(text):
            return text
    return None


# ---------------------------------------------------------------------------
# Line items
# ---------------------------------------------------------------------------
def item_section(lines):
    """Return the lines between the column header and SUBTOTAL."""
    start = None
    for i, line in enumerate(lines):
        if ITEMS_HEADER_PATTERN.match(line):
            start = i + 1
            break
    if start is None:
        return []

    section = []
    for line in lines[start:]:
        if ITEMS_END_PATTERN.match(line):
            break
        if line.strip() and not SEPARATOR_PATTERN.match(line):
            section.append(line)
    return section


def parse_item_line(line):
    """Split one item line: QTY DESCRIPTION UNIT PRICE AMOUNT.

    The description can contain spaces and digits (e.g. 'GRND BEEF 80/20 10LB'),
    so we find the UNIT token from the right and split around it.
    """
    tokens = line.split()
    if len(tokens) < 2:
        return None

    # Find the last token that is a known unit
    unit_index = None
    for i in range(len(tokens) - 1, 0, -1):
        if tokens[i].upper() in KNOWN_UNITS:
            unit_index = i
            break

    if unit_index is not None:
        description_tokens = tokens[1:unit_index]
        unit = tokens[unit_index].upper()
        after = tokens[unit_index + 1:]
    else:
        # No unit found: assume the last two tokens are price and amount
        description_tokens = tokens[1:-2]
        unit = None
        after = tokens[-2:]

    # We expect exactly two tokens after the unit: price and amount.
    # Anything else means OCR garbled them, so we don't trust either.
    if len(after) == 2:
        unit_price = parse_money(after[0])
        line_total = parse_money(after[1])
    else:
        unit_price = None
        line_total = None

    description = " ".join(description_tokens) or None
    return {
        "description": description,
        "quantity": parse_quantity(tokens[0]),
        "unit": unit,
        "unit_price": unit_price,
        "line_total": line_total,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def parse_receipt_text(text):
    """Turn the OCR text of one receipt into a dict of fields."""
    text = text or ""
    lines = text.splitlines()

    items = []
    for line in item_section(lines):
        item = parse_item_line(line)
        if item is not None:
            items.append(item)

    return {
        "vendor": parse_vendor(lines),
        "date": first_match(DATE_PATTERN, text),
        "receipt_number": first_match(RECEIPT_NUMBER_PATTERN, text),
        "lines": items,
        "subtotal": parse_money(first_match(SUBTOTAL_PATTERN, text)),
        "tax": parse_money(first_match(TAX_PATTERN, text)),
        "total": parse_money(first_match(TOTAL_PATTERN, text)),
    }
