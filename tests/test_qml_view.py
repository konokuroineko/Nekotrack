"""Headless smoke test for the production QML Library view."""
import os
from pathlib import Path
import unittest

# CI runners have no desktop session; choose a headless renderer before the
# first QApplication is created.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QUrl
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication

from ui.qml_bridge import QmlApplicationBridge


ROOT = Path(__file__).resolve().parents[1]


class QmlLibraryViewSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.bridge = QmlApplicationBridge(
            library_loader=lambda: [],
            auto_refresh=False,
        )

    def test_production_library_qml_loads_with_the_python_bridge(self):
        widget = QQuickWidget()
        self.addCleanup(widget.deleteLater)
        widget.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        widget.rootContext().setContextProperty("qmlBridge", self.bridge)
        qml_path = ROOT / "ui" / "qml" / "LibraryView.qml"
        widget.setSource(QUrl.fromLocalFile(str(qml_path)))

        self.app.processEvents()
        self.assertEqual(
            widget.status(),
            QQuickWidget.Status.Ready,
            "\n".join(error.toString() for error in widget.errors()),
        )
        self.assertIsNotNone(widget.rootObject())


if __name__ == "__main__":
    unittest.main()
