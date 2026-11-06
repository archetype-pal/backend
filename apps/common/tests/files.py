"""Test helper: the smallest valid image upload."""

from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image


def tiny_png(name: str = "logo.png", content_type: str = "image/png") -> SimpleUploadedFile:
    buf = BytesIO()
    Image.new("RGB", (1, 1)).save(buf, format="PNG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type=content_type)
