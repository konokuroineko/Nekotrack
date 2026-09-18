import os
import tempfile
import unittest

import database
import series


class BundleAppearanceTests(unittest.TestCase):
    def test_library_bundle_uses_earliest_member_by_default_and_override(self):
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()

                first = {
                    "id": 1,
                    "title": {"romaji": "Example 1", "english": None, "native": None},
                    "type": "ANIME",
                    "format": "TV",
                    "startDate": {"year": 2020, "month": 1, "day": 1},
                    "coverImage": {"large": "https://example.test/first.jpg"},
                }
                second = {
                    "id": 2,
                    "title": {"romaji": "Example 2", "english": None, "native": None},
                    "type": "ANIME",
                    "format": "TV",
                    "startDate": {"year": 2021, "month": 1, "day": 1},
                    "coverImage": {"large": "https://example.test/second.jpg"},
                }
                database.save_anime(first)
                database.save_anime(second)
                database.add_to_library(1)
                database.add_to_library(2)

                group = series.get_library_series()[0]
                self.assertEqual(group["id"], 1)
                self.assertEqual(group["title"], "Example 1")
                self.assertEqual(group["cover_url"], "https://example.test/first.jpg")

                self.assertTrue(
                    database.save_bundle_override(
                        [1, 2],
                        1,
                        custom_title="My Example Bundle",
                        cover_work_id=2,
                    )
                )
                group = series.get_library_series()[0]
                self.assertEqual(group["title"], "My Example Bundle")
                self.assertEqual(group["cover_url"], "https://example.test/second.jpg")
            finally:
                os.chdir(old_cwd)

    def test_search_bundle_keeps_match_identity_but_uses_earliest_presentation(self):
        later = {
            "id": 3,
            "type": "ANIME",
            "format": "TV",
            "title": {"romaji": "Example 3", "english": None, "native": None},
            "coverImage": {"large": "https://example.test/third.jpg"},
            "startDate": {"year": 2022, "month": 1, "day": 1},
        }
        earliest = {
            "id": 1,
            "type": "ANIME",
            "format": "TV",
            "title": {"romaji": "Example 1", "english": None, "native": None},
            "coverImage": {"large": "https://example.test/first.jpg"},
            "startDate": {"year": 2020, "month": 1, "day": 1},
        }

        grouped = series._group_discovered([later], [later, earliest])
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0]["id"], 3)
        self.assertEqual(grouped[0]["title"]["romaji"], "Example 1")
        self.assertEqual(
            grouped[0]["coverImage"]["large"],
            "https://example.test/first.jpg",
        )


if __name__ == "__main__":
    unittest.main()
