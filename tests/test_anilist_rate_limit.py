import unittest
from unittest.mock import patch

import api


class FakeClock:
    def __init__(self, initial=100.0):
        self.now = initial

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(0.0, float(seconds))


class FakeCancellationEvent:
    """Advance the test clock instead of blocking on a real Event wait."""

    def __init__(self, clock):
        self.clock = clock

    def is_set(self):
        return False

    def wait(self, seconds=None):
        self.clock.sleep(0.0 if seconds is None else seconds)
        return False


class AniListRateLimitTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        with api._anilist_rate_lock:
            api._anilist_next_request_at = self.clock.now
            api._anilist_cooldown_until = self.clock.now

    def test_requests_are_paced(self):
        with patch.object(api.time, "monotonic", self.clock.monotonic), patch.object(
            api.time, "sleep", self.clock.sleep
        ), patch.object(api, "_api_shutdown_event", FakeCancellationEvent(self.clock)):
            api._wait_for_anilist_slot()
            first_slot = api._anilist_next_request_at
            api._wait_for_anilist_slot()
            self.assertAlmostEqual(self.clock.now, first_slot, places=6)
            self.assertAlmostEqual(
                api._anilist_next_request_at - first_slot,
                api.ANILIST_MIN_REQUEST_INTERVAL,
                places=6,
            )

    def test_rate_limit_extends_shared_cooldown(self):
        with patch.object(api.time, "monotonic", self.clock.monotonic), patch.object(
            api.time, "sleep", self.clock.sleep
        ), patch.object(api, "_api_shutdown_event", FakeCancellationEvent(self.clock)):
            api._extend_anilist_cooldown(3)
            expected_cooldown = self.clock.now + 3
            self.assertEqual(api._anilist_cooldown_until, expected_cooldown)
            api._wait_for_anilist_slot()
            self.assertGreaterEqual(self.clock.now, expected_cooldown)
            self.assertGreaterEqual(
                api._anilist_next_request_at,
                expected_cooldown + api.ANILIST_MIN_REQUEST_INTERVAL,
            )

    def test_http_429_honors_retry_after_before_retrying(self):
        class FakeResponse:
            def __init__(self, status_code, payload, headers=None):
                self.status_code = status_code
                self._payload = payload
                self.headers = headers or {}
                self.reason = "rate limited" if status_code == 429 else "ok"

            def json(self):
                return self._payload

        request_times = []
        responses = [
            FakeResponse(
                429,
                {"errors": [{"message": "slow down"}]},
                {"Retry-After": "3"},
            ),
            FakeResponse(200, {"data": {"Media": {"id": 42}}}),
        ]

        def fake_post(*_args, **_kwargs):
            request_times.append(self.clock.now)
            return responses.pop(0)

        with patch.object(api.time, "monotonic", self.clock.monotonic), patch.object(
            api.time, "sleep", self.clock.sleep
        ), patch.object(api, "_retry_sleep", self.clock.sleep), patch.object(
            api, "_api_shutdown_event", FakeCancellationEvent(self.clock)
        ), patch.object(api.requests, "post", side_effect=fake_post):
            result = api.anilist_request("query { Media(id: 42) { id } }")

        self.assertEqual(result, {"Media": {"id": 42}})
        self.assertEqual(len(request_times), 2)
        self.assertGreaterEqual(request_times[1] - request_times[0], 3.0)
        self.assertGreaterEqual(api._anilist_cooldown_until, request_times[0] + 3.0)

    def test_retry_after_http_date_is_parsed_deterministically(self):
        from datetime import datetime, timezone
        from email.utils import format_datetime

        now = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
        retry_at = datetime(2026, 10, 12, 12, 0, 7, tzinfo=timezone.utc)
        header = format_datetime(retry_at, usegmt=True)

        self.assertEqual(api._retry_after_delay(header, fallback=2, now=now), 7.0)
        self.assertEqual(api._retry_after_delay("nonsense", fallback=2, now=now), 2.0)
        self.assertEqual(api._retry_after_delay("999", fallback=2, now=now), 60.0)


if __name__ == "__main__":
    unittest.main()
