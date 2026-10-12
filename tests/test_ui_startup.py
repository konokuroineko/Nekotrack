import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import shiboken6
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QBuffer, QIODevice
from PySide6.QtTest import QTest
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtWidgets import QApplication, QLabel, QFrame

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
    from ui.widgets.person_card import PersonCard
    from ui.pages.entity_profile_page import EntityProfilePage, MediaCreditCard, ProfileWorkCreditCard
    from ui.widgets.character_card import CharacterCard
    from ui.widgets.work_card import WorkCard
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
                    groups = series.get_library_series()

                self.assertEqual(saved, 1)
                memberships = database.get_automatic_bundle_memberships([21355])
                self.assertEqual(
                    {int(row["work_id"]) for row in memberships},
                    {21355, 100049, 120700},
                )
                # Assert against the grouping computed with the same enabled
                # OVA/ONA preferences, rather than re-running with defaults.
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
                        {
                            "home", "collections", "search", "work_detail",
                            "entity_profile", "settings",
                        },
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


    def test_character_bundle_voice_actors_open_profiles_and_back_returns_to_character(self):
        MemorySettings.stores = {
            ("NekoTrack", "NekoTrack"): {
                preferences._MIGRATION_KEY: True,
                "_theme_palette_version": preferences._THEME_PALETTE_VERSION,
                "theme_preset": "Neko",
                "setup_complete": True,
            },
            ("AniTrack", "AniTrack"): {},
        }
        actors = [
            {
                "person_id": 7001,
                "name": "Japanese Actor",
                "language": "Japanese",
                "languages": ["Japanese"],
                "image_path": None,
                "image_url": None,
                "credits": [{
                    "work_id": 101,
                    "work_title": "Adaptation 101",
                    "language": "Japanese",
                }],
            },
            {
                "person_id": 7002,
                "name": "English Actor",
                "language": "English",
                "languages": ["English"],
                "image_path": None,
                "image_url": None,
                "credits": [{
                    "work_id": 102,
                    "work_title": "Adaptation 102",
                    "language": "English",
                }],
            },
        ]
        window = None
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                with patch.object(preferences, "QSettings", MemorySettings), \
                     patch("ui.main_window.get_bundle_character_voice_actors", return_value=actors) as get_actors, \
                     patch("ui.pages.entity_profile_page.EntityProfilePage._start_profile_load"):
                    window = MainWindow()
                    window.work_detail_page.work = {
                        "id": 101,
                        "_series_members": [{"id": 101}, {"id": 102}],
                    }
                    window.show_entity_profile(
                        "character",
                        {"id": 501, "character_name": "Example Character"},
                    )
                    self.assertEqual(
                        get_actors.call_args.args,
                        ([101, 102], 501),
                    )

                    window.show()
                    self.app.processEvents()
                    cards = window.entity_profile_page.findChildren(PersonCard)
                    self.assertEqual(
                        {card.person["person_id"] for card in cards},
                        {7001, 7002},
                    )
                    QTest.mouseClick(cards[0], Qt.LeftButton)
                    self.assertEqual(window.entity_profile_page.current_type, "voice_actor")
                    self.assertIn(
                        window.entity_profile_page.current_record.get("person_id"),
                        {7001, 7002},
                    )

                    window._back_from_entity_profile()
                    self.assertEqual(window.entity_profile_page.current_type, "character")
                    self.assertEqual(
                        {actor["person_id"] for actor in window.entity_profile_page.voice_actors},
                        {7001, 7002},
                    )
            finally:
                if window is not None:
                    window.close()
                    window.deleteLater()
                    self.app.processEvents()
                os.chdir(old_cwd)

    def test_missing_character_voice_actor_triggers_targeted_refresh_and_updates_profile(self):
        MemorySettings.stores = {
            ("NekoTrack", "NekoTrack"): {
                preferences._MIGRATION_KEY: True,
                "_theme_palette_version": preferences._THEME_PALETTE_VERSION,
                "theme_preset": "Neko",
                "setup_complete": True,
            },
            ("AniTrack", "AniTrack"): {},
        }
        actor = {
            "person_id": 901,
            "name": "Recovered Voice Actor",
            "language": "Japanese",
            "languages": ["Japanese"],
            "image_path": None,
            "image_url": None,
            "credits": [{
                "work_id": 21355,
                "work_title": "Re:ZERO -Starting Life in Another World-",
                "language": "Japanese",
            }],
        }
        window = None
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                with patch.object(preferences, "QSettings", MemorySettings), \
                     patch("ui.pages.entity_profile_page.EntityProfilePage._start_profile_load"), \
                     patch("ui.main_window.get_bundle_character_voice_actors", side_effect=[[], [actor]]), \
                     patch("ui.main_window.get_work", side_effect=lambda work_id: {"id": work_id, "type": "ANIME"}), \
                     patch(
                         "database.get_characters",
                         side_effect=lambda work_id: (
                             [{"id": 90185, "person_id": None}] if int(work_id) == 21355 else []
                         ),
                     ) as get_characters, \
                     patch("ui.main_window.invalidate_character_snapshots", return_value=2) as invalidate, \
                     patch.object(MainWindow, "_queue_library_imports") as queue_imports:
                    window = MainWindow()
                    window.work_detail_page.work = {
                        "id": 21355,
                        "_series_members": [{"id": 21355}, {"id": 108632}],
                    }
                    window.show_entity_profile(
                        "character",
                        {"id": 90185, "character_name": "Crusch Karsten"},
                    )

                    # Refresh must not depend on the target character already being
                    # present in every member's potentially incomplete cache.
                    get_characters.assert_not_called()

                    invalidate.assert_called_once_with([21355, 108632])
                    queue_imports.assert_called_once_with([21355, 108632])
                    self.assertEqual(window.entity_profile_page.voice_actors, [])

                    window._complete_pending_character_cast_refresh(21355)
                    self.assertEqual(window.entity_profile_page.voice_actors, [])
                    window._complete_pending_character_cast_refresh(108632)

                    self.assertEqual(
                        [item["person_id"] for item in window.entity_profile_page.voice_actors],
                        [901],
                    )
                    self.assertEqual(
                        window.entity_profile_page.current_record["voice_actors"][0]["name"],
                        "Recovered Voice Actor",
                    )
                    self.assertFalse(window._pending_character_cast_refreshes)
            finally:
                if window is not None:
                    window.close()
                    window.deleteLater()
                    self.app.processEvents()
                os.chdir(old_cwd)


    def test_profile_about_description_lives_under_name_in_header(self):
        description = "A long biography that should use the wide space beside the portrait."
        with patch.object(EntityProfilePage, "_start_profile_load"):
            page = EntityProfilePage()
            try:
                page.set_profile(
                    "character",
                    {"id": 90185, "character_name": "Crusch Karsten"},
                )
                page._remote_data = {
                    "id": 90185,
                    "name": {"full": "Crusch Karsten"},
                    "description": description,
                    "image": {},
                    "media": {"edges": []},
                }
                page._render_profile()

                active_widgets = [
                    page.content_layout.itemAt(index).widget()
                    for index in range(page.content_layout.count())
                    if page.content_layout.itemAt(index) is not None
                    and page.content_layout.itemAt(index).widget() is not None
                ]
                header = active_widgets[0] if active_widgets else None
                self.assertIsNotNone(header)
                about = header.findChild(QLabel, "profileDescription")
                self.assertIsNotNone(about)
                self.assertEqual(about.text(), description)
                self.assertFalse(
                    any(
                        section.isAncestorOf(about)
                        for section in active_widgets
                        if isinstance(section, QFrame) and section.objectName() == "profileSection"
                    )
                )
            finally:
                page.close()
                page.deleteLater()
                self.app.processEvents()

    def test_voice_acting_roles_show_work_left_and_character_right_sorted_by_role(self):
        with patch.object(EntityProfilePage, "_start_profile_load"):
            page = EntityProfilePage()
            try:
                page.set_profile(
                    "voice_actor",
                    {"person_id": 7001, "name": "Yuka Iguchi"},
                )
                node = {
                    "id": 21355,
                    "type": "ANIME",
                    "format": "TV",
                    "title": {"english": "Re:Zero"},
                    "coverImage": {},
                    "startDate": {"year": 2016},
                }
                page._remote_data = {
                    "id": 7001,
                    "name": {"full": "Yuka Iguchi"},
                    "image": {},
                    "description": "Voice actor biography.",
                    "staffMedia": {"edges": []},
                    "characterMedia": {
                        "edges": [
                            {
                                "characterRole": "SUPPORTING",
                                "characters": [{
                                    "id": 90185,
                                    "name": {"full": "Crusch Karsten"},
                                    "image": {},
                                }],
                                "node": node,
                            },
                            {
                                "characterRole": "BACKGROUND",
                                "characters": [{
                                    "id": 90187,
                                    "name": {"full": "Background Character"},
                                    "image": {},
                                }],
                                "node": node,
                            },
                            {
                                "characterRole": "MAIN",
                                "characters": [{
                                    "id": 90186,
                                    "name": {"full": "Main Character"},
                                    "image": {},
                                }],
                                "node": node,
                            },
                        ]
                    },
                }
                page._render_profile()
                active_widgets = [
                    page.content_layout.itemAt(index).widget()
                    for index in range(page.content_layout.count())
                    if page.content_layout.itemAt(index) is not None
                    and page.content_layout.itemAt(index).widget() is not None
                ]
                section_titles = [
                    title.text()
                    for widget in active_widgets
                    if isinstance(widget, QFrame)
                    and (title := widget.findChild(QLabel, "profileSectionTitle")) is not None
                ]
                self.assertIn("Voice acting roles", section_titles)
                self.assertNotIn("Staff credits", section_titles)
                section = next(
                    frame for frame in active_widgets
                    if (
                        isinstance(frame, QFrame)
                        and frame.objectName() == "profileSection"
                        and (title := frame.findChild(QLabel, "profileSectionTitle")) is not None
                        and title.text() == "Voice acting roles"
                    )
                )
                cards = section.findChildren(MediaCreditCard)
                self.assertEqual(len(cards), 3)
                self.assertEqual(
                    [card.character_cards[0].character["id"] for card in cards],
                    [90186, 90185, 90187],
                )
                self.assertTrue(all(card.width() == 300 for card in cards))
                self.assertEqual(
                    [card.findChild(QLabel, "mediaCreditRole").text() for card in cards],
                    ["MAIN", "SUPPORTING", "BACKGROUND"],
                )
                for card in cards:
                    self.assertEqual(len(card.character_cards), 1)
                    self.assertEqual(card.findChild(QLabel, "mediaCreditMetadata"), None)
                    self.assertFalse(card.findChildren(CharacterCard))
                    labels = [label.text() for label in card.findChildren(QLabel)]
                    self.assertNotIn("CHARACTERS", labels)
                    self.assertFalse(any("credit" in text.casefold() for text in labels))
            finally:
                page.close()
                page.deleteLater()
                self.app.processEvents()

    def test_character_profile_appears_in_uses_shared_poster_cards(self):
        with patch.object(EntityProfilePage, "_start_profile_load"):
            page = EntityProfilePage()
            try:
                page.set_profile(
                    "character",
                    {"id": 90185, "character_name": "Crusch Karsten"},
                )
                page._remote_data = {
                    "id": 90185,
                    "name": {"full": "Crusch Karsten"},
                    "image": {},
                    "description": "",
                    "media": {
                        "edges": [
                            {
                                "node": {
                                    "id": 21355,
                                    "type": "ANIME",
                                    "format": "TV",
                                    "title": {"english": "Re:Zero"},
                                    "coverImage": {},
                                    "startDate": {"year": 2016},
                                }
                            },
                            {
                                "node": {
                                    "id": 21356,
                                    "type": "ANIME",
                                    "format": "OVA",
                                    "title": {"english": "Re:Zero OVA"},
                                    "coverImage": {},
                                    "startDate": {"year": 2018},
                                }
                            },
                        ]
                    },
                }
                page._render_profile()
                active_widgets = [
                    page.content_layout.itemAt(index).widget()
                    for index in range(page.content_layout.count())
                    if page.content_layout.itemAt(index) is not None
                    and page.content_layout.itemAt(index).widget() is not None
                ]
                section = next(
                    frame for frame in active_widgets
                    if (
                        isinstance(frame, QFrame)
                        and frame.objectName() == "profileSection"
                        and (title := frame.findChild(QLabel, "profileSectionTitle")) is not None
                        and title.text() == "Appears in"
                    )
                )
                cards = section.findChildren(WorkCard)
                self.assertEqual(len(cards), 2)
                self.assertTrue(all(card.objectName() == "posterCard" for card in cards))
                self.assertFalse(section.findChildren(MediaCreditCard))
            finally:
                page.close()
                page.deleteLater()
                self.app.processEvents()

    def test_staff_profile_credits_use_compact_poster_cards(self):
        with patch.object(EntityProfilePage, "_start_profile_load"):
            page = EntityProfilePage()
            try:
                page.set_profile("staff", {"person_id": 7002, "name": "Example Staff"})
                page._remote_data = {
                    "id": 7002,
                    "name": {"full": "Example Staff"},
                    "image": {},
                    "description": "",
                    "staffMedia": {
                        "edges": [{
                            "staffRole": "Director / Storyboard",
                            "node": {
                                "id": 21355,
                                "type": "ANIME",
                                "format": "TV",
                                "title": {"english": "Re:Zero"},
                                "coverImage": {},
                                "startDate": {"year": 2016},
                            },
                        }]
                    },
                    "characterMedia": {"edges": []},
                }
                page._render_profile()

                active_widgets = [
                    page.content_layout.itemAt(index).widget()
                    for index in range(page.content_layout.count())
                    if page.content_layout.itemAt(index) is not None
                    and page.content_layout.itemAt(index).widget() is not None
                ]
                section = next(
                    frame for frame in active_widgets
                    if (
                        isinstance(frame, QFrame)
                        and frame.objectName() == "profileSection"
                        and (title := frame.findChild(QLabel, "profileSectionTitle")) is not None
                        and title.text() == "Staff credits"
                    )
                )
                cards = section.findChildren(ProfileWorkCreditCard)
                self.assertEqual(len(cards), 1)
                self.assertIsInstance(cards[0], WorkCard)
                role = cards[0].findChild(QLabel, "profileCreditRole")
                self.assertIsNotNone(role)
                self.assertEqual(role.toolTip(), "Director / Storyboard")
            finally:
                page.close()
                page.deleteLater()
                self.app.processEvents()

    def test_character_voice_actor_cards_show_language_without_credit_count(self):
        credits = [
            {"language": "Japanese", "work_id": work_id, "work_title": f"Adaptation {work_id}"}
            for work_id in (101, 102, 103, 104, 105)
        ]
        actor = {
            "person_id": 7003,
            "name": "Example Voice Actor",
            "language": "Japanese",
            "languages": ["Japanese"],
            "credits": credits,
            "image_path": None,
            "image_url": None,
        }
        with patch.object(EntityProfilePage, "_start_profile_load"):
            page = EntityProfilePage()
            try:
                page.set_profile(
                    "character",
                    {"id": 90185, "character_name": "Crusch Karsten"},
                    voice_actors=[actor],
                )
                page._remote_data = {
                    "id": 90185,
                    "name": {"full": "Crusch Karsten"},
                    "image": {},
                    "description": "",
                    "media": {"edges": []},
                }
                page._render_profile()
                active_widgets = [
                    page.content_layout.itemAt(index).widget()
                    for index in range(page.content_layout.count())
                    if page.content_layout.itemAt(index) is not None
                    and page.content_layout.itemAt(index).widget() is not None
                ]
                voice_section = next(
                    widget for widget in active_widgets
                    if isinstance(widget, QFrame)
                    and widget.objectName() == "profileSection"
                    and (
                        (title := widget.findChild(QLabel, "profileSectionTitle")) is not None
                        and title.text() == "Voice actors"
                    )
                )
                card = voice_section.findChild(PersonCard)
                self.assertIsNotNone(card)
                role = card.findChild(QLabel, "personRole")
                self.assertIsNotNone(role)
                self.assertEqual(role.text(), "Japanese")
                self.assertNotIn("credit", role.text().casefold())
                self.assertIn("Adaptation 101", card.toolTip())
            finally:
                page.close()
                page.deleteLater()
                self.app.processEvents()

if __name__ == "__main__":
    unittest.main()
