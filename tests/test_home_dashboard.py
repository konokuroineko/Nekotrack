import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QFrame, QWidget

from ui.pages.home_page import HomePage
from ui.pages.recommendations_page import RecommendationsPage


class HomeDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_home_removes_hero_and_summary_cards_and_embeds_recommendations(self):
        with (
            patch.object(HomePage, "_read_library", return_value=[]),
            patch.object(RecommendationsPage, "refresh", autospec=True),
        ):
            page = HomePage()

        try:
            page.show()
            self.app.processEvents()
            self.assertTrue(page.recommendations_page.embedded)
            self.assertEqual(page.content_layout.indexOf(page.recommendations_page), 2)
            self.assertIs(
                page.content.findChild(RecommendationsPage),
                page.recommendations_page,
            )
            self.assertIsNone(page.content.findChild(QFrame, "homeHero"))
            self.assertIsNone(page.content.findChild(QWidget, "homeStatsRow"))
            texts = {label.text() for label in page.findChildren(QLabel)}
            self.assertNotIn("YOUR PERSONAL MEDIA SPACE", texts)
            self.assertFalse(
                {"ALL TITLES", "IN PROGRESS", "COMPLETED", "PLANNED"} & texts
            )
        finally:
            page.close()
            page.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
