"""Parity and query-count tests for batched bundle detail reads."""
import json
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


def reference_bundle_detail_readiness(work_ids):
    """Former preload readiness checks, retained as a parity oracle."""
    ids = database._validated_work_ids(work_ids)
    if ids is None or not ids:
        return {}
    result = {}
    for work_id in ids:
        characters_loaded = database.characters_are_loaded(work_id)
        work = database.get_work(work_id)
        if work is None:
            result[work_id] = {
                "work_exists": False,
                "characters_loaded": characters_loaded,
                "expected_episodes": 0,
                "episodes_saved": False,
            }
            continue
        expected_episodes = work["episodes"] or 0
        saved = database.get_episodes(work_id)
        result[work_id] = {
            "work_exists": True,
            "characters_loaded": characters_loaded,
            "expected_episodes": expected_episodes,
            "episodes_saved": bool(saved),
        }
    return result


def reference_episode_section_snapshot(work_id):
    """Former standalone readers, kept as a parity oracle."""
    work = database.get_work(work_id)
    if work is None:
        return {
            "work": None,
            "episodes": [],
            "catalog_metadata": None,
        }
    metadata = database.get_provider_metadata(work_id, "tmdb_episode_match_version")
    return {
        "work": dict(work),
        "episodes": [dict(row) for row in database.get_episodes(work_id)],
        "catalog_metadata": metadata,
    }


def reference_bundle_staff_page_state(work_ids):
    """Former per-work staff count and provider-metadata reads."""
    ids = database._validated_work_ids(work_ids)
    if ids is None or not ids:
        return {}
    result = {}
    for work_id in ids:
        result[work_id] = {
            "saved_staff_count": len(database.get_staff(work_id)),
            "anilist_media_id": (
                database.get_provider_metadata(work_id, "anilist_media_id")
                if work_id < 0 else None
            ),
            "page_info": database.get_provider_metadata(work_id, "anilist_staff_page_info"),
        }
    return result


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
                    format TEXT, cover_url TEXT, cover_path TEXT,
                    episodes INTEGER, characters_loaded INTEGER NOT NULL DEFAULT 0,
                    tmdb_id INTEGER, tmdb_season_number INTEGER
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
                CREATE TABLE bundle_overrides (
                    bundle_anchor_id INTEGER PRIMARY KEY,
                    custom_title TEXT,
                    cover_work_id INTEGER,
                    custom_cover_path TEXT
                );
                CREATE TABLE manual_bundle_links (
                    work_a INTEGER NOT NULL, work_b INTEGER NOT NULL,
                    PRIMARY KEY (work_a, work_b)
                );
                CREATE TABLE bundle_exclusions (
                    work_a INTEGER NOT NULL, work_b INTEGER NOT NULL,
                    PRIMARY KEY (work_a, work_b)
                );
                CREATE TABLE automatic_bundle_memberships (
                    bundle_id INTEGER NOT NULL, work_id INTEGER NOT NULL,
                    PRIMARY KEY (bundle_id, work_id)
                );
                CREATE TABLE episodes (
                    id INTEGER PRIMARY KEY,
                    work_id INTEGER NOT NULL,
                    episode_number INTEGER NOT NULL,
                    title TEXT, description TEXT, air_date TEXT,
                    thumbnail_url TEXT, watched INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (work_id, episode_number)
                );
                CREATE TABLE user_library (
                    work_id INTEGER PRIMARY KEY, status TEXT,
                    progress_episodes INTEGER, progress_chapters INTEGER,
                    progress_volumes INTEGER, rating INTEGER, notes TEXT,
                    added_date TEXT, updated_date TEXT
                );
                CREATE TABLE release_reminders (
                    work_id INTEGER NOT NULL,
                    episode_number INTEGER NOT NULL,
                    notified_date TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (work_id, episode_number)
                );
                CREATE TABLE work_provider_metadata (
                    work_id INTEGER NOT NULL,
                    provider TEXT NOT NULL,
                    provider_id TEXT,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (work_id, provider)
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
        for fn in (database.get_bundle_characters, database.get_bundle_staff, database.get_bundle_relations, database.get_bundle_detail_readiness, database.get_bundle_staff_page_state):
            with self.subTest(function=fn.__name__):
                with patch.object(database, "get_connection", wraps=database.get_connection) as factory:
                    fn([1, 2, 3])
                self.assertEqual(factory.call_count, 1)

    def test_episode_section_snapshot_matches_legacy_readers_with_one_connection(self):
        con = database.get_connection()
        try:
            con.execute(
                "UPDATE works SET episodes = 12, tmdb_id = 77, tmdb_season_number = 2 "
                "WHERE id = 1"
            )
            con.executemany(
                "INSERT INTO episodes (id, work_id, episode_number, title, watched) VALUES (?, ?, ?, ?, ?)",
                [(201, 1, 1, "Episode 1", 1), (202, 1, 2, "Episode 2", 0)],
            )
            con.execute(
                "INSERT INTO work_provider_metadata (work_id, provider, payload_json) VALUES (?, ?, ?)",
                (1, "tmdb_episode_match_version", json.dumps({
                    "version": 4, "fetched_at": 1750000000, "complete": True
                })),
            )
            con.commit()
        finally:
            con.close()

        expected = reference_episode_section_snapshot(1)
        with patch.object(database, "get_connection", wraps=database.get_connection) as factory:
            actual = database.get_episode_section_snapshot(1)

        self.assertEqual(factory.call_count, 1)
        self.assertEqual(dict(actual["work"]), expected["work"])
        self.assertEqual([dict(row) for row in actual["episodes"]], expected["episodes"])
        self.assertEqual(actual["catalog_metadata"], expected["catalog_metadata"])
        self.assertIsNone(actual["catalog_metadata_error"])
        self.assertEqual(actual["work"]["tmdb_id"], 77)
        self.assertEqual(actual["work"]["tmdb_season_number"], 2)

    def test_episode_section_snapshot_reports_missing_work_without_extra_reads(self):
        with patch.object(database, "get_connection", wraps=database.get_connection) as factory:
            actual = database.get_episode_section_snapshot(987654)

        self.assertEqual(factory.call_count, 1)
        self.assertIsNone(actual["work"])
        self.assertEqual(actual["episodes"], [])
        self.assertIsNone(actual["catalog_metadata"])
        self.assertIsNone(actual["catalog_metadata_error"])

    def test_batched_staff_page_state_matches_per_work_reads_with_one_connection(self):
        con = database.get_connection()
        try:
            con.executemany(
                "INSERT INTO work_provider_metadata (work_id, provider, payload_json) VALUES (?, ?, ?)",
                [
                    (1, "anilist_staff_page_info", json.dumps({"hasNextPage": True, "currentPage": 3})),
                    (2, "anilist_staff_page_info", json.dumps({"hasNextPage": False, "currentPage": 4})),
                    (-10, "anilist_media_id", json.dumps({"id": 9910})),
                    (-10, "anilist_staff_page_info", json.dumps({"hasNextPage": True, "currentPage": 2})),
                ],
            )
            con.commit()
        finally:
            con.close()

        ids = [1, 2, 3, -10, 99]
        expected = reference_bundle_staff_page_state(ids)
        with patch.object(database, "get_connection", wraps=database.get_connection) as factory:
            actual = database.get_bundle_staff_page_state(ids)
        self.assertEqual(actual, expected)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(actual[1]["saved_staff_count"], 5)
        self.assertEqual(actual[1]["page_info"], {"hasNextPage": True, "currentPage": 3})
        self.assertEqual(actual[-10]["anilist_media_id"], {"id": 9910})

    def test_batched_readiness_matches_per_work_checks_and_one_connection(self):
        con = database.get_connection()
        try:
            con.execute("UPDATE works SET episodes = 2, characters_loaded = 1 WHERE id = 1")
            con.execute("UPDATE works SET episodes = 4, characters_loaded = 1 WHERE id = 2")
            con.execute("UPDATE works SET episodes = 0, characters_loaded = 0 WHERE id = 3")
            con.execute("UPDATE work_characters SET role = NULL WHERE work_id = 2 AND character_id = 10")
            con.executemany(
                "INSERT INTO episodes (id, work_id, episode_number) VALUES (?, ?, ?)",
                [(101, 1, 1), (102, 1, 2)],
            )
            con.commit()
        finally:
            con.close()

        ids = [1, 2, 3, 99]
        expected = reference_bundle_detail_readiness(ids)
        with patch.object(database, "get_connection", wraps=database.get_connection) as factory:
            actual = database.get_bundle_detail_readiness(ids)
        self.assertEqual(actual, expected)
        self.assertEqual(factory.call_count, 1)
        self.assertTrue(actual[1]["characters_loaded"])
        self.assertTrue(actual[1]["episodes_saved"])
        self.assertFalse(actual[2]["characters_loaded"])
        self.assertFalse(actual[2]["episodes_saved"])
        self.assertTrue(actual[3]["work_exists"])
        self.assertTrue(actual[3]["characters_loaded"] is False)
        self.assertFalse(actual[99]["work_exists"])

    def test_bulk_bundle_overrides_chunk_large_id_lists_and_preserve_anchor_priority(self):
        con = database.get_connection()
        try:
            con.executemany(
                "INSERT INTO bundle_overrides VALUES (?, ?, ?, ?)",
                [(10, "Ten", None, None), (500, "Five Hundred", None, None),
                 (1200, "Twelve Hundred", None, None)],
            )
            con.commit()
        finally:
            con.close()

        ids = list(range(1, 1201))
        with patch.object(database, "get_connection", wraps=database.get_connection) as factory:
            rows = database.get_bundle_overrides(ids)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(
            [(row["bundle_anchor_id"], row["custom_title"]) for row in rows],
            [(10, "Ten"), (500, "Five Hundred"), (1200, "Twelve Hundred")],
        )
        chosen = database.get_bundle_override([1200, 500, 10])
        self.assertEqual(chosen["bundle_anchor_id"], 10)

    def test_large_library_link_exclusion_and_membership_queries_chunk_and_deduplicate(self):
        con = database.get_connection()
        try:
            con.executemany(
                "INSERT INTO manual_bundle_links VALUES (?, ?)",
                [(10, 900), (400, 401), (1200, 1201)],
            )
            con.executemany(
                "INSERT INTO bundle_exclusions VALUES (?, ?)",
                [(10, 900), (400, 401), (1200, 1201)],
            )
            con.executemany(
                "INSERT INTO automatic_bundle_memberships VALUES (?, ?)",
                [(9001, 10), (9001, 900), (9002, 1200), (9002, 1300)],
            )
            con.commit()
        finally:
            con.close()

        ids = list(range(1, 1201))
        cases = (
            (database.get_manual_bundle_links, [(10, 900), (400, 401), (1200, 1201)]),
            (database.get_bundle_exclusions, [(10, 900), (400, 401), (1200, 1201)]),
            (database.get_automatic_bundle_memberships, [
                (9001, 10), (9001, 900), (9002, 1200), (9002, 1300),
            ]),
        )
        for function, expected in cases:
            with self.subTest(function=function.__name__):
                with patch.object(database, "get_connection", wraps=database.get_connection) as factory:
                    rows = function(ids)
                self.assertEqual(
                    [(int(row[0]), int(row[1])) for row in rows],
                    expected,
                )
                self.assertEqual(factory.call_count, 1)

    def test_large_recommendation_credit_and_voice_actor_queries_stay_batched(self):
        ids = list(range(1, 1201))
        with patch.object(database, "get_connection", wraps=database.get_connection) as factory:
            profile = database.get_recommendation_credit_profile(ids)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(len(profile), 1200)
        self.assertTrue(profile[1]["characters"])
        self.assertTrue(profile[1]["staff"])

        with patch.object(database, "get_connection", wraps=database.get_connection) as factory:
            staff_state = database.get_bundle_staff_page_state(ids)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(len(staff_state), 1200)
        self.assertEqual(staff_state[1]["saved_staff_count"], 5)

        with patch.object(database, "get_connection", wraps=database.get_connection) as factory:
            actors = database.get_bundle_character_voice_actors(ids, 10)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(
            {actor["person_id"] for actor in actors},
            {100, 101, 102},
        )

    def test_large_id_write_paths_chunk_and_preserve_bundle_semantics(self):
        # Fill out the disposable fixture to 1,200 real works. This test never
        # touches the user's NekoTrack database.
        con = database.get_connection()
        try:
            con.executemany(
                "INSERT INTO works (id, title, type, episodes, characters_loaded) VALUES (?, ?, 'ANIME', 0, 1)",
                [
                    (work_id, f"Synthetic Work {work_id}")
                    for work_id in range(7, 1201)
                ],
            )
            con.execute("UPDATE works SET characters_loaded = 1")
            con.executemany(
                "INSERT INTO manual_bundle_links (work_a, work_b) VALUES (?, ?)",
                [(1, 1200), (2, 1200)],
            )
            con.commit()
        finally:
            con.close()

        ids = list(range(1, 1201))
        with patch.object(database, "get_connection", wraps=database.get_connection) as factory:
            self.assertEqual(database.invalidate_character_snapshots(ids), 1200)
        self.assertEqual(factory.call_count, 1)
        con = database.get_connection()
        try:
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM works WHERE characters_loaded = 0").fetchone()[0],
                1200,
            )
        finally:
            con.close()

        with patch.object(database, "get_connection", wraps=database.get_connection) as factory:
            self.assertTrue(database.save_automatic_bundle_membership(1, ids))
        self.assertEqual(factory.call_count, 1)
        saved = database.get_automatic_bundle_memberships([1])
        self.assertEqual(len(saved), 1200)
        self.assertEqual((saved[0]["bundle_id"], saved[0]["work_id"]), (1, 1))
        self.assertEqual((saved[-1]["bundle_id"], saved[-1]["work_id"]), (1, 1200))

        with patch.object(database, "get_connection", wraps=database.get_connection) as factory:
            self.assertTrue(database.save_bundle_override(
                ids, anchor_id=1, custom_title="Large bundle", cover_work_id=1200
            ))
        self.assertEqual(factory.call_count, 1)
        override = database.get_bundle_override([1200, 1])
        self.assertEqual(override["custom_title"], "Large bundle")
        self.assertEqual(override["cover_work_id"], 1200)
        with patch.object(database, "get_connection", wraps=database.get_connection) as factory:
            self.assertTrue(database.clear_bundle_override(ids))
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(database.get_bundle_overrides(ids), [])

        with patch.object(database, "get_connection", wraps=database.get_connection) as factory:
            self.assertTrue(database.remove_bundle_member(1, 1200, ids))
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(database.get_manual_bundle_links(), [])
        exclusions = database.get_bundle_exclusions()
        self.assertEqual(len(exclusions), 1199)
        self.assertEqual(
            (exclusions[0]["work_a"], exclusions[0]["work_b"]),
            (1, 1200),
        )

    def test_large_episode_catalog_pruning_uses_temp_table_and_preserves_kept_rows(self):
        con = database.get_connection()
        try:
            con.executemany(
                "INSERT INTO episodes (id, work_id, episode_number, title, watched) VALUES (?, 1, ?, ?, 0)",
                [(101, 1, "One"), (102, 2, "Two"), (1200, 1200, "Twelve hundred"), (1500, 1500, "Stale episode")],
            )
            con.executemany(
                "INSERT INTO release_reminders (work_id, episode_number, notified_date) VALUES (1, ?, NULL)",
                [(1200,), (1500,)],
            )
            con.execute(
                "INSERT INTO user_library (work_id, status, progress_episodes, progress_chapters, progress_volumes) "
                "VALUES (1, 'Watching', 1400, 0, 0)"
            )
            con.commit()
        finally:
            con.close()

        replacement_catalog = [{"episodeNumber": number} for number in range(1, 1201)]
        self.assertEqual(database.prune_episode_catalog(1, replacement_catalog), 1)

        con = database.get_connection()
        try:
            remaining_episodes = [
                int(row["episode_number"])
                for row in con.execute(
                    "SELECT episode_number FROM episodes WHERE work_id = 1 ORDER BY episode_number"
                ).fetchall()
            ]
            remaining_reminders = [
                int(row["episode_number"])
                for row in con.execute(
                    "SELECT episode_number FROM release_reminders WHERE work_id = 1 ORDER BY episode_number"
                ).fetchall()
            ]
            progress = con.execute(
                "SELECT progress_episodes FROM user_library WHERE work_id = 1"
            ).fetchone()["progress_episodes"]
        finally:
            con.close()

        self.assertEqual(remaining_episodes, [1, 2, 1200])
        self.assertEqual(remaining_reminders, [1200])
        self.assertEqual(progress, 1200)

    def test_batched_episode_thumbnail_paths_match_single_writes_with_one_connection(self):
        con = database.get_connection()
        try:
            con.executemany(
                "INSERT INTO episodes (id, work_id, episode_number, title, thumbnail_url) VALUES (?, 1, ?, ?, NULL)",
                [(801, 1, "Episode 1"), (802, 2, "Episode 2")],
            )
            con.commit()
        finally:
            con.close()

        paths = [
            (1, "cache/episode-1.jpg"),
            (2, Path("cache") / "episode-2.jpg"),
            (2, "cache/episode-2-final.jpg"),
            (999, "cache/not-present.jpg"),
            (True, "cache/invalid.jpg"),
            (3, ""),
        ]
        with patch.object(database, "get_connection", wraps=database.get_connection) as factory:
            saved = database.save_episode_thumbnail_paths(1, paths)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(saved, {1, 2})

        con = database.get_connection()
        try:
            rows = con.execute(
                "SELECT episode_number, thumbnail_url FROM episodes WHERE work_id = 1 ORDER BY episode_number"
            ).fetchall()
        finally:
            con.close()
        self.assertEqual(
            [(int(row["episode_number"]), row["thumbnail_url"]) for row in rows],
            [(1, "cache/episode-1.jpg"), (2, "cache/episode-2-final.jpg")],
        )

    def test_save_episodes_batches_thumbnail_reads_and_preserves_cached_paths(self):
        with tempfile.TemporaryDirectory(prefix="nekotrack-save-episodes-") as directory:
            cached_file = Path(directory) / "local-episode.jpg"
            cached_file.write_bytes(b"cached")
            con = database.get_connection()
            try:
                con.executemany(
                    """
                    INSERT INTO episodes (
                        id, work_id, episode_number, title, description, air_date,
                        thumbnail_url, watched
                    ) VALUES (?, 1, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (501, 1, "Episode 1", "Old 1", "2020-01-01", str(cached_file), 1),
                        (502, 2, "Episode 2", "Old 2", "2020-01-08", "https://old.invalid/2.jpg", 0),
                    ],
                )
                con.commit()
            finally:
                con.close()

            incoming = [
                {
                    "episodeNumber": 1,
                    "title": "Episode 1 Updated",
                    "description": "New description",
                    "airdate": "2020-01-02",
                    "thumbnail": "https://image.tmdb.org/t/p/w500/remote-1.jpg",
                },
                {
                    "episodeNumber": 2,
                    "title": "Episode 2 Updated",
                    "thumbnail": "https://image.tmdb.org/t/p/w500/remote-2.jpg",
                },
                {
                    "episodeNumber": 3,
                    "title": "Episode 3 First",
                    "thumbnail": "https://image.tmdb.org/t/p/w500/remote-3-first.jpg",
                },
                {
                    "episodeNumber": 3,
                    "title": "Episode 3 Final",
                    "thumbnail": None,
                },
                {"episodeNumber": True, "title": "Invalid"},
                {"episodeNumber": 1.5, "title": "Fractional"},
            ]
            with patch.object(database, "get_connection", wraps=database.get_connection) as factory:
                database.save_episodes(1, incoming)
            self.assertEqual(factory.call_count, 1)

            con = database.get_connection()
            try:
                rows = con.execute(
                    """
                    SELECT episode_number, title, description, air_date, thumbnail_url, watched
                    FROM episodes WHERE work_id = 1 ORDER BY episode_number
                    """
                ).fetchall()
            finally:
                con.close()
            self.assertEqual(
                [(
                    int(row["episode_number"]), row["title"], row["description"],
                    row["air_date"], row["thumbnail_url"], int(row["watched"])
                ) for row in rows],
                [
                    (1, "Episode 1 Updated", "New description", "2020-01-02", str(cached_file), 1),
                    (2, "Episode 2 Updated", "Old 2", "2020-01-08", "https://image.tmdb.org/t/p/w500/remote-2.jpg", 0),
                    (3, "Episode 3 Final", None, None, "https://image.tmdb.org/t/p/w500/remote-3-first.jpg", 0),
                ],
            )

    def test_library_grouping_state_matches_three_readers_with_one_connection(self):
        con = database.get_connection()
        try:
            con.executemany(
                "INSERT INTO manual_bundle_links (work_a, work_b) VALUES (?, ?)",
                [(1, 4), (2, 5), (4, 6)],
            )
            con.executemany(
                "INSERT INTO bundle_exclusions (work_a, work_b) VALUES (?, ?)",
                [(1, 3), (4, 5), (6, 8)],
            )
            con.executemany(
                "INSERT INTO automatic_bundle_memberships (bundle_id, work_id) VALUES (?, ?)",
                [(1, 1), (1, 2), (1, 5), (4, 4), (4, 6), (9, 4), (9, 5)],
            )
            con.commit()
        finally:
            con.close()

        ids = [1, 2, 4, 6]
        expected = {
            "manual_links": [
                (int(row["work_a"]), int(row["work_b"]))
                for row in database.get_manual_bundle_links(ids)
            ],
            "exclusions": [
                (int(row["work_a"]), int(row["work_b"]))
                for row in database.get_bundle_exclusions(ids)
            ],
            "automatic_memberships": [
                (int(row["bundle_id"]), int(row["work_id"]))
                for row in database.get_automatic_bundle_memberships(ids)
            ],
        }

        with patch.object(database, "get_connection", wraps=database.get_connection) as factory:
            actual_rows = database.get_library_bundle_grouping_state(ids)
        self.assertEqual(factory.call_count, 1)
        actual = {
            "manual_links": [(int(row["work_a"]), int(row["work_b"])) for row in actual_rows["manual_links"]],
            "exclusions": [(int(row["work_a"]), int(row["work_b"])) for row in actual_rows["exclusions"]],
            "automatic_memberships": [
                (int(row["bundle_id"]), int(row["work_id"]))
                for row in actual_rows["automatic_memberships"]
            ],
        }
        self.assertEqual(actual, expected)

    def test_empty_and_invalid_relation_inputs_keep_existing_contract(self):
        self.assertEqual(database.get_bundle_characters(None), [])
        self.assertEqual(database.get_bundle_staff(None), [])
        self.assertEqual(database.get_bundle_relations(None), [])
        self.assertEqual(database.get_bundle_overrides(None), [])
        self.assertEqual(database.get_bundle_overrides([1, "invalid"]), [])
        self.assertEqual(database.get_bundle_detail_readiness(None), {})
        self.assertEqual(database.get_bundle_staff_page_state(None), {})
        self.assertEqual(database.get_bundle_detail_readiness([1, "invalid"]), {})
        self.assertEqual(database.get_bundle_relations([1, "invalid"]), [])


if __name__ == "__main__":
    unittest.main()
