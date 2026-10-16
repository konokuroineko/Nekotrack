import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
from recommendation_engine import (
    character_role_weight,
    exposure_multiplier,
    inject_rare_exploration,
    rank_candidates,
    staff_role_weight,
    voice_actor_role_weight,
)


class RecommendationScoringTests(unittest.TestCase):
    def test_exposure_penalty_diminishes_but_never_reaches_zero(self):
        values = [exposure_multiplier(count) for count in (0, 1, 10, 100, 1000000)]
        self.assertEqual(values[0], 1.0)
        self.assertTrue(all(value > 0 for value in values))
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertGreaterEqual(values[-1], 0.18)

    def test_like_boosts_matching_metadata_and_dislike_suppresses_exact_title(self):
        candidates = [
            {"id": 1, "type": "ANIME", "title": {"english": "Liked"},
             "genres": ["Mystery"], "averageScore": 80},
            {"id": 2, "type": "ANIME", "title": {"english": "Similar"},
             "genres": ["Mystery"], "averageScore": 72},
            {"id": 3, "type": "ANIME", "title": {"english": "Different"},
             "genres": ["Sports"], "averageScore": 95},
            {"id": 4, "type": "ANIME", "title": {"english": "Rejected"},
             "genres": ["Sports"], "averageScore": 99},
        ]
        history = {
            1: {"work_id": 1, "feedback": "like", "impressions": 1,
                "metadata": {"id": 1, "genres": ["Mystery"]}},
            4: {"work_id": 4, "feedback": "dislike", "impressions": 0,
                "metadata": {"id": 4, "genres": ["Sports"]}},
        }

        ranked = rank_candidates(candidates, history=history, rotation=0)

        ids = [item["id"] for item in ranked]
        self.assertNotIn(4, ids)
        self.assertLess(ids.index(2), ids.index(3))
        self.assertIn("Mystery", ranked[ids.index(2)]["_recommendation_reason"])

    def test_exploration_is_small_and_does_not_change_candidate_eligibility(self):
        candidates = [
            {"id": index + 1, "type": "ANIME", "title": {"english": str(index)},
             "_recommendation_score": float(100 - index)}
            for index in range(75)
        ]
        reordered = inject_rare_exploration(candidates, rotation=3, fraction=0.04)
        self.assertEqual({item["id"] for item in reordered}, {item["id"] for item in candidates})
        self.assertEqual(len(reordered), len(candidates))
        # The low-ranked discovery can enter a reserved slot but cannot dominate
        # the first few high-confidence recommendations.
        self.assertEqual([item["id"] for item in reordered[:10]], [item["id"] for item in candidates[:10]])
        self.assertNotEqual([item["id"] for item in reordered], [item["id"] for item in candidates])

    def test_character_voice_and_staff_role_weights_are_centralized(self):
        self.assertGreater(character_role_weight("MAIN"), character_role_weight("SUPPORTING"))
        self.assertGreater(character_role_weight("SUPPORTING"), character_role_weight("BACKGROUND"))
        self.assertEqual(voice_actor_role_weight("MAIN"), character_role_weight("MAIN"))
        self.assertGreater(staff_role_weight("Series Composition"), staff_role_weight("Production Assistant"))
        self.assertGreater(staff_role_weight("Original story"), staff_role_weight("Background art"))


class RecommendationHistoryPersistenceTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self._database_path = Path(self._directory.name) / "recommendations.db"
        self._patcher = patch.object(database, "DATABASE_NAME", str(self._database_path))
        self._patcher.start()
        database.initialize_database()

    def tearDown(self):
        self._patcher.stop()
        self._directory.cleanup()

    def test_feedback_and_impressions_survive_database_reinitialization(self):
        work = {
            "id": 831, "type": "ANIME",
            "title": {"english": "Saved feedback"},
            "genres": ["Mystery"], "tags": [{"name": "Investigation"}],
            "cover_url": "https://example.invalid/cover.jpg",
        }
        self.assertTrue(database.set_recommendation_feedback(831, "like", work))
        self.assertEqual(database.record_recommendation_impressions([work]), 1)
        self.assertEqual(database.record_recommendation_impressions([work]), 1)

        database.initialize_database()
        history = database.get_recommendation_history()
        self.assertEqual(history[831]["feedback"], "like")
        self.assertEqual(history[831]["impressions"], 2)
        self.assertEqual(history[831]["metadata"]["genres"], ["Mystery"])
        self.assertTrue(database.set_recommendation_feedback(831, "dislike", work))
        self.assertEqual(database.get_recommendation_history()[831]["feedback"], "dislike")

    def test_invalid_feedback_and_impression_ids_are_ignored(self):
        self.assertFalse(database.set_recommendation_feedback(True, "like"))
        self.assertFalse(database.set_recommendation_feedback(0, "like"))
        self.assertFalse(database.set_recommendation_feedback(832, "maybe"))
        self.assertEqual(database.record_recommendation_impressions([
            {"id": True}, {"id": 0}, {"id": "bad"}, None
        ]), 0)


if __name__ == "__main__":
    unittest.main()
