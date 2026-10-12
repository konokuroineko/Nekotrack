import unittest
from unittest.mock import patch

import database


class BundleCharacterRoleTests(unittest.TestCase):
    @staticmethod
    def _character(role):
        return {
            "id": 777,
            "character_name": "Example Character",
            "character_role": role,
            "character_image_url": None,
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
