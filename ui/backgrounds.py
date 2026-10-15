"""Persistent user-selected backgrounds and the shared app-wide canvas."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QObject, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from diagnostics import log_event, log_exception
from ui.preferences import get, set_value
from ui.theme import COLORS

MAX_BACKGROUND_BYTES = 20 * 1024 * 1024
MAX_BACKGROUND_WIDTH = 8192
MAX_BACKGROUND_HEIGHT = 8192
MAX_BACKGROUND_PIXELS = 32_000_000
SUPPORTED_FORMATS = {"png", "jpg", "jpeg", "webp", "bmp"}
FORMAT_EXTENSIONS = {"png": "png", "jpg": "jpg", "jpeg": "jpg", "webp": "webp", "bmp": "bmp"}
SLIDESHOW_INTERVALS = (-1, 0, 30, 60, 300, 900, 1800)


def _image_from_bytes(payload):
    """Decode safely only after limiting file bytes, decoded dimensions, and format."""
    if not isinstance(payload, (bytes, bytearray)) or not payload:
        raise ValueError("The file is empty or is not valid image data.")
    if len(payload) > MAX_BACKGROUND_BYTES:
        raise ValueError("Images must be no larger than 20 MiB.")
    buffer = QBuffer()
    buffer.setData(QByteArray(bytes(payload)))
    if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
        raise ValueError("The selected image could not be opened.")
    try:
        reader = QImageReader(buffer)
        reader.setDecideFormatFromContent(True)
        dimensions = reader.size()
        if not dimensions.isValid() or not reader.canRead():
            raise ValueError("The file is not a supported image.")
        width, height = dimensions.width(), dimensions.height()
        if (width <= 0 or height <= 0 or width > MAX_BACKGROUND_WIDTH
                or height > MAX_BACKGROUND_HEIGHT or width * height > MAX_BACKGROUND_PIXELS):
            raise ValueError("Image dimensions exceed NekoTrack's safety limits.")
        image_format = bytes(reader.format()).decode("ascii", errors="ignore").lower()
        if image_format not in SUPPORTED_FORMATS:
            raise ValueError("Use a PNG, JPG, WEBP, or BMP image that Qt can decode.")
        image = reader.read()
        if image.isNull():
            raise ValueError("NekoTrack could not decode the selected image.")
        return image, image_format
    finally:
        buffer.close()


class BackgroundManager(QObject):
    """Own the chosen image set, active image, persistent settings, and one slideshow timer."""

    background_changed = Signal()
    images_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._working_directory = Path.cwd().resolve()
        self.storage_directory = (self._working_directory / "data" / "backgrounds").resolve()
        self.storage_directory.mkdir(parents=True, exist_ok=True)
        self._paths = []
        self._index = 0
        self._pixmap = QPixmap()
        self.last_errors = []
        self._interval = self._valid_interval(get("background_slideshow_interval"))
        self._overlay_opacity = self._valid_opacity(get("background_overlay_opacity"))
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.timeout.connect(self._advance)
        self._load_saved_paths()
        self._refresh_pixmap()
        self._restart_timer()

    @staticmethod
    def _valid_interval(value):
        try:
            value = int(value)
        except (TypeError, ValueError, OverflowError):
            return -1
        return value if value in SLIDESHOW_INTERVALS else -1

    @staticmethod
    def _valid_opacity(value):
        try:
            value = int(value)
        except (TypeError, ValueError, OverflowError):
            return 62
        return max(35, min(90, value))

    @property
    def paths(self):
        return tuple(self._paths)

    @property
    def interval(self):
        return self._interval

    @property
    def overlay_opacity(self):
        return self._overlay_opacity

    @property
    def selected_path(self):
        return self._paths[self._index] if self._paths else None

    @property
    def display_pixmap(self):
        return None if self._interval < 0 or self._pixmap.isNull() else self._pixmap

    def _resolve_managed_path(self, stored_path):
        if not isinstance(stored_path, str) or not stored_path.strip():
            return None
        candidate = Path(stored_path.strip())
        if not candidate.is_absolute():
            candidate = self._working_directory / candidate
        try:
            resolved = candidate.resolve()
            resolved.relative_to(self.storage_directory)
        except (OSError, ValueError, RuntimeError):
            return None
        return resolved if resolved.is_file() else None

    def _relative_path(self, path):
        try:
            return Path(path).resolve().relative_to(self._working_directory).as_posix()
        except (OSError, ValueError, RuntimeError):
            return None

    def _read_pixmap(self, path):
        try:
            path = Path(path)
            if not path.is_file() or path.stat().st_size > MAX_BACKGROUND_BYTES:
                return QPixmap()
            image, _fmt = _image_from_bytes(path.read_bytes())
            return QPixmap.fromImage(image)
        except (OSError, ValueError, RuntimeError) as error:
            log_event("background.image_unavailable", level=30, error_type=type(error).__name__,
                      error=str(error))
            return QPixmap()

    def _load_saved_paths(self):
        raw = get("background_image_paths_json")
        try:
            values = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError, ValueError):
            values = []
        if not isinstance(values, list):
            values = []
        cleaned = []
        for value in values:
            path = self._resolve_managed_path(value)
            if path is None or self._read_pixmap(path).isNull():
                continue
            stored = self._relative_path(path)
            if stored and stored not in cleaned:
                cleaned.append(stored)
        self._paths = cleaned
        if self._paths != values:
            self._persist_paths()
        self._index = 0

    def _persist_paths(self):
        set_value("background_image_paths_json", json.dumps(self._paths))

    def _refresh_pixmap(self):
        if not self._paths:
            self._index = 0
            self._pixmap = QPixmap()
        else:
            self._index = max(0, min(self._index, len(self._paths) - 1))
            path = self._resolve_managed_path(self._paths[self._index])
            self._pixmap = self._read_pixmap(path) if path else QPixmap()
        self.background_changed.emit()

    def _restart_timer(self):
        self._timer.stop()
        if self._interval > 0 and len(self._paths) > 1:
            self._timer.start(self._interval * 1000)

    def set_interval(self, value):
        self._interval = self._valid_interval(value)
        set_value("background_slideshow_interval", self._interval)
        self._restart_timer()
        self.background_changed.emit()

    def set_overlay_opacity(self, value):
        self._overlay_opacity = self._valid_opacity(value)
        set_value("background_overlay_opacity", self._overlay_opacity)
        self.background_changed.emit()

    def add_images(self, source_paths):
        """Validate and atomically copy files to managed per-user storage."""
        self.last_errors = []
        previous_path = self.selected_path
        added = 0
        for value in source_paths or []:
            source = Path(str(value)).expanduser()
            try:
                if not source.is_file():
                    raise ValueError("The selected file does not exist.")
                if source.stat().st_size > MAX_BACKGROUND_BYTES:
                    raise ValueError("Images must be no larger than 20 MiB.")
                payload = source.read_bytes()
                _image, image_format = _image_from_bytes(payload)
                digest = hashlib.sha256(payload).hexdigest()
                self.storage_directory.mkdir(parents=True, exist_ok=True)
                destination = self.storage_directory / f"{digest}.{FORMAT_EXTENSIONS[image_format]}"
                if not destination.exists():
                    temporary_path = None
                    try:
                        with tempfile.NamedTemporaryFile(mode="wb", dir=self.storage_directory,
                                                         prefix=".nekotrack-background-", suffix=".part",
                                                         delete=False) as handle:
                            temporary_path = Path(handle.name)
                            handle.write(payload)
                            handle.flush()
                            os.fsync(handle.fileno())
                        os.replace(temporary_path, destination)
                    finally:
                        if temporary_path is not None and temporary_path.exists():
                            temporary_path.unlink(missing_ok=True)
                stored = self._relative_path(destination)
                if stored is None:
                    raise ValueError("The image path is outside app storage.")
                if stored not in self._paths:
                    self._paths.append(stored)
                    added += 1
            except (OSError, ValueError, RuntimeError) as error:
                self.last_errors.append(f"{source.name}: {error}")
                log_event("background.image_rejected", level=30, filename=source.name,
                          error_type=type(error).__name__, error=str(error))
        if previous_path and previous_path in self._paths:
            self._index = self._paths.index(previous_path)
        elif self._paths:
            self._index = 0
        if added:
            self._persist_paths()
            self._refresh_pixmap()
            self._restart_timer()
            self.images_changed.emit()
        return added

    def remove_image(self, stored_path):
        if stored_path not in self._paths:
            return False
        try:
            index = self._paths.index(stored_path)
            self._paths.remove(stored_path)
            self._index = min(index, len(self._paths) - 1) if self._paths else 0
            self._persist_paths()
            self._refresh_pixmap()
            self._restart_timer()
            self.images_changed.emit()
            path = self._resolve_managed_path(stored_path)
            if path is not None:
                path.unlink(missing_ok=True)
            return True
        except (OSError, ValueError, RuntimeError) as error:
            log_exception("background.image_remove_failed", error)
            return False

    def _advance(self):
        """Skip missing or invalid files and advance without blocking the UI."""
        if self._interval <= 0 or len(self._paths) < 2:
            return
        for _ in range(len(self._paths)):
            self._index = (self._index + 1) % len(self._paths)
            stored = self._paths[self._index]
            path = self._resolve_managed_path(stored)
            pixmap = self._read_pixmap(path) if path else QPixmap()
            if not pixmap.isNull():
                self._pixmap = pixmap
                self.background_changed.emit()
                return
            self._paths.pop(self._index)
            self._index = 0 if not self._paths else self._index % len(self._paths)
            self._persist_paths()
            self.images_changed.emit()
        self._refresh_pixmap()
        self._restart_timer()

    def refresh_theme(self):
        self.background_changed.emit()


class BackgroundCanvas(QWidget):
    """Root widget painting a selected image and a theme-colored contrast overlay."""

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.setObjectName("appBackgroundCanvas")
        manager.background_changed.connect(self.update)

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor(COLORS["background"]))
        pixmap = self.manager.display_pixmap
        if pixmap is not None and not pixmap.isNull() and not self.rect().isEmpty():
            scaled = pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                   Qt.TransformationMode.SmoothTransformation)
            x = max(0, (scaled.width() - self.width()) // 2)
            y = max(0, (scaled.height() - self.height()) // 2)
            painter.drawPixmap(self.rect(), scaled, QRect(x, y, self.width(), self.height()))
            overlay = QColor(COLORS["background"])
            overlay.setAlpha(round(255 * self.manager.overlay_opacity / 100))
            painter.fillRect(self.rect(), overlay)
        painter.end()
