import unittest
from unittest.mock import patch

import mangabaka_api as mb


class MangaBakaFilterMappingTests(unittest.TestCase):
    @patch.object(mb, "search_series")
    def test_reading_filters_are_translated_to_provider_parameters(self, search):
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


if __name__ == "__main__":
    unittest.main()
