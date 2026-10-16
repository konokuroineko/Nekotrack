import datetime
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QFrame, QWidget, QPushButton

from ui.pages.home_page import HomePage
from ui.pages.recommendations_page import RecommendationsPage


class HomeDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_empty_home(self):
        patches = [
            patch.object(HomePage, "_read_library", return_value=[]),
            patch.object(RecommendationsPage, "refresh", autospec=True),
            patch("ui.pages.home_page.get_release_reminders", return_value=[]),
            patch("ui.pages.home_page.get_episodes", return_value=[]),
        ]
        for candidate in patches:
            candidate.start()
            self.addCleanup(candidate.stop)
        page = HomePage()
        self.addCleanup(page.close)
        self.addCleanup(page.deleteLater)
        self.addCleanup(self.app.processEvents)
        return page

    def test_home_removes_hero_and_summary_cards_and_embeds_recommendations(self):
        with (
            patch.object(HomePage, "_read_library", return_value=[]),
            patch.object(RecommendationsPage, "refresh", autospec=True) as refresh_mock,
            patch("ui.pages.home_page.get_release_reminders", return_value=[]),
            patch("ui.pages.home_page.get_episodes", return_value=[]),
        ):
            page = HomePage()

        try:
            page.show()
            self.app.processEvents()
            self.assertTrue(page.recommendations_page.embedded)
            self.assertEqual(page.content_layout.indexOf(page.recommendations_page), 3)
            refresh_mock.assert_called_once_with(
                page.recommendations_page, library_rows=[]
            )
            self.assertIs(
                page.content.findChild(RecommendationsPage),
                page.recommendations_page,
            )
            self.assertIsNone(page.content.findChild(QFrame, "homeHero"))
            self.assertIsNone(page.content.findChild(QWidget, "homeStatsRow"))
            texts = {label.text() for label in page.findChildren(QLabel)}
            self.assertNotIn("YOUR PERSONAL MEDIA SPACE", texts)
            self.assertFalse(
                {"ALL TITLES", "IN PROGRESS", "COMPLETED", "PLANNED"} & texts
            )
            self.assertIn("Upcoming releases", texts)
            self.assertIsNotNone(page.content.findChild(QPushButton, "homeCalendarAction"))
        finally:
            page.close()
            page.deleteLater()
            self.app.processEvents()

    def test_upcoming_release_preview_uses_cached_dates_and_saved_reminders(self):
        page = self._make_empty_home()
        today = datetime.date(2026, 10, 16)
        library = [
            {"id": 1, "type": "ANIME", "title": "Anime One"},
            {"id": 2, "type": "ANIME", "title": "Anime Two"},
            {"id": 3, "type": "MANGA", "title": "Manga is not an anime schedule"},
        ]
        episodes = {
            1: [
                {"episode_number": 2, "title": "Special episode", "air_date": "2026-10-18"},
                {"episode_number": 3, "title": "Episode 3", "air_date": "2026-10-20"},
                {"episode_number": 4, "title": "Old episode", "air_date": "2026-10-15"},
                {"episode_number": 5, "title": "Too far away", "air_date": "2026-12-16"},
                {"episode_number": 6, "title": "Bad date", "air_date": "not-a-date"},
            ],
            2: [
                {"episode_number": 1, "title": None, "air_date": "2026-10-16"},
            ],
        }
        with (
            patch(
                "ui.pages.home_page.get_release_reminders",
                return_value=[{"work_id": 1, "episode_number": 2}],
            ),
            patch(
                "ui.pages.home_page.get_episodes",
                side_effect=lambda work_id: episodes.get(work_id, []),
            ) as get_episodes_mock,
        ):
            events = page._upcoming_release_rows(library, today=today)

        self.assertEqual(
            [(row["work_id"], row["episode_number"]) for row in events],
            [(2, 1), (1, 2), (1, 3)],
        )
        self.assertTrue(events[1]["_reminder_enabled"])
        self.assertEqual(events[0]["episode_title"], "Episode 1")
        self.assertEqual(events[2]["episode_title"], "Episode 3")
        self.assertEqual(get_episodes_mock.call_count, 2)

    def test_reminder_toggle_saves_and_refreshes_home(self):
        page = self._make_empty_home()
        with (
            patch("ui.pages.home_page.set_release_reminder") as save_reminder,
            patch.object(page, "refresh") as refresh_mock,
        ):
            page._toggle_release_reminder(101, 4, True)
        save_reminder.assert_called_once_with(101, 4, True)
        refresh_mock.assert_called_once_with()

    def test_calendar_button_emits_navigation_request(self):
        from PySide6.QtWidgets import QPushButton

        page = self._make_empty_home()
        requests = []
        page.calendar_requested.connect(lambda: requests.append(True))
        button = page.findChild(QPushButton, "homeCalendarAction")
        self.assertIsNotNone(button)
        button.click()
        self.assertEqual(requests, [True])


if __name__ == "__main__":
    unittest.main()
