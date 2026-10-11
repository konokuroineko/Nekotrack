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
    from ui.pages.library_page import (
        RelationSyncWorker,
        _backfill_automatic_bundle_memberships,
        pending_relation_sync_ids,
    )
    from ui.pages.settings_page import SettingsPage
    from ui.pages.work_detail_page import WorkDetailPage
    from ui.setup_wizard import SetupWizard


class UiStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_library_uses_the_bundle_saved_from_search_before_relation_sync_finishes(self):
        import os
        import tempfile

        import database
        import series

        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()
                items = [
                    {
                        "id": 21355,
                        "title": {"romaji": "Re:Zero", "english": "Re:Zero"},
                        "type": "ANIME",
                        "format": "TV",
                    },
                    {
                        "id": 100049,
                        "title": {"romaji": "Re:Zero OVAs", "english": "Re:Zero OVAs"},
                        "type": "ANIME",
                        "format": "OVA",
                    },
                    {
                        "id": 120700,
                        "title": {"romaji": "Re:Zero Break Time", "english": "Re:Zero Break Time"},
                        "type": "ANIME",
                        "format": "ONA",
                    },
                ]
                for item in items:
                    database.save_anime(item)
                    database.add_to_library(item["id"], "Planning")
                database.save_automatic_bundle_membership(
                    21355,
                    [item["id"] for item in items],
                )
                with patch(
                    "series.get",
                    side_effect=lambda key: key in {
                        "bundle_include_ovas",
                        "bundle_include_onas",
                    },
                ):
                    groups = series.get_library_series()
                self.assertEqual(len(groups), 1)
                self.assertEqual(
                    {int(member["id"]) for member in groups[0]["_series_members"]},
                    {21355, 100049, 120700},
                )
            finally:
                os.chdir(old_cwd)

    def test_relation_sync_backfills_existing_library_bundles_from_complete_graph(self):
        import os
        import tempfile

        import database
        import series

        tv = {
            "id": 21355,
            "type": "ANIME",
            "format": "TV",
            "title": {"english": "Re:Zero", "romaji": "Re:Zero"},
            "relations": {"edges": [
                {
                    "relationType": "SIDE_STORY",
                    "node": {
                        "id": 100049, "type": "ANIME", "format": "OVA",
                        "title": {"english": "Re:Zero OVAs", "romaji": "Re:Zero OVAs"},
                    },
                },
                {
                    "relationType": "SPIN_OFF",
                    "node": {
                        "id": 120700, "type": "ANIME", "format": "ONA",
                        "title": {"english": "Re:Zero Break Time", "romaji": "Re:Zero Break Time"},
                    },
                },
            ]},
        }
        ova = {
            "id": 100049,
            "type": "ANIME",
            "format": "OVA",
            "title": {"english": "Re:Zero OVAs", "romaji": "Re:Zero OVAs"},
            "relations": {"edges": [
                {
                    "relationType": "PREQUEL",
                    "node": {
                        "id": 21355, "type": "ANIME", "format": "TV",
                        "title": {"english": "Re:Zero", "romaji": "Re:Zero"},
                    },
                },
            ]},
        }
        ona = {
            "id": 120700,
            "type": "ANIME",
            "format": "ONA",
            "title": {"english": "Re:Zero Break Time", "romaji": "Re:Zero Break Time"},
            "relations": {"edges": [
                {
                    "relationType": "SPIN_OFF",
                    "node": {
                        "id": 21355, "type": "ANIME", "format": "TV",
                        "title": {"english": "Re:Zero", "romaji": "Re:Zero"},
                    },
                },
            ]},
        }

        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()
                items = [tv, ova, ona]
                for item in items:
                    database.save_anime(item)
                    database.add_to_library(item["id"], "Planning")

                with patch(
                    "series.get",
                    side_effect=lambda key: key in {
                        "bundle_include_ovas",
                        "bundle_include_onas",
                    },
                ):
                    saved = _backfill_automatic_bundle_memberships(
                        [item["id"] for item in items],
                        {item["id"]: item for item in items},
                    )

                self.assertEqual(saved, 1)
                memberships = database.get_automatic_bundle_memberships([21355])
                self.assertEqual(
                    {int(row["work_id"]) for row in memberships},
                    {21355, 100049, 120700},
                )
                groups = series.get_library_series()
                self.assertEqual(len(groups), 1)
                self.assertEqual(
                    {int(member["id"]) for member in groups[0]["_series_members"]},
                    {21355, 100049, 120700},
                )
            finally:
                os.chdir(old_cwd)

    def test_library_relation_sync_does_not_skip_previously_connected_ids(self):
        # A work can already appear as a target/source in a stale or partial
        # relation graph; only completed or failed attempts in this app session
        # should suppress another full-snapshot fetch.
        pending = pending_relation_sync_ids(
            [21355, 108632, -148237],
            checked_ids={108632},
            failed_ids=set(),
        )
        self.assertEqual(pending, [-148237, 21355])

    def test_relation_sync_worker_persists_full_relation_snapshots(self):
        details = {
            "id": 21355,
            "type": "ANIME",
            "format": "TV",
            "title": {"romaji": "Re:Zero", "english": "Re:Zero"},
            "relations": {
                "edges": [
                    {
                        "relationType": "SIDE_STORY",
                        "node": {
                            "id": 100049,
                            "type": "ANIME",
                            "format": "OVA",
                            "title": {"romaji": "Re:Zero OVAs", "english": "Re:Zero OVAs"},
                        },
                    }
                ]
            },
        }
        emitted = []
        worker = RelationSyncWorker([21355])
        worker.finished.connect(emitted.append)

        with patch(
            "ui.pages.library_page.get_media_relations_batch",
            return_value={21355: details},
        ) as fetch_relations, patch(
            "ui.pages.library_page.save_anime"
        ) as save_anime:
            worker.run()

        fetch_relations.assert_called_once_with([21355])
        save_anime.assert_called_once_with(details)
        self.assertEqual(emitted, [{21355}])

    def test_relation_sync_worker_does_not_fan_out_after_batch_failure(self):
        emitted = []
        worker = RelationSyncWorker([21355, 108632, 119661])
        worker.finished.connect(emitted.append)

        with patch(
            "ui.pages.library_page.get_media_relations_batch",
            side_effect=RuntimeError("batch unavailable"),
        ) as fetch_relations, patch(
            "ui.pages.library_page.save_anime"
        ) as save_anime, patch(
            "ui.pages.library_page.log_exception"
        ):
            worker.run()

        fetch_relations.assert_called_once_with([21355, 108632, 119661])
        save_anime.assert_not_called()
        self.assertEqual(emitted, [set()])

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
