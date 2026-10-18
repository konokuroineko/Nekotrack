"""Regression tests for V1 update safety and recommendation feed stability."""
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QFrame, QLabel

import ui.preferences as preferences
import updater
from ui.pages.home_page import HomePage
from ui.pages.recommendations_page import RecommendationsPage
from ui.pages.settings_page import SettingsPage
from ui.theme import _CHECKBOX_CHECKMARK, application_stylesheet
from ui.widgets.work_card import WorkCard


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


def minimal_pe_payload(body=b"nekotrack-test"):
    dos_header = bytearray(64)
    dos_header[:2] = b"MZ"
    pe_offset = 0x80
    dos_header[0x3C:0x40] = pe_offset.to_bytes(4, "little")
    return bytes(dos_header) + bytes(pe_offset - len(dos_header)) + b"PE\0\0" + body


class V1StabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        self.app.processEvents()
        MemorySettings.stores.clear()

    def test_checkbox_styles_include_a_visible_checkmark_asset(self):
        stylesheet = application_stylesheet()
        self.assertIn("QCheckBox::indicator:checked", stylesheet)
        self.assertIn('image: url("', stylesheet)
        self.assertTrue(Path(_CHECKBOX_CHECKMARK).is_file())

    def test_update_preferences_default_to_stable_and_are_normalized(self):
        with patch.object(preferences, "QSettings", MemorySettings):
            self.assertTrue(preferences.get("auto_check_updates"))
            self.assertEqual(preferences.get("update_channel"), "stable")
            preferences.set_value("auto_check_updates", False)
            preferences.set_value("update_channel", "PREVIEW")
            self.assertFalse(preferences.get("auto_check_updates"))
            self.assertEqual(preferences.get("update_channel"), "preview")
            preferences.set_value("update_channel", "anything-else")
            self.assertEqual(preferences.get("update_channel"), "stable")

    def test_settings_page_exposes_manual_update_and_rollback_actions(self):
        with (
            patch.object(preferences, "QSettings", MemorySettings),
            patch("ui.pages.settings_page.get_all_library", return_value=[]),
        ):
            page = SettingsPage()
            try:
                channel = page.findChild(QComboBox, "updateChannelCombo")
                self.assertIsNotNone(channel)
                self.assertEqual(channel.currentData(), "stable")
                update_toggle = next(
                    check for check in page.findChildren(QCheckBox)
                    if check.accessibleName() == "Check for updates at startup"
                )
                self.assertTrue(update_toggle.isChecked())

                requested = []
                rolled_back = []
                page.update_check_requested.connect(lambda: requested.append(True))
                page.rollback_requested.connect(lambda: rolled_back.append(True))
                from PySide6.QtWidgets import QPushButton
                page.findChild(QPushButton, "checkUpdatesButton").click()
                page.findChild(QPushButton, "rollbackUpdateButton").click()
                self.assertEqual(requested, [True])
                self.assertEqual(rolled_back, [True])
            finally:
                page.close()
                page.deleteLater()
                self.app.processEvents()

    def test_update_checker_uses_stable_or_preview_channel(self):
        url = "https://github.com/konokuroineko/Nekotrack/releases/tag/v1.0.1-beta.1"
        asset_url = (
            "https://github.com/konokuroineko/Nekotrack/releases/download/"
            "v1.0.1-beta.1/NekoTrack.exe"
        )
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [{
            "tag_name": "v1.0.1-beta.1",
            "html_url": url,
            "prerelease": True,
            "draft": False,
            "assets": [{
                "name": "NekoTrack.exe",
                "browser_download_url": asset_url,
                "digest": "sha256:" + "a" * 64,
            }],
        }]

        stable_updates, stable_none = [], []
        stable = updater.UpdateChecker("1.0.0", include_prereleases=False)
        stable.update_available.connect(stable_updates.append)
        stable.no_update_available.connect(lambda: stable_none.append(True))
        with patch.object(updater.requests, "get", return_value=response):
            stable.run()
        self.assertEqual(stable_updates, [])
        self.assertEqual(stable_none, [True])

        preview_updates, preview_none = [], []
        preview = updater.UpdateChecker("1.0.0", include_prereleases=True)
        preview.update_available.connect(preview_updates.append)
        preview.no_update_available.connect(lambda: preview_none.append(True))
        with patch.object(updater.requests, "get", return_value=response):
            preview.run()
        self.assertEqual(preview_none, [])
        self.assertEqual(len(preview_updates), 1)
        self.assertEqual(preview_updates[0].version, "1.0.1-beta.1")
        self.assertEqual(preview_updates[0].asset_name, "NekoTrack.exe")
        self.assertEqual(preview_updates[0].digest, "sha256:" + "a" * 64)
        self.assertTrue(updater._is_trusted_release_asset_url(asset_url, expected_name="NekoTrack.exe"))
        self.assertFalse(updater._is_trusted_release_asset_url(asset_url, expected_name="wrong.exe"))

    def test_update_helper_is_copied_to_durable_app_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "_MEI12345" / "safe_update.ps1"
            source.parent.mkdir()
            source.write_text("Write-Output 'safe'", encoding="utf-8")
            data_dir = root / "isolated-preview-data"
            persistent = updater.persist_update_helper(source, data_dir)
            self.assertTrue(persistent.is_file())
            self.assertEqual(persistent.read_text(encoding="utf-8"), "Write-Output 'safe'")
            self.assertEqual(persistent.parent, (data_dir / "update_helpers").resolve())
            source.unlink()
            self.assertTrue(persistent.is_file())
            self.assertEqual(updater.persist_update_helper(persistent, data_dir), persistent)

    def test_home_uses_library_bundle_and_preserves_custom_appearance(self):
        member_a = {
            "id": 501, "title": "Original Series", "type": "ANIME",
            "status": "Watching", "episodes": 12, "progress_episodes": 6,
            "start_year": 2018, "cover_path": "custom-cover.png",
        }
        member_b = {
            "id": 502, "title": "Second Season", "type": "ANIME",
            "status": "Watching", "episodes": 12, "progress_episodes": 3,
            "start_year": 2020, "cover_path": "season-cover.png",
        }
        group = {
            "id": 501, "title": "My custom Re:Zero bundle", "type": "ANIME",
            "status": "Watching", "episodes": 24, "progress_episodes": 9,
            "cover_path": "custom-cover.png", "_series_count": 2,
            "_series_members": [member_a, member_b],
            "_bundle_summary": "2 seasons",
        }
        with (
            patch.object(HomePage, "_read_library", return_value=[member_a, member_b]),
            patch("ui.pages.home_page.get_library_series", return_value=[group]) as grouper,
            patch.object(RecommendationsPage, "refresh", autospec=True),
            patch("ui.pages.home_page.get_release_reminders", return_value=[]),
            patch("ui.pages.home_page.get_episodes", return_value=[]),
        ):
            page = HomePage()
        try:
            grouper.assert_called_once()
            cards = page.findChildren(WorkCard)
            self.assertEqual(len(cards), 2)
            self.assertTrue(all(card.card_size <= 112 for card in cards))
            self.assertTrue(all(card.work.get("title") == "My custom Re:Zero bundle" for card in cards))
            self.assertTrue(all(card.work.get("cover_path") == "custom-cover.png" for card in cards))
            prepared = page._prepare_home_work(group)
            self.assertEqual(prepared["progress_episodes"], 9)
            self.assertEqual(prepared["episodes"], 24)
            self.assertEqual(prepared["_home_status"], "watching")
        finally:
            page.close()
            page.deleteLater()
            self.app.processEvents()

    def test_update_checker_prefers_portable_asset_for_isolated_preview_install(self):
        releases = [{
            "tag_name": "v1.0.1-beta.2",
            "html_url": "https://github.com/konokuroineko/Nekotrack/releases/tag/v1.0.1-beta.2",
            "prerelease": True,
            "draft": False,
            "assets": [
                {
                    "name": "NekoTrack-Setup-1.0.1.exe",
                    "browser_download_url": "https://github.com/konokuroineko/Nekotrack/releases/download/v1.0.1-beta.2/NekoTrack-Setup-1.0.1.exe",
                },
                {
                    "name": "NekoTrack.exe",
                    "browser_download_url": "https://github.com/konokuroineko/Nekotrack/releases/download/v1.0.1-beta.2/NekoTrack.exe",
                },
            ],
        }]
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = releases
        updates = []
        checker = updater.UpdateChecker(
            "1.0.0", include_prereleases=True, preferred_asset="portable"
        )
        checker.update_available.connect(updates.append)
        with patch.object(updater.requests, "get", return_value=response):
            checker.run()
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].asset_name, "NekoTrack.exe")

    def test_update_backup_preserves_executable_and_consistent_database_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_dir = root / "install"
            data_dir = root / "AppData" / "NekoTrack"
            install_dir.mkdir()
            data_dir.mkdir(parents=True)
            executable = install_dir / "NekoTrack.exe"
            payload = minimal_pe_payload(b"previous build")
            executable.write_bytes(payload)
            database = data_dir / "anime_tracker.db"
            connection = sqlite3.connect(database)
            try:
                connection.execute("CREATE TABLE progress (work_id INTEGER, episodes INTEGER)")
                connection.execute("INSERT INTO progress VALUES (42, 7)")
                connection.commit()
            finally:
                connection.close()

            backup = updater.create_update_backup(
                executable, data_dir, database, "1.0.0", "1.0.1-beta.1"
            )
            self.assertEqual((backup / "NekoTrack.exe").read_bytes(), payload)
            self.assertEqual(executable.read_bytes(), payload)
            self.assertTrue((backup / "manifest.json").is_file())
            manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["database_backed_up"])
            self.assertEqual(manifest["from_version"], "1.0.0")
            self.assertEqual(manifest["to_version"], "1.0.1-beta.1")

            snapshot = sqlite3.connect(backup / "anime_tracker.db")
            original = sqlite3.connect(database)
            try:
                self.assertEqual(snapshot.execute("SELECT * FROM progress").fetchall(), [(42, 7)])
                self.assertEqual(original.execute("SELECT * FROM progress").fetchall(), [(42, 7)])
            finally:
                snapshot.close()
                original.close()

            self.assertEqual(updater.find_previous_update_backup(data_dir), backup)

    def test_preview_launcher_guards_live_data_and_never_overwrites_preview_data(self):
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "installer" / "run-preview.ps1").read_text(encoding="utf-8")
        self.assertIn("NEKOTRACK_DATA_DIR", launcher)
        self.assertIn("Preview data must be separate from the live", launcher)
        self.assertIn("Refusing to overwrite it", launcher)
        self.assertIn("Copy-Item", launcher)
        self.assertIn("Close NekoTrack before copying", launcher)

    def test_installer_build_includes_recovery_helper_and_rollback_shortcut(self):
        root = Path(__file__).resolve().parents[1]
        helper = root / "installer" / "safe_update.ps1"
        installer = (root / "installer" / "NekoTrack.iss").read_text(encoding="utf-8")
        build = (root / "installer" / "build-installer.ps1").read_text(encoding="utf-8")
        self.assertTrue(helper.is_file())
        self.assertIn("safe_update.ps1", installer)
        self.assertIn("RollbackLatest", installer)
        self.assertIn("installer\\safe_update.ps1;installer", build)
        self.assertIn("[string]$VersionOverride", build)
        self.assertIn('--add-data "$versionSource;."', build)
        self.assertIn("UTF8Encoding($false)", build)
        self.assertIn("if ($VersionOverride -notmatch '", build)
        self.assertIn("throw \"VersionOverride must be a NekoTrack version", build)
        self.assertIn("finally {", build)
        self.assertIn("Pop-Location", build)
        self.assertEqual(build.count("if ($VersionOverride -notmatch"), 1)
        self.assertIn(r"if ($VersionOverride -notmatch '^\d+\.\d+\.\d+(?:-(?:dev|alpha|beta|rc)(?:\.\d+)?)?$')", build)
        self.assertNotIn('--add-data "VERSION;."', build)
        script_text = helper.read_text(encoding="utf-8")
        self.assertIn("The previous executable was restored from backup.", script_text)
        self.assertIn("if (-not (Start-CandidateAndWaitForHealth $ExpectedVersion $AttemptId))", script_text)

    def test_recommendation_page_reuses_search_loading_skeleton_cards(self):
        from ui.widgets.skeleton_card import SkeletonCard

        page = RecommendationsPage(embedded=True)
        try:
            page._render_loading_skeletons(8)
            cards = page.findChildren(QFrame, "skeleton")
            self.assertEqual(len(cards), 8)
            self.assertTrue(all(isinstance(card, SkeletonCard) for card in cards))
            self.assertTrue(all(card.width() > 0 and card.height() > 0 for card in cards))
        finally:
            page.request_shutdown()
            page.close()
            page.deleteLater()
            self.app.processEvents()

    def test_long_bundle_indicator_is_elided_instead_of_cut_off(self):
        summary = "Season 1 · Season 2 · OVAs · Specials · Bonus episodes"
        with patch.object(WorkCard, "_load_cover"):
            card = WorkCard(
                {
                    "id": 987654,
                    "title": "Re:Zero",
                    "type": "ANIME",
                    "_series_count": 5,
                    "_bundle_summary": summary,
                },
                mode="library",
            )
        try:
            self.assertNotEqual(card.series_info_label.text(), summary)
            self.assertTrue(card.series_info_label.text().endswith("…"))
            self.assertEqual(card.series_info_label.toolTip(), summary)
        finally:
            card.deleteLater()
            self.app.processEvents()

    def test_pagination_appends_new_items_without_reranking_old_items(self):
        page = RecommendationsPage(embedded=True)
        try:
            page._stop_event = threading.Event()
            page._results = [{"id": 101}, {"id": 102}]
            page._worker = SimpleNamespace(
                catalog_only=True,
                catalog_next_page=3,
                catalog_has_next=True,
                history={},
                favorite_works=[],
                favorite_entities=[],
                credit_profile={},
                source_weights={},
                voice_language="ALL",
            )
            page._render_results = Mock()
            incoming = [{"id": 103}, {"id": 104}, {"id": 102}]
            with (
                patch(
                    "ui.pages.recommendations_page.rank_candidates",
                    side_effect=lambda items, **kwargs: list(reversed(items)),
                ) as rank,
                patch(
                    "ui.pages.recommendations_page.inject_rare_exploration",
                    side_effect=lambda items, **kwargs: items,
                ),
            ):
                page._recommendations_ready(incoming)

            self.assertEqual([item["id"] for item in page._results], [101, 102, 104, 103])
            ranked_batch = rank.call_args.args[0]
            self.assertEqual([item["id"] for item in ranked_batch], [103, 104])
            page._render_results.assert_called_once_with(
                preserve_scroll=True, animate_reflow=False
            )
        finally:
            page.request_shutdown()
            page.close()
            page.deleteLater()
            self.app.processEvents()

    def test_home_uses_normal_size_continue_cards_and_removes_recent_section(self):
        from unittest.mock import patch
        library = [
            {"id": 1, "type": "ANIME", "title": {"english": "Example One"}, "status": "Watching", "progress_episodes": 2, "episodes": 12},
            {"id": 2, "type": "ANIME", "title": {"english": "Example Two"}, "status": "Rewatching", "progress_episodes": 4, "episodes": 24},
            {"id": 3, "type": "ANIME", "title": {"english": "Example Three"}, "status": "Planning", "progress_episodes": 0, "episodes": 12},
        ]
        with (
            patch.object(HomePage, "_read_library", return_value=library),
            patch("ui.pages.home_page.get_library_series", side_effect=lambda rows: rows),
            patch.object(RecommendationsPage, "refresh", autospec=True),
            patch("ui.pages.home_page.get_release_reminders", return_value=[]),
            patch("ui.pages.home_page.get_episodes", return_value=[]),
        ):
            page = HomePage()
        try:
            page.show()
            self.app.processEvents()
            cards = page.findChildren(WorkCard)
            self.assertEqual(len(cards), 2)
            self.assertGreater(min(card.card_size for card in cards), 112)
            section_titles = [
                label.text() for label in page.findChildren(QLabel, "homeSectionTitle")
            ]
            self.assertNotIn("Recently added", section_titles)
            captions = page.findChildren(QLabel, "homeTrackProgress")
            self.assertTrue(all(caption.maximumHeight() > 16 for caption in captions))
            self.assertEqual(page.content_layout.indexOf(page.recommendations_page), 2)
        finally:
            page.close()
            page.deleteLater()
            self.app.processEvents()



if __name__ == "__main__":
    unittest.main()
