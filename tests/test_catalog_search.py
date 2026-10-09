import unittest
from unittest.mock import patch

import catalog_search


def anime_item(media_id, title, media_type="MANGA", media_format="MANGA", score=80):
    return {
        "id": media_id, "type": media_type, "format": media_format,
        "title": {"english": title, "romaji": title},
        "averageScore": score, "startDate": {"year": 2020, "month": 1, "day": 1},
        "relations": {"edges": []},
    }


def mb_item(series_id, title, local_id=None, score=80):
    local_id = -series_id if local_id is None else local_id
    raw = {
        "id": series_id, "type": "manga",
        "titles": [{"language": "en", "title": title}],
        "external_ids": [], "content_rating": "safe", "rating": score,
    }
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
            "media": [mb_item(9, "Published Work", local_id=100)],
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

