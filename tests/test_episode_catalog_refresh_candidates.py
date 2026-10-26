import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database


class EpisodeCatalogRefreshAttemptTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "episode-refresh.sqlite3"
        self.database_name_patch = patch.object(
            database, "DATABASE_NAME", str(self.database_path)
        )
        self.database_name_patch.start()
        database.initialize_database()
        self.now = 1_700_000_000
        self._insert_candidate(
            work_id=120700,
            catalog_metadata={
                "version": 3,
                "fetched_at": self.now - 9 * 24 * 60 * 60,
                "complete": True,
            },
        )

    def tearDown(self):
        self.database_name_patch.stop()
        self.temp_dir.cleanup()

    def _insert_candidate(self, work_id, catalog_metadata):
        connection = database.get_connection()
        try:
            connection.execute(
                "INSERT INTO works (id, title, type, episodes, format) "
                "VALUES (?, ?, 'ANIME', 12, 'ONA')",
                (work_id, f"Example {work_id}"),
            )
            connection.execute(
                "INSERT INTO user_library (work_id) VALUES (?)",
                (work_id,),
            )
            connection.execute(
                "INSERT INTO episodes (work_id, episode_number, air_date) "
                "VALUES (?, 1, '2099-01-01')",
                (work_id,),
            )
            if catalog_metadata is not None:
                connection.execute(
                    "INSERT INTO work_provider_metadata "
                    "(work_id, provider, payload_json) VALUES (?, ?, ?)",
                    (work_id, "tmdb_episode_match_version", json.dumps(catalog_metadata)),
                )
            connection.commit()
        finally:
            connection.close()

    def _save_attempt(self, *, version, attempted_at):
        database.save_provider_metadata(
            120700,
            "tmdb_episode_match_attempt",
            {"version": version, "attempted_at": attempted_at},
        )

    def _refresh_ids(self, *, version=4, now=None, cooldown=24 * 60 * 60):
        return database.get_library_episode_catalog_refresh_ids(
            version,
            7 * 24 * 60 * 60,
            now=self.now if now is None else now,
            attempt_cooldown_seconds=cooldown,
        )

    def test_recent_current_policy_attempt_suppresses_repeat_lookup(self):
        self._save_attempt(version=4, attempted_at=self.now - 60)

        self.assertEqual(self._refresh_ids(), [])

    def test_expired_attempt_allows_failed_catalog_to_retry(self):
        self._save_attempt(version=4, attempted_at=self.now - 2 * 24 * 60 * 60)

        self.assertEqual(self._refresh_ids(), [120700])

    def test_newer_catalog_policy_is_not_blocked_by_old_attempt(self):
        self._save_attempt(version=4, attempted_at=self.now - 60)

        self.assertEqual(self._refresh_ids(version=5), [120700])

    def test_zero_cooldown_disables_attempt_suppression(self):
        self._save_attempt(version=4, attempted_at=self.now - 60)

        self.assertEqual(self._refresh_ids(cooldown=0), [120700])


if __name__ == "__main__":
    unittest.main()
