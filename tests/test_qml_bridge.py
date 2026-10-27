import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import Qt

from ui.qml_bridge import LibraryListModel, QmlApplicationBridge


class LibraryListModelTests(unittest.TestCase):
    def test_model_maps_existing_bundle_data_without_recomputing_grouping(self):
        groups = [{
            "id": 101,
            "title": "Example Show",
            "type": "ANIME",
            "format": "TV",
            "start_year": 2020,
            "status": "Watching",
            "_series_count": 2,
            "_series_progress": 5,
            "_series_episode_total": 26,
            "_bundle_summary": "2 seasons",
            "_series_members": [
                {
                    "id": 101,
                    "episodes": 12,
                    "progress_episodes": 3,
                    "progress_chapters": 14,
                    "progress_volumes": 2,
                },
                {
                    "id": 102,
                    "episodes": 14,
                    "progress_episodes": 2,
                    "progress_chapters": 8,
                    "progress_volumes": 1,
                },
            ],
        }]
        model = LibraryListModel(library_loader=lambda: groups)

        self.assertEqual(model.refresh(), 1)
        self.assertEqual(model.rowCount(), 1)

        index = model.index(0, 0)
        self.assertEqual(model.data(index, Qt.ItemDataRole.DisplayRole), "Example Show")
        self.assertEqual(model.data(index, model.WorkIdRole), 101)
        self.assertEqual(model.data(index, model.TitleRole), "Example Show")
        self.assertEqual(model.data(index, model.MediaTypeRole), "ANIME")
        self.assertEqual(model.data(index, model.StatusRole), "Watching")
        self.assertEqual(model.data(index, model.ProgressEpisodesRole), 5)
        self.assertEqual(model.data(index, model.EpisodeTotalRole), 26)
        self.assertEqual(model.data(index, model.ProgressChaptersRole), 22)
        self.assertEqual(model.data(index, model.ProgressVolumesRole), 3)
        self.assertEqual(model.data(index, model.SeriesCountRole), 2)
        self.assertEqual(model.data(index, model.BundleSummaryRole), "2 seasons")
        self.assertEqual(model.data(index, model.MemberIdsRole), [101, 102])


    def test_member_ids_preserve_canonical_member_order(self):
        model = LibraryListModel(library_loader=lambda: [{
            "id": 99,
            "title": "Older representative",
            "_series_members": [
                {"id": 99, "title": "Older representative"},
                {"id": 5, "title": "Newer entry"},
                {"id": 42, "title": "Middle entry"},
            ],
            "_series_count": 3,
        }])
        self.assertEqual(model.refresh(), 1)
        self.assertEqual(model.data(model.index(0, 0), model.MemberIdsRole), [99, 5, 42])

    def test_status_filter_maps_planned_to_planning_and_restores_all(self):
        model = LibraryListModel(library_loader=lambda: [
            {"id": 1, "title": "Watching", "status": "Watching"},
            {"id": 2, "title": "Completed", "status": "Completed"},
            {"id": 3, "title": "Planned", "status": "Planning"},
        ])
        self.assertEqual(model.refresh(), 3)
        self.assertTrue(model.set_filter("Planned"))
        self.assertEqual(model.rowCount(), 1)
        self.assertEqual(model.data(model.index(0, 0), model.WorkIdRole), 3)
        self.assertTrue(model.set_filter("All"))
        self.assertEqual(model.rowCount(), 3)

    def test_cached_cover_path_wins_over_remote_url_when_file_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            cover = Path(directory) / "cover.jpg"
            cover.write_bytes(b"cached image placeholder")
            model = LibraryListModel(library_loader=lambda: [{
                "id": 7,
                "title": {"romaji": "Cached Cover"},
                "cover_path": str(cover),
                "cover_url": "https://images.example.invalid/remote.jpg",
            }])

            model.refresh()
            source = model.data(model.index(0, 0), model.CoverSourceRole)
            self.assertTrue(source.startswith("file:"))
            self.assertIn("cover.jpg", source)

    def test_invalid_work_rows_are_skipped_and_role_names_are_stable(self):
        model = LibraryListModel(library_loader=lambda: [
            {"title": "Missing id"},
            {"id": 0, "title": "Invalid id"},
            {"id": 9, "title": None},
        ])

        self.assertEqual(model.refresh(), 1)
        self.assertEqual(model.data(model.index(0, 0), model.TitleRole), "Untitled")
        self.assertEqual(model.roleNames()[model.WorkIdRole], b"workId")
        self.assertEqual(model.roleNames()[model.MemberIdsRole], b"memberIds")
        self.assertIsNone(model.data(model.index(4, 0), model.TitleRole))


class QmlApplicationBridgeTests(unittest.TestCase):
    def test_bridge_exposes_model_and_emits_signed_work_ids(self):
        bridge = QmlApplicationBridge(library_loader=lambda: [], auto_refresh=True)
        requested = []
        changed = []
        bridge.openWorkRequested.connect(requested.append)
        bridge.libraryChanged.connect(changed.append)

        self.assertEqual(bridge.libraryModel.rowCount(), 0)
        self.assertTrue(bridge.requestOpenWork(42))
        self.assertTrue(bridge.requestOpenWork(-73))
        self.assertFalse(bridge.requestOpenWork(0))
        self.assertEqual(requested, [42, -73])
        self.assertEqual(changed, [0])

    def test_refresh_errors_are_reported_without_crashing_the_host(self):
        def fail_loader():
            raise RuntimeError("synthetic database read failure")

        bridge = QmlApplicationBridge(library_loader=fail_loader, auto_refresh=False)
        errors = []
        bridge.errorOccurred.connect(errors.append)

        self.assertEqual(bridge.refreshLibrary(), -1)
        self.assertEqual(len(errors), 1)
        self.assertIn("diagnostic log", errors[0])
        self.assertEqual(bridge.libraryModel.rowCount(), 0)


if __name__ == "__main__":
    unittest.main()
