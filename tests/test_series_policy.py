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

    def _options(self, **enabled):
        return lambda key: bool(enabled.get(key, False))

    def test_unrelated_cross_format_prequel_is_rejected(self):
        source = self._item(1, "One Piece", media_format="TV")
        target = self._item(2, "Monsters: 103 Mercies Dragon Damnation", media_format="MOVIE")
        edge = self._edge("PREQUEL", target)
        self.assertFalse(series._relation_group_compatible(source, edge, target))

    def test_explicit_side_story_is_excluded_when_ova_is_disabled(self):
        source = self._item(1, "Attack on Titan", media_format="TV")
        target = self._item(2, "Attack on Titan OVA", media_format="OVA")
        edge = self._edge("SIDE_STORY", target)
        with patch.object(series, "get", side_effect=self._options()):
            self.assertFalse(series._relation_group_compatible(source, edge, target))

    def test_explicit_side_story_can_cross_formats_when_ova_is_enabled(self):
        source = self._item(1, "Attack on Titan", media_format="TV")
        target = self._item(2, "Attack on Titan OVA", media_format="OVA")
        edge = self._edge("SIDE_STORY", target)
        with patch.object(series, "get", side_effect=self._options(bundle_include_ovas=True)):
            self.assertTrue(series._relation_group_compatible(source, edge, target))

    def test_related_ona_can_be_discovered_without_enabling_other_extras(self):
        source = self._item(1, "Re:Zero - Starting Life in Another World", media_format="TV")
        target = self._item(2, "Re:Zero - Starting Break Time", media_format="ONA")
        edge = self._edge("SPIN_OFF", target)
        with patch.object(series, "get", side_effect=self._options(bundle_include_onas=True)):
            self.assertTrue(series._traversal_edge_allowed(source, edge))
            self.assertTrue(series._auto_bundleable(target))
            movie = self._item(3, "Re:Zero Movie", media_format="MOVIE")
            ova = self._item(4, "Re:Zero OVA", media_format="OVA")
            special = self._item(5, "Re:Zero Special", media_format="SPECIAL")
            self.assertFalse(series._auto_bundleable(movie))
            self.assertFalse(series._auto_bundleable(ova))
            self.assertFalse(series._auto_bundleable(special))

    def test_manga_and_novels_require_their_own_options(self):
        manga = self._item(5, "Example Manga", media_type="MANGA", media_format="MANGA")
        novel = self._item(6, "Example Light Novel", media_type="MANGA", media_format="NOVEL")
        one_shot = self._item(7, "Example One-shot", media_type="MANGA", media_format="ONE_SHOT")
        with patch.object(series, "get", side_effect=self._options()):
            self.assertFalse(series._auto_bundleable(manga))
            self.assertFalse(series._auto_bundleable(novel))
            self.assertFalse(series._auto_bundleable(one_shot))
        with patch.object(
            series,
            "get",
            side_effect=self._options(
                bundle_include_manga=True,
                bundle_include_novels=True,
                bundle_include_one_shots=False,
            ),
        ):
            self.assertTrue(series._auto_bundleable(manga))
            self.assertTrue(series._auto_bundleable(novel))
            self.assertFalse(series._auto_bundleable(one_shot))

    def test_unknown_format_is_not_automatically_bundleable(self):
        item = self._item(2, "Unannounced Special", media_format=None)
        self.assertFalse(series._is_bundleable(item))


if __name__ == "__main__":
    unittest.main()
