import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget

from ui.pages.work_detail_page import WorkDetailPage


class DetailSkeletonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_pending_detail_view_uses_section_and_episode_skeletons(self):
        page = WorkDetailPage()
        with (
            patch.object(page, "_local_detail_ready", return_value=(False, False)),
            patch.object(page, "_hero", return_value=QFrame()),
            patch.object(page, "_mangabaka_section", return_value=None),
            patch.object(page, "_is_reading_media", return_value=False),
        ):
            content, ready = page._build_detail_content([12345], defer_missing=False)

        self.assertFalse(ready)
        section_titles = {
            frame.property("_skeleton_section_title")
            for frame in content.findChildren(QFrame, "detailSkeletonSection")
        }
        self.assertEqual(section_titles, {"Characters", "Staff", "Relations"})
        self.assertEqual(
            len(content.findChildren(QFrame, "detailSkeletonEpisodeCard")),
            4,
        )
        self.assertIsNotNone(
            content.findChild(QLabel, "detailEpisodeLoadingLabel")
        )
        self.assertFalse(
            any(label.text() == "Loading details…" for label in content.findChildren(QLabel))
        )

        content.deleteLater()
        page.deleteLater()
        self.app.processEvents()

    def test_missing_catalog_work_is_not_treated_as_an_empty_season(self):
        page = WorkDetailPage()
        page.work = {
            "id": 12345,
            "type": "ANIME",
            "format": "TV",
        }

        with (
            patch("ui.pages.work_detail_page.characters_are_loaded", return_value=False),
            patch("ui.pages.work_detail_page.get_work", return_value=None),
            patch("ui.pages.work_detail_page.get_episodes", return_value=[]),
        ):
            self.assertEqual(page._local_detail_ready([12345]), (False, False))

        page.deleteLater()
        self.app.processEvents()

    def test_episode_section_waits_when_selected_season_row_is_missing(self):
        page = WorkDetailPage()
        page.work = {
            "id": 12345,
            "type": "ANIME",
            "format": "TV",
            "episodes": 12,
            "title": {"romaji": "Example Series", "english": None},
            "_series_members": [{
                "id": 12345,
                "title": {"romaji": "Example Series", "english": None},
                "start_year": 2020,
                "start_month": 1,
                "start_day": 1,
                "episodes": 12,
                "format": "TV",
            }],
        }
        page._selected_episode_work_id = 12345

        with (
            patch("ui.pages.work_detail_page.get_work", return_value=None),
            patch("ui.pages.work_detail_page.get_episodes", return_value=[]),
            patch.object(page, "_start_episode_sync") as sync,
        ):
            frame = page._episodes_section()

        self.assertIsNotNone(
            frame.findChild(QLabel, "detailEpisodeLoadingLabel")
        )
        sync.assert_not_called()
        frame.deleteLater()
        page.deleteLater()
        self.app.processEvents()

    def test_deferred_episode_render_retries_pending_import_without_crashing(self):
        page = WorkDetailPage()
        page.work = {
            "id": 12345,
            "type": "ANIME",
            "format": "TV",
            "_series_members": [{"id": 12345}],
        }
        page._detail_build_token = 7
        content = QWidget()
        layout = QVBoxLayout(content)
        host = QFrame(content)
        layout.addWidget(host)
        page.scroll_area.setWidget(content)
        callbacks = []

        with (
            patch("ui.pages.work_detail_page.get_work", return_value=None),
            patch(
                "ui.pages.work_detail_page.QTimer.singleShot",
                side_effect=lambda delay, callback: callbacks.append((delay, callback)),
            ),
        ):
            page._populate_episode_section(7, content, host)

        self.assertEqual(len(callbacks), 1)
        self.assertEqual(callbacks[0][0], 250)
        self.assertGreaterEqual(layout.indexOf(host), 0)

        page.deleteLater()
        self.app.processEvents()

    def test_deferred_episode_render_shows_recovery_message_after_timeout(self):
        page = WorkDetailPage()
        page.work = {
            "id": 12345,
            "type": "ANIME",
            "format": "TV",
            "_series_members": [{"id": 12345}],
        }
        page._detail_build_token = 9
        content = QWidget()
        layout = QVBoxLayout(content)
        host = QFrame(content)
        layout.addWidget(host)
        page.scroll_area.setWidget(content)

        with patch("ui.pages.work_detail_page.get_work", return_value=None):
            page._populate_episode_section(9, content, host, attempt=120)

        replacement = content.findChild(QFrame, "section")
        self.assertIsNotNone(replacement)
        self.assertTrue(any(
            "taking longer than expected" in label.text()
            for label in replacement.findChildren(QLabel)
        ))

        page.deleteLater()
        self.app.processEvents()

    def test_hero_cover_distinguishes_loading_from_unavailable(self):
        page = WorkDetailPage()
        page._apply_detail_styles()
        label = QLabel(page)
        label.setObjectName("detailHeroCover")
        label.resize(235, 335)

        page._set_cover_placeholder(label, True, "Loading artwork…")
        self.assertTrue(label.property("coverLoading"))
        self.assertEqual(label.text(), "Loading artwork…")

        page._set_cover_placeholder(label, False, "COVER UNAVAILABLE")
        self.assertFalse(label.property("coverLoading"))
        self.assertEqual(label.text(), "COVER UNAVAILABLE")

        page._set_cover_placeholder(label, False, "NO COVER")
        self.assertFalse(label.property("coverLoading"))
        self.assertEqual(label.text(), "NO COVER")
        page.deleteLater()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
