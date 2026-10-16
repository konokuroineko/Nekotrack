import sqlite3
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
    merge_recommendation_candidate,
    rank_candidates,
    seed_strength,
    source_weight_for_work,
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

    def test_discovery_skips_seen_titles_but_keeps_explicit_likes(self):
        candidates = [
            {"id": 10, "type": "ANIME", "title": {"english": "Already seen"}, "averageScore": 98},
            {"id": 11, "type": "ANIME", "title": {"english": "Explicit like"}, "averageScore": 70},
            {"id": 12, "type": "ANIME", "title": {"english": "Fresh title"}, "averageScore": 65},
        ]
        history = {
            10: {"work_id": 10, "feedback": None, "impressions": 4, "metadata": candidates[0]},
            11: {"work_id": 11, "feedback": "like", "impressions": 12, "metadata": candidates[1]},
        }

        default_ranked = rank_candidates(candidates, history=history)
        discovery_ranked = rank_candidates(
            candidates, history=history, exclude_seen=True
        )

        self.assertIn(10, [item["id"] for item in default_ranked])
        discovery_ids = [item["id"] for item in discovery_ranked]
        self.assertNotIn(10, discovery_ids)
        self.assertIn(11, discovery_ids)
        self.assertIn(12, discovery_ids)

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

    def test_new_recommendation_choices_adjust_genres_sources_and_permanently_hide_only_one_id(self):
        history = {
            900: {
                "work_id": 900,
                "feedback": "more_like_this",
                "impressions": 1,
                "metadata": {
                    "id": 900, "genres": ["Mystery"],
                    "_recommendation_source_ids": [41],
                },
            },
            901: {
                "work_id": 901,
                "feedback": "less_like_this",
                "impressions": 1,
                "metadata": {
                    "id": 901, "genres": ["Sports"],
                    "_recommendation_source_ids": [42],
                },
            },
            999: {
                "work_id": 999,
                "feedback": "never_show",
                "impressions": 1,
                "metadata": {"id": 999, "genres": ["Drama"]},
            },
        }
        candidates = [
            {"id": 11, "type": "ANIME", "title": {"english": "Preferred relation"},
             "genres": ["Mystery"], "_recommendation_source_ids": [41], "averageScore": 80, "popularity": 500},
            {"id": 12, "type": "ANIME", "title": {"english": "Other relation"},
             "genres": ["Mystery"], "_recommendation_source_ids": [77], "averageScore": 80, "popularity": 500},
            {"id": 13, "type": "ANIME", "title": {"english": "Rejected relation"},
             "genres": ["Sports"], "_recommendation_source_ids": [42], "averageScore": 80, "popularity": 500},
            {"id": 14, "type": "ANIME", "title": {"english": "Other sport"},
             "genres": ["Sports"], "_recommendation_source_ids": [77], "averageScore": 80, "popularity": 500},
            {"id": 999, "type": "ANIME", "title": {"english": "Never show"},
             "genres": ["Drama"], "_recommendation_source_ids": [77], "averageScore": 100, "popularity": 10000},
        ]

        ranked = rank_candidates(candidates, history=history, rotation=0)
        ids = [item["id"] for item in ranked]
        self.assertNotIn(999, ids)
        self.assertLess(ids.index(11), ids.index(12))
        self.assertLess(ids.index(14), ids.index(13))

        suggestions = {}
        self.assertFalse(merge_recommendation_candidate(
            suggestions,
            candidates[-1],
            set(),
            history,
        ))

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

    def test_voice_actor_reason_names_the_person_and_title(self):
        candidate = {
            "id": 8801,
            "type": "ANIME",
            "title": {"english": "Candidate"},
            "characters": {"edges": [{
                "role": "MAIN",
                "node": {"id": 700, "name": {"full": "Mina"}},
                "voiceActors": [{
                    "id": 901, "language": "Japanese",
                    "name": {"full": "Miyuki Sawashiro"},
                }],
            }]},
        }
        profile = {
            42: {
                "_source_weight": 1.0,
                "_source_title": "A Series You Enjoyed",
                "characters": [],
                "voice_actors": [{
                    "id": 901, "language": "Japanese", "character_role": "MAIN",
                }],
                "staff": [],
            }
        }
        ranked = rank_candidates([candidate], credit_profile=profile, voice_language="JA")
        self.assertIn("Miyuki Sawashiro", ranked[0]["_recommendation_reason"])
        self.assertIn("A Series You Enjoyed", ranked[0]["_recommendation_reason"])
        self.assertIn("Japanese voice actor", ranked[0]["_recommendation_reason"])

        favorited = rank_candidates(
            [candidate], favorite_entities=[
                {"entity_type": "voice_actor", "entity_id": 901},
            ], voice_language="JA",
        )
        self.assertIn("Miyuki Sawashiro", favorited[0]["_recommendation_reason"])
        self.assertIn("favorited", favorited[0]["_recommendation_reason"].casefold())

    def test_seed_weights_and_candidate_merging_live_in_the_algorithm_module(self):
        work = {
            "id": 901,
            "type": "ANIME",
            "status": "watching",
            "rating": 8,
        }
        plain_seed = seed_strength(work, set(), {})
        preferred_seed = seed_strength(
            work, {901}, {901: {"feedback": "like"}}
        )
        self.assertGreater(preferred_seed, plain_seed)
        self.assertEqual(source_weight_for_work(901, {"status": "planning"}, set(), {}), 1.0)
        self.assertEqual(
            source_weight_for_work(
                901, work, {901}, {901: {"feedback": "like"}}
            ),
            3.5,
        )

        suggestions = {}
        known_ids = set()
        candidate = {
            "id": 902, "type": "ANIME",
            "title": {"english": "Merged candidate"},
        }
        self.assertTrue(merge_recommendation_candidate(
            suggestions, candidate, known_ids, {},
            source_id=901, source_title="Saved A",
        ))
        self.assertTrue(merge_recommendation_candidate(
            suggestions, candidate, known_ids, {},
            source_id=903, source_title="Saved B",
        ))
        self.assertEqual(suggestions[902]["_recommendation_count"], 2)
        self.assertEqual(
            suggestions[902]["_recommendation_source_titles"], ["Saved A", "Saved B"]
        )
        self.assertFalse(merge_recommendation_candidate(
            suggestions, {"id": 904, "type": "ANIME"}, known_ids,
            {904: {"feedback": "dislike"}},
        ))


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
            "_recommendation_source_ids": [12, 34, 12, "invalid", -1],
        }
        self.assertTrue(database.set_recommendation_feedback(831, "like", work))
        self.assertEqual(database.record_recommendation_impressions([work]), 1)
        self.assertEqual(database.record_recommendation_impressions([work]), 1)

        database.initialize_database()
        history = database.get_recommendation_history()
        self.assertEqual(history[831]["feedback"], "like")
        self.assertEqual(history[831]["impressions"], 2)
        self.assertEqual(history[831]["metadata"]["genres"], ["Mystery"])
        self.assertEqual(history[831]["metadata"]["_recommendation_source_ids"], [12, 34])
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
        for choice in ("more_like_this", "less_like_this", "never_show"):
            self.assertTrue(database.set_recommendation_feedback(831, choice, work))
            self.assertEqual(database.get_recommendation_history()[831]["feedback"], choice)

    def test_old_history_table_migrates_without_losing_rows(self):
        connection = sqlite3.connect(self._database_path)
        connection.execute("DROP TABLE recommendation_history")
        connection.execute("""
            CREATE TABLE recommendation_history (
                work_id INTEGER PRIMARY KEY,
                impressions INTEGER NOT NULL DEFAULT 0 CHECK (impressions >= 0),
                feedback TEXT CHECK (feedback IN ('like', 'dislike') OR feedback IS NULL),
                metadata_json TEXT NOT NULL DEFAULT '{}',
                first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_seen_at DATETIME
            )
        """)
        connection.execute(
            "INSERT INTO recommendation_history (work_id, impressions, feedback, metadata_json) VALUES (?, ?, ?, ?)",
            (88, 7, "like", '{"id":88,"genres":["Mystery"]}'),
        )
        connection.commit()
        connection.close()

        database.initialize_database()
        self.assertEqual(database.get_recommendation_history()[88]["impressions"], 7)
        self.assertTrue(database.set_recommendation_feedback(89, "never_show"))
        self.assertEqual(database.get_recommendation_history()[89]["feedback"], "never_show")

    def test_invalid_feedback_and_impression_ids_are_ignored(self):
        self.assertFalse(database.set_recommendation_feedback(True, "like"))
        self.assertFalse(database.set_recommendation_feedback(0, "like"))
        self.assertFalse(database.set_recommendation_feedback(832, "maybe"))
        self.assertFalse(database.set_recommendation_feedback(832, "hide"))
        self.assertEqual(database.record_recommendation_impressions([
            {"id": True}, {"id": 0}, {"id": "bad"}, None
        ]), 0)


if __name__ == "__main__":
    unittest.main()
