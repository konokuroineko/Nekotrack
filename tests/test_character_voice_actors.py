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
        # The first bundle member may have no cast entry; later valid data wins.
        for ordered_ids in ([102, 101], [101, 102]):
            with self.subTest(ordered_ids=ordered_ids):
                preview = database.get_bundle_characters(ordered_ids)
                self.assertEqual(len(preview), 1)
                self.assertEqual(preview[0]["person_id"], 7001)

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

    def test_same_actor_is_deduplicated_but_all_adaptation_credits_are_retained(self):
        self._add_two_adaptations()
        database.save_characters(
            101, [self._character([self._actor(7001, "Shared Voice Actor", "Japanese")])]
        )
        database.save_characters(
            102, [self._character([self._actor(7001, "Shared Voice Actor", "ja")])]
        )

        actors = database.get_bundle_character_voice_actors([102, 101], 501)
        self.assertEqual(len(actors), 1)
        actor = actors[0]
        self.assertEqual(actor["person_id"], 7001)
        self.assertEqual(actor["language"], "Japanese")
        self.assertEqual(actor["languages"], ["Japanese"])
        self.assertEqual(actor["work_ids"], [101, 102])
        self.assertEqual(actor["work_titles"], ["Adaptation 101", "Adaptation 102"])
        self.assertEqual(
            [
                (credit["work_id"], credit["work_title"], credit["language"])
                for credit in actor["credits"]
            ],
            [
                (101, "Adaptation 101", "Japanese"),
                (102, "Adaptation 102", "Japanese"),
            ],
        )

    def test_partial_cast_snapshot_does_not_erase_previously_saved_actors(self):
        self._add_two_adaptations()
        database.save_characters(
            101, [self._character([self._actor(7001, "Previously Saved Actor")])]
        )
        partial_character = self._character([])
        partial_character.pop("voiceActors")
        database.save_characters(101, [partial_character])

        self.assertFalse(database.characters_are_loaded(101))
        self.assertEqual(
            [
                actor["person_id"]
                for actor in database.get_bundle_character_voice_actors([101], 501)
            ],
            [7001],
        )

    def test_cast_snapshot_can_be_invalidated_without_deleting_saved_characters(self):
        self._add_two_adaptations()
        database.save_characters(101, [self._character([])])
        self.assertTrue(database.characters_are_loaded(101))
        self.assertEqual(len(database.get_characters(101)), 1)

        self.assertEqual(database.invalidate_character_snapshots([101]), 1)
        self.assertFalse(database.characters_are_loaded(101))
        self.assertEqual(len(database.get_characters(101)), 1)


    def test_complete_snapshot_cleanup_batches_queries_and_preserves_shared_references(self):
        self._add_two_adaptations()
        shared_actor = self._actor(7001, "Shared Voice Actor")
        first_cast = [self._character([shared_actor])]

        for offset in range(40):
            character = self._character([
                self._actor(7100 + offset, f"Private Actor {offset}")
            ])
            character["node"]["id"] = 600 + offset
            character["node"]["name"] = {"full": f"Private Character {offset}"}
            first_cast.append(character)

        database.save_characters(101, first_cast)
        database.save_characters(102, [self._character([shared_actor])])
        # Keep the first private actor alive through a separate staff credit.
        database.save_staff(101, [{
            "role": "Storyboard",
            "node": {
                "id": 7100,
                "name": {"full": "Private Actor 0"},
                "image": {"large": "https://example.invalid/7100.jpg"},
            },
        }])

        real_get_connection = database.get_connection
        connections = []

        class CountingConnection:
            def __init__(self, connection):
                self._connection = connection
                self.execute_calls = 0
                self.executemany_calls = 0

            def execute(self, *args, **kwargs):
                self.execute_calls += 1
                return self._connection.execute(*args, **kwargs)

            def executemany(self, *args, **kwargs):
                self.executemany_calls += 1
                return self._connection.executemany(*args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._connection, name)

        def counted_connection():
            wrapped = CountingConnection(real_get_connection())
            connections.append(wrapped)
            return wrapped

        with patch.object(database, "get_connection", side_effect=counted_connection):
            database.save_characters(101, [])

        self.assertEqual(len(connections), 1)
        # The old loop performed repeated SELECT/DELETE calls for each stale
        # character and actor. The set-based cleanup keeps direct calls bounded.
        self.assertLessEqual(connections[0].execute_calls, 25)
        self.assertGreaterEqual(connections[0].executemany_calls, 5)

        self.assertEqual(database.get_characters(101), [])
        self.assertEqual(len(database.get_characters(102)), 1)
        self.assertEqual(dict(database.get_characters(102)[0])["person_id"], 7001)

        connection = database.get_connection()
        try:
            characters = {
                int(row["id"])
                for row in connection.execute(
                    "SELECT id FROM characters WHERE id BETWEEN 600 AND 639"
                ).fetchall()
            }
            actor_ids = {
                int(row["id"])
                for row in connection.execute(
                    "SELECT id FROM people WHERE id BETWEEN 7100 AND 7139"
                ).fetchall()
            }
            scoped_credits = connection.execute(
                "SELECT work_id, character_id, person_id "
                "FROM work_character_voice_actors WHERE character_id = 501 "
                "ORDER BY work_id"
            ).fetchall()
        finally:
            connection.close()

        self.assertEqual(characters, set())
        self.assertEqual(actor_ids, {7100})
        self.assertEqual(
            [(int(row["work_id"]), int(row["character_id"]), int(row["person_id"]))
             for row in scoped_credits],
            [(102, 501, 7001)],
        )


    def test_legacy_global_actor_rows_migrate_and_mark_cast_for_refresh(self):
        self._add_two_adaptations()
        actor = self._actor(7001, "Legacy Actor")
        database.save_characters(101, [self._character([actor])])
        database.save_characters(102, [self._character([])])
        database.save_anime(self._work(103))

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
        self.assertTrue(database.characters_are_loaded(103))
        # Fresh cast snapshots can now correct this legacy ambiguous association
        # independently for each adaptation without cross-deleting the actor.
        database.save_characters(102, [self._character([])])
        self.assertEqual(dict(database.get_characters(101)[0])["person_id"], 7001)
        self.assertIsNone(dict(database.get_characters(102)[0])["person_id"])


if __name__ == "__main__":
    unittest.main()
