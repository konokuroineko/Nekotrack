"""Qt viewport checks for persistent recommendation impressions."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest.mock import patch

from PySide6.QtWidgets import (
    QApplication, QGridLayout, QLabel, QPushButton, QToolButton, QSizePolicy, QWidget,
)

from ui.preferences import get
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

    def test_recommendation_reason_is_inside_the_card_and_layout_respects_settings(self):
        self.page.resize(900, 700)
        self.page._results = [{
            "id": 9877,
            "type": "ANIME",
            "title": {"english": "Compact recommendation"},
            "format": "TV",
            "start_year": 2025,
            "averageScore": 86,
            "_recommendation_reason": "Shares Japanese voice actor Miyuki Sawashiro with A Series You Enjoyed",
        }]
        self.page._history = {}
        self.page.show()
        self.page._render_results(preserve_scroll=False)
        self.app.processEvents()

        card = self.page._tiles[0][0]
        reason = card.findChild(QLabel, "recommendationReason")
        title = card.findChild(QLabel, "title")
        metadata = card.findChild(QLabel, "meta")
        self.assertIsInstance(card, WorkCard)
        self.assertIsNotNone(reason)
        self.assertIsNotNone(title)
        self.assertIsNotNone(metadata)
        self.assertIs(reason.parentWidget(), card)
        self.assertLess(title.y(), reason.y())
        self.assertLess(reason.y(), metadata.y())
        self.assertLess(reason.width(), card.width())

        buttons = [button.text() for button in card.findChildren(QPushButton)]
        self.assertNotIn("♥", buttons)
        self.assertNotIn("♡", buttons)
        self.assertNotIn("×", buttons)
        self.assertNotIn("Like", buttons)
        self.assertNotIn("Not for me", buttons)
        self.assertIsNone(card.findChild(QPushButton, "recommendationLike"))
        self.assertIsNone(card.findChild(QPushButton, "recommendationDislike"))
        menu_button = card.findChild(QToolButton, "recommendationMenuButton")
        self.assertIsNotNone(menu_button)
        self.assertEqual(
            [action.text() for action in menu_button.menu().actions()],
            [
                "I want more like this",
                "I don't want anything from this",
                "I don't want anything like this",
            ],
        )
        self.assertNotIn("recommendationsTile", card.objectName())

        grid = self.page.findChild(QGridLayout)
        self.assertIsNotNone(grid)
        expected_gap = min(120, max(0, int(get("card_gap") or 0)))
        self.assertEqual(grid.horizontalSpacing(), expected_gap)
        self.assertEqual(grid.verticalSpacing(), expected_gap)
        grid_host = self.page.findChild(QWidget, "recommendationsGridHost")
        self.assertIsNotNone(grid_host)
        self.assertEqual(
            grid_host.sizePolicy().horizontalPolicy(),
            QSizePolicy.Policy.Expanding,
        )
        self.assertGreater(grid.columnStretch(0), 0)



    def test_never_show_feedback_is_saved_and_permanently_removes_exact_title(self):
        hidden = {
            "id": 9877,
            "type": "ANIME",
            "title": {"english": "Never show this title"},
            "format": "TV",
            "_recommendation_reason": "Popular anime discovery",
        }
        other = {
            "id": 9878,
            "type": "ANIME",
            "title": {"english": "Another recommendation"},
            "format": "TV",
            "_recommendation_reason": "Popular anime discovery",
        }
        self.page._results = [hidden, other]
        self.page._history = {}
        self.page._catalog_has_next = False
        self.page._favorite_works = []
        self.page._favorite_entities = []
        self.page._credit_profile = {}
        self.page._voice_language = "ALL"
        self.page._refresh_cycle = 1
        self.page.show()
        self.page._render_results(preserve_scroll=False)
        self.app.processEvents()

        with (
            patch(
                "ui.pages.recommendations_page.set_recommendation_feedback",
                return_value=True,
            ) as save_feedback,
            patch(
                "ui.pages.recommendations_page.get_recommendation_history",
                return_value={
                    9877: {
                        "work_id": 9877,
                        "feedback": "never_show",
                        "metadata": hidden,
                        "impressions": 0,
                    }
                },
            ),
        ):
            button = self.page.findChild(QToolButton, "recommendationMenuButton")
            self.assertIsNotNone(button)
            self.assertIsNone(self.page.findChild(QPushButton, "recommendationLike"))
            self.assertIsNone(self.page.findChild(QPushButton, "recommendationDislike"))
            menu = button.menu()
            labels = [action.text() for action in menu.actions()]
            self.assertEqual(labels, [
                "I want more like this",
                "I don't want anything from this",
                "I don't want anything like this",
            ])
            next(action for action in menu.actions()
                 if action.text() == "I don't want anything from this").trigger()

        save_feedback.assert_called_once()
        self.assertEqual(save_feedback.call_args.args[0:2], (9877, "never_show"))
        remaining_ids = [item["id"] for item in self.page._results]
        self.assertNotIn(9877, remaining_ids)
        self.assertIn(9878, remaining_ids)

    def test_empty_catalog_feed_automatically_loads_after_worker_cleanup(self):
        self.page._results = []
        self.page._catalog_has_next = True
        self.page._loading_more = False
        self.page._loaded = True
        self.page._pending_refresh = None
        thread = object()
        self.page._thread = thread
        with (
            patch.object(self.page, "_update_load_more_ui"),
            patch.object(self.page, "_maybe_load_more") as maybe_load_more,
            patch("ui.pages.recommendations_page.QTimer.singleShot") as single_shot,
        ):
            self.page._thread_finished(thread)

        self.assertIsNone(self.page._thread)
        self.assertIsNone(self.page._worker)
        maybe_load_more.assert_not_called()
        self.assertTrue(any(
            len(call.args) == 2
            and call.args[0] == 0
            and getattr(call.args[1], "__self__", None) is self.page
            and getattr(call.args[1], "__name__", "") == "load_more"
            for call in single_shot.call_args_list
        ))

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
        # The test controls the monotonic clock manually; stop the production
        # timer so it cannot consume a side_effect clock value during Qt events.
        self.page._impression_timer.stop()
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
