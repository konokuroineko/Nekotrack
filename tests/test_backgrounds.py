import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

import ui.preferences as preferences
from ui.backgrounds import BackgroundCanvas, BackgroundManager


class MemorySettings:
    stores = {}

    def __init__(self, organization, application):
        self.store = self.stores.setdefault((organization, application), {})

    def value(self, key, default=None):
        return self.store.get(key, default)

    def setValue(self, key, value):
        self.store[key] = value

    def allKeys(self):
        return list(self.store)

    def sync(self):
        pass


class BackgroundManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._old_cwd = os.getcwd()
        self._directory = tempfile.TemporaryDirectory()
        os.chdir(self._directory.name)
        MemorySettings.stores = {
            ("NekoTrack", "NekoTrack"): {
                preferences._MIGRATION_KEY: True,
                "_theme_palette_version": preferences._THEME_PALETTE_VERSION,
                "_bundle_options_v1_migrated": True,
                "theme_preset": "Neko",
                "background_image_paths_json": "[]",
                "background_slideshow_interval": 0,
                "background_overlay_opacity": 62,
            },
            ("AniTrack", "AniTrack"): {},
        }
        self._settings_patch = patch.object(preferences, "QSettings", MemorySettings)
        self._settings_patch.start()

    def tearDown(self):
        self._settings_patch.stop()
        os.chdir(self._old_cwd)
        self._directory.cleanup()

    def _image(self, name, color):
        path = Path(self._directory.name) / name
        image = QImage(48, 64, QImage.Format.Format_ARGB32)
        image.fill(QColor(color))
        self.assertTrue(image.save(str(path), "PNG"))
        return path

    def _manager(self):
        return BackgroundManager()

    def test_imported_backgrounds_are_copied_persisted_and_restored(self):
        source = self._image("user-wallpaper.png", "#eb5a73")
        manager = self._manager()
        self.assertEqual(manager.add_images([str(source)]), 1)
        self.assertEqual(len(manager.paths), 1)
        stored = manager.paths[0]
        managed_file = Path(self._directory.name) / stored
        self.assertTrue(managed_file.is_file())
        self.assertNotEqual(str(managed_file), str(source))
        self.assertFalse(manager._pixmap.isNull())
        self.assertEqual(json.loads(preferences.get("background_image_paths_json")), [stored])

        manager._timer.stop()
        manager.deleteLater()
        self.app.processEvents()
        restored = self._manager()
        self.assertEqual(restored.paths, (stored,))
        self.assertEqual(restored.selected_path, stored)
        self.assertFalse(restored._pixmap.isNull())
        restored._timer.stop()
        restored.deleteLater()
        self.app.processEvents()

    def test_missing_interval_preference_defaults_to_visible_static_background(self):
        MemorySettings.stores[("NekoTrack", "NekoTrack")].pop(
            "background_slideshow_interval", None
        )
        manager = self._manager()
        self.assertEqual(manager.interval, 0)
        source = self._image("default-background.png", "#d35c79")
        self.assertEqual(manager.add_images([str(source)]), 1)
        self.assertIsNotNone(manager.display_pixmap)
        manager._timer.stop()
        manager.deleteLater()
        self.app.processEvents()

    def test_slideshow_interval_static_off_and_overlay_persist(self):
        first = self._image("first.png", "#e95a73")
        second = self._image("second.png", "#459ad7")
        manager = self._manager()
        self.assertEqual(manager.add_images([str(first), str(second)]), 2)
        manager.set_interval(0)
        self.assertFalse(manager._timer.isActive())
        self.assertIsNotNone(manager.display_pixmap)
        current = manager.selected_path
        manager.set_interval(30)
        self.assertTrue(manager._timer.isActive())
        self.assertEqual(manager._timer.interval(), 30_000)
        manager._advance()
        self.assertNotEqual(manager.selected_path, current)
        manager.set_interval(-1)
        self.assertFalse(manager._timer.isActive())
        self.assertIsNone(manager.display_pixmap)
        manager.set_overlay_opacity(76)
        self.assertEqual(preferences.get("background_overlay_opacity"), 76)
        self.assertEqual(manager.overlay_opacity, 76)
        self.assertEqual(preferences.get("background_slideshow_interval"), -1)
        manager._timer.stop()
        manager.deleteLater()
        self.app.processEvents()

    def test_slideshow_reuses_decoded_images_and_drops_missing_file_cache_entries(self):
        first = self._image("first-cache.png", "#e95a73")
        second = self._image("second-cache.png", "#459ad7")
        manager = self._manager()
        self.assertEqual(manager.add_images([str(first), str(second)]), 2)
        manager.set_interval(30)
        manager._advance()
        manager._advance()
        self.assertEqual(len(manager._pixmap_cache), 2)

        remaining = manager.paths[0]
        missing = manager.paths[1]
        missing_file = Path(self._directory.name) / missing
        missing_file.unlink()
        manager._advance()
        self.assertEqual(manager.paths, (remaining,))
        self.assertEqual(len(manager._pixmap_cache), 1)
        self.assertFalse(manager._pixmap.isNull())
        manager._timer.stop()
        manager.deleteLater()
        self.app.processEvents()

    def test_invalid_images_and_missing_saved_files_are_ignored(self):
        bad_file = Path(self._directory.name) / "not-an-image.png"
        bad_file.write_text("not image bytes", encoding="utf-8")
        manager = self._manager()
        self.assertEqual(manager.add_images([str(bad_file)]), 0)
        self.assertEqual(len(manager.last_errors), 1)
        self.assertEqual(manager.paths, ())
        image_path = self._image("valid.png", "#38aa84")
        self.assertEqual(manager.add_images([str(image_path)]), 1)
        stored = manager.paths[0]
        (Path(self._directory.name) / stored).unlink()
        manager._timer.stop()
        manager.deleteLater()
        self.app.processEvents()
        restored = self._manager()
        self.assertEqual(restored.paths, ())
        self.assertIsNone(restored.display_pixmap)
        self.assertEqual(json.loads(preferences.get("background_image_paths_json")), [])
        restored._timer.stop()
        restored.deleteLater()
        self.app.processEvents()

    def test_background_canvas_paints_theme_surface_without_image(self):
        manager = self._manager()
        canvas = BackgroundCanvas(manager)
        canvas.resize(80, 60)
        canvas.show()
        self.app.processEvents()
        rendered = canvas.grab().toImage()
        from ui.theme import COLORS
        self.assertEqual(rendered.pixelColor(10, 10).name(), QColor(COLORS["background"]).name())
        source = self._image("canvas.png", "#e95a73")
        manager.add_images([str(source)])
        canvas.repaint()
        self.app.processEvents()
        self.assertFalse(canvas.grab().toImage().isNull())
        manager._timer.stop()
        manager.deleteLater()
        canvas.close()
        canvas.deleteLater()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
