import threading
import unittest
from unittest.mock import patch

import api


class ProviderPaginationShutdownTests(unittest.TestCase):
    def test_media_details_stops_optional_pages_after_shutdown(self):
        stop_event = threading.Event()
        initial_media = {
            "id": 123,
            "type": "ANIME",
            "format": "TV",
            "title": {
                "english": "Example Series",
                "romaji": "Example Series",
                "native": None,
            },
            "startDate": {"year": 2020, "month": 1, "day": 1},
            "endDate": {"year": 2020, "month": 3, "day": 1},
            "coverImage": {"large": "https://example.test/cover.jpg"},
            "episodes": 12,
            "characters": {
                "edges": [
                    {
                        "role": "MAIN",
                        "node": {
                            "id": 456,
                            "name": {"full": "Example Character"},
                            "image": {"large": "https://example.test/character.jpg"},
                        },
                        "voiceActors": [],
                    }
                ],
                "pageInfo": {
                    "currentPage": 1,
                    "lastPage": 5,
                    "hasNextPage": True,
                },
            },
            "airingSchedule": {
                "nodes": [{"airingAt": 1_700_000_000, "episode": 1}],
                "pageInfo": {
                    "currentPage": 1,
                    "lastPage": 4,
                    "hasNextPage": True,
                },
            },
            "staff": {
                "edges": [],
                "pageInfo": {
                    "currentPage": 1,
                    "lastPage": 1,
                    "hasNextPage": False,
                },
            },
            "studios": {"edges": []},
            "relations": {"edges": []},
        }

        def initial_response(_query, _variables=None):
            # Simulate the user closing the app while the first provider request
            # is in flight. No further pages should be requested afterward.
            stop_event.set()
            return {"Media": initial_media}

        with patch.object(api, "anilist_request", side_effect=initial_response) as request:
            details = api.get_media_details(123, stop_event=stop_event)

        request.assert_called_once()
        self.assertFalse(details["_characters_snapshot_valid"])
        self.assertEqual(details["characters"]["pageInfo"]["currentPage"], 1)
        self.assertEqual(details["airingSchedule"]["pageInfo"]["currentPage"], 1)
        self.assertEqual(len(details["airingSchedule"]["nodes"]), 1)


if __name__ == "__main__":
    unittest.main()
