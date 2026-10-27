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


    def test_qml_cover_mask_keeps_legacy_crop_insets_and_separate_effect(self):
        source = (ROOT / "ui" / "qml" / "PosterCard.qml").read_text(encoding="utf-8")
        self.assertIn("fillMode: Image.PreserveAspectCrop", source)
        self.assertIn("smooth: true", source)
        self.assertIn("width: parent.width - 4", source)
        self.assertIn("height: parent.height - 4", source)
        self.assertIn("maskSource: coverMask", source)
        self.assertIn("source: cover", source)
        self.assertIn("border.width: 3", source)
        self.assertNotIn("layer.effect: MultiEffect", source)

    def test_qml_poster_keeps_original_width_ratio_and_title_fitting(self):
        source = (ROOT / "ui" / "qml" / "PosterCard.qml").read_text(encoding="utf-8")
        self.assertIn("Math.max(1, posterWidth - 4", source)
        self.assertIn('font.family: "Segoe UI"', source)
        self.assertIn("font.pixelSize: bridge.fontSize", source)
        self.assertIn('return first + "\\n" + second', source)
        self.assertIn("readonly property int posterWidth: bridge.cardSize", source)
        self.assertIn("readonly property int posterHeight: bridge.coverHeight", source)

    def test_production_library_qml_loads_with_the_python_bridge(self):
        self._load_qml("LibraryView.qml", self.bridge)


    def test_failed_qml_bridge_import_keeps_legacy_startup_available(self):
        from unittest.mock import patch
        from ui.main_window import MainWindow

        with patch("ui.main_window.ApplicationBridge", None), patch("ui.main_window.log_event"):
            self.assertFalse(MainWindow._install_qml_shell(object()))


    def test_qml_manage_actions_skip_duplicate_hidden_library_refreshes(self):
        library_source = (ROOT / "ui" / "pages" / "library_page.py").read_text(encoding="utf-8")
        main_source = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
        self.assertIn("def _delete_item(self, group, refresh=True)", library_source)
        self.assertIn("if deleted and refresh:", library_source)
        self.assertIn("def _edit_bundle(self, group, refresh=True)", library_source)
        self.assertIn("self.library_page._edit_bundle(group, refresh=False)", main_source)
        self.assertIn("self.library_page._delete_item(group, refresh=False)", main_source)
        self.assertIn("QTimer.singleShot(0, bridge.forceRefreshAll)", main_source)


    def test_qml_bundle_actions_wait_for_library_refresh_without_duplicate_detail_load(self):
        main_source = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
        self.assertIn("bridge.forceRefreshAll()", main_source)
        self.assertIn('if action == "customize_identity" and group is None:', main_source)
        self.assertIn("bridge.refreshSelectedWork()", main_source)


    def test_qml_library_route_preserves_deferred_relation_sync(self):
        library_source = (ROOT / "ui" / "pages" / "library_page.py").read_text(encoding="utf-8")
        main_source = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
        self.assertIn("relation_sync_completed = Signal()", library_source)
        self.assertIn('getattr(self.window(), "_qml_shell_enabled", False)', library_source)
        self.assertIn("self.library_page.relation_sync_completed.connect(self._refresh_library_after_bundle_change)", main_source)
        navigation_handler = main_source[main_source.index("def _qml_navigation_requested"):main_source.index("def _qml_open_library_work")]
        self.assertIn('if page_name == "collections":', navigation_handler)
        self.assertIn("QTimer.singleShot(0, self._start_qml_library_relation_sync)", navigation_handler)
        self.assertIn("page._start_relation_sync()", main_source)


    def test_qml_episode_tiles_keep_original_card_geometry_and_content(self):
        source = (ROOT / "ui" / "qml" / "ApplicationShell.qml").read_text(encoding="utf-8")
        self.assertIn("cellWidth: 252", source)
        self.assertIn("cellHeight: 274", source)
        self.assertIn("width: 240\n                                    height: 260", source)
        self.assertIn("Layout.preferredHeight: 126", source)
        self.assertIn("modelData.description ||", source)
        self.assertIn('"EP " + ((modelData.episodeNumber || 0) < 10 ? "0" : "")', source)
        self.assertIn('text: "Watched"', source)

    def test_production_application_shell_loads_with_the_application_bridge(self):
        source = (ROOT / "ui" / "qml" / "ApplicationShell.qml").read_text(encoding="utf-8")
        self.assertNotIn('text: "Your anime, manga and light novels in one place."', source)
        self.assertNotIn('text: "In progress"', source)
        self.assertIn('text: "Continue watching or reading"', source)
        self.assertIn("orientation: ListView.Horizontal", source)
        self.assertIn("recommendationGrid.contentHeight + 8", source)
        self.assertIn("model: bridge.recommendationItems", source)
        self.assertIn("A learning feed built from your collection, saved favorites, feedback, and the wider anime catalog.", source)
        self.assertIn("recommendationLoading && bridge.recommendationItems.length === 0", source)
        self.assertIn("bridge.loadMoreRecommendations()", source)
        self.assertIn('text: (bridge.selectedWork.seriesCount || 1) > 1', source)
        self.assertIn('"Edit bundle appearance…"', source)
        self.assertIn('text: "Delete from Library"', source)
        self.assertIn('text: "Mark all watched"', source)
        self.assertIn('text: "Clear progress"', source)
        self.assertIn("bridge.markAllEpisodesWatched(bridge.selectedWork.id, false)", source)
        self.assertIn('text: "Auto-bundle related works"', source)
        self.assertIn('text: "Add to bundle…"', source)
        self.assertIn('text: "Remove bundled item…"', source)
        self.assertIn('"Customize title and cover…"', source)
        self.assertIn("bridge.requestDeleteWork(bridge.selectedWork.id)", source)
        self.assertIn('bridge.requestDetailAction("customize_identity")', source)
        self.assertIn("bridge.brandWordmarkSource", source)
        self.assertIn('model: ["General", "Appearance", "Library", "Discovery", "Integrations", "Data & Storage", "Advanced"]', source)
        self.assertIn('visible: settingsPage.settingsCategory === "Data & Storage"', source)
        self.assertIn('text: "Local data"', source)
        self.assertIn("model: bridge.themePresetItems", source)
        bridge = ApplicationBridge()
        self.addCleanup(bridge.deleteLater)
        self.assertTrue(bridge.brandWordmarkSource.startswith("data:image/svg+xml;charset=utf-8,"))
        self.assertGreaterEqual(len(bridge.themePresetItems), 1)
        self._load_qml("ApplicationShell.qml", bridge)

    def test_qml_controls_default_to_palette_aware_basic_style(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")', source)


if __name__ == "__main__":
    unittest.main()
