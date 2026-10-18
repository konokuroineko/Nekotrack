"""A responsive, data-driven home dashboard for NekoTrack."""

import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from database import (
    get_all_library,
    get_episodes,
    get_release_reminders,
    set_release_reminder,
)
from diagnostics import log_exception
from ui.preferences import get
from ui.theme import COLORS, surface_rgba
from ui.widgets.work_card import WorkCard
from ui.pages.recommendations_page import RecommendationsPage
from series import get_library_series


class HomePage(QWidget):
    """Home dashboard backed by saved library records and real read/watch progress."""

    work_selected = Signal(object)
    calendar_requested = Signal()

    def __init__(self, add_callback=None):
        super().__init__()
        self.setObjectName("homePage")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("homeScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.content = QWidget()
        self.content.setObjectName("homeContent")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(18, 18, 18, 20)
        self.content_layout.setSpacing(12)
        self.scroll_area.setWidget(self.content)
        outer.addWidget(self.scroll_area)

        self.recommendations_page = RecommendationsPage(add_callback, embedded=True)
        self.recommendations_page.set_visibility_viewport(
            self.scroll_area.viewport(), self.scroll_area.verticalScrollBar()
        )
        self._apply_theme_styles()
        self.refresh()

    def _prepare_home_work(self, group):
        """Copy a library bundle while preserving its user-selected presentation."""
        work = dict(group)
        members = work.get("_series_members")
        members = members if isinstance(members, list) and members else [group]
        work["_series_members"] = members
        if len(members) > 1:
            for target, source in (
                ("progress_episodes", "progress_episodes"),
                ("episodes", "episodes"),
                ("progress_chapters", "progress_chapters"),
                ("chapters", "chapters"),
                ("progress_volumes", "progress_volumes"),
                ("volumes", "volumes"),
            ):
                work[target] = sum(
                    max(0, self._integer(member.get(source)))
                    for member in members
                    if isinstance(member, dict)
                )
        statuses = [
            self._status(member) for member in members
            if isinstance(member, dict)
        ]
        if any(status in {"watching", "rewatching"} for status in statuses):
            work["_home_status"] = (
                "rewatching" if "rewatching" in statuses else "watching"
            )
        elif "reading" in statuses:
            work["_home_status"] = "reading"
        else:
            work["_home_status"] = self._status(work)
        return work

    @staticmethod
    def _integer(value, default=0):
        try:
            return int(value or 0)
        except (TypeError, ValueError, OverflowError):
            return default

    @staticmethod
    def _status(work):
        return str(work.get("status") or "").strip().casefold()

    @classmethod
    def _progress_caption(cls, work):
        media_type = str(work.get("type") or "").strip().upper()
        status = cls._status(work)
        if media_type == "ANIME" or status in {"watching", "rewatching"}:
            progress = max(0, cls._integer(work.get("progress_episodes")))
            total = max(0, cls._integer(work.get("episodes")))
            next_episode = progress + 1
            if total:
                if progress >= total:
                    return f"Episode progress: {progress}/{total}"
                return f"Next episode {next_episode} · {progress}/{total} logged"
            return f"Next episode {next_episode} · total unknown"

        chapter_progress = max(0, cls._integer(work.get("progress_chapters")))
        chapter_total = max(0, cls._integer(work.get("chapters")))
        volume_progress = max(0, cls._integer(work.get("progress_volumes")))
        volume_total = max(0, cls._integer(work.get("volumes")))
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

    def _read_library(self):
        try:
            rows = get_all_library() or []
            return [dict(row) for row in rows]
        except Exception as error:
            log_exception("home.library_load_failed", error)
            return []

    def refresh(self):
        # Preserve the embedded recommendations widget while rebuilding the
        # local library sections. It may own an active QThread.
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                if widget is not self.recommendations_page:
                    widget.deleteLater()

        library = self._read_library()
        statuses = [self._status(work) for work in library]
        self._home_counts = {
            "all": len(library),
            "in_progress": sum(
                status in {"watching", "rewatching", "reading", "in progress"}
                for status in statuses
            ),
            "completed": sum(status == "completed" for status in statuses),
            "planned": sum(
                status in {"planning", "plan to watch", "plan to read"}
                for status in statuses
            ),
        }
        try:
            # Use exactly the Library's saved automatic/manual bundles,
            # exclusions, custom titles, and cover choices for Home too.
            display_library = get_library_series(library)
        except Exception as error:
            log_exception("home.bundle_grouping_failed", error)
            display_library = library

        continue_items = []
        recent_items = []
        in_progress_statuses = {"watching", "rewatching", "reading", "in progress"}
        for group in display_library:
            work = self._prepare_home_work(group)
            recent_items.append(work)
            members = group.get("_series_members") if isinstance(group, dict) else None
            members = members if isinstance(members, list) and members else [group]
            if any(self._status(member) in in_progress_statuses for member in members):
                continue_items.append(work)

        self._continue_ids = {
            self._integer(work.get("id")) for work in continue_items
        }
        self._recent_ids = [
            self._integer(work.get("id")) for work in recent_items[:4]
        ]

        self.content_layout.addWidget(
            self._work_section(
                "Continue watching or reading",
                "Pick up from your locally saved progress.",
                continue_items[:4],
                kind="continue",
            )
        )
        self.content_layout.addWidget(
            self._work_section(
                "Recently added",
                "Your latest additions, in the order recorded by your library.",
                recent_items[:4],
                kind="recent",
            )
        )
        self.content_layout.addWidget(
            self._release_section(self._upcoming_release_rows(library))
        )
        # Reuse the already-loaded local rows instead of querying SQLite a
        # second time just to seed recommendations.
        self.content_layout.addWidget(self.recommendations_page)
        # A new Home visit starts a new recommendation cycle. Feedback and
        # exposure history are loaded by the worker, and the discovery sort
        # rotates so the same first page is not shown forever.
        self.recommendations_page.refresh(force=True, library_rows=library)
        self.content_layout.addStretch(1)
        self._apply_theme_styles()

    @staticmethod
    def _parse_air_date(value):
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            return datetime.date.fromisoformat(value[:10])
        except (TypeError, ValueError):
            return None

    def _upcoming_release_rows(self, library, today=None):
        """Build a small Home preview from cached episode dates only."""
        today = today or datetime.date.today()
        last_date = today + datetime.timedelta(days=60)

        reminders = set()
        try:
            for reminder in get_release_reminders() or []:
                try:
                    reminders.add((
                        int(reminder["work_id"]),
                        int(reminder["episode_number"]),
                    ))
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
        except Exception as error:
            log_exception("home.release_reminders_load_failed", error)

        events = []
        for work in library:
            if str(work.get("type") or "").strip().upper() != "ANIME":
                continue
            work_id = self._integer(work.get("id"))
            if work_id <= 0:
                continue

            try:
                episodes = get_episodes(work_id) or []
            except Exception as error:
                log_exception("home.release_episodes_load_failed", error, work_id=work_id)
                continue

            for episode in episodes:
                row = dict(episode)
                air_date = self._parse_air_date(row.get("air_date"))
                if air_date is None or air_date < today or air_date > last_date:
                    continue
                episode_number = self._integer(row.get("episode_number"))
                episode_title = row.get("title")
                if not isinstance(episode_title, str):
                    episode_title = ""
                episode_title = episode_title.strip()
                if not episode_title or episode_title.casefold().startswith("episode "):
                    episode_title = f"Episode {episode_number}"

                events.append({
                    "work_id": work_id,
                    "work_title": str(work.get("title") or f"Untitled · {work_id}"),
                    "episode_number": episode_number,
                    "episode_title": episode_title,
                    "_release_date": air_date,
                    "_reminder_enabled": (work_id, episode_number) in reminders,
                })

        events.sort(key=lambda row: (
            row["_release_date"],
            str(row.get("work_title") or "").casefold(),
            row["episode_number"],
        ))
        return events

    def _release_section(self, events):
        section = QFrame()
        section.setObjectName("homeSection")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)

        header = QHBoxLayout()
        text_column = QVBoxLayout()
        text_column.setSpacing(4)
        title = QLabel("Upcoming releases")
        title.setObjectName("homeSectionTitle")
        subtitle = QLabel(
            "Cached episode dates for the next 60 days. Reminders notify while NekoTrack is running."
        )
        subtitle.setObjectName("homeSectionSubtitle")
        subtitle.setWordWrap(True)
        text_column.addWidget(title)
        text_column.addWidget(subtitle)
        header.addLayout(text_column, 1)

        open_calendar = QPushButton("Open calendar")
        open_calendar.setObjectName("homeCalendarAction")
        open_calendar.setCursor(Qt.CursorShape.PointingHandCursor)
        open_calendar.clicked.connect(self.calendar_requested.emit)
        header.addWidget(open_calendar, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(header)

        if not events:
            empty = QFrame()
            empty.setObjectName("homeSectionEmpty")
            empty_layout = QVBoxLayout(empty)
            empty_layout.setContentsMargins(16, 14, 16, 14)
            empty_layout.setSpacing(5)
            message = QLabel("No upcoming episode dates cached")
            message.setObjectName("homeEmptyState")
            hint = QLabel(
                "This preview uses saved episode schedules and won't guess release dates. "
                "Check the calendar for the full view."
            )
            hint.setObjectName("homeEmptyHint")
            hint.setWordWrap(True)
            empty_layout.addWidget(message)
            empty_layout.addWidget(hint)
            layout.addWidget(empty)
            return section

        count = QLabel(
            f"{len(events)} upcoming episode{'s' if len(events) != 1 else ''} · next 60 days"
        )
        count.setObjectName("homeReleaseCount")
        layout.addWidget(count)

        for row in events[:3]:
            layout.addWidget(self._release_event_card(row))
        if len(events) > 3:
            more = QLabel(f"{len(events) - 3} more release dates in Calendar")
            more.setObjectName("homeReleaseMore")
            layout.addWidget(more)
        return section

    def _release_event_card(self, row):
        card = QFrame()
        card.setObjectName("homeReleaseEvent")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(8)

        release_date = row["_release_date"]
        date_badge = QFrame()
        date_badge.setObjectName("homeReleaseDateBadge")
        badge_layout = QVBoxLayout(date_badge)
        badge_layout.setContentsMargins(6, 2, 6, 2)
        badge_layout.setSpacing(0)
        month = QLabel(release_date.strftime("%b").upper())
        month.setObjectName("homeReleaseMonth")
        day = QLabel(str(release_date.day))
        day.setObjectName("homeReleaseDay")
        badge_layout.addWidget(month, 0, Qt.AlignmentFlag.AlignHCenter)
        badge_layout.addWidget(day, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(date_badge)

        description = QVBoxLayout()
        description.setSpacing(1)
        work_title = str(row.get("work_title") or "Untitled")
        episode_title = str(row.get("episode_title") or f"Episode {row.get('episode_number', 0)}")
        label = QLabel(f"{work_title} · {episode_title}")
        label.setObjectName("homeReleaseWorkTitle")
        label.setWordWrap(False)
        label.setMinimumWidth(0)
        label.setMaximumHeight(22)
        label.setToolTip(f"{work_title} · {episode_title}")
        episode_date = QLabel(release_date.strftime("%a, %b %d"))
        episode_date.setObjectName("homeReleaseDate")
        description.addWidget(label)
        description.addWidget(episode_date)
        layout.addLayout(description, 1)

        work_id = int(row["work_id"])
        episode_number = int(row["episode_number"])
        reminder_enabled = bool(row.get("_reminder_enabled"))
        reminder = QPushButton("On" if reminder_enabled else "Remind")
        reminder.setObjectName(
            "homeReminderActive" if reminder_enabled else "homeReminderToggle"
        )
        reminder.setCursor(Qt.CursorShape.PointingHandCursor)
        reminder.setAccessibleName(
            "Disable episode reminder" if reminder_enabled else "Enable episode reminder"
        )
        reminder.setToolTip(
            "Disable this episode reminder" if reminder_enabled else "Remind me about this episode"
        )
        reminder.clicked.connect(
            lambda _=False, wid=work_id, number=episode_number, current=reminder_enabled:
                self._toggle_release_reminder(wid, number, not current)
        )
        layout.addWidget(reminder, 0, Qt.AlignmentFlag.AlignVCenter)
        return card

    def _toggle_release_reminder(self, work_id, episode_number, enabled):
        try:
            set_release_reminder(work_id, episode_number, enabled)
        except Exception as error:
            log_exception(
                "home.release_reminder_save_failed",
                error,
                work_id=work_id,
                episode_number=episode_number,
            )
            return
        self.refresh()

    def _work_section(self, title, description, works, kind):
        section = QFrame()
        section.setObjectName("homeSection")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(7)

        header = QVBoxLayout()
        header.setSpacing(4)
        heading = QLabel(title)
        heading.setObjectName("homeSectionTitle")
        detail = QLabel(description)
        detail.setObjectName("homeSectionSubtitle")
        detail.setWordWrap(True)
        header.addWidget(heading)
        header.addWidget(detail)
        layout.addLayout(header)

        if not works:
            empty = QFrame()
            empty.setObjectName("homeSectionEmpty")
            empty.setMinimumHeight(64)
            empty_layout = QVBoxLayout(empty)
            empty_layout.setContentsMargins(11, 10, 11, 10)
            empty_layout.setSpacing(5)
            message = QLabel(
                "Nothing in progress yet"
                if kind == "continue" else "Nothing has been added yet"
            )
            message.setObjectName("homeEmptyState")
            hint = QLabel(
                "Add a title to your library, then your saved progress will appear here."
                if kind == "continue" else
                "Use Search to find a title and add it to your collection."
            )
            hint.setObjectName("homeEmptyHint")
            hint.setWordWrap(True)
            empty_layout.addWidget(message)
            empty_layout.addWidget(hint)
            layout.addWidget(empty)
            return section

        strip = QWidget()
        strip.setObjectName("homeTrackStrip")
        strip.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        strip_layout = QHBoxLayout(strip)
        strip_layout.setContentsMargins(3, 2, 6, 2)
        strip_layout.setSpacing(10)
        for work in works:
            tile = QWidget(strip)
            tile.setObjectName("homeTrackTile")
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(0, 0, 0, 0)
            tile_layout.setSpacing(3)
            home_card_size = min(112, max(88, round(self._integer(get("card_size"), 210) * 0.45)))
            card = WorkCard(work, mode="library", parent=tile, card_size_override=home_card_size)
            card.setToolTip("Open details to update your progress")
            card.clicked.connect(self.work_selected.emit)
            tile_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)

            status_text = (
                str(work.get("_home_status") or self._status(work)).replace("_", " ").upper()
                if kind == "continue" else "IN YOUR LIBRARY"
            )
            status = QLabel(status_text)
            status.setObjectName("homeTrackStatus")
            status.setAlignment(Qt.AlignmentFlag.AlignLeft)
            status.setFixedHeight(12)
            if kind == "continue":
                caption_text = self._progress_caption(work)
            else:
                caption_text = f"Status: {work.get('status') or 'Unknown'}"
            caption = QLabel(caption_text)
            caption.setObjectName("homeTrackProgress")
            caption.setWordWrap(True)
            caption.setFixedHeight(16)
            caption.setToolTip(caption_text)
            tile_layout.addWidget(status)
            tile_layout.addWidget(caption)
            strip_layout.addWidget(tile, 0, Qt.AlignmentFlag.AlignTop)

        strip_layout.addStretch(1)
        strip.adjustSize()
        scroll = QScrollArea()
        scroll.setObjectName("homeWorkScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(False)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        cover_height = round(home_card_size * 284 / 210)
        scroll.setFixedHeight(cover_height + 82)
        scroll.setWidget(strip)
        layout.addWidget(scroll)
        return section

    def _apply_theme_styles(self):
        self.setStyleSheet(f"""
            QWidget#homePage, QWidget#homeContent {{
                background: transparent;
            }}
            QScrollArea#homeScrollArea, QScrollArea#homeWorkScroll {{
                background: transparent;
                border: none;
            }}
            QFrame#homeSection {{
                background: {surface_rgba('surface')};
                border: 1px solid {COLORS['frame']};
                border-radius: 16px;
            }}
            QLabel#homeSectionTitle {{
                color: {COLORS['primary']};
                background: transparent;
                font-size: 16px;
                font-weight: 850;
            }}
            QLabel#homeSectionSubtitle {{
                color: {COLORS['muted']};
                background: transparent;
                font-size: 11px;
            }}
            QFrame#homeSectionEmpty {{
                background: {surface_rgba('surface_alt')};
                border: 1px dashed {COLORS['border']};
                border-radius: 11px;
            }}
            QLabel#homeEmptyState {{
                color: {COLORS['primary']};
                background: transparent;
                font-size: 13px;
                font-weight: 800;
            }}
            QLabel#homeEmptyHint {{
                color: {COLORS['muted']};
                background: transparent;
                font-size: 11px;
            }}
            QWidget#homeTrackTile {{ background: transparent; }}
            QLabel#homeTrackStatus {{
                color: {COLORS['accent']};
                background: transparent;
                font-size: 9px;
                font-weight: 900;
                letter-spacing: 1px;
            }}
            QLabel#homeTrackProgress {{
                color: {COLORS['secondary']};
                background: transparent;
                font-size: 10px;
                min-height: 28px;
                max-width: 218px;
            }}
            QFrame#homeReleaseEvent {{
                background: {surface_rgba('surface_alt')};
                border: 1px solid {COLORS['border']};
                border-radius: 11px;
            }}
            QFrame#homeReleaseDateBadge {{
                background: {surface_rgba('accent_soft')};
                border: 1px solid {COLORS['border_hover']};
                border-radius: 9px;
                min-width: 48px;
                max-width: 48px;
            }}
            QLabel#homeReleaseMonth {{
                color: {COLORS['accent']};
                background: transparent;
                font-size: 9px;
                font-weight: 900;
            }}
            QLabel#homeReleaseDay {{
                color: {COLORS['primary']};
                background: transparent;
                font-size: 21px;
                font-weight: 900;
            }}
            QLabel#homeReleaseWorkTitle {{
                color: {COLORS['primary']};
                background: transparent;
                font-size: 12px;
                font-weight: 800;
            }}
            QLabel#homeReleaseEpisodeTitle, QLabel#homeReleaseDate,
            QLabel#homeReleaseCount, QLabel#homeReleaseMore {{
                color: {COLORS['secondary']};
                background: transparent;
                font-size: 10px;
            }}
            QPushButton#homeCalendarAction, QPushButton#homeReminderToggle,
            QPushButton#homeReminderActive {{
                background: {surface_rgba('surface_alt')};
                color: {COLORS['primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                padding: 8px 11px;
                font-size: 10px;
                font-weight: 800;
            }}
            QPushButton#homeCalendarAction:hover, QPushButton#homeReminderToggle:hover,
            QPushButton#homeReminderActive:hover {{
                background: {surface_rgba('accent_soft')};
                border-color: {COLORS['accent']};
            }}
            QPushButton#homeReminderActive {{ color: {COLORS['accent']}; }}
        """)
        for card in self.findChildren(WorkCard):
            card.refresh_theme()

    def refresh_theme(self):
        self._apply_theme_styles()
