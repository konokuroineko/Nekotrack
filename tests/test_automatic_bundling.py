import os
import tempfile
import unittest

import database
import series


class AutomaticLibraryBundlingTests(unittest.TestCase):
    def test_related_library_entries_form_one_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()

                first = {
                    "id": 1,
                    "title": {"romaji": "Example Season 1", "english": None, "native": None},
                    "type": "ANIME",
                    "format": "TV",
                    "startDate": {"year": 2020, "month": 1, "day": 1},
                    "coverImage": {"large": "https://example.test/1.jpg"},
                    "relations": {
                        "edges": [
                            {
                                "relationType": "SEQUEL",
                                "node": {
                                    "id": 2,
                                    "type": "ANIME",
                                    "format": "TV",
                                    "title": {
                                        "romaji": "Example Season 2",
                                        "english": None,
                                        "native": None,
                                    },
                                    "coverImage": {
                                        "large": "https://example.test/2.jpg"
                                    },
                                },
                            }
                        ]
                    },
                }
                second = {
                    "id": 2,
                    "title": {"romaji": "Example Season 2", "english": None, "native": None},
                    "type": "ANIME",
                    "format": "TV",
                    "startDate": {"year": 2021, "month": 1, "day": 1},
                    "coverImage": {"large": "https://example.test/2.jpg"},
                }

                database.save_anime(first)
                database.save_anime(second)
                database.add_to_library(1)
                database.add_to_library(2)

                groups = database.get_all_library()
                self.assertEqual(len(list(groups)), 2)

                bundles = series.get_library_series()
                self.assertEqual(len(bundles), 1)
                self.assertEqual(bundles[0]["_series_count"], 2)
                self.assertEqual([member["id"] for member in bundles[0]["_series_members"]], [1, 2])
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
