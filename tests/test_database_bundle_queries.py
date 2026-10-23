"""Parity and query-count tests for batched bundle detail reads."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database


def reference_bundle_characters(work_ids):
    """Former per-work implementation, retained as a parity oracle."""
    unique = {}
    priorities = {"MAIN": 0, "SUPPORTING": 1, "BACKGROUND": 2}
    for work_id in work_ids or []:
        for raw in database.get_characters(work_id):
            row = dict(raw)
            try:
                character_id = int(row["id"])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            role = str(row.get("character_role") or "").upper()
            existing = unique.get(character_id)
            if existing is None:
                unique[character_id] = row
                continue
            old_role = str(existing.get("character_role") or "").upper()
            if priorities.get(role, 3) < priorities.get(old_role, 3):
                existing["character_role"] = row.get("character_role")

            def voice_priority(item):
                try:
                    person_id = int(item.get("person_id") or 0)
                except (TypeError, ValueError, OverflowError):
                    person_id = 0
                if person_id <= 0:
                    return (2, "", 0)
                language = database._voice_actor_language_label(item.get("person_language"))
                return (0 if language == "Japanese" else 1,
                        str(item.get("person_name") or "").casefold(), person_id)

            if voice_priority(row) < voice_priority(existing):
                for key in ("person_id", "person_name", "person_image_path",
                            "person_image_url", "person_language"):
                    existing[key] = row.get(key)
    return sorted(unique.values(), key=lambda row: (
        priorities.get(str(row.get("character_role") or "").upper(), 3),
        str(row.get("character_name") or "").lower(),
    ))


def reference_bundle_staff(work_ids):
    """Former per-work implementation, retained as a parity oracle."""
    unique = {}
    for work_id in work_ids or []:
        for row in database.get_staff(work_id):
            person_id = int(row["person_id"])
            entry = unique.get(person_id)
            if entry is None:
                entry = dict(row)
                entry["_roles"] = []
                unique[person_id] = entry
            for role in str(row["role"] or "").split("\n"):
                role = role.strip()
                if role and role not in entry["_roles"]:
                    entry["_roles"].append(role)
    for entry in unique.values():
        entry["role"] = "\n".join(entry.pop("_roles", []))
    from recommendation_engine import staff_role_weight
    return sorted(unique.values(), key=lambda row: (
        -max((staff_role_weight(role) for role in str(row.get("role") or "").split("\n")),
             default=0.30),
        str(row.get("name") or "").casefold(),
    ))


def reference_bundle_relations(work_ids):
    """Former per-work implementation, retained as a parity oracle."""
    ids = database._validated_work_ids(work_ids)
    if not ids:
        return []
    unique = {}
    for work_id in ids:
        for row in database.get_relations(work_id):
            target_id = row["target_id"]
            if target_id is None:
                continue
            target_id = int(target_id)
            if target_id in ids:
                continue
            entry = unique.get(target_id)
            if entry is None:
                entry = dict(row)
                entry["_relation_types"] = []
                unique[target_id] = entry
            relation_type = str(row["relation_type"] or "OTHER")
            if relation_type not in entry["_relation_types"]:
                entry["_relation_types"].append(relation_type)
    for entry in unique.values():
        entry["relation_types"] = "\n".join(entry.pop("_relation_types", []))
    return sorted(unique.values(), key=lambda row: str(row.get("title") or "").lower())


class BundleDetailBatchingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            database, "DATABASE_NAME", str(Path(self.temp_dir.name) / "bundle-test.sqlite3")
        )
        self.db_patch.start()
        con = database.get_connection()
        try:
            con.executescript("""
                CREATE TABLE works (
                    id INTEGER PRIMARY KEY, title TEXT NOT NULL, type TEXT NOT NULL,
                    format TEXT, cover_url TEXT, cover_path TEXT
                );
                CREATE TABLE characters (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, image_url TEXT, image_path TEXT
                );
                CREATE TABLE people (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, image_url TEXT, image_path TEXT
                );
                CREATE TABLE work_characters (
                    work_id INTEGER NOT NULL, character_id INTEGER NOT NULL, role TEXT,
                    PRIMARY KEY (work_id, character_id)
                );
                CREATE TABLE work_character_voice_actors (
                    work_id INTEGER NOT NULL, character_id INTEGER NOT NULL,
                    person_id INTEGER NOT NULL, language TEXT,
                    PRIMARY KEY (work_id, character_id, person_id)
                );
                CREATE TABLE work_staff (
                    work_id INTEGER NOT NULL, person_id INTEGER NOT NULL, role TEXT NOT NULL,
                    PRIMARY KEY (work_id, person_id, role)
                );
                CREATE TABLE work_relations (
                    source_id INTEGER NOT NULL, target_id INTEGER NOT NULL,
                    relation_type TEXT NOT NULL,
                    PRIMARY KEY (source_id, target_id, relation_type)
                );
            """)
            con.executemany(
                "INSERT INTO works (id,title,type,format,cover_url) VALUES (?,?,'ANIME','TV',?)",
                [(1, "Alpha Series", "cover-1"), (2, "Beta Series", "cover-2"),
                 (3, "Gamma Series", "cover-3"), (4, "Delta External", "cover-4"),
                 (5, "Epsilon External", "cover-5"), (6, "Zeta External", "cover-6")],
            )
            con.executemany("INSERT INTO characters VALUES (?,?,?,?)", [
                (10, "A Character", "https://example.invalid/a.png", None),
                (11, "B Character", None, "cache/b.png"),
                (12, "C Character", "https://example.invalid/c.png", "cache/c.png"),
            ])
            con.executemany("INSERT INTO people VALUES (?,?,?,?)", [
                (100, "Z Voice Actor", "https://example.invalid/100.png", None),
                (101, "A Japanese Voice Actor", None, "cache/101.png"),
                (102, "B English Voice Actor", None, None),
                (103, "C Voice Actor", None, "cache/103.png"),
                (200, "Alex Staff", "https://example.invalid/200.png", None),
                (201, "Taylor Staff", None, "cache/201.png"),
                (202, "Morgan Staff", None, None),
                (203, "Same Name", None, None), (204, "same name", None, None),
            ])
            con.executemany("INSERT INTO work_characters VALUES (?,?,?)", [
                (1, 10, "MAIN"), (1, 11, "SUPPORTING"), (1, 12, "BACKGROUND"),
                (2, 10, "SUPPORTING"), (2, 12, "SUPPORTING"), (3, 11, "MAIN"),
            ])
            con.executemany("INSERT INTO work_character_voice_actors VALUES (?,?,?,?)", [
                (1, 10, 100, "English"), (1, 10, 101, "Japanese"),
                (2, 10, 102, "English"), (1, 11, 103, "ja"),
                (2, 12, 102, "English"), (3, 11, 101, "Japanese"),
            ])
            con.executemany("INSERT INTO work_staff VALUES (?,?,?)", [
                (1, 200, "Music"), (1, 200, "Original Creator"), (2, 200, "Director"),
                (3, 200, "Music"), (1, 201, "Producer"), (2, 201, "Planning"),
                (2, 201, "Producer"), (1, 202, "Script"), (2, 202, "Series Composition"),
                (1, 203, "Music"), (1, 204, "music"),
            ])
            con.executemany("INSERT INTO work_relations VALUES (?,?,?)", [
                (1, 2, "SEQUEL"), (1, 4, "ADAPTATION"), (1, 4, "PREQUEL"),
                (1, 5, "OTHER"), (2, 4, "SEQUEL"), (2, 6, "SIDE_STORY"),
                (3, 6, "SEQUEL"),
            ])
            con.commit()
        finally:
            con.close()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_batched_results_match_former_per_work_implementation(self):
        ids = [2, 1, 2, "1", None, "not-an-id", 3]
        self.assertEqual(database.get_bundle_characters(ids), reference_bundle_characters(ids))
        self.assertEqual(database.get_bundle_staff(ids), reference_bundle_staff(ids))
        relation_ids = [2, 1, 1]
        self.assertEqual(database.get_bundle_relations(relation_ids), reference_bundle_relations(relation_ids))

    def test_each_nonempty_bundle_reader_uses_one_connection(self):
        for fn in (database.get_bundle_characters, database.get_bundle_staff, database.get_bundle_relations):
            with self.subTest(function=fn.__name__):
                with patch.object(database, "get_connection", wraps=database.get_connection) as factory:
                    fn([1, 2, 3])
                self.assertEqual(factory.call_count, 1)

    def test_empty_and_invalid_relation_inputs_keep_existing_contract(self):
        self.assertEqual(database.get_bundle_characters(None), [])
        self.assertEqual(database.get_bundle_staff(None), [])
        self.assertEqual(database.get_bundle_relations(None), [])
        self.assertEqual(database.get_bundle_relations([1, "invalid"]), [])


if __name__ == "__main__":
    unittest.main()
