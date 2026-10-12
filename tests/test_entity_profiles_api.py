import unittest
from unittest.mock import patch

import api


class EntityProfileApiTests(unittest.TestCase):
    def test_character_profile_returns_bio_and_media_credits(self):
        profile = {
            "id": 123,
            "name": {"full": "Example Character"},
            "description": "A detailed character bio.",
            "media": {"edges": []},
        }
        with patch("api.anilist_request", return_value={"Character": profile}) as request:
            result = api.get_entity_profile("character", 123)

        self.assertEqual(result, profile)
        self.assertIn("description", request.call_args.args[0])
        self.assertIn("characterRole", request.call_args.args[0])
        self.assertEqual(request.call_args.args[1], {"id": 123})

    def test_voice_actor_uses_staff_profile(self):
        profile = {
            "id": 456,
            "name": {"full": "Example Voice Actor"},
            "primaryOccupations": ["Voice Actor"],
            "staffMedia": {"edges": []},
        }
        with patch("api.anilist_request", return_value={"Staff": profile}) as request:
            result = api.get_entity_profile("voice_actor", 456)

        self.assertEqual(result, profile)
        self.assertIn("Staff(id: $id)", request.call_args.args[0])
        self.assertIn("primaryOccupations", request.call_args.args[0])
        self.assertIn("staffMedia", request.call_args.args[0])

    def test_profile_fetch_repairs_both_malformed_youtube_links(self):
        malformed = (
            "[Youtube]\\([https://youtube.com/](https://youtube.com/)"
            "[@officialyoutubechannel3974]"
            "(https://anilist.co/user/officialyoutubechannel3974)"
            "?si=9AjlJ6Ujj2Vw1CiU) "
            "[YouTube]\\([https://www.youtube.com/](https://www.youtube.com/)"
            "[@Ueda](https://anilist.co/user/Ueda)-Kana)"
        )
        profile = {
            "id": 456,
            "name": {"full": "Example Voice Actor"},
            "description": f"<p>{malformed}</p>",
            "staffMedia": {"edges": []},
            "characterMedia": {"edges": []},
        }
        with patch("api.anilist_request", return_value={"Staff": profile}):
            result = api.get_entity_profile("voice_actor", 456)

        description = result["description"]
        self.assertIn(
            'href="https://youtube.com/@officialyoutubechannel3974?si=9AjlJ6Ujj2Vw1CiU"',
            description,
        )
        self.assertIn('href="https://www.youtube.com/@Ueda-Kana"', description)
        self.assertNotIn("https://anilist.co/user/officialyoutubechannel3974", description)
        self.assertNotIn("https://anilist.co/user/Ueda", description)
        self.assertNotIn("[Youtube]\\(", description)
        self.assertNotIn("[YouTube]\\(", description)

    def test_invalid_entity_id_is_rejected_before_network_call(self):
        for value in (None, 0, -5, True, "not-an-id", 1 << 40):
            with self.subTest(value=value), patch("api.anilist_request") as request:
                with self.assertRaises(ValueError):
                    api.get_entity_profile("character", value)
                request.assert_not_called()

    def test_mangabaka_count_fallback_skips_null_primary_fields(self):
        normalized = api.normalize_mangabaka_series(
            {
                "id": 678,
                "type": "novel",
                "title": "Example Light Novel",
                "total_chapters": None,
                "chapters": "23",
                "total_volumes": None,
                "volumes": 7,
                "final_volume": 8,
            },
            preferred_id=-678,
        )
        self.assertEqual(normalized["chapters"], 23)
        self.assertEqual(normalized["volumes"], 7)


if __name__ == "__main__":
    unittest.main()
