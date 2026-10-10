"""Deterministic adversarial tests for provider data, search and progress invariants."""
import math
import os
import random
import subprocess
import tempfile
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


class MangaBakaShapeStressTests(unittest.TestCase):
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
