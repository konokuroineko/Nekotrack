import unittest
from unittest.mock import Mock, patch

import api


class AniListFilterTests(unittest.TestCase):
    @patch("api.anilist_request")
    def test_combined_filter_arguments_are_encoded_correctly(self, request):
        request.return_value = {
            "Page": {
                "pageInfo": {"currentPage": 1, "lastPage": 1, "hasNextPage": False},
                "media": [],
            }
        }
        api.search_anime(
            "", per_page=5, media_type="ANIME", format_filter="TV",
            status="FINISHED", season="WINTER", year="2020",
            sort="SCORE_DESC", min_score=80,
            genre="Action, Fantasy", tag="Isekai, Time Travel",
            include_relations=False,
        )
        query, variables = request.call_args.args
        self.assertIn("format_in: $formatFilter", query)
        self.assertIn("status: $status", query)
        self.assertIn("season: $season", query)
        self.assertIn("seasonYear: $seasonYear", query)
        self.assertEqual(variables["formatFilter"], ["TV"])
        self.assertEqual(variables["status"], "FINISHED")
        self.assertEqual(variables["season"], "WINTER")
        self.assertEqual(variables["seasonYear"], 2020)
        self.assertEqual(variables["minScore"], 79)
        self.assertEqual(variables["genres"], ["Action", "Fantasy"])
        self.assertEqual(variables["tags"], ["Isekai", "Time Travel"])
        self.assertEqual(variables["sort"], ["SCORE_DESC"])

    @patch("api.anilist_request")
    def test_year_without_season_uses_start_date_filter(self, request):
        request.return_value = {
            "Page": {
                "pageInfo": {"currentPage": 1, "lastPage": 1, "hasNextPage": False},
                "media": [],
            }
        }
        api.search_anime("", media_type="ANIME", year="2020", include_relations=False)
        query, variables = request.call_args.args
        self.assertIn("startDate_like: $year", query)
        self.assertEqual(variables["year"], "2020")
        self.assertNotIn("seasonYear", variables)

    @patch("api.anilist_request")
    def test_lightweight_results_include_fields_needed_to_verify_filters(self, request):
        request.return_value = {
            "Page": {
                "pageInfo": {"currentPage": 1, "lastPage": 1, "hasNextPage": False},
                "media": [],
            }
        }
        api.search_anime("", media_type="ANIME", include_relations=False)
        query = request.call_args.args[0]
        for field in ("status", "season", "seasonYear", "genres", "tags { name }"):
            self.assertIn(field, query)


    @patch("api.requests.get")
    def test_tmdb_connection_uses_bearer_auth_and_closes_response(self, request):
        response = Mock()
        request.return_value = response

        self.assertTrue(api.test_tmdb_connection("  example-token  "))

        request.assert_called_once_with(
            "https://api.themoviedb.org/3/configuration",
            headers={
                "Authorization": "Bearer example-token",
                "accept": "application/json",
            },
            timeout=10,
        )
        response.raise_for_status.assert_called_once_with()
        response.close.assert_called_once_with()

    @patch("api.requests.get")
    def test_tmdb_connection_closes_error_response(self, request):
        response = Mock()
        response.raise_for_status.side_effect = api.requests.HTTPError("unauthorized")
        request.return_value = response

        with self.assertRaises(api.requests.HTTPError):
            api.test_tmdb_connection("invalid-token")

        response.close.assert_called_once_with()

    def test_tmdb_connection_rejects_an_empty_token_without_network_access(self):
        with patch("api.requests.get") as request:
            with self.assertRaisesRegex(ValueError, "token is required"):
                api.test_tmdb_connection("  ")
        request.assert_not_called()



if __name__ == "__main__":
    unittest.main()
