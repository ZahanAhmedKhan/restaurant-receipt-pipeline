"""Small helpers shared by several test files."""

import io

from PIL import Image


def image_bytes(fmt="JPEG", size=(200, 300), color=(240, 240, 240)):
    """Make a small in-memory image and return its bytes."""
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, fmt)
    return buffer.getvalue()
