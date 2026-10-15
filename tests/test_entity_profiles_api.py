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

    def test_profile_fetch_repairs_malformed_social_links_as_markdown_for_all_profile_bios(self):
        malformed_links = (
            (
                r"[YouTube]\([https://www.youtube.com/](https://www.youtube.com/)"
                r"[@Ueda](https://anilist.co/user/Ueda)-Kana)",
                "[YouTube](https://www.youtube.com/@Ueda-Kana)",
                "https://www.youtube.com/@Ueda-Kana",
            ),
            (
                r"[Youtube]\([https://youtube.com/](https://youtube.com/)"
                r"[@officialyoutubechannel3974](https://anilist.co/user/officialyoutubechannel3974)"
                r"?si=9AjlJ6Ujj2Vw1CiU)",
                "[Youtube](https://youtube.com/@officialyoutubechannel3974?si=9AjlJ6Ujj2Vw1CiU)",
                "https://youtube.com/@officialyoutubechannel3974?si=9AjlJ6Ujj2Vw1CiU",
            ),
            (
                r"[Youtube]\([https://www.youtube.com/](https://www.youtube.com/)"
                r"[@OfficialChannel](https://anilist.co/user/OfficialChannel)-eu5sl)",
                "[Youtube](https://www.youtube.com/@OfficialChannel-eu5sl)",
                "https://www.youtube.com/@OfficialChannel-eu5sl",
            ),
            (
                r"[TikTok]\([https://www.tiktok.com/](https://www.tiktok.com/)"
                r"[@example](https://anilist.co/user/example)-live)",
                "[TikTok](https://www.tiktok.com/@example-live)",
                "https://www.tiktok.com/@example-live",
            ),
        )
        raw_description = "\n".join(
            malformed for malformed, _expected_markdown, _expected_url in malformed_links
        )

        # Character and Staff (including voice actor) profiles must both request
        # raw Markdown; asking AniList for HTML can change this malformed nested
        # link syntax before the shared normalizer sees it.
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
            ) as request:
                result = api.get_entity_profile(entity_type, entity_id)
                query = request.call_args.args[0]
                self.assertIn("description", query)
                self.assertIn("descriptionHtml: description(asHtml: true)", query)
                self.assertEqual(
                    result["description"],
                    "\n".join(
                        expected_markdown
                        for _malformed, expected_markdown, _expected_url in malformed_links
                    ),
                )
                for _malformed, expected_markdown, expected_url in malformed_links:
                    self.assertIn(expected_markdown, result["description"])
                    self.assertIn(f"]({expected_url})", result["description"])
                self.assertNotIn("https://anilist.co/user/", result["description"])
                self.assertNotIn(r"\([https://", result["description"])

    def test_normalizer_can_also_repair_legacy_mixed_html_bios(self):
        malformed_html = (
            r'<p>[YouTube]\(<a href="https://www.youtube.com/">'
            r'https://www.youtube.com/</a>'
            r'<a href="https://anilist.co/user/OfficialChannel">'
            r'@OfficialChannel</a>-eu5sl)</p>'
        )
        description = api._normalize_anilist_profile_description(
            malformed_html, html_mode=True
        )
        self.assertIn(
            'href="https://www.youtube.com/@OfficialChannel-eu5sl"',
            description,
        )
        self.assertIn(">YouTube</a>", description)
        self.assertNotIn("https://anilist.co/user/OfficialChannel", description)
        self.assertNotIn('<a href="https://www.youtube.com/">', description)

    def test_anilist_request_normalizes_nested_descriptions_everywhere(self):
        malformed = (
            r"[YouTube]\([https://www.youtube.com/](https://www.youtube.com/)"
            r"[@Ueda](https://anilist.co/user/Ueda)-Kana)"
        )
        expected = "[YouTube](https://www.youtube.com/@Ueda-Kana)"
        payload = {
            "data": {
                "Media": {
                    "description": malformed,
                    "relations": {
                        "edges": [
                            {"node": {"description": malformed}},
                        ],
                    },
                },
                "Staff": {"description": malformed},
            },
        }

        class FakeResponse:
            status_code = 200
            headers = {}
            reason = "OK"

            @staticmethod
            def json():
                return payload

        with patch("api._wait_for_anilist_slot"), patch(
            "api.requests.post", return_value=FakeResponse()
        ):
            result = api.anilist_request("query { Media { description } }")

        self.assertEqual(result["Media"]["description"], expected)
        self.assertEqual(
            result["Media"]["relations"]["edges"][0]["node"]["description"],
            expected,
        )
        self.assertEqual(result["Staff"]["description"], expected)

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
