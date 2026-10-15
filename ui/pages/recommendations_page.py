"""Recommendations grounded in titles already saved in the local library."""

import threading

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from api import get_media_recommendations
from database import get_all_library
from diagnostics import log_exception
from ui.preferences import get
from ui.theme import COLORS
from ui.widgets.work_card import WorkCard


class RecommendationWorker(QObject):
    """Fetch suggestions in a worker thread; never block the UI on AniList."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, library_rows, stop_event=None):
        super().__init__()
        self.library_rows = [dict(row) for row in library_rows]
        self.stop_event = stop_event or threading.Event()

    @staticmethod
    def _work_id(work):
        try:
            work_id = int(work.get("id"))
        except (TypeError, ValueError, OverflowError):
            return None
        return work_id if work_id > 0 else None

    def run(self):
        known_ids = {
            work_id for work in self.library_rows
            if (work_id := self._work_id(work)) is not None
        }
        seeds = []
        for work in self.library_rows:
            work_id = self._work_id(work)
            media_type = str(work.get("type") or "").upper()
            if work_id is None or media_type not in {"ANIME", "MANGA"}:
                continue
            seeds.append((work_id, self._title(work)))
            if len(seeds) >= 4:
                break

        if not seeds:
            self.finished.emit([])
            return

        suggestions = {}
        errors = []
        for seed_id, seed_title in seeds:
            if self.stop_event.is_set():
                self.finished.emit([])
                return
            try:
                records = get_media_recommendations(seed_id, per_page=12)
            except Exception as error:
                errors.append(error)
                log_exception(
                    "recommendations.seed_fetch_failed",
                    error,
                    work_id=seed_id,
                )
                continue
            for record in records or []:
                if not isinstance(record, dict):
                    continue
                try:
                    work_id = int(record.get("id"))
                except (TypeError, ValueError, OverflowError):
                    continue
                if work_id <= 0 or work_id in known_ids or self.stop_event.is_set():
                    continue
                entry = suggestions.setdefault(
                    work_id,
                    {
                        **record,
                        "_recommendation_source_ids": [],
                        "_recommendation_source_titles": [],
                        "_recommendation_count": 0,
                    },
                )
                if seed_id not in entry["_recommendation_source_ids"]:
                    entry["_recommendation_source_ids"].append(seed_id)
                    entry["_recommendation_source_titles"].append(seed_title)
                    entry["_recommendation_count"] += 1

        if not suggestions and errors and len(errors) == len(seeds):
            self.failed.emit("AniList recommendations could not be loaded. Check your connection and try again.")
            return

        def ranking(item):
            score = item.get("averageScore")
            try:
                score = int(score) if score is not None else 0
            except (TypeError, ValueError, OverflowError):
                score = 0
            return (
                -int(item.get("_recommendation_count") or 0),
                -int(item.get("_recommendation_rating") or 0),
                -score,
                str((item.get("title") or {}).get("english") or
                    (item.get("title") or {}).get("romaji") or "").casefold(),
            )

        ordered = sorted(suggestions.values(), key=ranking)
        self.finished.emit(ordered[:40])

    @staticmethod
    def _title(work):
        title = work.get("title")
        if isinstance(title, dict):
            return str(title.get("english") or title.get("romaji") or title.get("native") or "Untitled")
        return str(title or "Untitled")


class RecommendationsPage(QWidget):
    work_selected = Signal(object)
    search_requested = Signal()

    def __init__(self, add_callback=None, embedded=False):
        super().__init__()
        self.add_callback = add_callback
        self.embedded = bool(embedded)
        self._thread = None
        self._worker = None
        self._stop_event = threading.Event()
        self._loaded = False
        self._results = []
        self._library_signature = None
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.content = QWidget()
        self.content.setObjectName("recommendationsContent")
        self.content_layout = QVBoxLayout(self.content)

        if self.embedded:
            # Home already owns the page-level scroll area, so embedded
            # recommendations must not create a second vertical scroll area.
            self.content_layout.setContentsMargins(0, 0, 0, 0)
            self.content_layout.setSpacing(18)
            self.scroll = None
            outer.addWidget(self.content)
        else:
            self.scroll = QScrollArea(self)
            self.scroll.setObjectName("recommendationsScroll")
            self.scroll.setWidgetResizable(True)
            self.scroll.setFrameShape(QFrame.Shape.NoFrame)
            self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.content_layout.setContentsMargins(34, 28, 34, 34)
            self.content_layout.setSpacing(18)
            self.scroll.setWidget(self.content)
            outer.addWidget(self.scroll)
        self._apply_theme()

    def _header(self):
        header = QFrame()
        header.setObjectName("recommendationsHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(22, 20, 22, 20)
        text_col = QVBoxLayout()
        text_col.setSpacing(5)
        title = QLabel("For your next watch or read")
        title.setObjectName("recommendationsTitle")
        subtitle = QLabel(
            "Suggestions from AniList, based on titles already in your library."
        )
        subtitle.setObjectName("recommendationsSubtitle")
        subtitle.setWordWrap(True)
        text_col.addWidget(title)
        text_col.addWidget(subtitle)
        layout.addLayout(text_col, 1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("recommendationsRefresh")
        self.refresh_button.clicked.connect(lambda: self.refresh(force=True))
        layout.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignVCenter)
        return header

    @staticmethod
    def _rows_signature(rows):
        return tuple(
            (
                str(row.get("id") or ""),
                str(row.get("type") or "").upper(),
                RecommendationWorker._title(row),
            )
            for row in rows
        )

    def refresh(self, force=False, library_rows=None):
        if self._thread is not None and self._thread.isRunning():
            return
        try:
            rows = (
                [dict(row) for row in library_rows]
                if library_rows is not None
                else [dict(row) for row in (get_all_library() or [])]
            )
        except Exception as error:
            log_exception("recommendations.library_read_failed", error)
            if self.content_layout.count() == 0:
                label = QLabel(
                    "Your library could not be read. Reopen this page to try again."
                )
                label.setObjectName("recommendationsStatus")
                label.setWordWrap(True)
                self.content_layout.addWidget(label)
            return

        signature = self._rows_signature(rows)
        if self._loaded and not force and signature == self._library_signature:
            self._render_results()
            return

        self._stop_event = threading.Event()
        self._clear_content()
        self.content_layout.addWidget(self._header())
        self.status = QLabel("Finding recommendations from your saved titles…")
        self.status.setObjectName("recommendationsStatus")
        self.status.setWordWrap(True)
        self.content_layout.addWidget(self.status)
        self._library_signature = signature

        if not any(
            RecommendationWorker._work_id(row) is not None
            and str(row.get("type") or "").upper() in {"ANIME", "MANGA"}
            for row in rows
        ):
            self._loaded = True
            self._results = []
            self._render_results()
            return

        worker = RecommendationWorker(rows, self._stop_event)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._recommendations_ready)
        worker.failed.connect(self._recommendations_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._thread_finished(t))
        self._worker = worker
        self._thread = thread
        thread.start()
        self.refresh_button = self.findChild(QPushButton, "recommendationsRefresh")
        if self.refresh_button is not None:
            self.refresh_button.setEnabled(False)

    def _recommendations_ready(self, results):
        if self._stop_event.is_set():
            return
        self._loaded = True
        self._results = [dict(item) for item in (results or []) if isinstance(item, dict)]
        self._render_results()

    def _recommendations_failed(self, message):
        if self._stop_event.is_set():
            return
        self._loaded = False
        self._clear_content()
        self.content_layout.addWidget(self._header())
        label = QLabel(message)
        label.setObjectName("recommendationsStatus")
        label.setWordWrap(True)
        self.content_layout.addWidget(label)
        self.content_layout.addStretch(1)

    def _thread_finished(self, thread):
        if self._thread is thread:
            self._thread = None
            self._worker = None
        button = self.findChild(QPushButton, "recommendationsRefresh")
        if button is not None:
            button.setEnabled(True)

    def _render_empty(self, message):
        empty = QFrame()
        empty.setObjectName("recommendationsEmpty")
        layout = QVBoxLayout(empty)
        layout.setContentsMargins(22, 22, 22, 22)
        title = QLabel("No recommendations to show yet")
        title.setObjectName("recommendationsEmptyTitle")
        body = QLabel(message)
        body.setObjectName("recommendationsSubtitle")
        body.setWordWrap(True)
        explore = QPushButton("Explore the catalog")
        explore.setObjectName("recommendationsRefresh")
        explore.clicked.connect(self.search_requested.emit)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addWidget(explore, 0, Qt.AlignmentFlag.AlignLeft)
        self.content_layout.addWidget(empty)
        self.content_layout.addStretch(1)

    def _render_results(self):
        self._clear_content()
        self.content_layout.addWidget(self._header())
        if not self._results:
            self._render_empty(
                "AniList did not return suggestions for the titles currently saved in your library."
            )
            return
        summary = QLabel(
            f"{len(self._results)} suggestions · titles already in your library are excluded"
        )
        summary.setObjectName("recommendationsSubtitle")
        self.content_layout.addWidget(summary)
        grid_host = QWidget()
        grid_host.setObjectName("recommendationsGridHost")
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(22)
        available_width = max(
            100,
            self.width() if self.embedded else (self.scroll.viewport().width() or self.width() - 320),
        )
        poster_width = int(get("card_size") or 210) + 8
        columns = max(2, min(5, (available_width - 50) // (poster_width + 16)))
        for index, work in enumerate(self._results):
            tile = QFrame()
            tile.setObjectName("recommendationsTile")
            layout = QVBoxLayout(tile)
            layout.setContentsMargins(5, 5, 5, 10)
            layout.setSpacing(8)
            card = WorkCard(
                work, mode="search", add_callback=self.add_callback,
                show_add_button=True, parent=tile,
            )
            card.clicked.connect(self.work_selected.emit)
            layout.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
            source_titles = work.get("_recommendation_source_titles") or []
            source_count = int(work.get("_recommendation_count") or 0)
            if source_count > 1:
                reason = f"Matches {source_count} of your titles"
            elif source_titles:
                reason = f"Suggested from {source_titles[0]}"
            else:
                reason = "Suggested by AniList"
            reason_label = QLabel(reason)
            reason_label.setObjectName("recommendationsReason")
            reason_label.setWordWrap(True)
            layout.addWidget(reason_label)
            grid.addWidget(tile, index // columns, index % columns, Qt.AlignmentFlag.AlignTop)
        self.content_layout.addWidget(grid_host)
        self.content_layout.addStretch(1)
        self._apply_theme()

    def _clear_content(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def request_shutdown(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.quit()

    def refresh_theme(self):
        self._apply_theme()
        for card in self.findChildren(WorkCard):
            card.refresh_theme()

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QWidget#recommendationsContent {{ background:transparent; }}
            QScrollArea#recommendationsScroll {{ background:transparent; border:none; }}
            QFrame#recommendationsHeader, QFrame#recommendationsEmpty {{
                background:{COLORS['surface']}; border:1px solid {COLORS['frame']}; border-radius:15px;
            }}
            QLabel#recommendationsTitle, QLabel#recommendationsEmptyTitle {{
                color:{COLORS['primary']}; background:transparent; font-size:22px; font-weight:850;
            }}
            QLabel#recommendationsSubtitle, QLabel#recommendationsStatus {{
                color:{COLORS['secondary']}; background:transparent; font-size:12px;
            }}
            QLabel#recommendationsReason {{
                color:{COLORS['muted']}; background:transparent; font-size:10px; max-width:210px;
            }}
            QFrame#recommendationsTile {{ background:transparent; border:1px solid transparent; border-radius:12px; }}
            QFrame#recommendationsTile:hover {{ background:{COLORS['surface']}; border-color:{COLORS['border']}; }}
            QPushButton#recommendationsRefresh {{
                background:{COLORS['accent']}; color:{COLORS['accent_text']}; border:1px solid {COLORS['accent']};
                border-radius:8px; padding:9px 13px; font-weight:800;
            }}
        """)


__all__ = ["RecommendationWorker", "RecommendationsPage"]
