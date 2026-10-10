import unittest
from unittest.mock import patch

import api as mb


def sample_series(series_id=42, series_type="novel", english="Example Work"):
    return {
        "id": series_id,
        "type": series_type,
        "status": "completed",
        "content_rating": "safe",
        "rating": 84.5,
        "total_chapters": 73,
        "final_volume": 12,
        "cover": {"x350": "https://images.example/cover.jpg"},
        "published": {"start": "2014-01-01", "end": "2023-10-01"},
        "titles": [
            {"language": "en", "traits": ["official"], "title": english, "is_primary": True},
            {"language": "ja", "traits": ["native", "official"], "title": "例の作品", "is_primary": True},
            {"language": "ja-Latn", "traits": ["official"], "title": "Rei no Sakuhin", "is_primary": True},
        ],
        "authors": ["Author Name"],
        "artists": ["Artist Name"],
        "tags": [
            {"name": "Fantasy", "name_path": "Fantasy", "is_genre": True},
            {"name": "Adventure", "name_path": "Adventure", "is_genre": False},
        ],
        "source": {},
    }


class MangaBakaAPITests(unittest.TestCase):
    def test_normalize_keeps_native_romanized_and_english_titles(self):
        normalized = mb.normalize_mangabaka_series(sample_series())
        self.assertEqual(normalized["id"], -42)
        self.assertEqual(normalized["type"], "MANGA")
        self.assertEqual(normalized["format"], "NOVEL")
        self.assertEqual(normalized["title"]["english"], "Example Work")
        self.assertEqual(normalized["title"]["romaji"], "Rei no Sakuhin")
        self.assertEqual(normalized["title"]["native"], "例の作品")
        self.assertEqual(normalized["chapters"], 73)
        self.assertEqual(normalized["volumes"], 12)
        self.assertEqual(normalized["coverImage"]["large"], "https://images.example/cover.jpg")
        self.assertEqual(normalized["_mangabaka"]["authors"], ["Author Name"])

    def test_light_novel_type_is_normalized_and_filtered_as_a_novel(self):
        record = sample_series(series_type="light_novel")
        normalized = mb.normalize_mangabaka_series(record)
        self.assertEqual(normalized["format"], "NOVEL")
        self.assertTrue(mb._matches_local_filters(record, "NOVEL", {}))
        self.assertFalse(mb._matches_local_filters(record, "MANGA", {}))

    def test_novel_search_includes_light_novel_provider_type(self):
        payload = {
            "status": 200,
            "data": [sample_series(91, series_type="light_novel")],
            "pagination": {"page": 1, "limit": 20, "count": 1, "next": None},
        }
        with patch.object(mb, "search_mangabaka_series", return_value=payload) as search:
            result = mb.search_mangabaka_media(
                "Example", media_type="MANGA", media_format="NOVEL", filters={},
            )
        self.assertEqual(len(result["media"]), 1)
        self.assertEqual(result["media"][0]["format"], "NOVEL")
        self.assertCountEqual(search.call_args.kwargs["type"], ["novel", "light_novel"])

    def test_linked_anilist_id_is_used_instead_of_synthetic_id(self):
        series = sample_series(series_id=55)
        series["anilist_response"] = {"data": {"Media": {"id": 12345}}}
        normalized = mb.normalize_mangabaka_series(series)
        self.assertEqual(normalized["id"], 12345)
        self.assertEqual(mb.get_mangabaka_external_id(series, "anilist"), 12345)

    def test_duplicate_english_titles_match_by_anilist_id(self):
        target = {"id": 200, "type": "MANGA", "title": {"english": "ReZero IF"}}
        ordinary = sample_series(1, "novel", "ReZero")
        greed_if = sample_series(2, "novel", "ReZero")
        ordinary["anilist_response"] = {"data": {"Media": {"id": 100}}}
        greed_if["anilist_response"] = {"data": {"Media": {"id": 200}}}
        self.assertIs(mb.match_series_for_anilist(target, [ordinary, greed_if]), greed_if)

    def test_ambiguous_title_match_is_not_guessed(self):
        target = {"id": 200, "type": "MANGA", "title": {"english": "ReZero"}}
        first = sample_series(1, "novel", "ReZero")
        second = sample_series(2, "novel", "ReZero")
        self.assertIsNone(mb.match_series_for_anilist(target, [first, second]))

    def test_search_defaults_to_safe_and_suggestive_ratings(self):
        with patch.object(mb, "_request", return_value={"status": 200, "data": []}) as request:
            mb.search_mangabaka_series("Example", page=2, limit=15)
        args, kwargs = request.call_args
        self.assertEqual(args[0], "series/search")
        self.assertEqual(kwargs["params"]["q"], "Example")
        self.assertEqual(kwargs["params"]["page"], 2)
        self.assertEqual(kwargs["params"]["limit"], 15)
        self.assertEqual(kwargs["params"]["content_rating"], ["safe", "suggestive"])

    def test_search_media_normalizes_novel_results_and_pagination(self):
        payload = {
            "status": 200,
            "data": [sample_series(77)],
            "pagination": {"count": 21, "page": 1, "limit": 20, "next": "?page=2"},
        }
        with patch.object(mb, "search_mangabaka_series", return_value=payload):
            result = mb.search_mangabaka_media("Example", page=1, media_type="MANGA",
                                     media_format="NOVEL", filters={})
        self.assertEqual(len(result["media"]), 1)
        self.assertEqual(result["media"][0]["format"], "NOVEL")
        self.assertTrue(result["pageInfo"]["hasNextPage"])
        self.assertEqual(result["pageInfo"]["lastPage"], 2)

    def test_get_volume_records_maps_work_titles_and_isbns(self):
        collection = {"id": 6, "type": "volume", "language": "en", "count": 1}
        work = {"id": 99, "volume_number": 1, "title": "The First Volume",
                "isbn_13": "9780000000001", "published": "2021-02-03"}
        with patch.object(mb, "get_mangabaka_series_collections",
                          return_value={"data": [collection], "pagination": {}}), \
             patch.object(mb, "get_mangabaka_collection_works",
                          return_value={"data": [work], "pagination": {}}):
            volumes = mb.get_mangabaka_volume_records(42)
        self.assertEqual(len(volumes), 1)
        self.assertEqual(volumes[0]["number"], 1)
        self.assertEqual(volumes[0]["title"], "The First Volume")
        self.assertEqual(volumes[0]["isbn"], "9780000000001")

    def test_full_series_schema_uses_documented_query_parameter(self):
        with patch.object(
            mb, "_request",
            return_value={"status": 200, "data": {"id": 42, "titles": []}},
        ) as request:
            mb.get_mangabaka_series(42, full=True)
        self.assertEqual(request.call_args.args[0], "series/42")
        self.assertEqual(request.call_args.kwargs["params"], {"schema": "full"})

    def test_hidden_gems_mode_uses_the_discovery_endpoint(self):
        payload = {
            "status": 200,
            "data": [sample_series(88)],
            "pagination": {"count": 1, "page": 1, "limit": 20, "next": None},
        }
        with patch.object(mb, "get_mangabaka_hidden_gems", return_value=payload) as hidden_gems:
            result = mb.search_mangabaka_media("", browse_mode="hidden_gems")
        hidden_gems.assert_called_once()
        self.assertEqual(result["media"][0]["_mangabaka_id"], 88)

    def test_query_in_hidden_gems_mode_still_performs_title_search(self):
        payload = {"status": 200, "data": [sample_series(89)],
                   "pagination": {"count": 1, "page": 1, "limit": 20, "next": None}}
        with patch.object(mb, "search_mangabaka_series", return_value=payload) as search:
            mb.search_mangabaka_media("Example", browse_mode="hidden_gems")
        search.assert_called_once()
        self.assertEqual(search.call_args.args[0], "Example")

    def test_account_and_moderation_routes_are_not_public_catalog_calls(self):
        with self.assertRaises(ValueError):
            mb.get_mangabaka_public_data("my/profile")
        with self.assertRaises(ValueError):
            mb.get_mangabaka_public_data("mod/statistics")


    def test_mangabaka_implementation_lives_in_central_api_module(self):
        public_functions = (
            "enrich_anilist_media",
            "enrich_anilist_results",
            "get_mangabaka_external_id",
            "get_mangabaka_collection_works",
            "get_mangabaka_public_data",
            "get_mangabaka_publisher",
            "get_mangabaka_publisher_stats",
            "get_mangabaka_related_series",
            "get_mangabaka_series",
            "get_mangabaka_series_collections",
            "get_mangabaka_series_mix",
            "get_mangabaka_series_news",
            "get_mangabaka_similar_publishers",
            "get_mangabaka_volume_records",
            "get_mangabaka_hidden_gems",
            "get_mangabaka_work",
            "get_mangabaka_publishers",
            "normalize_mangabaka_series",
            "search_mangabaka_media",
            "search_mangabaka_series",
        )
        for public_name in public_functions:
            with self.subTest(api_name=public_name):
                function = getattr(mb, public_name)
                self.assertTrue(callable(function))
                self.assertEqual(function.__module__, "api")
        self.assertEqual(mb.MangaBakaAPIError.__module__, "api")



if __name__ == "__main__":
    unittest.main()
