import threading
import unittest
from unittest.mock import patch

import api


class ProviderPaginationShutdownTests(unittest.TestCase):
    def setUp(self):
        api.reset_api_shutdown()

    def tearDown(self):
        api.reset_api_shutdown()

    def test_blocking_http_call_can_be_abandoned_during_shutdown(self):
        stop_event = threading.Event()
        request_started = threading.Event()
        release_request = threading.Event()
        response_closed = threading.Event()
        errors = []

        class FakeResponse:
            def close(self):
                response_closed.set()

        def blocking_request(*_args, **_kwargs):
            request_started.set()
            release_request.wait(timeout=3)
            return FakeResponse()

        def call_api():
            try:
                api.anilist_request(
                    "query Example { Viewer { id } }",
                    stop_event=stop_event,
                )
            except Exception as error:
                errors.append(error)

        with (
            patch.object(api, "_wait_for_anilist_slot"),
            patch.object(api.requests, "post", side_effect=blocking_request),
        ):
            caller = threading.Thread(target=call_api, name="test-api-caller")
            caller.start()
            try:
                self.assertTrue(request_started.wait(timeout=2))
                stop_event.set()
                caller.join(timeout=0.5)
                self.assertFalse(
                    caller.is_alive(),
                    "The provider caller should not wait for a blocked socket at shutdown.",
                )
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], InterruptedError)
            finally:
                release_request.set()
                caller.join(timeout=2)
                response_closed.wait(timeout=2)

        self.assertTrue(response_closed.is_set())

    def test_anilist_slot_wait_stops_immediately_when_shutdown_is_set(self):
        stop_event = threading.Event()
        stop_event.set()

        with self.assertRaisesRegex(InterruptedError, "cancelled during shutdown"):
            api._wait_for_anilist_slot(stop_event)

    def test_anilist_request_does_not_start_after_shutdown(self):
        stop_event = threading.Event()
        stop_event.set()

        with patch.object(api.requests, "post") as post:
            with self.assertRaisesRegex(InterruptedError, "cancelled during shutdown"):
                api.anilist_request("query Example { Viewer { id } }", stop_event=stop_event)

        post.assert_not_called()

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

        def initial_response(_query, _variables=None, stop_event=None):
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
