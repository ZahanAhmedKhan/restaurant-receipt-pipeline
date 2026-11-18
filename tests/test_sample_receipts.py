"""Checks on the generated fake receipts in data/sample/."""

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal

import pytest
from PIL import Image

from scripts.make_sample_receipts import generate
from src import config

SAMPLE_JSON = sorted(config.SAMPLE_DIR.glob("receipt_*.json"))


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def lines_sum(data):
    return sum(Decimal(line["line_total"]) for line in data["lines"])


def test_sample_folder_has_51_receipts():
    assert len(SAMPLE_JSON) == 51


@pytest.mark.parametrize("path", SAMPLE_JSON, ids=lambda p: p.stem)
def test_each_json_has_an_image_that_opens(path):
    data = load(path)
    image_path = config.SAMPLE_DIR / data["file"]
    assert image_path.exists()
    with Image.open(image_path) as image:
        assert image.format in ("PNG", "JPEG")


@pytest.mark.parametrize("path", SAMPLE_JSON, ids=lambda p: p.stem)
def test_each_line_total_is_qty_times_price(path):
    for line in load(path)["lines"]:
        amount = Decimal(line["quantity"]) * Decimal(line["unit_price"])
        # Receipts round half up (0.005 -> 0.01), like a till
        expected = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert Decimal(line["line_total"]) == expected


@pytest.mark.parametrize("path", SAMPLE_JSON, ids=lambda p: p.stem)
def test_totals_add_up_except_deliberate_errors(path):
    data = load(path)
    errors = data["deliberate_errors"]
    subtotal = Decimal(data["subtotal"])
    tax = Decimal(data["tax"])
    total = Decimal(data["total"])

    if "lines_dont_match_subtotal" in errors:
        assert lines_sum(data) != subtotal
    else:
        assert lines_sum(data) == subtotal

    if "wrong_total" in errors:
        assert subtotal + tax != total
    else:
        assert subtotal + tax == total


def test_expected_number_of_deliberate_errors():
    all_errors = [e for path in SAMPLE_JSON for e in load(path)["deliberate_errors"]]
    assert all_errors.count("wrong_total") == 3
    assert all_errors.count("lines_dont_match_subtotal") == 1
    assert all_errors.count("duplicate_receipt") == 1
    assert all_errors.count("duplicate_file") == 1
    assert all_errors.count("not_canadian") == 1


def test_duplicate_file_has_same_hash_as_original():
    for path in SAMPLE_JSON:
        data = load(path)
        if "duplicate_file" in data["deliberate_errors"]:
            original = load(config.SAMPLE_DIR / f"{data['duplicate_of']}.json")
            copy_bytes = (config.SAMPLE_DIR / data["file"]).read_bytes()
            original_bytes = (config.SAMPLE_DIR / original["file"]).read_bytes()
            assert hashlib.sha256(copy_bytes).digest() == hashlib.sha256(original_bytes).digest()


def test_generator_is_repeatable(tmp_path):
    """Running the generator again gives identical ground truth."""
    count = generate(out_dir=tmp_path)
    assert count == 51
    for path in SAMPLE_JSON:
        assert load(tmp_path / path.name) == load(path)
