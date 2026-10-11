import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import shiboken6
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtWidgets import QApplication, QLabel

import ui.preferences as preferences


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


# ui.theme reads settings while the UI modules are imported. Use an isolated
# in-memory settings backend even at import time so this smoke test never edits
# the developer's real NekoTrack preferences.
with patch.object(preferences, "QSettings", MemorySettings):
    from ui.main_window import MainWindow
    from ui.pages.settings_page import SettingsPage
    from ui.pages.work_detail_page import WorkDetailPage
    from ui.setup_wizard import SetupWizard


class UiStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_remote_cover_finished_ignores_deleted_label(self):
        page = WorkDetailPage()
        label = QLabel()
        shiboken6.delete(label)

        buffer = QBuffer()
        self.assertTrue(buffer.open(QIODevice.WriteOnly))
        image = QPixmap(2, 2)
        image.fill()
        self.assertTrue(image.save(buffer, "PNG"))
        image_bytes = bytes(buffer.data())
        buffer.close()

        class FakeReply:
            NetworkError = QNetworkReply.NetworkError

            def __init__(self):
                self.deleted = False

            @staticmethod
            def error():
                return QNetworkReply.NetworkError.NoError

            @staticmethod
            def readAll():
                return image_bytes

            def deleteLater(self):
                self.deleted = True

        reply = FakeReply()
        page._cover_reply = reply
        cover_url = "https://example.invalid/cover.png?deleted-label-test"

        with tempfile.TemporaryDirectory() as directory:
            image_directory = Path(directory)
            with patch(
                "ui.pages.work_detail_page.IMAGE_DIRECTORY", image_directory
            ), patch(
                "ui.pages.work_detail_page.save_cover_path"
            ) as save_cover_path:
                page._remote_cover_finished(label, 42, cover_url, reply)

            self.assertIsNone(page._cover_reply)
            self.assertTrue(reply.deleted)
            self.assertIn(cover_url, page._cover_cache)
            self.assertTrue((image_directory / "42.jpg").is_file())
            save_cover_path.assert_called_once_with(
                42, str(image_directory / "42.jpg")
            )
        page.deleteLater()
        self.app.processEvents()

    def test_bundle_options_are_available_in_setup_and_settings(self):
        option_defaults = {
            key: False for key in preferences.BUNDLE_OPTION_KEYS
        }
        MemorySettings.stores = {
            ("NekoTrack", "NekoTrack"): {
                preferences._MIGRATION_KEY: True,
                "_bundle_options_v1_migrated": True,
                "_theme_palette_version": preferences._THEME_PALETTE_VERSION,
                "theme_preset": "Neko",
                "setup_complete": True,
                **option_defaults,
            },
            ("AniTrack", "AniTrack"): {},
        }

        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            wizard = None
            settings_page = None
            try:
                os.chdir(directory)
                import database
                database.initialize_database()
                with patch.object(preferences, "QSettings", MemorySettings):
                    wizard = SetupWizard()
                    settings_page = SettingsPage()
                    expected = set(preferences.BUNDLE_OPTION_KEYS)
                    self.assertEqual(set(wizard.bundle_checkboxes), expected)
                    self.assertEqual(set(settings_page.bundle_checkboxes), expected)

                    wizard.bundle_checkboxes["bundle_include_ovas"].setChecked(True)
                    self.assertTrue(wizard.bundle_options["bundle_include_ovas"])

                    settings_page.bundle_checkboxes["bundle_include_onas"].setChecked(True)
                    self.assertTrue(preferences.get("bundle_include_onas"))
            finally:
                if wizard is not None:
                    wizard.close()
                    wizard.deleteLater()
                if settings_page is not None:
                    settings_page.close()
                    settings_page.deleteLater()
                self.app.processEvents()
                os.chdir(old_cwd)

    def test_main_window_builds_with_only_registered_pages(self):
        MemorySettings.stores = {
            ("NekoTrack", "NekoTrack"): {
                preferences._MIGRATION_KEY: True,
                "_theme_palette_version": preferences._THEME_PALETTE_VERSION,
                "theme_preset": "Neko",
                "setup_complete": True,
            },
            ("AniTrack", "AniTrack"): {},
        }

        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                with patch.object(preferences, "QSettings", MemorySettings):
                    window = MainWindow()
                    self.assertEqual(
                        set(window.navigation.pages),
                        {"home", "collections", "search", "work_detail", "settings"},
                    )
                    self.assertFalse(window.windowIcon().isNull())
                    self.assertFalse(window.brand_mark.pixmap().isNull())
                    self.assertFalse(window.brand_word.pixmap().isNull())
                    self.assertEqual(window.brand_word.accessibleName(), "NekoTrack")
                    self.assertEqual(
                        {name: button.text() for name, button in window.navigation_buttons.items()},
                        {
                            "home": "Home",
                            "collections": "Library",
                            "search": "Search",
                            "settings": "Settings",
                        },
                    )
                    self.assertTrue(
                        all(not button.icon().isNull() for button in window.navigation_buttons.values())
                    )
                    window.close()
                    window.deleteLater()
                    self.app.processEvents()
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
