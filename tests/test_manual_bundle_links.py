import os
import tempfile
import unittest

import database


class ManualBundleDatabaseTests(unittest.TestCase):
    def test_remove_from_library_keeps_work_data(self):
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()
                work = {
                    "id": 1,
                    "title": {"romaji": "Work One", "english": None, "native": None},
                    "type": "ANIME",
                    "format": "TV",
                }
                database.save_anime(work)
                database.add_to_library(1)
                self.assertTrue(database.remove_from_library(1))
                self.assertIsNotNone(database.get_work(1))
                self.assertFalse(database.get_work(1)["status"])
            finally:
                os.chdir(old_cwd)

    def test_manual_link_requires_existing_local_works(self):
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()
                self.assertFalse(database.add_manual_bundle_link(1, 2))

                work = {
                    "id": 1,
                    "title": {"romaji": "Work One", "english": None, "native": None},
                    "type": "ANIME",
                    "format": "TV",
                }
                database.save_anime(work)
                work["id"] = 2
                work["title"] = {"romaji": "Work Two", "english": None, "native": None}
                database.save_anime(work)

                self.assertTrue(database.add_manual_bundle_link(2, 1))
                links = database.get_manual_bundle_links()
                self.assertEqual([(row["work_a"], row["work_b"]) for row in links], [(1, 2)])
                self.assertEqual(len(database.get_manual_bundle_partners(1)), 1)
                self.assertTrue(database.remove_manual_bundle_link(1, 2))
                self.assertEqual(database.get_manual_bundle_links(), [])
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
