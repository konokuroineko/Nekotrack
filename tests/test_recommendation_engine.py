import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
from recommendation_engine import (
    character_role_weight,
    credit_profile_from_media_record,
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

    def test_favorite_character_and_language_matched_voice_actors_boost_candidates(self):
        candidates = [
            {
                "id": 801, "type": "ANIME", "title": {"english": "Favorite role"},
                "characters": {"edges": [{
                    "role": "MAIN", "node": {"id": 71},
                    "voiceActors": [{"id": 91, "language": "Japanese"}],
                }]},
                "staff": {"edges": []},
            },
            {
                "id": 802, "type": "ANIME", "title": {"english": "Background role"},
                "characters": {"edges": [{
                    "role": "BACKGROUND", "node": {"id": 71},
                    "voiceActors": [{"id": 91, "language": "English"}],
                }]},
                "staff": {"edges": []},
            },
        ]
        favorites = [
            {"entity_type": "character", "entity_id": 71},
            {"entity_type": "voice_actor", "entity_id": 91, "language": "Japanese"},
        ]
        ja_ranked = rank_candidates(candidates, favorite_entities=favorites, voice_language="JA")
        self.assertEqual(ja_ranked[0]["id"], 801)
        self.assertGreater(
            ja_ranked[0]["_recommendation_credit_boost"],
            ja_ranked[1]["_recommendation_credit_boost"],
        )
        en_ranked = rank_candidates(candidates, favorite_entities=favorites, voice_language="EN")
        self.assertGreater(
            ja_ranked[0]["_recommendation_credit_boost"],
            next(row["_recommendation_credit_boost"] for row in en_ranked if row["id"] == 801),
        )
        # The person remains favorited across languages; only the matching voice
        # credit on each candidate is filtered by the selected audio preference.
        english_candidate = next(row for row in en_ranked if row["id"] == 802)
        self.assertGreater(english_candidate["_recommendation_credit_boost"], 0)

    def test_persisted_media_credits_normalize_and_deduplicate_by_role(self):
        record = {
            "characters": {"edges": [
                {"role": "BACKGROUND", "node": {"id": 71},
                 "voiceActors": [{"id": 91, "language": "Japanese"}]},
                {"role": "MAIN", "node": {"id": 71},
                 "voiceActors": [{"id": 91, "language": "Japanese"}]},
            ]},
            "staff": {"edges": [
                {"role": "Production Assistant", "node": {"id": 99}},
                {"role": "Series Composition", "node": {"id": 99}},
            ]},
        }
        profile = credit_profile_from_media_record(record)
        self.assertEqual(len(profile["characters"]), 1)
        self.assertEqual(profile["characters"][0]["role"], "MAIN")
        self.assertEqual(len(profile["voice_actors"]), 1)
        self.assertEqual(profile["voice_actors"][0]["character_role"], "MAIN")
        self.assertEqual(len(profile["staff"]), 1)
        self.assertEqual(profile["staff"][0]["role"], "Series Composition")

    def test_saved_creator_credit_boosts_important_roles_and_deduplicates(self):
        candidate = {
            "id": 803, "type": "ANIME", "title": {"english": "Candidate"},
            "staff": {"edges": [
                {"role": "Series Composition", "node": {"id": 99}},
                {"role": "Background Art", "node": {"id": 99}},
            ]},
        }
        profile = {
            1: {
                "_source_weight": 2.0,
                "characters": [],
                "voice_actors": [],
                "staff": [{"id": 99, "role": "Series Composition"}],
            }
        }
        scored = rank_candidates([candidate], credit_profile=profile)
        self.assertGreater(scored[0]["_recommendation_credit_boost"], 0)
        self.assertIn("production staff", scored[0]["_recommendation_reason"].casefold())

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
        self.assertLess(staff_role_weight("Assistant Director"), staff_role_weight("Director"))


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
            "characters": {"edges": [{
                "role": "MAIN", "node": {"id": 712},
                "voiceActors": [{"id": 913, "language": "Japanese"}],
            }]},
            "staff": {"edges": [{
                "role": "Series Composition", "node": {"id": 994},
            }]},
        }
        self.assertTrue(database.set_recommendation_feedback(831, "like", work))
        self.assertEqual(database.record_recommendation_impressions([work]), 1)
        self.assertEqual(database.record_recommendation_impressions([work]), 1)

        database.initialize_database()
        history = database.get_recommendation_history()
        self.assertEqual(history[831]["feedback"], "like")
        self.assertEqual(history[831]["impressions"], 2)
        self.assertEqual(history[831]["metadata"]["genres"], ["Mystery"])
        self.assertEqual(
            history[831]["metadata"]["characters"]["edges"][0]["voiceActors"][0]["language"],
            "Japanese",
        )
        self.assertEqual(
            history[831]["metadata"]["staff"]["edges"][0]["role"],
            "Series Composition",
        )
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
