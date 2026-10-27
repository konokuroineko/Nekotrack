import sys
import threading
import time
from pathlib import Path

from api import (
    get_media_details,
    request_api_shutdown,
    reset_api_shutdown,
    get_tmdb_episode_data,
    TMDB_EPISODE_CATALOG_REFRESH_INTERVAL_SECONDS,
    TMDB_EPISODE_CATALOG_VERSION,
    get_mangabaka_series_news,
    get_mangabaka_volume_records,
)
from PySide6.QtCore import QObject, Signal, QThread, Qt, QTimer, QSize, QProcess, QUrl
from PySide6.QtGui import QColor
from PySide6.QtQuickWidgets import QQuickWidget

from PySide6.QtWidgets import QApplication, QDialog, QFrame, QHBoxLayout, QMainWindow, QMessageBox, QPushButton, QStackedWidget, QSystemTrayIcon, QVBoxLayout

from database import (
    add_to_library,
    characters_are_loaded,
    get_alternate_titles,
    get_bundle_character_voice_actors,
    get_due_release_reminders,
    get_episode_section_snapshot,
    get_library_episode_catalog_refresh_ids,
    invalidate_character_snapshots,
    get_tmdb_mapping,
    get_work,
    initialize_database,
    prune_episode_catalog,
    save_anime,
    save_automatic_bundle_membership,
    save_characters,
    save_cover_path,
    save_episodes,
    save_provider_metadata,
    save_reading_item_metadata,
    mark_release_reminder_notified,
    save_staff,
    save_tmdb_mapping,
)
from image_cache import download_cover
from library_import_queue import LibraryImportQueue
from diagnostics import diagnostic_context, log_event, log_exception, log_operation
from ui.backgrounds import BackgroundCanvas, BackgroundManager
from ui.branding import application_icon, navigation_icon, WordmarkLabel
from ui.navigation import NavigationController
from ui.preferences import get
from ui.qml_app_bridge import ApplicationBridge
from ui.setup_wizard import SetupWizard
from ui.theme import COLORS, application_stylesheet, refresh_theme, surface_rgba
from ui.pages.calendar_page import CalendarPage
from ui.pages.favorites_page import FavoritesPage
from ui.pages.home_page import HomePage
from ui.pages.library_page import LibraryPage
from ui.pages.recommendations_page import RecommendationsPage
from ui.pages.search_page import SearchPage
from ui.pages.settings_page import SettingsPage
from ui.pages.work_detail_page import WorkDetailPage
from ui.pages.entity_profile_page import EntityProfilePage



def _persist_episode_catalog_snapshot(work_id, expected_episode_count, episode_data):
    """Save episode rows and matching-policy freshness without losing progress."""
    episodes = list(episode_data or [])
    save_episodes(work_id, episodes)

    def positive_integer(value):
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value > 0 else None
        if isinstance(value, float):
            return int(value) if value.is_integer() and value > 0 else None
        if isinstance(value, str):
            text = value.strip()
            if text and text.isascii() and text.isdigit():
                number = int(text)
                return number if number > 0 else None
        return None

    expected_count = positive_integer(expected_episode_count)
    episode_numbers = {
        number
        for episode in episodes
        if isinstance(episode, dict)
        for number in [positive_integer(episode.get("episodeNumber"))]
        if number is not None
    }
    catalog_complete = (
        expected_count is not None and len(episode_numbers) >= expected_count
    )
    if catalog_complete:
        prune_episode_catalog(work_id, episodes)

    save_provider_metadata(
        work_id,
        "tmdb_episode_match_version",
        {
            "version": TMDB_EPISODE_CATALOG_VERSION,
            "fetched_at": int(time.time()),
            "complete": catalog_complete if expected_count is not None else None,
        },
    )
    return catalog_complete


class ImageWorker(QObject):
    finished = Signal(int, object)
    error = Signal(int, str)

    def __init__(self, work_id, image_url):
        super().__init__()
        self.work_id = work_id
        self.image_url = image_url

    def run(self):
        with diagnostic_context(workflow="cover_download", work_id=self.work_id):
            try:
                with log_operation("cover.download", work_id=self.work_id):
                    cover_path = download_cover(self.work_id, self.image_url)
                log_event("cover.download.signal_success", available=bool(cover_path))
                self.finished.emit(self.work_id, cover_path)
            except Exception as error:
                log_event(
                    "cover.download.signal_error",
                    error_type=type(error).__name__,
                    error=str(error),
                )
                self.error.emit(self.work_id, str(error))


class LibraryImportWorker(QObject):
    finished = Signal(int, object)
    error = Signal(int, str)

    def __init__(self, work_id, stop_event=None):
        super().__init__()
        self.work_id = int(work_id)
        self.stop_event = stop_event

    def _cancelled(self):
        return self.stop_event is not None and self.stop_event.is_set()

    def run(self):
        with diagnostic_context(workflow="library_import", work_id=self.work_id):
            log_event("library.import.started")
            self._run_import()

    def _run_import(self):
        try:
            # Pass the shared shutdown signal into paginated provider reads so
            # an active import stops optional follow-up requests between pages.
            if self.stop_event is None:
                details = get_media_details(self.work_id)
            else:
                details = get_media_details(
                    self.work_id,
                    stop_event=self.stop_event,
                )
            if not details:
                raise RuntimeError("AniList returned no details for this work.")

            save_anime(details)

            # Cache real published volume/work records when MangaBaka has them.
            # Numeric read progress is stored separately and never depends on
            # generating fictional chapter or volume entries.
            if not self._cancelled() and str(details.get("type") or "").upper() == "MANGA":
                mb_id = details.get("_mangabaka_id")
                if mb_id is None and self.work_id < 0:
                    mb_id = abs(self.work_id)
                if mb_id:
                    try:
                        volume_records = get_mangabaka_volume_records(int(mb_id), max_pages=2)
                        if volume_records:
                            save_provider_metadata(
                                self.work_id,
                                "mangabaka_volumes",
                                volume_records,
                                provider_id=mb_id,
                            )
                            save_reading_item_metadata(
                                self.work_id,
                                "volume",
                                volume_records,
                            )
                    except Exception as volume_error:
                        log_exception("library.import.volume_metadata_failed", volume_error,
                                      work_id=self.work_id, provider="MangaBaka")
                        print(
                            f"MangaBaka volume lookup failed for work {self.work_id}: "
                            f"{volume_error}"
                        )

                    # Series news is optional metadata: preserve the endpoint's
                    # available records, but never block library preparation if
                    # the feed is empty, unavailable, or has changed schema.
                    try:
                        news_payload = (
                            get_mangabaka_series_news(int(mb_id), page=1, limit=10)
                            if not self._cancelled() else {}
                        )
                        news_data = (
                            news_payload.get("data", news_payload)
                            if isinstance(news_payload, dict) else news_payload
                        )
                        if isinstance(news_data, dict):
                            news_data = (
                                news_data.get("items") or news_data.get("news")
                                or news_data.get("results") or []
                            )
                        if isinstance(news_data, list) and news_data:
                            save_provider_metadata(
                                self.work_id,
                                "mangabaka_news",
                                news_data,
                                provider_id=mb_id,
                            )
                    except Exception as news_error:
                        log_exception("library.import.news_metadata_failed", news_error,
                                      work_id=self.work_id, provider="MangaBaka")
                        print(
                            f"MangaBaka news lookup failed for work {self.work_id}: "
                            f"{news_error}"
                        )

            character_connection = details.get("characters")
            character_edges = (
                character_connection.get("edges")
                if isinstance(character_connection, dict)
                else None
            )
            if details.get("_characters_snapshot_valid", True) is False:
                save_characters(self.work_id, None)
            else:
                save_characters(self.work_id, character_edges)

            staff_connection = details.get("staff")
            staff_edges = (
                staff_connection.get("edges")
                if isinstance(staff_connection, dict)
                else None
            )
            if details.get("_staff_snapshot_valid", True) is False:
                save_staff(self.work_id, None)
            else:
                save_staff(self.work_id, staff_edges)

            try:
                linked_anilist_id = int(
                    details.get("_anilist_id") or self.work_id
                )
            except (TypeError, ValueError, OverflowError):
                linked_anilist_id = 0
            staff_page_info = details.get("_anilist_staff_page_info")
            if not isinstance(staff_page_info, dict):
                staff_page_info = (
                    staff_connection.get("pageInfo")
                    if isinstance(staff_connection, dict) else None
                )
            if linked_anilist_id > 0 and isinstance(staff_page_info, dict):
                if self.work_id < 0:
                    save_provider_metadata(
                        self.work_id,
                        "anilist_media_id",
                        {"id": linked_anilist_id},
                        provider_id=linked_anilist_id,
                    )
                save_provider_metadata(
                    self.work_id,
                    "anilist_staff_page_info",
                    staff_page_info,
                    provider_id=linked_anilist_id,
                )

            # Preserve core work data, but don't start further optional provider
            # requests once the application is closing.
            if self._cancelled():
                log_event(
                    "library.import.optional_data.skipped_shutdown",
                    work_id=self.work_id,
                )
                self.finished.emit(self.work_id, details)
                return

            # TMDB episode feeds apply only to anime. Manga and light novels
            # use chapter/volume placeholders until reading-item metadata is
            # available, so never try to match them to a television season.
            if str(details.get("type") or "").upper() != "ANIME":
                log_event(
                    "library.import.completed",
                    media_type=str(details.get("type") or "").upper(),
                    episode_preload="not_applicable",
                )
                self.finished.emit(self.work_id, details)
                return

            # Library entries should be fully prepared before the user opens
            # their detail page. Episode metadata is fetched here, in the
            # existing background worker, rather than on the click path.
            title_data = details.get("title") or {}
            title_variants = [
                str(title_data.get("english") or "").strip(),
                str(title_data.get("romaji") or "").strip(),
                str(title_data.get("native") or "").strip(),
                *get_alternate_titles(self.work_id),
                *[
                    str(value).strip()
                    for value in (details.get("synonyms") or [])
                ],
            ]
            title_variants = list(
                dict.fromkeys(value for value in title_variants if value)
            )

            start_date_data = details.get("startDate") or {}
            end_date_data = details.get("endDate") or {}

            def format_date(date_data):
                year = date_data.get("year")
                if year is None:
                    return None
                month = date_data.get("month") or 1
                day = date_data.get("day") or 1
                return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

            start_date = format_date(start_date_data)
            end_date = format_date(end_date_data)
            expected_episodes = details.get("episodes")
            media_format = str(details.get("format") or "").upper()
            tmdb_id, tmdb_season_number = get_tmdb_mapping(self.work_id)

            # Episode preloading is best-effort. A missing TMDB token or a
            # temporary provider failure must not prevent Library import.
            episode_payload = {}
            try:
                episode_payload = get_tmdb_episode_data(
                    title_variants,
                    start_date,
                    end_date,
                    expected_episodes,
                    tmdb_id,
                    tmdb_season_number,
                    media_format,
                )
                resolved_tmdb_id = episode_payload.get("tmdb_id")
                resolved_season = episode_payload.get("tmdb_season_number")
                if resolved_tmdb_id is not None:
                    save_tmdb_mapping(
                        self.work_id,
                        resolved_tmdb_id,
                        resolved_season,
                    )
                _persist_episode_catalog_snapshot(
                    self.work_id,
                    expected_episodes,
                    episode_payload.get("episodes") or [],
                )
            except Exception as episode_error:
                # A missing TMDB catalog match is normal for some catalog
                # entries and is not an import failure. Keep it observable in
                # the diagnostic log without printing an alarming traceback.
                if (
                    isinstance(episode_error, RuntimeError)
                    and str(episode_error) == "TMDB could not find a matching TV series."
                ):
                    log_event(
                        "library.import.episode_preload.unavailable",
                        work_id=self.work_id,
                        provider="TMDB",
                        reason="no_series_match",
                    )
                else:
                    log_exception("library.import.episode_preload_failed", episode_error,
                                  work_id=self.work_id, provider="TMDB")
                    print(
                        f"Episode preload failed for work {self.work_id}: "
                        f"{episode_error}"
                    )

            log_event(
                "library.import.completed",
                media_type=str(details.get("type") or "").upper(),
                episode_preload=(
                    "completed" if episode_payload.get("episodes")
                    else "completed_empty"
                ) if str(details.get("type") or "").upper() == "ANIME" else "not_applicable",
                episode_count=len(episode_payload.get("episodes") or [])
                if str(details.get("type") or "").upper() == "ANIME" else None,
            )
            self.finished.emit(self.work_id, details)
        except Exception as error:
            log_exception("library.import.failed", error, work_id=self.work_id)
            log_event("library.import.error_signal", work_id=self.work_id)
            self.error.emit(self.work_id, str(error))



class LibraryEpisodePreloadWorker(QObject):
    finished = Signal(int, object)
    completed = Signal()
    error = Signal(int, str)
    skipped = Signal(int)

    def __init__(self, work_ids, stop_event=None):
        super().__init__()
        self.work_ids = [int(work_id) for work_id in work_ids]
        self.stop_event = stop_event

    def run(self):
        for work_id in self.work_ids:
            if self.stop_event is not None and self.stop_event.is_set():
                break
            try:
                snapshot = get_episode_section_snapshot(work_id)
                connection_work = snapshot.get("work")
                if connection_work is None:
                    continue
                if str(connection_work["type"] or "").upper() != "ANIME":
                    continue

                if snapshot.get("catalog_metadata_error") is not None:
                    log_exception(
                        "library.episode_preload.catalog_metadata_read_failed",
                        snapshot["catalog_metadata_error"],
                        work_id=work_id,
                    )

                metadata = snapshot.get("catalog_metadata")
                try:
                    catalog_version = max(0, int(metadata.get("version") or 0))
                except (AttributeError, TypeError, ValueError, OverflowError):
                    catalog_version = 0

                title_variants = [
                    str(connection_work["title"] or "").strip(),
                    *get_alternate_titles(work_id),
                ]
                title_variants = list(
                    dict.fromkeys(value for value in title_variants if value)
                )
                if not title_variants:
                    continue

                year = connection_work["start_year"]
                if year is None:
                    start_date = None
                else:
                    month = connection_work["start_month"] or 1
                    day = connection_work["start_day"] or 1
                    start_date = (
                        f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
                    )

                # The current matching policy must re-resolve old mappings once.
                if catalog_version < TMDB_EPISODE_CATALOG_VERSION:
                    tmdb_id, tmdb_season_number = None, None
                else:
                    tmdb_id = connection_work["tmdb_id"]
                    tmdb_season_number = connection_work["tmdb_season_number"]

                # Record the attempt before the network call. Failed, unmatched,
                # or shutdown-interrupted lookups otherwise remain stale and
                # get retried every time the app starts.
                try:
                    save_provider_metadata(
                        work_id,
                        "tmdb_episode_match_attempt",
                        {
                            "version": TMDB_EPISODE_CATALOG_VERSION,
                            "attempted_at": int(time.time()),
                            "status": "pending",
                        },
                    )
                except Exception as metadata_error:
                    log_exception(
                        "library.episode_preload.attempt_marker_failed",
                        metadata_error,
                        work_id=work_id,
                    )

                log_event("library.episode_preload.started", work_id=work_id)
                payload = get_tmdb_episode_data(
                    title_variants,
                    start_date,
                    None,
                    connection_work["episodes"],
                    tmdb_id,
                    tmdb_season_number,
                    str(connection_work["format"] or "").upper(),
                )

                resolved_tmdb_id = payload.get("tmdb_id")
                if resolved_tmdb_id is not None:
                    save_tmdb_mapping(
                        work_id,
                        resolved_tmdb_id,
                        payload.get("tmdb_season_number"),
                    )

                episodes = payload.get("episodes") or []
                catalog_complete = _persist_episode_catalog_snapshot(
                    work_id,
                    connection_work["episodes"],
                    episodes,
                )

                log_event(
                    "library.episode_preload.completed",
                    work_id=work_id,
                    episode_count=len(episodes),
                    catalog_complete=catalog_complete,
                    tmdb_id=resolved_tmdb_id,
                )
                self.finished.emit(work_id, episodes)
            except InterruptedError as error:
                if self.stop_event is not None and self.stop_event.is_set():
                    try:
                        save_provider_metadata(
                            work_id,
                            "tmdb_episode_match_attempt",
                            {
                                "version": TMDB_EPISODE_CATALOG_VERSION,
                                "attempted_at": int(time.time()),
                                "status": "cancelled",
                            },
                        )
                    except Exception as metadata_error:
                        log_exception(
                            "library.episode_preload.attempt_marker_failed",
                            metadata_error,
                            work_id=work_id,
                        )
                    log_event(
                        "library.episode_preload.cancelled",
                        work_id=work_id,
                        reason="shutdown",
                    )
                    break
                log_exception("library.episode_preload.failed", error, work_id=work_id)
                self.error.emit(work_id, str(error))
            except Exception as error:
                if (
                    isinstance(error, RuntimeError)
                    and str(error) == "TMDB could not find a matching TV series."
                ):
                    try:
                        save_provider_metadata(
                            work_id,
                            "tmdb_episode_match_attempt",
                            {
                                "version": TMDB_EPISODE_CATALOG_VERSION,
                                "attempted_at": int(time.time()),
                                "status": "no_series_match",
                            },
                        )
                    except Exception as metadata_error:
                        log_exception(
                            "library.episode_preload.attempt_marker_failed",
                            metadata_error,
                            work_id=work_id,
                        )
                    log_event(
                        "library.episode_preload.unavailable",
                        work_id=work_id,
                        provider="TMDB",
                        reason="no_series_match",
                    )
                    self.skipped.emit(work_id)
                else:
                    try:
                        save_provider_metadata(
                            work_id,
                            "tmdb_episode_match_attempt",
                            {
                                "version": TMDB_EPISODE_CATALOG_VERSION,
                                "attempted_at": int(time.time()),
                                "status": "failed",
                            },
                        )
                    except Exception as metadata_error:
                        log_exception(
                            "library.episode_preload.attempt_marker_failed",
                            metadata_error,
                            work_id=work_id,
                        )
                    log_exception("library.episode_preload.failed", error, work_id=work_id)
                    self.error.emit(work_id, str(error))
        self.completed.emit()


class NavigationButton(QPushButton):
    def __init__(self, icon_name, label):
        super().__init__()
        self.icon_name = icon_name
        self.label = label
        self.setText(label)
        self.setIcon(navigation_icon(icon_name, COLORS["secondary"]))
        self.setIconSize(QSize(20, 20))
        self.setCheckable(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(52)
        self.setProperty("navButton", True)

    def refresh_icon(self, color=None):
        if color is None:
            color = (
                COLORS["accent"]
                if self.isChecked()
                else COLORS["primary"]
                if self.underMouse()
                else COLORS["secondary"]
            )
        self.setIcon(navigation_icon(self.icon_name, color))

    def enterEvent(self, event):
        super().enterEvent(event)
        self.refresh_icon()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.refresh_icon()


# This order is also used by the sidebar regression tests. The final item is
# anchored at the bottom of the sidebar; all category heading labels are omitted.
SIDEBAR_NAVIGATION = (
    ("home", "Home", "home"),
    ("library", "Library", "collections"),
    ("search", "Search", "search"),
    ("calendar", "Calendar", "calendar"),
    ("favorites", "Favorites", "favorites"),
    ("settings", "Settings", "settings"),
)


class BundleEnrichmentCheckWorker(QObject):
    """Check local metadata for all bundle members without blocking Qt's GUI thread."""

    finished = Signal(object, object, object)

    def __init__(self, selected_work_id, work_ids):
        super().__init__()
        self.selected_work_id = selected_work_id
        self.work_ids = tuple(int(work_id) for work_id in work_ids)

    def run(self):
        pending_ids = []
        failed_checks = []
        started_at = time.perf_counter()
        log_event(
            "work_details.enrichment_check_started",
            work_id=self.selected_work_id,
            member_count=len(self.work_ids),
        )
        for work_id in self.work_ids:
            try:
                needs_enrichment = not characters_are_loaded(work_id)
            except Exception as error:
                failed_checks.append(work_id)
                log_exception(
                    "work_details.enrichment_check_failed",
                    error,
                    selected_work_id=self.selected_work_id,
                    work_id=work_id,
                )
                continue
            if needs_enrichment:
                pending_ids.append(work_id)

        log_event(
            "work_details.enrichment_check_completed",
            work_id=self.selected_work_id,
            member_count=len(self.work_ids),
            pending_import_count=len(pending_ids),
            failed_check_ids=failed_checks,
            elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )
        self.finished.emit(self.selected_work_id, pending_ids, failed_checks)


class MainWindow(QMainWindow):
    _library_import_thread_stopped = Signal(object, object, int)
    check_updates_requested = Signal()
    rollback_requested = Signal()

    def __init__(self):
        super().__init__()
        self._library_import_thread_stopped.connect(self._library_import_thread_finished)
        with log_operation("database.initialize"):
            initialize_database()
        self.setWindowTitle("NekoTrack")
        self.setWindowIcon(application_icon())
        self.resize(1380, 860)
        self.image_threads = []
        self.library_import_threads = []
        self.library_import_workers = []
        self._library_import_queue = LibraryImportQueue(max_concurrent=2)
        self._shutdown_event = threading.Event()
        self._shutdown_requested = False
        self._shutdown_started_at = None
        self._shutdown_waited_for_workers = False
        self._startup_preload_scheduled = False
        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.setInterval(100)
        self._shutdown_timer.timeout.connect(self._poll_shutdown_workers)
        self.navigation_buttons = {}
        self._settings_rebuild_pending = False
        self._detail_enrichment_ids = set()
        self._detail_enrichment_check_jobs = {}
        self._entity_profile_history = []
        self._pending_character_cast_refreshes = {}
        self._completed_character_cast_refreshes = set()
        self._profile_work_return_state = None
        self._opening_profile_credit_work = False
        self._restart_requested = False
        self._restart_launch_scheduled = False
        self._library_episode_preload_thread = None
        self._library_episode_preload_worker = None
        self._ui_root_stack = None
        self._legacy_root_stack = None
        self._qml_shell_enabled = False
        self._qml_shell_widget = None
        self.qml_bridge = None
        self._qml_navigation_sync = False
        self.background_manager = BackgroundManager(self)
        self._release_reminder_tray = QSystemTrayIcon(application_icon(), self)
        self._release_reminder_tray.setToolTip("NekoTrack release reminders")
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._release_reminder_tray.show()
        self._release_reminder_timer = QTimer(self)
        self._release_reminder_timer.setInterval(60_000)
        self._release_reminder_timer.timeout.connect(self._check_release_reminders)
        self._release_reminder_timer.start()
        with log_operation("main_window.initial_ui_build"):
            self.setup_ui()
        # Initial API work is started after the first frame, not while pages are
        # being constructed. This reduces startup contention and close-time waits.
        QTimer.singleShot(5_000, self._check_release_reminders)

    def setup_ui(self, initial_page="home"):
        refresh_theme()

        if self._ui_root_stack is None:
            self._ui_root_stack = QStackedWidget()
            self._ui_root_stack.setObjectName("uiRootStack")
            self.setCentralWidget(self._ui_root_stack)
        root = BackgroundCanvas(self.background_manager)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(270)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 22, 18, 20)
        side.setSpacing(5)

        brand_badge = QFrame()
        brand_badge.setObjectName("brandBadge")
        brand_badge.setFixedSize(230, 72)
        brand = QHBoxLayout(brand_badge)
        brand.setContentsMargins(4, 4, 4, 4)
        brand.setSpacing(0)
        word = WordmarkLabel()
        word.setObjectName("brandWord")
        word.setAccessibleName("NekoTrack")
        word.setFixedSize(222, 58)
        word.setStyleSheet("background:transparent;border:none;padding:0;")
        self.brand_word = word
        self._update_brand_word()
        brand.addWidget(word)
        side.addWidget(brand_badge)
        side.addSpacing(28)

        self.stack = QStackedWidget()
        self.navigation = NavigationController(self.stack)
        with log_operation("main_window.construct_page", page="library"):
            # Library data is not needed to display Home. Defer its synchronous
            # grouping and card construction until the Library is first opened.
            self.library_page = LibraryPage(defer_initial_refresh=True)
        with log_operation("main_window.construct_page", page="search"):
            self.search_page = SearchPage(self.add_to_library)
        with log_operation("main_window.construct_page", page="work_detail"):
            self.work_detail_page = WorkDetailPage()
        with log_operation("main_window.construct_page", page="entity_profile"):
            self.entity_profile_page = EntityProfilePage()
        with log_operation("main_window.construct_page", page="settings"):
            # Keep startup focused on the initial Home page. Build the full
            # settings controls the first time the user visits Settings.
            self.settings_page = SettingsPage(background_manager=self.background_manager, defer_initial_build=True)
        with log_operation("main_window.construct_page", page="home"):
            self.home_page = HomePage(
                self.add_to_library,
                defer_initial_recommendations=True,
            )
        self.recommendations_page = self.home_page.recommendations_page
        with log_operation("main_window.construct_page", page="calendar"):
            self.calendar_page = CalendarPage(defer_initial_refresh=True)
        with log_operation("main_window.construct_page", page="favorites"):
            self.favorites_page = FavoritesPage(defer_initial_refresh=True)
        pages = {
            "home": self.home_page,
            "collections": self.library_page,
            "search": self.search_page,
            "calendar": self.calendar_page,
            "favorites": self.favorites_page,
            "work_detail": self.work_detail_page,
            "entity_profile": self.entity_profile_page,
            "settings": self.settings_page,
        }
        for name, page in pages.items():
            self.navigation.add_page(name, page)

        # Center primary destinations in the space between the brand and Settings.
        # The second stretch keeps Settings anchored at the bottom of the sidebar.
        side.addStretch()
        for nav_item in SIDEBAR_NAVIGATION[:-1]:
            self._add_nav(side, *nav_item)
        side.addStretch()
        self._add_nav(side, *SIDEBAR_NAVIGATION[-1])

        if not hasattr(self, "_last_navigation_page"):
            self._last_navigation_page = None
        self.navigation.page_changed.connect(self.update_navigation_state)
        self.navigation.page_changed.connect(self._page_changed)
        self.home_page.work_selected.connect(self.show_work_details)
        self.home_page.calendar_requested.connect(
            lambda: self.navigation.show("calendar")
        )
        self.recommendations_page.work_selected.connect(self.show_work_details)
        self.recommendations_page.search_requested.connect(
            lambda: self.navigation.show("search")
        )
        self.favorites_page.entity_selected.connect(
            lambda kind, entity: self.show_entity_profile(
                kind, entity, from_favorites=True
            )
        )
        self.favorites_page.search_requested.connect(
            lambda: self.navigation.show("search")
        )
        self.library_page.work_selected.connect(self.show_work_details)
        self.search_page.anime_selected.connect(self.show_search_work)
        self.work_detail_page.back_requested.connect(self._back_from_work_detail)
        self.work_detail_page.bundle_edit_requested.connect(self.library_page._edit_bundle)
        self.work_detail_page.character_selected.connect(
            lambda character: self.show_entity_profile("character", character)
        )
        self.work_detail_page.person_selected.connect(
            lambda person: self.show_entity_profile("staff", person)
        )
        self.work_detail_page.voice_actor_selected.connect(
            lambda actor: self.show_entity_profile("voice_actor", actor)
        )
        self.entity_profile_page.voice_actor_selected.connect(
            lambda actor: self.show_entity_profile("voice_actor", actor)
        )
        self.entity_profile_page.character_selected.connect(
            lambda character: self.show_entity_profile("character", character)
        )
        self.entity_profile_page.work_selected.connect(self.show_profile_credit_work)
        self.entity_profile_page.back_requested.connect(self._back_from_entity_profile)
        self.work_detail_page.relation_selected.connect(self.show_relation)
        self.work_detail_page.bundle_changed.connect(self._refresh_library_after_bundle_change)
        self.settings_page.settings_changed.connect(self.apply_settings)
        self.settings_page.setup_requested.connect(self.open_setup_wizard)
        self.settings_page.restart_requested.connect(self._restart_application)
        self.settings_page.update_check_requested.connect(self.check_updates_requested.emit)
        self.settings_page.rollback_requested.connect(self.rollback_requested.emit)

        root_layout.addWidget(sidebar)
        root_layout.addWidget(self.stack, 1)
        self.setStyleSheet(
            application_stylesheet()
            + f"""
            QFrame#sidebar {{ background:{surface_rgba('sidebar')}; border-right:1px solid {COLORS['frame']}; }}
            QFrame#brandBadge {{ background:transparent; border:none; }}
            QLabel#brandWord {{ background:transparent; border:none; padding:0; }}
            QPushButton[navButton="true"] {{ background:transparent; border:1px solid transparent; color:{COLORS['secondary']}; border-radius:11px; padding:13px 15px; text-align:left; font-size:14px; font-weight:600; }}
            QPushButton[navButton="true"]:hover {{ background:{surface_rgba('surface')}; color:{COLORS['primary']}; }}
            QPushButton[navButton="true"]:focus {{ background:{surface_rgba('surface')}; border-color:{COLORS['nav_selected_frame']}; outline:none; }}
            QPushButton[navButton="true"]:checked {{ background:{surface_rgba('accent_soft')}; border-color:{COLORS['nav_selected_frame']}; color:{COLORS['nav_selected_text']}; }}
        """
        )
        # Keep the old page tree alive for backend compatibility, but use one
        # QML root for the entire visible application.
        self._ui_root_stack.addWidget(root)
        self._ui_root_stack.setCurrentWidget(root)
        self._install_qml_shell(initial_page)
        self.navigation.show(initial_page, record_history=False)
        if self.isVisible():
            QTimer.singleShot(150, self.start_initial_background_work)

        # Do not eagerly build/cache a full Qt widget tree for every Library
        # entry on the GUI thread. Detail views are rendered when selected and
        # episode cards are created in bounded event-loop batches.

    def _install_qml_shell(self, initial_page="home"):
        """Make one QML root responsible for the visible shell and every main route."""
        bridge = ApplicationBridge(parent=self, background_manager=self.background_manager)
        quick = QQuickWidget(self)
        quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        quick.setClearColor(QColor(COLORS["background"]))
        quick.rootContext().setContextProperty("appBridge", bridge)
        quick.rootContext().setContextProperty("qmlBridge", bridge)
        quick.statusChanged.connect(self._qml_shell_status_changed)
        scene_graph_error = getattr(quick, "sceneGraphError", None)
        if scene_graph_error is not None:
            scene_graph_error.connect(self._qml_shell_scene_graph_error)

        bridge.navigationRequested.connect(self._qml_navigation_requested)
        bridge.openWorkRequested.connect(self._qml_open_library_work)
        bridge.editBundleRequested.connect(self._qml_edit_bundle)
        bridge.deleteWorkRequested.connect(self._qml_delete_work)
        bridge.detailActionRequested.connect(self._qml_detail_action)
        bridge.libraryChanged.connect(self._qml_library_refreshed)
        bridge.addToLibraryRequested.connect(lambda work: self.add_to_library(work, None))
        bridge.searchWorkRequested.connect(self.show_search_work)
        bridge.profileRequested.connect(self._qml_profile_requested)
        bridge.setupRequested.connect(self.open_setup_wizard)
        bridge.updateRequested.connect(self.check_updates_requested.emit)
        bridge.diagnosticsExportRequested.connect(self._qml_export_diagnostics)
        bridge.settingsChanged.connect(self.apply_settings)
        bridge.rollbackRequested.connect(self.rollback_requested.emit)
        bridge.restartRequested.connect(self._restart_application)

        qml_path = Path(__file__).resolve().parent / "qml" / "ApplicationShell.qml"
        quick.setSource(QUrl.fromLocalFile(str(qml_path)))
        if quick.status() == QQuickWidget.Status.Error:
            log_event(
                "qml_shell.load_failed",
                errors=[error.toString() for error in quick.errors()][:30],
            )
            quick.deleteLater()
            bridge.deleteLater()
            self._qml_shell_enabled = False
            self.qml_bridge = None
            return False

        old_central = self.takeCentralWidget()
        if old_central is not None:
            old_central.setParent(self)
            old_central.hide()
            self._legacy_root_stack = old_central

        self.qml_bridge = bridge
        self._qml_shell_widget = quick
        self.setCentralWidget(quick)
        self._qml_shell_enabled = True
        bridge.initializePage(initial_page)
        log_event("qml_shell.loaded", source=str(qml_path))
        return True

    def _qml_navigation_requested(self, page_name):
        if not self._qml_shell_enabled:
            return
        if page_name not in getattr(self.navigation, "pages", {}):
            return
        self._qml_navigation_sync = True
        try:
            self.navigation.show(page_name, record_history=False)
        finally:
            self._qml_navigation_sync = False

    def _qml_open_library_work(self, work_id):
        if not self._qml_shell_enabled or self.qml_bridge is None:
            return
        group = self.qml_bridge._group_for_id(int(work_id))
        if group is not None:
            self.show_work_details(group)

    def _qml_edit_bundle(self, work_id):
        if self.qml_bridge is None:
            return
        group = self.qml_bridge._group_for_id(int(work_id))
        if group is not None:
            self.library_page._edit_bundle(group)
            self.qml_bridge.refreshAll()

    def _qml_delete_work(self, work_id):
        if self.qml_bridge is None:
            return
        group = self.qml_bridge._group_for_id(int(work_id))
        if group is not None:
            self.library_page._delete_item(group)
            QTimer.singleShot(0, self.qml_bridge.refreshAll)

    def _qml_detail_action(self, action, work_id):
        """Reuse existing bundle/identity dialogs only when the user requests them."""
        if not self._qml_shell_enabled or self.qml_bridge is None:
            return
        try:
            normalized_id = int(work_id)
        except (TypeError, ValueError, OverflowError):
            return

        bridge = self.qml_bridge
        group = bridge._group_for_id(normalized_id)
        raw_work = group or bridge._selected_work_raw
        if not isinstance(raw_work, dict):
            return

        # Keep the old detail widget available as a dialog/action host only.
        # Assign the selected record without eagerly building its hidden detail UI.
        legacy_detail = self.work_detail_page
        legacy_detail.work = raw_work
        try:
            if action == "auto_bundle":
                legacy_detail._start_auto_bundle()
                return
            if action == "add_to_bundle":
                legacy_detail._open_add_bundle_dialog()
            elif action == "remove_from_bundle":
                legacy_detail._open_remove_bundle_dialog()
            elif action == "customize_identity":
                legacy_detail._open_display_identity_editor()
            else:
                return
        except Exception as error:
            log_exception(
                "qml_shell.detail_action_failed",
                error,
                action=action,
                work_id=normalized_id,
            )
            return

        # These dialogs can write bundle memberships or display overrides.
        bridge.forceRefreshAll()
        bridge.refreshSelectedWork()

    def _qml_library_refreshed(self, _item_count=0):
        bridge = self.qml_bridge
        if not self._qml_shell_enabled or bridge is None:
            return
        if bridge.currentPage not in {"work_detail", "relation"}:
            return

        selected = bridge.selectedWork
        selected_id = selected.get("id")
        group = bridge._group_for_id(selected_id)
        if group is not None:
            bridge.setSelectedWork(group)
        elif selected.get("isInLibrary"):
            # Do not leave the detail route showing a record that was deleted.
            bridge.navigate("collections")

    def _qml_profile_requested(self, profile):
        if not isinstance(profile, dict):
            return
        self.show_entity_profile(profile.get("entity_type"), profile, from_favorites=True)

    def _qml_export_diagnostics(self):
        exporter = getattr(self.settings_page, "_export_diagnostics", None)
        if callable(exporter):
            exporter(False)

    def _qml_shell_status_changed(self, status):
        if status != QQuickWidget.Status.Error:
            return
        errors = []
        if self._qml_shell_widget is not None:
            errors = [error.toString() for error in self._qml_shell_widget.errors()]
        log_event("qml_shell.load_failed", errors=errors[:30])
        self._fallback_to_legacy_shell()

    def _qml_shell_scene_graph_error(self, error, message):
        log_event("qml_shell.scene_graph_error", error=str(error), message=str(message)[:1000])
        self._fallback_to_legacy_shell()

    def _fallback_to_legacy_shell(self):
        quick = self._qml_shell_widget
        if self.qml_bridge is not None:
            self.qml_bridge.requestShutdown()
        self._qml_shell_enabled = False
        self.qml_bridge = None
        self._qml_shell_widget = None
        if quick is not None:
            self.takeCentralWidget()
            quick.deleteLater()
        if self._legacy_root_stack is not None:
            self.setCentralWidget(self._legacy_root_stack)
            self._legacy_root_stack.show()
        log_event("qml_shell.legacy_fallback")

    def start_initial_background_work(self):
        """Start optional API work after Home has had a chance to paint."""
        if self._shutdown_requested or self._shutdown_event.is_set():
            return
        home = getattr(self, "home_page", None)
        if self._qml_shell_enabled and self.qml_bridge is not None:
            # Recommendations start only after the first frame; the local
            # Library snapshot is already loading off-thread.
            self.qml_bridge.markStartupReady()
        elif home is not None:
            home.start_initial_recommendations_load()
        if not self._startup_preload_scheduled:
            self._startup_preload_scheduled = True
            QTimer.singleShot(1_000, self._start_existing_library_episode_preload)

    def _refresh_library_after_bundle_change(self):
        if self._qml_shell_enabled and self.qml_bridge is not None:
            QTimer.singleShot(0, self.qml_bridge.refreshAll)
            return
        QTimer.singleShot(0, self.library_page.refresh)

    def _page_changed(self, page_name):
        if self._qml_shell_enabled and self.qml_bridge is not None:
            if self._qml_navigation_sync:
                self._last_navigation_page = page_name
                return
            self.qml_bridge.setCurrentPage(page_name)
            self.qml_bridge.refreshVisiblePage()
            self._last_navigation_page = page_name
            return
        if page_name == "settings":
            self.settings_page.ensure_built()
        previous_page = self._last_navigation_page
        if page_name == "home" and previous_page not in (None, "home"):
            # Refresh the local snapshot only when returning to the dashboard;
            # do not rebuild its artwork cards on every Home click.
            self.home_page.refresh()
        elif page_name == "search":
            # Search can keep its result widgets alive while a detail-page
            # override is edited. Reapply global identity overrides on return.
            for card in self.search_page.findChildren(QFrame):
                refresh_identity = getattr(card, "refresh_display_identity", None)
                if callable(refresh_identity):
                    refresh_identity()
        if page_name == "calendar":
            self.calendar_page.refresh()
        elif page_name == "favorites":
            self.favorites_page.refresh()
        if page_name == "collections":
            # Rebuild the library when returning to it so relation-sync failures
            # can be retried through the normal page refresh path.
            self.library_page.refresh()
        self._last_navigation_page = page_name

    def open_setup_wizard(self):
        wizard = SetupWizard(self)
        result = wizard.exec()
        if result == QDialog.Accepted:
            self.apply_settings("setup")

    def apply_settings(self, changed_key=""):
        if changed_key in ("theme_preset", "light_mode"):
            self._apply_theme_live()
            return
        if changed_key == "ui_scale":
            # Qt applies the global scale multiplier only at the next startup.
            return
        if self._settings_rebuild_pending:
            return
        self._settings_rebuild_pending = True
        QTimer.singleShot(0, lambda key=changed_key: self._rebuild_for_settings(key))

    def _restart_application(self):
        """Close workers cleanly, then relaunch with the saved startup scale."""
        self._restart_requested = True
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(False)
        self.close()

    def _apply_theme_live(self):
        refresh_theme()
        if hasattr(self, "background_manager"):
            self.background_manager.refresh_theme()
        if self._qml_shell_enabled and self.qml_bridge is not None:
            self.qml_bridge.refreshTheme()
            self.qml_bridge.refreshVisiblePage()
            return

        self.setStyleSheet(
            application_stylesheet()
            + f"""
            QFrame#sidebar {{ background:{surface_rgba('sidebar')}; border-right:1px solid {COLORS['frame']}; }}
            QFrame#brandBadge {{ background:transparent; border:none; }}
            QLabel#brandWord {{ background:transparent; border:none; padding:0; }}
            QPushButton[navButton="true"] {{ background:transparent; border:1px solid transparent; color:{COLORS['secondary']}; border-radius:11px; padding:13px 15px; text-align:left; font-size:14px; font-weight:600; }}
            QPushButton[navButton="true"]:hover {{ background:{surface_rgba('surface')}; color:{COLORS['primary']}; }}
            QPushButton[navButton="true"]:focus {{ background:{surface_rgba('surface')}; border-color:{COLORS['nav_selected_frame']}; outline:none; }}
            QPushButton[navButton="true"]:checked {{ background:{surface_rgba('accent_soft')}; border-color:{COLORS['nav_selected_frame']}; color:{COLORS['nav_selected_text']}; }}
            """
        )

        if hasattr(self, "brand_word"):
            self._update_brand_word()
        for button in self.navigation_buttons.values():
            button.refresh_icon()

        if hasattr(self, "home_page"):
            self.home_page.refresh_theme()

        if hasattr(self, "library_page"):
            self.library_page.refresh_theme()

        if hasattr(self, "search_page") and hasattr(self.search_page, "refresh_theme"):
            self.search_page.refresh_theme()

        if hasattr(self, "work_detail_page") and hasattr(self.work_detail_page, "refresh_theme"):
            self.work_detail_page.refresh_theme()

        if hasattr(self, "entity_profile_page") and hasattr(self.entity_profile_page, "refresh_theme"):
            self.entity_profile_page.refresh_theme()

        if hasattr(self, "settings_page") and hasattr(self.settings_page, "refresh_theme"):
            self.settings_page.refresh_theme()
        if hasattr(self, "calendar_page"):
            self.calendar_page.refresh_theme()
        if hasattr(self, "recommendations_page"):
            self.recommendations_page.refresh_theme()
        if hasattr(self, "favorites_page"):
            self.favorites_page.refresh_theme()

    def _request_page_tree_shutdown(self, root):
        """Ask workers owned by a page tree to stop before that tree is deleted."""
        if root is None:
            return
        for page in root.findChildren(SearchPage):
            page.request_shutdown()
        for page in root.findChildren(LibraryPage):
            page.request_shutdown()
        for page in root.findChildren(WorkDetailPage):
            page.request_shutdown()
        for page in root.findChildren(EntityProfilePage):
            page.request_shutdown()
        for page in root.findChildren(RecommendationsPage):
            page.request_shutdown()
        for thread in root.findChildren(QThread):
            try:
                thread.quit()
            except RuntimeError:
                pass

    def _retire_page_tree_when_idle(self, root):
        """Delete a replaced page tree only after its own QThreads have stopped."""
        if root is None:
            return
        timer = QTimer(self)
        timer.setInterval(100)

        def poll():
            for thread in root.findChildren(QThread):
                try:
                    if thread.isRunning():
                        return
                except RuntimeError:
                    continue
            timer.stop()
            timer.deleteLater()
            root.deleteLater()

        timer.timeout.connect(poll)
        timer.start()
        poll()

    def _rebuild_for_settings(self, changed_key):
        self._settings_rebuild_pending = False
        if self._qml_shell_enabled and self.qml_bridge is not None:
            self.qml_bridge.refreshTheme()
            self.qml_bridge.refreshVisiblePage()
            if changed_key in {"maximized", "reset"}:
                self.showMaximized() if get("maximized") else self.showNormal()
            return
        current_page = "home"
        if hasattr(self, "navigation"):
            current_widget = self.stack.currentWidget()
            for name, page in self.navigation.pages.items():
                if page is current_widget:
                    current_page = name
                    break

        old_root = self._ui_root_stack.currentWidget() if self._ui_root_stack else None
        was_maximized = self.isMaximized()
        was_fullscreen = self.isFullScreen()
        normal_geometry = self.normalGeometry()

        # Request cooperative shutdown without blocking settings changes.
        # The old root remains alive until every QThread it owns has stopped.
        self._request_page_tree_shutdown(old_root)
        self.navigation_buttons = {}

        # setup_ui() builds an entire new root and leaves the old root visible
        # until the final addWidget/setCurrentWidget swap.
        self.setup_ui(current_page)
        new_root = self._ui_root_stack.currentWidget()
        if changed_key in {
            "recommendation_voice_language",
            "reset",
            "bundle_include_movies",
            "bundle_include_ovas",
            "bundle_include_onas",
            "bundle_include_specials",
            "bundle_include_manga",
            "bundle_include_novels",
            "bundle_include_one_shots",
        }:
            # The rebuilt Home page reads the current preference and starts with
            # a fresh candidate ordering rather than retaining stale rankings.
            try:
                self.home_page.recommendations_page.refresh(force=True)
            except Exception as error:
                log_exception(
                    "recommendations.settings_refresh_failed",
                    error,
                    changed_key=changed_key,
                )

        if old_root is not None and old_root is not new_root:
            self._retire_page_tree_when_idle(old_root)

        # Only touch the native window state when that setting actually changed.
        # Calling showMaximized()/showNormal() for every theme change causes the
        # compositor to briefly blank the window.
        if changed_key == "maximized":
            if get("maximized"):
                self.showMaximized()
            else:
                self.showNormal()
                if normal_geometry.isValid():
                    self.setGeometry(normal_geometry)
        elif was_fullscreen:
            self.showFullScreen()
        elif was_maximized:
            # Preserve the existing maximized state without re-triggering it.
            pass
        else:
            # Preserve normal-window geometry without forcing another show cycle.
            pass

    def _update_brand_word(self):
        self.brand_word.set_wordmark(
            COLORS["accent"], light_mode=get("light_mode")
        )
        self.brand_word.setAccessibleName("NekoTrack")
        self.brand_word.setStyleSheet("background:transparent;border:none;padding:0;")

    def _add_nav(self, layout, icon, label, page_name):
        button = NavigationButton(icon, label)
        self.navigation_buttons[page_name] = button
        button.clicked.connect(lambda checked=False, n=page_name: self.navigation.show(n))
        layout.addWidget(button)

    def update_navigation_state(self, page_name):
        for name, button in self.navigation_buttons.items():
            selected = name == page_name
            button.setChecked(selected)
            button.refresh_icon()

    def _start_existing_library_episode_preload(self):
        if self._shutdown_event.is_set():
            return
        if (
            self._library_episode_preload_thread is not None
            and self._library_episode_preload_thread.isRunning()
        ):
            return

        try:
            refresh_ids = get_library_episode_catalog_refresh_ids(
                TMDB_EPISODE_CATALOG_VERSION,
                TMDB_EPISODE_CATALOG_REFRESH_INTERVAL_SECONDS,
            )
        except Exception as error:
            log_exception("library.episode_preload.candidate_query_failed", error)
            return

        log_event(
            "library.episode_preload.plan",
            candidate_count=len(refresh_ids),
            candidate_ids=refresh_ids[:100],
        )
        if not refresh_ids:
            return

        worker = LibraryEpisodePreloadWorker(refresh_ids, self._shutdown_event)
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(self._library_episode_preloaded)
        worker.error.connect(
            lambda work_id, message:
                print(
                    f"Existing library episode preload failed for "
                    f"{work_id}: {message}"
                )
        )
        worker.completed.connect(thread.quit)
        worker.completed.connect(self._library_episode_preload_completed)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda t=thread: self._library_episode_preload_thread_finished(t)
        )

        self._library_episode_preload_thread = thread
        self._library_episode_preload_worker = worker
        thread.start()

    def _library_episode_preloaded(self, work_id, episodes):
        if self._shutdown_event.is_set():
            return
        try:
            self.work_detail_page._start_episode_image_cache(
                int(work_id),
                [dict(episode) for episode in (episodes or [])],
            )

            # If this season belongs to the currently open bundle, replace its
            # loading section now. Never pre-build hidden full detail widget
            # trees for every Library group in the GUI thread.
            current_work = getattr(self.work_detail_page, "work", None)
            if current_work is not None:
                try:
                    if int(work_id) in self.work_detail_page._detail_work_ids():
                        self.work_detail_page._replace_episode_section()
                except Exception as error:
                    log_exception(
                        "library.episode_preload.refresh_open_detail_failed",
                        error,
                        work_id=work_id,
                    )
        except Exception as error:
            log_exception("library.episode_preload.ui_finalize_failed", error,
                          work_id=work_id)
            print(
                f"Existing library preload failed for work {work_id}: "
                f"{error}"
            )

    def _library_episode_preload_completed(self):
        if self._shutdown_event.is_set():
            return
        current_page = self.navigation.current_name()
        if current_page == "calendar":
            self.calendar_page.refresh()
        elif current_page == "home":
            self.home_page.refresh()

    def _library_episode_preload_thread_finished(self, thread):
        if self._library_episode_preload_thread is thread:
            self._library_episode_preload_thread = None
            self._library_episode_preload_worker = None


    def show_work_details(self, work):
        # A normal work selection starts a new navigation path. Preserve the
        # profile return target only while opening a work from a profile credit.
        if not self._opening_profile_credit_work:
            self._profile_work_return_state = None

        # Open the detail page immediately. Older library entries may still
        # need their full character/staff payload, so enrich them in
        # the existing background worker instead of blocking the click.
        raw_members = work.get("_series_members") if hasattr(work, "get") else None
        members = list(raw_members) if raw_members else [work]
        work_id = work.get("id") if hasattr(work, "get") else None
        selected_work_id = work_id
        log_event(
            "work_details.open_requested",
            work_id=work_id,
            member_count=len(members),
        )

        if self._qml_shell_enabled and self.qml_bridge is not None:
            self.qml_bridge.setSelectedWork(work)
        else:
            self.work_detail_page.set_work(work)
        log_event(
            "work_details.page_build_returned",
            work_id=work_id,
            member_count=len(members),
        )
        self.navigation.show("work_detail")
        log_event(
            "work_details.navigation_show_returned",
            work_id=work_id,
            member_count=len(members),
        )

        member_ids = []
        seen = set()
        for member in members:
            raw_id = member.get("id") if hasattr(member, "get") else None
            try:
                member_id = int(raw_id)
            except (TypeError, ValueError, OverflowError):
                continue
            if member_id > 0 and member_id not in seen:
                seen.add(member_id)
                member_ids.append(member_id)

        # Do not walk the database for every bundle member in the same GUI
        # event that opens the page. Check a few members between paint turns.
        QTimer.singleShot(
            0,
            lambda ids=tuple(member_ids), selected=selected_work_id:
                self._queue_detail_enrichment_batch(ids, selected, 0),
        )
        log_event(
            "work_details.open_flow_scheduled",
            work_id=selected_work_id,
            member_count=len(members),
            unique_member_count=len(member_ids),
        )


    def _queue_detail_enrichment_batch(self, member_ids, selected_work_id, offset=0):
        """Check bundle readiness in a worker before starting writes to the database."""
        if self._shutdown_requested or self._shutdown_event.is_set():
            return
        if offset:
            # Retain the old call shape for queued callbacks from older views;
            # one worker now checks the full list to avoid GUI-thread SQLite reads.
            member_ids = member_ids[offset:]
        ids = []
        seen = set()
        for value in member_ids or ():
            try:
                work_id = int(value)
            except (TypeError, ValueError, OverflowError):
                continue
            if work_id > 0 and work_id not in seen:
                seen.add(work_id)
                ids.append(work_id)

        if not ids:
            log_event(
                "work_details.open_flow_completed",
                work_id=selected_work_id,
                member_count=0,
                pending_enrichment_count=0,
            )
            return

        thread = QThread(self)
        thread.setProperty("detail_enrichment_selected_work_id", str(selected_work_id))
        worker = BundleEnrichmentCheckWorker(selected_work_id, ids)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._detail_enrichment_check_finished)
        worker.finished.connect(
            thread.quit,
            Qt.ConnectionType.DirectConnection,
        )
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._detail_enrichment_check_thread_stopped)
        thread.finished.connect(thread.deleteLater)
        self._detail_enrichment_check_jobs[thread] = {
            "worker": worker,
            "selected_work_id": selected_work_id,
            "member_ids": tuple(ids),
        }
        log_event(
            "work_details.enrichment_check_scheduled",
            work_id=selected_work_id,
            member_count=len(ids),
        )
        thread.start()

    def _detail_enrichment_check_finished(self, selected_work_id, pending_ids, failed_ids):
        """Mark required work before delaying write-heavy imports until initial reads return."""
        if self._shutdown_requested or self._shutdown_event.is_set():
            return
        pending_ids = tuple(int(work_id) for work_id in (pending_ids or ()))
        self._detail_enrichment_ids.update(pending_ids)
        log_event(
            "work_details.open_flow_completed",
            work_id=selected_work_id,
            pending_enrichment_count=len(pending_ids),
            failed_check_count=len(failed_ids or ()),
        )
        if pending_ids:
            # Give the initial episode detail callback time to finish its short
            # GUI-side lookups before imports begin writing to the shared SQLite DB.
            QTimer.singleShot(
                250,
                lambda ids=pending_ids: self._queue_library_imports(ids),
            )

    def _detail_enrichment_check_thread_stopped(self):
        thread = self.sender()
        if thread is None:
            return
        job = self._detail_enrichment_check_jobs.pop(thread, None)
        if job is not None:
            log_event(
                "work_details.enrichment_check_thread_stopped",
                work_id=job.get("selected_work_id"),
                member_count=len(job.get("member_ids") or ()),
            )


    def show_search_work(self, work):
        """Open a Search result immediately; enrichment runs in background workers."""
        if not work:
            return
        try:
            work_id = int(work["id"])
        except (KeyError, TypeError, ValueError, OverflowError):
            work_id = None

        # Prefer the richer local snapshot for an already imported individual
        # work, but keep a Search-produced bundle record intact.
        if work_id is not None and not (
            isinstance(work, dict) and work.get("_series_members")
        ):
            try:
                saved_work = get_work(work_id)
            except Exception as error:
                log_exception(
                    "work_details.search_local_lookup_failed",
                    error,
                    work_id=work_id,
                )
                saved_work = None
            if saved_work is not None:
                work = saved_work

        log_event(
            "work_details.search_selected",
            work_id=work_id,
            enrichment="background",
        )
        # show_work_details queues the existing bounded LibraryImportWorker
        # for missing provider data. Never call get_media_details/GraphQL in
        # this Qt slot: connection retries must not freeze the main window.
        self.show_work_details(work)

    def show_profile_credit_work(self, work):
        """Open a work from a character/staff credit inside NekoTrack."""
        if not work:
            return
        self._profile_work_return_state = self.entity_profile_page.profile_state()
        self._opening_profile_credit_work = True
        try:
            self.show_search_work(work)
        finally:
            self._opening_profile_credit_work = False

    def _back_from_work_detail(self):
        """Return to the profile that opened an internal media-credit page."""
        state = self._profile_work_return_state
        self._profile_work_return_state = None
        if isinstance(state, dict):
            self.entity_profile_page.set_profile(
                state["entity_type"],
                state["record"],
                source_work=state["source_work"],
                voice_actors=state["voice_actors"],
            )
            self.navigation.back(fallback="entity_profile", skip=("work_detail",))
            return
        self.navigation.back(fallback="collections", skip=("work_detail",))

    def show_entity_profile(self, entity_type, entity, from_favorites=False):
        """Open a detailed character, staff, or voice-actor profile."""
        if not entity:
            return
        kind = str(entity_type or "").strip().lower()
        if self._qml_shell_enabled and self.qml_bridge is not None:
            try:
                record = dict(entity)
            except (TypeError, ValueError):
                record = {"name": str(entity)}
            record["entity_type"] = kind
            self.qml_bridge.setSelectedProfile(record)
            self.navigation.show("entity_profile", record_history=False)
            return
        # Preserve whichever profile launched this one, including character
        # links opened from a voice actor's voice-acting credits. Back returns
        # through the same profile path in either direction.
        if self.stack.currentWidget() is self.entity_profile_page:
            self._entity_profile_history.append(
                self.entity_profile_page.profile_state()
            )
        else:
            self._entity_profile_history.clear()

        try:
            record = dict(entity)
        except (TypeError, ValueError):
            record = entity
        voice_actors = None
        if kind == "character" and not from_favorites:
            try:
                character_id = record.get("id") if hasattr(record, "get") else record["id"]
                voice_actors = get_bundle_character_voice_actors(
                    self.work_detail_page._detail_work_ids(),
                    character_id,
                )
                if isinstance(record, dict):
                    record["voice_actors"] = voice_actors
            except (KeyError, TypeError, ValueError, OverflowError):
                voice_actors = []

        self.entity_profile_page.set_profile(
            kind,
            record,
            source_work=None if from_favorites else self.work_detail_page.work,
            voice_actors=voice_actors,
        )
        self.navigation.show("entity_profile")
        if kind == "character" and not voice_actors and not from_favorites:
            self._queue_missing_character_voice_actor_refresh(
                record,
                self.work_detail_page._detail_work_ids(),
            )

    def _queue_missing_character_voice_actor_refresh(self, record, work_ids):
        """Refresh every anime member when no bundled voice-actor credit is cached."""
        if self._shutdown_requested or self._shutdown_event.is_set():
            return

        try:
            character_id = int(
                record.get("id") if hasattr(record, "get") else record["id"]
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            return
        if character_id <= 0:
            return

        bundle_work_ids = []
        for raw_id in work_ids or []:
            try:
                work_id = int(raw_id)
            except (TypeError, ValueError, OverflowError):
                continue
            if work_id > 0 and work_id not in bundle_work_ids:
                bundle_work_ids.append(work_id)
        if not bundle_work_ids:
            return

        key = (character_id, tuple(sorted(bundle_work_ids)))
        if key in self._completed_character_cast_refreshes:
            log_event(
                "character.voice_actor_refresh.not_queued",
                character_id=character_id,
                bundle_work_count=len(bundle_work_ids),
                reason="already_refreshed_this_session",
            )
            return

        state = self._pending_character_cast_refreshes.get(key)
        already_pending = (
            state.get("pending_work_ids", set()) if isinstance(state, dict) else set()
        )

        # Do not use cached character rows to decide which work to refresh.
        # A missing row can be the corruption/incompleteness we're recovering
        # from, and would otherwise exclude the one adaptation holding the
        # missing actor credit. Since no voice actors are cached for this
        # character anywhere in the bundle, refresh every anime member.
        candidate_ids = []
        for work_id in bundle_work_ids:
            try:
                work = get_work(work_id)
                if work is None or str(work["type"] or "").upper() != "ANIME":
                    continue
                if work_id not in already_pending:
                    candidate_ids.append(work_id)
            except Exception as error:
                log_exception(
                    "character.voice_actor_refresh.status_failed",
                    error,
                    character_id=character_id,
                    work_id=work_id,
                )

        if not candidate_ids:
            if not already_pending:
                log_event(
                    "character.voice_actor_refresh.not_queued",
                    character_id=character_id,
                    bundle_work_count=len(bundle_work_ids),
                    reason="no_cached_anime_bundle_members",
                )
            return

        try:
            invalidated = invalidate_character_snapshots(candidate_ids)
        except Exception as error:
            log_exception(
                "character.voice_actor_refresh.invalidate_failed",
                error,
                character_id=character_id,
                work_ids=candidate_ids,
            )
            return
        if invalidated <= 0:
            log_event(
                "character.voice_actor_refresh.not_queued",
                character_id=character_id,
                bundle_work_count=len(bundle_work_ids),
                reason="no_cast_snapshots_invalidated",
            )
            return

        if state is None:
            state = {
                "character_id": character_id,
                "work_ids": tuple(sorted(bundle_work_ids)),
                "pending_work_ids": set(),
            }
            self._pending_character_cast_refreshes[key] = state
        state["pending_work_ids"].update(candidate_ids)
        self._detail_enrichment_ids.update(candidate_ids)

        log_event(
            "character.voice_actor_refresh.queued",
            character_id=character_id,
            bundle_work_count=len(bundle_work_ids),
            refresh_work_ids=candidate_ids,
        )
        self._queue_library_imports(candidate_ids)
        # Avoid repeatedly re-importing the entire bundle on every profile open
        # if the provider still has no credit to return. A new app session can
        # retry after a provider/data update.
        self._completed_character_cast_refreshes.add(key)

    def _complete_pending_character_cast_refresh(self, work_id):
        """Re-read cached actor credits after all targeted cast imports stop."""
        try:
            work_id = int(work_id)
        except (TypeError, ValueError, OverflowError):
            return

        completed = []
        for key, state in list(self._pending_character_cast_refreshes.items()):
            pending = state.get("pending_work_ids")
            if not isinstance(pending, set) or work_id not in pending:
                continue
            pending.discard(work_id)
            if not pending:
                self._pending_character_cast_refreshes.pop(key, None)
                completed.append(state)

        for state in completed:
            character_id = state["character_id"]
            try:
                voice_actors = get_bundle_character_voice_actors(
                    state["work_ids"], character_id
                )
            except Exception as error:
                log_exception(
                    "character.voice_actor_refresh.read_failed",
                    error,
                    character_id=character_id,
                    work_ids=list(state["work_ids"]),
                )
                continue

            self._update_character_voice_actor_profiles(character_id, voice_actors)

    def _update_character_voice_actor_profiles(self, character_id, voice_actors):
        """Refresh visible and saved navigation states for one character profile."""
        actors = [
            dict(actor) for actor in (voice_actors or [])
            if isinstance(actor, dict) or hasattr(actor, "keys")
        ]

        def matches(state):
            if not isinstance(state, dict) or state.get("entity_type") != "character":
                return False
            record = state.get("record")
            if not isinstance(record, dict):
                return False
            try:
                return int(record.get("id")) == character_id
            except (TypeError, ValueError, OverflowError):
                return False

        def update_saved_state(state):
            if not matches(state):
                return
            record = dict(state["record"])
            record["voice_actors"] = [dict(actor) for actor in actors]
            state["record"] = record
            state["voice_actors"] = [dict(actor) for actor in actors]

        for state in self._entity_profile_history:
            update_saved_state(state)
        update_saved_state(self._profile_work_return_state)

        current_record = getattr(self.entity_profile_page, "current_record", {})
        try:
            current_id = int(current_record.get("id"))
        except (AttributeError, TypeError, ValueError, OverflowError):
            current_id = 0
        if (
            self.entity_profile_page.current_type == "character"
            and current_id == character_id
        ):
            updated_record = dict(current_record)
            updated_record["voice_actors"] = [dict(actor) for actor in actors]
            self.entity_profile_page.set_profile(
                "character",
                updated_record,
                source_work=self.entity_profile_page.source_work,
                voice_actors=actors,
            )

        log_event(
            "character.voice_actor_refresh.completed",
            character_id=character_id,
            actor_count=len(actors),
        )

    def _back_from_entity_profile(self):
        """Return to the character profile when a voice actor opened from it."""
        if self._entity_profile_history:
            state = self._entity_profile_history.pop()
            self.entity_profile_page.set_profile(
                state["entity_type"],
                state["record"],
                source_work=state["source_work"],
                voice_actors=state["voice_actors"],
            )
            return
        self.navigation.back(fallback="work_detail", skip=("entity_profile",))

    def show_relation(self, relation):
        if not relation:
            return
        try:
            target_id = relation["target_id"]
        except (KeyError, TypeError, IndexError):
            target_id = relation.get("target_id") if hasattr(relation, "get") else None
        work = get_work(target_id) if target_id else None
        if work:
            self.show_work_details(work)

    def add_to_library(self, anime, button):
        try:
            primary_id = int(anime["id"])

            # A bundled Search result carries every member in _series_members.
            # Add the whole bundle instead of only the representative result.
            members = anime.get("_series_members") if hasattr(anime, "get") else None
            if not members:
                members = [anime]

            bundle_members = []
            seen_ids = set()
            for member in members:
                try:
                    member_id = int(member["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                if member_id in seen_ids:
                    continue
                seen_ids.add(member_id)
                bundle_members.append(member)

            if not bundle_members:
                bundle_members = [anime]

            title_value = anime.get("title")
            log_event(
                "library.add_requested",
                representative_id=primary_id,
                representative_title=(
                    title_value.get("english") or title_value.get("romaji")
                    if isinstance(title_value, dict) else title_value
                ),
                member_count=len(bundle_members),
                members=[
                    {
                        "id": member.get("id"),
                        "title": member.get("title"),
                        "type": member.get("type"),
                        "format": member.get("format"),
                    }
                    for member in bundle_members[:50]
                ],
            )
            membership_ids = []
            for member in bundle_members:
                member_id = int(member["id"])

                # Save all lightweight records and Library membership first.
                # Persist the Search snapshot before starting provider imports.
                save_anime(member)
                add_to_library(member_id, "Planning")
                membership_ids.append(member_id)

            save_automatic_bundle_membership(primary_id, membership_ids)
            log_event(
                "library.add_bundle_membership_saved",
                bundle_id=primary_id,
                member_count=len(membership_ids),
            )
            self._queue_library_imports(membership_ids)

            if button is not None:
                button.setText("Added")
                button.setEnabled(False)
            if self._qml_shell_enabled and self.qml_bridge is not None:
                self.qml_bridge.forceRefreshAll()
                self.qml_bridge.refreshVisiblePage()
            else:
                self.library_page.refresh()

            # The QML poster cache handles artwork for the visible interface.
            if button is not None:
                self.start_cover_download(
                    primary_id,
                    (anime.get("coverImage") or {}).get("large"),
                    button,
                )
        except Exception as error:
            log_exception("library.add_failed", error,
                          work_id=anime.get("id") if hasattr(anime, "get") else None)
            if button is not None:
                button.setText("Error")
            if self._qml_shell_enabled and self.qml_bridge is not None:
                self.qml_bridge.reportSearchError(f"Could not save: {error}")
            self.search_page.results_title.setText(f"Could not save: {error}")


    def _library_import_finished(self, work_id, details):
        work_id = int(work_id)
        self._detail_enrichment_ids.discard(work_id)
        if self._shutdown_event.is_set():
            return

        # Episode artwork is cached by WorkDetailPage when a season's saved
        # catalog is displayed. Do not query SQLite here: other members of this
        # bundle may still be writing their imports, and this row shape also
        # differs from the TMDB episode-image cache worker's input schema.

        self._refresh_open_detail_after_import(work_id)

    def _library_import_error(self, work_id, message):
        work_id = int(work_id)
        self._detail_enrichment_ids.discard(work_id)
        log_event("library.import.error_signal", work_id=work_id, error=message)
        # The basic Library entry remains usable when optional metadata fails;
        # still flush a deferred refresh after the last bundle import completes.
        self._refresh_open_detail_after_import(work_id)

    def _refresh_open_detail_after_import(self, work_id):
        """Refresh an open bundle once its required member imports have settled."""
        if self._shutdown_event.is_set():
            return

        if self._qml_shell_enabled and self.qml_bridge is not None:
            selected = self.qml_bridge.selectedWork
            current_ids = {
                int(value)
                for value in (selected.get("memberIds") or [selected.get("id")])
                if value is not None
            }
            if int(work_id) not in current_ids:
                return
            pending_ids = current_ids.intersection(self._detail_enrichment_ids)
            if pending_ids:
                log_event(
                    "library.import.qml_detail_refresh_deferred",
                    work_id=work_id,
                    pending_member_ids=sorted(pending_ids),
                )
                return
            raw_work = self.qml_bridge._selected_work_raw
            QTimer.singleShot(
                0,
                lambda current=raw_work, bridge=self.qml_bridge:
                    bridge.setSelectedWork(current) if bridge is not None else None,
            )
            log_event(
                "library.import.qml_detail_refresh_queued",
                work_id=work_id,
                member_count=len(current_ids),
            )
            return

        current_work = getattr(self.work_detail_page, "work", None)
        if current_work is None:
            return

        try:
            current_ids = {
                int(member["id"])
                for member in self.work_detail_page._detail_work_ids()
            }
        except Exception as error:
            log_exception(
                "library.import.detail_refresh_ids_failed",
                error,
                work_id=work_id,
            )
            return

        if int(work_id) not in current_ids:
            return

        pending_ids = current_ids.intersection(self._detail_enrichment_ids)
        if pending_ids:
            log_event(
                "library.import.detail_refresh_deferred",
                work_id=work_id,
                pending_member_count=len(pending_ids),
                pending_member_ids=sorted(pending_ids),
            )
            return

        log_event(
            "library.import.detail_refresh_after_bundle_idle",
            work_id=work_id,
            member_count=len(current_ids),
        )
        self.work_detail_page.set_work(current_work)

    def _queue_library_imports(self, work_ids):
        """Queue imports and reserve only a bounded number of worker threads."""
        if self._shutdown_requested or self._shutdown_event.is_set():
            return
        for work_id in self._library_import_queue.enqueue(work_ids):
            self._start_library_import_thread(work_id)

    def _start_library_import_thread(self, work_id):
        worker = LibraryImportWorker(int(work_id), self._shutdown_event)
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(self._library_import_finished)
        worker.error.connect(self._library_import_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        # Queue completion from the worker thread onto MainWindow's GUI thread
        # before releasing a slot or creating the next QThread.
        thread.finished.connect(
            lambda t=thread, w=worker, wid=int(work_id):
                self._library_import_thread_stopped.emit(t, w, wid)
        )

        self.library_import_threads.append(thread)
        self.library_import_workers.append(worker)
        thread.start()

    def _library_import_thread_finished(self, thread, worker, work_id):
        if thread in self.library_import_threads:
            self.library_import_threads.remove(thread)
        if worker in self.library_import_workers:
            self.library_import_workers.remove(worker)
        thread.deleteLater()

        self._complete_pending_character_cast_refresh(work_id)
        next_ids = self._library_import_queue.complete(work_id)
        if not self._shutdown_requested:
            for next_id in next_ids:
                self._start_library_import_thread(next_id)

    def _check_release_reminders(self):
        """Show enabled reminders once on their stored air date."""
        if self._shutdown_requested or not self._release_reminder_tray.isVisible():
            return
        try:
            due = [dict(row) for row in get_due_release_reminders()]
        except Exception as error:
            log_exception("release_reminders.check_failed", error)
            return
        if not due:
            return
        display_lines = []
        for item in due[:5]:
            title = str(item.get("work_title") or "Untitled")
            try:
                number = int(item.get("episode_number") or 0)
            except (TypeError, ValueError, OverflowError):
                number = 0
            display_lines.append(f"{title} · Episode {number}")
        if len(due) > 5:
            display_lines.append(f"and {len(due) - 5} more")
        self._release_reminder_tray.showMessage(
            "NekoTrack · Releases today",
            "\n".join(display_lines),
            QSystemTrayIcon.MessageIcon.Information,
            10_000,
        )
        for item in due:
            try:
                mark_release_reminder_notified(item["work_id"], item["episode_number"])
            except Exception as error:
                log_exception(
                    "release_reminders.mark_notified_failed",
                    error,
                    work_id=item.get("work_id"),
                    episode_number=item.get("episode_number"),
                )

    def _running_worker_threads(self):
        """Return the active page/update QThreads without blocking the GUI."""
        running = []
        for thread in self.findChildren(QThread):
            try:
                if thread.isRunning():
                    running.append(thread)
            except RuntimeError:
                continue
        return running

    def _has_running_worker_threads(self):
        return bool(self._running_worker_threads())

    def _launch_restarted_application(self):
        app = QApplication.instance()
        if app is None:
            return

        if getattr(sys, "frozen", False):
            program = sys.executable
            arguments = list(sys.argv[1:])
        else:
            program = sys.executable
            script = Path(__file__).resolve().parents[1] / "main.py"
            arguments = [str(script), *sys.argv[1:]]

        try:
            result = QProcess.startDetached(program, arguments, str(Path.cwd()))
            started = result[0] if isinstance(result, tuple) else bool(result)
        except Exception as error:
            log_exception("app.restart.failed", error)
            started = False

        if not started:
            QMessageBox.warning(
                None,
                "Restart failed",
                "Your scale choice is saved, but NekoTrack could not reopen itself. "
                "Close and launch NekoTrack again to apply the new scale.",
            )
        app.quit()

    def closeEvent(self, event):
        if not self._shutdown_requested:
            self._shutdown_started_at = time.monotonic()
            log_event("app.shutdown_requested")
            self._release_reminder_timer.stop()
            if self._release_reminder_tray.isVisible():
                self._release_reminder_tray.hide()

        self._shutdown_requested = True
        self._shutdown_event.set()
        if self.qml_bridge is not None:
            self.qml_bridge.requestShutdown()
        request_api_shutdown()
        self._library_import_queue.close()

        for search_page in self.findChildren(SearchPage):
            search_page.request_shutdown()
        for library_page in self.findChildren(LibraryPage):
            library_page.request_shutdown()
        for detail_page in self.findChildren(WorkDetailPage):
            detail_page.request_shutdown()
        for profile_page in self.findChildren(EntityProfilePage):
            profile_page.request_shutdown()
        for recommendations_page in self.findChildren(RecommendationsPage):
            recommendations_page.request_shutdown()
        # Stop event loops; an in-flight provider request must still return.
        # Keep the disabled window present until workers finish, so "closed"
        # never means a hidden process is still using the database in the back.
        for thread in self.findChildren(QThread):
            try:
                cancel = getattr(thread, "cancel", None)
                if callable(cancel):
                    try:
                        cancel()
                    except TypeError:
                        thread.requestInterruption()
                else:
                    thread.requestInterruption()
                thread.quit()
            except (RuntimeError, TypeError):
                continue

        running_threads = self._running_worker_threads()
        if running_threads:
            self._shutdown_waited_for_workers = True
            elapsed_ms = (
                round((time.monotonic() - self._shutdown_started_at) * 1000, 2)
                if self._shutdown_started_at is not None else 0.0
            )
            log_event(
                "app.shutdown_waiting_for_workers",
                elapsed_ms=elapsed_ms,
                running_thread_count=len(running_threads),
                running_thread_names=[
                    thread.objectName() or "<unnamed QThread>"
                    for thread in running_threads
                ],
            )
            self.setEnabled(False)
            event.ignore()
            if not self._shutdown_timer.isActive():
                self._shutdown_timer.start()
            return

        self._shutdown_timer.stop()
        elapsed_ms = (
            round((time.monotonic() - self._shutdown_started_at) * 1000, 2)
            if self._shutdown_started_at is not None else 0.0
        )
        log_event(
            "app.shutdown_completed",
            elapsed_ms=elapsed_ms,
            waited_for_workers=self._shutdown_waited_for_workers,
        )
        if self._release_reminder_tray.isVisible():
            self._release_reminder_tray.hide()
        reset_api_shutdown()
        event.accept()
        if self._restart_requested and not self._restart_launch_scheduled:
            self._restart_launch_scheduled = True
            QTimer.singleShot(250, self._launch_restarted_application)

    def _poll_shutdown_workers(self):
        if self._has_running_worker_threads():
            return
        self._shutdown_timer.stop()
        self.close()

    def start_cover_download(self, work_id, image_url, button):
        if not image_url:
            return
        worker = ImageWorker(work_id, image_url)
        worker.finished.connect(self.cover_download_finished)
        worker.error.connect(self.cover_download_error)
        thread = threading.Thread(target=worker.run, daemon=True)
        self.image_threads.append(thread)
        thread.start()
        button.setProperty("cover_work_id", work_id)

    def cover_download_finished(self, work_id, cover_path):
        if cover_path:
            save_cover_path(work_id, cover_path)
        self._finish_cover_button(work_id)

    def cover_download_error(self, work_id, message):
        self._finish_cover_button(work_id, f"Cover unavailable: {message}")

    def _finish_cover_button(self, work_id, tooltip=None):
        for button in self.findChildren(QPushButton):
            if button.property("cover_work_id") == work_id:
                button.setText("Added")
                button.setToolTip(tooltip or "")
                break
