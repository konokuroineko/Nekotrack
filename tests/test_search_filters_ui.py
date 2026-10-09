import os
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from ui.pages.search_page import SearchPage


class SearchFilterUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.page = SearchPage(lambda *_args: None)

    def tearDown(self):
        self.page.close()
        self.page.deleteLater()
        self.app.processEvents()

    def test_publisher_and_licensing_filters_are_disabled_for_anime(self):
        self.page.media_filter.setCurrentText("Anime")
        self.assertFalse(self.page.publisher_filter.isEnabled())
        self.assertFalse(self.page.licensing_filter.isEnabled())
        self.assertTrue(self.page.season_filter.isEnabled())
        self.assertIsNone(self.page.selected_filters()["publisher_id"])
        self.assertIsNone(self.page.selected_filters()["is_licensed"])

    def test_season_is_cleared_when_switching_to_manga(self):
        self.page.season_filter.setCurrentText("Winter")
        self.page.media_filter.setCurrentText("Manga")
        self.assertEqual(self.page.season_filter.currentText(), "All")
        self.assertFalse(self.page.season_filter.isEnabled())

    def test_format_filter_disables_incompatible_provider_filters(self):
        self.page.format_filter.setCurrentText("TV")
        self.page._refresh_filter_availability()
        self.assertFalse(self.page.publisher_filter.isEnabled())
        self.assertFalse(self.page.licensing_filter.isEnabled())
        self.page.format_filter.setCurrentText("Novel")
        self.page._refresh_filter_availability()
        self.assertTrue(self.page.publisher_filter.isEnabled())
        self.assertTrue(self.page.licensing_filter.isEnabled())

    def test_clear_filters_resets_format_and_every_other_filter(self):
        self.page.format_filter.setCurrentText("OVA")
        self.page.status_filter.setCurrentText("Finished")
        self.page.season_filter.setCurrentText("Winter")
        self.page.year_filter.setText("2020")
        self.page.min_score_filter.setCurrentText("80+")
        self.page.sort_filter.setCurrentText("Score")
        self.page.genre_filter.setText("Fantasy, Action")
        self.page.tag_filter.setText("Isekai")
        self.page.publisher_filter.setText("123")
        self.page.licensing_filter.setCurrentText("Licensed only")
        self.page.clear_filters()
        self.assertEqual(self.page.media_filter.currentText(), "All")
        self.assertEqual(self.page.format_filter.currentText(), "All")
        self.assertEqual(self.page.status_filter.currentText(), "All")
        self.assertEqual(self.page.season_filter.currentText(), "All")
        self.assertEqual(self.page.year_filter.text(), "")
        self.assertEqual(self.page.min_score_filter.currentText(), "Any score")
        self.assertEqual(self.page.sort_filter.currentText(), "Relevance")
        self.assertEqual(self.page.genre_filter.text(), "")
        self.assertEqual(self.page.tag_filter.text(), "")
        self.assertEqual(self.page.publisher_filter.text(), "")
        self.assertEqual(self.page.licensing_filter.currentText(), "Any licensing")


if __name__ == "__main__":
    unittest.main()
