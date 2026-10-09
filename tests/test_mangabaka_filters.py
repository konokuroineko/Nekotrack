import unittest
from unittest.mock import patch

import mangabaka_api as mb


def sample_series(series_id, title, status, rating=85):
    return {
        "id": series_id,
        "type": "manga",
        "title": title,
        "status": status,
        "content_rating": "safe",
        "rating": rating,
        "published": {"start": "2020-04-02"},
        "tags": [
            {"name": "Fantasy", "name_path": "Fantasy", "is_genre": True},
            {"name": "Adventure", "name_path": "Adventure", "is_genre": False},
            {"name": "Isekai", "name_path": "Isekai", "is_genre": False},
        ],
        "publisher_id": 42,
        "is_licensed": True,
    }


class MangaBakaFilterMappingTests(unittest.TestCase):
    @patch.object(mb, "search_series")
    def test_provider_filter_parameters_are_mapped(self, search):
        search.return_value = {
            "status": 200,
            "data": [],
            "pagination": {"page": 1, "limit": 7, "count": 0, "next": None},
        }
        result = mb.search_media(
            "Example", page=1, media_type="MANGA", media_format=None,
            filters={
                "format_filter": "MANGA", "status": "FINISHED", "min_score": 80,
                "year": "2020", "genre": "Action, Fantasy",
                "tag": "Isekai, Reincarnation", "publisher_id": "42",
                "is_licensed": True, "sort": "SCORE_DESC",
            }, limit=7,
        )
        self.assertEqual(result["media"], [])
        self.assertEqual(search.call_args.args[0], "Example")
        kwargs = search.call_args.kwargs
        self.assertEqual(kwargs["page"], 1)
        self.assertEqual(kwargs["limit"], 7)
        self.assertEqual(kwargs["type"], ["manga", "manhwa", "manhua", "oel", "other"])
        self.assertEqual(kwargs["status"], ["completed"])
        self.assertEqual(kwargs["rating_lower"], 80)
        self.assertEqual(kwargs["start_year"], 2020)
        self.assertEqual(kwargs["end_year"], 2020)
        self.assertEqual(kwargs["genre"], ["Action", "Fantasy"])
        self.assertEqual(kwargs["tag"], ["Isekai", "Reincarnation"])
        self.assertEqual(kwargs["publisher_id"], 42)
        self.assertIs(kwargs["is_licensed"], True)
        self.assertEqual(kwargs["sort_by"], "rating_desc")

    @patch.object(mb, "search_series")
    def test_status_filter_locally_removes_releasing_records(self, search):
        search.return_value = {
            "status": 200,
            "data": [
                sample_series(1, "Completed example", "completed"),
                sample_series(2, "Releasing example", "releasing"),
            ],
            "pagination": {"page": 1, "limit": 20, "count": 2, "next": None},
        }
        result = mb.search_media(
            "Example", media_type="MANGA",
            filters={"format_filter": "MANGA", "status": "FINISHED"},
        )
        self.assertEqual([item["title"]["english"] for item in result["media"]], ["Completed example"])

    @patch.object(mb, "search_series")
    def test_local_filtering_enforces_score_year_genre_tag_publisher_and_license(self, search):
        matching = sample_series(1, "Matching", "completed", rating=85)
        wrong_publisher = sample_series(2, "Wrong publisher", "completed", rating=90)
        wrong_publisher["publisher_id"] = 99
        wrong_license = sample_series(3, "Unlicensed", "completed", rating=90)
        wrong_license["is_licensed"] = False
        low_score = sample_series(4, "Low score", "completed", rating=60)
        wrong_year = sample_series(5, "Wrong year", "completed", rating=90)
        wrong_year["published"]["start"] = "2019-04-02"
        wrong_genre = sample_series(6, "Wrong genre", "completed", rating=90)
        wrong_genre["tags"][0]["name"] = "Comedy"
        wrong_tag = sample_series(7, "Wrong tag", "completed", rating=90)
        wrong_tag["tags"][2]["name"] = "Romance"
        search.return_value = {
            "status": 200,
            "data": [matching, wrong_publisher, wrong_license, low_score, wrong_year, wrong_genre, wrong_tag],
            "pagination": {"page": 1, "limit": 20, "count": 7, "next": None},
        }
        result = mb.search_media(
            "Example", media_type="MANGA",
            filters={
                "format_filter": "MANGA", "status": "FINISHED", "min_score": 80,
                "year": "2020", "genre": "Fantasy", "tag": "Isekai",
                "publisher_id": "42", "is_licensed": True,
            },
        )
        self.assertEqual([item["_mangabaka_id"] for item in result["media"]], [1])


if __name__ == "__main__":
    unittest.main()
