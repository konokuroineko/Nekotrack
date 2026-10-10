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

    def test_exclusion_cannot_be_bypassed_through_a_transitive_relation(self):
        first = media(11, "Echo Series", "TV", relations=[
            edge("SEQUEL", {
                "id": 12, "type": "ANIME", "format": "TV",
                "title": {"english": "Echo Series Season 2", "romaji": "Echo Series Season 2"},
                "coverImage": {"large": None},
                "startDate": {"year": 2021, "month": 1, "day": 1},
            }),
            edge("SEQUEL", {
                "id": 13, "type": "ANIME", "format": "TV",
                "title": {"english": "Echo Series Season 3", "romaji": "Echo Series Season 3"},
                "coverImage": {"large": None},
                "startDate": {"year": 2022, "month": 1, "day": 1},
            }),
        ])
        second = media(12, "Echo Series Season 2", "TV", relations=[
            edge("PREQUEL", {
                "id": 11, "type": "ANIME", "format": "TV",
                "title": {"english": "Echo Series", "romaji": "Echo Series"},
                "coverImage": {"large": None},
                "startDate": {"year": 2020, "month": 1, "day": 1},
            }),
            edge("SEQUEL", {
                "id": 13, "type": "ANIME", "format": "TV",
                "title": {"english": "Echo Series Season 3", "romaji": "Echo Series Season 3"},
                "coverImage": {"large": None},
                "startDate": {"year": 2022, "month": 1, "day": 1},
            }),
        ])
        third = media(13, "Echo Series Season 3", "TV", relations=[
            edge("PREQUEL", {
                "id": 12, "type": "ANIME", "format": "TV",
                "title": {"english": "Echo Series Season 2", "romaji": "Echo Series Season 2"},
                "coverImage": {"large": None},
                "startDate": {"year": 2021, "month": 1, "day": 1},
            }),
        ])

        with patch("series.get_manual_bundle_links", return_value=[]), \
             patch("series.get_bundle_exclusions", return_value=[{"work_a": 11, "work_b": 12}]), \
             patch("series.get", return_value=False):
            groups = series.group_media_results([first, second, third], enrich=False)

        memberships = [
            {member["id"] for member in group["_series_members"]}
            for group in groups
        ]
        self.assertTrue(any(11 in members for members in memberships))
        self.assertTrue(any(12 in members for members in memberships))
        self.assertFalse(any({11, 12} <= members for members in memberships))

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


    def test_generic_other_relation_can_bundle_a_named_ova_when_enabled(self):
        tv = media(101, "Re:Zero - Starting Life in Another World", "TV", relations=[
            edge("OTHER", {
                "id": 102, "type": "ANIME", "format": "OVA",
                "title": {
                    "english": "Re:Zero - Starting Life in Another World: Memory Snow",
                    "romaji": "Re:Zero kara Hajimeru Isekai Seikatsu - Memory Snow",
                    "native": None,
                },
                "coverImage": {"large": None},
                "startDate": {"year": 2018, "month": 1, "day": 1},
            })
        ])
        ova = media(
            102,
            "Re:Zero - Starting Life in Another World: Memory Snow",
            "OVA",
        )

        with patch("series.get_manual_bundle_links", return_value=[]), \\
             patch("series.get_bundle_exclusions", return_value=[]), \\
             patch("series.get", side_effect=lambda key: key == "bundle_include_ovas"):
            groups = series.group_media_results([tv, ova], enrich=False)

        self.assertEqual(len(groups), 1)
        self.assertEqual(
            {member["id"] for member in groups[0]["_series_members"]},
            {101, 102},
        )

    def test_generic_mangabaka_related_type_can_bundle_matching_novel_entries(self):
        first = media(
            -501,
            "Re:Zero - Starting Life in Another World - Light Novel",
            "NOVEL",
            "MANGA",
            relations=[edge("RELATED", {
                "id": -502,
                "type": "MANGA",
                "format": "NOVEL",
                "title": {
                    "english": "Re:Zero - Starting Life in Another World - Volume 2",
                    "romaji": "Re:Zero kara Hajimeru Isekai Seikatsu Volume 2",
                    "native": None,
                },
                "coverImage": {"large": None},
                "startDate": {"year": 2015, "month": 1, "day": 1},
            })],
        )
        second = media(
            -502,
            "Re:Zero - Starting Life in Another World - Volume 2",
            "NOVEL",
            "MANGA",
        )

        with patch("series.get_manual_bundle_links", return_value=[]), \\
             patch("series.get_bundle_exclusions", return_value=[]), \\
             patch("series.get", side_effect=lambda key: key == "bundle_include_novels"):
            groups = series.group_media_results([first, second], enrich=False)

        self.assertEqual(len(groups), 1)
        self.assertEqual(
            {member["id"] for member in groups[0]["_series_members"]},
            {-501, -502},
        )

    def test_generic_relationship_does_not_bundle_an_unrelated_series(self):
        first = media(201, "Re:Zero - Starting Life in Another World", "TV", relations=[
            edge("OTHER", {
                "id": 202, "type": "ANIME", "format": "OVA",
                "title": {"english": "Overlord: Ple Ple Pleiades", "romaji": "Overlord Ple Ple Pleiades"},
                "coverImage": {"large": None},
                "startDate": {"year": 2015, "month": 1, "day": 1},
            })
        ])
        second = media(202, "Overlord: Ple Ple Pleiades", "OVA")
        with patch("series.get_manual_bundle_links", return_value=[]), \\
             patch("series.get_bundle_exclusions", return_value=[]), \\
             patch("series.get", side_effect=lambda key: key == "bundle_include_ovas"):
            groups = series.group_media_results([first, second], enrich=False)

        self.assertEqual(len(groups), 2)


if __name__ == "__main__":
    unittest.main()
