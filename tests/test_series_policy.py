import unittest
from unittest.mock import patch

import series


class SeriesPolicyTests(unittest.TestCase):
    def _item(self, media_id, title, media_type="ANIME", media_format=None):
        return {
            "id": media_id,
            "type": media_type,
            "format": media_format,
            "title": {"romaji": title, "english": None, "native": None},
        }

    def _edge(self, relation_type, node):
        return {"relationType": relation_type, "node": node}

    def test_unrelated_cross_format_prequel_is_rejected(self):
        source = self._item(1, "One Piece", media_format="TV")
        target = self._item(2, "Monsters: 103 Mercies Dragon Damnation", media_format="MOVIE")
        edge = self._edge("PREQUEL", target)
        self.assertFalse(series._relation_group_compatible(source, edge, target))

    def test_explicit_side_story_is_excluded_in_main_only_mode(self):
        source = self._item(1, "Attack on Titan", media_format="TV")
        target = self._item(2, "Attack on Titan OVA", media_format="OVA")
        edge = self._edge("SIDE_STORY", target)
        with patch.object(series, "get", return_value="main"):
            self.assertFalse(series._relation_group_compatible(source, edge, target))

    def test_explicit_side_story_can_cross_formats_when_extras_enabled(self):
        source = self._item(1, "Attack on Titan", media_format="TV")
        target = self._item(2, "Attack on Titan OVA", media_format="OVA")
        edge = self._edge("SIDE_STORY", target)
        with patch.object(series, "get", return_value="extras"):
            self.assertTrue(series._relation_group_compatible(source, edge, target))

    def test_related_spin_off_can_be_discovered_when_extras_enabled(self):
        source = self._item(1, "Re:Zero - Starting Life in Another World", media_format="TV")
        target = self._item(2, "Re:Zero - Starting Break Time", media_format="ONA")
        edge = self._edge("SPIN_OFF", target)
        with patch.object(series, "get", return_value="extras"):
            self.assertTrue(series._traversal_edge_allowed(source, edge))
        with patch.object(series, "get", return_value="main"):
            self.assertFalse(series._traversal_edge_allowed(source, edge))

    def test_unknown_format_is_not_automatically_bundleable(self):
        item = self._item(2, "Unannounced Special", media_format=None)
        self.assertFalse(series._is_bundleable(item))


if __name__ == "__main__":
    unittest.main()
