"""Deterministic adversarial tests for provider data, search and progress invariants."""
import math
import os
import random
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import api
import stress_test
import database
import mangabaka_api as mb
import series

def _fuzz_seed(base):
    """Keep tests reproducible while allowing each soak iteration to vary inputs."""
    try:
        offset = int(os.environ.get("NEKOTRACK_FUZZ_SEED", "0"))
    except (TypeError, ValueError, OverflowError):
        offset = 0
    return (int(base) + offset) % (2**32)



class FakeResponse:
    def __init__(self, payload, status_code=200, reason="OK", headers=None):
        self.payload = payload
        self.status_code = status_code
        self.reason = reason
        self.headers = headers or {}

    def json(self):
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


class MediaDetailIdentifierStressTests(unittest.TestCase):
    def test_invalid_media_identifiers_fail_before_provider_requests(self):
        invalid_ids = (
            None,
            True,
            False,
            0,
            -0.0,
            1.5,
            float("inf"),
            float("-inf"),
            float("nan"),
            1 << 100,
            1 << 31,
            -(1 << 63),
            -(1 << 63) - 1,
            1e300,
            "not-an-id",
            "9" * 5000,
        )
        with patch("api.anilist_request") as anilist, \
             patch("api.get_mangabaka_series") as mangabaka:
            for value in invalid_ids:
                with self.subTest(value=repr(value)[:80]):
                    with self.assertRaises(ValueError):
                        api.get_media_details(value)
            anilist.assert_not_called()
            mangabaka.assert_not_called()

    def test_episode_and_relation_helpers_reject_bad_ids_before_network_calls(self):
        invalid_ids = (
            True,
            1.5,
            float("inf"),
            float("nan"),
            0,
            1 << 31,
            -(1 << 63),
            "bad-id",
        )
        with patch("api.anilist_request") as anilist, \
             patch("api.get_mangabaka_series") as mangabaka, \
             patch("api.get_media_details") as details:
            for media_id in invalid_ids:
                with self.subTest(media_id=repr(media_id)):
                    self.assertEqual(api.get_media_episodes(media_id), [])
                    with self.assertRaises(ValueError):
                        api.get_media_relations(media_id)
            anilist.assert_not_called()
            mangabaka.assert_not_called()
            details.assert_not_called()

    def test_numeric_string_media_id_is_normalized_before_graphql_request(self):
        payload = {
            "Media": {
                "id": 123,
                "type": "ANIME",
                "characters": {"edges": [], "pageInfo": {
                    "currentPage": 1, "lastPage": 1, "hasNextPage": False,
                }},
                "airingSchedule": {"nodes": [], "pageInfo": {
                    "currentPage": 1, "lastPage": 1, "hasNextPage": False,
                }},
            }
        }
        with patch("api.anilist_request", return_value=payload) as request:
            media = api.get_media_details(" 123 ")

        self.assertEqual(media["id"], 123)
        self.assertEqual(request.call_args.args[1]["id"], 123)


class ApiResponseShapeStressTests(unittest.TestCase):
    def test_url_parser_only_accepts_real_positive_anilist_media_urls(self):
        valid = {
            "https://anilist.co/anime/1": 1,
            "https://www.anilist.co/manga/456/a-title/": 456,
            "http://anilist.co/anime/42?source=test": 42,
            "https://ANILIST.CO/anime/900001/title": 900001,
        }
        for value, expected in valid.items():
            with self.subTest(value=value):
                self.assertEqual(api.parse_anilist_url(value), expected)

        invalid = [
            None, 123, "", "anilist.co/anime/1",
            "javascript://anilist.co/anime/1",
            "ftp://anilist.co/anime/1",
            "https://anilist.co.evil.example/anime/1",
            "https://evil.anilist.co/anime/1",
            "https://user@anilist.co/anime/1",
            "https://anilist.co:9999/anime/1",
            "https://anilist.co:invalid/anime/1",
            "https://anilist.co/anime/0",
            "https://anilist.co/anime/-1",
            "https://anilist.co/anime/not-a-number",
            "https://anilist.co/character/1",
            "https://anilist.co/",
        ]
        for value in invalid:
            with self.subTest(value=repr(value)):
                self.assertIsNone(api.parse_anilist_url(value))

    def test_malformed_success_payloads_raise_clean_errors_not_internal_type_errors(self):
        malformed = [
            None, [], "not-json-object", 13, {},
            {"errors": []},
            {"errors": [None]},
            {"errors": [{"message": "provider rejected query"}]},
            {"errors": "not-an-array"},
            {"data": None},
        ]
        for payload in malformed:
            with self.subTest(payload=repr(payload)):
                response = FakeResponse(payload)
                with patch("api.requests.post", return_value=response), patch("api.time.sleep"):
                    with self.assertRaises(Exception):
                        api.anilist_request("query { Page { pageInfo { currentPage } } }")

    def test_malformed_rate_limit_payload_still_retries_and_returns_a_useful_error(self):
        response = FakeResponse(None, status_code=429, reason="Too Many Requests")
        with patch("api.requests.post", return_value=response) as post, patch("api.time.sleep"):
            with self.assertRaisesRegex(Exception, "429"):
                api.anilist_request("query { Page { pageInfo { currentPage } } }")
        self.assertEqual(post.call_count, api.MAX_RETRIES)

    def test_untrusted_retry_after_values_never_produce_unbounded_sleep(self):
        success = FakeResponse({"data": {"Page": {"media": []}}})
        for retry_after in ("1e309", "1e300", "nan", "inf"):
            with self.subTest(retry_after=retry_after):
                limited = FakeResponse(
                    None,
                    status_code=429,
                    reason="Too Many Requests",
                    headers={"Retry-After": retry_after},
                )
                with patch.object(api, "MAX_RETRIES", 2), \
                     patch("api.requests.post", side_effect=[limited, success]), \
                     patch("api.time.sleep") as sleep:
                    result = api.anilist_request(
                        "query { Page { media { id } } }"
                    )

                self.assertEqual(result, {"Page": {"media": []}})
                sleep.assert_called_once()
                delay = sleep.call_args.args[0]
                self.assertTrue(math.isfinite(delay), retry_after)
                self.assertGreaterEqual(delay, 1.0)
                self.assertLessEqual(delay, 60.0)

    def test_valid_graphql_envelope_is_unchanged(self):
        response = FakeResponse({"data": {"Page": {"media": []}}})
        with patch("api.requests.post", return_value=response):
            self.assertEqual(api.anilist_request("query { Page { media { id } } }"), {"Page": {"media": []}})


class StressRunnerDiscoveryStressTests(unittest.TestCase):
    def test_successful_zero_test_discovery_is_not_reported_as_pass(self):
        completed = subprocess.CompletedProcess(
            args=["python", "-m", "unittest", "discover"],
            returncode=0,
            stdout="",
            stderr="Ran 0 tests in 0.000s\n\nOK\n",
        )
        with patch("stress_test.subprocess.run", return_value=completed):
            result = stress_test.run_full_regression_suite()

        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["tests_run"], 0)

    def test_real_nonzero_test_summary_can_be_reported_as_pass(self):
        completed = subprocess.CompletedProcess(
            args=["python", "-m", "unittest", "discover"],
            returncode=0,
            stdout="",
            stderr="Ran 3 tests in 0.012s\n\nOK\n",
        )
        with patch("stress_test.subprocess.run", return_value=completed):
            result = stress_test.run_full_regression_suite()

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["tests_run"], 3)


class OfflineNetworkGuardStressTests(unittest.TestCase):
    def test_offline_guard_blocks_http_dns_and_raw_socket_paths(self):
        import socket
        import urllib.request

        attempted = []
        with stress_test.offline_network_guard(attempted):
            with self.assertRaisesRegex(AssertionError, "Unexpected network request"):
                api.requests.get("https://example.invalid/test")
            with self.assertRaisesRegex(AssertionError, "Unexpected network request"):
                urllib.request.urlopen("https://example.invalid/test")
            with self.assertRaisesRegex(AssertionError, "Unexpected network request"):
                socket.getaddrinfo("example.invalid", 443)
            with self.assertRaisesRegex(AssertionError, "Unexpected network request"):
                socket.gethostbyname("example.invalid")
            with self.assertRaisesRegex(AssertionError, "Unexpected network request"):
                socket.gethostbyname_ex("example.invalid")
            with self.assertRaisesRegex(AssertionError, "Unexpected network request"):
                socket.gethostbyaddr("203.0.113.5")
            with self.assertRaisesRegex(AssertionError, "Unexpected network request"):
                socket.getnameinfo(("203.0.113.5", 443), 0)
            with self.assertRaisesRegex(AssertionError, "Unexpected network request"):
                socket.create_connection(("example.invalid", 443))
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                with self.assertRaisesRegex(AssertionError, "Unexpected network request"):
                    client.connect(("example.invalid", 443))
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                with self.assertRaisesRegex(AssertionError, "Unexpected network request"):
                    client.connect_ex(("example.invalid", 443))
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                with self.assertRaisesRegex(AssertionError, "Unexpected network request"):
                    client.send(b"offline")
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                with self.assertRaisesRegex(AssertionError, "Unexpected network request"):
                    client.sendall(b"offline")
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                with self.assertRaisesRegex(AssertionError, "Unexpected network request"):
                    client.sendto(b"offline", ("example.invalid", 53))

        methods = [attempt["method"] for attempt in attempted]
        self.assertEqual(len(methods), 13)
        self.assertIn("GET", methods)
        self.assertIn("urllib.request.urlopen", methods)
        self.assertIn("socket.getaddrinfo", methods)
        self.assertIn("socket.gethostbyname", methods)
        self.assertIn("socket.gethostbyname_ex", methods)
        self.assertIn("socket.gethostbyaddr", methods)
        self.assertIn("socket.getnameinfo", methods)
        self.assertIn("socket.create_connection", methods)
        self.assertIn("socket.connect", methods)
        self.assertIn("socket.connect_ex", methods)
        self.assertIn("socket.send", methods)
        self.assertIn("socket.sendall", methods)
        self.assertIn("socket.sendto", methods)


class TmdbImageCacheResourceStressTests(unittest.TestCase):
    def test_oversized_cached_image_is_not_loaded_into_memory(self):
        url = "https://image.tmdb.org/t/p/w500/oversized.jpg"

        class StreamingResponse:
            def __init__(self, response_url):
                self.status_code = 200
                self.headers = {"Content-Length": "3"}
                self.url = response_url

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size):
                return iter([b"bad"])

            def close(self):
                return None

        with tempfile.TemporaryDirectory() as directory:
            cache_root = Path(directory)
            work_dir = cache_root / "42"
            work_dir.mkdir(parents=True)
            digest = api.hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
            cached = work_dir / f"3_{digest}.jpg"
            cached.write_bytes(b"this-cache-is-larger-than-16")
            original_read_bytes = Path.read_bytes

            def forbid_cached_read(candidate):
                if candidate == cached:
                    raise AssertionError("oversized cached image must not be read")
                return original_read_bytes(candidate)

            with patch.object(api, "TMDB_EPISODE_CACHE_DIRECTORY", cache_root), \
                 patch.object(api, "MAX_TMDB_EPISODE_IMAGE_BYTES", 16), \
                 patch.object(api.requests, "get", return_value=StreamingResponse(url)), \
                 patch.object(Path, "read_bytes", forbid_cached_read):
                result = api.cache_tmdb_episode_image(url, 42, 3)

            self.assertIsNone(result)
            self.assertFalse(cached.exists())


class DatabaseEpisodeMetadataStressTests(unittest.TestCase):
    def test_partial_episode_refresh_preserves_metadata_and_skips_invalid_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()
                database.save_anime({
                    "id": 79,
                    "type": "ANIME",
                    "format": "TV",
                    "title": {"english": "Episode metadata test", "romaji": "Episode metadata test"},
                })
                database.save_episodes(79, [{
                    "episodeNumber": 1,
                    "title": "Episode One",
                    "description": "Previously downloaded description",
                    "airdate": "2020-01-02",
                    "thumbnail": "https://images.example.invalid/episode-one.jpg",
                }])

                # Malformed entries must be ignored; missing detail fields must
                # not erase values already cached for the same episode.
                database.save_episodes(79, [
                    {"episodeNumber": 10**100, "title": "Impossible episode"},
                    {"episodeNumber": 1.5, "title": "Fractional episode"},
                    {"episodeNumber": True, "title": "Boolean episode"},
                    {"episodeNumber": "9" * 5000, "title": "Huge numeric text"},
                    {
                        "episodeNumber": 1,
                        "title": None,
                        "description": {"unexpected": "object"},
                        "airdate": None,
                        "thumbnail": ["malformed"],
                    },
                    {
                        "episodeNumber": 2,
                        "title": "Episode Two",
                        "description": None,
                        "airdate": None,
                        "thumbnail": None,
                    },
                ])

                connection = database.get_connection()
                try:
                    rows = connection.execute(
                        """
                        SELECT episode_number, title, description, air_date, thumbnail_url
                        FROM episodes WHERE work_id = ? ORDER BY episode_number
                        """,
                        (79,),
                    ).fetchall()
                finally:
                    connection.close()

                self.assertEqual([row["episode_number"] for row in rows], [1, 2])
                self.assertEqual(rows[0]["title"], "Episode One")
                self.assertEqual(rows[0]["description"], "Previously downloaded description")
                self.assertEqual(rows[0]["air_date"], "2020-01-02")
                self.assertEqual(
                    rows[0]["thumbnail_url"],
                    "https://images.example.invalid/episode-one.jpg",
                )
                self.assertEqual(rows[1]["title"], "Episode Two")
            finally:
                os.chdir(old_cwd)

    def test_episode_progress_rejects_invalid_ids_without_leaking_transactions(self):
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()
                work_id = 80
                database.save_anime({
                    "id": work_id,
                    "type": "ANIME",
                    "format": "TV",
                    "title": {"english": "Progress ID test", "romaji": "Progress ID test"},
                })
                database.save_episodes(work_id, [{
                    "episodeNumber": 1,
                    "title": "Episode One",
                }])
                database.add_to_library(work_id)

                invalid_calls = (
                    (True, 1),
                    (work_id, True),
                    (work_id, 1.5),
                    (work_id, 10**100),
                    (10**100, 1),
                )
                for invalid_work_id, episode_number in invalid_calls:
                    with self.subTest(work_id=invalid_work_id, episode_number=episode_number):
                        self.assertEqual(
                            database.set_episode_watched(
                                invalid_work_id, episode_number, True
                            ),
                            (0, 0),
                        )

                # A valid write immediately after the invalid calls confirms
                # they did not strand an open SQLite transaction/connection.
                self.assertEqual(database.set_episode_watched(work_id, 1, True), (1, 1))
                saved = database.get_work(work_id)
                self.assertEqual(saved["progress_episodes"], 1)
                self.assertEqual(saved["status"], "Completed")
            finally:
                os.chdir(old_cwd)


class DatabaseCastPayloadStressTests(unittest.TestCase):
    def test_malformed_character_edges_do_not_crash_or_mark_partial_cast_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()
                database.save_anime({
                    "id": 77,
                    "type": "ANIME",
                    "format": "TV",
                    "title": {"english": "Cast payload test", "romaji": "Cast payload test"},
                })

                database.save_characters(77, [
                    None,
                    {
                        "node": {
                            "id": 10**100,
                            "name": {"full": "Out-of-range character"},
                            "image": {"large": None},
                        },
                        "role": "MAIN",
                        "voiceActors": [],
                    },
                    {
                        "node": {
                            "id": 11,
                            "name": {"full": "Partial character"},
                            "image": {"large": None},
                        },
                        "role": "MAIN",
                        "voiceActors": "malformed-not-a-list",
                    },
                ])

                self.assertFalse(database.characters_are_loaded(77))
                connection = database.get_connection()
                try:
                    ids = [
                        row["character_id"]
                        for row in connection.execute(
                            "SELECT character_id FROM work_characters WHERE work_id = ?",
                            (77,),
                        ).fetchall()
                    ]
                finally:
                    connection.close()
                self.assertEqual(ids, [11])

                database.save_characters(77, [{
                    "node": {
                        "id": 12,
                        "name": {"full": "Complete character"},
                        "image": {"large": None},
                    },
                    "role": "MAIN",
                    "voiceActors": [],
                }])
                self.assertTrue(database.characters_are_loaded(77))
            finally:
                os.chdir(old_cwd)

    def test_malformed_staff_edges_are_skipped_without_aborting_valid_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()
                database.save_anime({
                    "id": 78,
                    "type": "ANIME",
                    "format": "TV",
                    "title": {"english": "Staff payload test", "romaji": "Staff payload test"},
                })

                database.save_staff(78, [
                    None,
                    {"node": {
                        "id": 10**100,
                        "name": {"full": "Out-of-range staff"},
                    }, "role": "Writer"},
                    {"node": {
                        "id": 90,
                        "name": {"full": "Valid staff"},
                        "image": {"large": None},
                    }, "role": "Writer"},
                ])

                staff = database.get_staff(78)
                self.assertEqual(len(staff), 1)
                self.assertEqual(staff[0]["person_id"], 90)
                self.assertEqual(staff[0]["role"], "Writer")
            finally:
                os.chdir(old_cwd)

    def test_staff_refresh_reconciles_stale_roles_but_partial_snapshots_preserve_them(self):
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()
                work_id = 79
                database.save_anime({
                    "id": work_id,
                    "type": "ANIME",
                    "format": "TV",
                    "title": {"english": "Staff reconciliation", "romaji": "Staff reconciliation"},
                })

                def staff_edge(person_id, name, role):
                    return {
                        "node": {
                            "id": person_id,
                            "name": {"full": name},
                            "image": {"large": None},
                        },
                        "role": role,
                    }

                def saved_staff():
                    connection = database.get_connection()
                    try:
                        return {
                            (row["person_id"], row["role"])
                            for row in connection.execute(
                                "SELECT person_id, role FROM work_staff WHERE work_id = ?",
                                (work_id,),
                            ).fetchall()
                        }
                    finally:
                        connection.close()

                database.save_staff(work_id, [
                    staff_edge(90, "Staff One", "Writer"),
                    staff_edge(91, "Staff Two", "Artist"),
                ])
                original = {(90, "Writer"), (91, "Artist")}
                self.assertEqual(saved_staff(), original)

                # A malformed list must not let valid-looking partial edges
                # erase the old rows. New info can be added, but stale rows wait
                # for a complete snapshot before removal.
                database.save_staff(work_id, [
                    staff_edge(90, "Staff One", "Editor"),
                    None,
                ])
                self.assertTrue(original.issubset(saved_staff()))
                self.assertIn((90, "Editor"), saved_staff())

                # This person is still used as a voice actor after disappearing
                # from the work's staff list, so global person cleanup must keep it.
                database.save_characters(work_id, [{
                    "node": {
                        "id": 300,
                        "name": {"full": "Character"},
                        "image": {"large": None},
                    },
                    "role": "MAIN",
                    "voiceActors": [{
                        "id": 91,
                        "name": {"full": "Staff Two"},
                        "image": {"large": None},
                        "language": "Japanese",
                    }],
                }])

                database.save_staff(work_id, [staff_edge(90, "Staff One", "Editor")])
                self.assertEqual(saved_staff(), {(90, "Editor")})

                connection = database.get_connection()
                try:
                    still_shared = connection.execute(
                        "SELECT 1 FROM people WHERE id = ?",
                        (91,),
                    ).fetchone()
                finally:
                    connection.close()
                self.assertIsNotNone(still_shared)

                # A complete empty snapshot clears links and deletes truly
                # orphaned people, but not records still referenced by cast.
                database.save_staff(work_id, [])
                self.assertEqual(saved_staff(), set())
                connection = database.get_connection()
                try:
                    orphan = connection.execute(
                        "SELECT 1 FROM people WHERE id = ?",
                        (90,),
                    ).fetchone()
                    shared = connection.execute(
                        "SELECT 1 FROM people WHERE id = ?",
                        (91,),
                    ).fetchone()
                finally:
                    connection.close()
                self.assertIsNone(orphan)
                self.assertIsNotNone(shared)
            finally:
                os.chdir(old_cwd)


class DatabaseCastReconciliationStressTests(unittest.TestCase):
    def test_complete_cast_refresh_removes_stale_characters_and_voice_actors(self):
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()
                work_id = 81
                database.save_anime({
                    "id": work_id,
                    "type": "ANIME",
                    "format": "TV",
                    "title": {"english": "Cast reconciliation", "romaji": "Cast reconciliation"},
                })

                def character(character_id, name, actors):
                    return {
                        "node": {
                            "id": character_id,
                            "name": {"full": name},
                            "image": {"large": None},
                        },
                        "role": "MAIN",
                        "voiceActors": actors,
                    }

                def actor(person_id, name):
                    return {
                        "id": person_id,
                        "name": {"full": name},
                        "image": {"large": None},
                        "language": "Japanese",
                    }

                first_snapshot = [
                    character(1, "Character One", [actor(100, "Old Actor")]),
                    character(2, "Character Two", [actor(200, "Second Actor")]),
                ]
                database.save_characters(work_id, first_snapshot)
                self.assertTrue(database.characters_are_loaded(work_id))
                connection = database.get_connection()
                try:
                    connection.execute(
                        "UPDATE characters SET image_path = ?, image_url = NULL WHERE id = ?",
                        ("data/images/characters/1.png", 1),
                    )
                    connection.execute(
                        "UPDATE people SET image_path = ? WHERE id = ?",
                        ("data/images/people/100.png", 100),
                    )
                    connection.commit()
                finally:
                    connection.close()

                # A malformed snapshot must not remove any existing cast links.
                partial_snapshot = [
                    character(1, "Character One", [actor(101, "New Actor")]),
                    None,
                ]
                database.save_characters(work_id, partial_snapshot)
                self.assertFalse(database.characters_are_loaded(work_id))

                connection = database.get_connection()
                try:
                    after_partial_characters = [
                        row["character_id"]
                        for row in connection.execute(
                            "SELECT character_id FROM work_characters WHERE work_id = ? ORDER BY character_id",
                            (work_id,),
                        ).fetchall()
                    ]
                    after_partial_actors = [
                        row["person_id"]
                        for row in connection.execute(
                            "SELECT person_id FROM character_voice_actors WHERE character_id = ? ORDER BY person_id",
                            (1,),
                        ).fetchall()
                    ]
                finally:
                    connection.close()
                self.assertEqual(after_partial_characters, [1, 2])
                self.assertEqual(after_partial_actors, [100, 101])

                connection = database.get_connection()
                try:
                    connection.execute(
                        "UPDATE people SET image_path = ? WHERE id = ?",
                        ("data/images/people/101.png", 101),
                    )
                    connection.commit()
                finally:
                    connection.close()

                # A complete snapshot is authoritative: Character Two and the
                # voice actor no longer reported for Character One are removed.
                database.save_characters(
                    work_id,
                    [character(1, "Character One", [actor(101, "New Actor")])],
                )
                self.assertTrue(database.characters_are_loaded(work_id))
                connection = database.get_connection()
                try:
                    final_characters = [
                        row["character_id"]
                        for row in connection.execute(
                            "SELECT character_id FROM work_characters WHERE work_id = ? ORDER BY character_id",
                            (work_id,),
                        ).fetchall()
                    ]
                    final_actors = [
                        row["person_id"]
                        for row in connection.execute(
                            "SELECT person_id FROM character_voice_actors WHERE character_id = ? ORDER BY person_id",
                            (1,),
                        ).fetchall()
                    ]
                finally:
                    connection.close()
                self.assertEqual(final_characters, [1])
                self.assertEqual(final_actors, [101])
                connection = database.get_connection()
                try:
                    orphan_character = connection.execute(
                        "SELECT 1 FROM characters WHERE id = ?",
                        (2,),
                    ).fetchone()
                    orphan_voice_actors = connection.execute(
                        "SELECT COUNT(*) FROM character_voice_actors WHERE character_id = ?",
                        (2,),
                    ).fetchone()[0]
                    orphan_old_actor = connection.execute(
                        "SELECT 1 FROM people WHERE id = ?",
                        (100,),
                    ).fetchone()
                    orphan_second_actor = connection.execute(
                        "SELECT 1 FROM people WHERE id = ?",
                        (200,),
                    ).fetchone()
                    current_actor = connection.execute(
                        "SELECT 1 FROM people WHERE id = ?",
                        (101,),
                    ).fetchone()
                    character_image_path = connection.execute(
                        "SELECT image_path FROM characters WHERE id = ?",
                        (1,),
                    ).fetchone()["image_path"]
                    actor_image_path = connection.execute(
                        "SELECT image_path FROM people WHERE id = ?",
                        (101,),
                    ).fetchone()["image_path"]
                finally:
                    connection.close()
                self.assertIsNone(orphan_character)
                self.assertEqual(orphan_voice_actors, 0)
                self.assertIsNone(orphan_old_actor)
                self.assertIsNone(orphan_second_actor)
                self.assertIsNotNone(current_actor)
                self.assertEqual(character_image_path, "data/images/characters/1.png")
                self.assertEqual(actor_image_path, "data/images/people/101.png")

                # If the provider image URL actually changes, invalidate that
                # local cached path instead of displaying a stale image forever.
                changed_character = character(
                    1,
                    "Character One",
                    [actor(101, "New Actor")],
                )
                changed_character["node"]["image"]["large"] = (
                    "https://images.example.invalid/character-new.png"
                )
                changed_character["voiceActors"][0]["image"]["large"] = (
                    "https://images.example.invalid/actor-new.png"
                )
                database.save_characters(work_id, [changed_character])
                connection = database.get_connection()
                try:
                    changed_paths = connection.execute(
                        """
                        SELECT characters.image_path AS character_path,
                               people.image_path AS person_path
                        FROM characters, people
                        WHERE characters.id = 1 AND people.id = 101
                        """
                    ).fetchone()
                finally:
                    connection.close()
                self.assertIsNone(changed_paths["character_path"])
                self.assertIsNone(changed_paths["person_path"])
            finally:
                os.chdir(old_cwd)


class DatabaseDeletionSafetyStressTests(unittest.TestCase):
    def test_deleting_work_keeps_external_custom_cover_and_removes_owned_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()
                database.save_anime({
                    "id": 1,
                    "title": {"english": "Deletion safety", "romaji": "Deletion safety"},
                    "type": "ANIME",
                    "format": "TV",
                })
                database.add_to_library(1)

                cached_cover = Path("data") / "images" / "works" / "1.jpg"
                cached_cover.parent.mkdir(parents=True)
                cached_cover.write_bytes(b"generated cache")

                # This emulates the UI's fallback to the original selected
                # image when it cannot copy that image into the bundle cache.
                external_cover = Path(directory) / "user-original.png"
                external_cover.write_bytes(b"user-owned source")
                database.save_cover_path(1, str(cached_cover))
                self.assertTrue(database.save_bundle_override(
                    [1], 1, custom_cover_path=str(external_cover)
                ))

                self.assertTrue(database.delete_work_data(1))
                self.assertFalse(cached_cover.exists())
                self.assertEqual(external_cover.read_bytes(), b"user-owned source")
            finally:
                os.chdir(old_cwd)


class DatabasePartialMetadataStressTests(unittest.TestCase):
    def test_invalid_work_ids_are_rejected_before_any_database_write(self):
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()

                self.assertEqual(database._validated_work_id(-(1 << 63)), -(1 << 63))
                self.assertEqual(database._validated_work_id((1 << 63) - 1), (1 << 63) - 1)

                invalid_ids = (
                    None, True, False, 0, 1.5, float("inf"), float("nan"),
                    1 << 100, "x", "9" * 5000, str(1 << 63), str(-(1 << 63) - 1),
                )
                for value in invalid_ids:
                    with self.subTest(value=repr(value)[:60]):
                        with self.assertRaises(ValueError):
                            database.save_anime({"id": value})

                connection = database.get_connection()
                try:
                    self.assertEqual(
                        connection.execute("SELECT COUNT(*) FROM works").fetchone()[0],
                        0,
                    )
                finally:
                    connection.close()
            finally:
                os.chdir(old_cwd)

    def test_malformed_nested_metadata_is_sanitized_before_sqlite_upsert(self):
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()
                full = {
                    "id": 614,
                    "type": "MANGA",
                    "format": "MANGA",
                    "title": {"english": "Valid cached title", "romaji": "Valid cached title"},
                    "description": "Known description",
                    "episodes": 12,
                    "averageScore": 80,
                    "startDate": {"year": 2020, "month": 4, "day": 5},
                    "endDate": {"year": 2021, "month": 6, "day": 7},
                    "coverImage": {"large": "https://example.test/cover.jpg"},
                    "chapters": 42,
                    "volumes": 3,
                    "source": "MANGA",
                    "duration": 25,
                    "idMal": 1234,
                }
                database.save_anime(full)

                malformed = {
                    "id": 614,
                    "type": None,
                    "format": [],
                    "title": {"english": "  Updated safe title  ", "romaji": {"odd": "value"}},
                    "description": {"unexpected": "object"},
                    "episodes": {"count": 24},
                    "averageScore": float("inf"),
                    "startDate": "not-an-object",
                    "endDate": [],
                    "coverImage": ["bad"],
                    "chapters": 10**100,
                    "volumes": 1.5,
                    "source": {"name": "bad"},
                    "duration": True,
                    "idMal": [],
                    "synonyms": "not-a-list",
                    "studios": {"edges": [None]},
                    "relations": {"edges": [None]},
                    "_mangabaka": {
                        "id": 88,
                        "invalid_set": {1, 2},
                        "non_finite": float("inf"),
                    },
                }
                database.save_anime(malformed)

                connection = database.get_connection()
                try:
                    row = dict(connection.execute(
                        """
                        SELECT title, type, description, episodes, score, start_year,
                               start_month, start_day, cover_url, format, chapters,
                               volumes, source, end_year, duration, mal_id
                        FROM works WHERE id = ?
                        """,
                        (614,),
                    ).fetchone())
                    synonym_count = connection.execute(
                        "SELECT COUNT(*) FROM alternate_titles WHERE work_id = ?",
                        (614,),
                    ).fetchone()[0]
                    studio_count = connection.execute(
                        "SELECT COUNT(*) FROM work_studios WHERE work_id = ?",
                        (614,),
                    ).fetchone()[0]
                    relation_count = connection.execute(
                        "SELECT COUNT(*) FROM work_relations WHERE source_id = ?",
                        (614,),
                    ).fetchone()[0]
                    provider_count = connection.execute(
                        "SELECT COUNT(*) FROM work_provider_metadata WHERE work_id = ?",
                        (614,),
                    ).fetchone()[0]
                finally:
                    connection.close()

                self.assertEqual(row["title"], "Updated safe title")
                self.assertEqual(row["type"], "MANGA")
                self.assertEqual(row["description"], "Known description")
                self.assertEqual(row["episodes"], 12)
                self.assertEqual(row["score"], 80)
                self.assertEqual(
                    (row["start_year"], row["start_month"], row["start_day"]),
                    (2020, 4, 5),
                )
                self.assertEqual(row["cover_url"], "https://example.test/cover.jpg")
                self.assertEqual(row["format"], "MANGA")
                self.assertEqual(row["chapters"], 42)
                self.assertEqual(row["volumes"], 3)
                self.assertEqual(row["source"], "MANGA")
                self.assertEqual(row["end_year"], 2021)
                self.assertEqual(row["duration"], 25)
                self.assertEqual(row["mal_id"], 1234)
                self.assertEqual(synonym_count, 0)
                self.assertEqual(studio_count, 0)
                self.assertEqual(relation_count, 0)
                self.assertEqual(provider_count, 0)
            finally:
                os.chdir(old_cwd)

    def test_partial_refresh_preserves_fields_from_previously_loaded_details(self):
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()
                work_id = 612
                full = {
                    "id": work_id,
                    "type": "MANGA",
                    "format": "MANGA",
                    "title": {
                        "english": "Detailed title",
                        "romaji": "Detailed title",
                        "native": None,
                    },
                    "description": "Full description from an earlier import",
                    "episodes": 24,
                    "averageScore": 88,
                    "startDate": {"year": 2018, "month": 3, "day": 4},
                    "endDate": {"year": 2020, "month": 5, "day": 6},
                    "coverImage": {"large": "https://example.test/cached-cover.jpg"},
                    "chapters": 120,
                    "volumes": 12,
                    "source": "MANGA",
                    "duration": 40,
                }
                database.save_anime(full)

                # Search results intentionally omit detail-only fields. NekoTrack
                # saves them immediately before background enrichment, so this
                # refresh must not erase data if the later request fails.
                partial = {
                    "id": work_id,
                    "type": "MANGA",
                    "title": {
                        "english": "Updated title",
                        "romaji": "Updated title",
                        "native": None,
                    },
                    "format": None,
                    "episodes": None,
                    "averageScore": None,
                    "startDate": {"year": None, "month": None, "day": None},
                    "endDate": {},
                    "coverImage": {"large": None},
                }
                database.save_anime(partial)

                connection = database.get_connection()
                try:
                    row = dict(connection.execute(
                        """
                        SELECT title, description, episodes, score, start_year,
                               start_month, start_day, cover_url, format, chapters,
                               volumes, source, end_year, duration
                        FROM works WHERE id = ?
                        """,
                        (work_id,),
                    ).fetchone())
                finally:
                    connection.close()

                self.assertEqual(row["title"], "Updated title")
                self.assertEqual(row["description"], full["description"])
                self.assertEqual(row["episodes"], 24)
                self.assertEqual(row["score"], 88)
                self.assertEqual(
                    (row["start_year"], row["start_month"], row["start_day"]),
                    (2018, 3, 4),
                )
                self.assertEqual(row["cover_url"], full["coverImage"]["large"])
                self.assertEqual(row["format"], "MANGA")
                self.assertEqual(row["chapters"], 120)
                self.assertEqual(row["volumes"], 12)
                self.assertEqual(row["source"], "MANGA")
                self.assertEqual(row["end_year"], 2020)
                self.assertEqual(row["duration"], 40)

                # If the provider now supplies only a different year, do not
                # combine it with the old record's month/day into a date that
                # no provider ever returned.
                newer_partial_date = dict(partial)
                newer_partial_date["startDate"] = {
                    "year": 2024,
                    "month": None,
                    "day": None,
                }
                database.save_anime(newer_partial_date)
                connection = database.get_connection()
                try:
                    updated_date = connection.execute(
                        "SELECT start_year, start_month, start_day FROM works WHERE id = ?",
                        (work_id,),
                    ).fetchone()
                finally:
                    connection.close()
                self.assertEqual(
                    tuple(updated_date),
                    (2024, None, None),
                )
            finally:
                os.chdir(old_cwd)


    def test_studio_refresh_removes_stale_links_but_partial_payload_preserves_them(self):
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()
                work_id = 613

                def work(studio_edges_marker=None):
                    item = {
                        "id": work_id,
                        "type": "ANIME",
                        "format": "TV",
                        "title": {
                            "english": "Studio refresh test",
                            "romaji": "Studio refresh test",
                            "native": None,
                        },
                    }
                    if studio_edges_marker is not None:
                        item["studios"] = {"edges": studio_edges_marker}
                    return item

                def studio_edge(studio_id):
                    return {
                        "isMain": studio_id == 10,
                        "node": {"id": studio_id, "name": f"Studio {studio_id}"},
                    }

                def saved_studios():
                    connection = database.get_connection()
                    try:
                        return [
                            row["studio_id"]
                            for row in connection.execute(
                                "SELECT studio_id FROM work_studios "
                                "WHERE work_id = ? ORDER BY studio_id",
                                (work_id,),
                            ).fetchall()
                        ]
                    finally:
                        connection.close()

                database.save_anime(work([studio_edge(10), studio_edge(11)]))
                self.assertEqual(saved_studios(), [10, 11])

                # Lightweight records omit studios and must leave the cache alone.
                database.save_anime(work())
                self.assertEqual(saved_studios(), [10, 11])

                # A malformed list is not authoritative enough to delete old links.
                database.save_anime(work([studio_edge(10), None]))
                self.assertEqual(saved_studios(), [10, 11])

                # SQLite integers are signed 64-bit. An out-of-range provider ID
                # must mark the snapshot malformed instead of crashing the save.
                database.save_anime(work([studio_edge(10), studio_edge(10**100)]))
                self.assertEqual(saved_studios(), [10, 11])

                # A complete refresh replaces stale associations, and empty is
                # meaningful when the provider confirms that no studios remain.
                database.save_anime(work([studio_edge(10)]))
                self.assertEqual(saved_studios(), [10])
                database.save_anime(work([]))
                self.assertEqual(saved_studios(), [])
            finally:
                os.chdir(old_cwd)


class MangaBakaShapeStressTests(unittest.TestCase):
    def test_oversized_publisher_and_year_filters_fail_closed_without_requests(self):
        hostile_filters = (
            {"publisher_id": "9" * 5000},
            {"publisher_id": 10**100},
            {"year": "9" * 5000},
            {"year": 10**100},
        )
        with patch("mangabaka_api.search_series") as search_series, \
             patch("mangabaka_api.get_series_mix") as series_mix:
            for filters in hostile_filters:
                with self.subTest(filter_name=next(iter(filters))):
                    result = mb.search_media("", filters=filters)
                    self.assertEqual(result["media"], [])
                    self.assertFalse(result["pageInfo"]["hasNextPage"])
            search_series.assert_not_called()
            series_mix.assert_not_called()

        self.assertEqual(mb._bounded_positive_filter_int("123"), 123)
        self.assertIsNone(mb._bounded_positive_filter_int("9" * 5000))
        self.assertIsNone(mb._bounded_positive_filter_int(10**100))

    def test_extreme_provider_pagination_is_clamped_and_terminates(self):
        payload = {
            "data": {
                "items": [{
                    "id": 42,
                    "type": "manga",
                    "titles": [{"language": "en", "title": "Pagination boundary"}],
                    "content_rating": "safe",
                    "published": {"start": "2020-01-01"},
                    "rating": 80,
                }]
            },
            "pagination": {
                "page": 10**100,
                "limit": 20,
                "count": 10**100,
                "next": "https://api.mangabaka.org/v2/series?page=overflow",
            },
        }
        with patch("mangabaka_api.get_series_mix", return_value=payload) as request:
            result = mb.search_media("", page=10**100)

        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs["page"], mb.MAX_PROVIDER_PAGES)
        self.assertEqual(result["pageInfo"]["currentPage"], mb.MAX_PROVIDER_PAGES)
        self.assertEqual(result["pageInfo"]["lastPage"], mb.MAX_PROVIDER_PAGES)
        self.assertFalse(result["pageInfo"]["hasNextPage"])
        self.assertEqual(len(result["media"]), 1)

    def test_provider_envelopes_never_leak_non_dictionary_pagination(self):
        payloads = [
            None, [], 5, "text", {},
            {"data": None},
            {"data": []},
            {"data": {"items": "not-a-list"}},
            {"pagination": None},
            {"pagination": "broken"},
            {"pagination": [1, 2]},
            {"pagination": 7},
            {"pagination": {"page": "broken", "limit": None, "count": "many"}},
        ]
        for payload in payloads:
            with self.subTest(payload=repr(payload)):
                self.assertIsInstance(mb._records(payload), list)
                self.assertIsInstance(mb._pagination(payload), dict)

    def test_nested_request_parameters_always_produce_hashable_deterministic_cache_keys(self):
        first = mb._cache_key("series/search", {
            "filters": {"genres": ["Action", "Fantasy"], "nested": {"b": 2, "a": 1}},
            "options": [{"id": 2}, {"id": 1}],
        })
        second = mb._cache_key("series/search", {
            "options": [{"id": 1}, {"id": 2}],
            "filters": {"nested": {"a": 1, "b": 2}, "genres": ["Fantasy", "Action"]},
        })
        self.assertEqual(hash(first), hash(second))
        self.assertEqual(first, second)

    def test_invalid_dates_are_ignored_and_never_abort_normalization(self):
        rng = random.Random(_fuzz_seed(20261010))
        samples = [
            None, "", "unknown", "2020-13-40", "99999-01-01",
            {"year": "nope", "month": 1, "day": 1},
            {"year": "2024", "month": "bad", "day": 1},
            {"year": 2024, "month": 2, "day": 31},
            {"year": 2024, "month": 2, "day": 29},
            {"year": 2020},
            {"year": True, "month": [], "day": {}},
            {"year": 0, "month": 1, "day": 1},
        ]
        samples.extend(
            rng.choice([
                "not-a-date", "1900-02-29", "2000-02-29", "2033-00-01",
                {"year": str(rng.choice(["2021", "bad", "-1", "9999"])),
                 "month": rng.choice([None, "bad", 0, 1, 12, 13]),
                 "day": rng.choice([None, "bad", 0, 1, 28, 31, 32])},
            ])
            for _ in range(300)
        )
        for index, value in enumerate(samples, start=1):
            with self.subTest(index=index, value=repr(value)):
                result = mb.normalize_series({
                    "id": index,
                    "title": f"Fuzz title {index}",
                    "published": {"start": value},
                    "rating": rng.choice([None, "bad", "NaN", "Infinity", -1, 0, 88, 100, 101]),
                })
                date = result["startDate"]
                self.assertEqual(set(date), {"year", "month", "day"})
                if date["year"] is None:
                    self.assertEqual(date, {"year": None, "month": None, "day": None})
                else:
                    self.assertTrue(1 <= date["year"] <= 9999)
                    self.assertTrue(1 <= date["month"] <= 12)
                    self.assertTrue(1 <= date["day"] <= 31)
                score = result["averageScore"]
                self.assertTrue(score is None or (math.isfinite(score) and 0 <= score <= 100))
        self.assertEqual(mb._date_parts({"published": {"start": "99999-01-01"}}),
                         {"year": None, "month": None, "day": None})

    def test_normalizer_rejects_nonpositive_or_boolean_provider_ids(self):
        for value in (None, True, False, 0, -1, "0", "-23", "not-an-id"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError):
                    mb.normalize_series({"id": value, "title": "Invalid ID"})

    def test_nonfinite_scores_never_pass_local_minimum_score_filters(self):
        for rating in (float("nan"), float("inf"), float("-inf"), None, "unknown", [], {}):
            with self.subTest(rating=repr(rating)):
                self.assertFalse(mb._matches_local_filters(
                    {"type": "manga", "rating": rating, "content_rating": "safe"},
                    "MANGA",
                    {"min_score": 70},
                ))
        self.assertTrue(mb._matches_local_filters(
            {"type": "manga", "rating": 70, "content_rating": "safe"},
            "MANGA", {"min_score": 70},
        ))

    def test_randomized_provider_shapes_do_not_crash_local_filtering_or_normalization(self):
        rng = random.Random(_fuzz_seed(431072))
        scalar_values = [None, "", "2022-06-05", "bad", 0, 1, 99, True, False, float("nan"), float("inf")]
        terms = [None, "", "Action", "action, Fantasy", ["Action", "Fantasy"], {"name": "Isekai"}, [None, 3, {"slug": "Fantasy"}]]
        for index in range(500):
            start_date = rng.choice(scalar_values + [
                {"year": rng.choice(scalar_values), "month": rng.choice(scalar_values), "day": rng.choice(scalar_values)},
                rng.choice(scalar_values),
            ])
            record = {
                "id": index + 1,
                "type": rng.choice(["manga", "novel", None, "unknown"]),
                "title": rng.choice(scalar_values + ["Title"]),
                "titles": rng.choice([None, [], "bad", [{"language": "en", "title": "Title"}],
                                      [{"language": 9, "title": {"odd": "shape"}}]]),
                "published": rng.choice([None, "bad", {}, {"start": start_date}]),
                "rating": rng.choice(scalar_values),
                "tags": rng.choice(terms),
                "genres": rng.choice(terms),
                "status": rng.choice(scalar_values + ["completed", "releasing"]),
                "publisher": rng.choice(scalar_values + [{"id": "42"}, {"publisherId": 42}]),
                "is_licensed": rng.choice(scalar_values),
                "content_rating": rng.choice(["safe", "suggestive", "adult", None]),
                "secondary_titles": rng.choice([None, {}, [], ["Alias"], {"en": ["Alias"]}]),
            }
            normalized = mb.normalize_series(record)
            self.assertEqual(normalized["_mangabaka_id"], index + 1)
            filters = {
                "status": rng.choice(["FINISHED", "RELEASING", "HIATUS", None]),
                "min_score": rng.choice([None, 0, 70, 100, "bad", "nan"]),
                "year": rng.choice([None, 1900, 2022, "bad"]),
                "genre": rng.choice(terms),
                "tag": rng.choice(terms),
                "publisher_id": rng.choice([None, "42", "bad"]),
                "is_licensed": rng.choice([None, True, False]),
            }
            mb._matches_local_filters(record, rng.choice(["MANGA", "NOVEL", None]), filters)


class SeriesBundlingStressTests(unittest.TestCase):
    @staticmethod
    def media(media_id, title, media_type, media_format, start_date=None, edges=None):
        return {
            "id": media_id,
            "type": media_type,
            "format": media_format,
            "title": title,
            "startDate": start_date,
            "relations": {"edges": edges or []},
        }

    def test_title_and_relation_parsers_tolerate_malformed_optional_fields(self):
        for title in (None, 0, 1.5, [], {}, {"english": 42}, {"native": None}):
            with self.subTest(title=repr(title)):
                self.assertIsInstance(series._series_key(title), str)
                item = self.media(1, title, "ANIME", "TV", start_date="not-a-date", edges=[None, "bad", {}])
                with patch.object(series, "get_manual_bundle_links", return_value=[]), \
                     patch.object(series, "get_bundle_exclusions", return_value=[]), \
                     patch.object(series, "get", return_value=False):
                    groups = series.group_media_results([item], enrich=False)
                self.assertEqual(len(groups), 1)
                self.assertEqual(len(groups[0]["_series_members"]), 1)

    def test_undated_named_arcs_are_not_assumed_to_share_an_airing_season(self):
        first = self.media(
            1, {"english": "Example Series Dawn Arc"}, "ANIME", "TV",
            start_date=None, edges=[{"relationType": "SEQUEL", "node": {
                "id": 2, "type": "ANIME", "format": "TV",
                "title": {"english": "Example Series Twilight Arc"},
            }}],
        )
        second = self.media(
            2, {"english": "Example Series Twilight Arc"}, "ANIME", "TV",
            start_date=None, edges=[{"relationType": "PREQUEL", "node": {
                "id": 1, "type": "ANIME", "format": "TV",
                "title": {"english": "Example Series Dawn Arc"},
            }}],
        )
        self.assertEqual(series.logical_season_count([first, second]), 2)

    def test_seeded_random_graphs_preserve_every_original_result_exactly_once(self):
        rng = random.Random(_fuzz_seed(120241))
        formats = {
            "ANIME": ["TV", "TV_SHORT", "MOVIE", "OVA", "ONA", "SPECIAL", "MUSIC", None],
            "MANGA": ["MANGA", "NOVEL", "ONE_SHOT", None],
        }
        title_pool = [
            "Example Series", "Example Series Season 2", "Example Series Part 2",
            "Example Series Dawn Arc", "Example Series Twilight Arc",
            "Unrelated Title", "Another Franchise", "Single Entry",
        ]
        for case in range(80):
            count = rng.randint(1, 28)
            items = []
            for index in range(count):
                media_type = rng.choice(["ANIME", "MANGA"])
                media_format = rng.choice(formats[media_type])
                title = rng.choice(title_pool + [f"Unique title {case}-{index}"])
                date = rng.choice([
                    {"year": rng.randint(1980, 2026), "month": rng.randint(1, 12), "day": 1},
                    None, "malformed",
                ])
                items.append(self.media(case * 100 + index + 1, {"english": title, "romaji": title},
                                        media_type, media_format, date))

            for item in items:
                edges = []
                for _ in range(rng.randint(0, 3)):
                    target = rng.choice(items)
                    edges.append({
                        "relationType": rng.choice(list(series.SERIES_RELATIONS) + ["UNKNOWN", None]),
                        "node": {
                            "id": target["id"], "type": target["type"], "format": target["format"],
                            "title": target["title"], "startDate": target["startDate"],
                        },
                    })
                item["relations"] = {"edges": edges}

            options = {key: bool(rng.getrandbits(1)) for key in [
                "bundle_include_movies", "bundle_include_ovas", "bundle_include_onas",
                "bundle_include_specials", "bundle_include_manga", "bundle_include_novels",
                "bundle_include_one_shots",
            ]}
            series._relation_cache.clear()
            with patch.object(series, "get_manual_bundle_links", return_value=[]), \
                 patch.object(series, "get_bundle_exclusions", return_value=[]), \
                 patch.object(series, "get", side_effect=lambda key: options.get(key, False)):
                groups = series.group_media_results(items, enrich=False)

            flattened = []
            for group in groups:
                members = group.get("_series_members") or [group]
                flattened.extend(int(member["id"]) for member in members)
            expected = [int(item["id"]) for item in items]
            with self.subTest(case=case, count=count):
                self.assertCountEqual(flattened, expected)
                self.assertEqual(len(flattened), len(set(flattened)))


class DatabaseIdentifierHelperStressTests(unittest.TestCase):
    def test_episode_artwork_tmdb_and_library_helpers_reject_bad_ids_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = os.getcwd()
            try:
                os.chdir(directory)
                database.initialize_database()
                work_id = 80
                database.save_anime({
                    "id": work_id,
                    "type": "ANIME",
                    "format": "TV",
                    "title": {"english": "Database helper test", "romaji": "Database helper test"},
                })
                database.save_episodes(work_id, [{
                    "episodeNumber": 1,
                    "title": "Episode One",
                    "thumbnail": "https://images.example.invalid/remote.jpg",
                }])

                for invalid_id in (True, 1.5, 10**100, "9" * 5000):
                    with self.subTest(invalid_id=repr(invalid_id)[:50]):
                        self.assertEqual(database.get_tmdb_mapping(invalid_id), (None, None))
                        self.assertFalse(database.save_tmdb_mapping(invalid_id, 120, 1))
                        self.assertFalse(
                            database.save_episode_thumbnail_path(invalid_id, 1, "local.jpg")
                        )
                        self.assertFalse(database.save_cover_path(invalid_id, "cover.jpg"))
                        self.assertIsNone(database.get_work(invalid_id))
                        self.assertEqual(database.get_episodes(invalid_id), [])
                        self.assertEqual(database.get_alternate_titles(invalid_id), [])
                        self.assertEqual(database.get_relations(invalid_id), [])
                        self.assertEqual(database.get_characters(invalid_id), [])
                        self.assertEqual(database.get_staff(invalid_id), [])

                self.assertEqual(database.get_tmdb_mapping(-901), (None, None))
                self.assertFalse(database.save_tmdb_mapping(-901, 120, 1))
                self.assertFalse(database.save_episode_thumbnail_path(-901, 1, "local.jpg"))

                self.assertTrue(database.save_tmdb_mapping(work_id, 120, 0))
                self.assertEqual(database.get_tmdb_mapping(work_id), (120, 0))
                for tmdb_id, season in (
                    (1.5, 1),
                    (True, 1),
                    (10**100, 1),
                    (121, 1.5),
                    (121, True),
                    (121, 10**100),
                ):
                    with self.subTest(tmdb_id=tmdb_id, season=season):
                        self.assertFalse(database.save_tmdb_mapping(work_id, tmdb_id, season))
                        self.assertEqual(database.get_tmdb_mapping(work_id), (120, 0))

                for invalid_number in (True, 1.5, 10**100, "not-an-episode"):
                    with self.subTest(episode_number=repr(invalid_number)):
                        self.assertFalse(
                            database.save_episode_thumbnail_path(
                                work_id, invalid_number, "data/images/episodes/80/1.jpg"
                            )
                        )

                episodes = database.get_episodes(work_id)
                self.assertEqual(episodes[0]["thumbnail_url"], "https://images.example.invalid/remote.jpg")
                self.assertTrue(
                    database.save_episode_thumbnail_path(
                        work_id, 1, "data/images/episodes/80/1.jpg"
                    )
                )
                self.assertEqual(
                    database.get_episodes(work_id)[0]["thumbnail_url"],
                    "data/images/episodes/80/1.jpg",
                )

                self.assertFalse(database.save_character_image_path(True, "person.jpg"))
                self.assertFalse(database.save_person_image_path(10**100, "person.jpg"))
                self.assertFalse(database.save_cover_path(True, "data/images/works/80.jpg"))
                self.assertTrue(database.save_cover_path(work_id, "data/images/works/80.jpg"))
                self.assertEqual(database.get_work(work_id)["cover_path"], "data/images/works/80.jpg")

                with self.assertRaises(ValueError):
                    database.add_to_library(True, "Planning")
                self.assertFalse(database.remove_from_library(True))
                with self.assertRaises(ValueError):
                    database.delete_work_data(1.5)

                # After every malformed input, a normal transaction still works.
                database.add_to_library(work_id, "Planning")
                self.assertTrue(database.remove_from_library(work_id))

                second_id = 81
                database.save_anime({
                    "id": second_id,
                    "type": "ANIME",
                    "format": "TV",
                    "title": {"english": "Bundle helper test", "romaji": "Bundle helper test"},
                })
                self.assertTrue(database.add_manual_bundle_link(work_id, second_id))
                self.assertEqual(len(database.get_manual_bundle_links([work_id])), 1)
                self.assertEqual(database.get_manual_bundle_links([True]), [])
                self.assertEqual(database.get_bundle_exclusions([1.5]), [])
                self.assertIsNone(database.get_bundle_override([True]))
                self.assertFalse(database.remove_manual_bundle_link(True, second_id))
                self.assertFalse(database.add_bundle_exclusion(True, second_id))
                self.assertFalse(database.remove_bundle_member(work_id, second_id, [True]))

                self.assertTrue(database.save_bundle_override(
                    [work_id, second_id],
                    work_id,
                    custom_title="Custom bundle title",
                    cover_work_id=second_id,
                    custom_cover_path=Path("cover.jpg"),
                ))
                saved_override = database.get_bundle_override([work_id, second_id])
                self.assertIsNotNone(saved_override)
                self.assertEqual(saved_override["custom_title"], "Custom bundle title")
                self.assertFalse(database.save_bundle_override(
                    [work_id, second_id],
                    work_id,
                    custom_title="x" * 501,
                ))
                self.assertFalse(database.clear_bundle_override([10**100]))
                self.assertEqual(
                    database.get_bundle_override([work_id, second_id])["custom_title"],
                    "Custom bundle title",
                )
            finally:
                os.chdir(old_cwd)


class DatabaseProgressStressTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.temp_dir.name)
        database.initialize_database()
        for work_id in range(1, 5):
            work = {
                "id": work_id,
                "type": "MANGA",
                "format": "NOVEL",
                "title": {"english": f"Stress work {work_id}", "romaji": f"Stress work {work_id}", "native": None},
                "chapters": 90,
                "volumes": 30,
                "episodes": None,
                "coverImage": {"large": None},
            }
            database.save_anime(work)
            database.add_to_library(work_id)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp_dir.cleanup()

    def test_random_progress_toggles_keep_sqlite_and_aggregate_counts_consistent(self):
        rng = random.Random(_fuzz_seed(2026101001))
        expected = {
            work_id: {"chapter": set(), "volume": set()}
            for work_id in range(1, 5)
        }
        for _ in range(450):
            work_id = rng.randint(1, 4)
            item_type = rng.choice(["chapter", "volume"])
            item_number = rng.randint(1, 120)
            is_read = bool(rng.getrandbits(1))
            database.set_reading_item_read(work_id, item_type, item_number, is_read)
            if is_read:
                expected[work_id][item_type].add(item_number)
            else:
                expected[work_id][item_type].discard(item_number)

            read_count, total = database.get_reading_progress(work_id, item_type, total_hint=120)
            self.assertEqual(read_count, len(expected[work_id][item_type]))
            self.assertEqual(total, 120)

        for work_id, by_type in expected.items():
            saved = database.get_work(work_id)
            self.assertEqual(saved["progress_chapters"], len(by_type["chapter"]))
            self.assertEqual(saved["progress_volumes"], len(by_type["volume"]))

    def test_huge_placeholder_requests_are_bounded_and_idempotent(self):
        first = database.ensure_reading_placeholders(1, "chapter", 10**9, offset=10, limit=10**8)
        second = database.ensure_reading_placeholders(1, "chapter", 10**9, offset=10, limit=10**8)
        self.assertEqual(len(first), 100)
        self.assertEqual(len(second), 100)
        self.assertEqual([int(row["item_number"]) for row in first], list(range(11, 111)))
        self.assertEqual([int(row["item_number"]) for row in second], list(range(11, 111)))
        self.assertEqual(len(database.get_reading_items(1, "chapter", limit=100)), 100)

    def test_nonfinite_numeric_paging_arguments_fail_safely(self):
        self.assertEqual(
            database.ensure_reading_placeholders(1, "chapter", math.inf),
            [],
        )
        self.assertEqual(
            database.ensure_reading_placeholders(1, "chapter", 50, offset=math.inf),
            [],
        )
        self.assertEqual(
            database.get_reading_items(1, "chapter", limit=math.inf, offset=math.inf),
            [],
        )
        self.assertEqual(
            database.get_reading_progress(1, "chapter", total_hint=math.inf),
            (0, 0),
        )
        with self.assertRaises(ValueError):
            database.set_reading_item_read(1, "chapter", math.inf, True)
        with self.assertRaises(ValueError):
            database.set_reading_item_read(1, "chapter", 1.5, True)

    def test_nonpositive_reading_item_numbers_are_rejected(self):
        for number in (0, -1, -500):
            with self.subTest(number=number):
                with self.assertRaises(ValueError):
                    database.set_reading_item_read(1, "chapter", number, True)


if __name__ == "__main__":
    unittest.main()
