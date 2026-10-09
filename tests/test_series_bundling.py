import unittest
from unittest.mock import patch

import series


def media(media_id, title, fmt="TV", media_type="ANIME", relations=None):
    return {
        "id": media_id, "type": media_type, "format": fmt,
        "title": {"english": title, "romaji": title, "native": None},
        "startDate": {"year": 2020, "month": 1, "day": 1},
        "coverImage": {"large": None}, "relations": {"edges": relations or []},
    }


def edge(relation_type, node):
    return {"relationType": relation_type, "node": node}


class BundleOptionTests(unittest.TestCase):
    def test_tv_and_tv_short_are_always_bundleable(self):
        with patch("series.get", return_value=False):
            self.assertTrue(series._auto_bundleable(media(1, "Series", "TV")))
            self.assertTrue(series._auto_bundleable(media(2, "Series Short", "TV_SHORT")))

    def test_extra_formats_follow_preferences(self):
        settings = {
            "bundle_include_movies": False, "bundle_include_ovas": True,
            "bundle_include_onas": False, "bundle_include_specials": True,
            "bundle_include_manga": False, "bundle_include_novels": True,
            "bundle_include_one_shots": False,
        }
        with patch("series.get", side_effect=lambda key: settings.get(key, False)):
            self.assertFalse(series._auto_bundleable(media(1, "Movie", "MOVIE")))
            self.assertTrue(series._auto_bundleable(media(2, "OVA", "OVA")))
            self.assertFalse(series._auto_bundleable(media(3, "ONA", "ONA")))
            self.assertTrue(series._auto_bundleable(media(4, "Special", "SPECIAL")))
            self.assertFalse(series._auto_bundleable(media(5, "Manga", "MANGA", "MANGA")))
            self.assertTrue(series._auto_bundleable(media(6, "Novel", "NOVEL", "MANGA")))
            self.assertFalse(series._auto_bundleable(media(7, "One shot", "ONE_SHOT", "MANGA")))

    def test_ova_only_joins_tv_bundle_when_enabled(self):
        tv = media(1, "Example Series", "TV", relations=[
            edge("SIDE_STORY", {
                "id": 2, "type": "ANIME", "format": "OVA",
                "title": {"english": "Example Series OVA", "romaji": "Example Series OVA"},
                "coverImage": {"large": None},
                "startDate": {"year": 2021, "month": 1, "day": 1},
            })
        ])
        ova = media(2, "Example Series OVA", "OVA")
        with patch("series.get_manual_bundle_links", return_value=[]), patch("series.get_bundle_exclusions", return_value=[]), patch("series.get", return_value=False):
            default_groups = series.group_media_results([tv, ova], enrich=False)
        with patch("series.get_manual_bundle_links", return_value=[]), patch("series.get_bundle_exclusions", return_value=[]), patch("series.get", side_effect=lambda key: key == "bundle_include_ovas"):
            enabled_groups = series.group_media_results([tv, ova], enrich=False)
        self.assertEqual(len(default_groups), 2)
        self.assertEqual(len(enabled_groups), 1)
        self.assertEqual(enabled_groups[0]["_series_count"], 2)

    def test_manual_links_override_auto_bundle_rules(self):
        tv = media(1, "Main Series", "TV")
        music = media(2, "Unbundleable Theme Song", "MUSIC")
        with patch("series.get_manual_bundle_links", return_value=[{"work_a": 1, "work_b": 2}]), patch("series.get_bundle_exclusions", return_value=[]), patch("series.get", return_value=False):
            groups = series.group_media_results([tv, music], enrich=False)
        self.assertEqual(len(groups), 1)
        self.assertEqual({item["id"] for item in groups[0]["_series_members"]}, {1, 2})

    def test_exclusion_prevents_same_title_auto_grouping(self):
        first = media(1, "Same Series", "TV")
        second = media(2, "Same Series", "TV")
        with patch("series.get_manual_bundle_links", return_value=[]), patch("series.get_bundle_exclusions", return_value=[{"work_a": 1, "work_b": 2}]), patch("series.get", return_value=False):
            groups = series.group_media_results([first, second], enrich=False)
        self.assertEqual(len(groups), 2)

    def test_unrelated_spin_off_is_not_traversed(self):
        root = media(1, "One Piece", "TV", relations=[
            edge("SPIN_OFF", {
                "id": 2, "type": "ANIME", "format": "TV",
                "title": {"english": "MONSTERS", "romaji": "MONSTERS"},
                "coverImage": {"large": None},
                "startDate": {"year": 2024, "month": 1, "day": 1},
            })
        ])
        with patch("series.get_manual_bundle_links", return_value=[]), patch("series.get_bundle_exclusions", return_value=[]), patch("series.get", return_value=False):
            groups = series.group_media_results([root], enrich=False)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["_series_count"], 1)


if __name__ == "__main__":
    unittest.main()
