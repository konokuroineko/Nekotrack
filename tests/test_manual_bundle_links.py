import os
import tempfile
import unittest

import database


class ManualBundleDatabaseTests(unittest.TestCase):

    def test_library_grouping_reverse_edge_indexes_are_created_and_used(self):
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()
                connection = database.get_connection()
                try:
                    indexes = {
                        row["name"]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type = 'index'"
                        ).fetchall()
                    }
                    expected = {
                        "idx_work_relations_target_type_source",
                        "idx_manual_bundle_links_work_b",
                        "idx_bundle_exclusions_work_b",
                        "idx_automatic_bundle_memberships_work_id",
                    }
                    self.assertTrue(expected.issubset(indexes), expected - indexes)

                    plans = {
                        "relations": connection.execute(
                            "EXPLAIN QUERY PLAN SELECT source_id, target_id FROM work_relations "
                            "WHERE relation_type IN ('SEQUEL') AND target_id IN (?)",
                            (123,),
                        ).fetchall(),
                        "manual_links": connection.execute(
                            "EXPLAIN QUERY PLAN SELECT work_a, work_b FROM manual_bundle_links "
                            "WHERE work_b IN (?)",
                            (123,),
                        ).fetchall(),
                        "exclusions": connection.execute(
                            "EXPLAIN QUERY PLAN SELECT work_a, work_b FROM bundle_exclusions "
                            "WHERE work_b IN (?)",
                            (123,),
                        ).fetchall(),
                        "automatic_memberships": connection.execute(
                            "EXPLAIN QUERY PLAN SELECT bundle_id, work_id FROM automatic_bundle_memberships "
                            "WHERE work_id IN (?)",
                            (123,),
                        ).fetchall(),
                    }
                    expected_index_by_query = {
                        "relations": "idx_work_relations_target_type_source",
                        "manual_links": "idx_manual_bundle_links_work_b",
                        "exclusions": "idx_bundle_exclusions_work_b",
                        "automatic_memberships": "idx_automatic_bundle_memberships_work_id",
                    }
                    for name, plan_rows in plans.items():
                        details = " ".join(str(row["detail"]) for row in plan_rows)
                        self.assertIn(expected_index_by_query[name], details, (name, details))
                finally:
                    connection.close()
            finally:
                os.chdir(old_cwd)

    def test_delete_work_data_removes_local_work_and_library_entry(self):
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
                self.assertTrue(database.delete_work_data(1))
                self.assertIsNone(database.get_work(1))
                self.assertFalse(database.get_manual_bundle_links())
            finally:
                os.chdir(old_cwd)

    def test_remove_bundle_member_excludes_target_without_removing_library_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()

                for work_id, title in ((1, "Work One"), (2, "Work Two"), (3, "Work Three")):
                    database.save_anime({
                        "id": work_id,
                        "title": {"romaji": title, "english": None, "native": None},
                        "type": "ANIME",
                        "format": "TV",
                    })
                    database.add_to_library(work_id)

                self.assertTrue(database.add_manual_bundle_link(1, 2))
                self.assertTrue(database.add_manual_bundle_link(1, 3))

                self.assertTrue(database.remove_bundle_member(1, 2, [1, 2, 3]))
                self.assertIsNotNone(database.get_work(2))

                links = database.get_manual_bundle_links()
                self.assertEqual(
                    [(row["work_a"], row["work_b"]) for row in links],
                    [(1, 3)],
                )
                exclusions = database.get_bundle_exclusions()
                self.assertEqual(
                    [(row["work_a"], row["work_b"]) for row in exclusions],
                    [(1, 2), (2, 3)],
                )
            finally:
                os.chdir(old_cwd)

    def test_automatic_bundle_membership_round_trips_and_replaces_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()
                for work_id, title in ((1, "Main"), (2, "Extra"), (3, "Different")):
                    database.save_anime({
                        "id": work_id,
                        "title": {"romaji": title, "english": None, "native": None},
                        "type": "ANIME",
                        "format": "TV",
                    })
                self.assertTrue(database.save_automatic_bundle_membership(1, [1, 2]))
                first = database.get_automatic_bundle_memberships([1])
                self.assertEqual(
                    [(row["bundle_id"], row["work_id"]) for row in first],
                    [(1, 1), (1, 2)],
                )
                self.assertTrue(database.save_automatic_bundle_membership(1, [1, 3]))
                replaced = database.get_automatic_bundle_memberships([1])
                self.assertEqual(
                    [(row["bundle_id"], row["work_id"]) for row in replaced],
                    [(1, 1), (1, 3)],
                )
                self.assertTrue(database.save_automatic_bundle_membership(1, [1]))
                self.assertEqual(database.get_automatic_bundle_memberships([1]), [])
            finally:
                os.chdir(old_cwd)

    def test_deleting_work_removes_automatic_bundle_membership(self):
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()
                for work_id in (1, 2):
                    database.save_anime({
                        "id": work_id,
                        "title": {"romaji": f"Work {work_id}", "english": None, "native": None},
                        "type": "ANIME",
                        "format": "TV",
                    })
                database.save_automatic_bundle_membership(1, [1, 2])
                self.assertTrue(database.delete_work_data(2))
                self.assertEqual(database.get_automatic_bundle_memberships(), [])
            finally:
                os.chdir(old_cwd)

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
