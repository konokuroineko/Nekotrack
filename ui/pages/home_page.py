"""A responsive, data-driven home dashboard for NekoTrack."""

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

from database import get_all_library
from diagnostics import log_exception
from ui.preferences import get
from ui.theme import COLORS
from ui.widgets.work_card import WorkCard


class HomePage(QWidget):
    """Home dashboard backed by saved library records and real read/watch progress."""

    work_selected = Signal(object)
    search_requested = Signal()
    library_requested = Signal()

    def __init__(self):
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

        self._home_counts = {"all": 0, "in_progress": 0, "completed": 0, "planned": 0}
        self._continue_ids = set()
        self._recent_ids = []
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
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
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
            "planned": sum(status in {"planning", "plan to watch", "plan to read"} for status in statuses),
        }

        continue_items = [
            work for work in library
            if self._status(work) in {"watching", "rewatching", "reading", "in progress"}
        ]
        self._continue_ids = {
            self._integer(work.get("id")) for work in continue_items
        }
        self._recent_ids = [
            self._integer(work.get("id")) for work in library[:5]
        ]

        self.content_layout.addWidget(self._hero(library))
        self.content_layout.addWidget(self._stats_row())
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
        self.content_layout.addStretch(1)
        self._apply_theme_styles()

    def _hero(self, library):
        hero = QFrame()
        hero.setObjectName("homeHero")
        layout = QVBoxLayout(hero)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(10)

        eyebrow = QLabel("YOUR PERSONAL MEDIA SPACE")
        eyebrow.setObjectName("homeHeroEyebrow")
        title = QLabel(
            "Keep your stories moving." if library else "Your next story starts here."
        )
        title.setObjectName("homeHeroTitle")
        title.setWordWrap(True)
        description = QLabel(
            (
                f"You have {len(library)} saved title{'s' if len(library) != 1 else ''}. "
                "Continue a series or explore something new."
            )
            if library else
            "Build your own anime, manga, and light-novel collection. "
            "Your progress stays in your local library."
        )
        description.setObjectName("homeHeroDescription")
        description.setWordWrap(True)
        layout.addWidget(eyebrow)
        layout.addWidget(title)
        layout.addWidget(description)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        discover = QPushButton("Explore the catalog")
        discover.setObjectName("homePrimaryAction")
        discover.setCursor(Qt.CursorShape.PointingHandCursor)
        discover.clicked.connect(self.search_requested.emit)
        library_button = QPushButton("Open library")
        library_button.setObjectName("homeSecondaryAction")
        library_button.setCursor(Qt.CursorShape.PointingHandCursor)
        library_button.clicked.connect(self.library_requested.emit)
        actions.addWidget(discover, 0, Qt.AlignmentFlag.AlignLeft)
        actions.addWidget(library_button, 0, Qt.AlignmentFlag.AlignLeft)
        actions.addStretch(1)
        layout.addLayout(actions)
        return hero

    def _stats_row(self):
        row = QWidget()
        row.setObjectName("homeStatsRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        data = [
            ("ALL TITLES", self._home_counts["all"], "Saved in your library", "accent"),
            ("IN PROGRESS", self._home_counts["in_progress"], "Watching or reading", "success"),
            ("COMPLETED", self._home_counts["completed"], "Marked finished", "primary"),
            ("PLANNED", self._home_counts["planned"], "In your queue", "secondary"),
        ]
        for title, number, hint, tone in data:
            card = QFrame()
            card.setObjectName("homeStatCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 17, 18, 16)
            card_layout.setSpacing(6)
            heading = QLabel(title)
            heading.setObjectName("homeStatLabel")
            value = QLabel(str(number))
            value.setObjectName("homeStatValue")
            value.setProperty("statTone", tone)
            detail = QLabel(hint)
            detail.setObjectName("homeStatHint")
            detail.setWordWrap(True)
            card_layout.addWidget(heading)
            card_layout.addWidget(value)
            card_layout.addStretch(1)
            card_layout.addWidget(detail)
            layout.addWidget(card, 1)
        return row

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
                "Use Discover to find a title and add it to your collection."
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
            QFrame#homeHero {{
                background: {COLORS['surface']};
                border: 1px solid {COLORS['frame']};
                border-left: 5px solid {COLORS['accent']};
                border-radius: 18px;
            }}
            QLabel#homeHeroEyebrow {{
                color: {COLORS['accent']};
                background: transparent;
                font-size: 10px;
                font-weight: 900;
                letter-spacing: 1.4px;
            }}
            QLabel#homeHeroTitle {{
                color: {COLORS['primary']};
                background: transparent;
                font-size: 28px;
                font-weight: 850;
            }}
            QLabel#homeHeroDescription {{
                color: {COLORS['secondary']};
                background: transparent;
                font-size: 13px;
            }}
            QPushButton#homePrimaryAction {{
                background: {COLORS['accent']};
                color: {COLORS['accent_text']};
                border: 1px solid {COLORS['accent']};
                border-radius: 9px;
                padding: 10px 15px;
                font-weight: 800;
            }}
            QPushButton#homePrimaryAction:hover {{
                background: {COLORS['accent_hover']};
                border-color: {COLORS['accent_hover']};
            }}
            QPushButton#homeSecondaryAction {{
                background: {COLORS['surface_alt']};
                color: {COLORS['primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 9px;
                padding: 10px 15px;
                font-weight: 750;
            }}
            QPushButton#homeSecondaryAction:hover {{
                background: {COLORS['surface_hover']};
                border-color: {COLORS['border_hover']};
            }}
            QFrame#homeStatCard {{
                background: {COLORS['surface']};
                border: 1px solid {COLORS['frame']};
                border-radius: 14px;
            }}
            QLabel#homeStatLabel {{
                color: {COLORS['muted']};
                background: transparent;
                font-size: 10px;
                font-weight: 850;
                letter-spacing: 1.1px;
            }}
            QLabel#homeStatValue {{
                background: transparent;
                font-size: 32px;
                font-weight: 850;
            }}
            QLabel#homeStatHint {{
                color: {COLORS['secondary']};
                background: transparent;
                font-size: 11px;
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
        """)
        tones = {
            "accent": COLORS["accent"],
            "success": COLORS["success"],
            "primary": COLORS["primary"],
            "secondary": COLORS["secondary"],
        }
        for value in self.findChildren(QLabel):
            if value.objectName() == "homeStatValue":
                value.setStyleSheet(
                    f"color:{tones.get(value.property('statTone'), COLORS['primary'])};"
                    "background:transparent;font-size:32px;font-weight:850;"
                )
        for card in self.findChildren(WorkCard):
            card.refresh_theme()

    def refresh_theme(self):
        self._apply_theme_styles()
