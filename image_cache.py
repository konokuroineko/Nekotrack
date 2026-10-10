"""Bounded and path-safe cover-image downloads for NekoTrack."""
from pathlib import Path
import re
from urllib.parse import urlsplit

import requests
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QImageReader


IMAGE_DIRECTORY = Path("data") / "images" / "works"
MAX_COVER_BYTES = 20 * 1024 * 1024
MAX_COVER_WIDTH = 8192
MAX_COVER_HEIGHT = 8192
MAX_COVER_PIXELS = 32_000_000
MAX_WORK_ID_TEXT_LENGTH = 20


def _safe_work_id(value):
    """Return a filename-safe signed numeric ID (negative MangaBaka IDs are valid)."""
    if isinstance(value, bool):
        raise ValueError("A cover must have a numeric work ID.")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str):
        text = value.strip()
        if len(text) > MAX_WORK_ID_TEXT_LENGTH or not re.fullmatch(r"-?[1-9][0-9]*", text):
            raise ValueError("A cover must have a non-zero numeric work ID.")
        number = int(text)
    else:
        raise ValueError("A cover must have a numeric work ID.")

    if number == 0 or not -(2**63) <= number <= (2**63 - 1):
        raise ValueError("A cover work ID is outside the supported range.")
    return str(number)


def _safe_image_url(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A cover image URL is required.")
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except (TypeError, ValueError):
        raise ValueError("The cover image URL is invalid.")
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.fragment
    ):
        raise ValueError("Cover images must use a valid HTTPS URL.")
    return value.strip()


def _download_payload(image_url):
    with requests.get(image_url, timeout=15, stream=True) as response:
        response.raise_for_status()
        headers = getattr(response, "headers", None) or {}
        raw_length = headers.get("Content-Length")
        if raw_length not in (None, ""):
            try:
                declared_length = int(raw_length)
            except (TypeError, ValueError, OverflowError):
                raise ValueError("The image server returned an invalid content length.")
            if declared_length < 0:
                raise ValueError("The image server returned an invalid content length.")
            if declared_length > MAX_COVER_BYTES:
                raise ValueError("The cover image exceeds the 20 MiB size limit.")

        chunks = []
        byte_count = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            if not isinstance(chunk, (bytes, bytearray)):
                raise ValueError("The image server returned invalid image data.")
            byte_count += len(chunk)
            if byte_count > MAX_COVER_BYTES:
                raise ValueError("The cover image exceeded the 20 MiB download limit.")
            chunks.append(bytes(chunk))
    if not chunks:
        raise ValueError("The downloaded cover image is empty.")
    return b"".join(chunks)


def _decode_cover(payload):
    buffer = QBuffer()
    buffer.setData(QByteArray(payload))
    if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
        raise ValueError("Could not open the downloaded cover image.")

    reader = QImageReader(buffer)
    reader.setDecideFormatFromContent(True)
    dimensions = reader.size()
    if dimensions.isValid():
        width, height = dimensions.width(), dimensions.height()
        if (
            width <= 0
            or height <= 0
            or width > MAX_COVER_WIDTH
            or height > MAX_COVER_HEIGHT
            or width * height > MAX_COVER_PIXELS
        ):
            buffer.close()
            raise ValueError("The cover image dimensions are too large.")
    image = reader.read()
    buffer.close()
    if image.isNull():
        raise ValueError("Downloaded cover is not a supported image.")
    return image


def download_cover(work_id, image_url):
    """Download, validate, resize, and save one cover without unsafe paths or unbounded payloads."""

    safe_id = _safe_work_id(work_id)
    safe_url = _safe_image_url(image_url)
    payload = _download_payload(safe_url)
    image = _decode_cover(payload)
    image = image.scaled(
        400,
        600,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

    IMAGE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    image_path = IMAGE_DIRECTORY / f"{safe_id}.jpg"

    if not image.save(str(image_path), "JPG", 85):
        raise OSError("Could not save cover image")

    return str(image_path)
