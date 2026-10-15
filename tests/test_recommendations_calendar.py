import datetime
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import api
import database


class AniListRecommendationsTests(unittest.TestCase):
    @patch("api.anilist_request")
    def test_recommendations_are_normalized_deduplicated_and_bounded(self, request):
        request.return_value = {
            "Media": {
                "recommendations": {
                    "nodes": [
                        {
                            "rating": 88,
                            "mediaRecommendation": {
                                "id": 12,
                                "type": "ANIME",
                                "format": "TV",
                                "averageScore": 91,
                                "title": {"romaji": "Suggested", "english": "Suggested"},
                                "startDate": {"year": 2025},
                                "coverImage": {"large": "https://example.invalid/cover.jpg"},
                            },
                        },
                        {
                            "rating": 75,
                            "mediaRecommendation": {"id": 12, "title": {"romaji": "Duplicate"}},
                        },
                        {
                            "rating": 100,
                            "mediaRecommendation": {"id": 0, "title": {"romaji": "Invalid"}},
                        },
                        {"rating": 99, "mediaRecommendation": None},
                        {
                            "rating": 140,
                            "mediaRecommendation": {"id": 13, "title": {"romaji": "Bad score"}},
                        },
                    ]
                }
            }
        }

        rows = api.get_media_recommendations(5, per_page=900)

        request.assert_called_once()
        query, variables = request.call_args.args
        self.assertIn("recommendations(sort: [RATING_DESC]", query)
        self.assertEqual(variables, {"id": 5, "perPage": 25})
        self.assertEqual([row["id"] for row in rows], [12, 13])
        self.assertEqual(rows[0]["_recommendation_rating"], 88)
        self.assertEqual(rows[0]["cover_url"], "https://example.invalid/cover.jpg")
        self.assertEqual(rows[0]["start_year"], 2025)
        self.assertIsNone(rows[1]["_recommendation_rating"])

    def test_recommendations_reject_invalid_and_mangabaka_local_ids_without_network(self):
        with patch("api.anilist_request") as request:
            self.assertEqual(api.get_media_recommendations(-12), [])
            self.assertEqual(api.get_media_recommendations("not-an-id"), [])
        request.assert_not_called()



class RecommendationWorkerTests(unittest.TestCase):
    def test_worker_excludes_library_entries_and_ranks_repeat_suggestions_first(self):
        from ui.pages.recommendations_page import RecommendationWorker

        library = [
            {"id": 1, "type": "ANIME", "title": {"english": "Seed One"}},
            {"id": 2, "type": "ANIME", "title": {"romaji": "Seed Two"}},
            {"id": -3, "type": "MANGA", "title": {"english": "Provider-only work"}},
        ]
        first = [
            {
                "id": 1, "type": "ANIME",
                "title": {"english": "Already tracked"},
                "_recommendation_rating": 99,
            },
            {
                "id": 11, "type": "ANIME",
                "title": {"english": "Repeated suggestion"},
                "_recommendation_rating": 70, "averageScore": 81,
            },
            {
                "id": 12, "type": "ANIME",
                "title": {"english": "One-off suggestion"},
                "_recommendation_rating": 95, "averageScore": 96,
            },
        ]
        second = [
            {
                "id": 11, "type": "ANIME",
                "title": {"english": "Repeated suggestion"},
                "_recommendation_rating": 83, "averageScore": 81,
            },
            {
                "id": 13, "type": "ANIME",
                "title": {"english": "Second one-off"},
                "_recommendation_rating": 78, "averageScore": 78,
            },
        ]
        finished = []
        worker = RecommendationWorker(library)
        worker.finished.connect(finished.append)
        with patch("ui.pages.recommendations_page.get_media_recommendations", side_effect=[first, second]):
            worker.run()

        self.assertEqual(len(finished), 1)
        rows = finished[0]
        self.assertEqual([row["id"] for row in rows], [11, 12, 13])
        self.assertEqual(rows[0]["_recommendation_count"], 2)
        self.assertEqual(
            rows[0]["_recommendation_source_titles"],
            ["Seed One", "Seed Two"],
        )


class ReleaseReminderDatabaseTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self._database_path = Path(self._directory.name) / "reminders.db"
        self._patcher = patch.object(database, "DATABASE_NAME", str(self._database_path))
        self._patcher.start()
        database.initialize_database()
        connection = database.get_connection()
        connection.execute(
            "INSERT INTO works (id, title, type, format, episodes) VALUES (?, ?, ?, ?, ?)",
            (101, "Reminder Test", "ANIME", "TV", 12),
        )
        today = datetime.date.today().isoformat()
        connection.execute(
            "INSERT INTO episodes (work_id, episode_number, title, air_date) VALUES (?, ?, ?, ?)",
            (101, 5, "Episode Five", today),
        )
        connection.execute(
            "INSERT INTO episodes (work_id, episode_number, title, air_date) VALUES (?, ?, ?, ?)",
            (101, 6, "Episode Six", "2099-01-01"),
        )
        connection.commit()
        connection.close()

    def tearDown(self):
        self._patcher.stop()
        self._directory.cleanup()

    def test_reminder_persists_notifies_only_once_per_day_and_can_be_disabled(self):
        today = datetime.date.today().isoformat()
        self.assertTrue(database.set_release_reminder(101, 5, True))
        rows = database.get_release_reminders()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["work_title"], "Reminder Test")
        self.assertEqual(rows[0]["episode_number"], 5)
        self.assertEqual(rows[0]["air_date"], today)

        due = database.get_due_release_reminders(today)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["episode_title"], "Episode Five")
        self.assertTrue(database.mark_release_reminder_notified(101, 5, today))
        self.assertEqual(database.get_due_release_reminders(today), [])
        self.assertTrue(database.set_release_reminder(101, 5, True))
        self.assertEqual(len(database.get_due_release_reminders(today)), 1)

        self.assertFalse(database.set_release_reminder(101, 5, False))
        self.assertEqual(database.get_release_reminders(), [])

    def test_reminder_only_accepts_existing_episodes_and_valid_dates(self):
        with self.assertRaisesRegex(ValueError, "cached episode"):
            database.set_release_reminder(101, 88, True)
        with self.assertRaises(ValueError):
            database.set_release_reminder(101, True, True)
        with self.assertRaisesRegex(ValueError, "ISO date"):
            database.get_due_release_reminders("not-a-date")
        with self.assertRaisesRegex(ValueError, "ISO date"):
            database.mark_release_reminder_notified(101, 5, "not-a-date")


    def test_calendar_page_shows_cached_upcoming_events_and_persists_toggle(self):
        from PySide6.QtWidgets import QApplication, QPushButton
        from ui.pages.calendar_page import CalendarPage

        database.add_to_library(101, "Watching")
        app = QApplication.instance() or QApplication([])
        page = CalendarPage()
        app.processEvents()
        self.assertEqual(len(page._events), 1)
        self.assertEqual(page._events[0]["work_title"], "Reminder Test")
        button = next(
            candidate
            for candidate in page.findChildren(QPushButton)
            if candidate.accessibleName() == "Enable episode reminder"
        )
        button.click()
        app.processEvents()
        rows = database.get_release_reminders()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["episode_number"], 5)
        self.assertTrue(
            any(
                candidate.accessibleName() == "Disable episode reminder"
                for candidate in page.findChildren(QPushButton)
            )
        )
        page.close()
        page.deleteLater()
        app.processEvents()

    def test_new_reminder_table_is_safe_to_initialize_repeatedly(self):
        database.initialize_database()
        database.initialize_database()
        connection = database.get_connection()
        try:
            names = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        finally:
            connection.close()
        self.assertIn("release_reminders", names)


if __name__ == "__main__":
    unittest.main()
