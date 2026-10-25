"""Air-date calendar and persistent reminders for cached anime episodes."""

import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from database import get_release_reminders, get_upcoming_library_episodes, set_release_reminder
from diagnostics import log_exception
from ui.theme import COLORS, surface_rgba


class CalendarPage(QWidget):
    HORIZON_DAYS = 60

    def __init__(self):
        super().__init__()
        self.setObjectName("calendarPage")
        self._events = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("calendarScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setObjectName("calendarContent")
        self.layout = QVBoxLayout(self.content)
        self.layout.setContentsMargins(34, 28, 34, 34)
        self.layout.setSpacing(15)
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll)
        self.refresh()

    @staticmethod
    def _parse_date(value):
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            return datetime.date.fromisoformat(value[:10])
        except (TypeError, ValueError):
            return None

    def refresh(self):
        self._clear()
        heading = QFrame()
        heading.setObjectName("calendarHeader")
        header = QHBoxLayout(heading)
        header.setContentsMargins(22, 20, 22, 20)
        text_col = QVBoxLayout()
        text_col.setSpacing(5)
        title = QLabel("Release calendar")
        title.setObjectName("calendarTitle")
        subtitle = QLabel(
            "Upcoming episode dates from your cached schedule. Reminders notify once per release date while NekoTrack is running."
        )
        subtitle.setObjectName("calendarSubtitle")
        subtitle.setWordWrap(True)
        text_col.addWidget(title)
        text_col.addWidget(subtitle)
        header.addLayout(text_col, 1)
        refresh_button = QPushButton("Refresh")
        refresh_button.setObjectName("calendarAction")
        refresh_button.setToolTip("Re-read locally cached episode schedules")
        refresh_button.clicked.connect(self.refresh)
        header.addWidget(refresh_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.layout.addWidget(heading)

        today = datetime.date.today()
        last_date = today + datetime.timedelta(days=self.HORIZON_DAYS)
        events = []
        try:
            end_exclusive = last_date + datetime.timedelta(days=1)
            episode_rows = get_upcoming_library_episodes(
                today.isoformat(),
                end_exclusive.isoformat(),
            )
            for episode in episode_rows or []:
                row = dict(episode)
                air_date = self._parse_date(row.get("air_date"))
                if air_date is None or air_date < today or air_date > last_date:
                    continue
                work_id = int(row.get("work_id") or 0)
                row["work_title"] = row.get("work_title") or f"Untitled · {work_id}"
                row["cover_path"] = row.pop("work_cover_path", None)
                row["cover_url"] = row.pop("work_cover_url", None)
                row["_release_date"] = air_date
                row["_reminder_enabled"] = bool(row.pop("reminder_enabled", False))
                events.append(row)
        except Exception as error:
            log_exception("calendar.load_failed", error)

        events.sort(key=lambda row: (
            row["_release_date"], str(row.get("work_title") or "").casefold(),
            int(row.get("episode_number") or 0),
        ))
        self._events = events
        if not events:
            self._render_empty(today)
        else:
            counts = QLabel(f"{len(events)} upcoming episode{'s' if len(events) != 1 else ''} · next {self.HORIZON_DAYS} days")
            counts.setObjectName("calendarCount")
            self.layout.addWidget(counts)
            current_day = None
            for row in events:
                event_day = row["_release_date"]
                if event_day != current_day:
                    day_header = QLabel(event_day.strftime("%A · %B %d"))
                    day_header.setObjectName("calendarDayHeader")
                    self.layout.addWidget(day_header)
                    current_day = event_day
                self.layout.addWidget(self._event_card(row))
        self.layout.addStretch(1)
        self._apply_theme()

    def _render_empty(self, today):
        empty = QFrame()
        empty.setObjectName("calendarEmpty")
        layout = QVBoxLayout(empty)
        layout.setContentsMargins(22, 22, 22, 22)
        title = QLabel("No upcoming episode dates cached")
        title.setObjectName("calendarEmptyTitle")
        body = QLabel(
            "NekoTrack builds this view from locally saved episode metadata. "
            "The app may still be syncing schedules, or your library's anime may not have announced another episode yet. "
            "The calendar will populate as air dates become available."
        )
        body.setObjectName("calendarSubtitle")
        body.setWordWrap(True)
        reminder_count = len(get_release_reminders())
        reminder_label = QLabel(f"{reminder_count} saved reminder{'s' if reminder_count != 1 else ''}")
        reminder_label.setObjectName("calendarCount")
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addWidget(reminder_label)
        self.layout.addWidget(empty)

    def _event_card(self, row):
        card = QFrame()
        card.setObjectName("calendarEvent")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setSpacing(12)

        date_badge = QFrame()
        date_badge.setObjectName("calendarDateBadge")
        date_layout = QVBoxLayout(date_badge)
        date_layout.setContentsMargins(10, 7, 10, 7)
        date_layout.setSpacing(0)
        month = QLabel(row["_release_date"].strftime("%b").upper())
        month.setObjectName("calendarMonth")
        day = QLabel(str(row["_release_date"].day))
        day.setObjectName("calendarDay")
        date_layout.addWidget(month, 0, Qt.AlignmentFlag.AlignHCenter)
        date_layout.addWidget(day, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(date_badge)

        description = QVBoxLayout()
        description.setSpacing(4)
        title = QLabel(str(row.get("work_title") or "Untitled"))
        title.setObjectName("calendarWorkTitle")
        title.setWordWrap(True)
        episode = int(row.get("episode_number") or 0)
        episode_title = str(row.get("title") or "").strip()
        label = episode_title if episode_title and not episode_title.casefold().startswith("episode ") else f"Episode {episode}"
        subtitle = QLabel(label)
        subtitle.setObjectName("calendarEpisodeTitle")
        airdate = QLabel(row["_release_date"].strftime("%A, %B %d, %Y"))
        airdate.setObjectName("calendarSubtitle")
        description.addWidget(title)
        description.addWidget(subtitle)
        description.addWidget(airdate)
        layout.addLayout(description, 1)

        key = (int(row["work_id"]), episode)
        remind = QPushButton("Reminder on" if row["_reminder_enabled"] else "Remind me")
        remind.setObjectName("calendarReminderOn" if row["_reminder_enabled"] else "calendarAction")
        remind.setCheckable(False)
        remind.setAccessibleName("Disable episode reminder" if row["_reminder_enabled"] else "Enable episode reminder")
        remind.clicked.connect(lambda _=False, work_id=key[0], number=key[1], current=row["_reminder_enabled"]:
                               self._toggle_reminder(work_id, number, not current))
        layout.addWidget(remind, 0, Qt.AlignmentFlag.AlignVCenter)
        card.setToolTip(f"{row['work_title']} · Episode {episode} · date-only schedule")
        return card

    def _toggle_reminder(self, work_id, episode_number, enabled):
        try:
            set_release_reminder(work_id, episode_number, enabled)
        except Exception as error:
            log_exception("calendar.reminder_save_failed", error, work_id=work_id, episode_number=episode_number)
            return
        self.refresh()

    def _clear(self):
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def refresh_theme(self):
        self._apply_theme()

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QWidget#calendarContent {{ background:transparent; }}
            QScrollArea#calendarScroll {{ background:transparent; border:none; }}
            QFrame#calendarHeader, QFrame#calendarEmpty, QFrame#calendarEvent {{
                background:{surface_rgba('surface')}; border:1px solid {COLORS['frame']}; border-radius:14px;
            }}
            QFrame#calendarEvent:hover {{ border-color:{COLORS['border_hover']}; }}
            QFrame#calendarDateBadge {{
                background:{surface_rgba('accent_soft')}; border:1px solid {COLORS['border_hover']}; border-radius:10px;
                min-width:54px; max-width:54px;
            }}
            QLabel#calendarTitle, QLabel#calendarEmptyTitle {{
                color:{COLORS['primary']}; background:transparent; font-size:22px; font-weight:850;
            }}
            QLabel#calendarSubtitle {{ color:{COLORS['secondary']}; background:transparent; font-size:12px; }}
            QLabel#calendarCount {{ color:{COLORS['muted']}; background:transparent; font-size:11px; font-weight:750; }}
            QLabel#calendarDayHeader {{ color:{COLORS['accent']}; background:transparent; font-size:13px; font-weight:850; padding:7px 2px; }}
            QLabel#calendarMonth {{ color:{COLORS['accent']}; background:transparent; font-size:10px; font-weight:900; }}
            QLabel#calendarDay {{ color:{COLORS['primary']}; background:transparent; font-size:23px; font-weight:900; }}
            QLabel#calendarWorkTitle {{ color:{COLORS['primary']}; background:transparent; font-size:13px; font-weight:800; }}
            QLabel#calendarEpisodeTitle {{ color:{COLORS['secondary']}; background:transparent; font-size:11px; font-weight:750; }}
            QPushButton#calendarAction, QPushButton#calendarReminderOn {{
                background:{surface_rgba('surface_alt')}; color:{COLORS['primary']}; border:1px solid {COLORS['border']};
                border-radius:8px; padding:9px 12px; font-size:11px; font-weight:800;
            }}
            QPushButton#calendarAction:hover, QPushButton#calendarReminderOn:hover {{
                background:{surface_rgba('accent_soft')}; border-color:{COLORS['accent']};
            }}
            QPushButton#calendarReminderOn {{ color:{COLORS['accent']}; }}
        """)


__all__ = ["CalendarPage"]
