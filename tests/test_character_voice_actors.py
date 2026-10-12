import os
import tempfile
import unittest

import database


class CharacterVoiceActorScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.temp_dir.name)
        database.initialize_database()

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp_dir.cleanup()

    @staticmethod
    def _work(work_id):
        return {
            "id": work_id,
            "type": "ANIME",
            "format": "TV",
            "title": {"english": f"Adaptation {work_id}", "romaji": f"Adaptation {work_id}"},
            "coverImage": {"large": None},
        }

    @staticmethod
    def _actor(person_id, name, language="Japanese"):
        return {
            "id": person_id,
            "name": {"full": name},
            "image": {"large": f"https://example.invalid/{person_id}.jpg"},
            "language": language,
        }

    @classmethod
    def _character(cls, actors, role="MAIN"):
        return {
            "node": {
                "id": 501,
                "name": {"full": "Shared Character"},
                "image": {"large": "https://example.invalid/character.jpg"},
            },
            "role": role,
            "voiceActors": actors,
        }

    def _add_two_adaptations(self):
        database.save_anime(self._work(101))
        database.save_anime(self._work(102))

    def test_empty_cast_in_one_adaptation_does_not_erase_other_adaptations_actor(self):
        self._add_two_adaptations()
        actor = self._actor(7001, "First Adaptation Actor")
        database.save_characters(101, [self._character([actor])])
        database.save_characters(102, [self._character([])])

        first = [dict(row) for row in database.get_characters(101)]
        second = [dict(row) for row in database.get_characters(102)]
        self.assertEqual(first[0]["person_id"], 7001)
        self.assertEqual(first[0]["person_name"], "First Adaptation Actor")
        self.assertIsNone(second[0]["person_id"])
        self.assertEqual(
            [row["person_id"] for row in database.get_bundle_character_voice_actors([101, 102], 501)],
            [7001],
        )

    def test_each_adaptation_keeps_its_own_cast_and_bundle_prefers_japanese_actor(self):
        self._add_two_adaptations()
        japanese = self._actor(7001, "Japanese Actor", "Japanese")
        english = self._actor(7002, "English Actor", "English")
        database.save_characters(101, [self._character([japanese])])
        database.save_characters(102, [self._character([english], role="SUPPORTING")])

        first = dict(database.get_characters(101)[0])
        second = dict(database.get_characters(102)[0])
        self.assertEqual(first["person_id"], 7001)
        self.assertEqual(second["person_id"], 7002)

        bundle_forward = database.get_bundle_characters([101, 102])
        bundle_reverse = database.get_bundle_characters([102, 101])
        self.assertEqual(bundle_forward[0]["person_id"], 7001)
        self.assertEqual(bundle_reverse[0]["person_id"], 7001)
        all_actors = database.get_bundle_character_voice_actors([102, 101], 501)
        self.assertEqual({row["person_id"] for row in all_actors}, {7001, 7002})

    def test_legacy_global_actor_rows_migrate_and_mark_cast_for_refresh(self):
        self._add_two_adaptations()
        actor = self._actor(7001, "Legacy Actor")
        database.save_characters(101, [self._character([actor])])
        database.save_characters(102, [self._character([])])

        connection = database.get_connection()
        try:
            connection.execute("DROP TABLE work_character_voice_actors")
            connection.execute("UPDATE works SET characters_loaded = 1")
            connection.commit()
        finally:
            connection.close()

        database.initialize_database()
        self.assertFalse(database.characters_are_loaded(101))
        self.assertFalse(database.characters_are_loaded(102))
        # Fresh cast snapshots can now correct this legacy ambiguous association
        # independently for each adaptation without cross-deleting the actor.
        database.save_characters(102, [self._character([])])
        self.assertEqual(dict(database.get_characters(101)[0])["person_id"], 7001)
        self.assertIsNone(dict(database.get_characters(102)[0])["person_id"])


if __name__ == "__main__":
    unittest.main()
