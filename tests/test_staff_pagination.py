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

    def test_replacing_staff_snapshot_removes_only_unreferenced_people(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)
                database.initialize_database()
                for work_id in (123, 124):
                    database.save_anime({
                        "id": work_id,
                        "type": "ANIME",
                        "format": "TV",
                        "title": {"romaji": f"Example Show {work_id}"},
                        "coverImage": {"large": None},
                    })

                def staff_edge(person_id, name):
                    return {
                        "role": "Series Composition",
                        "node": {
                            "id": person_id,
                            "name": {"full": name},
                            "image": {"large": None},
                        },
                    }

                database.save_staff(123, [
                    staff_edge(301, "Obsolete Staff"),
                    staff_edge(303, "Still Staff"),
                    staff_edge(304, "Cast-only Reference"),
                ])
                database.save_staff(124, [staff_edge(303, "Still Staff")])
                database.save_characters(124, [{
                    "role": "MAIN",
                    "node": {
                        "id": 801,
                        "name": {"full": "Shared Character"},
                        "image": {"large": None},
                    },
                    "voiceActors": [{
                        "id": 304,
                        "name": {"full": "Cast-only Reference"},
                        "image": {"large": None},
                        "language": "Japanese",
                    }],
                }])

                database.save_staff(123, [staff_edge(302, "Replacement Staff")])

                con = database.get_connection()
                try:
                    people = {
                        int(row["id"]): row["name"]
                        for row in con.execute(
                            "SELECT id, name FROM people WHERE id IN (301, 302, 303, 304)"
                        ).fetchall()
                    }
                    linked_staff = {
                        (int(row["work_id"]), int(row["person_id"]))
                        for row in con.execute(
                            "SELECT work_id, person_id FROM work_staff WHERE person_id IN (301, 302, 303, 304)"
                        ).fetchall()
                    }
                    cast_refs = {
                        int(row["person_id"])
                        for row in con.execute(
                            "SELECT person_id FROM character_voice_actors"
                        ).fetchall()
                    }
                finally:
                    con.close()

                self.assertNotIn(301, people)
                self.assertEqual(people[302], "Replacement Staff")
                self.assertEqual(people[303], "Still Staff")
                self.assertEqual(people[304], "Cast-only Reference")
                self.assertEqual(linked_staff, {(123, 302), (124, 303)})
                self.assertIn(304, cast_refs)
            finally:
                os.chdir(old_cwd)

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
