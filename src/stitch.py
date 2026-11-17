"""Join several photos of ONE long receipt into a single tall image
(like a document scanner app does), so it is read as one receipt.

Photos are joined top to bottom in the order given. The result is then
ingested like any other image (validation + duplicate check still apply).
"""

import io

from PIL import Image, ImageOps

from src import ingest

MAX_WIDTH = 2000          # wider than this only makes the file bigger, not more readable
JPEG_QUALITY = 90
MAX_PARTS = 10


class StitchError(Exception):
    """One of the parts is not acceptable; the message says which and why."""


def check_parts(parts):
    """parts: list of (bytes, original_name). Raise StitchError for any bad part."""
    if len(parts) < 2:
        raise StitchError("a long receipt needs at least 2 photos")
    if len(parts) > MAX_PARTS:
        raise StitchError(f"at most {MAX_PARTS} photos per receipt")
    for number, (data, name) in enumerate(parts, start=1):
        _, reason = ingest.validate_image(data, name)
        if reason:
            raise StitchError(f"photo {number}: {reason}")


def open_upright(data):
    """Open an image and turn it the right way up (phones store rotation in EXIF)."""
    with Image.open(io.BytesIO(data)) as image:
        upright = ImageOps.exif_transpose(image)
        return upright.convert("RGB")


def stitch_images(parts):
    """Join the photos top to bottom. Returns JPEG bytes.

    parts: list of (bytes, original_name), in reading order (top of receipt first).
    """
    check_parts(parts)
    images = [open_upright(data) for data, _ in parts]

    # Same width for every part: the widest photo, but not more than MAX_WIDTH
    width = min(max(image.width for image in images), MAX_WIDTH)
    resized = []
    for image in images:
        height = round(image.height * width / image.width)
        resized.append(image.resize((width, height), Image.LANCZOS))

    total_height = sum(image.height for image in resized)
    sheet = Image.new("RGB", (width, total_height), "white")
    top = 0
    for image in resized:
        sheet.paste(image, (0, top))
        top += image.height

    # Stay inside the limits that ingestion enforces
    if width * total_height > ingest.MAX_PIXELS:
        scale = (ingest.MAX_PIXELS / (width * total_height)) ** 0.5
        sheet = sheet.resize((int(width * scale), int(total_height * scale)), Image.LANCZOS)
    return _to_jpeg_under_limit(sheet)


def _to_jpeg_under_limit(image):
    """Save as JPEG; lower the quality step by step if it is over 10 MB."""
    quality = JPEG_QUALITY
    while True:
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=quality)
        data = buffer.getvalue()
        if len(data) <= ingest.MAX_BYTES or quality <= 50:
            return data
        quality -= 10
