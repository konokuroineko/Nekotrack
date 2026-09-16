from threading import Event

from PySide6.QtCore import QObject, QThread, Qt, Signal, QTimer
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from api import search_anime
from series import group_media_results, has_pending_relation_enrichment
from ui.preferences import get
from ui.theme import COLORS
from ui.widgets.work_card import WorkCard


class InfiniteScrollArea(QScrollArea):
    scroll_to_bottom = Signal()

    def __init__(self):
        super().__init__()
        self.verticalScrollBar().valueChanged.connect(self._check)

    def _check(self):
        bar = self.verticalScrollBar()
        if bar.value() >= bar.maximum() - 120:
            self.scroll_to_bottom.emit()


class SkeletonCard(QFrame):
    """Lightweight result placeholder shown while AniList work is in flight."""
    def __init__(self, parent=None):
        super().__init__(parent)
        card_size = get("card_size")
        card_width = card_size + 8
        cover_height = round(card_size * 284 / 210)
        self.setFixedSize(card_width, cover_height + 112)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setStyleSheet(f"""
            QFrame#skeleton {{
                background: transparent;
                border: 2px solid {COLORS['border']};
                border-radius: {get('corner_radius') + 2}px;
            }}
            QFrame#skeletonFill {{
                background: {COLORS['surface_hover']};
                border: 1px solid {COLORS['border']};
                border-radius: {get('corner_radius')}px;
            }}
        """)
        self.setObjectName("skeleton")
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(8)

        cover = QFrame(); cover.setObjectName("skeletonFill"); cover.setFixedSize(card_size, cover_height)
        root.addWidget(cover, 0, Qt.AlignHCenter)

        title_line_1 = QFrame(); title_line_1.setObjectName("skeletonFill"); title_line_1.setFixedHeight(9); title_line_1.setFixedWidth(max(80, card_width - 26))
        title_line_2 = QFrame(); title_line_2.setObjectName("skeletonFill"); title_line_2.setFixedHeight(9); title_line_2.setFixedWidth(max(55, card_width - 70))
        root.addWidget(title_line_1)
        root.addWidget(title_line_2)

        meta = QFrame(); meta.setObjectName("skeletonFill"); meta.setFixedHeight(8); meta.setFixedWidth(max(70, card_width - 90))
        root.addWidget(meta)
        root.addStretch(1)


class SearchWorker(QObject):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, search_text, page, media_type, media_format, filters):
        super().__init__()
        self.search_text = search_text
        self.page = page
        self.media_type = media_type
        self.media_format = media_format
        self.filters = filters

    def run(self):
        try:
            data = search_anime(
                self.search_text,
                self.page,
                media_type=self.media_type,
                media_format=self.media_format,
                **self.filters,
            )
            self.finished.emit(data)
        except Exception as error:
            self.error.emit(str(error))


class SeriesEnrichmentWorker(QObject):
    finished = Signal(object)

    def __init__(self, results, stop_event):
        super().__init__()
        self.results = results
        self.stop_event = stop_event

    def run(self):
        grouped = group_media_results(
            self.results,
            enrich=True,
            max_requests=8,
            delay=1.1,
            stop_event=self.stop_event,
        )
        self.finished.emit(grouped)


class SearchPage(QWidget):
    anime_selected = Signal(object)

    def __init__(self, add_to_library):
        super().__init__()
        self.add_to_library = add_to_library
        self.current_search = ""
        self.current_media_type = None
        self.current_media_format = None
        self.current_page = 1
        self.has_next_page = False
        self.is_loading = False
        self.has_searched = False
        self.threads, self.workers = [], []
        self.enrichment_thread = None
        self.enrichment_worker = None
        self.enrichment_stop = None
        self.enrichment_scheduled = False
        self.enrichment_generation = 0
        self.raw_results = []

        root = QVBoxLayout(self)
        root.setContentsMargins(34, 30, 34, 28)
        root.setSpacing(20)

        intro = QVBoxLayout(); intro.setSpacing(3)
        heading = QLabel("Discover")
        heading.setStyleSheet(f"font-size: 34px; font-weight: 850; color: {COLORS['primary']};")
        sub = QLabel("Search the AniList catalog and build your library.")
        sub.setStyleSheet(f"font-size: 12px; color: {COLORS['muted']};")
        intro.addWidget(heading); intro.addWidget(sub); root.addLayout(intro)

        search_panel = QFrame()
        search_panel.setStyleSheet(f"QFrame {{ background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 16px; }}")
        panel = QVBoxLayout(search_panel); panel.setContentsMargins(12, 12, 12, 12); panel.setSpacing(10)

        bar = QHBoxLayout(); bar.setSpacing(8)
        self.search = QLineEdit(); self.search.setPlaceholderText("Title, character, franchise... (optional)"); self.search.setMinimumHeight(46); self.search.setClearButtonEnabled(True)
        self.search_button = QPushButton("Search"); self.search_button.setMinimumHeight(46); self.search_button.setMinimumWidth(100)
        bar.addWidget(self.search, 1); bar.addWidget(self.search_button); panel.addLayout(bar)

        self.filters_button = QPushButton("Filters")
        self.filters_button.setFixedHeight(40); self.filters_button.setMinimumWidth(82)
        panel.addWidget(self.filters_button, 0, Qt.AlignLeft)

        self.filters_panel = QFrame(); self.filters_panel.setVisible(False)
        self.filters_panel.setStyleSheet(f"QFrame {{ background: {COLORS['background']}; border: 1px solid {COLORS['border']}; border-radius: 12px; }} QLabel {{ background: transparent; border: none; }}")
        filters_layout = QGridLayout(self.filters_panel); filters_layout.setContentsMargins(12, 12, 12, 12); filters_layout.setHorizontalSpacing(10); filters_layout.setVerticalSpacing(5)

        self.media_filter = self._make_combo(["All", "Anime", "Manga", "Novels"])
        self.format_filter = self._make_combo(["All", "TV", "TV Short", "Movie", "OVA", "ONA", "Special", "Music"])
        self.status_filter = self._make_combo(["All", "Finished", "Releasing", "Not Yet Released", "Cancelled", "Hiatus"])
        self.season_filter = self._make_combo(["All", "Winter", "Spring", "Summer", "Fall"])
        self.year_filter = QLineEdit(); self.year_filter.setPlaceholderText("e.g. 2024"); self.year_filter.setFixedHeight(38)
        self.min_score_filter = QComboBox(); self.min_score_filter.addItems(["Any score", "50+", "60+", "70+", "80+", "90+"]); self.min_score_filter.setFixedHeight(38)
        self.sort_filter = self._make_combo(["Relevance", "Popularity", "Score", "Newest", "Oldest", "Title A–Z", "Title Z–A"])
        self.genre_filter = QLineEdit(); self.genre_filter.setPlaceholderText("e.g. Fantasy, Action"); self.genre_filter.setFixedHeight(38)
        self.tag_filter = QLineEdit(); self.tag_filter.setPlaceholderText("e.g. Isekai, Reincarnation"); self.tag_filter.setFixedHeight(38)

        fields = [
            ("Type", self.media_filter, 0, 0), ("Format", self.format_filter, 0, 1), ("Status", self.status_filter, 0, 2), ("Season", self.season_filter, 0, 3),
            ("Year", self.year_filter, 1, 0), ("Minimum score", self.min_score_filter, 1, 1), ("Sort", self.sort_filter, 1, 2), ("Genre", self.genre_filter, 1, 3),
            ("Tag", self.tag_filter, 2, 0),
        ]
        for label_text, widget, row, col in fields:
            label = QLabel(label_text); label.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {COLORS['muted']}; padding-left: 2px;")
            filters_layout.addWidget(label, row * 2, col); filters_layout.addWidget(widget, row * 2 + 1, col)

        self.clear_filters_button = QPushButton("Clear filters"); self.clear_filters_button.setFixedHeight(38)
        filters_layout.addWidget(self.clear_filters_button, 6, 0, 1, 4, Qt.AlignLeft)
        panel.addWidget(self.filters_panel); root.addWidget(search_panel)

        result_head = QHBoxLayout()
        self.results_title = QLabel("Ready to search"); self.results_title.setStyleSheet(f"font-size: 15px; font-weight: 750; color: {COLORS['primary']};")
        result_head.addWidget(self.results_title); result_head.addStretch(); root.addLayout(result_head)

        self.results_scroll = InfiniteScrollArea(); self.results_scroll.setWidgetResizable(True); self.results_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding); self.results_scroll.setFrameShape(QFrame.NoFrame)
        self.grid_container = QWidget(); self.grid_layout = QGridLayout(self.grid_container); self.grid_layout.setContentsMargins(4, 4, 4, 20); self.grid_layout.setHorizontalSpacing(22); self.grid_layout.setVerticalSpacing(30)
        self.results_scroll.setWidget(self.grid_container); self.results_scroll.scroll_to_bottom.connect(self.load_more_results); root.addWidget(self.results_scroll, 1)

        self.search_button.clicked.connect(self.search_clicked); self.search.returnPressed.connect(self.search_clicked)
        self.media_filter.currentIndexChanged.connect(self.media_filter_changed)
        self.filters_button.clicked.connect(self.toggle_filters); self.clear_filters_button.clicked.connect(self.clear_filters)
        self._refresh_format_filter()

    def _make_combo(self, items):
        combo = QComboBox(); combo.addItems(items); combo.setFixedHeight(38); return combo

    def toggle_filters(self):
        visible = not self.filters_panel.isVisible(); self.filters_panel.setVisible(visible); self.filters_button.setText("Hide filters" if visible else "Filters")

    def _refresh_format_filter(self):
        current = self.format_filter.currentText()
        self.format_filter.blockSignals(True)
        self.format_filter.clear()
        if self.current_media_type == "ANIME":
            items = ["All", "TV", "TV Short", "Movie", "OVA", "ONA", "Special", "Music"]
        elif self.current_media_type == "MANGA":
            if self.current_media_format == "NOVEL":
                items = ["All", "Novel"]
            else:
                items = ["All", "Manga", "One Shot"]
        else:
            items = ["All", "TV", "TV Short", "Movie", "OVA", "ONA", "Special", "Music", "Manga", "Novel", "One Shot"]
        self.format_filter.addItems(items)
        if current in items:
            self.format_filter.setCurrentText(current)
        else:
            self.format_filter.setCurrentIndex(0)
        self.format_filter.setEnabled(True)
        self.format_filter.blockSignals(False)

    def media_filter_changed(self):
        self.current_media_type, self.current_media_format = self.selected_media_filter()
        self._refresh_format_filter()
        if self.has_searched and not self.is_loading: self.search_clicked()

    def selected_media_filter(self):
        return {"All": (None, None), "Anime": ("ANIME", None), "Manga": ("MANGA", "MANGA"), "Novels": ("MANGA", "NOVEL")}[self.media_filter.currentText()]

    def selected_filters(self):
        format_map = {"TV": "TV", "TV Short": "TV_SHORT", "Movie": "MOVIE", "OVA": "OVA", "ONA": "ONA", "Special": "SPECIAL", "Music": "MUSIC", "Manga": "MANGA", "Novel": "NOVEL", "One Shot": "ONE_SHOT"}
        status_map = {"Finished": "FINISHED", "Releasing": "RELEASING", "Not Yet Released": "NOT_YET_RELEASED", "Cancelled": "CANCELLED", "Hiatus": "HIATUS"}
        season_map = {"Winter": "WINTER", "Spring": "SPRING", "Summer": "SUMMER", "Fall": "FALL"}
        sort_map = {"Relevance": "SEARCH_MATCH", "Popularity": "POPULARITY_DESC", "Score": "SCORE_DESC", "Newest": "START_DATE_DESC", "Oldest": "START_DATE", "Title A–Z": "TITLE_ROMAJI", "Title Z–A": "TITLE_ROMAJI_DESC"}
        year = self.year_filter.text().strip(); year = year if year.isdigit() and len(year) == 4 else None
        min_score = self.min_score_filter.currentText(); min_score = int(min_score[:-1]) if min_score.endswith("+") else None
        return {
            "format_filter": format_map.get(self.format_filter.currentText()),
            "status": status_map.get(self.status_filter.currentText()),
            "season": season_map.get(self.season_filter.currentText()),
            "year": year,
            "sort": sort_map.get(self.sort_filter.currentText()),
            "min_score": min_score,
            "genre": self.genre_filter.text().strip() or None,
            "tag": self.tag_filter.text().strip() or None,
        }

    def clear_filters(self):
        self.media_filter.setCurrentIndex(0)
        self._refresh_format_filter()
        self.status_filter.setCurrentIndex(0)
        self.season_filter.setCurrentIndex(0)
        self.year_filter.clear()
        self.min_score_filter.setCurrentIndex(0)
        self.sort_filter.setCurrentIndex(0)
        self.genre_filter.clear()
        self.tag_filter.clear()
        if self.has_searched and not self.is_loading: self.search_clicked()

    def search_clicked(self):
        text = self.search.text().strip()
        if self.is_loading: return
        self._stop_enrichment()
        self.enrichment_generation += 1
        self.current_search = text
        self.current_media_type, self.current_media_format = self.selected_media_filter()
        self.current_page = 1
        self.has_next_page = False
        self.raw_results = []
        self.has_searched = True
        self.show_skeletons(12)
        self.results_title.setText("Browsing AniList" if not text else f"Searching for “{text}”")
        self.search_button.setEnabled(False)
        self.is_loading = True
        self.start_search(text, 1)

    def load_more_results(self):
        if self.has_searched and self.has_next_page and not self.is_loading:
            self.show_skeletons(8, append=True)
            self.is_loading = True
            self.start_search(self.current_search, self.current_page + 1)

    def start_search(self, text, page):
        thread = QThread()
        worker = SearchWorker(text, page, self.current_media_type, self.current_media_format, self.selected_filters())
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self.search_finished)
        worker.error.connect(self.search_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self.threads.append(thread); self.workers.append(worker); thread.start()

    def search_finished(self, data):
        self.search_button.setEnabled(True); self.is_loading = False
        self.current_page = data["pageInfo"]["currentPage"]
        self.has_next_page = data["pageInfo"]["hasNextPage"]
        new_results = data["media"]
        if self.current_page == 1:
            self.raw_results = []
        self.raw_results.extend(new_results)

        grouped = group_media_results(self.raw_results)
        self.results_title.setText(f"{len(self.raw_results)} entries · {len(grouped)} series · page {self.current_page}")
        if not grouped and self.current_page == 1:
            self.clear_results(); self.show_message("No results found"); return
        self._render_grouped(grouped)
        self._start_enrichment()

    def _start_enrichment(self):
        if not self.raw_results or self.enrichment_thread is not None and self.enrichment_thread.isRunning():
            return
        generation = self.enrichment_generation
        stop_event = Event()
        self.enrichment_stop = stop_event
        thread = QThread()
        worker = SeriesEnrichmentWorker(list(self.raw_results), stop_event)
        worker._generation = generation
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self.enrichment_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self.enrichment_thread = thread
        self.enrichment_worker = worker
        thread.start()

    def _stop_enrichment(self):
        if self.enrichment_stop is not None:
            self.enrichment_stop.set()
        self.enrichment_stop = None
        self.enrichment_worker = None
        self.enrichment_thread = None
        self.enrichment_scheduled = False

    def enrichment_finished(self, grouped):
        thread = self.enrichment_thread
        worker = self.enrichment_worker
        generation = getattr(worker, "_generation", self.enrichment_generation) if worker else self.enrichment_generation
        if generation != self.enrichment_generation:
            return
        if not self.raw_results:
            return
        current_grouped = group_media_results(self.raw_results)
        if grouped:
            current_grouped = grouped
        self.results_title.setText(f"{len(self.raw_results)} entries · {len(current_grouped)} series")
        self._render_grouped(current_grouped)
        self.enrichment_worker = None
        self.enrichment_thread = None
        self.enrichment_stop = None
        if has_pending_relation_enrichment(self.raw_results) and not self.enrichment_scheduled:
            self.enrichment_scheduled = True
            QTimer.singleShot(1300, self._resume_enrichment)
        else:
            self.enrichment_scheduled = False

    def _resume_enrichment(self):
        self.enrichment_scheduled = False
        if self.has_searched and self.raw_results:
            self._start_enrichment()

    def _render_grouped(self, grouped):
        self.clear_results()
        for anime in grouped:
            card = WorkCard(anime, mode="search", add_callback=self.add_to_library); card.clicked.connect(self.anime_selected); self.grid_layout.addWidget(card)
        self._reflow_cards()

    def search_error(self, message):
        self.search_button.setEnabled(True); self.is_loading = False
        rate_limited = "(429)" in message
        if self.raw_results and rate_limited:
            self.has_next_page = False
            self.clear_skeletons()
            grouped = group_media_results(self.raw_results)
            self._render_grouped(grouped)
            self.results_title.setText(f"{len(self.raw_results)} entries · {len(grouped)} series · AniList rate limit reached")
            return
        self.clear_results()
        if "(403)" in message and "temporarily disabled" in message.lower(): text = "AniList is temporarily unavailable.\nYour offline library still works."
        elif rate_limited: text = "AniList is rate-limiting requests.\nPlease try again shortly."
        elif "(5" in message[:20]: text = "AniList is having server problems.\nPlease try again later."
        else: text = f"Search failed.\n{message}"
        self.results_title.setText("Search unavailable"); self.show_message(text); retry = QPushButton("Try again"); retry.clicked.connect(self.search_clicked); self.grid_layout.addWidget(retry, 1, 0)

    def show_skeletons(self, count, append=False):
        if not append:
            self.clear_results()
        for _ in range(count):
            self.grid_layout.addWidget(SkeletonCard())
        self._reflow_cards()

    def clear_skeletons(self):
        for i in range(self.grid_layout.count() - 1, -1, -1):
            widget = self.grid_layout.itemAt(i).widget()
            if isinstance(widget, SkeletonCard):
                self.grid_layout.takeAt(i)
                widget.deleteLater()

    def show_message(self, text):
        panel = QFrame(); panel.setStyleSheet(f"background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 18px;")
        box = QVBoxLayout(panel); box.setContentsMargins(35, 60, 35, 60)
        label = QLabel(text); label.setAlignment(Qt.AlignCenter); label.setWordWrap(True); label.setStyleSheet(f"color: {COLORS['secondary']}; font-size: 14px; border: none;"); box.addWidget(label); self.grid_layout.addWidget(panel, 0, 0, 1, 4)

    def clear_results(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

    def resizeEvent(self, event):
        super().resizeEvent(event); self._reflow_cards()

    def _reflow_cards(self):
        widgets = []
        for i in range(self.grid_layout.count()):
            widget = self.grid_layout.itemAt(i).widget()
            if isinstance(widget, (WorkCard, SkeletonCard)):
                widgets.append(widget)
        for widget in widgets: self.grid_layout.removeWidget(widget)
        columns = max(1, self.results_scroll.viewport().width() // 230); columns = min(columns, max(1, len(widgets)))
        for col in range(columns): self.grid_layout.setColumnStretch(col, 1)
        for i, widget in enumerate(widgets):
            row = i // columns; row_count = min(columns, len(widgets) - row * columns); start_col = (columns - row_count) // 2
            self.grid_layout.addWidget(widget, row, start_col + (i % columns), Qt.AlignHCenter)
