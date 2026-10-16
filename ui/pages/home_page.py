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
from ui.theme import COLORS
from ui.widgets.work_card import WorkCard
from ui.pages.recommendations_page import RecommendationsPage


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
        self.content_layout.setContentsMargins(34, 30, 34, 34)
        self.content_layout.setSpacing(22)
        self.scroll_area.setWidget(self.content)
        outer.addWidget(self.scroll_area)

        self.recommendations_page = RecommendationsPage(add_callback, embedded=True)
        self.recommendations_page.set_visibility_viewport(
            self.scroll_area.viewport(), self.scroll_area.verticalScrollBar()
        )
        self._apply_theme_styles()
        self.refresh()

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
        continue_items = [
            work for work in library
            if self._status(work) in {"watching", "rewatching", "reading", "in progress"}
        ]
        self._continue_ids = {self._integer(work.get("id")) for work in continue_items}
        self._recent_ids = [self._integer(work.get("id")) for work in library[:5]]

        self.content_layout.addWidget(
            self._work_section(
                "Continue watching or reading",
                "Pick up from your locally saved progress.",
                continue_items[:8],
                kind="continue",
            )
        )
        self.content_layout.addWidget(
            self._work_section(
                "Recently added",
                "Your latest additions, in the order recorded by your library.",
                library[:5],
                kind="recent",
            )
        )
        self.content_layout.addWidget(
            self._release_section(self._upcoming_release_rows(library))
        )
        # Reuse the already-loaded local rows instead of querying SQLite a
        # second time just to seed recommendations.
        self.content_layout.addWidget(self.recommendations_page)
        self.recommendations_page.refresh(library_rows=library)
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
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(10)

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

        for row in events[:5]:
            layout.addWidget(self._release_event_card(row))
        if len(events) > 5:
            more = QLabel(f"{len(events) - 5} more release dates in Calendar")
            more.setObjectName("homeReleaseMore")
            layout.addWidget(more)
        return section

    def _release_event_card(self, row):
        card = QFrame()
        card.setObjectName("homeReleaseEvent")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        release_date = row["_release_date"]
        date_badge = QFrame()
        date_badge.setObjectName("homeReleaseDateBadge")
        badge_layout = QVBoxLayout(date_badge)
        badge_layout.setContentsMargins(9, 5, 9, 5)
        badge_layout.setSpacing(0)
        month = QLabel(release_date.strftime("%b").upper())
        month.setObjectName("homeReleaseMonth")
        day = QLabel(str(release_date.day))
        day.setObjectName("homeReleaseDay")
        badge_layout.addWidget(month, 0, Qt.AlignmentFlag.AlignHCenter)
        badge_layout.addWidget(day, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(date_badge)

        description = QVBoxLayout()
        description.setSpacing(3)
        work_title = QLabel(str(row.get("work_title") or "Untitled"))
        work_title.setObjectName("homeReleaseWorkTitle")
        work_title.setWordWrap(True)
        episode_title = QLabel(str(row.get("episode_title") or f"Episode {row.get('episode_number', 0)}"))
        episode_title.setObjectName("homeReleaseEpisodeTitle")
        episode_date = QLabel(release_date.strftime("%A, %B %d"))
        episode_date.setObjectName("homeReleaseDate")
        description.addWidget(work_title)
        description.addWidget(episode_title)
        description.addWidget(episode_date)
        layout.addLayout(description, 1)

        work_id = int(row["work_id"])
        episode_number = int(row["episode_number"])
        reminder_enabled = bool(row.get("_reminder_enabled"))
        reminder = QPushButton("Reminder on" if reminder_enabled else "Remind me")
        reminder.setObjectName(
            "homeReminderActive" if reminder_enabled else "homeReminderToggle"
        )
        reminder.setCursor(Qt.CursorShape.PointingHandCursor)
        reminder.setAccessibleName(
            "Disable episode reminder" if reminder_enabled else "Enable episode reminder"
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
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(10)

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
            empty.setMinimumHeight(92)
            empty_layout = QVBoxLayout(empty)
            empty_layout.setContentsMargins(16, 16, 16, 16)
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
        strip_layout.setContentsMargins(4, 3, 8, 3)
        strip_layout.setSpacing(15)
        for work in works:
            tile = QWidget(strip)
            tile.setObjectName("homeTrackTile")
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(0, 0, 0, 0)
            tile_layout.setSpacing(7)
            card = WorkCard(work, mode="library", parent=tile)
            card.setToolTip("Open details to update your progress")
            card.clicked.connect(self.work_selected.emit)
            tile_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)

            status = QLabel(
                self._status(work).replace("_", " ").upper()
                if kind == "continue" else "IN YOUR LIBRARY"
            )
            status.setObjectName("homeTrackStatus")
            status.setAlignment(Qt.AlignmentFlag.AlignLeft)
            if kind == "continue":
                caption_text = self._progress_caption(work)
            else:
                caption_text = f"Status: {work.get('status') or 'Unknown'}"
            caption = QLabel(caption_text)
            caption.setObjectName("homeTrackProgress")
            caption.setWordWrap(True)
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
        cover_height = round(self._integer(get("card_size"), 210) * 284 / 210)
        scroll.setFixedHeight(cover_height + 172)
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
                background: {COLORS['surface']};
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
                background: {COLORS['surface_alt']};
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
                background: {COLORS['surface_alt']};
                border: 1px solid {COLORS['border']};
                border-radius: 11px;
            }}
            QFrame#homeReleaseDateBadge {{
                background: {COLORS['accent_soft']};
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
                background: {COLORS['surface_alt']};
                color: {COLORS['primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                padding: 8px 11px;
                font-size: 10px;
                font-weight: 800;
            }}
            QPushButton#homeCalendarAction:hover, QPushButton#homeReminderToggle:hover,
            QPushButton#homeReminderActive:hover {{
                background: {COLORS['accent_soft']};
                border-color: {COLORS['accent']};
            }}
            QPushButton#homeReminderActive {{ color: {COLORS['accent']}; }}
        """)
        for card in self.findChildren(WorkCard):
            card.refresh_theme()

    def refresh_theme(self):
        self._apply_theme_styles()
