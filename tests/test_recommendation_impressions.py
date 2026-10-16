"""Qt viewport checks for persistent recommendation impressions."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QGridLayout, QLabel, QPushButton, QWidget

from ui.pages.recommendations_page import RecommendationsPage
from ui.widgets.work_card import WorkCard


class RecommendationImpressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.page = RecommendationsPage()
        self.page._impression_timer.stop()
        self.viewport = QWidget()
        self.viewport.resize(200, 200)
        self.viewport.show()
        self.tile = QWidget(self.viewport)
        self.tile.resize(100, 100)
        self.tile.move(0, 0)
        self.tile.show()
        self.work = {
            "id": 9876,
            "type": "ANIME",
            "title": {"english": "Visible title"},
        }
        self.page._visibility_viewport = self.viewport
        self.page._tiles = [(self.tile, self.work)]
        self.page._exposure_visible_since.clear()
        self.page._exposure_counted.clear()
        self.app.processEvents()

    def tearDown(self):
        self.page._shutting_down = True
        self.page._impression_timer.stop()
        self.page.close()
        self.viewport.close()
        self.page.deleteLater()
        self.app.processEvents()

    def test_empty_feed_keeps_pagination_available_when_catalog_has_more(self):
        self.page._results = []
        self.page._catalog_has_next = True
        self.page._loading_more = False
        self.page._load_more_failed = False
        self.page._render_results()
        self.assertIsNotNone(self.page.load_more_button)
        self.assertTrue(self.page.load_more_button.isEnabled())
        self.assertEqual(self.page.load_more_button.text(), "Load more")

    def test_recommendation_cards_are_compact_without_heart_or_dislike_buttons(self):
        self.page.resize(900, 700)
        self.page._results = [{
            "id": 9877,
            "type": "ANIME",
            "title": {"english": "Compact recommendation"},
            "_recommendation_reason": "Shares Japanese voice actor Miyuki Sawashiro with A Series You Enjoyed",
        }]
        self.page._history = {}
        self.page.show()
        self.page._render_results(preserve_scroll=False)
        self.app.processEvents()

        tile = self.page._tiles[0][0]
        card = tile.findChild(WorkCard)
        reason = tile.findChild(QLabel, "recommendationsReason")
        self.assertIsNotNone(card)
        self.assertIsNotNone(reason)
        self.assertEqual(tile.width(), card.width())
        self.assertEqual(reason.width(), card.width())

        buttons = [button.text() for button in tile.findChildren(QPushButton)]
        self.assertNotIn("♥", buttons)
        self.assertNotIn("♡", buttons)
        self.assertNotIn("×", buttons)
        self.assertNotIn("QFrame#recommendationsTile:hover", self.page.styleSheet())

        grid = self.page.findChild(QGridLayout)
        self.assertIsNotNone(grid)
        self.assertEqual(grid.horizontalSpacing(), 12)
        self.assertEqual(grid.verticalSpacing(), 14)

    def test_offscreen_tile_does_not_gain_an_impression(self):
        self.tile.move(300, 0)
        self.app.processEvents()
        with (
            patch("ui.pages.recommendations_page.time.monotonic", return_value=10.0),
            patch("ui.pages.recommendations_page.record_recommendation_impressions") as record,
        ):
            self.page._track_visible_impressions()
        record.assert_not_called()
        self.assertNotIn(9876, self.page._exposure_visible_since)

    def test_impression_requires_dwell_and_repainting_does_not_inflate_count(self):
        with (
            patch("ui.pages.recommendations_page.record_recommendation_impressions") as record,
            patch(
                "ui.pages.recommendations_page.get_recommendation_history",
                return_value={9876: {"impressions": 1}},
            ),
            patch(
                "ui.pages.recommendations_page.time.monotonic",
                side_effect=[10.0, 10.5, 11.3, 15.0],
            ),
        ):
            self.page._track_visible_impressions()
            record.assert_not_called()
            self.page._track_visible_impressions()
            record.assert_not_called()
            self.page._track_visible_impressions()
            record.assert_called_once_with([self.work])
            self.page._track_visible_impressions()
            record.assert_called_once_with([self.work])
        self.assertTrue(self.page._exposure_counted[9876])

    def test_scrolling_away_and_returning_allows_a_distinct_later_impression(self):
        with (
            patch("ui.pages.recommendations_page.record_recommendation_impressions") as record,
            patch(
                "ui.pages.recommendations_page.get_recommendation_history",
                return_value={9876: {"impressions": 1}},
            ),
            patch(
                "ui.pages.recommendations_page.time.monotonic",
                side_effect=[1.0, 2.4, 3.0, 4.0, 5.5],
            ),
        ):
            self.page._track_visible_impressions()
            self.page._track_visible_impressions()
            record.assert_called_once_with([self.work])

            self.tile.move(300, 0)
            self.page._track_visible_impressions()
            self.assertFalse(self.page._exposure_counted[9876])

            self.tile.move(0, 0)
            self.page._track_visible_impressions()
            self.page._track_visible_impressions()
            self.assertEqual(record.call_count, 2)
            self.assertEqual(record.call_args_list[-1].args, ([self.work],))


if __name__ == "__main__":
    unittest.main()
