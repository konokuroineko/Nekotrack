from functools import lru_cache
from pathlib import Path
import sys

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


def resource_path(relative_path):
    """Resolve assets from both a source checkout and a PyInstaller one-file build."""
    bundle_root = getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])
    return Path(bundle_root) / relative_path


def _render_svg(svg_text, size):
    renderer = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    if not renderer.isValid():
        return pixmap

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    return pixmap


@lru_cache(maxsize=1)
def _logo_svg():
    return resource_path("assets/nekotrack-logo.svg").read_text(encoding="utf-8")


@lru_cache(maxsize=4)
def logo_pixmap(size=128):
    """Render the shared vector logo for the sidebar and setup wizard."""
    return _render_svg(_logo_svg(), max(16, int(size)))


@lru_cache(maxsize=1)
def application_icon():
    """Return a multi-resolution app icon from the same source logo."""
    icon = QIcon()
    svg = _logo_svg()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = _render_svg(svg, size)
        if not pixmap.isNull():
            icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.Off)
    return icon


_NAV_DRAWINGS = {
    "home": (
        '<path d="M3.5 10.5 12 3.8l8.5 6.7"/>'
        '<path d="M5.7 9.1v10.4c0 .6.5 1.1 1.1 1.1h4v-6h2.4v6h4c.6 0 1.1-.5 1.1-1.1V9.1"/>'
    ),
    "library": (
        '<path d="M4.2 5.2c0-.8.6-1.4 1.4-1.4h5.1c.7 0 1.3.6 1.3 1.4v15.3c0-.7-.5-1.2-1.3-1.2H5.6c-.8 0-1.4.5-1.4 1.2Z"/>'
        '<path d="M12.8 5.2c0-.8.6-1.4 1.4-1.4h.2l5.1 1.5c.7.2 1.1.9.9 1.6l-3.4 13.2c-.2.7-.9 1.1-1.6.9l-2.6-.7"/>'
        '<path d="M6.7 7.4h3.2M6.7 10.1h3.2"/>'
    ),
    "search": (
        '<circle cx="10.7" cy="10.7" r="6.4"/>'
        '<path d="m15.4 15.4 5 5"/>'
    ),
    "settings": (
        '<path d="M4 6.2h5.3m3.4 0H20M4 12h2.4m3.4 0H20M4 17.8h8.1m3.4 0H20"/>'
        '<circle cx="10.4" cy="6.2" r="1.7"/>'
        '<circle cx="7.5" cy="12" r="1.7"/>'
        '<circle cx="13.8" cy="17.8" r="1.7"/>'
    ),
}


@lru_cache(maxsize=64)
def navigation_icon(name, color, size=24):
    """Render a clean, consistent outline icon for a navigation button."""
    drawing = _NAV_DRAWINGS.get(name)
    if drawing is None:
        return QIcon()

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
        f'<g fill="none" stroke="{color}" stroke-width="1.8" '
        f'stroke-linecap="round" stroke-linejoin="round">{drawing}</g></svg>'
    )
    pixmap = _render_svg(svg, max(16, int(size) * 2))
    pixmap.setDevicePixelRatio(2)
    icon = QIcon()
    icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.Off)
    return icon
