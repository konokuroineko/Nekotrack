"""Offline tests for database.py against a throwaway SQLite file."""

import database
from conftest import media, relation


class TestInitializeDatabase:
    def test_creates_tables(self, db_path):
        connection = database.get_connection()
        names = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        connection.close()
        for table in [
            "works", "work_relations", "user_library", "characters", "people",
            "work_characters", "character_voice_actors", "work_staff",
            "alternate_titles", "studios", "work_studios", "episodes",
            "songs", "work_songs",
        ]:
            assert table in names

    def test_migration_columns_exist(self, db_path):
        connection = database.get_connection()
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(works)").fetchall()
        }
        connection.close()
        for column in ["format", "cover_path", "chapters", "volumes", "source", "end_year", "duration"]:
            assert column in columns

    def test_idempotent(self, db_path):
        database.initialize_database()
        database.initialize_database()


class TestSaveAnime:
    def test_insert_and_upsert(self, db_path):
        database.save_anime(media(1, "Cowboy Bebop", year=1998, episodes=26))
        row = database.get_work(1)
        assert row["title"] == "Cowboy Bebop"
        assert row["start_year"] == 1998
        assert row["episodes"] == 26
        assert row["format"] == "TV"

        updated = media(1, "Cowboy Bebop", year=1998, episodes=26)
        updated["averageScore"] = 90
        database.save_anime(updated)
        assert database.get_work(1)["score"] == 90

    def test_synonyms_saved(self, db_path):
        database.save_anime(media(1, "A", synonyms=["Alternate One", "Alternate Two"]))
        connection = database.get_connection()
        titles = [
            row["title"]
            for row in connection.execute(
                "SELECT title FROM alternate_titles WHERE work_id = 1 ORDER BY title"
            ).fetchall()
        ]
        connection.close()
        assert titles == ["Alternate One", "Alternate Two"]

    def test_studios_saved(self, db_path):
        payload = media(1, "A")
        payload["studios"] = {
            "edges": [
                {"isMain": True, "node": {"id": 10, "name": "Studio Bones"}},
                {"isMain": False, "node": {"id": 11, "name": "Aniplex"}},
            ]
        }
        database.save_anime(payload)
        connection = database.get_connection()
        studios = connection.execute(
            "SELECT s.name, s.is_main FROM studios s "
            "JOIN work_studios ws ON ws.studio_id = s.id WHERE ws.work_id = 1"
        ).fetchall()
        connection.close()
        assert {row["name"]: row["is_main"] for row in studios} == {
            "Studio Bones": 1,
            "Aniplex": 0,
        }

    def test_relations_saved_with_bidirectional_rows(self, db_path):
        database.save_anime(
            media(2, "Sequel", year=2010, relations=[relation(1, title="Original")])
        )
        rows = database.get_relations(2)
        assert len(rows) == 1
        assert rows[0]["relation_type"] == "SEQUEL"
        assert rows[0]["target_id"] == 1
        assert rows[0]["title"] == "Original"


class TestEpisodes:
    def test_save_and_list(self, db_path):
        database.save_episodes(
            1,
            [
                {"episodeNumber": 1, "title": "First", "airdate": "2020-01-01"},
                {"episodeNumber": 2, "title": "Second", "airdate": "2020-01-08"},
            ],
        )
        episodes = database.get_episodes(1)
        assert [ep["episode_number"] for ep in episodes] == [1, 2]
        assert episodes[0]["title"] == "First"

    def test_upsert_no_duplicates(self, db_path):
        database.save_episodes(1, [{"episodeNumber": 1, "title": "Old"}])
        database.save_episodes(1, [{"episodeNumber": 1, "title": "New", "airdate": "2020-02-02"}])
        episodes = database.get_episodes(1)
        assert len(episodes) == 1
        assert episodes[0]["title"] == "New"

    def test_skips_missing_episode_number(self, db_path):
        database.save_episodes(1, [{"title": "No number"}])
        assert database.get_episodes(1) == []

    def test_set_episode_watched_updates_status_to_completed(self, db_path):
        database.save_anime(media(1, "A", year=2020, episodes=2))
        database.add_to_library(1, "Planning")
        database.save_episodes(1, [{"episodeNumber": 1}, {"episodeNumber": 2}])
        database.set_episode_watched(1, 1, True)
        assert database.get_work(1)["status"] == "Watching"
        database.set_episode_watched(1, 2, True)
        assert database.get_work(1)["status"] == "Completed"
        assert database.get_work(1)["progress_episodes"] == 2

    def test_set_episode_progress_clamps_and_syncs(self, db_path):
        database.save_anime(media(1, "A", year=2020, episodes=5))
        database.add_to_library(1, "Planning")
        database.save_episodes(1, [{"episodeNumber": n} for n in range(1, 6)])
        database.set_episode_progress(1, 99)
        row = database.get_work(1)
        assert row["progress_episodes"] == 5
        assert row["status"] == "Completed"
        watched = [ep["watched"] for ep in database.get_episodes(1)]
        assert watched == [1, 1, 1, 1, 1]
        database.set_episode_progress(1, 0)
        assert database.get_work(1)["status"] == "Planning"

    def test_set_episode_progress_missing_library_is_noop(self, db_path):
        database.save_anime(media(1, "A", year=2020, episodes=5))
        database.set_episode_progress(1, 3)  # never added to the library
        assert database.get_work(1)["progress_episodes"] is None


class TestLibrary:
    def test_add_and_filter_by_status(self, db_path):
        database.save_anime(media(1, "Watching Show", year=2020))
        database.save_anime(media(2, "Planned Show", year=2021))
        database.add_to_library(1, "Watching")
        database.add_to_library(2, "Planning")
        assert [row["id"] for row in database.get_library_by_status("Watching")] == [1]
        assert [row["id"] for row in database.get_library_by_status("Planning")] == [2]

    def test_all_library_ordered_newest_first(self, db_path):
        database.save_anime(media(1, "Old", year=2010))
        database.save_anime(media(2, "New", year=2011))
        database.add_to_library(1, "Planning")
        database.add_to_library(2, "Planning")
        rows = database.get_all_library()
        assert [row["id"] for row in rows] == [2, 1]

    def test_relation_type_counts(self, db_path):
        database.save_anime(
            media(3, "Three", year=2010, relations=[relation(1, title="One"), relation(2, "PREQUEL", title="Two")])
        )
        counts = {row["relation_type"]: row["count"] for row in database.get_relation_type_counts()}
        assert counts == {"SEQUEL": 1, "PREQUEL": 1}


class TestSavedAnime:
    def test_get_saved_anime_sorted_by_title(self, db_path):
        database.save_anime(media(1, "Zeta", year=2020))
        database.save_anime(media(2, "Alpha", year=2020))
        rows = database.get_saved_anime()
        assert [row["title"] for row in rows] == ["Alpha", "Zeta"]

    def test_get_work_left_join_returns_library_fields(self, db_path):
        database.save_anime(media(1, "A", year=2020))
        database.add_to_library(1, "Watching")
        row = database.get_work(1)
        assert row["status"] == "Watching"
        assert row["progress_episodes"] == 0

    def test_get_work_missing_returns_none(self, db_path):
        assert database.get_work(999) is None