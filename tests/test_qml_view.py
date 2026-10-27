"""Headless smoke test for the production QML Library view."""
import os
os.environ.setdefault("QT_QUICK_BACKEND", "software")
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
from ui.qml_app_bridge import ApplicationBridge


ROOT = Path(__file__).resolve().parents[1]


class QmlLibraryViewSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.bridge = QmlApplicationBridge(
            library_loader=lambda: [],
            auto_refresh=False,
        )

    def _load_qml(self, file_name, bridge):
        widget = QQuickWidget()
        self.addCleanup(widget.deleteLater)
        widget.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        # Prevent Qt Quick's default process exit on renderer errors in headless CI.
        scene_graph_errors = []
        scene_graph_error = getattr(widget, "sceneGraphError", None)
        if scene_graph_error is not None:
            scene_graph_error.connect(
                lambda error, message: scene_graph_errors.append((error, message))
            )
        context = widget.rootContext()
        context.setContextProperty("qmlBridge", bridge)
        context.setContextProperty("appBridge", bridge)
        qml_path = ROOT / "ui" / "qml" / file_name
        widget.setSource(QUrl.fromLocalFile(str(qml_path)))
        self.app.processEvents()
        self.assertEqual(
            widget.status(),
            QQuickWidget.Status.Ready,
            "\n".join(error.toString() for error in widget.errors()),
        )
        self.assertIsNotNone(widget.rootObject())
        return widget

    def test_production_library_qml_loads_with_the_python_bridge(self):
        self._load_qml("LibraryView.qml", self.bridge)

    def test_production_application_shell_loads_with_the_application_bridge(self):
        bridge = ApplicationBridge()
        self.addCleanup(bridge.deleteLater)
        self._load_qml("ApplicationShell.qml", bridge)


if __name__ == "__main__":
    unittest.main()
