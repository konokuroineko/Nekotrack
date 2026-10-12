import sqlite3
import unittest
from unittest.mock import patch

import database


class BundleCharacterRoleTests(unittest.TestCase):
    @staticmethod
    def _character(role, person_id=None, person_name=None, person_language=None):
        return {
            "id": 777,
            "character_name": "Example Character",
            "character_role": role,
            "character_image_url": None,
            "person_id": person_id,
            "person_name": person_name,
            "person_language": person_language,
        }

    def test_main_role_wins_independent_of_bundle_member_order(self):
        rows_by_work = {
            1: [self._character("SUPPORTING")],
            2: [self._character("MAIN")],
        }

        with patch(
            "database.get_characters",
            side_effect=lambda work_id: rows_by_work.get(int(work_id), []),
        ):
            forward = database.get_bundle_characters([1, 2])
            reverse = database.get_bundle_characters([2, 1])

        self.assertEqual(len(forward), 1)
        self.assertEqual(len(reverse), 1)
        self.assertEqual(forward[0]["character_role"], "MAIN")
        self.assertEqual(reverse[0]["character_role"], "MAIN")

    def test_sqlite_rows_are_supported(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        try:
            supporting = connection.execute(
                "SELECT 777 AS id, 'Example Character' AS character_name, "
                "'SUPPORTING' AS character_role, NULL AS character_image_url"
            ).fetchone()
            main = connection.execute(
                "SELECT 777 AS id, 'Example Character' AS character_name, "
                "'MAIN' AS character_role, NULL AS character_image_url"
            ).fetchone()
        finally:
            connection.close()

        with patch(
            "database.get_characters",
            side_effect=lambda work_id: [supporting] if int(work_id) == 1 else [main],
        ):
            result = database.get_bundle_characters([1, 2])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["character_role"], "MAIN")

    def test_same_priority_voice_actor_preview_is_independent_of_bundle_order(self):
        rows_by_work = {
            1: [self._character("MAIN", 8002, "Beta Actor", "Japanese")],
            2: [self._character("MAIN", 8001, "Alpha Actor", "Japanese")],
        }
        with patch(
            "database.get_characters",
            side_effect=lambda work_id: rows_by_work.get(int(work_id), []),
        ):
            forward = database.get_bundle_characters([1, 2])
            reverse = database.get_bundle_characters([2, 1])

        self.assertEqual(forward[0]["person_id"], 8001)
        self.assertEqual(reverse[0]["person_id"], 8001)
        self.assertEqual(forward[0]["person_name"], "Alpha Actor")
        self.assertEqual(reverse[0]["person_name"], "Alpha Actor")

    def test_supporting_beats_background_across_bundle(self):
        rows_by_work = {
            1: [self._character("BACKGROUND")],
            2: [self._character("SUPPORTING")],
        }

        with patch(
            "database.get_characters",
            side_effect=lambda work_id: rows_by_work.get(int(work_id), []),
        ):
            result = database.get_bundle_characters([1, 2])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["character_role"], "SUPPORTING")


if __name__ == "__main__":
    unittest.main()
