"""Launch the isolated Qt Quick prototype without changing the production app.

Run from the repository root with the same Python environment used by NekoTrack:
    python experiments/qml_preview.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine


def main() -> int:
    qml_directory = Path(__file__).resolve().parent / "qml"
    main_qml = qml_directory / "Main.qml"
    if not main_qml.is_file():
        print(f"QML preview entry point was not found: {main_qml}", file=sys.stderr)
        return 2

    app = QGuiApplication(sys.argv)
    app.setApplicationName("NekoTrack QML Preview")
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(qml_directory))
    engine.load(QUrl.fromLocalFile(str(main_qml)))

    if not engine.rootObjects():
        print("The QML preview failed to load. Review the Qt/QML errors above.", file=sys.stderr)
        return 1

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
