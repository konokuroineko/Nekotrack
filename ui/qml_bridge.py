"""Narrow, read-only Python model adapters for the staged QML migration.

The shipped UI still uses Qt Widgets. This module deliberately exposes existing
Library grouping as Qt model roles; it does not duplicate grouping, provider, or
SQLite behavior in QML.
"""
from pathlib import Path

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    Property,
    QUrl,
    Qt,
    Signal,
    Slot,
)

from diagnostics import log_event, log_exception
from series import get_library_series


def _optional_int(value):
    """Convert a legitimate integer-like value without accepting booleans."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            return None
        return int(value)
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


def _display_title(value):
    if isinstance(value, dict):
        for key in ("english", "romaji", "native"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return ""
    return value.strip() if isinstance(value, str) else ""


def _row_dict(value):
    try:
        return dict(value)
    except (TypeError, ValueError):
        return None


def _member_rows(group, work_id):
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
        seen = {work_id}

    return members, sorted(seen)


def _local_or_remote_cover(group):
    """Return an image source QML can load, preferring a real cached file."""
    raw_path = group.get("cover_path") or group.get("image_path")
    if isinstance(raw_path, str) and raw_path.strip():
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        try:
            if candidate.is_file():
                return QUrl.fromLocalFile(str(candidate.resolve())).toString()
        except (OSError, RuntimeError):
            pass

    raw_url = group.get("cover_url") or group.get("image_url")
    if not raw_url:
        cover_image = group.get("coverImage")
        if isinstance(cover_image, dict):
            raw_url = cover_image.get("extraLarge") or cover_image.get("large")
    if not isinstance(raw_url, str):
        return ""

    url = QUrl(raw_url.strip())
    if url.scheme().casefold() not in {"http", "https"} or not url.isValid():
        return ""
    return url.toString()


def _normalize_group(raw_group):
    group = _row_dict(raw_group)
    if group is None:
        return None

    work_id = _optional_int(group.get("id"))
    if work_id is None or work_id == 0:
        return None

    members, member_ids = _member_rows(group, work_id)
    start_year = _optional_int(group.get("start_year"))
    if start_year is None:
        start_date = group.get("startDate")
        if isinstance(start_date, dict):
            start_year = _optional_int(start_date.get("year"))

    series_count = _count(group.get("_series_count")) or len(member_ids)
    episode_total = _count(group.get("_series_episode_total"))
    if "_series_episode_total" not in group:
        episode_total = sum(_count(member.get("episodes")) for member in members)

    episode_progress = _count(group.get("_series_progress"))
    if "_series_progress" not in group:
        episode_progress = sum(
            _count(member.get("progress_episodes")) for member in members
        )

    return {
        "workId": work_id,
        "title": _display_title(group.get("title")) or "Untitled",
        "mediaType": str(group.get("type") or "UNKNOWN").upper(),
        "format": str(group.get("format") or "").upper(),
        "startYear": start_year or 0,
        "coverSource": _local_or_remote_cover(group),
        "status": str(group.get("status") or "Planning"),
        "progressEpisodes": episode_progress,
        "episodeTotal": episode_total,
        "progressChapters": sum(
            _count(member.get("progress_chapters")) for member in members
        ),
        "progressVolumes": sum(
            _count(member.get("progress_volumes")) for member in members
        ),
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
    StatusRole = CoverSourceRole + 1
    ProgressEpisodesRole = StatusRole + 1
    EpisodeTotalRole = ProgressEpisodesRole + 1
    ProgressChaptersRole = EpisodeTotalRole + 1
    ProgressVolumesRole = ProgressChaptersRole + 1
    SeriesCountRole = ProgressVolumesRole + 1
    BundleSummaryRole = SeriesCountRole + 1
    MemberIdsRole = BundleSummaryRole + 1

    _ROLE_NAMES = {
        WorkIdRole: b"workId",
        TitleRole: b"title",
        MediaTypeRole: b"mediaType",
        FormatRole: b"format",
        StartYearRole: b"startYear",
        CoverSourceRole: b"coverSource",
        StatusRole: b"status",
        ProgressEpisodesRole: b"progressEpisodes",
        EpisodeTotalRole: b"episodeTotal",
        ProgressChaptersRole: b"progressChapters",
        ProgressVolumesRole: b"progressVolumes",
        SeriesCountRole: b"seriesCount",
        BundleSummaryRole: b"bundleSummary",
        MemberIdsRole: b"memberIds",
    }

    rowsReloaded = Signal(int)

    def __init__(self, library_loader=None, parent=None):
        super().__init__(parent)
        self._library_loader = library_loader or get_library_series
        self._rows = []

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._rows)

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
        if role_name is None:
            return None
        return row.get(role_name.decode("ascii"))

    def refresh(self):
        """Reload canonical groups, preserving the existing ordering and bundling."""
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
        self._rows = refreshed
        self.endResetModel()
        self.rowsReloaded.emit(len(refreshed))
        return len(refreshed)


class QmlApplicationBridge(QObject):
    """Stable hand-off between QML views and the existing Python application."""

    openWorkRequested = Signal(int)
    libraryChanged = Signal(int)
    errorOccurred = Signal(str)

    def __init__(self, parent=None, library_loader=None, auto_refresh=True):
        super().__init__(parent)
        self._library_model = LibraryListModel(
            library_loader=library_loader,
            parent=self,
        )
        self._library_model.rowsReloaded.connect(self.libraryChanged)
        if auto_refresh:
            self.refreshLibrary()

    @Property(QObject, constant=True)
    def libraryModel(self):
        return self._library_model

    @Slot(result=int)
    def refreshLibrary(self):
        try:
            count = self._library_model.refresh()
        except Exception as error:
            log_exception("qml_bridge.library_refresh_failed", error)
            self.errorOccurred.emit(
                "NekoTrack could not refresh the Library. Check the diagnostic log."
            )
            return -1

        log_event("qml_bridge.library_refreshed", item_count=count)
        return count

    @Slot(int, result=bool)
    def requestOpenWork(self, work_id):
        """Ask the existing application shell to open a Library item."""
        normalized_id = _optional_int(work_id)
        if normalized_id is None or normalized_id == 0:
            return False
        self.openWorkRequested.emit(normalized_id)
        return True
