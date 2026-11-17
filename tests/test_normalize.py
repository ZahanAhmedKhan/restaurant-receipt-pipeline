"""Tests for src/normalize.py."""

from decimal import Decimal as D

from src import load_mart, normalize, review
from tests.test_quality import insert_receipt

RULES = [
    {"description_pattern": "%CHKN%BRST%", "item_name": "chicken breast", "category": "Meat",
     "standard_unit": "lb", "pack_size": None, "pack_unit": None},
    {"description_pattern": "%TOMATO%", "item_name": "tomatoes", "category": "Produce",
     "standard_unit": "lb", "pack_size": None, "pack_unit": None},
    {"description_pattern": "%TOMATOES%ROMA%", "item_name": "roma tomatoes", "category": "Produce",
     "standard_unit": "lb", "pack_size": None, "pack_unit": None},
    {"description_pattern": "%LAMB%LEG%", "item_name": "lamb leg", "category": "Meat",
     "standard_unit": "lb", "pack_size": None, "pack_unit": None},
    {"description_pattern": "%EGGS%LG%", "item_name": "large eggs", "category": "Dairy",
     "standard_unit": "each", "pack_size": None, "pack_unit": None},
    {"description_pattern": "%DISH%SOAP%", "item_name": "dish soap", "category": "Supplies",
     "standard_unit": "L", "pack_size": None, "pack_unit": None},
    {"description_pattern": "%FOIL%ROLL%", "item_name": "foil roll", "category": "Supplies",
     "standard_unit": "each", "pack_size": None, "pack_unit": None},
    {"description_pattern": "%NAPKINS%", "item_name": "napkins", "category": "Supplies",
     "standard_unit": "each", "pack_size": D("500"), "pack_unit": "CT"},
]


def test_parse_pack_size():
    assert normalize.parse_pack_size("CHKN BRST 10LB") == (D("10"), "LB")
    assert normalize.parse_pack_size("GRND BEEF 80/20 10LB") == (D("10"), "LB")
    assert normalize.parse_pack_size("ONIONS YELLOW 50 LB") == (D("50"), "LB")
    assert normalize.parse_pack_size("LAMB LEG BNLS 4.5KG") == (D("4.5"), "KG")
    assert normalize.parse_pack_size("FOIL ROLL 18IN") == (None, None)


def test_kg_to_lb_conversion():
    amount, unit = normalize.to_standard(D("1"), "KG")
    assert amount == D("2.20462") and unit == "lb"


def test_longest_matching_rule_wins():
    assert normalize.find_rule("TOMATOES ROMA 25 LB", RULES)["item_name"] == "roma tomatoes"
    assert normalize.find_rule("TOMATO 25LB", RULES)["item_name"] == "tomatoes"
    assert normalize.find_rule("chkn brst 10lb", RULES)["item_name"] == "chicken breast"
    assert normalize.find_rule("MYSTERY BOX", RULES) is None


def test_case_of_chicken_breast():
    result = normalize.normalize_line("CHKN BRST 10LB", D("2"), "CS", D("65.00"), RULES)
    assert result == {"item_name": "chicken breast", "standard_quantity": D("20.000"),
                      "unit_price_standard": D("3.2500")}


def test_sold_by_weight_uses_quantity():
    rules = RULES + [{"description_pattern": "%BEEF%BRISKET%", "item_name": "beef brisket",
                      "category": "Meat", "standard_unit": "lb", "pack_size": None, "pack_unit": None}]
    result = normalize.normalize_line("BEEF BRISKET", D("14.62"), "LB", D("71.49"), rules)
    assert result["standard_quantity"] == D("14.620")
    assert result["unit_price_standard"] == D("4.8899")


def test_kg_pack_converted_to_lb():
    result = normalize.normalize_line("LAMB LEG BNLS 4.5KG", D("2"), "EA", D("144.00"), RULES)
    assert result["standard_quantity"] == D("19.842")        # 2 x 4.5 kg x 2.20462


def test_dozens_and_gallons():
    eggs = normalize.normalize_line("EGGS LG 15DZ", D("1"), "CS", D("39.90"), RULES)
    soap = normalize.normalize_line("DISH SOAP 1GAL", D("2"), "EA", D("25.50"), RULES)
    assert eggs["standard_quantity"] == D("180.000")
    assert soap["standard_quantity"] == D("7.571")


def test_no_pack_size_counts_each():
    result = normalize.normalize_line("FOIL ROLL 18IN", D("3"), "EA", D("73.80"), RULES)
    assert result["standard_quantity"] == D("3.000")


def test_rule_pack_size_overrides_description():
    result = normalize.normalize_line("NAPKINS 6000CT", D("2"), "CS", D("60.00"), RULES)
    assert result["standard_quantity"] == D("1000.000")


def test_unit_mismatch_gives_none():
    # rule says lb, but the pack is counted in pieces
    result = normalize.normalize_line("CHKN BRST 40CT", D("1"), "CS", D("30.00"), RULES)
    assert result["item_name"] == "chicken breast"
    assert result["standard_quantity"] is None
    assert result["unit_price_standard"] is None


def test_missing_quantity_keeps_item_but_no_price():
    result = normalize.normalize_line("CHKN BRST 10LB", None, "CS", D("65.00"), RULES)
    assert result["item_name"] == "chicken breast"
    assert result["unit_price_standard"] is None


# --- database ---------------------------------------------------------------------
def test_mart_build_maps_items_and_lists_unmapped(db_conn):
    receipt_id = insert_receipt(db_conn, 1)               # lines 'A' and 'B': no rules
    db_conn.execute("UPDATE clean.receipt_line SET description = 'CHKN BRST 10LB' "
                    "WHERE receipt_id = %s AND line_no = 1", (receipt_id,))
    review.set_review_status(db_conn, receipt_id, "approved")
    load_mart.build_mart(db_conn)

    row = db_conn.execute(
        """
        SELECT i.item_name, i.standard_unit, f.standard_quantity, f.unit_price_standard
        FROM mart.fact_purchase_line f JOIN mart.dim_item i USING (item_key)
        JOIN clean.receipt_line l ON l.line_id = f.line_id
        WHERE l.line_no = 1
        """
    ).fetchone()
    assert row == ("chicken breast", "lb", D("10.000"), D("1.0000"))   # 1 case = 10 lb for $10
    assert [r[0] for r in normalize.unmapped_descriptions(db_conn)] == ["B"]


def test_added_rule_maps_on_next_build(db_conn):
    receipt_id = insert_receipt(db_conn, 1)
    review.set_review_status(db_conn, receipt_id, "approved")
    load_mart.build_mart(db_conn)
    assert len(normalize.unmapped_descriptions(db_conn)) == 2

    normalize.add_rule(db_conn, "b", "test item b", "Test", "each")
    try:
        load_mart.build_mart(db_conn)
        assert [r[0] for r in normalize.unmapped_descriptions(db_conn)] == ["A"]
    finally:
        db_conn.execute("DELETE FROM mart.item_mapping WHERE description_pattern = 'B'")
