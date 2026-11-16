"""Generate fake supplier receipts (images + ground-truth JSON).

All vendors, addresses and numbers are made up. These receipts are the
public demo data and the labelled data for OCR evaluation.

Output in data/sample/:
    receipt_001.png   the receipt image (some are .jpg)
    receipt_001.json  the correct values printed on that receipt

Deliberate problems (recorded in "deliberate_errors" in the JSON):
    wrong_total               printed TOTAL is not SUBTOTAL + TAX
    lines_dont_match_subtotal printed SUBTOTAL is not the sum of the lines
    duplicate_receipt         same receipt photographed again (different image)
    duplicate_file            byte-for-byte copy of another image file

Usage:
    python scripts/make_sample_receipts.py
"""

import json
import random
import shutil
import sys
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402

SEED = 42
UNIQUE_RECEIPTS = 48          # plus 2 duplicates = 50 files
START_DATE = date(2026, 6, 1)
END_DATE = date(2026, 11, 10)
CENT = Decimal("0.01")

# ---------------------------------------------------------------------------
# Fake vendors. Each one prints dates and receipt numbers in its own style,
# which gives the cleaning step something real to standardize.
# ---------------------------------------------------------------------------
VENDORS = [
    {
        "name": "Harbor Fresh Foods",
        "address": "1200 Dockside Ave, Riverton",
        "phone": "(555) 201-4410",
        "date_format": "%m/%d/%Y",          # 06/14/2026
        "number_format": "HF-{n:05d}",
        "number_start": 10200,
        "tax_rate": Decimal("0"),
        "items": [
            # description printed,  unit, base price
            ("CHKN BRST 10LB", "CS", "32.50"),
            ("GRND BEEF 80/20 10LB", "CS", "48.00"),
            ("RICE JASMINE 25LB", "BAG", "27.75"),
            ("OIL CANOLA 35LB", "JUG", "41.20"),
            ("FLOUR AP 50LB", "BAG", "22.40"),
            ("EGGS LG 15DZ", "CS", "39.90"),
            ("ONION YEL 50LB", "BAG", "24.00"),
            ("TOMATO 25LB", "CS", "29.50"),
        ],
    },
    {
        "name": "Golden Valley Produce",
        "address": "88 Orchard Rd, Fairfield",
        "phone": "(555) 377-9021",
        "date_format": "%Y-%m-%d",          # 2026-06-14
        "number_format": "GVP{n:06d}",
        "number_start": 500100,
        "tax_rate": Decimal("0"),
        "items": [
            ("ONIONS YELLOW 50 LB", "BAG", "21.75"),
            ("TOMATOES ROMA 25 LB", "CS", "31.00"),
            ("LETTUCE ROMAINE 24CT", "CS", "34.25"),
            ("POTATO RUSSET 50LB", "BAG", "26.50"),
            ("CILANTRO 30CT", "CS", "18.00"),
            ("LEMONS 115CT", "CS", "38.00"),
            ("GARLIC PEELED 5LB", "BAG", "16.50"),
            ("PEPPER GREEN BELL 25LB", "CS", "28.75"),
        ],
    },
    {
        "name": "Sunrise Meat Co.",
        "address": "4 Packer St, Millbrook",
        "phone": "(555) 640-1187",
        "date_format": "%b %d, %Y",         # Jun 14, 2026
        "number_format": "SMC-{n:04d}",
        "number_start": 3100,
        "tax_rate": Decimal("0"),
        "items": [
            ("CHICKEN BREAST BNLS 10 LB", "CS", "30.90"),
            ("GROUND BEEF 80/20 10 LB", "CS", "46.50"),
            ("CHKN THIGH BNLS 10LB", "CS", "27.80"),
            ("LAMB LEG BNLS 4.5KG", "EA", "72.00"),
            ("BEEF BRISKET", "LB", "4.89"),     # sold by weight
            ("GOAT CUBES", "LB", "6.25"),       # sold by weight
        ],
    },
    {
        "name": "Metro Restaurant Supply",
        "address": "350 Commerce Blvd, Riverton",
        "phone": "(555) 918-3300",
        "date_format": "%m/%d/%y",          # 06/14/26
        "number_format": "MRS{n:06d}",
        "number_start": 702300,
        "tax_rate": Decimal("0.0825"),      # supplies are taxed
        "items": [
            ("GLOVES NITRILE L 100CT", "BX", "9.80"),
            ("FOIL ROLL 18IN", "EA", "24.60"),
            ("TO-GO BOX 9X9 200CT", "CS", "38.40"),
            ("NAPKINS 6000CT", "CS", "31.20"),
            ("OIL CANOLA 35 LB", "JUG", "43.10"),
            ("RICE JASMINE 25 LB", "BAG", "29.25"),
            ("DISH SOAP 1GAL", "EA", "12.75"),
        ],
    },
]

# One item gets a deliberate price jump (> 10%) from September on,
# so the price-alert feature (M6.2) has something to find.
PRICE_JUMP = {"vendor": "Harbor Fresh Foods", "item": "CHKN BRST 10LB",
              "from": date(2026, 9, 1), "factor": Decimal("1.15")}


# ---------------------------------------------------------------------------
# Building the receipt data
# ---------------------------------------------------------------------------
def money(value):
    """Round a Decimal to cents, the way a till does (half up)."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def price_on(vendor, description, base_price, day, rng):
    """Base price with a small month-to-month drift, plus the planned jump."""
    months_in = (day.year - START_DATE.year) * 12 + day.month - START_DATE.month
    # +/- up to about 1% drift per month, fixed per item thanks to the seed
    drift = Decimal(1 + rng.uniform(-0.01, 0.015) * months_in)
    price = Decimal(base_price) * drift
    if (vendor["name"] == PRICE_JUMP["vendor"] and description == PRICE_JUMP["item"]
            and day >= PRICE_JUMP["from"]):
        price = price * PRICE_JUMP["factor"]
    return money(price)


def make_lines(vendor, day, rng):
    """Pick 3-7 random items for one receipt."""
    count = min(len(vendor["items"]), rng.randint(3, 7))
    chosen = rng.sample(vendor["items"], count)
    lines = []
    for description, unit, base_price in chosen:
        # Each item has its own random generator so its price drift is stable
        item_rng = random.Random(f"{vendor['name']}|{description}")
        unit_price = price_on(vendor, description, base_price, day, item_rng)
        if unit == "LB":
            # Sold by weight: quantity like 14.62
            quantity = Decimal(str(round(rng.uniform(8, 30), 2)))
        else:
            quantity = Decimal(rng.randint(1, 6))
        lines.append({
            "description": description,
            "quantity": quantity,
            "unit": unit,
            "unit_price": unit_price,
            "line_total": money(quantity * unit_price),
        })
    return lines


def random_day(rng):
    span = (END_DATE - START_DATE).days
    return START_DATE + timedelta(days=rng.randint(0, span))


def build_receipts(rng):
    """Create the list of unique receipts (as dicts with Decimal values)."""
    receipts = []
    counters = {v["name"]: v["number_start"] for v in VENDORS}
    for i in range(UNIQUE_RECEIPTS):
        vendor = VENDORS[i % len(VENDORS)]
        counters[vendor["name"]] += rng.randint(3, 40)
        day = random_day(rng)
        lines = make_lines(vendor, day, rng)
        subtotal = sum((line["line_total"] for line in lines), Decimal("0"))
        tax = money(subtotal * vendor["tax_rate"])
        receipts.append({
            "vendor": vendor,
            "date": day,
            "receipt_number": vendor["number_format"].format(n=counters[vendor["name"]]),
            "lines": lines,
            "subtotal": subtotal,
            "tax": tax,
            "total": subtotal + tax,
            "deliberate_errors": [],
        })
    # Receipts in date order look more natural
    receipts.sort(key=lambda r: r["date"])
    return receipts


def add_deliberate_errors(receipts):
    """Break a few receipts on purpose. Indexes are fixed so results are repeatable."""
    # 1-3: printed total is wrong (typo on the receipt)
    receipts[5]["total"] += Decimal("10.00")
    receipts[17]["total"] -= Decimal("1.00")
    receipts[30]["total"] += Decimal("0.90")
    for index in (5, 17, 30):
        receipts[index]["deliberate_errors"].append("wrong_total")

    # 4: subtotal printed does not match the lines (a line was left off the sum)
    r = receipts[24]
    r["subtotal"] -= r["lines"][-1]["line_total"]
    r["tax"] = money(r["subtotal"] * r["vendor"]["tax_rate"])
    r["total"] = r["subtotal"] + r["tax"]
    r["deliberate_errors"].append("lines_dont_match_subtotal")


# ---------------------------------------------------------------------------
# Drawing the receipt image
# ---------------------------------------------------------------------------
def load_font(size):
    """Use a monospaced Windows font if present; otherwise Pillow's default.

    Courier New Bold looks like a receipt printer and has a plain zero.
    (Consolas has a dotted zero that Tesseract often read as 8 or @.)
    """
    for name in ("courbd.ttf", "cour.ttf", "consola.ttf", "DejaVuSansMono.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def format_qty(quantity):
    """Show 2 not 2.00, but keep decimals for weights (14.62)."""
    if quantity == quantity.to_integral_value():
        return str(int(quantity))
    return f"{quantity:.2f}"


def receipt_text_lines(receipt):
    """The text rows printed on the receipt, top to bottom."""
    vendor = receipt["vendor"]
    width = 50
    rows = [
        vendor["name"].upper().center(width),
        vendor["address"].center(width),
        ("Tel " + vendor["phone"]).center(width),
        "",
        f"INVOICE #: {receipt['receipt_number']}",
        f"DATE: {receipt['date'].strftime(vendor['date_format'])}",
        "-" * width,
        f"{'QTY':<6}{'DESCRIPTION':<26}{'UNIT':<5}{'PRICE':>6}{'AMOUNT':>8}",
        "-" * width,
    ]
    for line in receipt["lines"]:
        rows.append(
            f"{format_qty(line['quantity']):<6}"
            f"{line['description']:<26}"
            f"{line['unit']:<5}"
            f"{line['unit_price']:>6}"
            f"{line['line_total']:>8}"
        )
    rows += [
        "-" * width,
        f"{'SUBTOTAL':<36}{receipt['subtotal']:>14}",
        f"{'TAX':<36}{receipt['tax']:>14}",
        f"{'TOTAL':<36}{receipt['total']:>14}",
        "",
        "THANK YOU FOR YOUR BUSINESS".center(width),
    ]
    return rows


def draw_receipt(receipt, rng, angle=None):
    """Render the receipt to a slightly imperfect 'photo'."""
    font = load_font(22)
    rows = receipt_text_lines(receipt)
    line_height = 30
    margin = 40
    width = 760
    height = margin * 2 + line_height * len(rows)

    paper = rng.randint(235, 252)                  # off-white paper
    image = Image.new("L", (width, height), color=paper)
    draw = ImageDraw.Draw(image)
    ink = rng.randint(10, 50)
    for i, row in enumerate(rows):
        draw.text((margin, margin + i * line_height), row, fill=ink, font=font)

    # Small rotation, like a hand-held photo
    if angle is None:
        angle = rng.uniform(-1.5, 1.5)
    image = image.rotate(angle, expand=True, fillcolor=paper, resample=Image.BICUBIC)

    # Light sensor noise blended in
    noise = Image.effect_noise(image.size, rng.uniform(8, 20))
    image = Image.blend(image, noise, 0.08)

    # Some photos are a bit soft
    if rng.random() < 0.3:
        image = image.filter(ImageFilter.GaussianBlur(radius=0.6))
    return image.convert("RGB")


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------
def to_json(receipt, file_name):
    """Ground truth: exactly what is printed on the receipt. Money as strings."""
    return {
        "file": file_name,
        "vendor": receipt["vendor"]["name"],
        "date": receipt["date"].isoformat(),
        "receipt_number": receipt["receipt_number"],
        "lines": [
            {
                "description": line["description"],
                "quantity": format_qty(line["quantity"]),
                "unit": line["unit"],
                "unit_price": str(line["unit_price"]),
                "line_total": str(line["line_total"]),
            }
            for line in receipt["lines"]
        ],
        "subtotal": str(receipt["subtotal"]),
        "tax": str(receipt["tax"]),
        "total": str(receipt["total"]),
        "deliberate_errors": receipt["deliberate_errors"],
    }


def save(image, data, out_dir, stem, ext):
    file_name = f"{stem}.{ext}"
    if ext == "jpg":
        image.save(out_dir / file_name, "JPEG", quality=85)
    else:
        image.save(out_dir / file_name, "PNG")
    data["file"] = file_name
    (out_dir / f"{stem}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def generate(out_dir=config.SAMPLE_DIR, seed=SEED):
    """Write all sample receipts into out_dir. Returns the number of receipts."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Remove old generated files so the folder always matches this script
    for old in out_dir.glob("receipt_*.*"):
        old.unlink()

    rng = random.Random(seed)
    receipts = build_receipts(rng)
    add_deliberate_errors(receipts)

    number = 0
    for receipt in receipts:
        number += 1
        ext = "png" if number % 3 == 0 else "jpg"   # mix of formats
        image = draw_receipt(receipt, rng)
        save(image, to_json(receipt, ""), out_dir, f"receipt_{number:03d}", ext)

    # Duplicate 1: the same paper receipt photographed again (new image, new hash)
    original = receipts[10]
    number += 1
    data = to_json(original, "")
    data["deliberate_errors"] = original["deliberate_errors"] + ["duplicate_receipt"]
    data["duplicate_of"] = "receipt_011"
    save(draw_receipt(original, rng, angle=-2.0), data, out_dir, f"receipt_{number:03d}", "png")

    # Duplicate 2: an exact copy of an existing file (same bytes, same hash)
    number += 1
    source_stem = "receipt_007"
    source_image = next(
        p for p in out_dir.glob(f"{source_stem}.*") if p.suffix in (".png", ".jpg")
    )
    copy_name = f"receipt_{number:03d}{source_image.suffix}"
    shutil.copyfile(source_image, out_dir / copy_name)
    data = json.loads((out_dir / f"{source_stem}.json").read_text(encoding="utf-8"))
    data["file"] = copy_name
    data["deliberate_errors"] = data["deliberate_errors"] + ["duplicate_file"]
    data["duplicate_of"] = source_stem
    (out_dir / f"receipt_{number:03d}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    return number


if __name__ == "__main__":
    total = generate()
    print(f"Wrote {total} sample receipts to {config.SAMPLE_DIR}")
