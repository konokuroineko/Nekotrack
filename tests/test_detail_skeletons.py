import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QLabel

from ui.pages.work_detail_page import WorkDetailPage


class DetailSkeletonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_pending_detail_view_uses_section_and_episode_skeletons(self):
        page = WorkDetailPage()
        with (
            patch.object(page, "_local_detail_ready", return_value=(False, False)),
            patch.object(page, "_hero", return_value=QFrame()),
            patch.object(page, "_mangabaka_section", return_value=None),
            patch.object(page, "_is_reading_media", return_value=False),
        ):
            content, ready = page._build_detail_content([12345], defer_missing=False)

        self.assertFalse(ready)
        section_titles = {
            frame.property("_skeleton_section_title")
            for frame in content.findChildren(QFrame, "detailSkeletonSection")
        }
        self.assertEqual(section_titles, {"Characters", "Staff", "Relations"})
        self.assertEqual(
            len(content.findChildren(QFrame, "detailSkeletonEpisodeCard")),
            4,
        )
        self.assertIsNotNone(
            content.findChild(QLabel, "detailEpisodeLoadingLabel")
        )
        self.assertFalse(
            any(label.text() == "Loading details…" for label in content.findChildren(QLabel))
        )

        content.deleteLater()
        page.deleteLater()
        self.app.processEvents()

    def test_hero_cover_distinguishes_loading_from_unavailable(self):
        page = WorkDetailPage()
        page._apply_detail_styles()
        label = QLabel(page)
        label.setObjectName("detailHeroCover")
        label.resize(235, 335)

        page._set_cover_placeholder(label, True, "Loading artwork…")
        self.assertTrue(label.property("coverLoading"))
        self.assertEqual(label.text(), "Loading artwork…")

        page._set_cover_placeholder(label, False, "COVER UNAVAILABLE")
        self.assertFalse(label.property("coverLoading"))
        self.assertEqual(label.text(), "COVER UNAVAILABLE")

        page._set_cover_placeholder(label, False, "NO COVER")
        self.assertFalse(label.property("coverLoading"))
        self.assertEqual(label.text(), "NO COVER")
        page.deleteLater()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
