"""Tests for joining several photos of one long receipt (src/stitch.py)."""

import io

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from src import config, ingest, stitch
from src.run_pipeline import process_multi_image
from tests.helpers import image_bytes

SAMPLE = config.SAMPLE_DIR / "receipt_003.png"


def size_of(data):
    with Image.open(io.BytesIO(data)) as image:
        return image.format, image.size


def split_in_two(path):
    """Cut a sample receipt into a top and a bottom photo (no overlap)."""
    with Image.open(path) as image:
        image = image.convert("RGB")
        middle = image.height // 2
        parts = []
        for box in [(0, 0, image.width, middle), (0, middle, image.width, image.height)]:
            buffer = io.BytesIO()
            image.crop(box).save(buffer, "PNG")
            parts.append((buffer.getvalue(), "part.png"))
    return parts


def test_photos_are_stacked_top_to_bottom():
    parts = [(image_bytes("JPEG", size=(400, 200)), "a.jpg"),
             (image_bytes("PNG", size=(400, 300)), "b.png")]
    fmt, (width, height) = size_of(stitch.stitch_images(parts))
    assert fmt == "JPEG"
    assert (width, height) == (400, 500)


def test_different_widths_are_scaled_to_the_same_width():
    parts = [(image_bytes("JPEG", size=(400, 200)), "a.jpg"),
             (image_bytes("JPEG", size=(200, 100)), "b.jpg")]      # half width -> scaled up x2
    assert size_of(stitch.stitch_images(parts))[1] == (400, 400)


def test_very_wide_photos_are_capped():
    parts = [(image_bytes("JPEG", size=(4000, 1000)), "a.jpg"),
             (image_bytes("JPEG", size=(4000, 1000)), "b.jpg")]
    assert size_of(stitch.stitch_images(parts))[1] == (2000, 1000)


def test_result_stays_inside_pixel_limit(monkeypatch):
    monkeypatch.setattr(ingest, "MAX_PIXELS", 100_000)
    parts = [(image_bytes("JPEG", size=(400, 200)), "a.jpg"),
             (image_bytes("JPEG", size=(400, 200)), "b.jpg")]
    width, height = size_of(stitch.stitch_images(parts))[1]
    assert width * height <= 100_000


def test_phone_rotation_is_applied():
    # A 300x100 photo whose EXIF says "rotate 90°" is really 100x300 when upright
    buffer = io.BytesIO()
    exif = Image.Exif()
    exif[0x0112] = 6                                    # Orientation: rotate 90° clockwise
    Image.new("RGB", (300, 100), "white").save(buffer, "JPEG", exif=exif)
    parts = [(buffer.getvalue(), "phone.jpg"), (image_bytes("JPEG", size=(100, 50)), "b.jpg")]
    assert size_of(stitch.stitch_images(parts))[1] == (100, 350)


def test_bad_part_is_named():
    parts = [(image_bytes("JPEG"), "a.jpg"), (b"not an image", "b.jpg")]
    with pytest.raises(stitch.StitchError, match="photo 2: not a valid image"):
        stitch.stitch_images(parts)


def test_needs_two_to_ten_photos():
    with pytest.raises(stitch.StitchError):
        stitch.stitch_images([(image_bytes(), "a.jpg")])
    with pytest.raises(stitch.StitchError):
        stitch.stitch_images([(image_bytes(), "a.jpg")] * 11)


def test_same_photos_give_same_image():
    parts = [(image_bytes("JPEG", color=(1, 2, 3)), "a.jpg"), (image_bytes("JPEG"), "b.jpg")]
    assert stitch.stitch_images(parts) == stitch.stitch_images(parts)


# --- whole flow (test database, real OCR) ------------------------------------------------
def test_receipt_in_two_photos_is_read_as_one(db_conn, tmp_path):
    result = process_multi_image(db_conn, split_in_two(SAMPLE), "upload", raw_dir=tmp_path)
    assert result["status"] == "new"
    assert db_conn.execute("SELECT count(*) FROM clean.receipt").fetchone()[0] == 1
    number, total, lines = db_conn.execute(
        "SELECT receipt_number, total, (SELECT count(*) FROM clean.receipt_line) FROM clean.receipt"
    ).fetchone()
    assert number == "HF-10210"                 # from the top photo
    assert total is not None                    # from the bottom photo
    assert lines == 5                           # all lines of the original receipt
    name = db_conn.execute("SELECT original_name FROM raw.receipt_file").fetchone()[0]
    assert name == "long_receipt_2_photos.jpg"


def test_same_photos_again_is_a_duplicate(db_conn, tmp_path):
    parts = split_in_two(SAMPLE)
    first = process_multi_image(db_conn, parts, "camera", raw_dir=tmp_path)
    second = process_multi_image(db_conn, parts, "camera", raw_dir=tmp_path)
    assert second["status"] == "duplicate"
    assert second["receipt_id"] == first["receipt_id"]


def test_bad_part_rejects_the_receipt(db_conn, tmp_path):
    result = process_multi_image(db_conn, [(image_bytes(), "a.jpg"), (b"x", "b.gif")], "upload",
                                 raw_dir=tmp_path)
    assert result["status"] == "rejected"
    assert result["reason"] == "photo 2: not a JPG or PNG file"
    assert db_conn.execute("SELECT count(*) FROM raw.receipt_file").fetchone()[0] == 0


def test_add_receipt_page_offers_long_receipt_mode(db_conn):
    app = AppTest.from_file(str(config.PROJECT_ROOT / "app" / "pages" / "1_Add_Receipt.py"))
    app.session_state["role"] = "developer"
    app.run()
    assert not app.exception
    assert "Several photos = one long receipt" in app.radio[0].options
    app.radio(key="upload_mode").set_value("Several photos = one long receipt").run()
    assert not app.exception
