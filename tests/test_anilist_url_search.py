import unittest
from unittest.mock import patch

import api


class AniListUrlSearchTests(unittest.TestCase):
    def test_parse_anime_url(self):
        self.assertEqual(
            api.parse_anilist_url("https://anilist.co/anime/16498/Attack-on-Titan/"),
            16498,
        )

    def test_parse_manga_url_with_query_string(self):
        self.assertEqual(
            api.parse_anilist_url("https://www.anilist.co/manga/12345/example?foo=bar"),
            12345,
        )

    def test_reject_non_anilist_url(self):
        self.assertIsNone(api.parse_anilist_url("https://example.com/anime/16498/Test"))
        self.assertIsNone(api.parse_anilist_url("16498"))

    def test_get_media_by_url_uses_exact_id(self):
        captured = {}

        def fake_request(query, variables=None):
            captured["query"] = query
            captured["variables"] = variables
            return {
                "Media": {
                    "id": 16498,
                    "type": "ANIME",
                    "title": {
                        "romaji": "Shingeki no Kyojin",
                        "english": "Attack on Titan",
                        "native": "進撃の巨人",
                    },
                    "format": "TV",
                }
            }

        with patch.object(api, "anilist_request", side_effect=fake_request):
            media = api.get_media_by_anilist_url(
                "https://anilist.co/anime/16498/Attack-on-Titan/"
            )

        self.assertEqual(media["id"], 16498)
        self.assertEqual(captured["variables"], {"id": 16498})
        self.assertIn("Media(id: $id)", captured["query"])
        self.assertNotIn("relations", captured["query"])

    def test_invalid_media_url_raises(self):
        with self.assertRaises(ValueError):
            api.get_media_by_anilist_url("https://example.com/anime/16498/Test")


if __name__ == "__main__":
    unittest.main()
