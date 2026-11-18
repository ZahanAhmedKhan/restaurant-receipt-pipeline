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
from decimal import Decimal

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
SUBTOTAL_PATTERN = re.compile(r"^\s*SUB\s*-?\s*TOTAL\s*[:;]?\s*(\S+)\s*$", re.I | re.M)
# Tax lines: TAX, or Canadian labels HST, GST/HST, GST, PST, QST (TPS/TVQ in French).
# The amount is the last token on the line ("HST 13% 50.50" -> 50.50).
TAX_LINE_PATTERN = re.compile(
    r"^\s*(?:SALES\s+)?(?:TAX|GST\s*/\s*HST|HST|GST|PST|QST|TPS|TVQ)\b.*?(\S+)\s*$", re.I | re.M)
# Lines that only show a tax REGISTRATION number, not an amount
TAX_NUMBER_LINE = re.compile(r"#|\bREG\b|\bNO\.|\d{9}\s?RT", re.I)

# The column header line that starts the item list
ITEMS_HEADER_PATTERN = re.compile(r"^\s*QTY\b.*DESCRIPTION", re.I)
# The item list ends at the first SUBTOTAL / TAX / TOTAL line,
# even if OCR garbled the number after it
ITEMS_END_PATTERN = re.compile(
    r"^\s*(?:SUB\s*-?\s*TOTAL|TAX|TOTAL|GST|HST|PST|QST|TPS|TVQ)\b", re.I)
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
def parse_tax(text):
    """Add up every tax line (e.g. GST 5.00 + PST 7.00 = 12.00).

    Returns None if there is no tax line, or if any tax amount can't be read
    (a partial sum would be a guess).
    """
    amounts = []
    for match in TAX_LINE_PATTERN.finditer(text):
        line = match.group(0)
        if TAX_NUMBER_LINE.search(line):
            continue                       # 'GST/HST #: 123456789 RT0001' is not an amount
        amount = parse_money(match.group(1))
        if amount is None:
            return None
        amounts.append(Decimal(amount))
    if not amounts:
        return None
    return str(sum(amounts))


# --- Total -------------------------------------------------------------------
# A line that can hold the final total
TOTAL_WORDS = re.compile(r"TOTAL|AMOUNT\s+DUE|BALANCE\s+DUE|\bNETT?\b|GRAND", re.I)
# Lines with the word TOTAL that are NOT the final total
NOT_FINAL_TOTAL = re.compile(
    r"SUB|QTY|QUANTITY|ITEMS?\b|SAVING|DISCOUNT|CHANGE|TENDER|\bCASH\b|EXCL|\bEX\)"
    r"|TOTAL\s*(?:GST|TAX|SST|HST|VAT)\b|TOTALGST|SUMMARY|INCLUDED",
    re.I,
)
# One amount on a line: 9.00, 1,234.56, 5,90 (decimal comma), 11. 80 (OCR space)
AMOUNT_PATTERN = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d+)\s?[.,]\s?(\d{2})(?!\d)")


def amounts_on_line(line):
    """All money amounts on a line, as clean strings ('1234.56')."""
    # Fix OCR letter/digit mix-ups only in tokens that contain a digit
    tokens = [fix_digits(t) if any(c.isdigit() for c in t) else t for t in line.split()]
    amounts = []
    for whole, cents in AMOUNT_PATTERN.findall(" ".join(tokens)):
        amounts.append(f"{whole.replace(',', '')}.{cents}")
    return amounts


def parse_total(lines):
    """The final total: the LAST total-type line that holds exactly one amount.

    Receipts usually go subtotal -> tax -> total -> rounded total, so the last
    total line is the amount actually paid. Sub-totals, item counts, tax lines
    and two-amount summary rows are skipped.
    """
    total = None
    for line in lines:
        if not TOTAL_WORDS.search(line) or NOT_FINAL_TOTAL.search(line):
            continue
        amounts = amounts_on_line(line)
        if len(amounts) == 1:
            total = amounts[0]
    return total


# --- Date --------------------------------------------------------------------
MONTHS = r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)[A-Z]*\.?"
DATE_TOKEN = re.compile(
    r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b"                      # 2018/02/22, 2026-06-14
    r"|\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b"                  # 25/12/2018, 23-01-2019, 5.3.18
    rf"|\b\d{{1,2}}[ -]?{MONTHS}[ -]?\d{{2,4}}\b"            # 12 Mar 2018, 14-Jun-2026
    rf"|\b{MONTHS}\s+\d{{1,2}},?\s+\d{{4}}\b",               # Jul 10, 2026
    re.I,
)
# "DATE" and common OCR misreadings of it
DATE_LABEL = re.compile(r"\b(?:DATE|DATED|DALE|DATA|FATE)\b", re.I)


def parse_date(lines):
    """The receipt date as printed (raw text; clean.py decides day/month order).

    Prefer a date on a line labelled DATE; otherwise the first date anywhere.
    """
    first_found = None
    for line in lines:
        match = DATE_TOKEN.search(line)
        if not match:
            continue
        if DATE_LABEL.search(line):
            return match.group(0)
        if first_found is None:
            first_found = match.group(0)
    return first_found


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
        "date": parse_date(lines),
        "receipt_number": first_match(RECEIPT_NUMBER_PATTERN, text),
        "lines": items,
        "subtotal": parse_money(first_match(SUBTOTAL_PATTERN, text)),
        "tax": parse_tax(text),
        "total": parse_total(lines),
    }
