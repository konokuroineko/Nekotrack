"""Read-only model and narrow host bridge for NekoTrack's QML Library view."""
import re
import shutil
from pathlib import Path

from PySide6.QtCore import (
    QAbstractListModel, QModelIndex, QObject, Property, QUrl, Qt, Signal, Slot,
)
from PySide6.QtGui import QFont, QFontMetrics, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from database import save_cover_path
from diagnostics import log_event, log_exception
from series import get_library_series
from ui.display_identity import get_display_override
from ui.preferences import get
from ui.theme import COLORS

_IMAGE_DIRECTORY = Path("data") / "images" / "works"
_FILTERS = ("All", "Watching", "Completed", "Planned")


def _optional_int(value):
    """Convert an integer-like value without accepting booleans or malformed strings."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        if not text or len(text) > 20:
            return None
        try:
            return int(text, 10)
        except ValueError:
            return None
    return None


def _count(value):
    parsed = _optional_int(value)
    return max(0, parsed) if parsed is not None else 0


def _row_dict(value):
    try:
        return dict(value)
    except (TypeError, ValueError):
        return None


def _member_rows(group, work_id):
    """Keep canonical member order; never sort bundle members by ID."""
    raw_members = group.get("_series_members")
    members = []
    seen = set()
    if isinstance(raw_members, (list, tuple)):
        for raw_member in raw_members:
            member = _row_dict(raw_member)
            if member is None:
                continue
            member_id = _optional_int(member.get("id"))
            if member_id is None or member_id == 0 or member_id in seen:
                continue
            seen.add(member_id)
            members.append(member)
    if not members:
        members = [group]
    return members, [int(member["id"]) for member in members]


def _fit_title_to_two_lines(text, width, font):
    """Keep the same two-line title fitting used by the original WorkCard."""
    text = " ".join(str(text).split())
    if not text:
        return ""
    metrics = QFontMetrics(font)
    words = text.split()
    first = ""
    first_end = 0
    for index, word in enumerate(words):
        candidate = word if not first else f"{first} {word}"
        if metrics.horizontalAdvance(candidate) <= width:
            first = candidate
            first_end = index + 1
        else:
            break
    if first_end >= len(words):
        return first
    second = ""
    second_end = first_end
    for index in range(first_end, len(words)):
        candidate = words[index] if not second else f"{second} {words[index]}"
        if metrics.horizontalAdvance(candidate) <= width:
            second = candidate
            second_end = index + 1
        else:
            break
    if second_end < len(words):
        overflow = " ".join(words[second_end:])
        second = metrics.elidedText(
            f"{second} {overflow}" if second else overflow,
            Qt.TextElideMode.ElideRight,
            width,
        )
    return f"{first}\n{second}" if second else f"{first}\n{metrics.elidedText(' '.join(words[first_end:]), Qt.TextElideMode.ElideRight, width)}"


def _display_title(value, group=None):
    if isinstance(value, dict):
        english = value.get("english")
        romanized = value.get("romaji")
        native = value.get("native")
        mangabaka = group.get("_mangabaka") if isinstance(group, dict) else None
        if isinstance(mangabaka, dict) and english and romanized:
            for record in mangabaka.get("titles") or []:
                if not isinstance(record, dict):
                    continue
                if str(record.get("language") or "").lower() == "ja-latn" and record.get("title"):
                    romanized = record["title"]
                    if record.get("is_primary"):
                        break
            normalize = lambda item: re.sub(r"[^a-z0-9]+", "", str(item or "").casefold())
            if normalize(english) != normalize(romanized):
                return f"{english} — {romanized}"
        for candidate in (english, romanized, native):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return ""
    return value.strip() if isinstance(value, str) else ""


def _resolved_path(path):
    if not isinstance(path, str) or not path.strip():
        return None
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    try:
        return candidate.resolve() if candidate.is_file() else None
    except (OSError, RuntimeError):
        return None


def _remote_image_url(value):
    if not isinstance(value, str) or not value.strip():
        return ""
    url = QUrl(value.strip())
    if url.scheme().casefold() not in {"http", "https"} or not url.isValid():
        return ""
    return url.toString()


def _local_or_remote_cover(group, members, single_override=None):
    """Resolve the selected or custom cover while preferring existing cached files."""
    selected_cover_id = _optional_int(group.get("_bundle_cover_work_id"))
    selected_member = next(
        (
            member for member in members
            if selected_cover_id is not None
            and _optional_int(member.get("id")) == selected_cover_id
        ),
        None,
    )
    fallback_member = next(
        (member for member in members if _display_title(member.get("title"), member)),
        members[0] if members else group,
    )

    path_candidates = []
    if isinstance(single_override, dict):
        path_candidates.append(single_override.get("custom_cover_path"))
    path_candidates.extend((
        group.get("_bundle_custom_cover_path"),
        group.get("custom_cover_path"),
    ))
    if selected_member is not None:
        path_candidates.extend((selected_member.get("cover_path"), selected_member.get("image_path")))
        if fallback_member is not group and fallback_member is not selected_member:
            path_candidates.extend((fallback_member.get("cover_path"), fallback_member.get("image_path")))
    else:
        path_candidates.extend((group.get("cover_path"), group.get("image_path")))
        if fallback_member is not group:
            path_candidates.extend((fallback_member.get("cover_path"), fallback_member.get("image_path")))
    for raw_path in path_candidates:
        path = _resolved_path(raw_path)
        if path is not None:
            return QUrl.fromLocalFile(str(path)).toString()

    url_candidates = []
    if selected_member is not None:
        url_candidates.extend((selected_member.get("cover_url"), selected_member.get("image_url")))
        selected_image = selected_member.get("coverImage")
        if isinstance(selected_image, dict):
            url_candidates.extend((selected_image.get("extraLarge"), selected_image.get("large")))
        if fallback_member is not group and fallback_member is not selected_member:
            url_candidates.extend((fallback_member.get("cover_url"), fallback_member.get("image_url")))
            fallback_image = fallback_member.get("coverImage")
            if isinstance(fallback_image, dict):
                url_candidates.extend((fallback_image.get("extraLarge"), fallback_image.get("large")))
    else:
        url_candidates.extend((group.get("cover_url"), group.get("image_url")))
        group_image = group.get("coverImage")
        if isinstance(group_image, dict):
            url_candidates.extend((group_image.get("extraLarge"), group_image.get("large")))
        if fallback_member is not group:
            url_candidates.extend((fallback_member.get("cover_url"), fallback_member.get("image_url")))
            fallback_image = fallback_member.get("coverImage")
            if isinstance(fallback_image, dict):
                url_candidates.extend((fallback_image.get("extraLarge"), fallback_image.get("large")))
    for raw_url in url_candidates:
        url = _remote_image_url(raw_url)
        if url:
            return url
    return ""


def _normalize_group(raw_group):
    group = _row_dict(raw_group)
    if group is None:
        return None
    work_id = _optional_int(group.get("id"))
    if work_id is None or work_id == 0:
        return None

    members, member_ids = _member_rows(group, work_id)
    series_count = _count(group.get("_series_count")) or len(member_ids)
    single_override = None
    if series_count <= 1:
        try:
            single_override = get_display_override(work_id)
        except Exception:
            single_override = None

    title = _display_title(group.get("title"), group)
    if series_count <= 1 and isinstance(single_override, dict):
        custom_title = single_override.get("custom_title")
        if isinstance(custom_title, str) and custom_title.strip():
            title = custom_title.strip()
    if not title:
        title = next(
            (_display_title(member.get("title"), member) for member in members
             if _display_title(member.get("title"), member)),
            "",
        )

    start_year = _optional_int(group.get("start_year"))
    if start_year is None:
        start_date = group.get("startDate")
        if isinstance(start_date, dict):
            start_year = _optional_int(start_date.get("year"))

    episode_total = _count(group.get("_series_episode_total"))
    if "_series_episode_total" not in group:
        episode_total = sum(_count(member.get("episodes")) for member in members)
    episode_progress = _count(group.get("_series_progress"))
    if "_series_progress" not in group:
        episode_progress = sum(_count(member.get("progress_episodes")) for member in members)

    cover_work_id = _optional_int(group.get("_bundle_cover_work_id"))
    if cover_work_id is None:
        cover_work_id = _optional_int(group.get("_bundle_default_member_id"))
    if cover_work_id is None:
        cover_work_id = work_id

    full_title = title or f"Untitled · {work_id}"
    title_font_size = max(8, int(get("font_size") or 13))
    title_font = QFont("Segoe UI", title_font_size)
    title_font.setWeight(QFont.Weight.Bold)
    fitted_title = _fit_title_to_two_lines(full_title, max(1, min(270, max(80, int(get("card_size")))) - 4), title_font)

    return {
        "workId": work_id,
        "title": fitted_title,
        "fullTitle": full_title,
        "mediaType": str(group.get("type") or "UNKNOWN").upper(),
        "format": str(group.get("format") or "").upper(),
        "startYear": start_year or 0,
        "coverSource": _local_or_remote_cover(group, members, single_override),
        "coverCacheWorkId": cover_work_id,
        "status": str(group.get("status") or "Planning"),
        "progressEpisodes": episode_progress,
        "episodeTotal": episode_total,
        "progressChapters": sum(_count(member.get("progress_chapters")) for member in members),
        "progressVolumes": sum(_count(member.get("progress_volumes")) for member in members),
        "seriesCount": series_count,
        "bundleSummary": str(group.get("_bundle_summary") or ""),
        "memberIds": member_ids,
    }


class LibraryListModel(QAbstractListModel):
    """Read-only QML model backed by NekoTrack's canonical Library groups."""

    WorkIdRole = int(Qt.ItemDataRole.UserRole) + 1
    TitleRole = WorkIdRole + 1
    MediaTypeRole = TitleRole + 1
    FormatRole = MediaTypeRole + 1
    StartYearRole = FormatRole + 1
    CoverSourceRole = StartYearRole + 1
    CoverCacheWorkIdRole = CoverSourceRole + 1
    StatusRole = CoverCacheWorkIdRole + 1
    ProgressEpisodesRole = StatusRole + 1
    EpisodeTotalRole = ProgressEpisodesRole + 1
    ProgressChaptersRole = EpisodeTotalRole + 1
    ProgressVolumesRole = ProgressChaptersRole + 1
    SeriesCountRole = ProgressVolumesRole + 1
    BundleSummaryRole = SeriesCountRole + 1
    MemberIdsRole = BundleSummaryRole + 1
    FullTitleRole = MemberIdsRole + 1

    _ROLE_NAMES = {
        WorkIdRole: b"workId",
        TitleRole: b"title",
        MediaTypeRole: b"mediaType",
        FormatRole: b"format",
        StartYearRole: b"startYear",
        CoverSourceRole: b"coverSource",
        CoverCacheWorkIdRole: b"coverCacheWorkId",
        StatusRole: b"status",
        ProgressEpisodesRole: b"progressEpisodes",
        EpisodeTotalRole: b"episodeTotal",
        ProgressChaptersRole: b"progressChapters",
        ProgressVolumesRole: b"progressVolumes",
        SeriesCountRole: b"seriesCount",
        BundleSummaryRole: b"bundleSummary",
        MemberIdsRole: b"memberIds",
        FullTitleRole: b"fullTitle",
    }
    rowsReloaded = Signal(int)

    def __init__(self, library_loader=None, parent=None):
        super().__init__(parent)
        self._library_loader = library_loader or get_library_series
        self._all_rows = []
        self._rows = []
        self._filter = "All"

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def roleNames(self):
        return dict(self._ROLE_NAMES)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.parent().isValid():
            return None
        row_number = index.row()
        if row_number < 0 or row_number >= len(self._rows):
            return None
        row = self._rows[row_number]
        if role == Qt.ItemDataRole.DisplayRole:
            return row["title"]
        role_name = self._ROLE_NAMES.get(int(role))
        return row.get(role_name.decode("ascii")) if role_name is not None else None

    def _filtered_rows(self):
        wanted = {"All": None, "Watching": "Watching",
                  "Completed": "Completed", "Planned": "Planning"}[self._filter]
        if wanted is None:
            return list(self._all_rows)
        return [row for row in self._all_rows if row["status"] == wanted]

    def set_filter(self, value):
        if value not in _FILTERS or value == self._filter:
            return False
        self.beginResetModel()
        self._filter = value
        self._rows = self._filtered_rows()
        self.endResetModel()
        self.rowsReloaded.emit(len(self._rows))
        return True

    def refresh(self):
        """Reload canonical groups while keeping the current status filter."""
        groups = self._library_loader()
        if groups is None:
            groups = []
        if isinstance(groups, (str, bytes, dict)) or not hasattr(groups, "__iter__"):
            raise TypeError("The Library grouping service returned an invalid result.")
        refreshed = []
        for group in groups:
            normalized = _normalize_group(group)
            if normalized is not None:
                refreshed.append(normalized)
        self.beginResetModel()
        self._all_rows = refreshed
        self._rows = self._filtered_rows()
        self.endResetModel()
        self.rowsReloaded.emit(len(self._rows))
        return len(self._rows)

    def set_cover_source(self, work_id, remote_source, local_source):
        changed = False
        for row in self._all_rows:
            if row["coverCacheWorkId"] == work_id and row["coverSource"] == remote_source:
                row["coverSource"] = local_source
                changed = True
        if not changed:
            return
        for index, row in enumerate(self._rows):
            if row["coverCacheWorkId"] == work_id and row["coverSource"] == local_source:
                model_index = self.index(index, 0)
                self.dataChanged.emit(model_index, model_index, [self.CoverSourceRole])


class QmlApplicationBridge(QObject):
    """Small, typed interface between the QML Library and existing Python pages."""

    openWorkRequested = Signal(int)
    editBundleRequested = Signal(int)
    deleteWorkRequested = Signal(int)
    libraryChanged = Signal(int)
    filterChanged = Signal(str)
    errorOccurred = Signal(str)
    themeChanged = Signal()

    def __init__(self, parent=None, library_loader=None, auto_refresh=True):
        super().__init__(parent)
        self._library_model = LibraryListModel(library_loader=library_loader, parent=self)
        self._library_model.rowsReloaded.connect(self.libraryChanged)
        self._cover_network = None
        self._cover_urls_inflight = set()
        self._cover_waiters = {}
        self._cover_cache_paths = {}
        self._theme_values = {}
        self._sync_theme_values()
        if auto_refresh:
            self.refreshLibrary()

    @Property(QObject, constant=True)
    def libraryModel(self):
        return self._library_model

    @Property(int, notify=libraryChanged)
    def visibleCount(self):
        return self._library_model.rowCount()

    @Property(str, notify=filterChanged)
    def libraryFilter(self):
        return self._library_model._filter

    @Property(str, notify=themeChanged)
    def primaryColor(self):
        return self._theme_values["primaryColor"]

    @Property(str, notify=themeChanged)
    def secondaryColor(self):
        return self._theme_values["secondaryColor"]

    @Property(str, notify=themeChanged)
    def mutedColor(self):
        return self._theme_values["mutedColor"]

    @Property(str, notify=themeChanged)
    def frameColor(self):
        return self._theme_values["frameColor"]

    @Property(str, notify=themeChanged)
    def surfaceColor(self):
        return self._theme_values["surfaceColor"]

    @Property(str, notify=themeChanged)
    def surfaceHoverColor(self):
        return self._theme_values["surfaceHoverColor"]

    @Property(str, notify=themeChanged)
    def accentColor(self):
        return self._theme_values["accentColor"]

    @Property(str, notify=themeChanged)
    def accentSoftColor(self):
        return self._theme_values["accentSoftColor"]

    @Property(str, notify=themeChanged)
    def selectedTextColor(self):
        return self._theme_values["selectedTextColor"]

    @Property(str, notify=themeChanged)
    def selectedFrameColor(self):
        return self._theme_values["selectedFrameColor"]

    @Property(int, notify=themeChanged)
    def cardSize(self):
        return self._theme_values["cardSize"]

    @Property(int, notify=themeChanged)
    def cardGap(self):
        return self._theme_values["cardGap"]

    @Property(int, notify=themeChanged)
    def cornerRadius(self):
        return self._theme_values["cornerRadius"]

    @Property(int, notify=themeChanged)
    def fontSize(self):
        return self._theme_values["fontSize"]

    @Property(bool, notify=themeChanged)
    def hoverHighlight(self):
        return self._theme_values["hoverHighlight"]

    def _sync_theme_values(self):
        self._theme_values = {
            "primaryColor": COLORS.get("primary", "#f4f0fa"),
            "secondaryColor": COLORS.get("secondary", "#c8bdcf"),
            "mutedColor": COLORS.get("muted", "#93899d"),
            "frameColor": COLORS.get("frame", "#51475f"),
            "surfaceColor": COLORS.get("surface", "#26212e"),
            "surfaceHoverColor": COLORS.get("surface_hover", "#342b40"),
            "accentColor": COLORS.get("accent", "#9271c5"),
            "accentSoftColor": COLORS.get("accent_soft", "#3b304b"),
            "selectedTextColor": COLORS.get("nav_selected_text", "#ede5ff"),
            "selectedFrameColor": COLORS.get("nav_selected_frame", "#9271c5"),
            # Match WorkCard: preserve its 80..270 poster-width clamp.
            "cardSize": min(270, max(80, int(get("card_size")))),
            "cardGap": max(0, min(120, int(get("card_gap")))),
            "cornerRadius": max(0, min(64, int(get("corner_radius")))),
            "fontSize": max(8, min(36, int(get("font_size")))),
            "coverHeight": round(min(270, max(80, int(get("card_size")))) * 284 / 210),
            "titleHeight": QFontMetrics(
                QFont("Segoe UI", max(8, int(get("font_size") or 13)))
            ).lineSpacing() * 2,
            "seriesHeight": QFontMetrics(QFont("Segoe UI", 10)).height(),
            "metadataHeight": self._metadata_height(),
            "hoverHighlight": bool(get("hover_highlight")),
        }

    @staticmethod
    def _metadata_height():
        font = QFont("Segoe UI")
        font.setPixelSize(11)
        return QFontMetrics(font).height()

    @Property(int, notify=themeChanged)
    def coverHeight(self):
        return self._theme_values["coverHeight"]

    @Property(int, notify=themeChanged)
    def titleHeight(self):
        return self._theme_values["titleHeight"]

    @Property(int, notify=themeChanged)
    def seriesHeight(self):
        return self._theme_values["seriesHeight"]

    @Property(int, notify=themeChanged)
    def metadataHeight(self):
        return self._theme_values["metadataHeight"]

    @Slot()
    def refreshTheme(self):
        self._sync_theme_values()
        self.themeChanged.emit()

    @Slot(str)
    def setLibraryFilter(self, value):
        normalized = str(value or "All")
        if normalized not in _FILTERS or normalized == self._library_model._filter:
            return
        if self._library_model.set_filter(normalized):
            self.filterChanged.emit(normalized)
            log_event("qml_bridge.library_filter_changed", status_filter=normalized)

    @Slot(result=int)
    def refreshLibrary(self):
        try:
            count = self._library_model.refresh()
        except Exception as error:
            log_exception("qml_bridge.library_refresh_failed", error)
            self.errorOccurred.emit("NekoTrack could not refresh the Library. Check the diagnostic log.")
            return -1
        log_event("qml_bridge.library_refreshed", item_count=count)
        return count

    @Slot(int, result=bool)
    def requestOpenWork(self, work_id):
        normalized_id = _optional_int(work_id)
        if normalized_id is None or normalized_id == 0:
            return False
        self.openWorkRequested.emit(normalized_id)
        return True

    @Slot(int)
    def requestEditBundle(self, work_id):
        normalized_id = _optional_int(work_id)
        if normalized_id is not None and normalized_id != 0:
            self.editBundleRequested.emit(normalized_id)

    @Slot(int)
    def requestDeleteWork(self, work_id):
        normalized_id = _optional_int(work_id)
        if normalized_id is not None and normalized_id != 0:
            self.deleteWorkRequested.emit(normalized_id)

    @Slot(int, str)
    def requestCoverCache(self, work_id, raw_url):
        """Persist remote poster art through the existing cover-path database field."""
        normalized_id = _optional_int(work_id)
        url = _remote_image_url(raw_url)
        if normalized_id is None or normalized_id == 0 or not url:
            return
        if url in self._cover_cache_paths:
            self._save_cached_cover(normalized_id, url, self._cover_cache_paths[url])
            return
        self._cover_waiters.setdefault(url, set()).add(normalized_id)
        if url in self._cover_urls_inflight:
            return
        self._cover_urls_inflight.add(url)
        if self._cover_network is None:
            self._cover_network = QNetworkAccessManager(self)
        reply = self._cover_network.get(QNetworkRequest(QUrl(url)))
        reply.finished.connect(
            lambda current=reply, source=url: self._cover_download_finished(current, source)
        )

    def _cover_download_finished(self, reply, url):
        self._cover_urls_inflight.discard(url)
        work_ids = sorted(self._cover_waiters.pop(url, set()))
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                log_event("qml_bridge.cover_cache_failed", url_host=QUrl(url).host(),
                          network_error=int(reply.error()))
                return
            pixmap = QPixmap()
            if not pixmap.loadFromData(reply.readAll()):
                log_event("qml_bridge.cover_cache_decode_failed", url_host=QUrl(url).host())
                return
            _IMAGE_DIRECTORY.mkdir(parents=True, exist_ok=True)
            first_saved_path = None
            for work_id in work_ids:
                path = _IMAGE_DIRECTORY / f"{work_id}.jpg"
                if pixmap.save(str(path), "JPG", 85):
                    save_cover_path(work_id, str(path))
                    self._library_model.set_cover_source(
                        work_id, url, QUrl.fromLocalFile(str(path.resolve())).toString()
                    )
                    if first_saved_path is None:
                        first_saved_path = path
            if first_saved_path is not None:
                self._cover_cache_paths[url] = first_saved_path
        except Exception as error:
            log_exception("qml_bridge.cover_cache_failed", error, url_host=QUrl(url).host())
        finally:
            reply.deleteLater()

    def _save_cached_cover(self, work_id, url, source_path):
        try:
            source = Path(source_path)
            if not source.is_file():
                self._cover_cache_paths.pop(url, None)
                return
            _IMAGE_DIRECTORY.mkdir(parents=True, exist_ok=True)
            destination = _IMAGE_DIRECTORY / f"{work_id}.jpg"
            if source.resolve() != destination.resolve():
                shutil.copy2(source, destination)
            save_cover_path(work_id, str(destination))
            self._library_model.set_cover_source(
                work_id, url, QUrl.fromLocalFile(str(destination.resolve())).toString()
            )
        except Exception as error:
            log_exception("qml_bridge.cover_cache_failed", error, work_id=work_id)
