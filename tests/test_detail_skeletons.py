import os
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication, QBoxLayout, QFrame, QHBoxLayout, QLabel, QPushButton,
    QToolButton, QVBoxLayout, QWidget, QWidgetAction,
)

from api import (
    TMDB_EPISODE_CATALOG_REFRESH_INTERVAL_SECONDS,
    TMDB_EPISODE_CATALOG_VERSION,
)
from ui.pages.work_detail_page import EpisodeArtwork, EpisodeCard, WorkDetailPage


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

    def test_missing_catalog_work_is_not_treated_as_an_empty_season(self):
        page = WorkDetailPage()
        page.work = {
            "id": 12345,
            "type": "ANIME",
            "format": "TV",
        }

        with (
            patch("ui.pages.work_detail_page.characters_are_loaded", return_value=False),
            patch("ui.pages.work_detail_page.get_work", return_value=None),
            patch("ui.pages.work_detail_page.get_episodes", return_value=[]),
        ):
            self.assertEqual(page._local_detail_ready([12345]), (False, False))

        page.deleteLater()
        self.app.processEvents()

    def test_episode_section_waits_when_selected_season_row_is_missing(self):
        page = WorkDetailPage()
        page.work = {
            "id": 12345,
            "type": "ANIME",
            "format": "TV",
            "episodes": 12,
            "title": {"romaji": "Example Series", "english": None},
            "_series_members": [{
                "id": 12345,
                "title": {"romaji": "Example Series", "english": None},
                "start_year": 2020,
                "start_month": 1,
                "start_day": 1,
                "episodes": 12,
                "format": "TV",
            }],
        }
        page._selected_episode_work_id = 12345

        with (
            patch("ui.pages.work_detail_page.get_work", return_value=None),
            patch("ui.pages.work_detail_page.get_episodes", return_value=[]),
            patch.object(page, "_start_episode_sync") as sync,
        ):
            frame = page._episodes_section()

        self.assertIsNotNone(
            frame.findChild(QLabel, "detailEpisodeLoadingLabel")
        )
        sync.assert_not_called()
        frame.deleteLater()
        page.deleteLater()
        self.app.processEvents()

    def test_deferred_episode_render_retries_pending_import_without_crashing(self):
        page = WorkDetailPage()
        page.work = {
            "id": 12345,
            "type": "ANIME",
            "format": "TV",
            "_series_members": [{"id": 12345}],
        }
        page._detail_build_token = 7
        content = QWidget()
        layout = QVBoxLayout(content)
        host = QFrame(content)
        layout.addWidget(host)
        page.scroll_area.setWidget(content)
        callbacks = []

        with (
            patch("ui.pages.work_detail_page.get_work", return_value=None),
            patch(
                "ui.pages.work_detail_page.QTimer.singleShot",
                side_effect=lambda delay, callback: callbacks.append((delay, callback)),
            ),
        ):
            page._populate_episode_section(7, content, host)

        self.assertEqual(len(callbacks), 1)
        self.assertEqual(callbacks[0][0], 250)
        self.assertGreaterEqual(layout.indexOf(host), 0)

        page.deleteLater()
        self.app.processEvents()

    def test_deferred_episode_render_shows_recovery_message_after_timeout(self):
        page = WorkDetailPage()
        page.work = {
            "id": 12345,
            "type": "ANIME",
            "format": "TV",
            "_series_members": [{"id": 12345}],
        }
        page._detail_build_token = 9
        content = QWidget()
        layout = QVBoxLayout(content)
        host = QFrame(content)
        layout.addWidget(host)
        page.scroll_area.setWidget(content)

        with patch("ui.pages.work_detail_page.get_work", return_value=None):
            page._populate_episode_section(9, content, host, attempt=120)

        replacement = content.findChild(QFrame, "section")
        self.assertIsNotNone(replacement)
        self.assertTrue(any(
            "taking longer than expected" in label.text()
            for label in replacement.findChildren(QLabel)
        ))

        page.deleteLater()
        self.app.processEvents()

    def test_ready_detail_defers_episode_cards_until_page_is_attached(self):
        page = WorkDetailPage()
        page.work = {
            "id": 12345,
            "type": "ANIME",
            "format": "TV",
            "title": {"english": "Bundled season"},
            "_series_members": [{"id": 12345}],
        }
        page._selected_episode_work_id = 12345
        episode_frame = QFrame()
        QVBoxLayout(episode_frame)
        episode_frame.setProperty("_episodes_section", True)
        episode_frame._pending_episode_cards = [
            {
                "work_id": 12345,
                "episode_number": number,
                "title": f"Episode {number}",
                "description": "",
                "air_date": "",
                "thumbnail_url": None,
                "watched": 0,
            }
            for number in range(1, 14)
        ]

        with (
            patch.object(page, "_local_detail_ready", return_value=(True, True)),
            patch.object(page, "_hero", return_value=QFrame()),
            patch.object(page, "_mangabaka_section", return_value=None),
            patch.object(page, "_is_reading_media", return_value=False),
            patch.object(page, "_episodes_section", return_value=episode_frame) as episodes,
            patch.object(page, "_build_detail_sections_local"),
        ):
            content, ready = page._build_detail_content([12345], defer_missing=False)

        self.assertTrue(ready)
        episodes.assert_called_once_with(defer_cards=True)
        self.assertEqual(content.findChildren(EpisodeCard), [])
        page.scroll_area.setWidget(content)

        with patch("ui.pages.work_detail_page.QTimer.singleShot") as schedule:
            page._queue_pending_episode_cards(content)
            self.assertEqual(content.findChildren(EpisodeCard), [])
            callback = schedule.call_args.args[1]
            with patch("ui.pages.work_detail_page.QTimer.singleShot") as next_batch:
                callback()
                self.assertEqual(len(content.findChildren(EpisodeCard)), 6)
                next_batch.assert_called_once()

        page.deleteLater()
        self.app.processEvents()

    def test_episode_rows_are_compact_and_hide_empty_synopsis(self):
        episode = {
            "work_id": 12345,
            "episode_number": 1,
            "thumbnail_url": None,
            "air_date": None,
            "title": "Episode title",
            "description": "",
            "watched": 0,
        }
        card = EpisodeCard(episode)
        artwork = card.findChild(EpisodeArtwork)
        description = card.findChild(QLabel, "detailEpisodeDescription")

        self.assertLessEqual(card.minimumHeight(), 64)
        self.assertEqual(artwork.size().width(), 96)
        self.assertEqual(artwork.size().height(), 54)
        # Empty synopses are omitted entirely rather than taking up row space.
        self.assertIsNone(description)

        card.deleteLater()
        self.app.processEvents()

    def test_episode_catalog_refresh_interval_uses_fetch_timestamp(self):
        page = WorkDetailPage()
        now = 2_000_000_000
        recent = {
            "version": TMDB_EPISODE_CATALOG_VERSION,
            "fetched_at": now - 60,
        }
        stale = {
            "version": TMDB_EPISODE_CATALOG_VERSION,
            "fetched_at": now - TMDB_EPISODE_CATALOG_REFRESH_INTERVAL_SECONDS - 1,
        }

        with patch("ui.pages.work_detail_page.get_provider_metadata", return_value=recent), patch(
            "ui.pages.work_detail_page.time.time", return_value=now
        ):
            self.assertFalse(page._episode_catalog_is_stale(12345))
        with patch("ui.pages.work_detail_page.get_provider_metadata", return_value=stale), patch(
            "ui.pages.work_detail_page.time.time", return_value=now
        ):
            self.assertTrue(page._episode_catalog_is_stale(12345))
        with patch("ui.pages.work_detail_page.get_provider_metadata", return_value={"version": 3}), patch(
            "ui.pages.work_detail_page.time.time", return_value=now
        ):
            self.assertTrue(page._episode_catalog_is_stale(12345))

        page.deleteLater()
        self.app.processEvents()

    def test_empty_episode_sync_keeps_last_good_mapping_and_catalog(self):
        page = WorkDetailPage()
        with (
            patch("ui.pages.work_detail_page.save_tmdb_mapping") as save_mapping,
            patch("ui.pages.work_detail_page.save_episodes") as save_episodes,
            patch("ui.pages.work_detail_page.save_provider_metadata") as save_metadata,
            patch("ui.pages.work_detail_page.prune_episode_catalog") as prune,
            patch.object(page, "_start_episode_image_cache"),
            patch.object(page, "_replace_episode_section"),
        ):
            page._episode_sync_finished(
                12345,
                {"episodes": [], "tmdb_count": 0, "tmdb_id": 99, "tmdb_season_number": 2},
            )

        save_mapping.assert_not_called()
        save_episodes.assert_not_called()
        save_metadata.assert_not_called()
        prune.assert_not_called()
        page.deleteLater()
        self.app.processEvents()

    def test_successful_episode_sync_prunes_and_records_refresh_time(self):
        page = WorkDetailPage()
        now = 2_000_000_000
        episodes = [{
            "episodeNumber": 1,
            "title": "Episode One",
            "description": None,
            "airdate": "2020-01-01",
            "thumbnail": None,
        }]
        with (
            patch("ui.pages.work_detail_page.save_episodes") as save_episodes,
            patch("ui.pages.work_detail_page.save_tmdb_mapping") as save_mapping,
            patch("ui.pages.work_detail_page.save_provider_metadata") as save_metadata,
            patch("ui.pages.work_detail_page.prune_episode_catalog") as prune,
            patch("ui.pages.work_detail_page.time.time", return_value=now),
            patch.object(page, "_start_episode_image_cache"),
            patch.object(page, "_replace_episode_section"),
        ):
            page._episode_sync_finished(
                12345,
                {
                    "episodes": episodes,
                    "tmdb_count": 1,
                    "tmdb_id": 99,
                    "tmdb_season_number": 1,
                },
            )

        save_episodes.assert_called_once_with(12345, episodes)
        save_mapping.assert_called_once_with(12345, 99, 1)
        prune.assert_called_once_with(12345, episodes)
        save_metadata.assert_called_once_with(
            12345,
            "tmdb_episode_match_version",
            {
                "version": TMDB_EPISODE_CATALOG_VERSION,
                "fetched_at": now,
            },
        )
        page.deleteLater()
        self.app.processEvents()

    def test_episode_synopses_are_single_line_with_full_tooltip(self):
        synopsis = "A long synopsis that should stay compact in the episode list."
        card = EpisodeCard({
            "work_id": 12345,
            "episode_number": 12,
            "thumbnail_url": None,
            "air_date": None,
            "title": "A very long episode title",
            "description": synopsis,
            "watched": 0,
        })
        description = card.findChild(QLabel, "detailEpisodeDescription")
        self.assertIsNotNone(description)
        self.assertFalse(description.wordWrap())
        self.assertEqual(description.toolTip(), synopsis)
        self.assertLess(card.minimumHeight(), 80)

        card.deleteLater()
        self.app.processEvents()

    def test_artwork_menu_is_on_far_right_in_rtl_and_customize_is_inside_it(self):
        page = WorkDetailPage()
        values = {
            "id": 12345,
            "type": "ANIME",
            "format": "TV",
            "episodes": 12,
            "chapters": None,
            "volumes": None,
            "title": {"english": "Example Title"},
            "title_native": None,
            "native": None,
            "description": "Example synopsis",
            "_series_members": [],
            "_series_count": 1,
            "cover_path": None,
            "cover_url": None,
            "coverImage": None,
            "start_year": 2025,
            "score": None,
            "averageScore": None,
        }
        page._value = lambda key: values.get(key)
        page._title = lambda: "Example Title"
        page._is_reading_media = lambda: False
        page.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        try:
            with (
                patch("ui.pages.work_detail_page.get_display_override", return_value={}),
                patch.object(page, "_load_remote_cover"),
                patch("ui.pages.work_detail_page.get_library_series", return_value=[]),
            ):
                hero = page._hero()
                row = hero.findChild(QHBoxLayout, "detailHeroTitleRow")
                self.assertIsNotNone(row)
                self.assertEqual(row.direction(), QBoxLayout.Direction.LeftToRight)
                self.assertEqual(row.itemAt(row.count() - 1).widget().objectName(), "detailMenu")
                self.assertIsNone(hero.findChild(QPushButton, "detailFavoriteButton"))

                menu_button = hero.findChild(QToolButton, "detailMenu")
                self.assertIsNotNone(menu_button)
                self.assertEqual(menu_button.accessibleName(), "More artwork actions")

                menu = page._build_detail_menu()
                self.assertIsNotNone(menu)
                menu_labels = []
                for action in menu.actions():
                    if isinstance(action, QWidgetAction):
                        button = action.defaultWidget()
                        if isinstance(button, QPushButton):
                            menu_labels.append(button.text())
                self.assertIn("Customize title and cover…", menu_labels)
                self.assertFalse(any(
                    button.text() == "Customize title and cover…"
                    for button in hero.findChildren(QPushButton)
                ))
                menu.deleteLater()
                hero.deleteLater()
        finally:
            page.close()
            page.deleteLater()
            self.app.processEvents()


    def test_bundle_episode_section_skips_bad_members_and_malformed_episode_rows(self):
        page = WorkDetailPage()
        page.work = {
            "id": 12345,
            "type": "ANIME",
            "format": "TV",
            "episodes": 2,
            "title": {"english": "Bundle Season"},
            "_series_members": [
                {"id": "not-a-work-id", "title": {"english": "Broken member"}},
                {"id": 12345, "title": {"english": "Bundle Season"},
                 "start_year": 2020, "start_month": 1, "start_day": 1},
            ],
        }
        page._selected_episode_work_id = 12345
        page._episode_sync_completed.add(12345)
        rows = [
            {"work_id": 12345, "episode_number": True, "title": "Boolean"},
            {"work_id": 12345, "episode_number": 1.5, "title": "Fractional"},
            {"work_id": 12345, "episode_number": "bad", "title": "Invalid"},
            {"work_id": 12345, "episode_number": 1, "title": "Valid", "watched": 0},
            {"work_id": 12345, "episode_number": 1, "title": "Duplicate", "watched": 1},
        ]
        with (
            patch("ui.pages.work_detail_page.get_episodes", return_value=rows),
            patch("ui.pages.work_detail_page.get_work", return_value={
                "id": 12345, "title": {"english": "Bundle Season"}, "episodes": 2,
                "format": "TV", "start_year": 2020, "start_month": 1, "start_day": 1,
            }),
            patch.object(page, "_start_episode_image_cache"),
        ):
            frame = page._episodes_section()

        cards = frame.findChildren(EpisodeCard)
        self.assertEqual(len(cards), 1)
        self.assertEqual(
            cards[0].findChild(QLabel, "detailEpisodeTitle").text(),
            "Valid",
        )
        frame.deleteLater()
        page.deleteLater()
        self.app.processEvents()

    def test_episode_storage_error_does_not_break_bundle_detail_section(self):
        page = WorkDetailPage()
        page.work = {
            "id": 12345,
            "type": "ANIME",
            "format": "TV",
            "_series_members": [{"id": 12345}],
        }
        page._selected_episode_work_id = 12345

        with patch(
            "ui.pages.work_detail_page.get_episodes",
            side_effect=RuntimeError("simulated corrupt episode catalog"),
        ):
            frame = page._episodes_section()

        self.assertTrue(frame.property("_episodes_section"))
        self.assertTrue(any(
            "Episode data could not be displayed" in label.text()
            for label in frame.findChildren(QLabel)
        ))
        frame.deleteLater()
        page.deleteLater()
        self.app.processEvents()

    def test_deferred_episode_callback_contains_bundle_id_errors(self):
        page = WorkDetailPage()
        page.work = {
            "id": 12345,
            "type": "ANIME",
            "format": "TV",
            "_series_members": [{"id": 12345}],
        }
        page._selected_episode_work_id = 12345
        content = QWidget()
        root = QVBoxLayout(content)
        host = QFrame(content)
        root.addWidget(host)
        page.scroll_area.setWidget(content)
        token = page._detail_build_token

        with patch.object(
            page, "_detail_work_ids",
            side_effect=RuntimeError("simulated invalid bundle details"),
        ):
            page._populate_episode_section(token, content, host)

        self.assertIsNotNone(content.findChild(QLabel, "detailEpisodeMessage"))
        self.assertEqual(root.indexOf(host), -1)
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
