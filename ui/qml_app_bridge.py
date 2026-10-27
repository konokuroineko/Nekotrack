"""Bridge for the single-root QML application shell; Python remains the data/backend layer."""
from __future__ import annotations

import datetime
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Property, QRunnable, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import QFileDialog

from api import get_entity_profile
from catalog_search import search_combined_media
from database import (
    get_entity_favorites,
    get_episode_section_snapshot,
    get_reading_progress,
    get_upcoming_library_episodes,
    is_work_in_library,
    set_entity_favorite,
    set_episode_progress,
    set_reading_progress_count,
    set_release_reminder,
)
from diagnostics import log_event, log_exception
from series import get_library_series, group_media_results
from ui.preferences import apply_theme_preset, get, set_value
from ui.qml_bridge import (
    QmlApplicationBridge as LibraryBridge,
    _normalize_group,
    _optional_int,
    _remote_image_url,
)
from ui.theme import COLORS, THEME_PRESETS, refresh_theme, surface_rgba


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
                include_relations=True,
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

    pageChanged = Signal()
    backgroundChanged = Signal()
    homeChanged = Signal()
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
    bundleEditRequested = Signal(int)
    bundleDeleteRequested = Signal(int)

    def __init__(self, parent=None, background_manager=None):
        self._raw_groups = []
        self._current_page = "home"
        self._previous_content_page = "home"
        self._home_items = []
        self._home_stats = {"all": 0, "inProgress": 0, "completed": 0, "planned": 0}
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
        self._favorites_items = []
        self._selected_work = {}
        self._selected_work_raw = {}
        self._episode_items = []
        self._selected_profile = {}
        self._profile_generation = 0
        self._profile_workers = {}
        self._background_manager = background_manager
        self._background_source = ""
        super().__init__(
            parent=parent,
            library_loader=lambda: self._raw_groups,
            auto_refresh=False,
        )
        if self._background_manager is not None:
            self._background_manager.background_changed.connect(self._background_changed)
            self._background_manager.images_changed.connect(self._background_changed)
        self.refreshTheme()
        self._background_changed()

    # ---- Global shell and theme -------------------------------------------------

    @Property(str, notify=pageChanged)
    def currentPage(self):
        return self._current_page

    @Property(str, notify=backgroundChanged)
    def backgroundSource(self):
        return self._background_source

    @Property(str, notify=themeChanged)
    def backgroundColor(self):
        return COLORS.get("background", "#17131e")

    @Property(str, notify=themeChanged)
    def backgroundOverlayColor(self):
        if self._background_manager is None or not self._background_manager.display_pixmap:
            return "#00000000"
        color = QColor(COLORS.get("background", "#17131e"))
        color.setAlpha(round(255 * self._background_manager.overlay_opacity / 100))
        return color.name(QColor.NameFormat.HexArgb)

    @Property(str, notify=themeChanged)
    def sidebarFillColor(self):
        return surface_rgba("sidebar")

    @Property(str, notify=themeChanged)
    def surfaceFillColor(self):
        return surface_rgba("surface")

    @Property(str, notify=themeChanged)
    def surfaceAltFillColor(self):
        return surface_rgba("surface_alt")

    @Property(str, notify=themeChanged)
    def borderColor(self):
        return COLORS.get("border", "#51475f")

    @Property(str, notify=themeChanged)
    def accentColor(self):
        return COLORS.get("accent", "#9271c5")

    @Property(str, notify=themeChanged)
    def successColor(self):
        return COLORS.get("success", "#55b881")

    @Property(str, notify=themeChanged)
    def dangerColor(self):
        return COLORS.get("danger", "#d85b70")

    @Property(str, notify=themeChanged)
    def themePreset(self):
        return str(get("theme_preset") or "Neko")

    @Property(bool, notify=themeChanged)
    def lightMode(self):
        return bool(get("light_mode"))

    @Property(int, notify=backgroundChanged)
    def backgroundOverlayOpacity(self):
        return int(self._background_manager.overlay_opacity) if self._background_manager else int(get("background_overlay_opacity"))

    @Property("QVariantList", notify=backgroundChanged)
    def backgroundPaths(self):
        return list(self._background_manager.paths) if self._background_manager else []

    @Property("QVariantList", constant=True)
    def themePresets(self):
        return list(THEME_PRESETS.keys())

    def _background_changed(self, *_args):
        manager = self._background_manager
        raw_path = manager.selected_path if manager is not None and manager.display_pixmap is not None else None
        self._background_source = _file_source(raw_path)
        self.backgroundChanged.emit()

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
            elif target == "calendar":
                self.refreshCalendar()
            elif target == "favorites":
                self.refreshFavorites()
            return
        self._current_page = target
        self.pageChanged.emit()
        if target == "collections":
            self.refreshAll()
        elif target == "home":
            if not self._raw_groups:
                self.refreshAll()
            else:
                self._refresh_home_items()
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
            "theme_preset", "light_mode", "card_size", "card_gap",
            "corner_radius", "font_size", "hover_highlight",
            "resize_animation", "animation_speed", "background_overlay_opacity",
            "background_slideshow_interval",
        }
        key = str(key or "")
        if key not in allowed:
            return
        try:
            if key == "theme_preset":
                apply_theme_preset(str(value))
            elif key == "background_overlay_opacity" and self._background_manager is not None:
                self._background_manager.set_overlay_opacity(value)
            else:
                set_value(key, value)
            refresh_theme()
            self.refreshTheme()
            self._background_changed()
            self.settingsChanged.emit(key)
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

    # ---- Library, Home and page refresh ----------------------------------------

    def _load_groups(self):
        try:
            rows = get_library_series()
            self._raw_groups = [_plain(group) for group in (rows or []) if isinstance(group, dict) or hasattr(group, "keys")]
            self._library_model.refresh()
            self._refresh_home_items()
        except Exception as error:
            log_exception("qml_bridge.library_snapshot_failed", error)
            self.errorOccurred.emit("NekoTrack could not load the Library. Check the diagnostic log.")

    @Slot()
    def refreshAll(self):
        self._load_groups()

    @Slot()
    def refreshHome(self):
        if not self._raw_groups:
            self._load_groups()
        else:
            self._library_model.refresh()
            self._refresh_home_items()

    def _refresh_home_items(self):
        all_rows = list(self._library_model._all_rows)
        statuses = [str(row.get("status") or "").strip().casefold() for row in all_rows]
        ongoing = {"watching", "rewatching", "reading", "in progress"}
        planned = {"planning", "plan to watch", "plan to read"}
        completed = {"completed"}
        self._home_stats = {
            "all": len(all_rows),
            "inProgress": sum(status in ongoing for status in statuses),
            "completed": sum(status in completed for status in statuses),
            "planned": sum(status in planned for status in statuses),
        }
        self._home_items = [
            dict(row) for row in all_rows
            if str(row.get("status") or "").strip().casefold() in ongoing
        ]
        self.homeChanged.emit()

    @Property("QVariantList", notify=homeChanged)
    def homeItems(self):
        return list(self._home_items)

    @Property("QVariantMap", notify=homeChanged)
    def homeStats(self):
        return dict(self._home_stats)

    @Slot(int)
    def requestOpenWork(self, work_id):
        normalized = _optional_int(work_id)
        if normalized is None or normalized == 0:
            return
        group = self._group_for_id(normalized)
        if group is not None:
            self.openWorkRequested.emit(normalized)

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

    @Slot(str, str, str)
    def searchCatalog(self, query, media_type="", media_format=""):
        self._search_query = str(query or "").strip()
        self._search_type = str(media_type or "")
        self._search_format = str(media_format or "")
        self._search_filters = {}
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

    # ---- Calendar and reminders -------------------------------------------------

    @Property("QVariantList", notify=calendarChanged)
    def calendarItems(self):
        return list(self._calendar_items)

    @Slot()
    def refreshCalendar(self):
        today = datetime.date.today()
        last_day = today + datetime.timedelta(days=60)
        try:
            rows = get_upcoming_library_episodes(
                today.isoformat(),
                (last_day + datetime.timedelta(days=1)).isoformat(),
            )
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
            self._calendar_items = items
        except Exception as error:
            log_exception("qml_bridge.calendar_load_failed", error)
            self._calendar_items = []
        self.calendarChanged.emit()

    @Slot(int, int, bool)
    def setReminder(self, work_id, episode_number, enabled):
        try:
            if set_release_reminder(work_id, episode_number, enabled):
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
        self._selected_profile = profile
        self.selectedProfileChanged.emit()
        self.profileRequested.emit(profile)

    @Property("QVariantMap", notify=selectedProfileChanged)
    def selectedProfile(self):
        return dict(self._selected_profile)

    @Slot(object)
    def setSelectedProfile(self, profile):
        if isinstance(profile, dict):
            self._selected_profile = _plain(profile)
            self.selectedProfileChanged.emit()
            kind = str(self._selected_profile.get("entity_type") or "").casefold()
            entity_id = _optional_int(self._selected_profile.get("id"))
            if kind in {"character", "staff", "voice_actor"} and entity_id and entity_id > 0:
                self._profile_generation += 1
                worker = _ProfileWorker(self._profile_generation, kind, entity_id)
                worker.signals.finished.connect(self._profile_finished)
                self._profile_workers[self._profile_generation] = worker
                QThreadPool.globalInstance().start(worker)

    @Slot(int, object, object)
    def _profile_finished(self, generation, profile, error):
        self._profile_workers.pop(generation, None)
        if generation != self._profile_generation:
            return
        if error:
            log_event("qml_bridge.profile_load_failed", error=str(error)[:500])
            return
        if isinstance(profile, dict):
            self._selected_profile.update(_plain(profile))
            self.selectedProfileChanged.emit()

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
            "isInLibrary": is_work_in_library(work_id),
            "progressEpisodes": _optional_int(raw.get("progress_episodes") or raw.get("_series_progress")) or 0,
            "progressChapters": _optional_int(raw.get("progress_chapters")) or 0,
            "progressVolumes": _optional_int(raw.get("progress_volumes")) or 0,
            "episodeTotal": _optional_int(raw.get("episodes") or raw.get("_series_episode_total")) or 0,
            "seriesCount": _optional_int(raw.get("_series_count")) or 1,
            "bundleSummary": str(raw.get("_bundle_summary") or ""),
        }
        episode_items = []
        try:
            snapshot = get_episode_section_snapshot(work_id)
            local_work = snapshot.get("work")
            if local_work is not None:
                local_map = _plain(dict(local_work))
                detail_data["isInLibrary"] = is_work_in_library(work_id)
                detail_data["status"] = str(local_map.get("status") or detail_data["status"])
                detail_data["progressEpisodes"] = _optional_int(local_map.get("progress_episodes")) or 0
                detail_data["progressChapters"] = _optional_int(local_map.get("progress_chapters")) or 0
                detail_data["progressVolumes"] = _optional_int(local_map.get("progress_volumes")) or 0
                detail_data["episodeTotal"] = _optional_int(local_map.get("episodes")) or detail_data["episodeTotal"]
            for row in (snapshot.get("episodes") or [])[:300]:
                episode = _plain(dict(row))
                number = _optional_int(episode.get("episode_number"))
                if number is None:
                    continue
                episode_items.append({
                    "workId": work_id,
                    "episodeNumber": number,
                    "title": str(episode.get("title") or f"Episode {number}"),
                    "description": str(episode.get("description") or ""),
                    "airDate": str(episode.get("air_date") or ""),
                    "watched": bool(episode.get("watched")),
                    "coverSource": _file_source(episode.get("thumbnail_path") or episode.get("image_path"))
                        or _image_source({"cover_url": episode.get("image_url")}),
                })
        except Exception as error:
            log_exception("qml_bridge.work_snapshot_failed", error, work_id=work_id)
        self._selected_work_raw = raw
        self._selected_work = detail_data
        self._episode_items = episode_items
        self._current_page = "work_detail"
        self.selectedWorkChanged.emit()
        self.episodesChanged.emit()
        self.pageChanged.emit()

    @Slot(int, int, bool)
    def setEpisodeWatched(self, work_id, episode_number, watched):
        current = [item["episodeNumber"] for item in self._episode_items if item["watched"]]
        number = _optional_int(episode_number)
        if number is None:
            return
        if watched and number not in current:
            current.append(number)
        elif not watched and number in current:
            current.remove(number)
        try:
            set_episode_progress(work_id, current)
        except Exception as error:
            log_exception("qml_bridge.episode_progress_save_failed", error, work_id=work_id, episode_number=number)
        self.setSelectedWork(self._selected_work_raw)
        self.refreshHome()

    @Slot(int, str, int, int)
    def setReadingProgress(self, work_id, item_type, read_count, total_hint=0):
        try:
            set_reading_progress_count(work_id, item_type, read_count, total_hint)
            chapters, _chapter_total = get_reading_progress(work_id, "chapter")
            volumes, _volume_total = get_reading_progress(work_id, "volume")
            self._selected_work["progressChapters"] = chapters
            self._selected_work["progressVolumes"] = volumes
            self.selectedWorkChanged.emit()
            self.refreshAll()
        except Exception as error:
            log_exception("qml_bridge.reading_progress_save_failed", error, work_id=work_id, item_type=item_type)

    # ---- QML poster menus and refresh ------------------------------------------

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
            if self._search_query:
                self.searchCatalog(self._search_query, self._search_type, self._search_format)

