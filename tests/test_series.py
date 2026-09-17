"""Tests for series grouping over the local SQLite library (offline)."""


import database
import series
from conftest import media, relation


def seed(db_path, *works):
    """Save works then add each to the library."""
    for work in works:
        database.save_anime(work)
        database.add_to_library(work["id"], "Planning")
    return works


class TestGetLibrarySeries:
    def test_empty_library(self, db_path):
        assert series.get_library_series() == []

    def test_single_work(self, db_path):
        seed(db_path, media(1, "Cowboy Bebop", year=1998, episodes=26))
        groups = series.get_library_series()
        assert len(groups) == 1
        assert groups[0]["_series_count"] == 1
        assert groups[0]["_series_episode_total"] == 26
        assert groups[0]["_series_progress"] == 0
        assert groups[0]["_bundle_summary"] == ""

    def test_relation_bundle_no_crash(self, db_path):
        """Regression: sqlite3.Row members crashed logical_season_count."""
        seed(
            db_path,
            media(1, "Attack on Titan", year=2013, episodes=25),
            media(2, "Attack on Titan Season 2", year=2017, episodes=12, relations=[relation(1, title="Attack on Titan")]),
        )
        groups = series.get_library_series()
        assert len(groups) == 1
        group = groups[0]
        assert group["_series_count"] == 2
        assert group["_series_episode_total"] == 37
        assert "2 seasons" in group["_bundle_summary"]

    def test_title_key_bundle_without_edges(self, db_path):
        seed(
            db_path,
            media(1, "Spice and Wolf", year=2008, episodes=13),
            media(2, "Spice and Wolf Season 2", year=2009, episodes=12),
        )
        groups = series.get_library_series()
        assert len(groups) == 1
        assert groups[0]["_series_count"] == 2

    def test_status_rollup_watching_wins(self, db_path):
        database.save_anime(media(1, "A", year=2020, episodes=12))
        database.save_anime(media(2, "A Season 2", year=2021, episodes=12))
        database.add_to_library(1, "Completed")
        database.add_to_library(2, "Watching")
        groups = series.get_library_series()
        assert groups[0]["status"] == "Watching"

    def test_status_rollup_all_completed(self, db_path):
        for work_id, title, year in [(1, "A", 2020), (2, "A Season 2", 2021)]:
            database.save_anime(media(work_id, title, year=year, episodes=12))
            database.add_to_library(work_id, "Completed")
        groups = series.get_library_series()
        assert groups[0]["status"] == "Completed"

    def test_status_rollup_planning_default(self, db_path):
        database.save_anime(media(1, "A", year=2020, episodes=12))
        database.save_anime(media(2, "A Season 2", year=2021, episodes=12))
        database.add_to_library(1, "Completed")
        database.add_to_library(2, "Planning")
        groups = series.get_library_series()
        assert groups[0]["status"] == "Planning"

    def test_bundle_summary_counts_ova_and_movie(self, db_path):
        seed(
            db_path,
            media(1, "Franchise", year=2000, episodes=24),
            media(2, "Franchise OVA", year=2001, media_format="OVA", episodes=None, relations=[relation(1, title="Franchise")]),
            media(3, "Franchise Movie", year=2002, media_format="MOVIE", episodes=None, relations=[relation(1, title="Franchise")]),
        )
        groups = series.get_library_series()
        assert len(groups) == 1
        summary = groups[0]["_bundle_summary"]
        assert "1 OVA" in summary
        assert "1 movie" in summary

    def test_progress_sums_members(self, db_path):
        database.save_anime(media(1, "A", year=2020, episodes=12))
        database.save_anime(media(2, "A Season 2", year=2021, episodes=12))
        database.add_to_library(1, "Watching")
        database.add_to_library(2, "Watching")
        connection = database.get_connection()
        connection.execute(
            "UPDATE user_library SET progress_episodes = ? WHERE work_id = ?", (4, 1)
        )
        connection.execute(
            "UPDATE user_library SET progress_episodes = ? WHERE work_id = ?", (8, 2)
        )
        connection.commit()
        connection.close()
        groups = series.get_library_series()
        assert groups[0]["_series_progress"] == 12
        assert groups[0]["_series_episode_total"] == 24

    def test_members_sorted_by_start_year_within_group(self, db_path):
        seed(
            db_path,
            media(1, "Newer First Entry", year=2005),
            media(2, "Oldest Sequel", year=1990, relations=[relation(1, title="Newer First Entry")]),
        )
        groups = series.get_library_series()
        assert len(groups) == 1
        member_ids = [int(member["id"]) for member in groups[0]["_series_members"]]
        assert member_ids == [2, 1]


class TestSeriesKey:
    def test_strips_season_suffix(self):
        assert series._series_key("Attack on Titan Season 2") == series._series_key("Attack on Titan")

    def test_strips_final_season(self):
        assert series._series_key("Attack on Titan: The Final Season") == series._series_key("Attack on Titan")

    def test_strips_part_number(self):
        assert series._series_key("Bleach Part 2") == series._series_key("Bleach")

    def test_roman_numerals(self):
        assert series._series_key("Psycho Pass 2") == series._series_key("Psycho Pass")
        assert series._series_key("Sword Art Online II") == series._series_key("Sword Art Online")

    def test_punctuation_normalized(self):
        assert series._series_key("Spice and Wolf!") == series._series_key("Spice and Wolf")
        assert series._series_key("Spice & Wolf") == series._series_key("Spice Wolf")

    def test_empty_title(self):
        assert series._series_key("") == ""

    def test_bare_trailing_number_stripped(self):
        assert series._series_key("Tokyo Ghoul:re 2") == series._series_key("Tokyo Ghoul:re")