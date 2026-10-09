import unittest
from unittest.mock import patch

from ui.main_window import LibraryImportWorker


class MangaEpisodeImportPolicyTests(unittest.TestCase):
    def test_library_import_does_not_query_tmdb_for_a_light_novel(self):
        details = {
            "id": 91,
            "type": "MANGA",
            "format": "NOVEL",
            "title": {
                "english": "Example Light Novel",
                "romaji": "Example Light Novel",
                "native": None,
            },
            "characters": {"edges": []},
            "staff": {"edges": []},
        }
        completed = []
        worker = LibraryImportWorker(91)
        worker.finished.connect(lambda work_id, payload: completed.append((work_id, payload)))

        with (
            patch("ui.main_window.get_media_details", return_value=details),
            patch("ui.main_window.save_anime") as save_work,
            patch("ui.main_window.save_characters"),
            patch("ui.main_window.save_staff"),
            patch("ui.main_window.get_tmdb_episode_data") as fetch_episodes,
        ):
            worker.run()

        save_work.assert_called_once_with(details)
        fetch_episodes.assert_not_called()
        self.assertEqual(completed, [(91, details)])


if __name__ == "__main__":
    unittest.main()
