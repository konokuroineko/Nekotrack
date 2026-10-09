"""Adversarial regression tests for malformed provider data and relationship graphs.

All API calls are mocked. SQLite tests run in a temporary working directory and
never open the user's real NekoTrack database.
"""
import os
import random
import tempfile
import unittest
from unittest.mock import patch

import api
import catalog_search
import database
import mangabaka_api as mb
import series


def manga_baka_series(series_id=1, series_type="novel", **overrides):
    record = {
        "id": series_id,
        "type": series_type,
        "status": "completed",
        "content_rating": "safe",
        "rating": 82,
        "titles": [{"language": "en", "title": "Adversarial Example", "is_primary": True}],
        "published": {"start": "2020-01-01"},
        "total_chapters": 12,
        "final_volume": 3,
    }
    record.update(overrides)
    return record


def media(media_id, title, media_type="ANIME", media_format="TV", relations=None):
    return {
        "id": media_id,
        "type": media_type,
        "format": media_format,
        "title": {"english": title, "romaji": title, "native": None},
        "startDate": {"year": 2020, "month": 1, "day": 1},
        "coverImage": {"large": None},
        "relations": {"edges": relations or []},
        "_relations_loaded": True,
    }


class AniListURLAdversarialTests(unittest.TestCase):
    def test_rejects_suspicious_schemes_hosts_and_nonpositive_ids(self):
        invalid = [
            "ftp://anilist.co/anime/1/Test",
            "file://anilist.co/anime/1/Test",
            "javascript://anilist.co/anime/1/Test",
            "//anilist.co/anime/1/Test",
            "https://anilist.co.evil.example/anime/1/Test",
            "https://anilist.co@evil.example/anime/1/Test",
            "https://evil.example/anilist.co/anime/1/Test",
            "https://anilist.co/anime/0/Test",
            "https://anilist.co/anime/-1/Test",
            "https://anilist.co/anime/not-a-number/Test",
            "https://anilist.co/character/1/Test",
            "https://anilist.co/anime/",
            "https://anilist.co:bad/anime/1/Test",
            "",
            None,
            123,
        ]
        for value in invalid:
            with self.subTest(value=value):
                self.assertIsNone(api.parse_anilist_url(value))

    def test_valid_url_variants_and_deterministic_random_noise_never_raise(self):
        self.assertEqual(api.parse_anilist_url("https://anilist.co/anime/1/Test"), 1)
        self.assertEqual(api.parse_anilist_url("http://www.anilist.co/manga/987/title?x=1"), 987)
        rng = random.Random(911731)
        alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:/.-_@?#[]"
        for _ in range(1200):
            value = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 90)))
            parsed = api.parse_anilist_url(value)
            self.assertTrue(parsed is None or (isinstance(parsed, int) and parsed > 0))


class MangaBakaAdversarialTests(unittest.TestCase):
    def test_malformed_dates_and_negative_counts_do_not_crash_normalization(self):
        invalid_date = manga_baka_series(
            published={"start": {"year": "not-a-year", "month": 99, "day": 99}},
            published_at="2020-02-29",
            total_chapters="-5 chapters",
            final_volume=-2,
        )
        normalized = mb.normalize_series(invalid_date)
        self.assertEqual(normalized["startDate"], {"year": 2020, "month": 2, "day": 29})
        self.assertIsNone(normalized["chapters"])
        self.assertIsNone(normalized["volumes"])

        self.assertIsNone(mb._date_parts({"published": {"start": "2020-13-40"}})["year"])
        self.assertIsNone(mb._count_or_none("-12"))
        self.assertIsNone(mb._count_or_none("-12 chapters"))
        self.assertIsNone(mb._count_or_none(0))
        self.assertEqual(mb._count_or_none("Volume 24"), 24)
        self.assertEqual(mb._count_or_none(9), 9)

    def test_random_malformed_provider_fields_never_crash_normalizer(self):
        rng = random.Random(1429)
        strange = [
            None, "", "not-a-date", "2024-99-99", {"year": "x", "month": [], "day": {}},
            {"year": 2020, "month": 0, "day": -3}, 0, -1, [], {}, True,
        ]
        counts = [None, "", "unknown", "-3", "-3 chapters", 0, -1, 1, 2.5, "Volume 7", [], {}]
        for index in range(250):
            record = manga_baka_series(
                series_id=index + 1,
                series_type=rng.choice(["novel", "manga", "manhwa", "manhua", None]),
                published={"start": rng.choice(strange)},
                published_at=rng.choice(strange),
                total_chapters=rng.choice(counts),
                final_volume=rng.choice(counts),
                rating=rng.choice([None, "?", 0, 50, 101, -5, [], {}]),
            )
            normalized = mb.normalize_series(record)
            self.assertEqual(normalized["_mangabaka_id"], index + 1)
            start = normalized["startDate"]
            self.assertIsInstance(start, dict)
            if start["year"] is not None:
                self.assertTrue(1 <= start["month"] <= 12)
                self.assertTrue(1 <= start["day"] <= 31)

    def test_bad_pagination_shape_is_treated_as_missing_metadata(self):
        payload = {
            "data": [manga_baka_series(123)],
            "pagination": ["this should be an object"],
        }
        with patch.object(mb, "search_series", return_value=payload):
            result = mb.search_media(
                "Adversarial Example",
                page=3,
                media_type="MANGA",
                media_format="NOVEL",
                filters={"format_filter": "NOVEL"},
                limit=10,
            )
        self.assertEqual(len(result["media"]), 1)
        self.assertEqual(result["pageInfo"]["currentPage"], 3)
        self.assertEqual(result["pageInfo"]["lastPage"], 3)


class UnifiedCatalogAdversarialTests(unittest.TestCase):
    def test_duplicate_ids_from_either_provider_are_emitted_only_once(self):
        anilist_rows = [
            media(100, "AniList original", "MANGA", "MANGA"),
            media(100, "Duplicate AniList row", "MANGA", "MANGA"),
            media(101, "AniList other", "MANGA", "MANGA"),
        ]

        def mb_row(local_id, provider_id, title):
            return {
                "id": local_id,
                "type": "MANGA",
                "format": "MANGA",
                "title": {"english": title, "romaji": title, "native": None},
                "averageScore": 80,
                "_provider": "MangaBaka",
                "_mangabaka_id": provider_id,
                "_mangabaka": {"id": provider_id, "type": "manga", "content_rating": "safe"},
                "relations": {"edges": []},
            }

        manga_baka_rows = [
            mb_row(-44, 44, "MangaBaka original"),
            mb_row(-44, 145, "Same synthetic local ID"),
            mb_row(-45, 45, "Different MangaBaka work"),
        ]
        page = {"currentPage": 1, "lastPage": 1, "hasNextPage": False}
        with patch("catalog_search.search_anime", return_value={"pageInfo": page, "media": anilist_rows}), \
             patch("catalog_search.search_mangabaka_media", return_value={"pageInfo": page, "media": manga_baka_rows}), \
             patch("catalog_search.enrich_anilist_results"):
            result = catalog_search.search_combined_media(
                "Example", 1, None, None, {"sort": "SEARCH_MATCH"}, include_relations=False
            )

        ids = [row["id"] for row in result["media"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {100, 101, -44, -45})

    def test_random_duplicate_catalog_pages_preserve_unique_ids(self):
        rng = random.Random(7719)
        page = {"currentPage": 1, "lastPage": 1, "hasNextPage": False}
        for _ in range(80):
            anilist_rows = []
            mb_rows = []
            for index in range(rng.randint(1, 18)):
                media_id = rng.randint(1000, 1010)
                anilist_rows.append(media(media_id, f"Anime {media_id}", "MANGA", "MANGA"))
            for index in range(rng.randint(1, 18)):
                provider_id = rng.randint(2000, 2010)
                local_id = -provider_id
                mb_rows.append({
                    "id": local_id,
                    "type": "MANGA",
                    "format": "MANGA",
                    "title": {"english": f"Book {provider_id}", "romaji": f"Book {provider_id}"},
                    "averageScore": 77,
                    "_provider": "MangaBaka",
                    "_mangabaka_id": provider_id,
                    "_mangabaka": {"id": provider_id, "type": "manga", "content_rating": "safe"},
                    "relations": {"edges": []},
                })
            with patch("catalog_search.search_anime", return_value={"pageInfo": page, "media": anilist_rows}), \
                 patch("catalog_search.search_mangabaka_media", return_value={"pageInfo": page, "media": mb_rows}), \
                 patch("catalog_search.enrich_anilist_results"):
                result = catalog_search.search_combined_media(
                    "Fuzz", 1, None, None, {"sort": "SEARCH_MATCH"}, include_relations=False
                )
            ids = [row["id"] for row in result["media"]]
            self.assertEqual(len(ids), len(set(ids)))


class BundleGraphAdversarialTests(unittest.TestCase):
    def test_random_cyclic_relation_graphs_partition_all_input_ids_once(self):
        rng = random.Random(29384)
        formats = ["TV", "TV_SHORT", "OVA", "ONA", "MOVIE", "SPECIAL", "MANGA", "NOVEL", "ONE_SHOT", None]
        relations = ["PREQUEL", "SEQUEL", "PARENT", "SIDE_STORY", "SUMMARY",
                     "SPIN_OFF", "ALTERNATIVE", "COMPILATION", "CONTAINS", "ADAPTATION"]
        for round_number in range(60):
            count = rng.randint(1, 24)
            items = []
            types = []
            for index in range(count):
                media_type = rng.choice(["ANIME", "MANGA"])
                types.append(media_type)
                if media_type == "ANIME":
                    fmt = rng.choice(formats[:6] + [None])
                else:
                    fmt = rng.choice(["MANGA", "NOVEL", "ONE_SHOT", None])
                title = rng.choice([
                    f"Franchise {rng.randrange(5)}",
                    f"Franchise {rng.randrange(5)} Season {rng.randrange(1, 6)}",
                    f"Independent Title {index}",
                ])
                items.append(media(10000 + index, title, media_type, fmt, relations=[]))

            by_id = {item["id"]: item for item in items}
            for item in items:
                edges = []
                for _ in range(rng.randrange(0, min(6, count + 1))):
                    target = rng.choice(items)
                    edges.append({
                        "relationType": rng.choice(relations),
                        "node": {
                            "id": target["id"],
                            "type": target["type"],
                            "format": target["format"],
                            "title": target["title"],
                            "startDate": target["startDate"],
                            "coverImage": target["coverImage"],
                        },
                    })
                item["relations"] = {"edges": edges}

            with patch("series.get_manual_bundle_links", return_value=[]), \
                 patch("series.get_bundle_exclusions", return_value=[]), \
                 patch("series.get", return_value=False), \
                 patch("series.get_media_relations_batch", side_effect=AssertionError("unexpected network call")):
                grouped = series.group_media_results(items, enrich=False, delay=0)

            flattened = [
                member["id"]
                for group in grouped
                for member in (group.get("_series_members") or [group])
            ]
            expected = sorted(by_id)
            self.assertEqual(sorted(flattened), expected, msg=f"seed round {round_number}")
            self.assertEqual(len(flattened), len(set(flattened)), msg=f"duplicate member in round {round_number}")


class IsolatedDatabaseAdversarialTests(unittest.TestCase):
    @staticmethod
    def work(work_id, media_type="ANIME", media_format="TV", chapters=None, volumes=None):
        return {
            "id": work_id,
            "type": media_type,
            "format": media_format,
            "title": {"english": f"Work {work_id}", "romaji": f"Work {work_id}", "native": None},
            "episodes": 12 if media_type == "ANIME" else None,
            "chapters": chapters,
            "volumes": volumes,
            "coverImage": {"large": None},
        }

    def test_malformed_episode_rows_do_not_break_refresh_or_progress(self):
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory(prefix="nekotrack-adversarial-db-") as temp_dir:
            try:
                os.chdir(temp_dir)
                database.initialize_database()
                work_id = 80001
                database.save_anime(self.work(work_id))
                database.add_to_library(work_id)
                database.save_episodes(work_id, [
                    {"episodeNumber": 1, "title": "One"},
                    {"episodeNumber": "2", "title": "Two"},
                    {"episodeNumber": "broken", "title": "Bad"},
                    {"episodeNumber": 0, "title": "Zero"},
                    {"episodeNumber": -1, "title": "Negative"},
                    {"episodeNumber": 1.5, "title": "Fraction"},
                    {"episodeNumber": True, "title": "Boolean"},
                    None,
                    "not a dictionary",
                ])
                episodes = database.get_episodes(work_id)
                self.assertEqual([row["episode_number"] for row in episodes], [1, 2])
                self.assertEqual(database.set_episode_watched(work_id, 1, True), (1, 2))
                self.assertEqual(database.get_work(work_id)["status"], "Watching")
                self.assertEqual(database.set_episode_watched(work_id, 2, True), (2, 2))
                self.assertEqual(database.get_work(work_id)["status"], "Completed")
                self.assertEqual(database.set_episode_watched(work_id, 2, False), (1, 2))
                self.assertEqual(database.get_work(work_id)["status"], "Watching")
            finally:
                os.chdir(original_cwd)

    def test_negative_provider_volume_numbers_are_not_mapped_to_positive_items(self):
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory(prefix="nekotrack-adversarial-reading-") as temp_dir:
            try:
                os.chdir(temp_dir)
                database.initialize_database()
                work_id = 80002
                database.save_anime(self.work(work_id, "MANGA", "NOVEL", chapters=20, volumes=8))
                saved = database.save_reading_item_metadata(work_id, "volume", [
                    {"number": "-5", "title": "Invalid negative volume"},
                    {"number": "3", "title": "Volume 3"},
                ])
                rows = database.get_reading_items(work_id, "volume", limit=100)
                self.assertEqual(saved, 1)
                self.assertEqual([row["item_number"] for row in rows], [3])
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
