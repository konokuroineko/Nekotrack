import os
import tempfile
import unittest
from unittest.mock import patch

import api
import database


class StaffPaginationTests(unittest.TestCase):
    def test_fetches_requested_anilist_staff_page_and_page_info(self):
        payload = {
            "Media": {
                "staff": {
                    "edges": [
                        {
                            "role": "Storyboard",
                            "node": {
                                "id": 302,
                                "name": {"full": "Example Staff"},
                                "image": {"large": "https://example.invalid/staff.jpg"},
                            },
                        }
                    ],
                    "pageInfo": {
                        "currentPage": 2,
                        "lastPage": 4,
                        "hasNextPage": True,
                    },
                }
            }
        }
        with patch("api.anilist_request", return_value=payload) as request:
            result = api.get_media_staff_page(123, page=2, per_page=15)

        self.assertEqual(len(result["edges"]), 1)
        self.assertEqual(result["pageInfo"]["currentPage"], 2)
        self.assertEqual(result["pageInfo"]["lastPage"], 4)
        self.assertTrue(result["pageInfo"]["hasNextPage"])
        self.assertEqual(request.call_args.args[1], {
            "id": 123, "page": 2, "perPage": 15
        })

    def test_negative_mangabaka_ids_never_call_anilist(self):
        with patch("api.anilist_request") as request:
            result = api.get_media_staff_page(-123, page=2)

        self.assertEqual(result["edges"], [])
        self.assertFalse(result["pageInfo"]["hasNextPage"])
        request.assert_not_called()

    def test_staff_pages_can_be_added_without_erasing_first_page(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)
                database.initialize_database()
                database.save_anime({
                    "id": 123,
                    "type": "ANIME",
                    "format": "TV",
                    "title": {"romaji": "Example Show"},
                    "coverImage": {"large": None},
                })
                first = [{
                    "role": "Series Composition",
                    "node": {"id": 301, "name": {"full": "First Staff"}},
                }]
                second = [{
                    "role": "Storyboard",
                    "node": {"id": 302, "name": {"full": "Second Staff"}},
                }]
                database.save_staff(123, first)
                database.save_staff(123, second, replace_snapshot=False)

                stored = database.get_staff(123)
                self.assertEqual(
                    {row["name"] for row in stored},
                    {"First Staff", "Second Staff"},
                )
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
