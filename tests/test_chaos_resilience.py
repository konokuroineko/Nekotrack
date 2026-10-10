"""Deterministic chaos tests for provider payloads, bundling graphs, and persisted state.

These tests deliberately generate malformed-but-JSON-like provider fields and
long randomized database operation sequences. They use fixed seeds so failures
are reproducible and never touch a real user's settings, database, or images.
"""
import os
import random
from concurrent.futures import ThreadPoolExecutor
import tempfile
import unittest
from unittest.mock import Mock, patch

import database
import mangabaka_api as mb
import series
import updater
import api as nt_api
from datetime import date
from pathlib import Path

def _fuzz_seed(base):
    """Keep tests reproducible while allowing each soak iteration to vary inputs."""
    try:
        offset = int(os.environ.get("NEKOTRACK_FUZZ_SEED", "0"))
    except (TypeError, ValueError, OverflowError):
        offset = 0
    return (int(base) + offset) % (2**32)



class ProviderPayloadChaosTests(unittest.TestCase):
    SEED = 0x4E454B4F

    def test_normalizer_survives_malformed_optional_provider_fields(self):
        rng = random.Random(_fuzz_seed(self.SEED))
        title_fields = [
            None,
            "unexpected title shape",
            [{"language": "en", "title": "Chaos Title", "traits": ["official"]}],
            [{"language": "en", "title": "Chaos Title", "traits": "official"}],
            [{"language": "en", "title": "Chaos Title", "traits": 17}],
            [{"language": "ja", "title": "作品", "traits": {"official": True}}],
            [{"language": "en", "title": 42}, None, 8],
            {"en": "not the documented title list"},
        ]
        date_fields = [
            None,
            "2020-03-04",
            "not a date",
            2022,
            {},
            {"start": {"year": "not-a-year", "month": 1, "day": 1}},
            {"start": {"year": [2020], "month": 1, "day": 1}},
            {"start": {"year": 2020, "month": "bad", "day": 1}},
            {"start": {"year": 2020, "month": 99, "day": 80}},
            {"start": {"year": 2021, "month": 2, "day": 28}},
            {"start": 2020},
        ]
        ratings = [None, "", "unknown", "81.5", -1, 101, {}, [], 0, 100, True]
        counts = [None, "", "12 chapters", "unknown", -10, {}, [], 0, 5000]
        covers = [None, "", "https://example.invalid/cover.jpg", 5, [], {},
                  {"x350": "https://example.invalid/cover.jpg"}]

        for case in range(350):
            record = {
                "id": case + 1,
                "type": rng.choice(["manga", "novel", "manhwa", None, 3]),
                "status": rng.choice(["completed", "releasing", None, 42]),
                "content_rating": "safe",
                "titles": rng.choice(title_fields),
                "published": rng.choice(date_fields),
                "rating": rng.choice(ratings),
                "total_chapters": rng.choice(counts),
                "final_volume": rng.choice(counts),
                "cover": rng.choice(covers),
                "secondary_titles": rng.choice([
                    None, ["Alias A", "Alias B"], {"en": ["Alias C"], "ja": "別名"},
                    42, {"bad": None},
                ]),
            }
            with self.subTest(case=case):
                normalized = mb.normalize_series(record)
                self.assertEqual(normalized["type"], "MANGA")
                self.assertEqual(normalized["_mangabaka_id"], case + 1)
                self.assertEqual(normalized["id"], -(case + 1))
                self.assertIsInstance(normalized["title"], dict)
                self.assertTrue(normalized["title"]["english"])
                self.assertIsInstance(normalized["synonyms"], list)
                self.assertEqual(normalized["relations"], {"edges": []})
                score = normalized["averageScore"]
                self.assertTrue(score is None or 0 <= score <= 100)
                date = normalized["startDate"]
                self.assertEqual(set(date), {"year", "month", "day"})
                if date["year"] is not None:
                    self.assertTrue(1 <= date["year"] <= 9999)
                    self.assertTrue(1 <= date["month"] <= 12)
                    self.assertTrue(1 <= date["day"] <= 31)

    def test_search_skips_bad_rows_and_malformed_pagination(self):
        payload = {
            "data": {
                "items": [
                    {
                        "id": 31,
                        "type": "novel",
                        "status": "completed",
                        "content_rating": "safe",
                        "rating": 84,
                        "titles": [{"language": "en", "title": "Valid Result"}],
                        "published": {"start": {"year": "not-a-year"}},
                    },
                    {"title": "Missing ID", "content_rating": "safe"},
                    None,
                    {"id": "not-an-id", "content_rating": "safe"},
                ]
            },
            "pagination": {
                "page": "not-a-page",
                "limit": {"unexpected": "object"},
                "count": "not-a-count",
                "next": True,
            },
        }
        with patch.object(mb, "search_series", return_value=payload):
            result = mb.search_media("chaos", page=1, media_type="MANGA", media_format="NOVEL")

        self.assertEqual([item["_mangabaka_id"] for item in result["media"]], [31])
        self.assertEqual(result["pageInfo"]["currentPage"], 1)
        self.assertGreaterEqual(result["pageInfo"]["lastPage"], 1)
        self.assertIsInstance(result["pageInfo"]["hasNextPage"], bool)

    def test_local_filter_never_admits_malformed_or_nonmatching_rows(self):
        rng = random.Random(_fuzz_seed(self.SEED + 1))
        rows = []
        for item_id in range(1, 151):
            status = rng.choice(["completed", "releasing", "upcoming", None, 42])
            rating = rng.choice([50, 70, 70.5, 90, None, "bad"])
            rows.append({
                "id": item_id,
                "type": "novel",
                "status": status,
                "content_rating": "safe",
                "rating": rating,
                "published": {"start": "2020-02-03"},
                "tags": [{"name": rng.choice(["Fantasy", "Romance", "Action"])}],
                "titles": [{"language": "en", "title": f"Novel {item_id}"}],
            })
        payload = {"data": {"items": rows}, "pagination": {"page": 1, "limit": 200, "count": len(rows)}}
        with patch.object(mb, "search_series", return_value=payload):
            result = mb.search_media(
                "novel", page=1, media_type="MANGA", media_format="NOVEL",
                filters={"status": "FINISHED", "min_score": 70, "year": "2020", "genre": "Fantasy"},
                limit=200,
            )

        for item in result["media"]:
            raw = item["_mangabaka"]
            self.assertEqual(item["format"], "NOVEL")
            self.assertIn(str(raw.get("status") or "").casefold(), {"completed", "finished"})
            self.assertGreaterEqual(float(raw["rating"]), 70)
            self.assertEqual(mb._date_parts(raw)["year"], 2020)
            self.assertTrue(
                any(
                    "fantasy" in str(tag.get(key, "")).casefold()
                    for tag in (raw.get("tags") or [])
                    if isinstance(tag, dict)
                    for key in ("name", "title", "name_path", "slug")
                )
                or "fantasy" in str(raw.get("genre") or "").casefold()
                or "fantasy" in str(raw.get("genres") or "").casefold()
            )


class BundlingGraphChaosTests(unittest.TestCase):
    SEED = 0x53455249
    FORMATS = ["TV", "TV_SHORT", "OVA", "ONA", "MOVIE", "SPECIAL", "MUSIC", "MANGA", "NOVEL", None]
    RELATIONS = [
        "PREQUEL", "SEQUEL", "PARENT", "SIDE_STORY", "SUMMARY", "FULL_STORY",
        "SPIN_OFF", "ALTERNATIVE", "COMPILATION", "CONTAINS", "CHARACTER",
        "UNKNOWN", None,
    ]

    def test_random_cyclic_relation_graphs_preserve_each_search_result_once(self):
        rng = random.Random(_fuzz_seed(self.SEED))
        preference_keys = {
            "bundle_include_movies", "bundle_include_ovas", "bundle_include_onas",
            "bundle_include_specials", "bundle_include_manga", "bundle_include_novels",
            "bundle_include_one_shots",
        }

        for case in range(120):
            count = rng.randint(1, 36)
            nodes = []
            for index in range(count):
                family = rng.randint(0, max(1, count // 4))
                title = rng.choice([
                    f"Chaos Family {family}",
                    f"Chaos Family {family} Season {rng.randint(2, 5)}",
                    f"Unrelated Work {case}-{index}",
                    f"One Word {rng.choice(['Alpha', 'Beta', 'Gamma'])}",
                ])
                media_type = "MANGA" if rng.random() < 0.2 else "ANIME"
                fmt = rng.choice(self.FORMATS if media_type == "ANIME" else ["MANGA", "NOVEL", "ONE_SHOT", None])
                nodes.append({
                    "id": 100000 + case * 100 + index,
                    "type": media_type,
                    "format": fmt,
                    "title": {"english": title, "romaji": title, "native": None},
                    "startDate": {"year": rng.randint(1980, 2035), "month": rng.randint(1, 12), "day": 1},
                    "coverImage": {"large": None},
                    "relations": {"edges": []},
                    "_relations_loaded": True,
                })

            for source in nodes:
                possible_targets = [node for node in nodes if node["id"] != source["id"]]
                rng.shuffle(possible_targets)
                for target in possible_targets[:rng.randint(0, min(5, len(possible_targets)))]:
                    source["relations"]["edges"].append({
                        "relationType": rng.choice(self.RELATIONS),
                        "node": {
                            "id": target["id"],
                            "type": target["type"],
                            "format": target["format"],
                            "title": target["title"],
                            "coverImage": target["coverImage"],
                            "startDate": target["startDate"],
                            "episodes": rng.choice([None, 0, 12, 24]),
                        },
                    })

            preferences = {key: bool(rng.getrandbits(1)) for key in preference_keys}
            with (
                patch.object(series, "get", side_effect=lambda key: preferences.get(key, False)),
                patch.object(series, "get_manual_bundle_links", return_value=[]),
                patch.object(series, "get_bundle_exclusions", return_value=[]),
            ):
                groups = series.group_media_results(nodes, enrich=False, delay=0)

            expected_ids = {node["id"] for node in nodes}
            seen_ids = []
            for group in groups:
                members = group.get("_series_members") or [group]
                member_ids = [member["id"] for member in members]
                self.assertEqual(len(member_ids), len(set(member_ids)))
                seen_ids.extend(member_id for member_id in member_ids if member_id in expected_ids)
            with self.subTest(case=case, count=count):
                self.assertEqual(set(seen_ids), expected_ids)
                self.assertEqual(len(seen_ids), len(expected_ids))


class DatabaseStateMachineChaosTests(unittest.TestCase):
    SEED = 0x44415441

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.temp_dir.name)
        database.initialize_database()

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp_dir.cleanup()

    @staticmethod
    def work(work_id, media_type, media_format):
        return {
            "id": work_id,
            "type": media_type,
            "format": media_format,
            "title": {
                "english": f"State Machine Work {work_id}",
                "romaji": f"State Machine Work {work_id}",
                "native": None,
            },
            "episodes": 24 if media_type == "ANIME" else None,
            "chapters": 120 if media_type == "MANGA" else None,
            "volumes": 12 if media_type == "MANGA" else None,
            "coverImage": {"large": None},
            "startDate": {"year": 2020, "month": 1, "day": 1},
        }

    def test_provider_metadata_payloads_are_validated_before_database_access(self):
        with patch.object(database, "get_connection") as get_connection:
            with self.assertRaisesRegex(ValueError, "valid JSON"):
                database.save_provider_metadata(616, "mangabaka", {"nested": {1, 2}})
            with self.assertRaisesRegex(ValueError, "valid JSON"):
                database.save_provider_metadata(616, "mangabaka", {"score": float("nan")})
            with self.assertRaises(ValueError):
                database.save_provider_metadata(1 << 100, "mangabaka", {"id": 9})
            self.assertIsNone(database.get_provider_metadata(1 << 100))
            get_connection.assert_not_called()

        database.save_anime(self.work(616, "MANGA", "MANGA"))
        payload = {"id": 9, "titles": [{"language": "en", "title": "Provider title"}]}
        database.save_provider_metadata(616, "MangaBaka", payload, provider_id=9)
        self.assertEqual(database.get_provider_metadata(616), payload)

        # Even a SQL error after connection acquisition must roll back and close
        # the connection so later catalog imports do not inherit a leaked handle.
        connection = Mock()
        connection.execute.side_effect = RuntimeError("simulated SQL error")
        with patch.object(database, "get_connection", return_value=connection):
            with self.assertRaisesRegex(RuntimeError, "simulated SQL error"):
                database.save_provider_metadata(616, "mangabaka", {"id": 10})
        connection.rollback.assert_called_once()
        connection.close.assert_called_once()

    def test_non_list_character_payload_marks_cache_retryable_without_deleting_rows(self):
        work_id = 617
        database.save_anime(self.work(work_id, "ANIME", "TV"))
        complete_edge = {
            "node": {
                "id": 620,
                "name": {"full": "Cached Character"},
                "image": {"large": None},
            },
            "role": "MAIN",
            "voiceActors": [],
        }
        database.save_characters(work_id, [complete_edge])
        self.assertTrue(database.characters_are_loaded(work_id))

        database.save_characters(work_id, None)
        self.assertFalse(database.characters_are_loaded(work_id))
        connection = database.get_connection()
        try:
            rows = connection.execute(
                "SELECT character_id FROM work_characters WHERE work_id = ?",
                (work_id,),
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual([row["character_id"] for row in rows], [620])

    def assert_database_invariants(self):
        connection = database.get_connection()
        self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

        for table, left_column, right_column in (
            ("manual_bundle_links", "work_a", "work_b"),
            ("bundle_exclusions", "work_a", "work_b"),
        ):
            bad = connection.execute(
                f"""
                SELECT COUNT(*) FROM {table} pair
                LEFT JOIN works a ON a.id = pair.{left_column}
                LEFT JOIN works b ON b.id = pair.{right_column}
                WHERE a.id IS NULL OR b.id IS NULL
                   OR pair.{left_column} >= pair.{right_column}
                """
            ).fetchone()[0]
            self.assertEqual(bad, 0, table)

        invalid_reading = connection.execute(
            """
            SELECT COUNT(*) FROM reading_items
            WHERE item_number < 1 OR item_type NOT IN ('chapter', 'volume')
            """
        ).fetchone()[0]
        self.assertEqual(invalid_reading, 0)
        connection.close()

    def test_adding_existing_library_item_preserves_progress_and_user_metadata(self):
        work_id = 501
        database.save_anime(self.work(work_id, "ANIME", "TV"))
        database.add_to_library(work_id)
        database.save_episodes(work_id, [
            {"episodeNumber": 1, "title": "Episode 1"},
            {"episodeNumber": 2, "title": "Episode 2"},
            {"episodeNumber": 3, "title": "Episode 3"},
        ])
        database.set_episode_watched(work_id, 1, True)
        database.set_episode_watched(work_id, 2, True)
        database.ensure_reading_placeholders(work_id, "chapter", 5, limit=5)
        database.ensure_reading_placeholders(work_id, "volume", 3, limit=3)
        database.set_reading_item_read(work_id, "chapter", 2, True)
        database.set_reading_item_read(work_id, "volume", 1, True)

        connection = database.get_connection()
        connection.execute(
            "UPDATE user_library SET rating = 9, notes = ?, added_date = ? WHERE work_id = ?",
            ("keep this note", "2020-01-02 03:04:05", work_id),
        )
        connection.commit()
        before = dict(connection.execute(
            "SELECT * FROM user_library WHERE work_id = ?", (work_id,)
        ).fetchone())
        connection.close()

        database.add_to_library(work_id, "Paused")

        connection = database.get_connection()
        after = dict(connection.execute(
            "SELECT * FROM user_library WHERE work_id = ?", (work_id,)
        ).fetchone())
        connection.close()
        self.assertEqual(after["status"], "Paused")
        for key in ("progress_episodes", "progress_chapters", "progress_volumes",
                    "rating", "notes", "added_date"):
            with self.subTest(field=key):
                self.assertEqual(after[key], before[key])

    def test_readding_removed_work_rebuilds_progress_from_cached_rows(self):
        work_id = 502
        database.save_anime(self.work(work_id, "ANIME", "TV"))
        database.add_to_library(work_id)
        database.save_episodes(work_id, [
            {"episodeNumber": 1, "title": "Episode 1"},
            {"episodeNumber": 2, "title": "Episode 2"},
            {"episodeNumber": 3, "title": "Episode 3"},
        ])
        database.set_episode_watched(work_id, 2, True)
        database.ensure_reading_placeholders(work_id, "chapter", 6, limit=6)
        database.ensure_reading_placeholders(work_id, "volume", 4, limit=4)
        database.set_reading_item_read(work_id, "chapter", 4, True)
        database.set_reading_item_read(work_id, "volume", 3, True)

        self.assertTrue(database.remove_from_library(work_id))
        database.add_to_library(work_id)

        connection = database.get_connection()
        row = dict(connection.execute(
            "SELECT * FROM user_library WHERE work_id = ?", (work_id,)
        ).fetchone())
        connection.close()
        self.assertEqual(row["progress_episodes"], 1)
        self.assertEqual(row["progress_chapters"], 1)
        self.assertEqual(row["progress_volumes"], 1)

    def test_partial_episode_refresh_never_deletes_missing_or_watched_rows(self):
        work_id = 503
        database.save_anime(self.work(work_id, "ANIME", "TV"))
        database.save_episodes(work_id, [
            {"episodeNumber": 1, "title": "Episode 1"},
            {"episodeNumber": 2, "title": "Episode 2"},
            {"episodeNumber": 3, "title": "Episode 3"},
        ])
        database.set_episode_watched(work_id, 2, True)

        # Simulates an upstream response that contains only part of a season.
        database.save_episodes(work_id, [
            {"episodeNumber": 1, "title": "Updated episode 1"},
        ])

        connection = database.get_connection()
        rows = connection.execute(
            "SELECT episode_number, title, watched FROM episodes "
            "WHERE work_id = ? ORDER BY episode_number", (work_id,)
        ).fetchall()
        connection.close()
        self.assertEqual([row["episode_number"] for row in rows], [1, 2, 3])
        self.assertEqual(rows[0]["title"], "Updated episode 1")
        self.assertEqual(rows[1]["watched"], 1)

    def test_malformed_episode_rows_do_not_abort_valid_episode_updates(self):
        work_id = 504
        database.save_anime(self.work(work_id, "ANIME", "TV"))
        database.save_episodes(work_id, [
            None,
            "not an episode object",
            {},
            {"episodeNumber": "not-a-number", "title": "bad row"},
            {"episodeNumber": 0, "title": "invalid zero"},
            {"episodeNumber": "1", "title": "Valid episode"},
        ])

        connection = database.get_connection()
        rows = connection.execute(
            "SELECT episode_number, title FROM episodes WHERE work_id = ?", (work_id,)
        ).fetchall()
        connection.close()
        self.assertEqual([(row["episode_number"], row["title"]) for row in rows],
                         [(1, "Valid episode")])

    def test_get_all_library_includes_volume_progress(self):
        work_id = 505
        database.save_anime(self.work(work_id, "MANGA", "NOVEL"))
        database.add_to_library(work_id)
        database.ensure_reading_placeholders(work_id, "volume", 3, limit=3)
        database.set_reading_item_read(work_id, "volume", 2, True)

        rows = database.get_all_library()
        row = next(item for item in rows if item["id"] == work_id)
        self.assertEqual(row["progress_volumes"], 1)

    def test_delete_work_removes_provider_metadata(self):
        work_id = 506
        item = self.work(work_id, "MANGA", "NOVEL")
        item["_mangabaka_id"] = 77
        item["_mangabaka"] = {
            "id": 77,
            "titles": [{"language": "en", "title": "Stored Provider Title"}],
        }
        database.save_anime(item)

        connection = database.get_connection()
        before = connection.execute(
            "SELECT COUNT(*) FROM work_provider_metadata WHERE work_id = ?",
            (work_id,),
        ).fetchone()[0]
        connection.close()
        self.assertEqual(before, 1)

        self.assertTrue(database.delete_work_data(work_id))
        connection = database.get_connection()
        after = connection.execute(
            "SELECT COUNT(*) FROM work_provider_metadata WHERE work_id = ?",
            (work_id,),
        ).fetchone()[0]
        connection.close()
        self.assertEqual(after, 0)

    def test_relation_refresh_removes_stale_edges_but_partial_payloads_preserve_them(self):
        source_id = 509

        def edge(target_id):
            return {
                "relationType": "SEQUEL",
                "node": {
                    "id": target_id,
                    "type": "ANIME",
                    "format": "TV",
                    "title": {
                        "english": f"Related Work {target_id}",
                        "romaji": f"Related Work {target_id}",
                        "native": None,
                    },
                    "coverImage": {"large": None},
                    "startDate": {"year": 2022, "month": 1, "day": 1},
                },
            }

        original = self.work(source_id, "ANIME", "TV")
        original["relations"] = {"edges": [edge(510), edge(511)]}
        database.save_anime(original)

        def source_targets():
            connection = database.get_connection()
            try:
                return [
                    row["target_id"]
                    for row in connection.execute(
                        "SELECT target_id FROM work_relations "
                        "WHERE source_id = ? ORDER BY target_id",
                        (source_id,),
                    ).fetchall()
                ]
            finally:
                connection.close()

        self.assertEqual(source_targets(), [510, 511])

        # A search/partial record omits relations; it must not erase cached edges.
        database.save_anime(self.work(source_id, "ANIME", "TV"))
        self.assertEqual(source_targets(), [510, 511])

        # A malformed edge list is not a complete snapshot; valid edges may be
        # refreshed, but stale rows must not be removed based on partial data.
        partial = self.work(source_id, "ANIME", "TV")
        partial["relations"] = {"edges": [edge(510), None]}
        database.save_anime(partial)
        self.assertEqual(source_targets(), [510, 511])

        # AniList relation IDs are positive; a negative/local-only catalog ID
        # also makes this list incomplete and must not clear cached edges.
        invalid_id = self.work(source_id, "ANIME", "TV")
        invalid_id["relations"] = {"edges": [edge(510), edge(-42)]}
        database.save_anime(invalid_id)
        self.assertEqual(source_targets(), [510, 511])

        oversized_id = self.work(source_id, "ANIME", "TV")
        oversized_id["relations"] = {"edges": [edge(510), edge(10**100)]}
        database.save_anime(oversized_id)
        self.assertEqual(source_targets(), [510, 511])

        # A fully valid refreshed graph removes the edge no longer returned.
        refreshed = self.work(source_id, "ANIME", "TV")
        refreshed["relations"] = {"edges": [edge(510)]}
        database.save_anime(refreshed)
        self.assertEqual(source_targets(), [510])

        # A valid empty list is authoritative and clears cached outgoing edges.
        empty = self.work(source_id, "ANIME", "TV")
        empty["relations"] = {"edges": []}
        database.save_anime(empty)
        self.assertEqual(source_targets(), [])


    def test_deleting_a_work_does_not_remove_shared_cover_still_in_use(self):
        first_id, second_id = 507, 508
        database.save_anime(self.work(first_id, "ANIME", "TV"))
        database.save_anime(self.work(second_id, "ANIME", "TV"))
        shared_cover = Path("data") / "images" / "works" / "shared-cover.jpg"
        shared_cover.parent.mkdir(parents=True, exist_ok=True)
        shared_cover.write_bytes(b"dummy image file used only for path ownership")
        database.save_cover_path(first_id, str(shared_cover))
        database.save_cover_path(second_id, str(shared_cover))

        self.assertTrue(database.delete_work_data(first_id))
        self.assertTrue(shared_cover.exists())

        # Once the last reference is removed, cleanup may delete the file.
        self.assertTrue(database.delete_work_data(second_id))
        self.assertFalse(shared_cover.exists())

    def test_900_random_database_operations_keep_relations_and_progress_consistent(self):
        rng = random.Random(_fuzz_seed(self.SEED))
        active = set(range(1, 41))
        for work_id in sorted(active):
            if work_id % 3 == 0:
                media_type, media_format = "MANGA", "NOVEL" if work_id % 2 else "MANGA"
            else:
                media_type, media_format = "ANIME", "TV" if work_id % 2 else "TV_SHORT"
            database.save_anime(self.work(work_id, media_type, media_format))
            if rng.random() < 0.65:
                database.add_to_library(work_id)

        for step in range(900):
            candidates = sorted(active)
            if not candidates:
                break
            work_id = rng.choice(candidates)
            operation = rng.randrange(8)

            if operation == 0:
                database.add_to_library(work_id, rng.choice(["Planning", "Watching", "Completed", "Paused"]))
            elif operation == 1:
                database.remove_from_library(work_id)
            elif operation == 2:
                item_type = rng.choice(["chapter", "volume"])
                item_number = rng.randint(1, 160)
                database.set_reading_item_read(work_id, item_type, item_number, bool(rng.getrandbits(1)))
            elif operation == 3:
                database.ensure_reading_placeholders(
                    work_id,
                    rng.choice(["chapter", "volume"]),
                    rng.randint(0, 260),
                    offset=rng.randint(0, 250),
                    limit=rng.randint(1, 150),
                )
            elif operation == 4 and len(active) > 1:
                other_id = rng.choice([value for value in candidates if value != work_id])
                database.add_manual_bundle_link(work_id, other_id)
            elif operation == 5 and len(active) > 1:
                other_id = rng.choice([value for value in candidates if value != work_id])
                database.add_bundle_exclusion(work_id, other_id)
            elif operation == 6 and len(active) > 1:
                other_id = rng.choice([value for value in candidates if value != work_id])
                database.remove_manual_bundle_link(work_id, other_id)
            elif operation == 7 and len(active) > 12:
                database.delete_work_data(work_id)
                active.remove(work_id)

            if step % 25 == 0:
                self.assert_database_invariants()

        self.assert_database_invariants()
        # Initialization is a supported repeat operation and must not damage a
        # healthy database after arbitrary library, bundle, and reading edits.
        database.initialize_database()
        self.assert_database_invariants()
        current_ids = {row["id"] for row in database.get_saved_anime()}
        self.assertEqual(current_ids, active)


class DatabaseConcurrencyChaosTests(unittest.TestCase):
    """Exercise real multi-connection write contention using a throwaway DB."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.temp_dir.name)
        database.initialize_database()

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp_dir.cleanup()

    def test_concurrent_imports_and_progress_updates_preserve_invariants(self):
        base_work_id = 600_000

        def worker(worker_id):
            rng = random.Random(_fuzz_seed(0x711B + worker_id))
            for step in range(10):
                # Every worker first creates a distinct row. Later iterations
                # deliberately collide on IDs to stress simultaneous upserts.
                work_id = (
                    base_work_id + worker_id + 1
                    if step == 0
                    else base_work_id + rng.randint(1, 8)
                )
                item_number = rng.randint(1, 36)
                work = DatabaseStateMachineChaosTests.work(
                    work_id, "MANGA", "MANGA"
                )
                work["title"]["english"] = (
                    f"Concurrent import {worker_id} {step}"
                )
                work["title"]["romaji"] = work["title"]["english"]

                database.save_anime(work)
                database.add_to_library(work_id)
                page_offset = ((item_number - 1) // 12) * 12
                database.ensure_reading_placeholders(
                    work_id, "chapter", 36, offset=page_offset, limit=12
                )
                database.set_reading_item_read(
                    work_id, "chapter", item_number, bool(rng.getrandbits(1))
                )

                read_count, total = database.get_reading_progress(
                    work_id, "chapter", total_hint=36
                )
                if not 0 <= read_count <= total:
                    raise AssertionError(
                        f"Invalid concurrent progress for {work_id}: "
                        f"{read_count}/{total}"
                    )

        # No connection object is shared between threads. Each production
        # database call opens its own SQLite connection, matching app usage.
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(worker, range(8)))

        connection = database.get_connection()
        try:
            self.assertEqual(
                connection.execute("PRAGMA integrity_check").fetchone()[0],
                "ok",
            )
            self.assertEqual(
                connection.execute("PRAGMA foreign_key_check").fetchall(),
                [],
            )
            work_ids = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM works WHERE id BETWEEN ? AND ? ORDER BY id",
                    (base_work_id + 1, base_work_id + 8),
                ).fetchall()
            ]
            self.assertEqual(work_ids, list(range(base_work_id + 1, base_work_id + 9)))

            mismatched_progress = connection.execute(
                """
                SELECT library.work_id, library.progress_chapters,
                       COALESCE(items.read_count, 0)
                FROM user_library AS library
                LEFT JOIN (
                    SELECT work_id, SUM(is_read) AS read_count
                    FROM reading_items
                    WHERE item_type = 'chapter'
                    GROUP BY work_id
                ) AS items ON items.work_id = library.work_id
                WHERE library.work_id BETWEEN ? AND ?
                  AND library.progress_chapters != COALESCE(items.read_count, 0)
                """,
                (base_work_id + 1, base_work_id + 8),
            ).fetchall()
            self.assertEqual(mismatched_progress, [])

            invalid_items = connection.execute(
                """
                SELECT COUNT(*) FROM reading_items
                WHERE work_id BETWEEN ? AND ?
                  AND (item_number < 1 OR is_read NOT IN (0, 1))
                """,
                (base_work_id + 1, base_work_id + 8),
            ).fetchone()[0]
            self.assertEqual(invalid_items, 0)
        finally:
            connection.close()


class TMDBPayloadChaosTests(unittest.TestCase):
    def test_tv_search_ignores_malformed_results_and_scores_bad_popularity_safely(self):
        payload = {
            "results": [
                None,
                "not a result object",
                {},
                {"id": "bad-id", "name": "Example Show"},
                {"id": "41", "name": "Example Show", "popularity": "not-a-number",
                 "origin_country": "JP", "first_air_date": "2020-01-01"},
                {"id": 42, "name": "Unrelated Show", "popularity": float("nan")},
            ]
        }
        with patch.object(nt_api, "_tmdb_get", return_value=payload):
            candidate = nt_api._find_tmdb_series(["Example Show"], date(2020, 1, 1))
        self.assertEqual(candidate["id"], 41)
        self.assertEqual(nt_api._candidate_score({"popularity": float("inf")}, [], None), 0)

    def test_movie_search_ignores_malformed_results(self):
        payload = {
            "results": [
                None,
                {"id": [], "title": "Special"},
                {"id": "87", "title": "Special", "release_date": "2020-01-01",
                 "popularity": "broken"},
            ]
        }
        with patch.object(nt_api, "_tmdb_get", return_value=payload):
            candidate = nt_api._find_tmdb_movie(["Special"], date(2020, 1, 1))
        self.assertEqual(candidate["id"], 87)

    def test_season_picker_skips_bad_rows_and_keeps_season_zero(self):
        details = {
            "seasons": [
                None,
                "not a season",
                {},
                {"season_number": "bad"},
                {"season_number": 0, "air_date": "2019-01-01"},
                {"season_number": "1", "air_date": "2020-01-01"},
                {"season_number": 2, "air_date": "2021-01-01"},
            ]
        }
        selected = nt_api._find_tmdb_season(details, date(2019, 1, 4))
        self.assertEqual(selected["season_number"], 0)

    def test_episode_fetch_skips_malformed_rows_and_avoids_extra_mapping_request(self):
        season = {
            "episodes": [
                None,
                "bad row",
                {},
                {"episode_number": "not-a-number", "air_date": "2020-01-01"},
                {"episode_number": 0, "air_date": "2020-01-01"},
                {"episode_number": "3", "air_date": "not-a-date"},
                {"episode_number": "2", "air_date": "2020-01-02", "name": "Second"},
                {"episode_number": 1, "air_date": "2020-01-01", "name": "First"},
                {"episode_number": 4, "air_date": "2020-01-02", "name": 123},
            ]
        }
        with patch.object(nt_api, "_tmdb_get", return_value=season) as request, \
             patch.object(nt_api, "_pick_best_episode_still", return_value=(None, 0)):
            result = nt_api.get_tmdb_episode_data(
                ["Example Show"], "2020-01-01", tmdb_id=12,
                tmdb_season_number=1,
            )
        self.assertEqual(request.call_count, 1)
        self.assertEqual([episode["episodeNumber"] for episode in result["episodes"]], [1, 2, 4])
        self.assertEqual(result["episodes"][2]["title"], "Episode 4")
        self.assertEqual(result["tmdb_count"], 3)

    def test_episode_still_ranking_survives_corrupted_image_metadata(self):
        with patch.object(nt_api, "_tmdb_get", return_value={
            "stills": [
                None,
                "not an image",
                {"file_path": "/bad.jpg", "vote_average": "bad", "vote_count": [], "width": "wide"},
                {"file_path": "/good.jpg", "vote_average": 8.7, "vote_count": 2, "width": 1920},
            ]
        }):
            url, count = nt_api._pick_best_episode_still(
                12, 1, {"episode_number": 4}
            )
        self.assertEqual(url, f"{nt_api.TMDB_IMAGE_BASE_URL}/good.jpg")
        self.assertEqual(count, 2)

    def test_anilist_rejects_malformed_graphql_payload_with_clear_error(self):
        response = Mock()
        response.status_code = 200
        response.reason = "OK"
        response.json.return_value = ["not", "an", "object"]
        with patch.object(nt_api.requests, "post", return_value=response), \
             patch.object(nt_api, "MAX_RETRIES", 1):
            with self.assertRaisesRegex(RuntimeError, "unexpected GraphQL response"):
                nt_api.anilist_request("query { Page { pageInfo { currentPage } } }")

    def test_anilist_error_payload_skips_malformed_error_objects(self):
        response = Mock()
        response.status_code = 400
        response.reason = "Bad Request"
        response.json.return_value = {"errors": [None, "bad error", {"message": 17}]}
        with patch.object(nt_api.requests, "post", return_value=response), \
             patch.object(nt_api, "MAX_RETRIES", 1):
            with self.assertRaisesRegex(RuntimeError, "AniList request failed"):
                nt_api.anilist_request("query { invalid }")


    def test_movie_image_ranking_survives_malformed_metadata(self):
        with patch.object(nt_api, "_tmdb_get", return_value={
            "backdrops": [
                None,
                "not an image",
                {"file_path": "/bad.jpg", "vote_average": "nan", "vote_count": "many"},
                {"file_path": "/good.jpg", "vote_average": 8.5, "vote_count": 10, "width": 1280},
            ]
        }):
            url, count = nt_api._pick_best_movie_image(50, {})
        self.assertEqual(url, f"{nt_api.TMDB_IMAGE_BASE_URL}/good.jpg")
        self.assertEqual(count, 2)

    def test_tmdb_rejects_non_object_json_responses(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = ["not", "an", "object"]
        with patch.object(nt_api, "_tmdb_token", return_value="test-token"), \
             patch.object(nt_api.requests, "get", return_value=response), \
             patch.object(nt_api.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "unexpected response"):
                nt_api._tmdb_get("/tv/12")

    def test_invalid_artwork_response_is_not_persistently_cached(self):
        url = "https://image.tmdb.org/t/p/w500/test.jpg"
        response = Mock()
        response.raise_for_status.return_value = None
        response.content = b"<html><body>temporary upstream error</body></html>"
        response.url = url
        response.headers = {}
        response.iter_content.return_value = iter([response.content])
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(nt_api, "TMDB_EPISODE_CACHE_DIRECTORY", Path(temp_dir)), \
             patch.object(nt_api.requests, "get", return_value=response) as request:
            first = nt_api.cache_tmdb_episode_image(url, 42, 3)
            second = nt_api.cache_tmdb_episode_image(url, 42, 3)
            files = list(Path(temp_dir).rglob("*"))
        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(request.call_count, 2)
        self.assertFalse(any(path.is_file() for path in files))

    def test_corrupt_existing_artwork_is_not_treated_as_a_cache_hit(self):
        url = "https://image.tmdb.org/t/p/w500/corrupt.webp"
        response = Mock()
        response.raise_for_status.return_value = None
        response.content = b"not a webp image"
        response.url = url
        response.headers = {}
        response.iter_content.return_value = iter([response.content])
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(nt_api, "TMDB_EPISODE_CACHE_DIRECTORY", Path(temp_dir)), \
             patch.object(nt_api.requests, "get", return_value=response) as request:
            digest = nt_api.hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
            work_dir = Path(temp_dir) / "42"
            work_dir.mkdir(parents=True)
            corrupt = work_dir / f"3_{digest}.webp"
            corrupt.write_bytes(b"old corrupt cache")
            result = nt_api.cache_tmdb_episode_image(url, 42, 3)
            exists_after = corrupt.exists()
        self.assertIsNone(result)
        self.assertEqual(request.call_count, 1)
        self.assertFalse(exists_after)

    def test_tmdb_image_cache_rejects_fractional_and_boolean_identifiers(self):
        url = "https://image.tmdb.org/t/p/w500/id-check.jpg"
        invalid_pairs = (
            (42.5, 3),
            (42, 3.5),
            (42, True),
            (False, 3),
            ("42.5", 3),
            (42, "3.5"),
        )
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(nt_api, "TMDB_EPISODE_CACHE_DIRECTORY", Path(temp_dir)), \
             patch.object(nt_api.requests, "get") as request:
            for work_id, episode_number in invalid_pairs:
                with self.subTest(work_id=work_id, episode_number=episode_number):
                    with self.assertRaisesRegex(ValueError, "integer"):
                        nt_api.cache_tmdb_episode_image(url, work_id, episode_number)
            request.assert_not_called()
            self.assertFalse(any(path.is_file() for path in Path(temp_dir).rglob("*")))

    def test_tmdb_image_redirect_to_untrusted_host_is_rejected(self):
        url = "https://image.tmdb.org/t/p/w500/redirect.jpg"
        response = Mock()
        response.status_code = 302
        response.headers = {"Location": "https://127.0.0.1/private.png"}
        response.url = url
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(nt_api, "TMDB_EPISODE_CACHE_DIRECTORY", Path(temp_dir)), \
             patch.object(nt_api.requests, "get", return_value=response) as request:
            with self.assertRaisesRegex(ValueError, "redirect destination is not trusted"):
                nt_api.cache_tmdb_episode_image(url, 42, 3)
        self.assertEqual(request.call_count, 1)
        response.close.assert_called_once()

    def test_tmdb_image_declared_oversize_is_rejected_before_reading_body(self):
        url = "https://image.tmdb.org/t/p/w500/large.jpg"
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Length": "17"}
        response.url = url
        response.raise_for_status.return_value = None
        response.iter_content.return_value = iter([b"x" * 17])
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(nt_api, "TMDB_EPISODE_CACHE_DIRECTORY", Path(temp_dir)), \
             patch.object(nt_api, "MAX_TMDB_EPISODE_IMAGE_BYTES", 16), \
             patch.object(nt_api.requests, "get", return_value=response):
            with self.assertRaisesRegex(ValueError, "download size limit"):
                nt_api.cache_tmdb_episode_image(url, 42, 3)
            files = [path for path in Path(temp_dir).rglob("*") if path.is_file()]
        response.iter_content.assert_not_called()
        self.assertEqual(files, [])

    def test_tmdb_image_stream_cannot_exceed_size_limit_without_content_length(self):
        url = "https://image.tmdb.org/t/p/w500/streamed.jpg"
        response = Mock()
        response.status_code = 200
        response.headers = {}
        response.url = url
        response.raise_for_status.return_value = None
        response.iter_content.return_value = iter([b"x" * 10, b"y" * 7])
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(nt_api, "TMDB_EPISODE_CACHE_DIRECTORY", Path(temp_dir)), \
             patch.object(nt_api, "MAX_TMDB_EPISODE_IMAGE_BYTES", 16), \
             patch.object(nt_api.requests, "get", return_value=response):
            with self.assertRaisesRegex(ValueError, "download size limit"):
                nt_api.cache_tmdb_episode_image(url, 42, 3)
            files = [path for path in Path(temp_dir).rglob("*") if path.is_file()]
        self.assertEqual(files, [])

    def test_tmdb_image_download_is_validated_and_atomically_cached(self):
        from PySide6.QtCore import QByteArray, QBuffer, QIODevice
        from PySide6.QtGui import QImage

        url = "https://image.tmdb.org/t/p/w500/valid.png"
        image_bytes = QByteArray()
        buffer = QBuffer(image_bytes)
        self.assertTrue(buffer.open(QIODevice.WriteOnly))
        image = QImage(12, 8, QImage.Format_ARGB32)
        image.fill(0xFF336699)
        self.assertTrue(image.save(buffer, "PNG"))
        buffer.close()
        data = bytes(image_bytes)

        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Length": str(len(data))}
        response.url = url
        response.raise_for_status.return_value = None
        response.iter_content.return_value = iter([data[:len(data)//2], data[len(data)//2:]])
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(nt_api, "TMDB_EPISODE_CACHE_DIRECTORY", Path(temp_dir)), \
             patch.object(nt_api.requests, "get", return_value=response) as request:
            saved_path = nt_api.cache_tmdb_episode_image(url, 42, 3)
            self.assertTrue(saved_path)
            path = Path(saved_path)
            self.assertEqual(path.read_bytes(), data)
            self.assertFalse(any(path.parent.glob("*.tmp")))
            cached_path = nt_api.cache_tmdb_episode_image(url, 42, 3)
        self.assertEqual(cached_path, saved_path)
        self.assertEqual(request.call_count, 1)

class AniListPaginationChaosTests(unittest.TestCase):
    @staticmethod
    def initial_media(character_page_info=None, schedule_page_info=None):
        character = {"id": 101, "name": {"full": "Character 101"}}
        return {
            "Media": {
                "id": 7001,
                "type": "ANIME",
                "characters": {
                    "edges": [{"node": character, "role": "MAIN", "voiceActors": []}],
                    "pageInfo": character_page_info or {
                        "currentPage": 1, "lastPage": 2, "hasNextPage": True,
                    },
                },
                "airingSchedule": {
                    "nodes": [{"episode": 1, "airingAt": 1000}],
                    "pageInfo": schedule_page_info or {
                        "currentPage": 1, "lastPage": 2, "hasNextPage": True,
                    },
                },
            }
        }

    def test_details_collects_all_pages_for_characters_and_schedule(self):
        character_two = {
            "node": {"id": 102, "name": {"full": "Character 102"}},
            "role": "SUPPORTING",
            "voiceActors": [],
        }
        character_page = {
            "Media": {
                "characters": {
                    "edges": [character_two],
                    "pageInfo": {"currentPage": 2, "lastPage": 2, "hasNextPage": False},
                }
            }
        }
        schedule_page = {
            "Media": {
                "airingSchedule": {
                    "nodes": [{"episode": 2, "airingAt": 2000}],
                    "pageInfo": {"currentPage": 2, "lastPage": 2, "hasNextPage": False},
                }
            }
        }
        with patch.object(
            nt_api, "anilist_request",
            side_effect=[self.initial_media(), character_page, schedule_page],
        ) as request:
            media = nt_api.get_media_details(7001)

        self.assertEqual(request.call_count, 3)
        self.assertEqual(
            [edge["node"]["id"] for edge in media["characters"]["edges"]],
            [101, 102],
        )
        self.assertEqual(
            [node["episode"] for node in media["airingSchedule"]["nodes"]],
            [1, 2],
        )
        self.assertFalse(media["characters"]["pageInfo"]["hasNextPage"])
        self.assertFalse(media["airingSchedule"]["pageInfo"]["hasNextPage"])

    def test_repeated_pages_are_deduplicated_and_cannot_loop_forever(self):
        repeated = self.initial_media(
            {"currentPage": 1, "lastPage": 999999, "hasNextPage": True},
            {"currentPage": 1, "lastPage": 999999, "hasNextPage": True},
        )
        repeated_character_page = {
            "Media": {
                "characters": {
                    "edges": repeated["Media"]["characters"]["edges"],
                    "pageInfo": {"currentPage": 2, "lastPage": 999999, "hasNextPage": True},
                }
            }
        }
        repeated_schedule_page = {
            "Media": {
                "airingSchedule": {
                    "nodes": repeated["Media"]["airingSchedule"]["nodes"],
                    "pageInfo": {"currentPage": 2, "lastPage": 999999, "hasNextPage": True},
                }
            }
        }
        with patch.object(
            nt_api, "anilist_request",
            side_effect=[repeated, repeated_character_page, repeated_schedule_page],
        ) as request:
            media = nt_api.get_media_details(7001)

        self.assertEqual(request.call_count, 3)
        self.assertEqual(len(media["characters"]["edges"]), 1)
        self.assertEqual(len(media["airingSchedule"]["nodes"]), 1)
        self.assertFalse(media["characters"]["pageInfo"]["hasNextPage"])
        self.assertFalse(media["airingSchedule"]["pageInfo"]["hasNextPage"])

    def test_malformed_connection_shapes_degrade_to_empty_connections(self):
        payload = {
            "Media": {
                "id": 7001,
                "type": "ANIME",
                "characters": "not a connection object",
                "airingSchedule": ["not", "a", "connection"],
            }
        }
        with patch.object(nt_api, "anilist_request", return_value=payload):
            media = nt_api.get_media_details(7001)
        self.assertEqual(media["characters"]["edges"], [])
        self.assertEqual(media["airingSchedule"]["nodes"], [])

    def test_missing_media_result_raises_descriptive_error(self):
        with patch.object(nt_api, "anilist_request", return_value={"Media": None}):
            with self.assertRaisesRegex(RuntimeError, "no media details"):
                nt_api.get_media_details(999999)


    def test_get_media_episodes_paginates_skips_bad_rows_and_deduplicates(self):
        first = {
            "Media": {
                "airingSchedule": {
                    "nodes": [
                        {"episode": 1, "airingAt": None},
                        None,
                        {"episode": "not-a-number", "airingAt": 1000},
                    ],
                    "pageInfo": {"currentPage": 1, "lastPage": 2, "hasNextPage": True},
                }
            }
        }
        second = {
            "Media": {
                "airingSchedule": {
                    "nodes": [
                        {"episode": 1, "airingAt": 9999},
                        {"episode": "2", "airingAt": "bad-timestamp"},
                        "bad node",
                    ],
                    "pageInfo": {"currentPage": 2, "lastPage": 2, "hasNextPage": False},
                }
            }
        }
        with patch.object(nt_api, "anilist_request", side_effect=[first, second]) as request:
            episodes = nt_api.get_media_episodes(7001)
        self.assertEqual(request.call_count, 2)
        self.assertEqual([item["episodeNumber"] for item in episodes], [1, 2])
        self.assertIsNone(episodes[0]["airdate"])
        self.assertIsNone(episodes[1]["airdate"])

    def test_get_media_episodes_stops_on_repeated_pages(self):
        page = {
            "Media": {
                "airingSchedule": {
                    "nodes": [{"episode": 1, "airingAt": 1000}],
                    "pageInfo": {"currentPage": 1, "lastPage": 999999, "hasNextPage": True},
                }
            }
        }
        repeat = {
            "Media": {
                "airingSchedule": {
                    "nodes": [{"episode": 1, "airingAt": 1000}],
                    "pageInfo": {"currentPage": 2, "lastPage": 999999, "hasNextPage": True},
                }
            }
        }
        with patch.object(nt_api, "anilist_request", side_effect=[page, repeat]) as request:
            episodes = nt_api.get_media_episodes(7001)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(len(episodes), 1)

    def test_get_media_episodes_handles_malformed_page_info_and_connections(self):
        payload = {"Media": {"airingSchedule": {
            "nodes": "bad nodes",
            "pageInfo": {"currentPage": "bad", "lastPage": {}, "hasNextPage": "true"},
        }}}
        with patch.object(nt_api, "anilist_request", return_value=payload) as request:
            episodes = nt_api.get_media_episodes(7001)
        self.assertEqual(episodes, [])
        request.assert_called_once()


class AniListRelationsChaosTests(unittest.TestCase):
    def test_malformed_detail_connections_are_normalized_before_ui_or_db_access(self):
        payload = {
            "Media": {
                "id": 616,
                "type": "ANIME",
                "title": {"english": "Malformed connections", "romaji": "Malformed connections"},
                "characters": "not-an-object",
                "airingSchedule": ["not", "an", "object"],
                "staff": "not-an-object",
                "studios": ["malformed"],
                "relations": "not-an-object",
            }
        }
        with patch.object(nt_api, "anilist_request", return_value=payload) as request:
            media = nt_api.get_media_details(616)

        request.assert_called_once()
        for name in ("characters", "staff", "studios", "relations"):
            self.assertIsInstance(media[name], dict)
        for name in ("characters", "staff", "studios"):
            self.assertIsInstance(media[name].get("edges"), list)
        self.assertEqual(media["characters"]["edges"], [])
        self.assertFalse(media["_characters_snapshot_valid"])
        self.assertEqual(media["staff"]["edges"], [])
        self.assertEqual(media["studios"]["edges"], [])
        # The missing relation list is deliberately not converted to []: an
        # empty list would be interpreted as an authoritative "no relations"
        # response and would erase previously cached edges.
        self.assertIsNone(media["relations"]["edges"])
        self.assertIsInstance(media["airingSchedule"], dict)
        self.assertEqual(media["airingSchedule"]["nodes"], [])


        payload = {
            "Media": {
                "id": 616,
                "type": "ANIME",
                "title": {"english": "Malformed connections", "romaji": "Malformed connections"},
                "characters": "not-an-object",
                "airingSchedule": ["not", "an", "object"],
                "staff": "not-an-object",
                "studios": ["malformed"],
                "relations": "not-an-object",
            }
        }
        with patch.object(nt_api, "anilist_request", return_value=payload) as request:
            media = nt_api.get_media_details(616)

        request.assert_called_once()
        for name in ("characters", "staff", "studios", "relations"):
            self.assertIsInstance(media[name], dict)
            self.assertIsInstance(media[name].get("edges"), list)
            self.assertEqual(media[name]["edges"], [])
        self.assertIsInstance(media["airingSchedule"], dict)
        self.assertEqual(media["airingSchedule"]["nodes"], [])



    def test_invalid_ids_do_not_crash_batch_relation_fetch(self):
        with patch.object(nt_api, "anilist_request") as request:
            result = nt_api.get_media_relations_batch([None, "bad-id", -7, 0])
        self.assertEqual(result, {})
        request.assert_not_called()

    def test_relation_batch_skips_invalid_returned_media_rows(self):
        payload = {
            "Page": {
                "media": [
                    {"id": "12", "title": {"romaji": "Valid"}},
                    None,
                    "not an object",
                    {"id": "not-an-id"},
                    {"id": -5},
                ]
            }
        }
        with patch.object(nt_api, "anilist_request", return_value=payload) as request:
            result = nt_api.get_media_relations_batch(["bad", None, 12, "12", -9])
        self.assertEqual(set(result), {12})
        self.assertEqual(result[12]["title"]["romaji"], "Valid")
        self.assertEqual(request.call_args.args[1]["ids"], [12])

    def test_optional_artwork_lookup_errors_do_not_discard_episode_data(self):
        with patch.object(nt_api, "_tmdb_get", side_effect=RuntimeError("invalid images JSON")):
            self.assertEqual(
                nt_api._pick_best_episode_still(12, 1, {"episode_number": 4}),
                (None, 0),
            )
            self.assertEqual(nt_api._pick_best_movie_image(12, {}), (None, 0))


class UpdateFeedChaosTests(unittest.TestCase):
    def test_malformed_release_entries_do_not_hide_a_valid_update(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [
            None,
            "not a release object",
            {"draft": "not-a-boolean", "tag_name": {"malformed": True}, "assets": []},
            {
                "draft": False,
                "tag_name": "v2.0.0",
                "assets": [
                    None,
                    {"name": 42, "browser_download_url": None},
                    {"name": "NekoTrack-Setup.exe", "browser_download_url": "https://example.invalid/setup.exe"},
                    {
                        "name": "NekoTrack-Setup.exe",
                        "browser_download_url": "https://github.com/konokuroineko/Nekotrack/releases/download/v2.0.0/NekoTrack-Setup.exe",
                    },
                ],
            },
        ]
        available = []
        failed = []
        checker = updater.UpdateChecker("1.0.0")
        checker.update_available.connect(available.append)
        checker.check_failed.connect(failed.append)

        with patch.object(updater.requests, "get", return_value=response):
            checker.run()

        self.assertEqual(len(available), 1)
        self.assertEqual(available[0].version, "2.0.0")
        self.assertEqual(available[0].asset_name, "NekoTrack-Setup.exe")
        self.assertEqual(failed, [])


if __name__ == "__main__":
    unittest.main()
