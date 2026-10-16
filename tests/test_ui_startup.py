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
from PySide6.QtWidgets import QApplication, QLabel, QFrame, QTextBrowser, QCheckBox, QComboBox, QPushButton

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
    from ui.widgets.character_card import CharacterCard, CharacterArtwork
    from ui.widgets.work_card import WorkCard
    from ui.theme import card_stylesheet
    from ui.pages.library_page import (
        RelationSyncWorker,
        _backfill_automatic_bundle_memberships,
        pending_relation_sync_ids,
    )
    from ui.pages.home_page import HomePage
    from ui.pages.settings_page import SettingsPage
    from ui.pages.work_detail_page import WorkDetailPage
    from ui.setup_wizard import SetupWizard


class UiStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_sidebar_navigation_order_and_branding_details(self):
        from ui.branding import _NAV_DRAWINGS, _wordmark_svg
        from ui.main_window import SIDEBAR_NAVIGATION

        self.assertEqual(
            [(label, page) for _icon, label, page in SIDEBAR_NAVIGATION],
            [
                ("Home", "home"),
                ("Library", "collections"),
                ("Search", "search"),
                ("Calendar", "calendar"),
                ("Favorites", "favorites"),
                ("Settings", "settings"),
            ],
        )
        self.assertEqual(len({page for _icon, _label, page in SIDEBAR_NAVIGATION}), 6)
        self.assertIn('stroke-width="3.5"', _wordmark_svg())
        self.assertEqual(_NAV_DRAWINGS["settings"].count("L"), 23)
        self.assertIn('<circle cx="12" cy="12" r="2.8"/>', _NAV_DRAWINGS["settings"])
        self.assertNotIn("M4 6.2h5.3", _NAV_DRAWINGS["settings"])

    def test_ui_scale_preference_is_configured_before_qt_startup(self):
        from ui.preferences import UI_SCALE_OPTIONS
        from ui.scale import configure_ui_scale

        original_scale = os.environ.get("QT_SCALE_FACTOR")
        try:
            self.assertEqual(UI_SCALE_OPTIONS, (80, 90, 100, 110, 125, 150, 175, 200))
            self.assertEqual(configure_ui_scale(125), 125)
            self.assertEqual(os.environ["QT_SCALE_FACTOR"], "1.25")
            self.assertEqual(configure_ui_scale(100), 100)
            self.assertEqual(os.environ["QT_SCALE_FACTOR"], "1")
            self.assertEqual(configure_ui_scale(120), 100)
            self.assertEqual(os.environ["QT_SCALE_FACTOR"], "1")
        finally:
            if original_scale is None:
                os.environ.pop("QT_SCALE_FACTOR", None)
            else:
                os.environ["QT_SCALE_FACTOR"] = original_scale

    def test_navigation_back_uses_the_actual_previous_page(self):
        from PySide6.QtWidgets import QStackedWidget, QWidget
        from ui.navigation import NavigationController
        from ui.branding import _NAV_DRAWINGS, navigation_icon

        self.assertIn("back", _NAV_DRAWINGS)
        self.assertFalse(navigation_icon("back", "#a678ff").isNull())

        for origin in ("home", "search"):
            stack = QStackedWidget()
            navigation = NavigationController(stack)
            for page_name in (
                "home", "collections", "search", "work_detail", "entity_profile"
            ):
                navigation.add_page(page_name, QWidget())
            navigation.show(origin, record_history=False)
            navigation.show("work_detail")
            navigation.show("entity_profile")
            self.assertEqual(
                navigation.back(fallback="work_detail", skip=("entity_profile",)),
                "work_detail",
            )
            self.assertEqual(
                navigation.back(fallback="collections", skip=("work_detail",)),
                origin,
            )
            stack.deleteLater()
        self.app.processEvents()

    def test_scale_change_offers_a_restart_action(self):
        previous_stores = MemorySettings.stores
        previous_factor = os.environ.get("QT_SCALE_FACTOR")
        os.environ["QT_SCALE_FACTOR"] = "1"
        MemorySettings.stores = {}
        try:
            with patch.object(preferences, "QSettings", MemorySettings):
                settings_page = SettingsPage()
                combo = settings_page.findChild(QComboBox, "uiScaleCombo")
                restart_button = settings_page.findChild(QPushButton, "uiScaleRestartButton")
                self.assertIsNotNone(combo)
                self.assertIsNotNone(restart_button)
                self.assertTrue(restart_button.isHidden())

                requested = []
                settings_page.restart_requested.connect(lambda: requested.append(True))
                combo.setCurrentIndex(combo.findData(125))
                self.app.processEvents()
                self.assertEqual(preferences.get("ui_scale"), 125)
                self.assertFalse(restart_button.isHidden())

                # Rebuilding Settings must not hide a scale change that has
                # been saved but has not yet been applied at application start.
                rebuilt_page = SettingsPage()
                rebuilt_button = rebuilt_page.findChild(QPushButton, "uiScaleRestartButton")
                self.assertIsNotNone(rebuilt_button)
                self.assertFalse(rebuilt_button.isHidden())

                restart_button.click()
                self.assertEqual(requested, [True])

                settings_page.close()
                settings_page.deleteLater()
                rebuilt_page.close()
                rebuilt_page.deleteLater()
                self.app.processEvents()
        finally:
            MemorySettings.stores = previous_stores
            if previous_factor is None:
                os.environ.pop("QT_SCALE_FACTOR", None)
            else:
                os.environ["QT_SCALE_FACTOR"] = previous_factor

    def test_brand_assets_and_switch_rendering_on_dark_and_white_surfaces(self):
        from PySide6.QtGui import QColor
        from ui.branding import application_icon, logo_pixmap, wordmark_pixmap
        from ui.preferences import THEME_PRESETS, palette_for_mode
        from ui.widgets.switch_control import SwitchControl

        icon = application_icon()
        self.assertFalse(icon.isNull())
        self.assertTrue(icon.availableSizes())

        app_mark = logo_pixmap(96)
        self.assertFalse(app_mark.isNull())
        self.assertEqual(app_mark.toImage().pixelColor(0, 0).alpha(), 0)

        dark_lockup = wordmark_pixmap("#a678ff", 222, 58, light_mode=False)
        light_lockup = wordmark_pixmap("#59c2b6", 222, 58, light_mode=True)
        self.assertFalse(dark_lockup.isNull())
        self.assertFalse(light_lockup.isNull())
        self.assertEqual(dark_lockup.width(), 666)
        self.assertEqual(dark_lockup.height(), 174)
        self.assertEqual(dark_lockup.devicePixelRatioF(), 3.0)
        self.assertEqual(light_lockup.toImage().pixelColor(0, 0).alpha(), 0)

        def count_pixels(pixmap, predicate):
            image = pixmap.toImage()
            return sum(
                1
                for y in range(image.height())
                for x in range(image.width())
                if predicate(image.pixelColor(x, y))
            )

        def black_ink(color):
            return color.alpha() > 220 and max(color.red(), color.green(), color.blue()) < 30

        def pale_outline(color):
            return (
                color.alpha() > 220
                and color.red() > 190
                and color.green() > 185
                and color.blue() > 200
            )

        self.assertGreater(count_pixels(dark_lockup, black_ink), 100)
        self.assertGreater(count_pixels(light_lockup, black_ink), 100)
        self.assertGreater(count_pixels(dark_lockup, pale_outline), 100)
        self.assertLess(
            count_pixels(light_lockup, pale_outline),
            count_pixels(dark_lockup, pale_outline),
        )

        def render(control):
            pixmap = QPixmap(control.size())
            pixmap.fill(QColor(0, 0, 0, 0))
            control.render(pixmap)
            return pixmap.toImage()

        for light_mode in (False, True):
            palette = palette_for_mode(THEME_PRESETS["Neko"], light_mode)
            switch = SwitchControl(palette=palette)
            switch.setAccessibleName("White mode")
            switch.resize(switch.sizeHint())
            switch.show()
            self.app.processEvents()
            y = switch.height() // 2

            unchecked = render(switch)
            self.assertEqual(
                unchecked.pixelColor(31, y).name(),
                QColor(
                    palette["surface_hover"] if switch.underMouse()
                    else palette["surface_alt"]
                ).name(),
            )
            unchecked_thumb = unchecked.pixelColor(11, y)
            self.assertGreater(unchecked_thumb.red(), 230)
            self.assertGreater(unchecked_thumb.green(), 230)
            self.assertGreater(unchecked_thumb.blue(), 230)

            switch.setChecked(True)
            QTest.qWait(220)
            self.app.processEvents()
            checked = render(switch)
            self.assertEqual(
                checked.pixelColor(8, y).name(),
                QColor(palette["accent"]).name(),
            )
            checked_thumb = checked.pixelColor(29, y)
            self.assertGreater(checked_thumb.red(), 230)
            self.assertGreater(checked_thumb.green(), 230)
            self.assertGreater(checked_thumb.blue(), 230)

            switch.setEnabled(False)
            self.app.processEvents()
            disabled = render(switch)
            self.assertEqual(
                disabled.pixelColor(8, y).name(),
                QColor(palette["background_alt"]).name(),
            )
            disabled_thumb = disabled.pixelColor(29, y)
            self.assertEqual(
                disabled_thumb.name(), QColor(palette["muted"]).name()
            )

            switch.setEnabled(True)
            switch.click()
            self.assertFalse(switch.isChecked())
            self.assertTrue(switch.isCheckable())
            switch.close()
            switch.deleteLater()
            self.app.processEvents()

    def test_white_palette_uses_light_frame_colors_for_every_theme(self):
        from ui.preferences import THEME_PRESETS, palette_for_mode

        for name, theme in THEME_PRESETS.items():
            with self.subTest(theme=name):
                white = palette_for_mode(theme, True)
                self.assertEqual(white["frame_color"], white["border"])
                self.assertEqual(white["frame_color"], "#ded8e7")
                dark = palette_for_mode(theme, False)
                self.assertEqual(dark["frame_color"], theme["frame_color"])

    def test_home_dashboard_uses_real_library_counts_progress_and_empty_states(self):
        rows = [
            {
                "id": 101, "title": "Watching Work", "type": "ANIME", "format": "TV",
                "status": "Watching", "episodes": 12, "progress_episodes": 4,
                "progress_chapters": 0, "progress_volumes": 0, "chapters": None,
                "volumes": None, "start_year": 2024, "cover_url": None,
                "cover_path": None, "added_date": "2026-10-12",
            },
            {
                "id": 102, "title": "Finished Work", "type": "ANIME", "format": "TV",
                "status": "Completed", "episodes": 8, "progress_episodes": 8,
                "progress_chapters": 0, "progress_volumes": 0, "chapters": None,
                "volumes": None, "start_year": 2023, "cover_url": None,
                "cover_path": None, "added_date": "2026-10-10",
            },
            {
                "id": -103, "title": "Reading Work", "type": "MANGA", "format": "NOVEL",
                "status": "Reading", "episodes": None, "progress_episodes": 0,
                "progress_chapters": 6, "progress_volumes": 1, "chapters": 30,
                "volumes": 4, "start_year": 2022, "cover_url": None,
                "cover_path": None, "added_date": "2026-10-09",
            },
        ]
        with patch("ui.pages.home_page.get_all_library", return_value=rows):
            with patch("ui.pages.home_page.RecommendationsPage.refresh", autospec=True):
                page = HomePage()
            self.app.processEvents()
            self.assertEqual(
                page._home_counts,
                {"all": 3, "in_progress": 2, "completed": 1, "planned": 0},
            )
            self.assertEqual(page._continue_ids, {101, -103})
            self.assertEqual(page._recent_ids, [101, 102, -103])
            captions = [
                label.text()
                for label in page.findChildren(QLabel, "homeTrackProgress")
            ]
            self.assertIn("Next episode 5 · 4/12 logged", captions)
            self.assertTrue(any("6/30 chapters" in text for text in captions))
            self.assertTrue(any("1/4 volumes" in text for text in captions))

            self.assertIsNone(page.findChild(QPushButton, "homePrimaryAction"))
            self.assertIsNone(page.findChild(QPushButton, "homeSecondaryAction"))
            page.close()
            page.deleteLater()
            self.app.processEvents()

        with (
            patch("ui.pages.home_page.get_all_library", return_value=[]),
            patch("ui.pages.home_page.RecommendationsPage.refresh", autospec=True),
        ):
            empty_page = HomePage()
            self.app.processEvents()
            self.assertEqual(
                empty_page._home_counts,
                {"all": 0, "in_progress": 0, "completed": 0, "planned": 0},
            )
            self.assertIsNotNone(
                empty_page.findChild(QLabel, "homeEmptyState")
            )
            empty_page.close()
            empty_page.deleteLater()
            self.app.processEvents()

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
                    self.assertEqual(
                        [
                            settings_page.category_tabs.tabText(index)
                            for index in range(settings_page.category_tabs.count())
                        ],
                        [
                            "General", "Appearance", "Library",
                            "Integrations", "Data & Storage", "Advanced",
                        ],
                    )
                    expected = set(preferences.BUNDLE_OPTION_KEYS)
                    self.assertEqual(set(wizard.bundle_checkboxes), expected)
                    self.assertEqual(set(settings_page.bundle_checkboxes), expected)
                    self.assertIsNotNone(wizard.findChild(QCheckBox, "lightModeToggle"))
                    settings_toggle = settings_page.findChild(QCheckBox, "lightModeToggle")
                    self.assertIsNotNone(settings_toggle)
                    from ui.widgets.switch_control import SwitchControl
                    self.assertIsInstance(settings_toggle, SwitchControl)

                    original_theme = preferences.get("theme_preset")
                    original_accent = preferences.get("accent")
                    settings_toggle.setChecked(True)
                    self.assertTrue(preferences.get("light_mode"))
                    self.assertEqual(preferences.get("theme_preset"), original_theme)
                    self.assertEqual(preferences.get("accent"), original_accent)
                    settings_toggle.setChecked(False)
                    wizard.light_mode_toggle.setChecked(True)
                    self.assertTrue(wizard.light_mode)
                    self.assertIsInstance(wizard.light_mode_toggle, SwitchControl)

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
        from ui.branding import WordmarkLabel

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
                            "home", "collections", "search",
                            "calendar", "favorites", "work_detail", "entity_profile", "settings",
                        },
                    )
                    self.assertFalse(window.windowIcon().isNull())
                    self.assertIsInstance(window.brand_word, WordmarkLabel)
                    self.assertTrue(window.brand_word._renderer.isValid())
                    self.assertEqual(window.brand_word.width(), 222)
                    self.assertEqual(window.brand_word.height(), 58)
                    self.assertFalse(window.brand_word.hasScaledContents())
                    self.assertEqual(window.findChild(QFrame, "sidebar").width(), 270)
                    self.assertEqual(window.navigation_buttons["home"].minimumHeight(), 52)
                    self.assertEqual(window.navigation_buttons["home"].iconSize().width(), 20)
                    self.assertEqual(window.navigation_buttons["settings"].minimumHeight(), 52)
                    self.assertEqual(window.brand_word.accessibleName(), "NekoTrack")
                    self.assertIs(
                        window.recommendations_page,
                        window.home_page.recommendations_page,
                    )
                    self.assertTrue(window.recommendations_page.embedded)
                    self.assertEqual(
                        {name: button.text() for name, button in window.navigation_buttons.items()},
                        {
                            "home": "Home",
                            "collections": "Library",
                            "search": "Search",
                            "calendar": "Calendar",
                            "favorites": "Favorites",
                            "settings": "Settings",
                        },
                    )
                    self.assertTrue(
                        all(not button.icon().isNull() for button in window.navigation_buttons.values())
                    )
                    sidebar = window.findChild(QFrame, "sidebar")
                    self.assertIsNotNone(sidebar)
                    sidebar_layout = sidebar.layout()
                    # Flexible spacers bracket the five main destinations so
                    # the group sits vertically centered while Settings stays last.
                    self.assertIsNotNone(sidebar_layout.itemAt(2).spacerItem())
                    self.assertIsNotNone(sidebar_layout.itemAt(8).spacerItem())
                    self.assertIs(
                        sidebar_layout.itemAt(9).widget(),
                        window.navigation_buttons["settings"],
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


    def test_entity_profile_queries_request_raw_markdown_descriptions(self):
        import api

        with patch.object(api, "anilist_request", return_value={
            "Character": {"id": 9, "description": "[YouTube]([https://youtube.com/](https://youtube.com/)[@Example](https://anilist.co/user/Example)-channel)"}
        }) as request:
            profile = api.get_entity_profile("character", 9)

        self.assertEqual(
            profile["description"],
            "[YouTube](https://youtube.com/@Example-channel)",
        )
        query = request.call_args.args[0]
        self.assertIn("description", query)
        self.assertIn("descriptionHtml: description(asHtml: true)", query)


    def test_profile_biography_uses_rich_text_without_about_label(self):
        description = (
            '<p>A long <strong>formatted</strong> biography with '
            '<a href="https://example.com/profile">a link</a>.</p>'
        )
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
                bio = header.findChild(QTextBrowser, "profileDescription")
                self.assertIsNotNone(bio)
                self.assertTrue(bio.isReadOnly())
                self.assertTrue(bio.openExternalLinks())
                rendered = bio.toHtml()
                self.assertIn("formatted", rendered)
                self.assertIn("https://example.com/profile", rendered)
                self.assertIsNotNone(header.findChild(QLabel, "profileName"))
                self.assertFalse(
                    any(
                        label.text().strip().casefold() == "about"
                        for label in header.findChildren(QLabel)
                    )
                )
                self.assertEqual(bio.verticalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)
                self.assertGreater(bio.maximumHeight(), 210)
            finally:
                page.close()
                page.deleteLater()
                self.app.processEvents()


    def test_malformed_anilist_youtube_links_render_as_clean_clickable_links(self):
        malformed_links = [
            (
                "[Youtube]\\([https://youtube.com/](https://youtube.com/)"
                "[@officialyoutubechannel3974]"
                "(https://anilist.co/user/officialyoutubechannel3974)"
                "?si=9AjlJ6Ujj2Vw1CiU)",
                "[Youtube](https://youtube.com/@officialyoutubechannel3974?si=9AjlJ6Ujj2Vw1CiU)",
                "https://youtube.com/@officialyoutubechannel3974?si=9AjlJ6Ujj2Vw1CiU",
            ),
            (
                "[YouTube]\\([https://www.youtube.com/](https://www.youtube.com/)"
                "[@Ueda](https://anilist.co/user/Ueda)-Kana)",
                "[YouTube](https://www.youtube.com/@Ueda-Kana)",
                "https://www.youtube.com/@Ueda-Kana",
            ),
        ]
        for malformed, expected_markdown, expected_url in malformed_links:
            with self.subTest(expected_url=expected_url):
                self.assertEqual(
                    EntityProfilePage._normalize_profile_description(malformed),
                    expected_markdown,
                )

        # Also cover entity-escaped Markdown punctuation in HTML mode.
        encoded_link = (
            "&#91;Youtube&#93;&#92;("
            "&#91;https://youtube.com/&#93;(https://youtube.com/)"
            "&#91;@officialyoutubechannel3974&#93;"
            "(https://anilist.co/user/officialyoutubechannel3974)"
            "?si=9AjlJ6Ujj2Vw1CiU)"
        )
        self.assertIn(
            "https://youtube.com/@officialyoutubechannel3974?si=9AjlJ6Ujj2Vw1CiU",
            EntityProfilePage._normalize_profile_description(encoded_link),
        )

        description = "<p>" + "</p><p>".join(
            raw for raw, _expected, _url in malformed_links
        ) + "</p>"
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
                header = page.content_layout.itemAt(0).widget()
                bio = header.findChild(QTextBrowser, "profileDescription")
                self.assertIsNotNone(bio)
                self.assertTrue(bio.openExternalLinks())
                rendered = bio.toHtml()
                for _raw, _expected, expected_url in malformed_links:
                    self.assertIn(expected_url, rendered)
                self.assertNotIn("https://anilist.co/user/officialyoutubechannel3974", rendered)
                self.assertNotIn("https://anilist.co/user/Ueda", rendered)
                self.assertNotIn("[Youtube]\\(", rendered)
                self.assertNotIn("[YouTube]\\(", rendered)
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
                    "staffMedia": {
                        "edges": [
                            {
                                "staffRole": "Voice Director",
                                "node": {
                                    "id": 21356,
                                    "type": "ANIME",
                                    "format": "TV",
                                    "title": {"english": "Example Staff Work"},
                                    "coverImage": {},
                                    "startDate": {"year": 2017},
                                },
                            },
                            {
                                "staffRole": "Series Composition",
                                "node": {
                                    "id": 21356,
                                    "type": "ANIME",
                                    "format": "TV",
                                    "title": {"english": "Example Staff Work"},
                                    "coverImage": {},
                                    "startDate": {"year": 2017},
                                },
                            },
                        ],
                    },
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
                self.assertIn("Staff credits", section_titles)
                staff_section = next(
                    frame for frame in active_widgets
                    if (
                        isinstance(frame, QFrame)
                        and frame.objectName() == "profileSection"
                        and (title := frame.findChild(QLabel, "profileSectionTitle")) is not None
                        and title.text() == "Staff credits"
                    )
                )
                staff_cards = staff_section.findChildren(ProfileWorkCreditCard)
                self.assertEqual(len(staff_cards), 1)
                credit_label = staff_cards[0].findChild(QLabel, "profileCreditRole")
                self.assertIsNotNone(credit_label)
                self.assertEqual(
                    credit_label.text(), "Voice Director · Series Composition"
                )
                content_layout = staff_cards[0].layout().itemAt(1).layout()
                content_names = [
                    content_layout.itemAt(index).widget().objectName()
                    for index in range(content_layout.count())
                    if content_layout.itemAt(index).widget() is not None
                ]
                self.assertLess(content_names.index("title"), content_names.index("profileCreditRole"))
                self.assertLess(content_names.index("profileCreditRole"), content_names.index("meta"))
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
                self.assertTrue(all(card.width() >= 430 for card in cards))
                self.assertTrue(all(card.height() == 140 for card in cards))
                self.assertEqual(
                    [card.findChild(QLabel, "mediaCreditRole").text() for card in cards],
                    ["Main", "Supporting", "Background"],
                )
                for card in cards:
                    self.assertEqual(len(card.character_cards), 1)
                    self.assertEqual(card.character_artwork.width(), 88)
                    self.assertEqual(card.character_artwork.height(), 116)
                    self.assertIsInstance(card.character_artwork, CharacterArtwork)
                    self.assertIsNone(card.character_artwork.findChild(QLabel))
                    self.assertEqual(card.findChild(QLabel, "creditCharacterName").text(), card.character_artwork.character["character_name"])
                    self.assertEqual(card.cover.width(), 88)
                    self.assertEqual(card.cover.height(), 116)
                    self.assertEqual(card.styleSheet(), card_stylesheet())
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
                self.assertTrue(all(card.mode == "library" for card in cards))
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
