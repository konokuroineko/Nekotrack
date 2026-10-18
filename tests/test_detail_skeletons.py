import os
import unittest
import time
import threading
from unittest.mock import patch

from PySide6.QtCore import Qt, Signal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication, QBoxLayout, QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QToolButton, QVBoxLayout, QWidget, QWidgetAction,
)

from api import (
    TMDB_EPISODE_CATALOG_REFRESH_INTERVAL_SECONDS,
    TMDB_EPISODE_CATALOG_VERSION,
)
from ui.pages.work_detail_page import (
    EpisodeArtwork, EpisodeCard, StaffFlowLayout,
    EpisodeImageCacheWorker, EpisodeSyncWorker, WorkDetailPage,
)


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
        page._selected_episode_work_id = 12345
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
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline and not callbacks:
                self.app.processEvents()
                time.sleep(0.01)
            self.app.processEvents()

        self.assertEqual(len(callbacks), 1)
        self.assertEqual(callbacks[0][0], 250)
        self.assertGreaterEqual(layout.indexOf(host), 0)
        self.assertFalse(page._episode_section_load_jobs)

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
        page._selected_episode_work_id = 12345
        page._detail_build_token = 9
        content = QWidget()
        layout = QVBoxLayout(content)
        host = QFrame(content)
        layout.addWidget(host)
        page.scroll_area.setWidget(content)

        with patch("ui.pages.work_detail_page.get_work", return_value=None):
            page._populate_episode_section(9, content, host, attempt=120)
            deadline = time.monotonic() + 4.0
            while (
                time.monotonic() < deadline
                and content.findChild(QLabel, "detailEpisodeMessage") is None
            ):
                self.app.processEvents()
                time.sleep(0.01)
            self.app.processEvents()

        message = content.findChild(QLabel, "detailEpisodeMessage")
        self.assertIsNotNone(message)
        self.assertIn("still being imported", message.text())
        self.assertFalse(page._episode_section_load_jobs)

        page.deleteLater()
        self.app.processEvents()

    def test_ui_stall_watchdog_logs_without_processing_gui_events(self):
        page = WorkDetailPage()
        events = []
        page._ui_watchdog_work_id = 21355
        page._ui_watchdog_bundle_ids = (21355, 108632)
        page._last_ui_phase = "test_deliberate_ui_stall"
        page._last_ui_heartbeat_at = time.monotonic() - 3.0

        with patch(
            "ui.pages.work_detail_page.log_event",
            side_effect=lambda event, **fields: events.append((event, fields)),
        ):
            deadline = time.monotonic() + 2.0
            # Intentionally do not pump QApplication events: the watchdog must
            # still log from its separate thread while Qt's UI queue is idle.
            while time.monotonic() < deadline and not any(
                event == "work_detail.ui_watchdog_stall_detected"
                for event, _fields in events
            ):
                time.sleep(0.02)

        stall_events = [
            fields for event, fields in events
            if event == "work_detail.ui_watchdog_stall_detected"
        ]
        self.assertTrue(stall_events)
        self.assertEqual(stall_events[0]["work_id"], 21355)
        self.assertEqual(stall_events[0]["bundle_work_ids"], [21355, 108632])
        self.assertEqual(stall_events[0]["last_ui_phase"], "test_deliberate_ui_stall")
        self.assertGreaterEqual(stall_events[0]["stall_ms"], 1500)

        page.request_shutdown()
        page._ui_stall_watchdog_thread.join(timeout=1.0)
        self.assertFalse(page._ui_stall_watchdog_thread.is_alive())
        page.deleteLater()
        self.app.processEvents()

    def test_active_episode_catalog_reads_run_off_gui_thread(self):
        page = WorkDetailPage()
        work_id = 12345
        page.work = {
            "id": work_id,
            "type": "ANIME",
            "format": "TV",
            "episodes": 1,
            "title": {"english": "Example Series"},
            "_series_members": [{
                "id": work_id,
                "title": {"english": "Example Series"},
                "start_year": 2020,
                "start_month": 1,
                "start_day": 1,
            }],
        }
        page._selected_episode_work_id = work_id
        page._detail_build_token = 17
        content = QWidget()
        content._detail_sections_ready = False
        content._detail_sections_success = True
        content._episode_section_ready = False
        content._episode_section_success = True
        layout = QVBoxLayout(content)
        host = page._episode_section_loading_frame()
        layout.addWidget(host)
        page.scroll_area.setWidget(content)

        gui_thread_id = threading.get_ident()
        database_threads = []
        work_row = {
            "id": work_id,
            "title": "Example Series",
            "type": "ANIME",
            "format": "TV",
            "episodes": 1,
        }
        episode_rows = [{
            "work_id": work_id,
            "episode_number": 1,
            "title": "Episode 1",
            "description": "An example synopsis for the first episode.",
            "air_date": "2020-01-01",
            "thumbnail_url": None,
            "watched": 0,
        }]

        def read_work(_work_id):
            database_threads.append(("work", threading.get_ident()))
            return work_row

        def read_episodes(_work_id):
            database_threads.append(("episodes", threading.get_ident()))
            return episode_rows

        def read_metadata(_work_id, _provider):
            database_threads.append(("metadata", threading.get_ident()))
            return {
                "version": TMDB_EPISODE_CATALOG_VERSION,
                "fetched_at": time.time(),
            }

        with (
            patch("ui.pages.work_detail_page.get_work", side_effect=read_work),
            patch("ui.pages.work_detail_page.get_episodes", side_effect=read_episodes),
            patch("ui.pages.work_detail_page.get_provider_metadata", side_effect=read_metadata),
            patch.object(page, "_start_episode_image_cache"),
        ):
            page._populate_episode_section(17, content, host)
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                self.app.processEvents()
                if (
                    not page._episode_section_load_jobs
                    and len(content.findChildren(EpisodeCard)) == 1
                ):
                    break
                time.sleep(0.01)
            self.app.processEvents()

        self.assertEqual(
            {name for name, _thread_id in database_threads},
            {"work", "episodes", "metadata"},
        )
        self.assertTrue(database_threads)
        self.assertTrue(
            all(thread_id != gui_thread_id for _name, thread_id in database_threads),
            "Episode catalog queries were run synchronously by the GUI thread.",
        )
        self.assertEqual(len(content.findChildren(EpisodeCard)), 1)
        self.assertFalse(page._episode_section_load_jobs)

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
        episode_frame_layout = QVBoxLayout(episode_frame)
        episode_cards_host = QWidget(episode_frame)
        episode_frame._episode_cards_layout = StaffFlowLayout(
            episode_cards_host, h_spacing=12, v_spacing=14
        )
        episode_frame_layout.addWidget(episode_cards_host)
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

    def test_active_detail_open_defers_all_expensive_sections_even_when_local_data_is_ready(self):
        page = WorkDetailPage()
        page.work = {
            "id": 12345,
            "type": "ANIME",
            "format": "TV",
            "title": {"english": "Bundled season"},
            "_series_members": [{"id": 12345}],
        }
        page._selected_episode_work_id = 12345

        with (
            patch.object(page, "_local_detail_ready") as readiness,
            patch.object(page, "_hero", return_value=QFrame()),
            patch.object(page, "_mangabaka_section", return_value=None),
            patch.object(page, "_is_reading_media", return_value=False),
            patch.object(page, "_episodes_section") as episodes,
            patch.object(page, "_build_detail_sections_local") as local_sections,
            patch("ui.pages.work_detail_page.QTimer.singleShot") as schedule,
        ):
            content, ready = page._build_detail_content([12345], defer_missing=True)

        self.assertFalse(ready)
        readiness.assert_not_called()
        episodes.assert_not_called()
        local_sections.assert_not_called()
        self.assertEqual(
            {
                frame.property("_skeleton_section_title")
                for frame in content.findChildren(QFrame, "detailSkeletonSection")
            },
            {"Characters", "Staff", "Relations"},
        )
        self.assertIsNotNone(content.findChild(QLabel, "detailEpisodeLoadingLabel"))
        self.assertFalse(content.property("_detail_cacheable"))
        self.assertEqual(schedule.call_count, 2)
        self.assertTrue(all(call.args[0] == 40 for call in schedule.call_args_list))

        content.deleteLater()
        page.deleteLater()
        self.app.processEvents()

    def test_bundle_section_database_reads_run_off_the_gui_thread(self):
        class DummyCard(QFrame):
            clicked = Signal(object)

            def __init__(self, item):
                super().__init__()
                self.item = item

        page = WorkDetailPage()
        page.work = {
            "id": 12345,
            "type": "ANIME",
            "format": "TV",
            "_series_members": [{"id": 12345}, {"id": 12346}],
        }
        page._detail_build_token = 1
        content = QWidget()
        content.setProperty("_detail_cache_key", [12345, 12346])
        content._detail_sections_ready = False
        content._detail_sections_success = True
        content._episode_section_ready = True
        content._episode_section_success = True
        layout = QVBoxLayout(content)
        skeleton = page._detail_section_skeleton("Relations", 6, "poster")
        layout.addWidget(skeleton)
        page.scroll_area.setWidget(content)

        gui_thread_id = threading.get_ident()
        query_thread_ids = []

        def read_bundle_relations(work_ids):
            query_thread_ids.append(threading.get_ident())
            return [{"id": 9001, "title": "Example relation"}]

        page._populate_detail_section(
            1,
            content,
            layout,
            skeleton,
            [12345, 12346],
            "Relations",
            read_bundle_relations,
            DummyCard,
            page.relation_selected,
            6,
        )

        # The function returns after scheduling its background query; the
        # database getter must not have run in the click/GUI call stack.
        self.assertEqual(query_thread_ids, [])
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and (
            page._detail_section_jobs
            or content.findChild(QFrame, "detailSkeletonSection") is not None
        ):
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()

        self.assertEqual(len(query_thread_ids), 1)
        self.assertNotEqual(query_thread_ids[0], gui_thread_id)
        self.assertEqual(
            len(content.findChildren(DummyCard)),
            1,
        )
        self.assertFalse(page._detail_section_jobs)

        page.deleteLater()
        self.app.processEvents()

    def test_anime_bundle_skips_unneeded_mangabaka_database_lookups(self):
        page = WorkDetailPage()
        page.work = {
            "id": 12345,
            "type": "ANIME",
            "format": "TV",
            "title": {"english": "Bundle representative"},
            "_series_members": [{"id": 12345 + index} for index in range(12)],
        }

        with patch("ui.pages.work_detail_page.get_provider_metadata") as metadata:
            detail_ids = page._prepare_detail_state(page.work)

        self.assertEqual(detail_ids, [12345 + index for index in range(12)])
        metadata.assert_not_called()
        self.assertIsNone(page.mangabaka_metadata)
        self.assertEqual(page.mangabaka_volume_records, [])
        self.assertEqual(page.mangabaka_news, [])

        page.deleteLater()
        self.app.processEvents()

    def test_episode_cards_use_thumbnail_first_layout_and_clear_watch_toggle(self):
        episode = {
            "work_id": 12345,
            "episode_number": 4,
            "display_episode_number": 1,
            "thumbnail_url": None,
            "air_date": None,
            "title": "Episode title",
            "description": "",
            "watched": 0,
        }
        card = EpisodeCard(episode)
        artwork = card.findChild(EpisodeArtwork)
        description = card.findChild(QLabel, "detailEpisodeDescription")
        watched = card.findChild(QCheckBox, "episodeWatchedCheckbox")
        title = card.findChild(QLabel, "detailEpisodeTitle")
        number = card.findChild(QLabel, "detailEpisodeNumber")
        labels = card.findChildren(QLabel)

        self.assertEqual(card.size().width(), EpisodeCard.CARD_WIDTH)
        self.assertEqual(card.size().height(), EpisodeCard.CARD_HEIGHT)
        self.assertIsInstance(card.layout(), QVBoxLayout)
        self.assertEqual(artwork.size().width(), 220)
        self.assertEqual(artwork.size().height(), 124)
        self.assertIn("EP 01", [label.text() for label in labels])
        self.assertIsNotNone(title)
        self.assertIsNotNone(number)
        self.assertLess(labels.index(title), labels.index(number))
        self.assertIsNotNone(watched)
        self.assertEqual(watched.text(), "Watched")
        self.assertIsNone(description)

        card.show()
        self.app.processEvents()
        self.assertLess(artwork.geometry().bottom(), title.geometry().top())

        card.deleteLater()
        self.app.processEvents()

    def test_episode_cards_stack_thumbnail_title_and_compact_synopsis(self):
        full_description = (
            "A surprisingly long episode synopsis follows the characters through "
            "an unexpected journey before revealing the secret behind the mystery."
        )
        card = EpisodeCard({
            "work_id": 12345,
            "episode_number": 1,
            "display_episode_number": 1,
            "thumbnail_url": None,
            "air_date": "2026-10-01",
            "title": "The Unexpected Turn",
            "description": full_description,
            "watched": 0,
        })
        artwork = card.findChild(EpisodeArtwork)
        title = card.findChild(QLabel, "detailEpisodeTitle")
        description = card.findChild(QLabel, "detailEpisodeDescription")
        number = card.findChild(QLabel, "detailEpisodeNumber")
        self.assertIsNotNone(artwork)
        self.assertIsNotNone(title)
        self.assertIsNotNone(description)
        self.assertIsNotNone(number)
        self.assertEqual(description.toolTip(), full_description)
        self.assertLessEqual(description.maximumHeight(), 32)

        card.show()
        self.app.processEvents()
        self.assertLess(artwork.geometry().bottom(), title.geometry().top())
        self.assertLess(title.geometry().bottom(), description.geometry().top())
        self.assertTrue(description.text().endswith("…"))
        self.assertEqual(number.text(), "EP 01")

        card.deleteLater()
        self.app.processEvents()

    def test_episode_card_flow_layout_wraps_to_multiple_columns(self):
        host = QWidget()
        layout = StaffFlowLayout(host, h_spacing=12, v_spacing=14)
        layout.setContentsMargins(0, 0, 0, 0)
        cards = [
            EpisodeCard({
                "work_id": 12345,
                "episode_number": index,
                "display_episode_number": index,
                "thumbnail_url": None,
                "air_date": None,
                "title": f"Episode {index}",
                "description": "",
                "watched": 0,
            })
            for index in range(1, 4)
        ]
        for card in cards:
            layout.addWidget(card)

        host.setFixedSize(500, 560)
        host.show()
        self.app.processEvents()

        self.assertEqual(cards[0].geometry().y(), cards[1].geometry().y())
        self.assertGreater(cards[2].geometry().y(), cards[0].geometry().y())
        self.assertGreater(cards[1].geometry().x(), cards[0].geometry().x())

        host.deleteLater()
        self.app.processEvents()

    def test_bundle_episode_selector_uses_real_member_titles_and_progress_control(self):
        page = WorkDetailPage()
        page._selected_episode_work_id = 12346
        members = [
            {
                "id": 12345,
                "title": {"english": "Re:ZERO Season One"},
                "start_year": 2016, "start_month": 4, "start_day": 4,
            },
            {
                "id": 12346,
                "title": {"english": "Re:ZERO - The Frozen Bond"},
                "start_year": 2019, "start_month": 11, "start_day": 8,
            },
        ]
        payload = {
            "status": "ok",
            "work_id": 12346,
            "members": members,
            "episodes": [{
                "work_id": 12346,
                "episode_number": 4,
                "title": "The Frozen Bond",
                "description": "",
                "air_date": None,
                "thumbnail_url": None,
                "watched": 0,
            }],
            "work": {
                "id": 12346,
                "title": "Re:ZERO - The Frozen Bond",
                "format": "OVA",
                "episodes": 1,
            },
            "catalog_version": TMDB_EPISODE_CATALOG_VERSION,
            "needs_catalog_refresh": False,
        }

        with (
            patch.object(page, "_is_reading_media", return_value=False),
            patch.object(page, "_start_episode_image_cache"),
        ):
            frame = page._build_episodes_section(defer_cards=True, loaded_data=payload)

        selector = frame.findChild(QToolButton)
        self.assertIsNotNone(selector)
        self.assertIn("The Frozen Bond", selector.text())
        self.assertNotIn("Season 2", selector.text())
        self.assertTrue(
            any(
                "Re:ZERO - The Frozen Bond" in action.text()
                for action in selector.menu().actions()
            )
        )
        self.assertEqual(
            frame.findChild(QSpinBox, "episodeProgressThrough").maximum(), 1
        )
        self.assertIsNotNone(frame.findChild(QPushButton, "episodeProgressApply"))
        self.assertIsNotNone(frame.findChild(QPushButton, "episodeMarkAllWatched"))

        frame.deleteLater()
        page.deleteLater()
        self.app.processEvents()

    def test_episode_image_plan_logs_missing_and_stale_local_artwork(self):
        page = WorkDetailPage()
        with patch("ui.pages.work_detail_page.log_event") as logged:
            page._start_episode_image_cache(
                12345,
                [
                    {"episodeNumber": 2, "thumbnail": None},
                    {"episodeNumber": 4, "thumbnail": "missing-cache/episode-4.jpg"},
                ],
            )

        plan = next(
            call for call in logged.call_args_list
            if call.args and call.args[0] == "episodes.image_cache_plan"
        )
        self.assertEqual(plan.kwargs["missing_thumbnail_count"], 1)
        self.assertEqual(plan.kwargs["missing_thumbnail_episode_numbers"], [2])
        self.assertEqual(plan.kwargs["broken_local_path_count"], 1)
        self.assertEqual(plan.kwargs["broken_local_path_episode_numbers"], [4])

        page.deleteLater()
        self.app.processEvents()

    def test_missing_episode_art_is_recorded_as_failure_not_a_successful_batch(self):
        worker = EpisodeImageCacheWorker(
            12345,
            [{"episodeNumber": 1, "thumbnail": "https://image.tmdb.org/t/p/w500/test.jpg"}],
        )
        failures = []
        successes = []
        worker.error.connect(lambda work_id, message: failures.append((work_id, message)))
        worker.finished.connect(lambda work_id: successes.append(work_id))

        with (
            patch(
                "ui.pages.work_detail_page.cache_tmdb_episode_image",
                return_value=None,
            ),
            patch("ui.pages.work_detail_page.save_episode_thumbnail_path") as save_path,
            patch("ui.pages.work_detail_page.log_event") as log_event,
            patch("ui.pages.work_detail_page.log_exception") as log_exception,
        ):
            worker.run()

        self.assertEqual(worker.attempted_count, 1)
        self.assertEqual(worker.cached_count, 0)
        self.assertEqual(worker.failed_episode_numbers, [1])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0][0], 12345)
        self.assertIn("ValueError", failures[0][1])
        self.assertEqual(successes, [])
        save_path.assert_not_called()
        log_exception.assert_called_once()
        self.assertTrue(any(
            call.args[0] == "episodes.image_cache_worker_finished"
            and call.kwargs.get("failed_count") == 1
            for call in log_event.call_args_list
        ))

    def test_episode_sync_thread_quits_without_gui_event_pump(self):
        page = WorkDetailPage()
        page.work = {"id": 12345, "type": "ANIME", "format": "TV"}
        events = []
        work_id = 12345

        with (
            patch(
                "ui.pages.work_detail_page.get_tmdb_episode_data",
                return_value={
                    "episodes": [],
                    "tmdb_count": 0,
                    "tmdb_id": 999,
                    "tmdb_season_number": 1,
                },
            ),
            patch(
                "ui.pages.work_detail_page.log_event",
                side_effect=lambda event, **fields: events.append((event, fields)),
            ),
            patch("ui.pages.work_detail_page.log_exception"),
        ):
            page._start_episode_sync(
                work_id,
                ["Example Series"],
                "2020-01-01",
                None,
                12,
                999,
                1,
                "TV",
            )
            thread = page._episode_sync_thread
            stopped_before_gui_pump = thread.wait(2000)
            self.app.processEvents()

        self.assertTrue(
            stopped_before_gui_pump,
            "Episode metadata QThread did not stop until GUI events were processed.",
        )
        event_names = [event for event, _fields in events]
        self.assertIn("episodes.sync_thread_started", event_names)
        self.assertIn("episodes.sync_worker_started", event_names)
        self.assertIn("episodes.sync_worker_succeeded", event_names)
        self.assertIn("episodes.sync_completion_received", event_names)
        self.assertIn("episodes.sync_thread_stopped", event_names)
        self.assertIsNone(page._episode_sync_thread)
        self.assertIsNone(page._episode_sync_worker)

        page.deleteLater()
        self.app.processEvents()

    def test_episode_sync_error_thread_quits_without_gui_event_pump(self):
        page = WorkDetailPage()
        page.work = {"id": 12346, "type": "ANIME", "format": "TV"}
        events = []
        work_id = 12346

        with (
            patch(
                "ui.pages.work_detail_page.get_tmdb_episode_data",
                side_effect=RuntimeError("simulated TMDB lookup failure"),
            ),
            patch(
                "ui.pages.work_detail_page.log_event",
                side_effect=lambda event, **fields: events.append((event, fields)),
            ),
            patch(
                "ui.pages.work_detail_page.log_exception",
                side_effect=lambda event, error, **fields: events.append((event, fields)),
            ),
        ):
            page._start_episode_sync(
                work_id,
                ["Example Series"],
                "2020-01-01",
                None,
                12,
                None,
                None,
                "TV",
            )
            thread = page._episode_sync_thread
            stopped_before_gui_pump = thread.wait(2000)
            self.app.processEvents()

        self.assertTrue(
            stopped_before_gui_pump,
            "Failed episode metadata QThread did not stop without GUI events.",
        )
        event_rows = dict((event, fields) for event, fields in events)
        self.assertIn("episodes.sync_worker_started", event_rows)
        self.assertIn("episodes.sync_worker_failed", event_rows)
        self.assertEqual(
            event_rows["episodes.sync_completion_received"]["outcome"],
            "error",
        )
        self.assertIn("episodes.sync_thread_stopped", event_rows)
        self.assertIsNone(page._episode_sync_thread)
        self.assertIsNone(page._episode_sync_worker)

        page.deleteLater()
        self.app.processEvents()

    def test_episode_image_cache_thread_quits_without_gui_event_pump(self):
        page = WorkDetailPage()
        events = []

        with (
            patch(
                "ui.pages.work_detail_page.cache_tmdb_episode_image",
                side_effect=lambda *args: (time.sleep(0.05), "cached-episode.jpg")[1],
            ),
            patch("ui.pages.work_detail_page.save_episode_thumbnail_path", return_value=True),
            patch(
                "ui.pages.work_detail_page.log_event",
                side_effect=lambda event, **fields: events.append((event, fields)),
            ),
            patch("ui.pages.work_detail_page.log_exception"),
        ):
            page._start_episode_image_cache(
                12345,
                [{
                    "episodeNumber": 1,
                    "thumbnail": "https://image.tmdb.org/t/p/w500/test.jpg",
                }],
            )
            thread = page._episode_image_cache_threads[12345]

            # Deliberately wait without processing GUI events. The worker must
            # be able to request thread shutdown without a queued GUI callback.
            stopped_before_gui_pump = thread.wait(2000)

            # If this regression returns, release queued callbacks and give the
            # thread a chance to stop before ending the test.
            if not stopped_before_gui_pump:
                self.app.processEvents()

            self.app.processEvents()

        self.assertTrue(
            stopped_before_gui_pump,
            "Episode image cache QThread did not stop until GUI events were processed.",
        )
        event_names = [event for event, _fields in events]
        self.assertIn("episodes.image_cache_worker_finished", event_names)
        self.assertIn("episodes.image_cache_completion_signal_emitting", event_names)
        self.assertIn("episodes.image_cache_completion_received", event_names)
        self.assertIn("episodes.image_cache_batch_succeeded", event_names)
        self.assertIn("episodes.image_cache_thread_stopped", event_names)
        self.assertNotIn(12345, page._episode_image_cache_threads)

        page.deleteLater()
        self.app.processEvents()

    def test_episode_image_cache_error_thread_quits_without_gui_event_pump(self):
        page = WorkDetailPage()
        events = []
        work_id = 12346

        with (
            patch(
                "ui.pages.work_detail_page.cache_tmdb_episode_image",
                return_value=None,
            ),
            patch("ui.pages.work_detail_page.save_episode_thumbnail_path") as save_path,
            patch(
                "ui.pages.work_detail_page.log_event",
                side_effect=lambda event, **fields: events.append((event, fields)),
            ),
            patch("ui.pages.work_detail_page.log_exception"),
        ):
            page._start_episode_image_cache(
                work_id,
                [{
                    "episodeNumber": 1,
                    "thumbnail": "https://image.tmdb.org/t/p/w500/missing.jpg",
                }],
            )
            thread = page._episode_image_cache_threads[work_id]

            # The error path must shut down the worker thread without relying
            # on the GUI queue to deliver the error callback.
            stopped_before_gui_pump = thread.wait(2000)
            self.app.processEvents()

        self.assertTrue(
            stopped_before_gui_pump,
            "Failed episode image cache QThread did not stop without GUI events.",
        )
        event_rows = dict((event, fields) for event, fields in events)
        self.assertIn("episodes.image_cache_worker_finished", event_rows)
        self.assertIn("episodes.image_cache_completion_signal_emitting", event_rows)
        self.assertEqual(
            event_rows["episodes.image_cache_completion_signal_emitting"]["outcome"],
            "error",
        )
        self.assertEqual(
            event_rows["episodes.image_cache_completion_received"]["outcome"],
            "error",
        )
        self.assertIn("episodes.image_cache_batch_failed", event_rows)
        self.assertIn("episodes.image_cache_thread_stopped", event_rows)
        self.assertGreater(page._episode_image_cache_retry_after[work_id], time.monotonic())
        self.assertNotIn(work_id, page._episode_image_cache_threads)
        self.assertNotIn(work_id, page._episode_image_cache_workers)
        save_path.assert_not_called()

        page.deleteLater()
        self.app.processEvents()

    def test_episode_image_cache_failure_keeps_thread_reference_and_throttles_retry(self):
        page = WorkDetailPage()
        page.work = {"id": 12345, "type": "ANIME", "format": "TV"}
        page._selected_episode_work_id = 12345
        thread = object()
        worker = type("FakeWorker", (), {"failed_episode_numbers": [1]})()
        page._episode_image_cache_threads[12345] = thread
        page._episode_image_cache_workers[12345] = worker

        with (
            patch.object(page, "_replace_episode_section") as replace_section,
            patch("ui.pages.work_detail_page.log_event") as log_event,
        ):
            page._episode_image_cache_error(12345, "Episode 1: ValueError")

        self.assertIn(12345, page._episode_image_cache_threads)
        self.assertIs(page._episode_image_cache_threads[12345], thread)
        self.assertIn(12345, page._episode_image_cache_workers)
        self.assertGreater(
            page._episode_image_cache_retry_after[12345],
            time.monotonic(),
        )
        replace_section.assert_called_once()
        self.assertTrue(any(
            call.args[0] == "episodes.image_cache_batch_failed"
            for call in log_event.call_args_list
        ))

        # Once the prior worker has stopped, reopening the section during the
        # cooldown must not spawn another immediate download worker.
        page._episode_image_cache_cleanup(12345)
        with (
            patch("ui.pages.work_detail_page.QThread") as thread_factory,
            patch("ui.pages.work_detail_page.log_event") as retry_log,
        ):
            page._start_episode_image_cache(
                12345,
                [{"episodeNumber": 1, "thumbnail": "https://image.tmdb.org/t/p/w500/test.jpg"}],
            )
        thread_factory.assert_not_called()
        self.assertTrue(any(
            call.args[0] == "episodes.image_cache_retry_suppressed"
            for call in retry_log.call_args_list
        ))

        page.deleteLater()
        self.app.processEvents()

    def test_episode_artwork_shows_unavailable_after_a_failed_cache_attempt(self):
        card = EpisodeCard({
            "work_id": 12345,
            "episode_number": 1,
            "thumbnail_url": "https://image.tmdb.org/t/p/w500/test.jpg",
            "air_date": None,
            "title": "Episode with unavailable art",
            "description": "Description is still available.",
            "watched": 0,
            "thumbnail_cache_failed": True,
        })
        artwork = card.findChild(EpisodeArtwork)
        title = card.findChild(QLabel, "detailEpisodeTitle")
        number = card.findChild(QLabel, "detailEpisodeNumber")
        description = card.findChild(QLabel, "detailEpisodeDescription")
        labels = card.findChildren(QLabel)
        self.assertIsNotNone(artwork)
        self.assertEqual(artwork.text(), "UNAVAILABLE")
        self.assertLess(labels.index(title), labels.index(number))
        self.assertIn("font-size:10px", description.styleSheet())
        self.assertEqual(
            description.toolTip(),
            "Description is still available.",
        )
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

    def test_successful_episode_sync_persists_catalog_in_worker(self):
        now = 2_000_000_000
        episodes = [{
            "episodeNumber": 1,
            "title": "Episode One",
            "description": None,
            "airdate": "2020-01-01",
            "thumbnail": None,
        }]
        worker = EpisodeSyncWorker(
            12345, ["Example Series"], "2020-01-01", None, 1, 99, 1, "TV"
        )
        results = []
        worker.finished.connect(lambda work_id, payload: results.append((work_id, payload)))
        with (
            patch(
                "ui.pages.work_detail_page.get_tmdb_episode_data",
                return_value={
                    "episodes": episodes,
                    "tmdb_count": 1,
                    "tmdb_id": 99,
                    "tmdb_season_number": 1,
                },
            ),
            patch("ui.pages.work_detail_page.save_episodes") as save_episodes,
            patch("ui.pages.work_detail_page.save_tmdb_mapping") as save_mapping,
            patch("ui.pages.work_detail_page.save_provider_metadata") as save_metadata,
            patch("ui.pages.work_detail_page.prune_episode_catalog") as prune,
            patch("ui.pages.work_detail_page.time.time", return_value=now),
        ):
            worker.run()

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
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], 12345)
        self.assertTrue(results[0][1]["_catalog_persisted"])

    def test_partial_episode_sync_does_not_prune_previous_catalog_rows(self):
        episodes = [
            {"episodeNumber": 1, "title": "Episode One"},
            {"episodeNumber": 2, "title": "Episode Two"},
        ]
        worker = EpisodeSyncWorker(
            12345, ["Example Series"], "2020-01-01", None, 3, 99, 1, "TV"
        )
        with (
            patch(
                "ui.pages.work_detail_page.get_tmdb_episode_data",
                return_value={
                    "episodes": episodes,
                    "tmdb_count": len(episodes),
                    "tmdb_id": 99,
                    "tmdb_season_number": 1,
                },
            ),
            patch("ui.pages.work_detail_page.save_episodes"),
            patch("ui.pages.work_detail_page.save_tmdb_mapping"),
            patch("ui.pages.work_detail_page.save_provider_metadata"),
            patch("ui.pages.work_detail_page.prune_episode_catalog") as prune,
            patch("ui.pages.work_detail_page.log_event") as event,
        ):
            worker.run()

        prune.assert_not_called()
        self.assertTrue(any(
            call.args[0] == "episodes.catalog_prune_skipped"
            and call.kwargs.get("reason") == "catalog_shorter_than_expected"
            and call.kwargs.get("preserved_existing_rows") is True
            for call in event.call_args_list
        ))

    def test_unknown_episode_count_does_not_authorize_catalog_pruning(self):
        episodes = [
            {"episodeNumber": 1, "title": "Episode One"},
        ]
        worker = EpisodeSyncWorker(
            12345, ["Example Series"], "2020-01-01", None, None, 99, 1, "TV"
        )
        with (
            patch(
                "ui.pages.work_detail_page.get_tmdb_episode_data",
                return_value={
                    "episodes": episodes,
                    "tmdb_count": len(episodes),
                    "tmdb_id": 99,
                    "tmdb_season_number": 1,
                },
            ),
            patch("ui.pages.work_detail_page.save_episodes"),
            patch("ui.pages.work_detail_page.save_tmdb_mapping"),
            patch("ui.pages.work_detail_page.save_provider_metadata"),
            patch("ui.pages.work_detail_page.prune_episode_catalog") as prune,
            patch("ui.pages.work_detail_page.log_event") as event,
        ):
            worker.run()

        prune.assert_not_called()
        self.assertTrue(any(
            call.args[0] == "episodes.catalog_prune_skipped"
            and call.kwargs.get("reason") == "expected_episode_count_unknown"
            and call.kwargs.get("preserved_existing_rows") is True
            for call in event.call_args_list
        ))

    def test_episode_catalog_database_writes_run_off_the_gui_thread(self):
        page = WorkDetailPage()
        gui_thread_id = threading.get_ident()
        writer_thread_ids = []
        episodes = [{
            "episodeNumber": 1,
            "title": "Episode One",
            "description": None,
            "airdate": "2020-01-01",
            "thumbnail": None,
        }]

        def record_writer_thread(*_args, **_kwargs):
            writer_thread_ids.append(threading.get_ident())

        with (
            patch(
                "ui.pages.work_detail_page.get_tmdb_episode_data",
                return_value={
                    "episodes": episodes,
                    "tmdb_count": 1,
                    "tmdb_id": 99,
                    "tmdb_season_number": 1,
                },
            ),
            patch("ui.pages.work_detail_page.save_episodes", side_effect=record_writer_thread),
            patch("ui.pages.work_detail_page.save_tmdb_mapping", side_effect=record_writer_thread),
            patch("ui.pages.work_detail_page.prune_episode_catalog", side_effect=record_writer_thread),
            patch("ui.pages.work_detail_page.save_provider_metadata", side_effect=record_writer_thread),
            patch.object(page, "_start_episode_image_cache"),
            patch.object(page, "_replace_episode_section"),
        ):
            page._start_episode_sync(
                12345, ["Example Series"], "2020-01-01", None, 1, 99, 1, "TV"
            )
            thread = page._episode_sync_thread
            self.assertTrue(thread.wait(2000), "Episode catalog worker did not stop.")
            self.app.processEvents()

        self.assertEqual(len(writer_thread_ids), 4)
        self.assertTrue(
            all(thread_id != gui_thread_id for thread_id in writer_thread_ids),
            "Episode catalog persistence unexpectedly ran on the GUI thread.",
        )
        page.deleteLater()
        self.app.processEvents()

    def test_episode_synopsis_is_compact_two_line_preview_with_full_tooltip(self):
        synopsis = " ".join(
            ["A long synopsis with enough words to overflow the compact preview."] * 8
        )
        card = EpisodeCard({
            "work_id": 12345,
            "episode_number": 12,
            "thumbnail_url": None,
            "air_date": None,
            "title": "A very long episode title",
            "description": synopsis,
            "watched": 0,
        })
        card.show()
        card.layout().activate()
        self.app.processEvents()
        description = card.findChild(QLabel, "detailEpisodeDescription")
        self.assertIsNotNone(description)
        self.assertTrue(description.wordWrap())
        self.assertEqual(description.toolTip(), synopsis)
        self.assertNotEqual(description.text(), synopsis)
        self.assertTrue(description.text().endswith("…"))
        self.assertLessEqual(description.text().count("\\n"), 1)
        self.assertIn("font-size:10px", description.styleSheet())
        self.assertLessEqual(description.maximumHeight(), 32)
        self.assertEqual(card.width(), EpisodeCard.CARD_WIDTH)
        self.assertEqual(card.height(), EpisodeCard.CARD_HEIGHT)

        description.setFixedWidth(500)
        self.app.processEvents()
        wide_preview = description.text()
        description.setFixedWidth(200)
        self.app.processEvents()
        self.assertLess(len(description.text()), len(wide_preview))
        self.assertTrue(description.text().endswith("…"))
        self.assertEqual(description.toolTip(), synopsis)

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
            patch.object(page, "_start_episode_image_cache") as start_image_cache,
        ):
            frame = page._episodes_section()

        cards = frame.findChildren(EpisodeCard)
        self.assertEqual(len(cards), 1)
        self.assertEqual(
            cards[0].findChild(QLabel, "detailEpisodeTitle").text(),
            "Valid",
        )
        start_image_cache.assert_called_once_with(
            12345,
            [{"episodeNumber": 1, "thumbnail": None}],
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

        with patch(
            "ui.pages.work_detail_page.get_work",
            side_effect=RuntimeError("simulated invalid bundle details"),
        ):
            page._populate_episode_section(token, content, host)
            deadline = time.monotonic() + 4.0
            while (
                time.monotonic() < deadline
                and content.findChild(QLabel, "detailEpisodeMessage") is None
            ):
                self.app.processEvents()
                time.sleep(0.01)
            self.app.processEvents()

        message = content.findChild(QLabel, "detailEpisodeMessage")
        self.assertIsNotNone(message)
        self.assertIn("could not be loaded", message.text())
        # Qt has already deleted the old placeholder frame after replacing it.
        self.assertGreaterEqual(root.indexOf(message.parentWidget()), 0)
        self.assertFalse(page._episode_section_load_jobs)
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


    def test_large_character_and_relation_sections_render_cards_incrementally(self):
        class DummyCard(QFrame):
            clicked = Signal(object)

            def __init__(self, item):
                super().__init__()
                self.item = item
                self.setObjectName("paginationTestCard")

        page = WorkDetailPage()
        items = [{"id": index} for index in range(30)]

        for title, clicked_signal in (
            ("Characters", page.character_selected),
            ("Relations", page.relation_selected),
        ):
            with self.subTest(section=title):
                section = page._grid_section(
                    title,
                    items,
                    DummyCard,
                    clicked_signal,
                    4,
                )
                self.assertEqual(
                    len(section.findChildren(DummyCard, "paginationTestCard")),
                    12,
                )
                more_button = section.findChild(QPushButton, "staffMoreButton")
                self.assertIsNotNone(more_button)
                self.assertIn("18 remaining", more_button.text())

                more_button.click()
                self.assertEqual(
                    len(section.findChildren(DummyCard, "paginationTestCard")),
                    24,
                )
                self.assertIn("6 remaining", more_button.text())

                more_button.click()
                self.assertEqual(
                    len(section.findChildren(DummyCard, "paginationTestCard")),
                    30,
                )
                self.assertTrue(more_button.isHidden())

                section.deleteLater()
                self.app.processEvents()

        page.deleteLater()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
