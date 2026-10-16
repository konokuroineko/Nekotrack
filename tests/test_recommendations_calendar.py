import datetime
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
    def test_empty_or_manga_only_library_still_uses_anime_catalog(self):
        from ui.pages.recommendations_page import RecommendationWorker

        catalog = {
            "pageInfo": {"currentPage": 1, "lastPage": 5, "hasNextPage": True},
            "media": [{
                "id": 801, "type": "ANIME",
                "title": {"english": "Catalog Anime"},
                "cover_url": "https://example.invalid/801.jpg",
                "genres": ["Adventure"],
            }],
        }
        finished = []
        worker = RecommendationWorker([
            {"id": -12, "type": "MANGA", "title": "Local manga only"}
        ])
        worker.finished.connect(finished.append)
        with (
            patch("ui.pages.recommendations_page.get_media_recommendations", return_value=[]),
            patch("ui.pages.recommendations_page.get_anime_discovery_page", return_value=catalog),
            patch("ui.pages.recommendations_page.get_work_favorites", return_value=[]),
            patch("ui.pages.recommendations_page.get_entity_favorites", return_value=[]),
            patch("ui.pages.recommendations_page.get_recommendation_credit_profile", return_value={}),
            patch("ui.pages.recommendations_page.get_recommendation_history", return_value={}),
        ):
            worker.run()

        self.assertEqual(len(finished), 1)
        self.assertEqual([work["id"] for work in finished[0]], [801])
        self.assertTrue(worker.catalog_has_next)
        self.assertEqual(worker.catalog_next_page, 2)

    def test_worker_does_not_truncate_a_valid_candidate_batch_at_forty(self):
        from ui.pages.recommendations_page import RecommendationWorker

        many = [
            {
                "id": 1000 + index, "type": "ANIME",
                "title": {"english": f"Candidate {index:02d}"},
                "averageScore": 75 + index % 20,
                "_recommendation_rating": 70 + index % 25,
            }
            for index in range(55)
        ]
        finished = []
        worker = RecommendationWorker([{
            "id": 9, "type": "ANIME", "title": {"english": "Seed"}
        }])
        worker.finished.connect(finished.append)
        with (
            patch("ui.pages.recommendations_page.get_media_recommendations", return_value=many),
            patch(
                "ui.pages.recommendations_page.get_anime_discovery_page",
                return_value={
                    "pageInfo": {"currentPage": 1, "lastPage": 1, "hasNextPage": False},
                    "media": [],
                },
            ),
            patch("ui.pages.recommendations_page.get_work_favorites", return_value=[]),
            patch("ui.pages.recommendations_page.get_entity_favorites", return_value=[]),
            patch("ui.pages.recommendations_page.get_recommendation_credit_profile", return_value={}),
            patch("ui.pages.recommendations_page.get_recommendation_history", return_value={}),
        ):
            worker.run()

        self.assertEqual(len(finished[0]), 55)

    def test_library_signature_uses_the_worker_title_normalizer(self):
        from ui.pages.recommendations_page import RecommendationsPage

        rows = [
            {"id": 12, "type": "ANIME", "title": {"english": "English title"}},
            {"id": 13, "type": "MANGA", "title": {"romaji": "Romanized title"}},
            {"id": 14, "type": "MANGA", "title": "Plain title"},
        ]
        self.assertEqual(
            RecommendationsPage._rows_signature(rows),
            (
                ("12", "ANIME", "English title"),
                ("13", "MANGA", "Romanized title"),
                ("14", "MANGA", "Plain title"),
            ),
        )

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
        with (
            patch("ui.pages.recommendations_page.get_media_recommendations", side_effect=[first, second]),
            patch(
                "ui.pages.recommendations_page.get_anime_discovery_page",
                return_value={
                    "pageInfo": {"currentPage": 1, "lastPage": 1, "hasNextPage": False},
                    "media": [],
                },
            ),
            patch("ui.pages.recommendations_page.get_work_favorites", return_value=[]),
            patch("ui.pages.recommendations_page.get_entity_favorites", return_value=[]),
            patch("ui.pages.recommendations_page.get_recommendation_credit_profile", return_value={}),
            patch("ui.pages.recommendations_page.get_recommendation_history", return_value={}),
        ):
            worker.run()

        self.assertEqual(len(finished), 1)
        rows = finished[0]
        self.assertEqual([row["id"] for row in rows], [11, 12, 13])
        self.assertEqual(rows[0]["_recommendation_count"], 2)
        self.assertEqual(
            rows[0]["_recommendation_source_titles"],
            ["Seed One", "Seed Two"],
        )


    @patch("api.search_anime")
    def test_anime_discovery_page_is_paginated_normalized_and_bounded(self, search):
        search.return_value = {
            "pageInfo": {"currentPage": 3, "lastPage": 9, "hasNextPage": True},
            "media": [
                {
                    "id": 501, "type": "ANIME", "title": {"romaji": "Catalog entry"},
                    "coverImage": {"large": "https://example.invalid/poster.jpg"},
                    "startDate": {"year": 2024},
                },
                {"id": 501, "type": "ANIME", "title": {"english": "Duplicate"}},
                {"id": 502, "type": "MANGA", "title": {"english": "Wrong type"}},
                {"id": 0, "type": "ANIME", "title": {"english": "Invalid ID"}},
                {"id": 503, "type": "ANIME", "title": {}},
            ],
        }

        result = api.get_anime_discovery_page(page=3, per_page=5000, sort="SCORE_DESC")

        search.assert_called_once_with(
            "", page=3, per_page=50, media_type="ANIME",
            sort="SCORE_DESC", include_relations=False, include_credit_signals=True,
        )
        self.assertEqual([row["id"] for row in result["media"]], [501])
        self.assertEqual(result["media"][0]["cover_url"], "https://example.invalid/poster.jpg")
        self.assertEqual(result["media"][0]["start_year"], 2024)
        self.assertTrue(result["pageInfo"]["hasNextPage"])

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
        with self.assertRaises(ValueError):
            database.set_release_reminder(101, 5.5, True)
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
