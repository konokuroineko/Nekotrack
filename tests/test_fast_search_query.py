import unittest
from unittest.mock import patch

import api


class FastSearchQueryTests(unittest.TestCase):
    def _fake_response(self, query, variables):
        return {"Page": {"pageInfo": {"currentPage": 1, "lastPage": 1, "hasNextPage": False}, "media": []}}

    def test_fast_search_query_omits_relations(self):
        captured = {}

        def fake_request(query, variables=None):
            captured["query"] = query
            captured["variables"] = variables
            return self._fake_response(query, variables)

        with patch.object(api, "anilist_request", side_effect=fake_request):
            api.search_anime("test", media_type="ANIME", include_relations=False)

        self.assertNotIn("relations", captured["query"])

    def test_normal_search_query_includes_relations(self):
        captured = {}

        def fake_request(query, variables=None):
            captured["query"] = query
            return self._fake_response(query, variables)

        with patch.object(api, "anilist_request", side_effect=fake_request):
            api.search_anime("test", media_type="ANIME", include_relations=True)

        self.assertIn("relations", captured["query"])


if __name__ == "__main__":
    unittest.main()
