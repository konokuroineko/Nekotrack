import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.pages.recommendations_page import RecommendationsPage


class RecommendationRefreshLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_refresh_during_active_worker_queues_latest_library_snapshot(self):
        page = RecommendationsPage(embedded=True)
        original_rows = [
            {"id": 1, "type": "ANIME", "title": {"english": "Original"}},
        ]
        updated_rows = [
            *original_rows,
            {"id": 2, "type": "MANGA", "title": {"english": "Newly added"}},
        ]
        latest_rows = [
            {"id": 3, "type": "ANIME", "title": {"english": "Latest snapshot"}},
        ]
        thread = Mock()
        thread.isRunning.return_value = True
        page._thread = thread
        page._library_signature = page._rows_signature(original_rows)
        active_stop_event = page._stop_event

        try:
            page.refresh(library_rows=updated_rows)
            self.assertEqual(page._pending_refresh, (False, updated_rows))
            self.assertTrue(active_stop_event.is_set())

            # A later refresh must replace the queued data and preserve an
            # explicit force-refresh request instead of spawning a second thread.
            page.refresh(force=True, library_rows=latest_rows)
            self.assertEqual(page._pending_refresh, (True, latest_rows))
            self.assertIs(page._thread, thread)

            with patch.object(page, "refresh") as refresh_mock:
                page._thread_finished(thread)

            self.assertIsNone(page._thread)
            self.assertIsNone(page._worker)
            self.assertIsNone(page._pending_refresh)
            refresh_mock.assert_called_once_with(
                force=True,
                library_rows=latest_rows,
            )
        finally:
            page.close()
            page.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
