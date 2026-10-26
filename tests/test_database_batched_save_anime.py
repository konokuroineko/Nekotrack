"""Regression tests for batched save_anime relation/studio/title persistence."""
import os
import tempfile
import unittest

import database


class BatchedSaveAnimeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="nekotrack-save-anime-")
        self.old_cwd = os.getcwd()
        os.chdir(self.temp_dir.name)
        database.initialize_database()

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp_dir.cleanup()

    def test_batched_titles_studios_and_relation_edges_preserve_input_order(self):
        source = {
            "id": 500,
            "type": "ANIME",
            "format": "TV",
            "title": {"english": "Source Show", "romaji": "Source Show"},
            "synonyms": ["Source Alias", "Source Alias", " Second Alias ", ""],
            "coverImage": {"large": "https://example.invalid/source.jpg"},
            "_mangabaka_id": 77,
            "_mangabaka": {
                "id": 77,
                "titles": [
                    {"language": "ja", "title": "Japanese Alias"},
                    {"language": "en", "title": "Source Alias"},
                ],
            },
            "studios": {"edges": [
                {"isMain": False, "node": {"id": 10, "name": "First Studio"}},
                {"isMain": True, "node": {"id": 11, "name": "Second Studio"}},
                {"isMain": True, "node": {"id": 10, "name": "First Studio Updated"}},
            ]},
            "relations": {"edges": [
                {
                    "relationType": "SEQUEL",
                    "node": {
                        "id": 600, "type": "ANIME", "format": "TV",
                        "title": {"english": "Related One", "romaji": "Related One"},
                        "coverImage": {"large": "https://example.invalid/related-1.jpg"},
                        "startDate": {"year": 2020, "month": 1, "day": 1},
                        "idMal": 6000,
                    },
                },
                {
                    "relationType": "SPIN_OFF",
                    "node": {
                        "id": 600, "type": "ANIME", "format": "MOVIE",
                        "title": {"english": "Related One Updated", "romaji": "Related One"},
                        "coverImage": {"large": None},
                        "startDate": {},
                    },
                },
                {
                    "relationType": "PREQUEL",
                    "node": {
                        "id": 601, "type": "MANGA", "format": "MANGA",
                        "title": {"english": "Related Two"},
                        "coverImage": {"large": None},
                        "startDate": {"year": 2022},
                    },
                },
            ]},
        }

        database.save_anime(source)

        con = database.get_connection()
        try:
            aliases = [
                (row["title"], row["language"])
                for row in con.execute(
                    "SELECT title, language FROM alternate_titles WHERE work_id = ? ORDER BY rowid",
                    (500,),
                ).fetchall()
            ]
            studios = {
                int(row["id"]): (row["name"], int(row["is_main"]))
                for row in con.execute(
                    "SELECT studios.id, studios.name, studios.is_main FROM studios "
                    "JOIN work_studios ON work_studios.studio_id = studios.id "
                    "WHERE work_studios.work_id = ?",
                    (500,),
                ).fetchall()
            }
            relations = [
                (int(row["target_id"]), row["relation_type"])
                for row in con.execute(
                    "SELECT target_id, relation_type FROM work_relations "
                    "WHERE source_id = ? ORDER BY relation_type",
                    (500,),
                ).fetchall()
            ]
            related_one = con.execute(
                "SELECT title, format, start_year, cover_url, mal_id FROM works WHERE id = 600"
            ).fetchone()
            related_two = con.execute(
                "SELECT title, type, format, start_year FROM works WHERE id = 601"
            ).fetchone()
        finally:
            con.close()

        self.assertIn(("Source Alias", None), aliases)
        self.assertNotIn((" Second Alias ", None), aliases)
        self.assertIn(("Second Alias", None), aliases)
        self.assertIn(("Japanese Alias", "ja"), aliases)
        self.assertEqual(studios[10], ("First Studio Updated", 1))
        self.assertEqual(studios[11], ("Second Studio", 1))
        self.assertEqual(set(relations), {(600, "SEQUEL"), (600, "SPIN_OFF"), (601, "PREQUEL")})
        self.assertEqual(related_one["title"], "Related One Updated")
        self.assertEqual(related_one["format"], "MOVIE")
        # Missing target data remains preserved through COALESCE updates.
        self.assertEqual(related_one["start_year"], 2020)
        self.assertEqual(related_one["cover_url"], "https://example.invalid/related-1.jpg")
        self.assertEqual(related_one["mal_id"], 6000)
        self.assertEqual(related_two["title"], "Related Two")
        self.assertEqual(related_two["type"], "MANGA")
        self.assertEqual(related_two["format"], "MANGA")
        self.assertEqual(related_two["start_year"], 2022)


if __name__ == "__main__":
    unittest.main()
