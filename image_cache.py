"""Bounded and path-safe cover-image downloads for NekoTrack."""
from pathlib import Path
import ipaddress
import tempfile
import re
from urllib.parse import urljoin, urlsplit

import requests
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImageReader


IMAGE_DIRECTORY = Path("data") / "images" / "works"
MAX_COVER_BYTES = 20 * 1024 * 1024
MAX_COVER_WIDTH = 8192
MAX_COVER_HEIGHT = 8192
MAX_COVER_PIXELS = 32_000_000
MAX_WORK_ID_TEXT_LENGTH = 20
MAX_COVER_REDIRECTS = 5


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
    host = (parsed.hostname or "").casefold().rstrip(".")
    if (
        parsed.scheme.casefold() != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.fragment
        or host == "localhost"
        or host.endswith((".localhost", ".local", ".internal"))
    ):
        raise ValueError("Cover images must use a valid public HTTPS URL.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Cover images cannot use private or local IP addresses.")
    return value.strip()


def _open_cover_response(start_url):
    """Follow redirects only after validating each destination URL."""
    url = start_url
    redirect_codes = {301, 302, 303, 307, 308}
    for _ in range(MAX_COVER_REDIRECTS + 1):
        response = requests.get(
            url,
            timeout=15,
            stream=True,
            allow_redirects=False,
        )
        status_code = getattr(response, "status_code", None)
        if status_code in redirect_codes:
            headers = getattr(response, "headers", None) or {}
            location = headers.get("Location")
            response.close()
            if not isinstance(location, str) or not location.strip():
                raise ValueError("The image server returned a redirect without a location.")
            url = _safe_image_url(urljoin(url, location.strip()))
            continue

        try:
            response.raise_for_status()
            final_url = getattr(response, "url", None) or url
            _safe_image_url(final_url)
        except Exception:
            # This function returns a live streamed response to its caller.
            # If status or final-URL validation fails before that handoff, no
            # caller context manager exists yet to close the socket.
            response.close()
            raise
        return response

    raise ValueError("The cover image download exceeded the redirect limit.")


def _download_payload(image_url):
    with _open_cover_response(image_url) as response:
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

    try:
        reader = QImageReader(buffer)
        reader.setDecideFormatFromContent(True)
        dimensions = reader.size()
        if not dimensions.isValid():
            raise ValueError("The cover image dimensions are invalid.")
        width, height = dimensions.width(), dimensions.height()
        if (
            width <= 0
            or height <= 0
            or width > MAX_COVER_WIDTH
            or height > MAX_COVER_HEIGHT
            or width * height > MAX_COVER_PIXELS
        ):
            raise ValueError("The cover image dimensions are too large.")
        image = reader.read()
    finally:
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
    temporary_path = None
    try:
        # Write to a separate file and atomically replace the cache entry only
        # after Qt has completed the JPEG successfully. This prevents a failed
        # write or simultaneous downloads from leaving a truncated cache hit.
        with tempfile.NamedTemporaryFile(
            prefix=f".{safe_id}-",
            suffix=".jpg",
            dir=IMAGE_DIRECTORY,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)

        if not image.save(str(temporary_path), "JPG", 85):
            raise OSError("Could not save cover image")

        temporary_path.replace(image_path)
        return str(image_path)
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
