import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
