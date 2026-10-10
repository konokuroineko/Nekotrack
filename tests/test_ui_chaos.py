"""Seeded randomized GUI-filter tests; never start a search or access the network."""
import os
import random
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import ui.preferences as preferences


class MemorySettings:
    stores = {}

    def __init__(self, organization, application):
        self.store = self.stores.setdefault((organization, application), {})

    def value(self, key, default=None):
        return self.store.get(key, default)

    def setValue(self, key, value):
        self.store[key] = value

    def allKeys(self):
        return list(self.store)

    def sync(self):
        pass


with patch.object(preferences, "QSettings", MemorySettings):
    from ui.pages.search_page import SearchPage
from PySide6.QtWidgets import QApplication


def _fuzz_seed(base):
    try:
        return int(os.environ.get("NEKOTRACK_FUZZ_SEED", base)) + int(base)
    except (TypeError, ValueError, OverflowError):
        return int(base)


class SearchFilterUiChaosTests(unittest.TestCase):
    SEED = 0x4E454B4F
    MEDIA_TYPES = ["All", "Anime", "Manga", "Novels"]
    STATUSES = ["All", "Finished", "Releasing", "Not Yet Released", "Cancelled", "Hiatus"]
    SEASONS = ["All", "Winter", "Spring", "Summer", "Fall"]
    SORTS = ["Relevance", "Popularity", "Score", "Newest", "Oldest", "Title A–Z", "Title Z–A"]
    SCORES = ["Any score", "50+", "60+", "70+", "80+", "90+"]
    LICENSING = ["Any licensing", "Licensed only", "Unlicensed only"]
    YEAR_VALUES = [
        "", " 2020 ", "202", "20200", "abcd", "0000", "9999",
        "1e30", "NaN", "２０２０", "2020\n", "١٩٩٩",
    ]
    TEXT_VALUES = [
        "", " Fantasy, Action ", "Isekai", "x" * 4096, "a,b,,c",
        "<script>alert(1)</script>", "雪と魔法", "  ", "genre/tag\tvalue",
    ]
    PUBLISHER_VALUES = ["", "0", "1", "123456", "-1", "1.5", "1" * 1000, " 123 "]

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        MemorySettings.stores = {
            ("NekoTrack", "NekoTrack"): {
                preferences._MIGRATION_KEY: True,
                "_bundle_options_v1_migrated": True,
                "_theme_palette_version": preferences._THEME_PALETTE_VERSION,
                "theme_preset": "Neko",
            },
            ("AniTrack", "AniTrack"): {},
        }
        self.page = SearchPage(lambda *_args: None)

    def tearDown(self):
        self.page.close()
        self.page.deleteLater()
        self.app.processEvents()

    @staticmethod
    def _pick(combo, rng):
        if combo.count():
            combo.setCurrentIndex(rng.randrange(combo.count()))

    def _assert_filter_payload(self):
        filters = self.page.selected_filters()
        self.assertEqual(
            set(filters),
            {"format_filter", "status", "season", "year", "sort", "min_score",
             "genre", "tag", "publisher_id", "is_licensed"},
        )
        self.assertIn(filters["format_filter"], {
            None, "TV", "TV_SHORT", "MOVIE", "OVA", "ONA", "SPECIAL", "MUSIC",
            "MANGA", "NOVEL", "ONE_SHOT",
        })
        self.assertIn(filters["status"], {
            None, "FINISHED", "RELEASING", "NOT_YET_RELEASED", "CANCELLED", "HIATUS",
        })
        self.assertIn(filters["season"], {None, "WINTER", "SPRING", "SUMMER", "FALL"})
        self.assertTrue(
            filters["year"] is None
            or (isinstance(filters["year"], str) and len(filters["year"]) == 4
                and filters["year"].isdigit())
        )
        self.assertIn(filters["sort"], {
            "SEARCH_MATCH", "POPULARITY_DESC", "SCORE_DESC", "START_DATE_DESC",
            "START_DATE", "TITLE_ROMAJI", "TITLE_ROMAJI_DESC",
        })
        self.assertTrue(filters["min_score"] is None or filters["min_score"] in {50, 60, 70, 80, 90})
        self.assertIsInstance(filters["genre"], (str, type(None)))
        self.assertIsInstance(filters["tag"], (str, type(None)))
        self.assertTrue(filters["publisher_id"] is None or str(filters["publisher_id"]).isdigit())
        self.assertIn(filters["is_licensed"], {None, True, False})

        media_choice = self.page.media_filter.currentText()
        media_type, media_format = self.page.selected_media_filter()
        self.assertEqual(
            (media_type, media_format),
            {
                "All": (None, None),
                "Anime": ("ANIME", None),
                "Manga": ("MANGA", "MANGA"),
                "Novels": ("MANGA", "NOVEL"),
            }[media_choice],
        )

        fmt = self.page.format_filter.currentText()
        if media_choice == "Anime" or fmt in {
            "TV", "TV Short", "Movie", "OVA", "ONA", "Special", "Music",
        }:
            self.assertFalse(self.page.publisher_filter.isEnabled())
            self.assertFalse(self.page.licensing_filter.isEnabled())
            self.assertIsNone(filters["publisher_id"])
            self.assertIsNone(filters["is_licensed"])
        if media_choice in {"Manga", "Novels"} or fmt in {"Manga", "Novel", "One Shot"}:
            self.assertFalse(self.page.season_filter.isEnabled())
            self.assertEqual(self.page.season_filter.currentText(), "All")
            self.assertIsNone(filters["season"])

    def test_random_filter_changes_never_produce_invalid_state_or_start_search(self):
        rng = random.Random(_fuzz_seed(self.SEED))
        iterations = 180

        for case in range(iterations):
            with self.subTest(case=case):
                self._pick(self.page.media_filter, rng)
                self._pick(self.page.format_filter, rng)
                self._pick(self.page.status_filter, rng)
                self._pick(self.page.season_filter, rng)
                self._pick(self.page.min_score_filter, rng)
                self._pick(self.page.sort_filter, rng)
                self._pick(self.page.licensing_filter, rng)

                self.page.year_filter.setText(rng.choice(self.YEAR_VALUES))
                self.page.genre_filter.setText(rng.choice(self.TEXT_VALUES))
                self.page.tag_filter.setText(rng.choice(self.TEXT_VALUES))
                self.page.publisher_filter.setText(rng.choice(self.PUBLISHER_VALUES))
                self.page.fast_search.setChecked(bool(rng.getrandbits(1)))

                self._assert_filter_payload()
                self.assertFalse(self.page.has_searched)
                self.assertFalse(self.page.is_loading)
                self.assertEqual(self.page.search_threads, [])
                self.assertEqual(self.page.search_workers, [])

                if rng.randrange(12) == 0:
                    self.page.clear_filters()
                    self.assertEqual(self.page.media_filter.currentText(), "All")
                    self.assertEqual(self.page.format_filter.currentText(), "All")
                    self.assertEqual(self.page.status_filter.currentText(), "All")
                    self.assertEqual(self.page.season_filter.currentText(), "All")
                    self.assertEqual(self.page.year_filter.text(), "")
                    self.assertEqual(self.page.genre_filter.text(), "")
                    self.assertEqual(self.page.tag_filter.text(), "")
                    self.assertEqual(self.page.publisher_filter.text(), "")
                    self.assertEqual(self.page.min_score_filter.currentText(), "Any score")
                    self.assertEqual(self.page.sort_filter.currentText(), "Relevance")
                    self.assertEqual(self.page.licensing_filter.currentText(), "Any licensing")
                    self._assert_filter_payload()

        self.app.processEvents()
        self.assertFalse(self.page.has_searched)
        self.assertEqual(self.page.search_threads, [])
