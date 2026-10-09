import os
import tempfile
import unittest

import database


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

    def test_chapter_and_volume_placeholders_track_progress_independently(self):
        work_id = 101
        database.save_anime(
            self._work(work_id, "MANGA", "NOVEL", chapters=8, volumes=3)
        )
        database.add_to_library(work_id)

        first_chapter_page = database.ensure_reading_placeholders(
            work_id, "chapter", 8, offset=0, limit=3
        )
        volume_page = database.ensure_reading_placeholders(
            work_id, "volume", 3, offset=0, limit=3
        )
        self.assertEqual(
            [row["item_number"] for row in first_chapter_page], [1, 2, 3]
        )
        self.assertEqual(len(volume_page), 3)
        # Items are created lazily, so a very long manga doesn't create every
        # placeholder row before the user needs to see it.
        self.assertEqual(
            len(database.get_reading_items(work_id, "chapter", limit=100)),
            3,
        )

        database.set_reading_item_read(work_id, "chapter", 2, True)
        database.set_reading_item_read(work_id, "volume", 1, True)
        database.set_reading_item_read(work_id, "volume", 3, True)

        self.assertEqual(database.get_reading_progress(work_id, "chapter", 8), (1, 8))
        self.assertEqual(database.get_reading_progress(work_id, "volume", 3), (2, 3))
        stored_work = database.get_work(work_id)
        self.assertEqual(stored_work["progress_chapters"], 1)
        self.assertEqual(stored_work["progress_volumes"], 2)

        # Re-opening placeholders doesn't reset read state.
        reloaded = database.ensure_reading_placeholders(
            work_id, "chapter", 8, offset=0, limit=3
        )
        self.assertTrue(reloaded[1]["is_read"])

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
