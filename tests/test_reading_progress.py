import os
import tempfile
import unittest
from unittest.mock import patch

import database
from ui.pages.work_detail_page import WorkDetailPage


class ReadingProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.temp_dir.name)
        database.initialize_database()

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp_dir.cleanup()

    @staticmethod
    def _work(work_id, media_type, media_format, chapters=None, volumes=None):
        return {
            "id": work_id,
            "type": media_type,
            "format": media_format,
            "title": {
                "romaji": f"Example {media_format}",
                "english": None,
                "native": None,
            },
            "chapters": chapters,
            "volumes": volumes,
            "episodes": None,
            "coverImage": {"large": None},
        }

    def test_reading_counts_survive_removal_of_synthetic_items(self):
        work_id = 101
        database.save_anime(
            self._work(work_id, "MANGA", "NOVEL", chapters=8, volumes=3)
        )
        database.add_to_library(work_id)

        # Simulate rows and aggregate values left by the previous placeholder UI.
        connection = database.get_connection()
        try:
            connection.executemany(
                """
                INSERT INTO reading_items
                    (work_id, item_type, item_number, title, is_read)
                VALUES (?, ?, ?, NULL, ?)
                """,
                [
                    (work_id, "chapter", 1, 0),
                    (work_id, "chapter", 2, 1),
                    (work_id, "chapter", 3, 0),
                    (work_id, "volume", 1, 1),
                    (work_id, "volume", 2, 0),
                    (work_id, "volume", 3, 1),
                ],
            )
            connection.execute(
                """
                UPDATE user_library
                SET progress_chapters = 1, progress_volumes = 2
                WHERE work_id = ?
                """,
                (work_id,),
            )
            connection.commit()
        finally:
            connection.close()

        # Startup migration removes fictional cards but keeps progress counts.
        database.initialize_database()
        connection = database.get_connection()
        try:
            synthetic_count = connection.execute(
                "SELECT COUNT(*) FROM reading_items WHERE work_id = ?",
                (work_id,),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(synthetic_count, 0)
        self.assertEqual(database.get_reading_progress(work_id, "chapter", 8), (1, 8))
        self.assertEqual(database.get_reading_progress(work_id, "volume", 3), (2, 3))

        # New numeric progress changes counts without recreating per-item rows.
        self.assertEqual(
            database.set_reading_progress_count(work_id, "chapter", 4, 8),
            (4, 8),
        )
        self.assertEqual(
            database.set_reading_progress_count(work_id, "volume", 2, 3),
            (2, 3),
        )
        stored_work = database.get_work(work_id)
        self.assertEqual(stored_work["progress_chapters"], 4)
        self.assertEqual(stored_work["progress_volumes"], 2)
        connection = database.get_connection()
        try:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM reading_items WHERE work_id = ?",
                    (work_id,),
                ).fetchone()[0],
                0,
            )
        finally:
            connection.close()

    def test_library_membership_is_not_confused_with_publication_status(self):
        work_id = 301
        work = self._work(work_id, "MANGA", "NOVEL", chapters=24, volumes=4)
        work["status"] = "FINISHED"
        database.save_anime(work)

        self.assertFalse(database.is_work_in_library(work_id))
        database.add_to_library(work_id, "Planning")
        self.assertTrue(database.is_work_in_library(work_id))

    def test_saved_mangabaka_totals_recover_missing_database_counts(self):
        work_id = -302
        database.save_anime(self._work(work_id, "MANGA", "NOVEL", chapters=None, volumes=None))
        database.save_provider_metadata(
            work_id,
            "mangabaka",
            {
                "id": 302,
                "total_chapters": None,
                "chapters": "73 chapters",
                "total_volumes": None,
                "volumes": None,
                "final_volume": 12,
            },
        )
        stored_work = database.get_work(work_id)
        self.assertEqual(WorkDetailPage._work_count(object(), stored_work, "chapters"), 73)
        self.assertEqual(WorkDetailPage._work_count(object(), stored_work, "volumes"), 12)

    def test_reading_item_metadata_batches_upserts_and_preserves_read_state(self):
        work_id = 401
        database.save_anime(self._work(work_id, "MANGA", "NOVEL", chapters=100, volumes=10))
        con = database.get_connection()
        try:
            con.execute(
                """
                INSERT INTO reading_items (work_id, item_type, item_number, title, is_read)
                VALUES (?, 'chapter', 2, 'Old Chapter 2', 1)
                """,
                (work_id,),
            )
            con.commit()
        finally:
            con.close()

        items = [
            {"number": "1", "title": "Chapter One"},
            {"number": "Chapter 2", "title": "Chapter Two"},
            {"number": "invalid", "title": "Skip"},
            {"title": "Fallback Index"},
            {"number": "2", "title": "Updated Chapter Two"},
            {"number": True, "title": "Skip Boolean"},
        ]
        with patch.object(database, "get_connection", wraps=database.get_connection) as factory:
            saved_count = database.save_reading_item_metadata(work_id, "chapter", items)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(saved_count, 4)

        con = database.get_connection()
        try:
            rows = con.execute(
                """
                SELECT item_number, title, is_read
                FROM reading_items
                WHERE work_id = ? AND item_type = 'chapter'
                ORDER BY item_number
                """,
                (work_id,),
            ).fetchall()
        finally:
            con.close()
        self.assertEqual(
            [(int(row["item_number"]), row["title"], int(row["is_read"])) for row in rows],
            [(1, "Chapter One", 0), (2, "Updated Chapter Two", 1), (4, "Fallback Index", 0)],
        )

    def test_older_manga_episode_imports_are_removed_but_anime_episodes_remain(self):
        anime_id = 201
        manga_id = 202
        database.save_anime(self._work(anime_id, "ANIME", "TV"))
        database.save_anime(
            self._work(manga_id, "MANGA", "NOVEL", chapters=8, volumes=3)
        )
        database.save_episodes(
            anime_id,
            [{"episodeNumber": 1, "title": "Pilot", "thumbnail": None}],
        )
        database.save_episodes(
            manga_id,
            [{"episodeNumber": 1, "title": "Wrong TV episode", "thumbnail": None}],
        )
        database.save_tmdb_mapping(manga_id, 98765, 1)

        # Database initialization also runs this compatibility cleanup for
        # existing installs, not just newly imported works.
        database.initialize_database()

        self.assertEqual(len(database.get_episodes(anime_id)), 1)
        self.assertEqual(database.get_episodes(manga_id), [])
        self.assertEqual(database.get_tmdb_mapping(manga_id), (None, None))


if __name__ == "__main__":
    unittest.main()
