"""Bridge for the single-root QML application shell; Python remains the data/backend layer."""
from __future__ import annotations

import datetime
import os
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Property, QRunnable, QThread, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFileDialog

from api import get_entity_profile
from catalog_search import search_combined_media
from database import (
    get_all_library,
    get_bundle_characters,
    get_bundle_relations,
    get_bundle_staff,
    get_entity_favorites,
    get_episode_section_snapshot,
    get_reading_progress,
    get_recommendation_history,
    get_release_reminders,
    get_upcoming_library_episodes,
    is_work_in_library,
    record_recommendation_impressions,
    is_entity_favorite,
    set_entity_favorite,
    set_episode_progress,
    set_reading_progress_count,
    set_recommendation_feedback,
    set_release_reminder,
)
from diagnostics import log_event, log_exception
from recommendation_engine import inject_rare_exploration, rank_candidates
from series import get_library_series, group_media_results
from ui.pages.recommendations_page import RecommendationWorker
from ui.bundle_options import BUNDLE_OPTION_GROUPS, BUNDLE_OPTION_KEYS
from ui.preferences import UI_SCALE_OPTIONS, apply_theme_preset, defaults, get, reset, set_value
from ui.qml_bridge import (
    QmlApplicationBridge as LibraryBridge,
    _normalize_group,
    _optional_int,
)
from ui.theme import COLORS, THEME_PRESETS, refresh_theme, surface_qml_color


def _plain(value):
    """Convert SQLite/provider values into Qt/QML-safe Python values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if hasattr(value, "keys"):
        try:
            return {str(key): _plain(value[key]) for key in value.keys()}
        except Exception:
            pass
    if isinstance(value, (list, tuple, set)):
        return [_plain(item) for item in value]
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    try:
        return str(value)
    except Exception:
        return ""


def _title(value):
    if isinstance(value, dict):
        return str(
            value.get("english")
            or value.get("romaji")
            or value.get("native")
            or ""
        ).strip()
    return str(value or "").strip()


def _file_source(path):
    try:
        candidate = Path(str(path or "")).expanduser().resolve()
        if candidate.is_file():
            return QUrl.fromLocalFile(str(candidate)).toString()
    except (OSError, RuntimeError, ValueError):
        pass
    return ""


def _image_source(record):
    if not isinstance(record, dict):
        return ""
    path = record.get("cover_path") or record.get("image_path")
    local = _file_source(path)
    if local:
        return local
    raw_url = record.get("cover_url") or record.get("image_url")
    if not raw_url:
        image = record.get("coverImage") or record.get("image")
        if isinstance(image, dict):
            raw_url = image.get("extraLarge") or image.get("large")
    if isinstance(raw_url, str):
        qurl = QUrl(raw_url)
        if qurl.isValid() and qurl.scheme().casefold() in {"https", "http"}:
            return qurl.toString()
    return ""


class _LibrarySignals(QObject):
    finished = Signal(int, object, object)


class _LibrarySnapshotWorker(QRunnable):
    """Read and group Library rows away from the UI thread."""

    def __init__(self, generation):
        super().__init__()
        self.generation = int(generation)
        self.signals = _LibrarySignals()

    @Slot()
    def run(self):
        try:
            rows = get_library_series()
            self.signals.finished.emit(self.generation, rows or [], None)
        except Exception as error:
            self.signals.finished.emit(
                self.generation,
                None,
                f"{type(error).__name__}: {error}",
            )


class _SearchSignals(QObject):
    finished = Signal(int, int, object, object)


class _SearchWorker(QRunnable):
    """Run provider requests away from the GUI thread."""

    def __init__(self, generation, page, query, media_type, media_format, filters):
        super().__init__()
        self.generation = generation
        self.page = page
        self.query = query
        self.media_type = media_type
        self.media_format = media_format
        self.filters = dict(filters or {})
        self.signals = _SearchSignals()

    @Slot()
    def run(self):
        try:
            result = search_combined_media(
                self.query,
                self.page,
                self.media_type or None,
                self.media_format or None,
                self.filters,
                include_relations=not bool(self.filters.get("fast_search")),
            )
            self.signals.finished.emit(self.generation, self.page, result, None)
        except Exception as error:
            self.signals.finished.emit(
                self.generation,
                self.page,
                None,
                f"{type(error).__name__}: {error}",
            )


class _ProfileSignals(QObject):
    finished = Signal(int, object, object)


class _DetailSignals(QObject):
    finished = Signal(int, object, object)


class _DetailSnapshotWorker(QRunnable):
    """Build QML detail snapshots from SQLite without blocking the GUI thread."""

    def __init__(self, generation, work_id, member_ids, member_titles=None):
        super().__init__()
        self.generation = int(generation)
        self.work_id = int(work_id)
        self.member_ids = tuple(dict.fromkeys(
            int(value) for value in (member_ids or ())
            if _optional_int(value) not in (None, 0)
        ))
        self.member_titles = {
            int(key): str(value or "").strip()
            for key, value in (member_titles or {}).items()
            if _optional_int(key) not in (None, 0)
        }
        self.signals = _DetailSignals()

    @Slot()
    def run(self):
        try:
            member_ids = self.member_ids or (self.work_id,)
            episodes = []
            local_rows = {}
            progress_episodes = 0
            episode_total = 0
            progress_chapters = 0
            chapter_total = 0
            progress_volumes = 0
            volume_total = 0
            reading_progress_by_work = {}

            # Fetch episode rows independently for every member. Bundle ids are
            # kept in the canonical series order and every episode retains its
            # owning id so the QML checkbox writes progress to the right season.
            # Keep the visible snapshot bounded even for large bundles.
            for member_id in member_ids:
                snapshot = get_episode_section_snapshot(member_id)
                local_work = snapshot.get("work")
                row_work = _plain(dict(local_work)) if local_work is not None else {}
                local_rows[member_id] = row_work
                member_title = str(
                    row_work.get("title")
                    or self.member_titles.get(member_id)
                    or f"Work {member_id}"
                )
                progress_episodes += _optional_int(row_work.get("progress_episodes")) or 0
                episode_total += _optional_int(row_work.get("episodes")) or 0

                for source in snapshot.get("episodes") or []:
                    if len(episodes) >= 300:
                        break
                    row = _plain(dict(source))
                    number = _optional_int(row.get("episode_number"))
                    if number is None:
                        continue
                    episodes.append({
                        "workId": member_id,
                        "workTitle": member_title,
                        "episodeNumber": number,
                        "title": str(row.get("title") or f"Episode {number}"),
                        "description": str(row.get("description") or ""),
                        "airDate": str(row.get("air_date") or ""),
                        "watched": bool(row.get("watched")),
                        "coverSource": _file_source(row.get("thumbnail_path") or row.get("image_path"))
                            or _image_source({"cover_url": row.get("image_url")}),
                    })

                chapters, chapters_total = get_reading_progress(member_id, "chapter")
                volumes, volumes_total = get_reading_progress(member_id, "volume")
                progress_chapters += _optional_int(chapters) or 0
                chapter_total += _optional_int(chapters_total) or 0
                progress_volumes += _optional_int(volumes) or 0
                volume_total += _optional_int(volumes_total) or 0
                reading_progress_by_work[str(member_id)] = {
                    "chapters": _optional_int(chapters) or 0,
                    "chapterTotal": _optional_int(chapters_total) or 0,
                    "volumes": _optional_int(volumes) or 0,
                    "volumeTotal": _optional_int(volumes_total) or 0,
                }

            local_row = local_rows.get(self.work_id, {})
            if not local_row and local_rows:
                local_row = next(iter(local_rows.values()))
            characters = []
            for source in get_bundle_characters(member_ids) or []:
                row = _plain(dict(source))
                characters.append({
                    "id": _optional_int(row.get("id")) or 0,
                    "name": str(row.get("character_name") or "Unknown character"),
                    "role": str(row.get("character_role") or ""),
                    "coverSource": _file_source(row.get("character_image_path"))
                        or _image_source({"cover_url": row.get("character_image_url")}),
                    "voiceActorId": _optional_int(row.get("person_id")) or 0,
                    "voiceActorName": str(row.get("person_name") or ""),
                    "voiceActorLanguage": str(row.get("person_language") or ""),
                    "voiceActorCoverSource": _file_source(row.get("person_image_path"))
                        or _image_source({"cover_url": row.get("person_image_url")}),
                })

            staff = []
            for source in get_bundle_staff(member_ids) or []:
                row = _plain(dict(source))
                staff.append({
                    "id": _optional_int(row.get("person_id")) or 0,
                    "name": str(row.get("name") or "Unknown staff"),
                    "role": str(row.get("role") or ""),
                    "coverSource": _file_source(row.get("image_path"))
                        or _image_source({"cover_url": row.get("image_url")}),
                })

            relations = []
            for source in get_bundle_relations(member_ids) or []:
                row = _plain(dict(source))
                target_id = _optional_int(row.get("target_id"))
                if target_id in (None, 0):
                    continue
                relations.append({
                    "id": target_id,
                    "title": str(row.get("title") or f"Work {target_id}"),
                    "mediaType": str(row.get("type") or "UNKNOWN").upper(),
                    "format": str(row.get("format") or "").upper(),
                    "coverSource": _file_source(row.get("cover_path"))
                        or _image_source({"cover_url": row.get("cover_url")}),
                    "relationTypes": str(row.get("relation_types") or row.get("relation_type") or "RELATED"),
                })

            payload = {
                "episodes": episodes,
                "characters": characters,
                "staff": staff,
                "relations": relations,
                "localWork": local_row,
                "progressEpisodes": progress_episodes,
                "episodeTotal": episode_total,
                "hasLocalWork": any(bool(row) for row in local_rows.values()),
                "readingProgressByWork": reading_progress_by_work,
                "progressChapters": progress_chapters,
                "chapterTotal": chapter_total,
                "progressVolumes": progress_volumes,
                "volumeTotal": volume_total,
            }
            self.signals.finished.emit(self.generation, payload, None)
        except Exception as error:
            self.signals.finished.emit(
                self.generation,
                None,
                f"{type(error).__name__}: {error}",
            )


class _ProfileWorker(QRunnable):
    def __init__(self, generation, entity_type, entity_id):
        super().__init__()
        self.generation = generation
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.signals = _ProfileSignals()

    @Slot()
    def run(self):
        try:
            result = get_entity_profile(self.entity_type, self.entity_id)
            self.signals.finished.emit(self.generation, result, None)
        except Exception as error:
            self.signals.finished.emit(
                self.generation,
                None,
                f"{type(error).__name__}: {error}",
            )


class ApplicationBridge(LibraryBridge):
    """Single QML-facing facade; all persisted state and provider work stays in Python."""

    # Qt/PySide requires a NOTIFY signal declared on the class adding each property.
    # Preserve the base signal for base properties and forward it to this local one.
    applicationThemeChanged = Signal()

    pageChanged = Signal()
    backgroundChanged = Signal()
    homeChanged = Signal()
    recommendationsChanged = Signal()
    searchChanged = Signal()
    calendarChanged = Signal()
    favoritesChanged = Signal()
    selectedWorkChanged = Signal()
    episodesChanged = Signal()
    selectedProfileChanged = Signal()
    settingsChanged = Signal(str)
    navigationRequested = Signal(str)
    navigationBackRequested = Signal()
    addToLibraryRequested = Signal(object)
    searchWorkRequested = Signal(object)
    profileRequested = Signal(object)
    setupRequested = Signal()
    updateRequested = Signal()
    diagnosticsExportRequested = Signal()
    rollbackRequested = Signal()
    restartRequested = Signal()
    detailActionRequested = Signal(str, int)
    bundleEditRequested = Signal(int)
    bundleDeleteRequested = Signal(int)

    def __init__(self, parent=None, background_manager=None):
        self._raw_groups = []
        self._groups_loaded = False
        self._groups_loading = False
        self._startup_ready = False
        self._groups_refresh_requested = False
        self._groups_generation = 0
        self._groups_workers = {}
        self._current_page = "home"
        self._previous_content_page = "home"
        self._home_items = []
        self._home_stats = {"all": 0, "inProgress": 0, "completed": 0, "planned": 0}
        self._recommendation_snapshot = []
        self._recommendation_raw_items = []
        self._recommendation_items = []
        self._recommendation_rows = {}
        self._recommendation_candidate_ids = set()
        self._recommendation_has_next = True
        self._recommendation_next_page = 1
        self._recommendation_loading = False
        self._recommendation_error = ""
        self._recommendation_refresh_cycle = 0
        self._recommendation_worker = None
        self._recommendation_thread = None
        self._recommendation_stop_event = None
        self._recommendation_pending_refresh = False
        self._recommendation_shutting_down = False
        self._recommendation_history = {}
        self._recommendation_favorite_works = []
        self._recommendation_favorite_entities = []
        self._recommendation_credit_profile = {}
        self._recommendation_voice_language = "ALL"
        self._recommendation_impressed_ids = set()
        self._search_items = []
        self._search_rows = {}
        self._search_raw_items = []
        self._search_query = ""
        self._search_type = ""
        self._search_format = ""
        self._search_filters = {}
        self._search_page = 1
        self._search_has_next = False
        self._search_loading = False
        self._search_error = ""
        self._search_generation = 0
        self._search_workers = {}
        self._calendar_items = []
        self._release_reminder_count = 0
        self._favorites_items = []
        self._selected_work = {}
        self._selected_work_raw = {}
        self._episode_items = []
        self._detail_generation = 0
        self._detail_workers = {}
        self._selected_profile = {}
        self._profile_generation = 0
        self._profile_workers = {}
        self._background_manager = background_manager
        self._background_source = ""
        self._active_ui_scale = self._read_active_ui_scale()
        super().__init__(
            parent=parent,
            library_loader=lambda: self._raw_groups,
            auto_refresh=False,
        )
        self.themeChanged.connect(self.applicationThemeChanged.emit)
        if self._background_manager is not None:
            self._background_manager.background_changed.connect(self._background_changed)
            self._background_manager.images_changed.connect(self._background_changed)
        self.refreshTheme()
        self._background_changed()

    def _sync_theme_values(self):
        super()._sync_theme_values()
        self._theme_values["resizeAnimation"] = bool(get("resize_animation"))
        self._theme_values["animationSpeed"] = int(get("animation_speed"))
        self._theme_values["uiScale"] = max(80, min(200, int(get("ui_scale"))))

    @Property(bool, notify=applicationThemeChanged)
    def resizeAnimation(self):
        return self._theme_values["resizeAnimation"]

    @Property(int, notify=applicationThemeChanged)
    def animationSpeed(self):
        return self._theme_values["animationSpeed"]

    @Property(int, notify=applicationThemeChanged)
    def uiScale(self):
        return self._theme_values["uiScale"]

    @Property(int, constant=True)
    def activeUiScale(self):
        return self._active_ui_scale

    @staticmethod
    def _read_active_ui_scale():
        configured = int(get("ui_scale"))
        factor_text = os.environ.get("QT_SCALE_FACTOR")
        if factor_text is None:
            return configured
        try:
            active = int(round(float(factor_text) * 100))
        except (TypeError, ValueError, OverflowError):
            return configured
        return active if active in UI_SCALE_OPTIONS else configured

    # ---- Global shell and theme -------------------------------------------------

    @Property(str, notify=pageChanged)
    def currentPage(self):
        return self._current_page

    @Property(str, notify=backgroundChanged)
    def backgroundSource(self):
        return self._background_source

    @Property(str, notify=applicationThemeChanged)
    def backgroundColor(self):
        return COLORS.get("background", "#17131e")

    @Property(str, notify=applicationThemeChanged)
    def backgroundOverlayColor(self):
        if (
            self._background_manager is None
            or self._background_manager.display_pixmap is None
            or self._background_manager.display_pixmap.isNull()
        ):
            return "#00000000"
        color = QColor(COLORS.get("background", "#17131e"))
        color.setAlpha(round(255 * self._background_manager.overlay_opacity / 100))
        return color.name(QColor.NameFormat.HexArgb)

    @Property(str, notify=applicationThemeChanged)
    def sidebarFillColor(self):
        return surface_qml_color("sidebar")

    @Property(str, notify=applicationThemeChanged)
    def surfaceFillColor(self):
        return surface_qml_color("surface")

    @Property(str, notify=applicationThemeChanged)
    def surfaceAltFillColor(self):
        return surface_qml_color("surface_alt")

    @Property(str, notify=applicationThemeChanged)
    def borderColor(self):
        return COLORS.get("border", "#51475f")

    @Property(str, notify=applicationThemeChanged)
    def accentColor(self):
        return COLORS.get("accent", "#9271c5")

    @Property(str, notify=applicationThemeChanged)
    def successColor(self):
        return COLORS.get("success", "#55b881")

    @Property(str, notify=applicationThemeChanged)
    def dangerColor(self):
        return COLORS.get("danger", "#d85b70")

    @Property(str, notify=applicationThemeChanged)
    def themePreset(self):
        return str(get("theme_preset") or "Neko")

    @Property(bool, notify=applicationThemeChanged)
    def lightMode(self):
        return bool(get("light_mode"))

    @Property(int, notify=backgroundChanged)
    def backgroundOverlayOpacity(self):
        return int(self._background_manager.overlay_opacity) if self._background_manager else int(get("background_overlay_opacity"))

    @Property("QVariantList", notify=backgroundChanged)
    def backgroundPaths(self):
        return list(self._background_manager.paths) if self._background_manager else []

    @Property(str, notify=backgroundChanged)
    def backgroundSelectedPath(self):
        if self._background_manager is None:
            return ""
        return str(self._background_manager.selected_path or "")

    @Property(int, notify=backgroundChanged)
    def backgroundInterval(self):
        return int(self._background_manager.interval) if self._background_manager else int(get("background_slideshow_interval"))

    @Property("QVariantList", constant=True)
    def backgroundIntervals(self):
        return [-1, 0, 30, 60, 300, 900, 1800]

    @Property("QVariantList", constant=True)
    def themePresets(self):
        return list(THEME_PRESETS.keys())

    @Property(bool, notify=applicationThemeChanged)
    def autoCheckUpdates(self):
        return bool(get("auto_check_updates"))

    @Property(str, notify=applicationThemeChanged)
    def updateChannel(self):
        return str(get("update_channel") or "stable")

    @Property(bool, notify=applicationThemeChanged)
    def maximized(self):
        return bool(get("maximized"))

    @Property(str, notify=applicationThemeChanged)
    def tmdbApiToken(self):
        return str(get("tmdb_api_token") or "")

    @Property(str, notify=applicationThemeChanged)
    def recommendationVoiceLanguage(self):
        return str(get("recommendation_voice_language") or "ALL").upper()

    @Property("QVariantList", notify=applicationThemeChanged)
    def bundleOptionGroups(self):
        return [
            {
                "title": group_title,
                "options": [
                    {
                        "key": key,
                        "label": label,
                        "description": description,
                        "checked": bool(get(key)),
                    }
                    for key, label, description in options
                ],
            }
            for group_title, options in BUNDLE_OPTION_GROUPS
        ]

    def _background_changed(self, *_args):
        manager = self._background_manager
        raw_path = manager.selected_path if manager is not None and manager.display_pixmap is not None else None
        self._background_source = _file_source(raw_path)
        self.backgroundChanged.emit()

    @Slot(str)
    def initializePage(self, page):
        target = str(page or "home")
        if target not in {"home", "collections", "search", "calendar", "favorites", "settings",
                          "work_detail", "entity_profile", "relation"}:
            target = "home"
        self._current_page = target
        if target not in {"work_detail", "entity_profile", "relation"}:
            self._previous_content_page = target
        self.pageChanged.emit()

    @Slot(str)
    def setCurrentPage(self, page):
        target = str(page or "home")
        if target not in {"home", "collections", "search", "calendar", "favorites", "settings",
                          "work_detail", "entity_profile", "relation"}:
            return
        if target == self._current_page:
            return
        if target not in {"work_detail", "entity_profile", "relation"}:
            self._previous_content_page = target
        self._current_page = target
        self.pageChanged.emit()

    @Slot(str)
    def navigate(self, page):
        valid = {
            "home", "collections", "search", "calendar", "favorites",
            "settings", "work_detail", "entity_profile", "relation",
        }
        target = str(page or "")
        if target not in valid:
            return
        if target not in {"work_detail", "entity_profile", "relation"}:
            self._previous_content_page = target
        if target == self._current_page:
            if target == "collections":
                self.refreshAll()
            elif target == "home":
                self.refreshHome()
            elif target == "calendar":
                self.refreshCalendar()
            elif target == "favorites":
                self.refreshFavorites()
            return
        self._current_page = target
        self.pageChanged.emit()
        self.navigationRequested.emit(target)
        if target == "collections":
            # Home already preloads the canonical Library snapshot. On the
            # first switch, reuse that model instead of forcing a second full
            # database/grouping pass that only causes a visible loading flash.
            # Explicit refreshes and relation-sync completion still use
            # refreshAll()/forceRefreshAll().
            if not self._groups_loaded and not self._groups_loading:
                self._load_groups()
        elif target == "home":
            self.refreshHome()
        elif target == "calendar":
            self.refreshCalendar()
        elif target == "favorites":
            self.refreshFavorites()
        elif target == "settings":
            self.refreshTheme()

    @Slot()
    def goBack(self):
        target = self._previous_content_page
        if target in {"work_detail", "entity_profile", "relation"}:
            target = "home"
        self.navigate(target)

    @Slot()
    def requestSetup(self):
        self.setupRequested.emit()

    @Slot()
    def requestUpdateCheck(self):
        self.updateRequested.emit()

    @Slot()
    def requestDiagnosticsExport(self):
        self.diagnosticsExportRequested.emit()

    @Slot(str, "QVariant")
    def setPreference(self, key, value):
        allowed = {
            "theme_preset", "light_mode", "ui_scale", "maximized", "card_size", "card_gap",
            "corner_radius", "font_size", "hover_highlight",
            "resize_animation", "animation_speed", "background_overlay_opacity",
            "background_slideshow_interval", "auto_check_updates", "update_channel",
            "recommendation_voice_language", "tmdb_api_token", *BUNDLE_OPTION_KEYS,
        }
        key = str(key or "")
        if key not in allowed:
            return
        try:
            if key == "theme_preset":
                apply_theme_preset(str(value))
            elif key == "ui_scale":
                try:
                    parsed_scale = int(value)
                except (TypeError, ValueError, OverflowError):
                    return
                if parsed_scale not in UI_SCALE_OPTIONS:
                    return
                set_value(key, parsed_scale)
            elif key == "update_channel":
                parsed_channel = str(value or "").strip().casefold()
                if parsed_channel not in {"stable", "preview"}:
                    return
                set_value(key, parsed_channel)
            elif key == "recommendation_voice_language":
                parsed_language = str(value or "ALL").strip().upper()
                if parsed_language not in {"JA", "EN", "ALL"}:
                    return
                set_value(key, parsed_language)
            elif key == "tmdb_api_token":
                set_value(key, str(value or "").strip())
            elif key == "maximized" or key == "auto_check_updates":
                set_value(key, bool(value))
            elif key in BUNDLE_OPTION_KEYS:
                set_value(key, bool(value))
                set_value(
                    "bundle_mode",
                    "extras" if all(bool(get(option_key)) for option_key in BUNDLE_OPTION_KEYS) else "main",
                )
            elif key == "background_overlay_opacity" and self._background_manager is not None:
                self._background_manager.set_overlay_opacity(value)
            elif key == "background_slideshow_interval" and self._background_manager is not None:
                self._background_manager.set_interval(value)
            else:
                set_value(key, value)
            refresh_theme()
            self.refreshTheme()
            self._background_changed()
            self.settingsChanged.emit(key)
            if key in BUNDLE_OPTION_KEYS:
                self.forceRefreshAll()
            elif key == "recommendation_voice_language":
                self.refreshRecommendations()
            log_event("qml_bridge.preference_changed", preference=key)
        except Exception as error:
            log_exception("qml_bridge.preference_change_failed", error, preference=key)

    @Slot()
    def chooseBackgroundImages(self):
        if self._background_manager is None:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            None,
            "Choose NekoTrack background images",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if paths:
            self._background_manager.add_images(paths)
            self._background_changed()

    @Slot(str)
    def removeBackgroundImage(self, path):
        if self._background_manager is None:
            return
        self._background_manager.remove_image(str(path or ""))
        self._background_changed()

    @Slot(str)
    def selectBackgroundImage(self, path):
        if self._background_manager is None:
            return
        self._background_manager.select_image(str(path or ""))
        self._background_changed()

    @Slot()
    def requestRollback(self):
        self.rollbackRequested.emit()

    @Slot()
    def requestRestart(self):
        self.restartRequested.emit()

    @Slot()
    def resetPreferences(self):
        try:
            reset()
            for key, value in defaults().items():
                set_value(key, value)
            if self._background_manager is not None:
                self._background_manager.reload_preferences()
            refresh_theme()
            self.refreshTheme()
            self._background_changed()
            self.forceRefreshAll()
            self.refreshRecommendations()
            self.settingsChanged.emit("reset")
            log_event("qml_bridge.preferences_reset")
        except Exception as error:
            log_exception("qml_bridge.preferences_reset_failed", error)

    # ---- Library, Home and page refresh ----------------------------------------

    def _load_groups(self, force=False):
        if self._recommendation_shutting_down:
            return
        if self._groups_loading:
            self._groups_refresh_requested = self._groups_refresh_requested or bool(force)
            return
        if self._groups_loaded and not force:
            self._library_model.refresh(self._raw_groups)
            self._refresh_home_items()
            return

        self._groups_generation += 1
        generation = self._groups_generation
        self._groups_loading = True
        self._library_loading = True
        self.loadingChanged.emit()
        self.homeChanged.emit()
        worker = _LibrarySnapshotWorker(generation)
        worker.signals.finished.connect(self._library_snapshot_ready)
        self._groups_workers[generation] = worker
        QThreadPool.globalInstance().start(worker)

    @Slot(int, object, object)
    def _library_snapshot_ready(self, generation, rows, error):
        self._groups_workers.pop(generation, None)
        if generation != self._groups_generation or self._recommendation_shutting_down:
            return
        self._groups_loading = False
        if error:
            self._groups_refresh_requested = False
            self._library_loading = False
            self.loadingChanged.emit()
            self._groups_loaded = False
            log_exception(
                "qml_bridge.library_snapshot_failed",
                RuntimeError(str(error)),
            )
            self.errorOccurred.emit("NekoTrack could not load the Library. Check the diagnostic log.")
            self.homeChanged.emit()
            return
        if self._groups_refresh_requested:
            self._groups_refresh_requested = False
            # Do not flash the loading state off while replacing a stale snapshot.
            QTimer.singleShot(0, lambda: self._load_groups(force=True))
            return

        self._library_loading = False
        self.loadingChanged.emit()
        self._groups_loaded = True
        self._raw_groups = [
            _plain(group)
            for group in (rows or [])
            if isinstance(group, dict) or hasattr(group, "keys")
        ]
        self._library_model.refresh(self._raw_groups)
        self._refresh_home_items()

        if self._current_page == "home" and self._startup_ready:
            self.refreshRecommendations()

    @Slot()
    def refreshAll(self):
        self._load_groups(force=self._groups_loaded)

    @Slot()
    def forceRefreshAll(self):
        self._load_groups(force=True)

    @Slot()
    def markStartupReady(self):
        self._startup_ready = True
        self.refreshHome()

    @Slot()
    def refreshHome(self):
        # The Home release preview is sourced from locally cached dates only.
        self.refreshCalendar()
        if not self._groups_loaded:
            self._load_groups()
            return
        self._library_model.refresh(self._raw_groups)
        self._refresh_home_items()
        # A screen revisit must not cancel an in-flight recommendations request.
        if (
            self._startup_ready
            and self._current_page == "home"
            and self._recommendation_thread is None
        ):
            self.refreshRecommendations()

    @staticmethod
    def _home_progress_caption(row, home_status):
        def nonnegative(value):
            return max(0, _optional_int(value) or 0)

        media_type = str(row.get("mediaType") or "").strip().upper()
        status = str(home_status or "").strip().casefold()
        if media_type == "ANIME" or status in {"watching", "rewatching"}:
            progress = nonnegative(row.get("progressEpisodes"))
            total = nonnegative(row.get("episodeTotal"))
            if total:
                if progress >= total:
                    return f"Episode progress: {progress}/{total}"
                return f"Next episode {progress + 1} · {progress}/{total} logged"
            return f"Next episode {progress + 1} · total unknown"

        chapter_progress = nonnegative(row.get("progressChapters"))
        chapter_total = nonnegative(row.get("chapterTotal"))
        volume_progress = nonnegative(row.get("progressVolumes"))
        volume_total = nonnegative(row.get("volumeTotal"))
        details = []
        if chapter_total or chapter_progress:
            details.append(
                f"{chapter_progress}/{chapter_total} chapters"
                if chapter_total else f"{chapter_progress} chapters logged"
            )
        if volume_total or volume_progress:
            details.append(
                f"{volume_progress}/{volume_total} volumes"
                if volume_total else f"{volume_progress} volumes logged"
            )
        if not details:
            return "No chapter or volume progress recorded yet"
        next_item = (
            f"Next chapter {chapter_progress + 1}"
            if chapter_total or chapter_progress
            else f"Next volume {volume_progress + 1}"
        )
        return f"{next_item} · " + " · ".join(details)

    def _refresh_home_items(self):
        all_rows = list(self._library_model._all_rows)
        raw_members = []
        raw_by_id = {}
        for source_group in self._raw_groups:
            if not isinstance(source_group, dict):
                continue
            group_id = _optional_int(source_group.get("id"))
            if group_id is not None:
                raw_by_id[group_id] = source_group
            group_members = source_group.get("_series_members")
            if not isinstance(group_members, list) or not group_members:
                group_members = [source_group]
            raw_members.extend(member for member in group_members if isinstance(member, dict))

        raw_statuses = [
            str(member.get("status") or "").strip().casefold()
            for member in raw_members
        ]
        ongoing = {"watching", "rewatching", "reading", "in progress"}
        planned = {"planning", "plan to watch", "plan to read"}
        completed = {"completed"}
        self._home_stats = {
            "all": len(raw_members) if raw_members else len(all_rows),
            "inProgress": sum(status in ongoing for status in raw_statuses) if raw_statuses else
                sum(str(row.get("status") or "").strip().casefold() in ongoing for row in all_rows),
            "completed": sum(status in completed for status in raw_statuses) if raw_statuses else
                sum(str(row.get("status") or "").strip().casefold() in completed for row in all_rows),
            "planned": sum(status in planned for status in raw_statuses) if raw_statuses else
                sum(str(row.get("status") or "").strip().casefold() in planned for row in all_rows),
        }

        home_items = []
        for row in all_rows:
            work_id = _optional_int(row.get("workId"))
            raw_group = raw_by_id.get(work_id) or {}
            group_members = raw_group.get("_series_members")
            if not isinstance(group_members, list) or not group_members:
                group_members = [raw_group] if raw_group else []
            member_statuses = [
                str(member.get("status") or "").strip().casefold()
                for member in group_members if isinstance(member, dict)
            ]
            current_status = str(row.get("status") or "").strip().casefold()
            eligible = any(status in ongoing for status in member_statuses) or current_status in ongoing
            if not eligible:
                continue

            if any(status in {"watching", "rewatching"} for status in member_statuses):
                home_status = "rewatching" if "rewatching" in member_statuses else "watching"
            elif "reading" in member_statuses:
                home_status = "reading"
            elif "in progress" in member_statuses:
                home_status = "in progress"
            else:
                home_status = current_status

            item = dict(row)
            item["homeStatus"] = home_status or current_status
            item["progressCaption"] = self._home_progress_caption(item, item["homeStatus"])
            home_items.append(item)

        self._home_items = home_items
        self.homeChanged.emit()

    @Property("QVariantList", notify=homeChanged)
    def homeItems(self):
        return list(self._home_items)

    @Property(bool, notify=homeChanged)
    def homeLoading(self):
        return self._groups_loading and not self._groups_loaded

    @Property("QVariantMap", notify=homeChanged)
    def homeStats(self):
        return dict(self._home_stats)

    @Property("QVariantList", notify=recommendationsChanged)
    def recommendationItems(self):
        return list(self._recommendation_items)

    @Property(bool, notify=recommendationsChanged)
    def recommendationLoading(self):
        return self._recommendation_loading

    @Property(bool, notify=recommendationsChanged)
    def recommendationHasNext(self):
        return self._recommendation_has_next

    @Property(str, notify=recommendationsChanged)
    def recommendationError(self):
        return self._recommendation_error

    # ---- Personalized recommendations ------------------------------------------

    @Slot()
    def refreshRecommendations(self):
        if self._recommendation_shutting_down:
            return
        if self._recommendation_thread is not None:
            self._recommendation_pending_refresh = True
            if self._recommendation_stop_event is not None:
                self._recommendation_stop_event.set()
            return
        try:
            rows = [
                _plain(dict(row))
                for row in (get_all_library() or [])
                if isinstance(row, dict) or hasattr(row, "keys")
            ]
        except Exception as error:
            log_exception("qml_bridge.recommendations_library_read_failed", error)
            self._recommendation_error = "Your Library could not be read for recommendations."
            self._recommendation_loading = False
            self.recommendationsChanged.emit()
            return

        self._recommendation_snapshot = rows
        self._recommendation_refresh_cycle += 1
        self._recommendation_raw_items = []
        self._recommendation_items = []
        self._recommendation_rows = {}
        self._recommendation_candidate_ids = set()
        self._recommendation_next_page = 1
        self._recommendation_has_next = True
        self._recommendation_error = ""
        self._recommendation_loading = True
        self._recommendation_impressed_ids.clear()
        self.recommendationsChanged.emit()
        self._start_recommendation_worker(fetch_seeds=True)

    @Slot()
    def loadMoreRecommendations(self):
        if (
            self._recommendation_shutting_down
            or self._recommendation_loading
            or not self._recommendation_has_next
            or self._recommendation_thread is not None
        ):
            return
        self._recommendation_loading = True
        self._recommendation_error = ""
        self.recommendationsChanged.emit()
        self._start_recommendation_worker(fetch_seeds=False)

    def _start_recommendation_worker(self, fetch_seeds):
        self._recommendation_stop_event = threading.Event()
        worker = RecommendationWorker(
            self._recommendation_snapshot,
            self._recommendation_stop_event,
            catalog_page=self._recommendation_next_page,
            existing_ids=self._recommendation_candidate_ids,
            refresh_cycle=self._recommendation_refresh_cycle,
            fetch_seeds=fetch_seeds,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._recommendations_ready)
        worker.failed.connect(self._recommendations_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda current=thread: self._recommendation_thread_finished(current))
        thread.finished.connect(thread.deleteLater)
        self._recommendation_worker = worker
        self._recommendation_thread = thread
        thread.start()

    @staticmethod
    def _recommendation_result_identity_ids(work):
        """Include every bundle member so pages cannot recommend duplicate entries."""
        ids = set()
        if not isinstance(work, dict):
            return ids
        work_id = _optional_int(work.get("id"))
        if work_id is not None and work_id > 0:
            ids.add(work_id)
        members = work.get("_series_members")
        if isinstance(members, list):
            for member in members:
                if not isinstance(member, dict):
                    continue
                member_id = _optional_int(member.get("id"))
                if member_id is not None and member_id > 0:
                    ids.add(member_id)
        return ids

    @classmethod
    def _recommendation_identity_ids(cls, items):
        ids = set()
        for item in items or []:
            ids.update(cls._recommendation_result_identity_ids(item))
        return ids

    @Slot(object)
    def _recommendations_ready(self, results):
        worker = self._recommendation_worker
        if worker is None or self._recommendation_shutting_down:
            return
        if self._recommendation_stop_event is not None and self._recommendation_stop_event.is_set():
            return

        incoming = [dict(item) for item in (results or []) if isinstance(item, dict)]
        catalog_only = bool(worker.catalog_only)
        self._recommendation_next_page = max(1, int(worker.catalog_next_page or 1))
        self._recommendation_has_next = bool(worker.catalog_has_next)
        self._recommendation_history = dict(worker.history or {})
        self._recommendation_favorite_works = list(worker.favorite_works or [])
        self._recommendation_favorite_entities = list(worker.favorite_entities or [])
        self._recommendation_credit_profile = dict(worker.credit_profile or {})
        self._recommendation_voice_language = str(worker.voice_language or "ALL")

        ranking_options = {
            "history": self._recommendation_history,
            "favorite_works": self._recommendation_favorite_works,
            "rotation": self._recommendation_refresh_cycle,
            "credit_profile": self._recommendation_credit_profile,
            "favorite_entities": self._recommendation_favorite_entities,
            "voice_language": self._recommendation_voice_language,
        }
        if catalog_only:
            existing_ids = self._recommendation_identity_ids(self._recommendation_raw_items)
            new_batch = []
            for item in incoming:
                identity_ids = self._recommendation_result_identity_ids(item)
                if identity_ids.intersection(existing_ids):
                    continue
                new_batch.append(item)
                existing_ids.update(identity_ids)
            ranked_new = rank_candidates(new_batch, **ranking_options)
            ranked_new = inject_rare_exploration(
                ranked_new,
                rotation=self._recommendation_refresh_cycle,
                fraction=0.04,
            )
            self._recommendation_raw_items.extend(ranked_new)
        else:
            ranked = rank_candidates(incoming, **ranking_options)
            self._recommendation_raw_items = inject_rare_exploration(
                ranked,
                rotation=self._recommendation_refresh_cycle,
                fraction=0.04,
            )

        self._recommendation_candidate_ids = self._recommendation_identity_ids(
            self._recommendation_raw_items
        )
        self._recommendation_loading = False
        self._recommendation_error = ""
        self._map_recommendation_items()
        self.recommendationsChanged.emit()

    @Slot(str)
    def _recommendations_failed(self, message):
        if self._recommendation_shutting_down:
            return
        if self._recommendation_stop_event is not None and self._recommendation_stop_event.is_set():
            return
        worker = self._recommendation_worker
        self._recommendation_loading = False
        if worker is not None and worker.catalog_only and self._recommendation_raw_items:
            self._recommendation_error = (
                "More titles could not be loaded. Your current recommendations are still available."
            )
        else:
            self._recommendation_error = str(message or "Recommendations could not be loaded.")
            self._recommendation_has_next = False
        self.recommendationsChanged.emit()

    def _map_recommendation_items(self):
        rows = []
        by_id = {}
        for raw_value in self._recommendation_raw_items:
            raw = _plain(raw_value) if isinstance(raw_value, dict) else {}
            normalized = _normalize_group(raw)
            if normalized is None:
                continue
            work_id = int(normalized["workId"])
            item = dict(normalized)
            item["id"] = work_id
            item["fullTitle"] = str(normalized.get("fullTitle") or normalized.get("title") or "Untitled")
            item["coverSource"] = normalized.get("coverSource") or _image_source(raw)
            item["isInLibrary"] = is_work_in_library(work_id)
            item["recommendationReason"] = str(
                raw.get("_recommendation_reason") or "Discovered from AniList"
            )
            rows.append(item)
            by_id[work_id] = raw
        self._recommendation_items = rows
        self._recommendation_rows = by_id

    @Slot(int, str, str, str, str)
    def requestOpenRelatedWork(self, work_id, title, media_type="", media_format="", cover_source=""):
        target_id = _optional_int(work_id)
        if target_id is None or target_id == 0:
            return
        group = self._group_for_id(target_id)
        if group is not None:
            self.openWorkRequested.emit(target_id)
            return
        raw = {
            "id": target_id,
            "title": {"romaji": str(title or f"Untitled · {target_id}")},
            "type": str(media_type or "UNKNOWN"),
            "format": str(media_format or ""),
        }
        source = str(cover_source or "")
        if source.startswith(("https://", "http://")):
            raw["cover_url"] = source
        elif source.startswith("file:"):
            raw["cover_path"] = QUrl(source).toLocalFile()
        self.searchWorkRequested.emit(raw)

    @Slot(int)
    def requestOpenRecommendation(self, work_id):
        raw = self._recommendation_rows.get(_optional_int(work_id))
        if raw is not None:
            self.searchWorkRequested.emit(raw)

    @Slot(int)
    def requestAddRecommendation(self, work_id):
        raw = self._recommendation_rows.get(_optional_int(work_id))
        if raw is not None:
            self.addToLibraryRequested.emit(raw)

    @Slot(int, str)
    def requestRecommendationFeedback(self, work_id, feedback):
        raw = self._recommendation_rows.get(_optional_int(work_id))
        if raw is None or feedback not in {"more_like_this", "less_like_this", "never_show"}:
            return
        if not set_recommendation_feedback(work_id, feedback, raw):
            self._recommendation_error = "Your recommendation feedback couldn't be saved."
            self.recommendationsChanged.emit()
            return
        try:
            history = get_recommendation_history()
            self._recommendation_history = history if isinstance(history, dict) else {}
            ranking_options = {
                "history": self._recommendation_history,
                "favorite_works": self._recommendation_favorite_works,
                "rotation": self._recommendation_refresh_cycle,
                "credit_profile": self._recommendation_credit_profile,
                "favorite_entities": self._recommendation_favorite_entities,
                "voice_language": self._recommendation_voice_language,
            }
            self._recommendation_raw_items = rank_candidates(
                self._recommendation_raw_items, **ranking_options
            )
            self._recommendation_raw_items = inject_rare_exploration(
                self._recommendation_raw_items,
                rotation=self._recommendation_refresh_cycle,
                fraction=0.04,
            )
            self._recommendation_candidate_ids = self._recommendation_identity_ids(
                self._recommendation_raw_items
            )
            self._recommendation_error = ""
            self._map_recommendation_items()
            self.recommendationsChanged.emit()
        except Exception as error:
            log_exception(
                "qml_bridge.recommendation_feedback_failed",
                error,
                work_id=work_id,
                feedback=feedback,
            )

    @Slot(int)
    def recordRecommendationImpression(self, work_id):
        normalized_id = _optional_int(work_id)
        if (
            normalized_id is None
            or normalized_id in self._recommendation_impressed_ids
            or normalized_id not in self._recommendation_rows
        ):
            return
        raw = self._recommendation_rows[normalized_id]
        try:
            if record_recommendation_impressions([raw]):
                self._recommendation_impressed_ids.add(normalized_id)
        except Exception as error:
            log_exception(
                "qml_bridge.recommendation_impression_failed",
                error,
                work_id=normalized_id,
            )

    @Slot()
    def requestShutdown(self):
        self._recommendation_shutting_down = True
        self._recommendation_pending_refresh = False
        if self._recommendation_stop_event is not None:
            self._recommendation_stop_event.set()
        if self._recommendation_thread is not None:
            try:
                self._recommendation_thread.quit()
            except RuntimeError:
                pass

    def _recommendation_thread_finished(self, thread):
        if thread is not self._recommendation_thread:
            return
        self._recommendation_thread = None
        self._recommendation_worker = None
        self._recommendation_stop_event = None
        pending = self._recommendation_pending_refresh
        self._recommendation_pending_refresh = False
        if pending and not self._recommendation_shutting_down:
            QTimer.singleShot(0, self.refreshRecommendations)

    @Slot(int, result=bool)
    def requestOpenWork(self, work_id):
        normalized = _optional_int(work_id)
        if normalized is None or normalized == 0:
            return False
        group = self._group_for_id(normalized)
        if group is None:
            return False
        self.openWorkRequested.emit(normalized)
        return True

    def _group_for_id(self, work_id):
        for group in self._raw_groups:
            if _optional_int(group.get("id")) == work_id:
                return group
        for group in self._raw_groups:
            for member in group.get("_series_members") or []:
                if _optional_int(member.get("id")) == work_id:
                    return group
        return None

    @Slot(int)
    def requestEditBundle(self, work_id):
        normalized = _optional_int(work_id)
        if normalized is not None and normalized != 0:
            self.editBundleRequested.emit(normalized)

    @Slot(int)
    def requestDeleteWork(self, work_id):
        normalized = _optional_int(work_id)
        if normalized is not None and normalized != 0:
            self.deleteWorkRequested.emit(normalized)

    @Slot(str)
    def requestDetailAction(self, action):
        allowed = {
            "auto_bundle",
            "add_to_bundle",
            "remove_from_bundle",
            "customize_identity",
        }
        normalized_action = str(action or "").strip().casefold()
        work_id = _optional_int(self._selected_work.get("id"))
        if normalized_action in allowed and work_id not in (None, 0):
            self.detailActionRequested.emit(normalized_action, work_id)

    # ---- Search ----------------------------------------------------------------

    @Property("QVariantList", notify=searchChanged)
    def searchItems(self):
        return list(self._search_items)

    @Property(bool, notify=searchChanged)
    def searchLoading(self):
        return self._search_loading

    @Property(bool, notify=searchChanged)
    def searchHasNext(self):
        return self._search_has_next

    @Property(str, notify=searchChanged)
    def searchError(self):
        return self._search_error

    @Property(str, notify=searchChanged)
    def searchQuery(self):
        return self._search_query

    @Property("QVariantMap", notify=searchChanged)
    def searchFilters(self):
        return dict(self._search_filters)

    @Slot(str, str, str)
    def searchCatalog(self, query, media_type="", media_format=""):
        self.searchCatalogWithFilters(query, media_type, media_format, {})

    @Slot(str, str, str, "QVariantMap")
    def searchCatalogWithFilters(self, query, media_type="", media_format="", filters=None):
        self._search_query = str(query or "").strip()
        self._search_type = str(media_type or "")
        self._search_format = str(media_format or "")
        self._search_filters = dict(filters or {})
        self._search_page = 1
        self._search_raw_items = []
        self._search_rows = {}
        self._search_items = []
        self._search_error = ""
        self._search_has_next = False
        self._search_generation += 1
        self._start_catalog_page(self._search_generation, 1)
        self.searchChanged.emit()

    @Slot()
    def loadMoreSearchResults(self):
        if self._search_loading or not self._search_has_next:
            return
        self._search_page += 1
        self._start_catalog_page(self._search_generation, self._search_page)

    def _start_catalog_page(self, generation, page):
        self._search_loading = True
        self._search_error = ""
        self.searchChanged.emit()
        worker = _SearchWorker(
            generation,
            page,
            self._search_query,
            self._search_type,
            self._search_format,
            self._search_filters,
        )
        worker.signals.finished.connect(self._catalog_page_finished)
        self._search_workers[(generation, page)] = worker
        QThreadPool.globalInstance().start(worker)

    @Slot(int, int, object, object)
    def _catalog_page_finished(self, generation, page, result, error):
        self._search_workers.pop((generation, page), None)
        if generation != self._search_generation:
            return
        self._search_loading = False
        if error:
            self._search_error = str(error)
            self._search_has_next = False
            self.searchChanged.emit()
            return
        data = result if isinstance(result, dict) else {}
        incoming = data.get("media") or []
        self._search_raw_items.extend(
            _plain(item) for item in incoming if isinstance(item, dict)
        )
        if bool(self._search_filters.get("fast_search")):
            grouped = list(self._search_raw_items)
        else:
            try:
                grouped = group_media_results(self._search_raw_items, enrich=False)
            except Exception as group_error:
                log_exception("qml_bridge.search_grouping_failed", group_error)
                grouped = list(self._search_raw_items)

        self._search_rows = {}
        mapped = []
        for group in grouped:
            raw = _plain(group)
            normalized = _normalize_group(raw)
            if normalized is None:
                continue
            work_id = int(normalized["workId"])
            self._search_rows[work_id] = raw
            item = dict(normalized)
            item["id"] = work_id
            item["fullTitle"] = str(normalized.get("fullTitle") or normalized.get("title") or "")
            item["coverSource"] = normalized.get("coverSource") or _image_source(raw)
            item["isInLibrary"] = is_work_in_library(work_id)
            item["synopsis"] = str(raw.get("description") or raw.get("synopsis") or "")
            mapped.append(item)
        self._search_items = mapped
        page_info = data.get("pageInfo") if isinstance(data.get("pageInfo"), dict) else {}
        self._search_has_next = bool(page_info.get("hasNextPage"))
        self._search_error = " · ".join(str(item) for item in data.get("_warnings") or [])
        log_event("qml_bridge.search_page_ready", page=page, count=len(mapped))
        self.searchChanged.emit()

    @Slot(int)
    def requestOpenSearchWork(self, work_id):
        work = self._search_rows.get(_optional_int(work_id))
        if work is not None:
            self.searchWorkRequested.emit(work)

    @Slot(int)
    def requestAddSearchWork(self, work_id):
        work = self._search_rows.get(_optional_int(work_id))
        if work is not None:
            self.addToLibraryRequested.emit(work)

    @Slot()
    def requestAddSelectedWork(self):
        if self._selected_work_raw:
            self.addToLibraryRequested.emit(self._selected_work_raw)

    # ---- Calendar and reminders -------------------------------------------------

    @Property("QVariantList", notify=calendarChanged)
    def calendarItems(self):
        return list(self._calendar_items)

    @Property(int, notify=calendarChanged)
    def releaseReminderCount(self):
        return int(self._release_reminder_count)

    @Slot()
    def refreshCalendar(self):
        today = datetime.date.today()
        last_day = today + datetime.timedelta(days=60)
        try:
            rows = get_upcoming_library_episodes(
                today.isoformat(),
                (last_day + datetime.timedelta(days=1)).isoformat(),
            )
            try:
                self._release_reminder_count = len(get_release_reminders() or [])
            except Exception as reminder_error:
                self._release_reminder_count = 0
                log_exception("qml_bridge.calendar_reminder_count_failed", reminder_error)
            items = []
            for source in rows or []:
                row = _plain(dict(source))
                work_id = _optional_int(row.get("work_id"))
                episode = _optional_int(row.get("episode_number"))
                air_date = str(row.get("air_date") or "")[:10]
                if work_id is None or episode is None or not air_date:
                    continue
                try:
                    parsed = datetime.date.fromisoformat(air_date)
                except ValueError:
                    continue
                cover = _file_source(row.get("work_cover_path")) or _image_source({
                    "cover_url": row.get("work_cover_url")
                })
                items.append({
                    "workId": work_id,
                    "episodeNumber": episode,
                    "workTitle": str(row.get("work_title") or f"Untitled · {work_id}"),
                    "episodeTitle": str(row.get("title") or ""),
                    "airDate": parsed.isoformat(),
                    "month": parsed.strftime("%b").upper(),
                    "day": str(parsed.day),
                    "dateLabel": parsed.strftime("%A, %B %d, %Y"),
                    "reminderEnabled": bool(row.get("reminder_enabled")),
                    "coverSource": cover,
                })
            items.sort(key=lambda item: (
                item["airDate"],
                str(item["workTitle"] or "").casefold(),
                item["episodeNumber"],
            ))
            items.sort(key=lambda item: (
                item["airDate"],
                str(item["workTitle"] or "").casefold(),
                item["episodeNumber"],
            ))
            self._calendar_items = items
        except Exception as error:
            log_exception("qml_bridge.calendar_load_failed", error)
            self._calendar_items = []
        self.calendarChanged.emit()

    @Slot(int, int, bool)
    def setReminder(self, work_id, episode_number, enabled):
        try:
            set_release_reminder(work_id, episode_number, enabled)
            self.refreshCalendar()
        except Exception as error:
            log_exception("qml_bridge.reminder_save_failed", error, work_id=work_id, episode_number=episode_number)

    # ---- Favorites and profiles -------------------------------------------------

    @Property("QVariantList", notify=favoritesChanged)
    def favoritesItems(self):
        return list(self._favorites_items)

    @Slot()
    def refreshFavorites(self):
        try:
            rows = get_entity_favorites() or []
            self._favorites_items = []
            for row in rows:
                item = _plain(dict(row))
                kind = str(item.get("entity_type") or "").casefold()
                entity_id = _optional_int(item.get("entity_id"))
                if kind not in {"character", "voice_actor", "staff"} or entity_id is None or entity_id <= 0:
                    continue
                item["entity_type"] = kind
                item["entity_id"] = entity_id
                item["entity_name"] = str(item.get("entity_name") or "").strip()
                item["imageSource"] = _image_source(item)
                item["languageLabel"] = str(item.get("language") or "").replace("_", " ").replace("-", " ").title()
                item["kindLabel"] = {
                    "character": "Character",
                    "voice_actor": "Voice actor",
                    "staff": "Production staff",
                }[kind]
                self._favorites_items.append(item)
        except Exception as error:
            log_exception("qml_bridge.favorites_load_failed", error)
            self._favorites_items = []
        self.favoritesChanged.emit()

    @Slot(str, int, bool)
    def removeFavorite(self, entity_type, entity_id, favorite):
        try:
            set_entity_favorite(entity_type, entity_id, favorite)
        except Exception as error:
            log_exception("qml_bridge.favorite_change_failed", error, entity_type=entity_type, entity_id=entity_id)
        self.refreshFavorites()

    @Slot(str, int, str)
    def requestOpenProfile(self, entity_type, entity_id, name):
        kind = str(entity_type or "").casefold()
        numeric_id = _optional_int(entity_id)
        if kind not in {"character", "voice_actor", "staff"} or numeric_id is None or numeric_id <= 0:
            return
        profile = {
            "id": numeric_id,
            "entity_type": kind,
            "name": str(name or "").strip() or f"{kind.title()} {numeric_id}",
        }
        # MainWindow starts the single profile-loading worker for this route.
        self.profileRequested.emit(profile)

    @Property("QVariantMap", notify=selectedProfileChanged)
    def selectedProfile(self):
        return dict(self._selected_profile)

    def _decorate_selected_profile(self):
        profile = self._selected_profile
        if not isinstance(profile, dict):
            return
        kind = str(profile.get("entity_type") or "").casefold()
        entity_id = _optional_int(profile.get("id"))
        name_value = profile.get("name") or profile.get("entity_name") or profile.get("character_name")
        if isinstance(name_value, dict):
            display_name = str(
                name_value.get("full")
                or name_value.get("english")
                or name_value.get("romaji")
                or name_value.get("native")
                or name_value.get("alternative")
                or "Unknown profile"
            ).strip()
        else:
            display_name = str(name_value or "Unknown profile").strip()
        profile["displayName"] = display_name or "Unknown profile"

        profile["imageSource"] = (
            _image_source(profile)
            or _image_source({
                "image_path": profile.get("image_path") or profile.get("character_image_path"),
                "image_url": profile.get("image_url") or profile.get("character_image_url"),
            })
        )

        if kind in {"character", "staff", "voice_actor"} and entity_id is not None and entity_id > 0:
            try:
                profile["isFavorite"] = bool(is_entity_favorite(kind, entity_id))
            except Exception as error:
                log_exception(
                    "qml_bridge.profile_favorite_read_failed",
                    error,
                    entity_type=kind,
                    entity_id=entity_id,
                )
                profile["isFavorite"] = False
        else:
            profile["isFavorite"] = False

        facts = []
        def add_fact(label, value):
            if isinstance(value, (list, tuple)):
                value = " · ".join(str(item).strip() for item in value if str(item or "").strip())
            value = str(value or "").strip()
            if value and value.casefold() not in {"none", "unknown", "n/a"}:
                facts.append({"label": str(label), "value": value})

        local_role = profile.get("character_role") or profile.get("role")
        if kind == "character":
            add_fact("Role in this bundle", str(local_role or "").replace("_", " ").title())
        else:
            add_fact("Occupation", profile.get("primaryOccupations"))
            if not profile.get("primaryOccupations"):
                add_fact("Credits in this bundle", str(local_role or "").replace("\n", " · "))
            add_fact("Language", profile.get("languageV2") or profile.get("language"))

        for label, key in (
            ("Gender", "gender"),
            ("Age", "age"),
            ("Blood type", "bloodType"),
            ("Hometown", "homeTown"),
        ):
            add_fact(label, profile.get(key))

        for label, key in (("Born", "dateOfBirth"), ("Died", "dateOfDeath")):
            date_value = profile.get(key)
            if isinstance(date_value, dict):
                date_parts = [
                    str(date_value.get(part))
                    for part in ("year", "month", "day")
                    if date_value.get(part) not in (None, 0, "")
                ]
                add_fact(label, "-".join(date_parts))

        years_active = profile.get("yearsActive")
        if isinstance(years_active, list):
            add_fact("Years active", years_active)
        favourites_count = _optional_int(profile.get("favourites"))
        if favourites_count and favourites_count > 0:
            add_fact("Favourites", f"{favourites_count:,}")
        profile["factItems"] = facts

        work_items = []
        work_index = {}
        connections = []
        if kind == "character":
            connections.append(("Appears in", profile.get("media"), "characterRole"))
        else:
            connections.extend([
                ("Staff credits", profile.get("staffMedia"), "staffRole"),
                ("Character roles", profile.get("characterMedia"), "characterRole"),
            ])

        for section_title, connection, role_key in connections:
            edges = connection.get("edges") if isinstance(connection, dict) else None
            for edge in edges if isinstance(edges, list) else []:
                if not isinstance(edge, dict):
                    continue
                node = edge.get("node")
                if not isinstance(node, dict):
                    continue
                work_id = _optional_int(node.get("id"))
                if work_id is None or work_id <= 0:
                    continue
                title_value = node.get("title") if isinstance(node.get("title"), dict) else {}
                work_title = str(
                    title_value.get("english")
                    or title_value.get("romaji")
                    or title_value.get("native")
                    or f"Untitled · {work_id}"
                ).strip()
                start_date = node.get("startDate") if isinstance(node.get("startDate"), dict) else {}
                role_text = str(edge.get(role_key) or edge.get("role") or "").replace("\n", " · ").strip()
                character_names = []
                for character in edge.get("characters") or []:
                    if not isinstance(character, dict):
                        continue
                    char_name = character.get("name")
                    if isinstance(char_name, dict):
                        char_name = char_name.get("full") or char_name.get("native")
                    char_name = str(char_name or "").strip()
                    if char_name and char_name not in character_names:
                        character_names.append(char_name)

                key = (work_id, section_title)
                item = work_index.get(key)
                if item is None:
                    item = {
                        "id": work_id,
                        "title": work_title,
                        "mediaType": str(node.get("type") or "UNKNOWN").upper(),
                        "format": str(node.get("format") or "").upper(),
                        "startYear": _optional_int(start_date.get("year")) or 0,
                        "coverSource": _image_source(node),
                        "section": section_title,
                        "role": role_text,
                        "characters": character_names,
                    }
                    work_index[key] = item
                    work_items.append(item)
                else:
                    if role_text and role_text not in str(item.get("role") or "").split(" · "):
                        item["role"] = " · ".join(filter(None, [item.get("role"), role_text]))
                    item["characters"] = list(dict.fromkeys(item.get("characters", []) + character_names))
        profile["workItems"] = work_items[:36]

    @Slot(object)
    def setSelectedProfile(self, profile):
        if not isinstance(profile, dict):
            return
        self._selected_profile = _plain(profile)
        self._selected_profile["profileLoading"] = True
        self._selected_profile["profileError"] = ""
        self._decorate_selected_profile()
        self.selectedProfileChanged.emit()
        kind = str(self._selected_profile.get("entity_type") or "").casefold()
        entity_id = _optional_int(self._selected_profile.get("id"))
        if kind in {"character", "staff", "voice_actor"} and entity_id and entity_id > 0:
            self._profile_generation += 1
            worker = _ProfileWorker(self._profile_generation, kind, entity_id)
            worker.signals.finished.connect(self._profile_finished)
            self._profile_workers[self._profile_generation] = worker
            QThreadPool.globalInstance().start(worker)
        else:
            self._selected_profile["profileLoading"] = False
            self.selectedProfileChanged.emit()

    @Slot(int, object, object)
    def _profile_finished(self, generation, profile, error):
        self._profile_workers.pop(generation, None)
        if generation != self._profile_generation:
            return
        if error:
            self._selected_profile["profileLoading"] = False
            self._selected_profile["profileError"] = "Profile details could not be loaded right now."
            self._decorate_selected_profile()
            log_event("qml_bridge.profile_load_failed", error=str(error)[:500])
            self.selectedProfileChanged.emit()
            return
        if isinstance(profile, dict):
            entity_type = self._selected_profile.get("entity_type")
            self._selected_profile.update(_plain(profile))
            self._selected_profile["entity_type"] = entity_type
            self._selected_profile["profileLoading"] = False
            self._selected_profile["profileError"] = ""
            self._decorate_selected_profile()
            self.selectedProfileChanged.emit()

    @Slot()
    def toggleSelectedProfileFavorite(self):
        profile = self._selected_profile
        kind = str(profile.get("entity_type") or "").casefold()
        entity_id = _optional_int(profile.get("id"))
        if kind not in {"character", "staff", "voice_actor"} or entity_id is None or entity_id <= 0:
            return
        favorite = not bool(profile.get("isFavorite"))
        name = str(profile.get("displayName") or profile.get("entity_name") or profile.get("character_name") or "")
        language = profile.get("languageV2") or profile.get("language")
        try:
            saved = set_entity_favorite(kind, entity_id, favorite, name=name, language=language)
            if not saved:
                raise RuntimeError("The favorite state was not saved.")
        except Exception as error:
            log_exception("qml_bridge.profile_favorite_save_failed", error, entity_type=kind, entity_id=entity_id)
            profile["profileError"] = "Favorite state could not be saved."
            self.selectedProfileChanged.emit()
            return
        profile["isFavorite"] = favorite
        profile["profileError"] = ""
        self.selectedProfileChanged.emit()
        self.refreshFavorites()

    @Slot(int)
    def requestOpenProfileWork(self, work_id):
        normalized = _optional_int(work_id)
        if normalized is None or normalized == 0:
            return
        group = self._group_for_id(normalized)
        if group is not None:
            self.openWorkRequested.emit(normalized)
        else:
            self.requestOpenSearchWork(normalized)

    # ---- Work Details -----------------------------------------------------------

    @Property("QVariantMap", notify=selectedWorkChanged)
    def selectedWork(self):
        return dict(self._selected_work)

    @Property("QVariantList", notify=episodesChanged)
    def episodeItems(self):
        return list(self._episode_items)

    @Slot(object)
    def setSelectedWork(self, work):
        raw = _plain(work) if isinstance(work, dict) or hasattr(work, "keys") else {}
        if not isinstance(raw, dict):
            raw = {}
        work_id = _optional_int(raw.get("id"))
        if work_id is None or work_id == 0:
            return
        previous = self._current_page
        if previous not in {"work_detail", "entity_profile", "relation"}:
            self._previous_content_page = previous

        local_group = self._group_for_id(work_id)
        source = local_group if local_group is not None else raw
        normalized = _normalize_group(source) or {}
        cover_source = normalized.get("coverSource") or _image_source(source)
        title = (
            normalized.get("title")
            or _title(raw.get("title"))
            or raw.get("name")
            or f"Untitled · {work_id}"
        )
        start_date = raw.get("startDate") if isinstance(raw.get("startDate"), dict) else {}
        start_year = normalized.get("startYear") or _optional_int(start_date.get("year")) or 0
        media_type = str(raw.get("type") or normalized.get("mediaType") or "UNKNOWN").upper()
        fmt = str(raw.get("format") or normalized.get("format") or "").upper()
        synopsis = str(raw.get("description") or raw.get("synopsis") or "")
        raw_members = source.get("_series_members") or raw.get("_series_members") or [source]
        member_ids = []
        bundle_members = []
        for member in raw_members:
            if not isinstance(member, dict):
                continue
            normalized_member = _normalize_group(member) or {}
            member_id = _optional_int(member.get("id"))
            if member_id is None or member_id == 0:
                continue
            member_ids.append(member_id)
            bundle_members.append({
                "id": member_id,
                "title": str(normalized_member.get("fullTitle") or normalized_member.get("title")
                    or _title(member.get("title")) or f"Untitled · {member_id}"),
                "coverSource": normalized_member.get("coverSource") or _image_source(member),
                "mediaType": str(member.get("type") or "UNKNOWN").upper(),
                "format": str(member.get("format") or "").upper(),
                "startYear": _optional_int(member.get("start_year")) or 0,
            })
        if not member_ids:
            member_ids = [work_id]
            bundle_members = [{
                "id": work_id,
                "title": str(title),
                "coverSource": cover_source,
                "mediaType": media_type,
                "format": fmt,
                "startYear": start_year,
            }]

        is_in_library = is_work_in_library(work_id)
        reading_members = [
            dict(member)
            for member in bundle_members
            if str(member.get("mediaType") or "").upper() == "MANGA"
            or str(member.get("format") or "").upper() in {"NOVEL", "LIGHT_NOVEL"}
        ]
        detail_data = {
            "id": work_id,
            "title": str(title),
            "fullTitle": str(title),
            "coverSource": cover_source,
            "mediaType": media_type,
            "format": fmt,
            "startYear": start_year,
            "synopsis": synopsis,
            "status": str(raw.get("status") or (local_group or {}).get("status") or "Planning"),
            "isInLibrary": is_in_library,
            "progressEpisodes": _optional_int(raw.get("progress_episodes") or raw.get("_series_progress")) or 0,
            "progressChapters": _optional_int(raw.get("progress_chapters")) or 0,
            "progressVolumes": _optional_int(raw.get("progress_volumes")) or 0,
            "episodeTotal": _optional_int(raw.get("episodes") or raw.get("_series_episode_total")) or 0,
            "seriesCount": _optional_int(raw.get("_series_count")) or len(bundle_members) or 1,
            "bundleSummary": str(raw.get("_bundle_summary") or ""),
            "memberIds": member_ids,
            "bundleMembers": bundle_members,
            "readingMembers": reading_members,
            "characters": [],
            "staff": [],
            "relations": [],
            "detailsLoading": True,
        }
        self._selected_work_raw = raw
        self._selected_work = detail_data
        self._episode_items = []
        self._current_page = "work_detail"
        self.selectedWorkChanged.emit()
        self.episodesChanged.emit()
        self.pageChanged.emit()

        self._detail_generation += 1
        generation = self._detail_generation
        worker = _DetailSnapshotWorker(
            generation,
            work_id,
            member_ids,
            {
                _optional_int(member.get("id")): member.get("title")
                for member in bundle_members
                if _optional_int(member.get("id")) is not None
            },
        )
        worker.signals.finished.connect(self._detail_snapshot_ready)
        self._detail_workers[generation] = worker
        QThreadPool.globalInstance().start(worker)

    @Slot(int, object, object)
    def _detail_snapshot_ready(self, generation, payload, error):
        self._detail_workers.pop(generation, None)
        if generation != self._detail_generation or self._current_page not in {
            "work_detail", "relation",
        }:
            return
        if error or not isinstance(payload, dict):
            log_event(
                "qml_bridge.detail_snapshot_failed",
                work_id=self._selected_work.get("id"),
                error=str(error or "Invalid detail snapshot")[:1000],
            )
            self._selected_work["detailsLoading"] = False
            self.selectedWorkChanged.emit()
            return

        local_work = payload.get("localWork") or {}
        if isinstance(local_work, dict):
            if not self._selected_work.get("synopsis"):
                self._selected_work["synopsis"] = str(local_work.get("description") or "")
            self._selected_work["isInLibrary"] = is_work_in_library(
                self._selected_work.get("id")
            )
            self._selected_work["status"] = str(
                local_work.get("status") or self._selected_work.get("status") or "Planning"
            )
            if payload.get("hasLocalWork"):
                self._selected_work["progressEpisodes"] = _optional_int(
                    payload.get("progressEpisodes")
                ) or 0
            self._selected_work["progressChapters"] = _optional_int(
                payload.get("progressChapters")
            ) or 0
            self._selected_work["chapterTotal"] = _optional_int(
                payload.get("chapterTotal")
            ) or 0
            self._selected_work["progressVolumes"] = _optional_int(
                payload.get("progressVolumes")
            ) or 0
            self._selected_work["volumeTotal"] = _optional_int(
                payload.get("volumeTotal")
            ) or 0
            aggregate_episode_total = _optional_int(payload.get("episodeTotal")) or 0
            if aggregate_episode_total > 0:
                self._selected_work["episodeTotal"] = aggregate_episode_total
            self._selected_work["readingProgressByWork"] = payload.get("readingProgressByWork") or {}

        self._selected_work["characters"] = payload.get("characters") or []
        self._selected_work["staff"] = payload.get("staff") or []
        self._selected_work["relations"] = payload.get("relations") or []
        self._selected_work["detailsLoading"] = False
        self._episode_items = payload.get("episodes") or []
        self.selectedWorkChanged.emit()
        self.episodesChanged.emit()
        log_event(
            "qml_bridge.detail_snapshot_ready",
            work_id=self._selected_work.get("id"),
            episode_count=len(self._episode_items),
            character_count=len(self._selected_work["characters"]),
            staff_count=len(self._selected_work["staff"]),
            relation_count=len(self._selected_work["relations"]),
        )

    @Slot(int, bool)
    def markAllEpisodesWatched(self, work_id, watched):
        try:
            selected_id = _optional_int(self._selected_work.get("id"))
            selected_member_ids = [
                _optional_int(value)
                for value in self._selected_work.get("memberIds") or []
            ]
            selected_member_ids = [
                value for value in selected_member_ids if value not in (None, 0)
            ]
            targets = (
                list(dict.fromkeys(selected_member_ids))
                if selected_id == _optional_int(work_id) and selected_member_ids
                else [_optional_int(work_id)]
            )
            for target_id in targets:
                if target_id in (None, 0):
                    continue
                snapshot = get_episode_section_snapshot(target_id)
                numbers = [
                    _optional_int(dict(row).get("episode_number"))
                    for row in snapshot.get("episodes") or []
                ]
                numbers = [number for number in numbers if number is not None] if watched else []
                set_episode_progress(target_id, numbers)
            self.setSelectedWork(self._selected_work_raw)
            self.refreshHome()
        except Exception as error:
            log_exception("qml_bridge.mark_all_episodes_failed", error, work_id=work_id)

    @Slot(int, int, bool)
    def setEpisodeWatched(self, work_id, episode_number, watched):
        number = _optional_int(episode_number)
        if number is None:
            return
        try:
            # The visible detail list is capped for responsiveness. Read the full
            # saved episode set before changing one item so higher-numbered episodes
            # are not accidentally marked unwatched.
            snapshot = get_episode_section_snapshot(work_id)
            current = [
                current_number
                for row in snapshot.get("episodes") or []
                if bool(dict(row).get("watched"))
                for current_number in [_optional_int(dict(row).get("episode_number"))]
                if current_number is not None
            ]
            if watched and number not in current:
                current.append(number)
            elif not watched and number in current:
                current.remove(number)
            set_episode_progress(work_id, current)
        except Exception as error:
            log_exception("qml_bridge.episode_progress_save_failed", error, work_id=work_id, episode_number=number)
        self.setSelectedWork(self._selected_work_raw)
        self.refreshHome()

    @Slot(int, str, int)
    def setReadingProgress(self, work_id, item_type, read_count):
        self._save_reading_progress(work_id, item_type, read_count, 0)

    @Slot(int, str, int, int)
    def setReadingProgressWithTotal(self, work_id, item_type, read_count, total_hint):
        self._save_reading_progress(work_id, item_type, read_count, total_hint)

    def _save_reading_progress(self, work_id, item_type, read_count, total_hint=0):
        try:
            set_reading_progress_count(work_id, item_type, read_count, total_hint)
            # Reload the selected member's counters off the UI thread and
            # recompute the bundle aggregate from persisted member records.
            self.setSelectedWork(self._selected_work_raw)
            self.forceRefreshAll()
            self.refreshHome()
        except Exception as error:
            log_exception("qml_bridge.reading_progress_save_failed", error, work_id=work_id, item_type=item_type)

    # ---- QML poster menus and refresh ------------------------------------------

    @Slot(str)
    def reportSearchError(self, message):
        self._search_error = str(message or "")
        self.searchChanged.emit()

    @Slot()
    def refreshSelectedWork(self):
        if self._selected_work_raw:
            self.setSelectedWork(self._selected_work_raw)

    @Slot()
    def refreshVisiblePage(self):
        if self._current_page == "collections":
            self.refreshAll()
        elif self._current_page == "home":
            self.refreshHome()
        elif self._current_page == "calendar":
            self.refreshCalendar()
        elif self._current_page == "favorites":
            self.refreshFavorites()
        elif self._current_page == "search":
            # Returning from Details should not issue another provider search.
            # Refresh the local membership/title snapshot while preserving result
            # order, pagination and scroll position.
            refreshed = []
            for item in self._search_items:
                row = dict(item)
                raw = self._search_rows.get(_optional_int(row.get("workId") or row.get("id")))
                if raw is not None:
                    normalized = _normalize_group(raw)
                    if normalized is not None:
                        row["title"] = normalized.get("title") or row.get("title") or "Untitled"
                        row["fullTitle"] = normalized.get("fullTitle") or row["title"]
                        row["coverSource"] = normalized.get("coverSource") or row.get("coverSource") or ""
                        row["isInLibrary"] = is_work_in_library(normalized["workId"])
                refreshed.append(row)
            self._search_items = refreshed
            self.searchChanged.emit()

