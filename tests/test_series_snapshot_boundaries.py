"""Regression tests for Search-selected membership surviving Library refreshes."""
import os
import tempfile
import unittest
from unittest.mock import patch

import database
import series


ANIME_MEMBERS = [
    (21355, "Re:ZERO -Starting Life in Another World-", "TV", 2016),
    (108632, "Re:ZERO -Starting Life in Another World- Season 2", "TV", 2020),
    (119661, "Re:ZERO -Starting Life in Another World- Season 2 Part 2", "TV", 2021),
    (163134, "Re:ZERO -Starting Life in Another World- Season 3", "TV", 2024),
    (189046, "Re:ZERO -Starting Life in Another World- Season 4", "TV", 2026),
    (21780, "Re:ZERO ~Starting Break Time From Zero~", "TV_SHORT", 2016),
    (21891, "Re:PETIT ~Re: Starting Life in Another World From PETIT~", "TV_SHORT", 2016),
    (100049, "Re:ZERO -Starting Life in Another World- OVAs", "OVA", 2018),
    (120700, "Re:Zero Break Time 2nd Season", "ONA", 2020),
    (128306, "Re:Zero Break Time 2nd Season Part 2", "ONA", 2021),
    (182417, "Re:Zero Break Time 3rd Season", "ONA", 2024),
    (210687, "Re:Zero Break Time 4th Season", "ONA", 2026),
]
NOVEL_MEMBERS = [
    (85737, "Re:ZERO -Starting Life in Another World-", "NOVEL", 2014),
    (97369, "Re:ZERO -Starting Life in Another World- Short Story Collection", "NOVEL", 2014),
    (87262, "Re:ZERO -Starting Life in Another World- Ex", "NOVEL", 2015),
    (-110149, "Apocalypse Girls", "NOVEL", 2015),
    (-148236, "Re:Zero IF", "NOVEL", 2016),
    (-148237, "Re:ZERO -Starting Life in Another World-", "NOVEL", 2016),
]
MANGA_MEMBERS = [
    (85736, "Re:ZERO Chapter 1", "MANGA", 2014),
    (85814, "Re:ZERO Chapter 2", "MANGA", 2014),
    (87259, "Re:ZERO Chapter 3", "MANGA", 2015),
    (122237, "Re:ZERO Official Anthology Comic", "MANGA", 2016),
    (110174, "Kenki Renka: Re:Zero", "MANGA", 2015),
    (112218, "Re:ZERO Chapter 4", "MANGA", 2016),
    (118370, "Re:ZERO The Frozen Bond", "MANGA", 2017),
    (175172, "Re:ZERO Chapter 5", "MANGA", 2020),
]


class LibrarySeriesSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tempdir.name)
        database.initialize_database()

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.tempdir.cleanup()

    @staticmethod
    def _record(work_id, title, media_format, year):
        is_anime = media_format in {"TV", "TV_SHORT", "OVA", "ONA"}
        english = title
        romaji = title
        native = title
        if work_id == 85737:
            native = "Re:ゼロから始める異世界生活"
            romaji = "Re:Zero kara Hajimeru Isekai Seikatsu"
        elif work_id == -148236:
            native = "Re:IFから始める異世界生活"
            romaji = "Re:IF kara Hajimeru Isekai Seikatsu"
        elif work_id == -148237:
            # Same English title as 85737, but distinct native/romanized identity.
            native = "Re:IFから始める異世界生活 ゼロカラカサネルイセカイセイカツ"
            romaji = "Re:IF kara Hajimeru Isekai Seikatsu: Zero kara Kasaneru Isekai Seikatsu"
        return {
            "id": work_id,
            "type": "ANIME" if is_anime else "MANGA",
            "format": media_format,
            "title": {"english": english, "romaji": romaji, "native": native},
            "startDate": {"year": year, "month": 1, "day": 1},
            "coverImage": {"large": None},
            "relations": {"edges": []},
        }

    def _save_group(self, records, representative_id):
        member_ids = []
        for work_id, title, media_format, year in records:
            database.save_anime(self._record(work_id, title, media_format, year))
            database.add_to_library(work_id, "Planning")
            member_ids.append(work_id)
        self.assertTrue(database.save_automatic_bundle_membership(representative_id, member_ids))
        return set(member_ids)

    def test_recorded_rezero_anime_novel_and_manga_groups_survive_refresh(self):
        expected_groups = {
            frozenset(self._save_group(ANIME_MEMBERS, 21355)),
            frozenset(self._save_group(NOVEL_MEMBERS, 85737)),
            frozenset(self._save_group(MANGA_MEMBERS, 85736)),
        }
        enabled = {
            "bundle_include_movies", "bundle_include_ovas", "bundle_include_onas",
            "bundle_include_specials", "bundle_include_manga", "bundle_include_novels",
            "bundle_include_one_shots",
        }
        with patch("series.get", side_effect=lambda key: key in enabled):
            groups = series.get_library_series()

        actual_groups = {
            frozenset(int(member["id"]) for member in group["_series_members"])
            for group in groups
        }
        self.assertEqual(actual_groups, expected_groups)
        self.assertEqual(len(groups), 3)

    def test_same_english_title_cannot_merge_distinct_saved_search_groups(self):
        # These entries deliberately share an English title while preserving the
        # native/romaji distinction between the main novel and the Re:IF volume.
        first = [
            (85737, "Re:ZERO -Starting Life in Another World-", "NOVEL", 2014),
            (97369, "Re:ZERO -Starting Life in Another World-", "NOVEL", 2015),
        ]
        second = [
            (-148237, "Re:ZERO -Starting Life in Another World-", "NOVEL", 2016),
            (-148236, "Re:ZERO -Starting Life in Another World-", "NOVEL", 2016),
        ]
        expected = {
            frozenset(self._save_group(first, 85737)),
            frozenset(self._save_group(second, -148237)),
        }
        with patch("series.get", side_effect=lambda key: key == "bundle_include_novels"):
            groups = series.get_library_series()

        actual = {
            frozenset(int(member["id"]) for member in group["_series_members"])
            for group in groups
        }
        self.assertEqual(actual, expected)
        self.assertNotIn(frozenset({85737, -148237}), actual)

    def test_exclusion_still_splits_members_of_a_saved_search_snapshot(self):
        records = [
            (1, "Example novel", "NOVEL", 2014),
            (2, "Example novel", "NOVEL", 2015),
            (3, "Example novel", "NOVEL", 2016),
        ]
        self._save_group(records, 1)
        self.assertTrue(database.add_bundle_exclusion(1, 2))
        with (
            patch("series.get", side_effect=lambda key: key == "bundle_include_novels"),
            patch("series.get_library_bundle_grouping_state", wraps=database.get_library_bundle_grouping_state) as grouping_state,
        ):
            groups = series.get_library_series()

        grouping_state.assert_called_once_with({1, 2, 3})
        member_sets = {
            frozenset(int(member["id"]) for member in group["_series_members"])
            for group in groups
        }
        self.assertIn(frozenset({1, 3}), member_sets)
        self.assertIn(frozenset({2}), member_sets)
        self.assertNotIn(frozenset({1, 2, 3}), member_sets)


if __name__ == "__main__":
    unittest.main()
