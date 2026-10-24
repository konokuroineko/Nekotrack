"""Regression coverage for TMDB token sharing and episode matching."""

import datetime
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import api
import database


class TMDBEpisodeMatchingTests(unittest.TestCase):
    def test_app_token_takes_precedence_over_per_user_token(self):
        with patch.dict(os.environ, {"NEKOTRACK_TMDB_ACCESS_TOKEN": " shared-token "}), patch(
            "api.get", return_value="user-token"
        ):
            self.assertEqual(api.get_tmdb_access_token(), "shared-token")

    def test_saved_user_token_remains_a_fallback_for_local_development(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "api.get", return_value="local-token"
        ):
            self.assertEqual(api.get_tmdb_access_token(), "local-token")

    def test_title_matching_supports_native_japanese_titles(self):
        native_title = "葬送のフリーレン"
        candidate = {
            "id": 311,
            "name": native_title,
            "original_name": native_title,
        }
        self.assertEqual(api._candidate_title_similarity(candidate, [native_title]), 1.0)

    def test_tv_search_retries_without_year_when_filtered_results_are_unrelated(self):
        unrelated = {
            "results": [{
                "id": 101,
                "name": "Unrelated Japanese Series",
                "original_name": "Unrelated Japanese Series",
                "first_air_date": "2020-01-01",
                "origin_country": ["JP"],
                "popularity": 100,
            }]
        }
        correct = {
            "results": [{
                "id": 202,
                "name": "Example Show",
                "original_name": "Example Show",
                "first_air_date": "2020-01-05",
                "origin_country": ["JP"],
                "popularity": 1,
            }]
        }
        with patch("api._tmdb_get", side_effect=[unrelated, correct]) as request:
            result = api._find_tmdb_series(
                ["Example Show"], datetime.date(2020, 1, 5)
            )

        self.assertEqual(result["id"], 202)
        self.assertEqual(request.call_count, 2)
        self.assertIn("first_air_date_year", request.call_args_list[0].args[1])

    def test_tv_search_skips_duplicate_exact_title_queries(self):
        payload = {
            "results": [{
                "id": 909,
                "name": "Example Show",
                "original_name": "Example Show",
                "first_air_date": "2020-01-05",
                "origin_country": ["JP"],
                "popularity": 1,
            }]
        }
        with patch("api._tmdb_get", return_value=payload) as request:
            result = api._find_tmdb_series(
                ["Example Show", "Example Show", " Example Show "],
                datetime.date(2020, 1, 5),
            )

        self.assertEqual(result["id"], 909)
        self.assertEqual(request.call_count, 1)

    def test_movie_search_skips_duplicate_exact_title_queries(self):
        payload = {
            "results": [{
                "id": 910,
                "title": "Example OVA",
                "original_title": "Example OVA",
                "release_date": "2020-01-05",
                "popularity": 1,
            }]
        }
        with patch("api._tmdb_get", return_value=payload) as request:
            result = api._find_tmdb_movie(
                ["Example OVA", "Example OVA", " Example OVA "],
                datetime.date(2020, 1, 5),
            )

        self.assertEqual(result["id"], 910)
        self.assertEqual(request.call_count, 1)

    def test_tv_search_refuses_to_choose_a_popular_but_unrelated_series(self):
        unrelated = {
            "results": [{
                "id": 101,
                "name": "Completely Different Show",
                "original_name": "Completely Different Show",
                "first_air_date": "2020-01-01",
                "origin_country": ["JP"],
                "popularity": 100,
            }]
        }
        with patch("api._tmdb_get", side_effect=[unrelated, unrelated]):
            with self.assertRaisesRegex(RuntimeError, "closely matched"):
                api._find_tmdb_series(
                    ["Example Show"], datetime.date(2020, 1, 5)
                )

    def test_season_selection_uses_date_boundary_count_and_specials_penalty(self):
        details = {
            "seasons": [
                {"season_number": 0, "air_date": "2020-01-03", "episode_count": 1},
                {"season_number": 1, "air_date": "2020-01-12", "episode_count": 12},
                {"season_number": 2, "air_date": "2021-01-02", "episode_count": 12},
            ]
        }
        selected = api._find_tmdb_season(
            details,
            datetime.date(2020, 1, 5),
            datetime.date(2021, 1, 1),
            12,
        )
        self.assertEqual(selected["season_number"], 1)

    def test_missing_start_date_uses_a_cached_tmdb_mapping(self):
        season_payload = {
            "episodes": [
                {
                    "id": 1, "episode_number": 1, "name": "Dated Episode",
                    "overview": "", "air_date": "2020-01-01", "still_path": None,
                },
                {
                    "id": 2, "episode_number": 2, "name": "Undated Episode",
                    "overview": "", "air_date": None, "still_path": None,
                },
            ]
        }
        with patch("api._tmdb_get", return_value=season_payload) as request, patch(
            "api._pick_best_episode_still", return_value=(None, 0)
        ):
            data = api.get_tmdb_episode_data(
                ["Example Show"], None, tmdb_id=99, tmdb_season_number=1
            )

        request.assert_called_once_with(
            "/tv/99/season/1", {"language": "en-US"}
        )
        self.assertEqual(
            [item["episodeNumber"] for item in data["episodes"]], [1, 2]
        )

    def test_missing_start_date_can_match_series_and_select_by_episode_count(self):
        series_payload = {
            "seasons": [
                {"season_number": 1, "air_date": "2020-01-01", "episode_count": 12},
                {"season_number": 2, "air_date": "2021-01-01", "episode_count": 24},
            ]
        }
        season_payload = {
            "episodes": [
                {
                    "id": 1, "episode_number": 1, "name": "Episode One",
                    "overview": "", "air_date": "2020-01-01", "still_path": None,
                }
            ]
        }
        with patch("api._find_tmdb_series", return_value={"id": 99}) as find_series, patch(
            "api._tmdb_get", side_effect=[series_payload, season_payload]
        ) as request, patch("api._pick_best_episode_still", return_value=(None, 0)):
            data = api.get_tmdb_episode_data(
                ["Example Show"], None, expected_episodes=12
            )

        find_series.assert_called_once_with(["Example Show"], None)
        self.assertEqual(data["tmdb_season_number"], 1)
        self.assertEqual([item["episodeNumber"] for item in data["episodes"]], [1])
        self.assertEqual(
            [call.args[0] for call in request.call_args_list],
            ["/tv/99", "/tv/99/season/1"],
        )

    def test_tv_episode_parser_rejects_fractional_boolean_and_duplicate_numbers(self):
        season_payload = {
            "episodes": [
                {
                    "id": 1, "episode_number": True, "name": "Boolean Number",
                    "overview": "", "air_date": None, "still_path": None,
                },
                {
                    "id": 2, "episode_number": 1.5, "name": "Fractional Number",
                    "overview": "", "air_date": None, "still_path": None,
                },
                {
                    "id": 3, "episode_number": 0, "name": "Zero Number",
                    "overview": "", "air_date": None, "still_path": None,
                },
                {
                    "id": 4, "episode_number": "1", "name": "Valid Episode",
                    "overview": "", "air_date": None, "still_path": None,
                },
                {
                    "id": 5, "episode_number": 1, "name": "Duplicate Episode",
                    "overview": "", "air_date": None, "still_path": None,
                },
                {
                    "id": 6, "episode_number": 1_000_001, "name": "Unreasonable Number",
                    "overview": "", "air_date": None, "still_path": None,
                },
            ]
        }
        with patch("api._tmdb_get", return_value=season_payload), patch(
            "api._pick_best_episode_still", return_value=(None, 0)
        ):
            data = api.get_tmdb_episode_data(
                ["Example Show"], None, tmdb_id=99, tmdb_season_number=1
            )

        self.assertEqual(
            [(item["episodeNumber"], item["title"]) for item in data["episodes"]],
            [(1, "Valid Episode")],
        )

    def test_selected_season_keeps_undated_entries_and_does_not_truncate(self):
        season_payload = {
            "episodes": [
                {
                    "id": 1, "episode_number": 1, "name": "Before AniList Start",
                    "overview": "Valid episode", "air_date": "2020-09-28",
                    "still_path": None, "episode_type": "standard",
                },
                {
                    "id": 2, "episode_number": 2, "name": "Undated Episode",
                    "overview": "No source date", "air_date": None,
                    "still_path": None, "episode_type": "standard",
                },
                {
                    "id": 3, "episode_number": 3, "name": "After Next AniList Entry",
                    "overview": "", "air_date": "2021-04-01",
                    "still_path": None, "episode_type": "standard",
                },
                {
                    "id": 4, "episode_number": 4, "name": "In Range Episode 4",
                    "overview": "Valid episode", "air_date": "2020-11-01",
                    "still_path": None, "episode_type": "standard",
                },
                {
                    "id": 5, "episode_number": 5, "name": "In Range Episode 5",
                    "overview": "Valid episode", "air_date": "2020-12-01",
                    "still_path": None, "episode_type": "standard",
                },
            ]
        }
        with patch("api._tmdb_get", return_value=season_payload) as request, patch(
            "api._pick_best_episode_still", return_value=(None, 0)
        ):
            data = api.get_tmdb_episode_data(
                ["Example Show"],
                "2020-10-01",
                "2021-03-01",
                expected_episodes=2,
                tmdb_id=99,
                tmdb_season_number=1,
            )

        request.assert_called_once_with("/tv/99/season/1", {"language": "en-US"})
        self.assertEqual([item["episodeNumber"] for item in data["episodes"]], [2, 3, 4, 5])
        self.assertIsNone(data["episodes"][0]["airdate"])
        self.assertEqual(data["tmdb_count"], 4)

    def test_malformed_episode_air_date_is_kept_as_undated(self):
        season_payload = {
            "episodes": [
                {
                    "id": 51, "episode_number": 7, "name": "Episode With Bad Date",
                    "overview": "Keep this catalog entry", "air_date": "not-a-date",
                    "still_path": None,
                },
            ]
        }
        with patch("api._tmdb_get", return_value=season_payload), patch(
            "api._pick_best_episode_still", return_value=(None, 0)
        ):
            data = api.get_tmdb_episode_data(
                ["Example Show"], "2020-10-01", "2021-03-01",
                expected_episodes=1, tmdb_id=99, tmdb_season_number=1,
            )

        self.assertEqual(len(data["episodes"]), 1)
        self.assertEqual(data["episodes"][0]["episodeNumber"], 7)
        self.assertIsNone(data["episodes"][0]["airdate"])
        self.assertEqual(data["episodes"][0]["title"], "Episode With Bad Date")

    def test_cached_episode_artwork_paths_are_absolute_and_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            url = "https://image.tmdb.org/t/p/w500/example-still.jpg"
            response = MagicMock()
            with (
                patch.object(api, "TMDB_EPISODE_CACHE_DIRECTORY", Path(directory)),
                patch("api._get_tmdb_episode_image_response", return_value=response) as download,
                patch("api._read_bounded_tmdb_image_response", return_value=b"fake-image"),
                patch("api._valid_image_data", return_value=True),
            ):
                local_path = api.cache_tmdb_episode_image(url, 99, 2)

                self.assertTrue(Path(local_path).is_absolute())
                self.assertTrue(Path(local_path).is_file())
                second_path = api.cache_tmdb_episode_image(url, 99, 2)

            self.assertEqual(second_path, local_path)
            download.assert_called_once_with(url)
            response.close.assert_called_once()

    def test_catalog_pruning_removes_stale_rows_but_preserves_watched_state(self):
        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                database.initialize_database()
                work_id = 921
                database.save_anime({
                    "id": work_id,
                    "type": "ANIME",
                    "format": "TV",
                    "episodes": 3,
                    "title": {"english": "Example Show", "romaji": "Example Show", "native": None},
                    "coverImage": {"large": None},
                    "startDate": {"year": 2020, "month": 1, "day": 1},
                })
                database.add_to_library(work_id)
                database.save_episodes(work_id, [
                    {"episodeNumber": 1, "title": "Episode 1", "airdate": "2020-01-01"},
                    {"episodeNumber": 2, "title": "Episode 2", "airdate": "2020-01-08"},
                    {"episodeNumber": 3, "title": "Stale Episode 3", "airdate": "2020-01-15"},
                ])
                connection = database.get_connection()
                try:
                    connection.execute(
                        "UPDATE episodes SET watched = 1 WHERE work_id = ? AND episode_number IN (1, 3)",
                        (work_id,),
                    )
                    connection.execute(
                        "UPDATE user_library SET progress_episodes = 3 WHERE work_id = ?",
                        (work_id,),
                    )
                    connection.commit()
                finally:
                    connection.close()
                database.set_release_reminder(work_id, 3, True)

                removed = database.prune_episode_catalog(work_id, [
                    {"episodeNumber": 1, "title": "Correct Episode 1"},
                    {"episodeNumber": 2, "title": "Correct Episode 2"},
                ])

                self.assertEqual(removed, 1)
                episodes = database.get_episodes(work_id)
                self.assertEqual([row["episode_number"] for row in episodes], [1, 2])
                self.assertEqual(episodes[0]["watched"], 1)
                self.assertEqual(episodes[1]["watched"], 0)
                connection = database.get_connection()
                try:
                    progress = connection.execute(
                        "SELECT progress_episodes FROM user_library WHERE work_id = ?",
                        (work_id,),
                    ).fetchone()["progress_episodes"]
                    reminders = connection.execute(
                        "SELECT COUNT(*) AS amount FROM release_reminders WHERE work_id = ?",
                        (work_id,),
                    ).fetchone()["amount"]
                finally:
                    connection.close()
                self.assertEqual(progress, 2)
                self.assertEqual(reminders, 0)
            finally:
                os.chdir(previous_cwd)

    def test_bulk_progress_updates_noncontiguous_episode_ids(self):
        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                database.initialize_database()
                work_id = 923
                database.save_anime({
                    "id": work_id,
                    "type": "ANIME",
                    "format": "TV",
                    "episodes": 3,
                    "title": {"english": "Example Show", "romaji": "Example Show", "native": None},
                    "coverImage": {"large": None},
                    "startDate": {"year": 2020, "month": 1, "day": 1},
                })
                database.add_to_library(work_id)
                database.save_episodes(work_id, [
                    {"episodeNumber": 1, "title": "Episode 1"},
                    {"episodeNumber": 3, "title": "Episode 3"},
                    {"episodeNumber": 5, "title": "Episode 5"},
                ])

                watched_count, total = database.set_episode_progress(work_id, [1, 5])

                self.assertEqual((watched_count, total), (2, 3))
                rows = database.get_episodes(work_id)
                self.assertEqual([row["episode_number"] for row in rows], [1, 3, 5])
                self.assertEqual([row["watched"] for row in rows], [1, 0, 1])
                connection = database.get_connection()
                try:
                    library = connection.execute(
                        "SELECT progress_episodes, status FROM user_library WHERE work_id = ?",
                        (work_id,),
                    ).fetchone()
                finally:
                    connection.close()
                self.assertEqual(library["progress_episodes"], 2)
                self.assertEqual(library["status"], "Watching")
            finally:
                os.chdir(previous_cwd)

    def test_bulk_progress_uses_bounded_set_updates_and_one_count_query(self):
        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                database.initialize_database()
                work_id = 924
                database.save_anime({
                    "id": work_id,
                    "type": "ANIME",
                    "format": "TV",
                    "episodes": 600,
                    "title": {
                        "english": "Progress Benchmark",
                        "romaji": "Progress Benchmark",
                        "native": None,
                    },
                    "coverImage": {"large": None},
                    "startDate": {"year": 2020, "month": 1, "day": 1},
                })
                database.add_to_library(work_id)
                database.save_episodes(work_id, [
                    {"episodeNumber": number, "title": f"Episode {number}"}
                    for number in range(1, 601)
                ])

                statements = []
                real_get_connection = database.get_connection

                def traced_connection():
                    connection = real_get_connection()
                    connection.set_trace_callback(statements.append)
                    return connection

                with patch.object(
                    database, "get_connection", side_effect=traced_connection
                ):
                    self.assertEqual(
                        database.set_episode_progress(work_id, range(1, 451)),
                        (450, 600),
                    )

                episode_updates = [
                    sql for sql in statements
                    if sql.lstrip().upper().startswith("UPDATE EPISODES")
                ]
                keep_set_inserts = [
                    sql for sql in statements
                    if sql.lstrip().upper().startswith(
                        "INSERT OR IGNORE INTO _EPISODE_PROGRESS_WATCHED_NUMBERS"
                    )
                ]
                episode_count_reads = [
                    sql for sql in statements
                    if sql.lstrip().upper().startswith("SELECT COUNT(*)")
                    and "FROM EPISODES" in sql.upper()
                ]
                self.assertEqual(len(episode_updates), 1)
                self.assertEqual(len(keep_set_inserts), 2)
                self.assertEqual(len(episode_count_reads), 1)

                rows = database.get_episodes(work_id)
                self.assertEqual(len(rows), 600)
                self.assertEqual(sum(int(row["watched"]) for row in rows), 450)
                self.assertEqual(int(rows[449]["watched"]), 1)
                self.assertEqual(int(rows[450]["watched"]), 0)

                statements.clear()
                with patch.object(
                    database, "get_connection", side_effect=traced_connection
                ):
                    self.assertEqual(
                        database.set_episode_watched(work_id, 451, True),
                        (451, 600),
                    )
                episode_count_reads = [
                    sql for sql in statements
                    if sql.lstrip().upper().startswith("SELECT COUNT(*)")
                    and "FROM EPISODES" in sql.upper()
                ]
                self.assertEqual(len(episode_count_reads), 1)
                self.assertFalse(any(
                    "SELECT 1 FROM USER_LIBRARY" in sql.upper()
                    for sql in statements
                ))
            finally:
                os.chdir(previous_cwd)

    def test_empty_catalog_never_prunes_existing_episode_data(self):
        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                database.initialize_database()
                work_id = 922
                database.save_anime({
                    "id": work_id,
                    "type": "ANIME",
                    "format": "TV",
                    "episodes": 1,
                    "title": {"english": "Example Show", "romaji": "Example Show", "native": None},
                    "coverImage": {"large": None},
                    "startDate": {"year": 2020, "month": 1, "day": 1},
                })
                database.save_episodes(work_id, [
                    {"episodeNumber": 1, "title": "Existing Episode"},
                ])
                self.assertEqual(database.prune_episode_catalog(work_id, []), 0)
                self.assertEqual(len(database.get_episodes(work_id)), 1)
            finally:
                os.chdir(previous_cwd)


if __name__ == "__main__":
    unittest.main()
