"""Tests for the shared logical-season counting implementation."""

import sqlite3

from season_count import _get, _is_arc, _is_continuation, _season_marker, logical_season_count


def tv(title, media_id, relations=None, year=2020, month=1):
    return {
        "id": media_id,
        "title": {"romaji": title, "english": None, "native": None},
        "format": "TV",
        "type": "ANIME",
        "startDate": {"year": year, "month": month, "day": 1},
        "relations": {"edges": relations or []},
    }


def movie(title, media_id):
    return {
        "id": media_id,
        "title": {"romaji": title, "english": None, "native": None},
        "format": "MOVIE",
        "type": "ANIME",
        "startDate": {"year": 2020, "month": 1, "day": 1},
        "relations": {"edges": []},
    }


def edge(target_id):
    return {"relationType": "SEQUEL", "node": {"id": target_id}}


class TestSeasonMarker:
    def test_ordinal_season(self):
        assert _season_marker("Mobile Suit Gundam 3rd Season") == "season-3"

    def test_word_ordinal_season(self):
        assert _season_marker("The Second Season") == "season-2"

    def test_numbered_season(self):
        assert _season_marker("Fate/Zero Season 2") == "season-2"

    def test_roman_season(self):
        assert _season_marker("Sword Art Online III") == "season-3"
        assert _season_marker("Psycho-Pass 2") == "season-2"

    def test_final_season(self):
        assert _season_marker("Attack on Titan: The Final Season") == "final"

    def test_bare_trailing_number(self):
        assert _season_marker("Tokyo Ghoul:re 2") == "season-2"

    def test_part_suffix_is_not_a_season(self):
        # Regression: "Boruto ... Part 2" is a continuation, not Season 2.
        assert _season_marker("Boruto: Naruto Next Generations Part 2") is None

    def test_no_marker(self):
        assert _season_marker("Attack on Titan") is None


class TestContinuationAndArc:
    def test_part_continuation(self):
        assert _is_continuation("Bleach: Thousand-Year Blood War Part 2")

    def test_final_season_is_continuation(self):
        assert _is_continuation("Shingeki no Kyojin: The Final Season")

    def test_plain_title_not_continuation(self):
        assert not _is_continuation("Cowboy Bebop")

    def test_arc(self):
        assert _is_arc("Bleach: The Thousand-Year Blood War Arc")
        assert not _is_arc("Cowboy Bebop")


class TestLogicalSeasonCount:
    def test_empty(self):
        assert logical_season_count([]) == 0

    def test_non_tv_ignored(self):
        assert logical_season_count([movie("A Movie", 1)]) == 0
        assert logical_season_count([]) == 0

    def test_plain_titles_are_separate(self):
        members = [tv("Attack on Titan", 1), tv("Attack on Titan Season 2", 2)]
        assert logical_season_count(members) == 2

    def test_explicit_markers_break_groups(self):
        members = [
            tv("Attack on Titan", 1),
            tv("Attack on Titan Season 2", 2),
            tv("Attack on Titan Season 3", 3),
        ]
        assert logical_season_count(members) == 3

    def test_continuation_inherits_neighbor(self):
        members = [
            tv("Bleach", 1),
            tv("Bleach Part 2", 2, relations=[edge(1)]),
        ]
        assert logical_season_count(members) == 1

    def test_continuation_never_crosses_markers(self):
        members = [
            tv("X Season 2", 2),
            tv("X Part 2", 3, relations=[edge(2)]),
        ]
        # Part 2 has no marker, its neighbor has season-2; they must not merge.
        assert logical_season_count(members) == 2

    def test_same_marker_union(self):
        members = [
            tv("The Final Season Part 1", 1),
            tv("The Final Season Part 2", 2, relations=[edge(1)]),
        ]
        # Both carry the "final" marker: continuation merges them into one season.
        assert logical_season_count(members) == 1

    def test_arcs_same_airing_season_merge(self):
        members = [
            tv("Fate Arc A", 1, year=2014, month=10),
            tv("Fate Arc B", 2, year=2014, month=11, relations=[edge(1)]),
        ]
        assert logical_season_count(members) == 1

    def test_arcs_different_airing_seasons_stay_split(self):
        members = [
            tv("Fate Arc A", 1, year=2014, month=10),
            tv("Fate Arc B", 2, year=2015, month=1, relations=[edge(1)]),
        ]
        assert logical_season_count(members) == 2

    def test_row_factory_members(self):
        """Regression: library rows are sqlite3.Row objects without .get()."""
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute(
            "CREATE TABLE works (id INTEGER PRIMARY KEY, title TEXT, format TEXT, start_year INTEGER)"
        )
        connection.execute(
            "CREATE TABLE relations (source_id INTEGER, target_id INTEGER, relation_type TEXT)"
        )
        connection.execute(
            "INSERT INTO works VALUES (1, 'Attack on Titan', 'TV', 2013)"
        )
        connection.execute(
            "INSERT INTO works VALUES (2, 'Attack on Titan Season 2', 'TV', 2017)"
        )
        connection.execute(
            "INSERT INTO works VALUES (3, 'Attack on Titan: The Final Season', 'TV', 2020)"
        )
        connection.execute("INSERT INTO relations VALUES (1, 2, 'SEQUEL')")
        connection.execute("INSERT INTO relations VALUES (2, 3, 'SEQUEL')")
        rows = connection.execute("SELECT * FROM works").fetchall()
        assert not hasattr(rows[0], "get")
        assert logical_season_count(rows) == 3


class TestGetHelper:
    def test_dict(self):
        assert _get({"a": 1}, "a") == 1
        assert _get({"a": 1}, "b", "fallback") == "fallback"

    def test_row(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT 7 AS a").fetchone()
        assert _get(row, "a") == 7
        assert _get(row, "missing", "fallback") == "fallback"

    def test_none(self):
        assert _get(None, "x", "fallback") == "fallback"