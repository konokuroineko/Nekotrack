import unittest
from unittest.mock import patch

import mangabaka


class MangaBakaTests(unittest.TestCase):
    def setUp(self):
        mangabaka._response_cache.clear()

    def test_normalize_novel_and_multilingual_titles(self):
        raw = {
            "id": 456, "type": "novel", "content_rating": "safe", "title": "Example Novel",
            "titles": [
                {"language": "en", "title": "Example Novel", "traits": ["official"], "is_primary": True},
                {"language": "ja-Latn", "title": "Rei no Shousetsu", "traits": ["official"], "is_primary": False},
                {"language": "ja", "title": "例の小説", "traits": ["native", "official"], "is_primary": True},
                {"language": "en", "title": "Example IF Route", "traits": ["alternative"], "is_primary": False},
            ],
            "cover": {"x350": "https://images.example/cover.jpg"},
            "published": {"start_date": "2020-03-02"}, "total_chapters": 31,
            "final_volume": 8, "rating": 8.1, "description": "A test novel",
            "tags": [{"name": "Fantasy", "is_genre": True}], "links": [],
        }
        item = mangabaka.normalize_series(raw)
        self.assertLess(item["id"], 0)
        self.assertEqual(item["type"], "MANGA")
        self.assertEqual(item["format"], "NOVEL")
        self.assertEqual(item["title"]["romaji"], "Rei no Shousetsu")
        self.assertEqual(item["title"]["native"], "例の小説")
        self.assertEqual(item["chapters"], 31)
        self.assertEqual(item["volumes"], 8)
        self.assertEqual(item["_provider_id"], "456")
        self.assertEqual(len(item["_alternate_title_entries"]), 4)

    def test_linked_anilist_id_is_used(self):
        raw = {
            "id": 10023, "type": "manga", "content_rating": "safe",
            "titles": [{"language": "en", "title": "Title", "traits": ["official"], "is_primary": True}],
            "links": [{"name": "AniList", "type": "source", "url": "https://anilist.co/manga/12345/title/"}],
            "cover": {}, "published": {},
        }
        self.assertEqual(mangabaka.normalize_series(raw)["id"], 12345)

    def test_unsafe_record_is_not_normalized(self):
        with self.assertRaises(ValueError):
            mangabaka.normalize_series({"id": 5, "type": "manga", "content_rating": "suggestive"})

    def test_api_get_caches_response(self):
        response = unittest.mock.Mock()
        response.status_code = 200
        response.headers = {}
        response.json.return_value = {"status": 200, "data": [{"id": 1}]}
        with patch.object(mangabaka.requests, "get", return_value=response) as get:
            first = mangabaka.api_get("series/search", {"q": "Test"})
            second = mangabaka.api_get("series/search", {"q": "Test"})
        self.assertEqual(first, second)
        self.assertEqual(get.call_count, 1)

    def test_enrichment_keeps_anilist_id_and_merges_titles(self):
        anilist = {
            "id": 77, "type": "MANGA", "format": "NOVEL",
            "title": {"english": "Novel", "romaji": "Romanized", "native": None},
            "chapters": None, "volumes": None, "description": None,
            "coverImage": {}, "synonyms": [], "relations": {"edges": []},
        }
        mb = {
            "id": 100, "type": "novel", "content_rating": "safe",
            "titles": [
                {"language": "en", "title": "Novel", "traits": ["official"], "is_primary": True},
                {"language": "ja-Latn", "title": "Nihongo Title", "traits": ["official"], "is_primary": False},
            ],
            "total_chapters": 22, "final_volume": 4, "description": "Description",
            "published": {}, "cover": {"x350": "https://example/cover.jpg"}, "links": [],
        }
        merged = mangabaka.enrich_anilist_media_from_mangabaka(anilist, mb)
        self.assertEqual(merged["id"], 77)
        self.assertEqual(merged["chapters"], 22)
        self.assertEqual(merged["volumes"], 4)
        self.assertEqual(merged["_provider_id"], "100")
        self.assertIn("Nihongo Title", merged["synonyms"])


if __name__ == "__main__":
    unittest.main()
