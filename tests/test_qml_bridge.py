import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ui.qml_bridge import LibraryListModel, QmlApplicationBridge


_APP = QApplication.instance() or QApplication([])


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
        self.assertEqual(model.data(model.index(0, 0), model.TitleRole), "Untitled · 9")
        self.assertEqual(model.roleNames()[model.WorkIdRole], b"workId")
        self.assertEqual(model.roleNames()[model.MemberIdsRole], b"memberIds")
        self.assertIsNone(model.data(model.index(4, 0), model.TitleRole))


class QmlApplicationBridgeTests(unittest.TestCase):
    def test_bridge_exposes_model_and_emits_signed_work_ids(self):
        bridge = QmlApplicationBridge(library_loader=lambda: [], auto_refresh=False)
        requested = []
        changed = []
        bridge.openWorkRequested.connect(requested.append)
        bridge.libraryChanged.connect(changed.append)

        self.assertEqual(bridge.refreshLibrary(), 0)
        self.assertEqual(bridge.libraryModel.rowCount(), 0)
        self.assertTrue(bridge.requestOpenWork(42))
        self.assertTrue(bridge.requestOpenWork(-73))
        self.assertFalse(bridge.requestOpenWork(0))
        self.assertEqual(requested, [42, -73])
        self.assertEqual(changed, [0])


    def test_exact_default_card_geometry_matches_work_card(self):
        from unittest.mock import patch

        values = {
            "card_size": 210,
            "card_gap": 24,
            "corner_radius": 12,
            "font_size": 13,
            "hover_highlight": True,
        }
        with patch("ui.qml_bridge.get", side_effect=lambda key: values[key]):
            bridge = QmlApplicationBridge(library_loader=lambda: [], auto_refresh=False)

        self.assertEqual(bridge.cardSize, 210)
        self.assertEqual(bridge.coverHeight, 284)
        self.assertEqual(bridge.cardGap, 24)
        self.assertEqual(bridge.cornerRadius, 12)
        self.assertEqual(bridge.fontSize, 13)
        self.assertTrue(bridge.hoverHighlight)

    def test_card_width_and_poster_height_match_the_original_work_card(self):
        from unittest.mock import patch

        values = {
            "card_size": 400,
            "card_gap": 24,
            "corner_radius": 12,
            "font_size": 13,
            "hover_highlight": True,
        }
        with patch("ui.qml_bridge.get", side_effect=lambda key: values[key]):
            bridge = QmlApplicationBridge(library_loader=lambda: [], auto_refresh=False)

        self.assertEqual(bridge.cardSize, 270)
        self.assertEqual(bridge.coverHeight, round(270 * 284 / 210))


    def test_search_filters_are_preserved_and_fast_search_is_forwarded(self):
        from unittest.mock import patch

        from ui.qml_app_bridge import ApplicationBridge

        bridge = ApplicationBridge()
        filters = {
            "status": "FINISHED",
            "season": "WINTER",
            "year": "2024",
            "sort": "SCORE_DESC",
            "min_score": 80,
            "genre": "Mystery",
            "tag": "Time Travel",
            "publisher_id": "12",
            "is_licensed": False,
            "fast_search": True,
        }
        with patch.object(bridge, "_start_catalog_page") as start_search:
            bridge.searchCatalogWithFilters("Example", "ANIME", "", filters)

        self.assertEqual(bridge._search_filters, filters)
        self.assertEqual(bridge._search_type, "ANIME")
        self.assertEqual(bridge._search_query, "Example")
        self.assertEqual(bridge._search_page, 1)
        start_search.assert_called_once_with(1, 1)
        self.assertTrue(bridge.animationSpeed >= 0)
        self.assertIn(bridge.uiScale, {80, 90, 100, 110, 125, 150, 175, 200})


    def test_startup_does_not_start_recommendations_until_visible(self):
        from unittest.mock import patch

        from ui.qml_app_bridge import ApplicationBridge

        bridge = ApplicationBridge()
        bridge._groups_loaded = True
        with patch.object(bridge, "refreshRecommendations") as refresh_recommendations:
            bridge.refreshHome()
            refresh_recommendations.assert_not_called()
            bridge.markStartupReady()
            refresh_recommendations.assert_called_once_with()

    def test_exact_default_theme_geometry_values(self):
        from unittest.mock import patch

        from ui.qml_app_bridge import ApplicationBridge

        values = {
            "card_size": 210,
            "card_gap": 24,
            "corner_radius": 12,
            "font_size": 13,
            "hover_highlight": True,
            "resize_animation": True,
            "animation_speed": 260,
            "ui_scale": 100,
        }
        with patch("ui.qml_bridge.get", side_effect=lambda key: values[key]), \
             patch("ui.qml_app_bridge.get", side_effect=lambda key: values[key]):
            bridge = ApplicationBridge()

        self.assertEqual(bridge.cardSize, 210)
        self.assertEqual(bridge.coverHeight, 284)
        self.assertEqual(bridge.cardGap, 24)
        self.assertEqual(bridge.cornerRadius, 12)
        self.assertEqual(bridge.fontSize, 13)
        self.assertEqual(bridge.animationSpeed, 260)
        self.assertEqual(bridge.uiScale, 100)


    def test_application_bridge_exposes_update_and_discovery_defaults(self):
        from unittest.mock import patch

        from ui.preferences import defaults
        from ui.qml_app_bridge import ApplicationBridge

        default_values = defaults()
        with patch("ui.qml_bridge.get", side_effect=lambda key: default_values[key]), \
             patch("ui.qml_app_bridge.get", side_effect=lambda key: default_values[key]):
            bridge = ApplicationBridge()
            self.assertTrue(bridge.autoCheckUpdates)
            self.assertEqual(bridge.updateChannel, "stable")
            self.assertEqual(bridge.recommendationVoiceLanguage, "ALL")
            self.assertEqual(bridge.tmdbApiToken, "")
            self.assertTrue(bridge.maximized)
            groups = bridge.bundleOptionGroups
        self.assertEqual([group["title"] for group in groups], ["ANIME EXTRAS", "MANGA & LITERATURE"])
        self.assertEqual(
            [option["key"] for group in groups for option in group["options"]],
            [
                "bundle_include_movies",
                "bundle_include_ovas",
                "bundle_include_onas",
                "bundle_include_specials",
                "bundle_include_manga",
                "bundle_include_novels",
                "bundle_include_one_shots",
            ],
        )


    def test_profile_decorator_maps_favorite_state_and_linked_works(self):
        from unittest.mock import patch

        from ui.qml_app_bridge import ApplicationBridge

        bridge = ApplicationBridge()
        bridge._selected_profile = {
            "id": 88,
            "entity_type": "character",
            "name": {"full": "Example Character"},
            "gender": "Female",
            "media": {
                "edges": [{
                    "characterRole": "MAIN",
                    "node": {
                        "id": 123,
                        "type": "ANIME",
                        "format": "TV",
                        "title": {"english": "Example Series"},
                        "coverImage": {"large": "https://images.example.invalid/cover.jpg"},
                        "startDate": {"year": 2020},
                    },
                }],
            },
        }
        with patch("ui.qml_app_bridge.is_entity_favorite", return_value=True):
            bridge._decorate_selected_profile()

        self.assertEqual(bridge._selected_profile["displayName"], "Example Character")
        self.assertTrue(bridge._selected_profile["isFavorite"])
        self.assertEqual(bridge._selected_profile["factItems"][0], {
            "label": "Gender", "value": "Female"
        })
        work = bridge._selected_profile["workItems"][0]
        self.assertEqual(work["title"], "Example Series")
        self.assertEqual(work["section"], "Appears in")
        self.assertEqual(work["mediaType"], "ANIME")
        self.assertEqual(work["startYear"], 2020)
        self.assertEqual(work["coverSource"], "https://images.example.invalid/cover.jpg")


    def test_detail_snapshot_worker_aggregates_episodes_for_all_bundle_members(self):
        from unittest.mock import patch

        from ui.qml_app_bridge import _DetailSnapshotWorker

        snapshots = {
            101: {
                "work": {"title": "Season One", "episodes": 12, "progress_episodes": 4},
                "episodes": [{
                    "episode_number": 1,
                    "title": "Episode One",
                    "watched": True,
                    "air_date": "2020-01-01",
                }],
            },
            202: {
                "work": {"title": "Season Two", "episodes": 10, "progress_episodes": 2},
                "episodes": [{
                    "episode_number": 1,
                    "title": "Episode Two",
                    "watched": False,
                    "air_date": "2021-01-01",
                }],
            },
        }
        results = []
        worker = _DetailSnapshotWorker(7, 101, [101, 202], {101: "Season One", 202: "Season Two"})
        worker.signals.finished.connect(lambda generation, payload, error: results.append((generation, payload, error)))

        with patch("ui.qml_app_bridge.get_episode_section_snapshot", side_effect=lambda work_id: snapshots[work_id]), \
             patch("ui.qml_app_bridge.get_bundle_characters", return_value=[]), \
             patch("ui.qml_app_bridge.get_bundle_staff", return_value=[]), \
             patch("ui.qml_app_bridge.get_bundle_relations", return_value=[]), \
             patch("ui.qml_app_bridge.get_reading_progress", return_value=(0, 0)):
            worker.run()

        self.assertEqual(len(results), 1)
        generation, payload, error = results[0]
        self.assertEqual(generation, 7)
        self.assertIsNone(error)
        self.assertEqual([item["workId"] for item in payload["episodes"]], [101, 202])
        self.assertEqual([item["workTitle"] for item in payload["episodes"]], ["Season One", "Season Two"])
        self.assertEqual(payload["progressEpisodes"], 6)
        self.assertEqual(payload["episodeTotal"], 22)
        self.assertEqual(payload["readingProgressByWork"]["101"]["chapters"], 0)
        self.assertEqual(payload["readingProgressByWork"]["202"]["volumes"], 0)


    def test_active_ui_scale_requires_restart_after_scale_preference_changes(self):
        from unittest.mock import patch

        from ui.preferences import defaults
        from ui.qml_app_bridge import ApplicationBridge

        default_values = defaults()
        with patch.dict("os.environ", {"QT_SCALE_FACTOR": "1.0"}), \
             patch("ui.qml_bridge.get", side_effect=lambda key: default_values[key]), \
             patch("ui.qml_app_bridge.get", side_effect=lambda key: default_values[key]):
            bridge = ApplicationBridge()
            self.assertEqual(bridge.activeUiScale, 100)
            bridge.setPreference("ui_scale", 125)
            self.assertEqual(bridge.uiScale, 125)
            self.assertEqual(bridge.activeUiScale, 100)
            requested = []
            bridge.restartRequested.connect(lambda: requested.append(True))
            bridge.requestRestart()

        self.assertEqual(requested, [True])


    def test_detail_selects_only_manga_and_novel_members_for_reading_progress(self):
        from unittest.mock import patch

        from ui.qml_app_bridge import ApplicationBridge

        group = {
            "id": 101,
            "title": {"romaji": "Example"},
            "type": "ANIME",
            "_series_count": 3,
            "_series_members": [
                {"id": 101, "title": {"romaji": "Anime Season"}, "type": "ANIME", "format": "TV"},
                {"id": 202, "title": {"romaji": "Manga"}, "type": "MANGA", "format": "MANGA"},
                {"id": 303, "title": {"romaji": "Novel"}, "type": "MANGA", "format": "NOVEL"},
            ],
        }
        bridge = ApplicationBridge()
        with patch("ui.qml_app_bridge.is_work_in_library", return_value=True), \
             patch("ui.qml_app_bridge.QThreadPool.globalInstance") as pool:
            bridge._raw_groups = [group]
            bridge.setSelectedWork(group)
            self.assertEqual(
                [item["id"] for item in bridge._selected_work["readingMembers"]],
                [202, 303],
            )
            pool.return_value.start.assert_called_once()

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
