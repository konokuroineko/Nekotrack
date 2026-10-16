"""Regression tests for bounded AniList HTTP retry behavior."""

import unittest
from unittest.mock import Mock, patch

import api


class AniListRequestRetryTests(unittest.TestCase):
    def setUp(self):
        api._anilist_next_request_at = 0.0
        api._anilist_cooldown_until = 0.0

    @patch("api._wait_for_anilist_slot")
    @patch("api._retry_sleep")
    @patch("api.requests.post")
    def test_ssl_eof_retries_with_bounded_timeout_then_succeeds(
        self, post, sleep, _wait_for_slot
    ):
        response = Mock()
        response.status_code = 200
        response.headers = {}
        response.reason = "OK"
        response.json.return_value = {"data": {"Media": {"id": 123}}}
        post.side_effect = [
            api.requests.exceptions.SSLError(
                "[SSL: UNEXPECTED_EOF_WHILE_READING] connection closed"
            ),
            response,
        ]

        result = api.anilist_request("query { Media(id: 123) { id } }")

        self.assertEqual(result, {"Media": {"id": 123}})
        self.assertEqual(post.call_count, 2)
        self.assertEqual(
            post.call_args.kwargs["timeout"],
            api.ANILIST_REQUEST_TIMEOUT,
        )
        self.assertEqual(api.ANILIST_REQUEST_TIMEOUT, (5, 15))
        sleep.assert_called_once_with(1)

    @patch("api._wait_for_anilist_slot")
    @patch("api._retry_sleep")
    @patch("api.requests.post")
    def test_persistent_network_errors_stop_after_three_short_retries(
        self, post, sleep, _wait_for_slot
    ):
        post.side_effect = api.requests.exceptions.SSLError("TLS EOF")

        with self.assertRaisesRegex(RuntimeError, "Network error after 3 attempts"):
            api.anilist_request("query { Media(id: 123) { id } }")

        self.assertEqual(post.call_count, 3)
        self.assertEqual(
            [call.args[0] for call in sleep.call_args_list],
            [1, 2],
        )
        self.assertTrue(
            all(call.kwargs["timeout"] == (5, 15) for call in post.call_args_list)
        )


if __name__ == "__main__":
    unittest.main()
