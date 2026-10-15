"""Shared display-identity lookup and safe custom-cover storage."""

import hashlib
import os
import tempfile
from functools import lru_cache
from pathlib import Path

from PySide6.QtGui import QImageReader

from database import get_work_display_override

MAX_CUSTOM_COVER_BYTES = 20 * 1024 * 1024
MAX_CUSTOM_COVER_WIDTH = 8192
MAX_CUSTOM_COVER_HEIGHT = 8192
MAX_CUSTOM_COVER_PIXELS = 32_000_000
_ALLOWED_FORMATS = {"png", "jpg", "jpeg", "webp", "bmp"}
_FORMAT_EXTENSIONS = {
    "png": "png",
    "jpg": "jpg",
    "jpeg": "jpg",
    "webp": "webp",
    "bmp": "bmp",
}


@lru_cache(maxsize=4096)
def get_display_override(work_id):
    """Cache safe overrides so each poster card does not open SQLite repeatedly."""
    try:
        return get_work_display_override(work_id) or {}
    except Exception:
        return {}


def invalidate_display_override(work_id=None):
    """Clear one identity entry, or all cached entries after global preference changes."""
    if work_id is None:
        get_display_override.cache_clear()
        return
    try:
        get_display_override.cache_clear()
    except Exception:
        pass


def copy_custom_cover(source_path):
    """Validate and atomically copy selected artwork into app-owned storage."""
    source = Path(str(source_path or "")).expanduser()
    if not source.is_file():
        raise ValueError("Select an existing image file.")
    try:
        stat = source.stat()
        if stat.st_size <= 0 or stat.st_size > MAX_CUSTOM_COVER_BYTES:
            raise ValueError("Custom cover images must be between 1 byte and 20 MiB.")
        reader = QImageReader(str(source))
        reader.setDecideFormatFromContent(True)
        dimensions = reader.size()
        if not reader.canRead() or not dimensions.isValid():
            raise ValueError("The selected file is not a supported image.")
        width, height = dimensions.width(), dimensions.height()
        if (
            width <= 0
            or height <= 0
            or width > MAX_CUSTOM_COVER_WIDTH
            or height > MAX_CUSTOM_COVER_HEIGHT
            or width * height > MAX_CUSTOM_COVER_PIXELS
        ):
            raise ValueError("The image dimensions exceed NekoTrack's safety limits.")
        image_format = bytes(reader.format()).decode("ascii", errors="ignore").lower()
        if image_format not in _ALLOWED_FORMATS:
            raise ValueError("Use PNG, JPG, WEBP, or BMP artwork.")
        if reader.read().isNull():
            raise ValueError("NekoTrack could not decode the selected image.")
        payload = source.read_bytes()
    except (OSError, RuntimeError) as error:
        raise ValueError(f"The selected cover could not be read: {error}") from error

    digest = hashlib.sha256(payload).hexdigest()
    storage_directory = (Path.cwd() / "data" / "display_overrides").resolve()
    storage_directory.mkdir(parents=True, exist_ok=True)
    destination = storage_directory / f"{digest}.{_FORMAT_EXTENSIONS[image_format]}"
    if not destination.exists():
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=storage_directory,
                prefix=".nekotrack-cover-",
                suffix=".part",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, destination)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink(missing_ok=True)
    return destination.relative_to(Path.cwd().resolve()).as_posix()


__all__ = ["copy_custom_cover", "get_display_override", "invalidate_display_override"]
