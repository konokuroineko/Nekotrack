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


class AniListRateLimitTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        with api._anilist_rate_lock:
            api._anilist_next_request_at = self.clock.now
            api._anilist_cooldown_until = self.clock.now

    def test_requests_are_paced(self):
        with patch.object(api.time, "monotonic", self.clock.monotonic), patch.object(
            api.time, "sleep", self.clock.sleep
        ):
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
        ):
            api._extend_anilist_cooldown(3)
            expected_cooldown = self.clock.now + 3
            self.assertEqual(api._anilist_cooldown_until, expected_cooldown)
            api._wait_for_anilist_slot()
            self.assertGreaterEqual(self.clock.now, expected_cooldown)
            self.assertGreaterEqual(
                api._anilist_next_request_at,
                expected_cooldown + api.ANILIST_MIN_REQUEST_INTERVAL,
            )


if __name__ == "__main__":
    unittest.main()
