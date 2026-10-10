import unittest
from unittest.mock import patch

import catalog_search
import series


def anime_item(media_id, title, media_type="MANGA", media_format="MANGA", score=80):
    return {
        "id": media_id, "type": media_type, "format": media_format,
        "title": {"english": title, "romaji": title},
        "averageScore": score, "startDate": {"year": 2020, "month": 1, "day": 1},
        "relations": {"edges": []},
    }


def mb_item(series_id, title, local_id=None, score=80, publisher_id=None, is_licensed=None):
    local_id = -series_id if local_id is None else local_id
    raw = {
        "id": series_id, "type": "manga",
        "titles": [{"language": "en", "title": title}],
        "external_ids": [], "content_rating": "safe", "rating": score,
    }
    if publisher_id is not None:
        raw["publisher_id"] = publisher_id
    if is_licensed is not None:
        raw["is_licensed"] = is_licensed
    return {
        "id": local_id, "type": "MANGA", "format": "MANGA",
        "title": {"english": title, "romaji": title},
        "averageScore": score, "_provider": "MangaBaka",
        "_mangabaka_id": series_id, "_mangabaka": raw,
        "relations": {"edges": []},
    }


class CombinedCatalogSearchTests(unittest.TestCase):
    @patch("catalog_search.enrich_anilist_results")
    @patch("catalog_search.search_mangabaka_media")
    @patch("catalog_search.search_anime")
    def test_merges_and_deduplicates_linked_titles(self, search_anilist, search_mb, enrich):
        search_anilist.return_value = {
            "pageInfo": {"currentPage": 1, "lastPage": 2, "hasNextPage": True},
            "media": [anime_item(100, "Shared Title"), anime_item(101, "AniList Only")],
        }
        search_mb.return_value = {
            "pageInfo": {"currentPage": 1, "lastPage": 3, "hasNextPage": True},
            "media": [mb_item(9, "Shared Title", local_id=100), mb_item(10, "MangaBaka Only")],
        }
        result = catalog_search.search_combined_media("Shared", 1, None, None, {"sort": "SEARCH_MATCH"})
        self.assertEqual({row["id"] for row in result["media"]}, {100, 101, -10})
        self.assertTrue(result["pageInfo"]["hasNextPage"])
        self.assertEqual(result["pageInfo"]["lastPage"], 3)
        enrich.assert_called_once()

    @patch("catalog_search.enrich_anilist_results")
    @patch("catalog_search.search_mangabaka_media")
    @patch("catalog_search.search_anime")
    def test_publisher_filter_requires_matching_mangabaka_metadata(self, search_anilist, search_mb, enrich):
        linked = anime_item(100, "Published Work")
        linked["_mangabaka_id"] = 9
        search_anilist.return_value = {
            "pageInfo": {"currentPage": 1, "lastPage": 1, "hasNextPage": False},
            "media": [linked, anime_item(101, "Unmatched Work")],
        }
        search_mb.return_value = {
            "pageInfo": {"currentPage": 1, "lastPage": 1, "hasNextPage": False},
            "media": [mb_item(9, "Published Work", local_id=100, publisher_id=5)],
        }
        result = catalog_search.search_combined_media(
            "", 1, None, None, {"publisher_id": "5", "sort": "POPULARITY_DESC"}
        )
        self.assertEqual([row["id"] for row in result["media"]], [100])
        self.assertNotIn("publisher_id", search_anilist.call_args.kwargs)

    @patch("catalog_search.enrich_anilist_results")
    @patch("catalog_search.search_mangabaka_media")
    @patch("catalog_search.search_anime")
    def test_anime_only_search_skips_mangabaka(self, search_anilist, search_mb, enrich):
        search_anilist.return_value = {
            "pageInfo": {"currentPage": 1, "lastPage": 1, "hasNextPage": False},
            "media": [anime_item(100, "Anime", media_type="ANIME", media_format="TV")],
        }
        result = catalog_search.search_combined_media(
            "Anime", 1, "ANIME", None, {"sort": "SEARCH_MATCH"}
        )
        self.assertEqual([row["id"] for row in result["media"]], [100])
        search_mb.assert_not_called()

    def test_extremely_long_publisher_ids_are_rejected_without_crashing(self):
        abusive_id = "9" * 5000

        self.assertEqual(catalog_search._collect_publisher_ids(abusive_id), set())
        self.assertEqual(catalog_search._collect_publisher_ids(10**200), set())
        self.assertIsNone(catalog_search._positive_provider_id(abusive_id))
        self.assertFalse(
            catalog_search._matches_provider_only_filters(
                {"_mangabaka": {"publisher_id": 5}},
                {"publisher_id": abusive_id},
            )
        )
        self.assertFalse(
            catalog_search._matches_provider_only_filters(
                {"_mangabaka": {"publisher_id": 5}},
                {"publisher_id": 10**200},
            )
        )

    def test_media_and_provider_ids_are_bounded_and_strict(self):
        valid = {
            "id": 123,
        }
        self.assertEqual(catalog_search._media_id(valid), 123)
        self.assertEqual(catalog_search._media_id({"id": -42}), -42)
        for value in (
            True,
            False,
            0,
            1.5,
            float("inf"),
            float("nan"),
            1 << 31,
            -(1 << 63),
            -(1 << 63) - 1,
            "bad-id",
            "9" * 5000,
        ):
            with self.subTest(media_id=repr(value)[:60]):
                self.assertIsNone(catalog_search._media_id({"id": value}))

        self.assertEqual(catalog_search._provider_id({"_mangabaka_id": 15}), 15)
        self.assertIsNone(catalog_search._provider_id({"_mangabaka_id": 10**200}))
        self.assertIsNone(catalog_search._provider_id({"_mangabaka_id": "9" * 5000}))

    @patch("catalog_search.enrich_anilist_results")
    @patch("catalog_search.search_mangabaka_media")
    @patch("catalog_search.search_anime")
    def test_malformed_catalog_ids_are_removed_before_enrichment(
        self, search_anilist, search_mb, enrich
    ):
        search_anilist.return_value = {
            "pageInfo": {"currentPage": 1, "lastPage": 1, "hasNextPage": False},
            "media": [
                anime_item(100, "Valid AniList Work"),
                anime_item(1 << 31, "Out-of-range AniList ID"),
                anime_item("9" * 5000, "Malformed AniList ID"),
                anime_item(True, "Boolean AniList ID"),
            ],
        }
        invalid_local_id = mb_item(10, "Out-of-range local ID", local_id=1 << 100)
        invalid_provider_id = mb_item(10**200, "Out-of-range provider ID", local_id=-12)
        valid_local = mb_item(11, "Valid MangaBaka Only", local_id=-11)
        search_mb.return_value = {
            "pageInfo": {"currentPage": 1, "lastPage": 1, "hasNextPage": False},
            "media": [invalid_local_id, invalid_provider_id, valid_local],
        }

        result = catalog_search.search_combined_media("", 1, None, None, {"sort": "SEARCH_MATCH"})

        self.assertEqual({row["id"] for row in result["media"]}, {100, -11})
        enrich.assert_called_once()
        candidates = enrich.call_args.kwargs["candidates"]
        self.assertEqual([candidate["id"] for candidate in candidates], [11])

    @patch("catalog_search.enrich_anilist_results")
    @patch("catalog_search.search_mangabaka_media")
    @patch("catalog_search.search_anime")
    def test_malformed_attached_provider_payload_does_not_crash_provider_filter(
        self, search_anilist, search_mb, enrich
    ):
        malformed = anime_item(100, "Malformed linked work")
        malformed["_mangabaka"] = ["unexpected", "provider", "payload"]
        search_anilist.return_value = {
            "pageInfo": {"currentPage": 1, "lastPage": 1, "hasNextPage": False},
            "media": [malformed],
        }
        search_mb.return_value = {
            "pageInfo": {"currentPage": 1, "lastPage": 1, "hasNextPage": False},
            "media": [mb_item(9, "Matching provider row")],
        }

        result = catalog_search.search_combined_media(
            "", 1, None, None, {"publisher_id": "5"}
        )
        self.assertEqual(result["media"], [])

    @patch("catalog_search.search_anime")
    def test_invalid_page_and_malformed_pagination_fall_back_safely(self, search_anilist):
        search_anilist.return_value = {
            "pageInfo": {
                "currentPage": "bad",
                "lastPage": float("inf"),
                "hasNextPage": "false",
            },
            "media": [anime_item(100, "Valid work")],
        }
        result = catalog_search.search_combined_media(
            "", float("inf"), "ANIME", None, {}
        )
        self.assertEqual(result["pageInfo"]["currentPage"], 1)
        self.assertEqual(result["pageInfo"]["lastPage"], 1)
        self.assertFalse(result["pageInfo"]["hasNextPage"])

    @patch("catalog_search.search_anime")
    def test_extreme_page_numbers_are_clamped_and_cannot_request_page_10001(self, search_anilist):
        search_anilist.return_value = {
            "pageInfo": {
                "currentPage": 10**100,
                "lastPage": 10**100,
                "hasNextPage": True,
            },
            "media": [],
        }

        result = catalog_search.search_combined_media(
            "", 10**100, "ANIME", None, {}
        )

        self.assertEqual(search_anilist.call_args.args[1], catalog_search.MAX_CATALOG_PAGES)
        self.assertEqual(result["pageInfo"]["currentPage"], catalog_search.MAX_CATALOG_PAGES)
        self.assertEqual(result["pageInfo"]["lastPage"], catalog_search.MAX_CATALOG_PAGES)
        self.assertFalse(result["pageInfo"]["hasNextPage"])

    @patch("catalog_search.search_mangabaka_media")
    @patch("catalog_search.search_anime")
    def test_invalid_start_date_does_not_break_date_sort(self, search_anilist, search_mb):
        valid = anime_item(100, "Dated work")
        invalid = anime_item(101, "Undated work")
        invalid["startDate"] = {"year": float("inf"), "month": 13, "day": 99}
        search_anilist.return_value = {
            "pageInfo": {"currentPage": 1, "lastPage": 1, "hasNextPage": False},
            "media": [invalid, valid],
        }
        result = catalog_search.search_combined_media(
            "", 1, "ANIME", None, {"sort": "START_DATE_DESC"}
        )
        self.assertEqual([item["id"] for item in result["media"]], [100, 101])

    @patch("series.get_media_relations_batch")
    @patch("catalog_search.enrich_anilist_results")
    @patch("catalog_search.search_mangabaka_media")
    @patch("catalog_search.search_anime")
    def test_mangabaka_only_results_bundle_through_native_relations(
        self, search_anilist, search_mb, enrich, fetch_relations
    ):
        search_anilist.return_value = {
            "pageInfo": {"currentPage": 1, "lastPage": 1, "hasNextPage": False},
            "media": [],
        }
        first = mb_item(11, "Example Original", local_id=-11)
        second = mb_item(12, "Example Continuation", local_id=-12)
        search_mb.return_value = {
            "pageInfo": {"currentPage": 1, "lastPage": 1, "hasNextPage": False},
            "media": [first, second],
        }

        result = catalog_search.search_combined_media(
            "Example", 1, None, None, {"sort": "SEARCH_MATCH"}
        )
        self.assertEqual({item["id"] for item in result["media"]}, {-11, -12})
        self.assertTrue(all("_relations_loaded" not in item for item in result["media"]))
        enrich.assert_not_called()

        related_node = {
            "id": second["id"],
            "type": second["type"],
            "format": second["format"],
            "title": second["title"],
            "coverImage": second["coverImage"],
        }
        first_details = {
            **first,
            "relations": {
                "edges": [{"relationType": "SEQUEL", "node": related_node}],
            },
        }
        second_details = {**second, "relations": {"edges": []}}
        fetch_relations.return_value = {
            -11: first_details,
            -12: second_details,
        }

        with (
            patch.dict(series._relation_cache, {}, clear=True),
            patch("series.get_manual_bundle_links", return_value=[]),
            patch("series.get_bundle_exclusions", return_value=[]),
            patch("series.get", side_effect=lambda key: key == "bundle_include_manga"),
        ):
            groups = series.group_media_results(
                result["media"], enrich=True, delay=0
            )

        fetch_relations.assert_called_once()
        self.assertEqual(len(groups), 1)
        self.assertEqual(
            {item["id"] for item in groups[0]["_series_members"]},
            {-11, -12},
        )

