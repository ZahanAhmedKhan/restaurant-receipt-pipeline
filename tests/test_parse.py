"""Tests for src/parse.py using fixed OCR text (no OCR needed)."""

from src.parse import parse_item_line, parse_money, parse_quantity, parse_receipt_text

CLEAN_TEXT = """HARBOR FRESH FOODS
1200 Dockside Ave, Riverton
Tel (555) 201-4410

INVOICE #: HF-10210
DATE: 06/07/2026
--------------------------------------------------
QTY   DESCRIPTION               UNIT  PRICE  AMOUNT
--------------------------------------------------
5 OIL CANOLA 35LB JUG 41.20 206.00
4 GRND BEEF 80/20 10LB cs 48.00 192.00
26.64 BEEF BRISKET LB 4.86 129.47
--------------------------------------------------
SUBTOTAL 527.47
TAX 0.00
TOTAL 527.47
THANK YOU FOR YOUR BUSINESS
"""

# Real kinds of OCR mistakes seen on our sample receipts
MESSY_TEXT = """SUNRISE MEAT CO.
4 Packer St, Millbrook
INVOICE #: SMC-3138
DATE: Jul 12, 2026
QTY DESCRIPTION UNIT PRICE AMOUNT
2 LAMB LEG BNLS 4.5KG EA 72.62 145.24
ES CHKN THIGH BNLS 10LB cs Zitz Zhe
3 GROUND BEEF 80/20 10 LB cs 46.73 14O.19
2 ONION YEL 50LB BAG 23.97, 47.94
1 CHKN THIGH BNLS 10LB cs 27.72 2772
6 ONIONS YELLOW 50 LB BAG Aa SS als). 21)
SUBTOTAL 608.62
TAX 0.0O
TOTAL 6O8.62
"""


def test_header_fields():
    result = parse_receipt_text(CLEAN_TEXT)
    assert result["vendor"] == "HARBOR FRESH FOODS"
    assert result["receipt_number"] == "HF-10210"
    assert result["date"] == "06/07/2026"
    assert result["subtotal"] == "527.47"
    assert result["tax"] == "0.00"
    assert result["total"] == "527.47"


def test_total_is_not_confused_with_subtotal():
    result = parse_receipt_text("SUBTOTAL 10.00\nTOTAL 12.00\n")
    assert result["subtotal"] == "10.00"
    assert result["total"] == "12.00"


def test_item_lines_clean():
    lines = parse_receipt_text(CLEAN_TEXT)["lines"]
    assert len(lines) == 3
    assert lines[0] == {"description": "OIL CANOLA 35LB", "quantity": "5", "unit": "JUG",
                        "unit_price": "41.20", "line_total": "206.00"}
    # Description keeps its own numbers; lowercase unit is normalized
    assert lines[1]["description"] == "GRND BEEF 80/20 10LB"
    assert lines[1]["unit"] == "CS"
    # Weight quantity with decimals
    assert lines[2]["quantity"] == "26.64"
    assert lines[2]["unit"] == "LB"


def test_messy_lines_become_none_not_guesses():
    lines = parse_receipt_text(MESSY_TEXT)["lines"]
    assert len(lines) == 6
    garbled = lines[1]
    assert garbled["quantity"] is None              # "ES"
    assert garbled["unit_price"] is None            # "Zitz"
    assert garbled["line_total"] is None            # "Zhe"
    assert garbled["description"] == "CHKN THIGH BNLS 10LB"
    assert lines[4]["line_total"] is None           # "2772" lost its dot: don't guess
    assert lines[5]["unit_price"] is None           # too many junk tokens
    assert lines[5]["line_total"] is None


def test_messy_letter_digit_fixes():
    result = parse_receipt_text(MESSY_TEXT)
    assert result["lines"][2]["line_total"] == "140.19"    # O -> 0
    assert result["lines"][3]["unit_price"] == "23.97"     # trailing comma dropped
    assert result["tax"] == "0.00"
    assert result["total"] == "608.62"
    assert result["date"] == "Jul 12, 2026"


def test_garbled_subtotal_still_ends_item_list():
    text = ("QTY DESCRIPTION UNIT PRICE AMOUNT\n"
            "3 RICE JASMINE 25 LB BAG 28.14 84.42\n"
            "SUBTOTAL alhl Ss}\n"
            "TAX 10.85\n"
            "TOTAL 142.38\n")
    result = parse_receipt_text(text)
    assert len(result["lines"]) == 1
    assert result["subtotal"] is None
    assert result["tax"] == "10.85"


def test_empty_text_gives_all_none():
    result = parse_receipt_text("")
    assert result == {"vendor": None, "date": None, "receipt_number": None, "lines": [],
                      "subtotal": None, "tax": None, "total": None}


def test_missing_fields_are_none():
    result = parse_receipt_text("SOME SHOP\nTOTAL 9.99\n")
    assert result["vendor"] == "SOME SHOP"
    assert result["receipt_number"] is None
    assert result["date"] is None
    assert result["subtotal"] is None
    assert result["total"] == "9.99"


def test_parse_money_rules():
    assert parse_money("1,234.56") == "1234.56"
    assert parse_money("12.5") is None          # needs exactly 2 decimals
    assert parse_money("abc") is None
    assert parse_money(None) is None


def test_parse_quantity_rules():
    assert parse_quantity("l") == "1"
    assert parse_quantity("5)") is None
    assert parse_quantity("14.62") == "14.62"


def test_line_without_known_unit():
    item = parse_item_line("2 MYSTERY ITEM 3.00 6.00")
    assert item["unit"] is None
    assert item["description"] == "MYSTERY ITEM"
    assert item["unit_price"] == "3.00"
    assert item["line_total"] == "6.00"
