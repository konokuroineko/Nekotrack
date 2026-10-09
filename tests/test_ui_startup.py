import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

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


class UiStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

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
                    window.close()
                    window.deleteLater()
                    self.app.processEvents()
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
