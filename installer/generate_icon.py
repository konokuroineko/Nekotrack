"""Generate a Windows .ico file from the shared NekoTrack SVG logo.

Uses Qt's SVG renderer and writes PNG-backed ICO frames without Pillow or other
image-conversion dependencies. Run from any working directory.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


ROOT = Path(__file__).resolve().parents[1]
SVG_PATH = ROOT / "assets" / "nekotrack-logo.svg"
ICO_PATH = ROOT / "assets" / "NekoTrack.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def render_png(renderer, size):
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()

    encoded = QByteArray()
    buffer = QBuffer(encoded)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError("Could not create an in-memory PNG buffer.")
    try:
        if not image.save(buffer, "PNG"):
            raise OSError(f"Qt could not render the {size}px icon frame.")
    finally:
        buffer.close()
    return bytes(encoded)


def build_ico():
    if not SVG_PATH.is_file():
        raise FileNotFoundError(f"Logo SVG not found: {SVG_PATH}")

    app = QGuiApplication.instance() or QGuiApplication([sys.argv[0]])
    del app
    renderer = QSvgRenderer(str(SVG_PATH))
    if not renderer.isValid():
        raise ValueError(f"Logo SVG is invalid: {SVG_PATH}")

    frames = [(size, render_png(renderer, size)) for size in SIZES]
    directory_size = 6 + 16 * len(frames)
    offset = directory_size
    entries = []
    payloads = []

    for size, png in frames:
        dimension = 0 if size == 256 else size
        entries.append(
            struct.pack(
                "<BBBBHHII",
                dimension,  # Width; 0 encodes 256 pixels.
                dimension,  # Height; 0 encodes 256 pixels.
                0,          # No palette.
                0,          # Reserved.
                1,          # Planes.
                32,         # Bits per pixel.
                len(png),
                offset,
            )
        )
        payloads.append(png)
        offset += len(png)

    ICO_PATH.parent.mkdir(parents=True, exist_ok=True)
    ICO_PATH.write_bytes(
        struct.pack("<HHH", 0, 1, len(frames))
        + b"".join(entries)
        + b"".join(payloads)
    )
    print(f"Generated {ICO_PATH} ({ICO_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    build_ico()
