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

    def test_profile_fetch_repairs_malformed_social_links_for_character_and_staff_bios(self):
        malformed_links = (
            (
                r"[YouTube]\([https://www.youtube.com/](https://www.youtube.com/)"
                r"[@Ueda](https://anilist.co/user/Ueda)-Kana)",
                "https://www.youtube.com/@Ueda-Kana",
            ),
            (
                r"[Youtube]\([https://youtube.com/](https://youtube.com/)"
                r"[@officialyoutubechannel3974](https://anilist.co/user/officialyoutubechannel3974)"
                r"?si=9AjlJ6Ujj2Vw1CiU)",
                "https://youtube.com/@officialyoutubechannel3974?si=9AjlJ6Ujj2Vw1CiU",
            ),
            (
                r"[Youtube]\([https://www.youtube.com/](https://www.youtube.com/)"
                r"[@OfficialChannel](https://anilist.co/user/OfficialChannel)-eu5sl)",
                "https://www.youtube.com/@OfficialChannel-eu5sl",
            ),
            (
                r"[TikTok]\([https://www.tiktok.com/](https://www.tiktok.com/)"
                r"[@example](https://anilist.co/user/example)-live)",
                "https://www.tiktok.com/@example-live",
            ),
        )
        raw_description = "<p>" + " ".join(
            malformed for malformed, _expected_url in malformed_links
        ) + "</p>"

        # Character, staff, and voice-actor profiles all pass through the same
        # API boundary, so the repair must not be limited to voice-actor pages.
        profile_kinds = (
            ("character", "Character", 123),
            ("voice_actor", "Staff", 456),
        )
        for entity_type, payload_key, entity_id in profile_kinds:
            profile = {
                "id": entity_id,
                "name": {"full": "Example profile"},
                "description": raw_description,
                "media": {"edges": []},
                "staffMedia": {"edges": []},
                "characterMedia": {"edges": []},
            }
            with self.subTest(entity_type=entity_type), patch(
                "api.anilist_request", return_value={payload_key: profile}
            ):
                result = api.get_entity_profile(entity_type, entity_id)
                description = result["description"]
                for _malformed, expected_url in malformed_links:
                    self.assertIn(f'href="{expected_url}"', description)
                self.assertNotIn("https://anilist.co/user/", description)
                self.assertNotIn(r"\([https://", description)

        # The plain Markdown path is also used for locally saved/fallback bios.
        first_malformed, first_url = malformed_links[0]
        self.assertEqual(
            api._normalize_anilist_profile_description(first_malformed),
            f"[YouTube]({first_url})",
        )

    def test_profile_fetch_repairs_mixed_html_social_links(self):
        malformed_html = (
            r'<p>[YouTube]\(<a href="https://www.youtube.com/">'
            r'https://www.youtube.com/</a>'
            r'<a href="https://anilist.co/user/OfficialChannel">'
            r'@OfficialChannel</a>-eu5sl)</p>'
        )
        profile = {
            "id": 456,
            "name": {"full": "Example Voice Actor"},
            "description": malformed_html,
            "staffMedia": {"edges": []},
            "characterMedia": {"edges": []},
        }
        with patch("api.anilist_request", return_value={"Staff": profile}):
            result = api.get_entity_profile("voice_actor", 456)

        description = result["description"]
        self.assertIn(
            'href="https://www.youtube.com/@OfficialChannel-eu5sl"',
            description,
        )
        self.assertIn(">YouTube</a>", description)
        self.assertNotIn("https://anilist.co/user/OfficialChannel", description)
        self.assertNotIn("<a href=\"https://www.youtube.com/\">", description)

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
