from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from api import search_anime
from series import group_media_results
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


class SearchWorker(QObject):
    finished = Signal(object)
    error = Signal(str)
    def __init__(self, search_text, page, media_type, media_format):
        super().__init__()
        self.search_text, self.page = search_text, page
        self.media_type, self.media_format = media_type, media_format
    def run(self):
        try:
            self.finished.emit(search_anime(
                self.search_text,
                self.page,
                media_type=self.media_type,
                media_format=self.media_format,
            ))
        except Exception as error:
            self.error.emit(str(error))


class SearchPage(QWidget):
    anime_selected = Signal(object)
    def __init__(self, add_to_library):
        super().__init__()
        self.add_to_library = add_to_library
        self.current_search = ""
        self.current_media_type = "ANIME"
        self.current_media_format = None
        self.current_page = 1
        self.has_next_page = False
        self.is_loading = False
        self.threads, self.workers = [], []
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
        self.search = QLineEdit(); self.search.setPlaceholderText("Title, character, franchise..."); self.search.setMinimumHeight(46); self.search.setClearButtonEnabled(True)
        self.search_button = QPushButton("Search"); self.search_button.setMinimumHeight(46); self.search_button.setMinimumWidth(100)
        bar.addWidget(self.search, 1); bar.addWidget(self.search_button); panel.addLayout(bar)

        type_row = QHBoxLayout()
        type_label = QLabel("TYPE"); type_label.setObjectName("typeLabel")
        type_label.setStyleSheet(f"font-size: 10px; font-weight: 800; color: {COLORS['muted']}; letter-spacing: 1.5px; padding: 0; background: transparent; border: none;")
        type_row.addWidget(type_label, 0, Qt.AlignVCenter)
        self.media_filter = QComboBox(); self.media_filter.addItems(["Anime", "Manga", "Novels"]); self.media_filter.setMinimumWidth(130)
        type_row.addWidget(self.media_filter); type_row.addStretch(); panel.addLayout(type_row); root.addWidget(search_panel)

        result_head = QHBoxLayout()
        self.results_title = QLabel("Ready to search")
        self.results_title.setStyleSheet(f"font-size: 15px; font-weight: 750; color: {COLORS['primary']};")
        result_head.addWidget(self.results_title); result_head.addStretch(); root.addLayout(result_head)

        self.results_scroll = InfiniteScrollArea(); self.results_scroll.setWidgetResizable(True); self.results_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding); self.results_scroll.setFrameShape(QFrame.NoFrame)
        self.grid_container = QWidget(); self.grid_layout = QGridLayout(self.grid_container); self.grid_layout.setContentsMargins(4, 4, 4, 20); self.grid_layout.setHorizontalSpacing(22); self.grid_layout.setVerticalSpacing(30)
        self.results_scroll.setWidget(self.grid_container); self.results_scroll.scroll_to_bottom.connect(self.load_more_results); root.addWidget(self.results_scroll, 1)

        self.search_button.clicked.connect(self.search_clicked); self.search.returnPressed.connect(self.search_clicked); self.media_filter.currentIndexChanged.connect(self.media_filter_changed)

    def media_filter_changed(self):
        if self.current_search: self.search_clicked()

    def selected_media_filter(self):
        return {"Anime": ("ANIME", None), "Manga": ("MANGA", "MANGA"), "Novels": ("MANGA", "NOVEL")}[self.media_filter.currentText()]

    def search_clicked(self):
        text = self.search.text().strip()
        if not text or self.is_loading: return
        self.current_search = text; self.current_media_type, self.current_media_format = self.selected_media_filter(); self.current_page = 1; self.has_next_page = False; self.raw_results = []
        self.clear_results(); self.results_title.setText(f"Searching for “{text}”"); self.search_button.setEnabled(False); self.is_loading = True; self.start_search(text, 1)

    def load_more_results(self):
        if self.current_search and self.has_next_page and not self.is_loading:
            self.is_loading = True; self.start_search(self.current_search, self.current_page + 1)

    def start_search(self, text, page):
        thread = QThread(); worker = SearchWorker(text, page, self.current_media_type, self.current_media_format); worker.moveToThread(thread); thread.started.connect(worker.run)
        worker.finished.connect(self.search_finished); worker.error.connect(self.search_error); worker.finished.connect(thread.quit); worker.error.connect(thread.quit); thread.finished.connect(worker.deleteLater); thread.finished.connect(thread.deleteLater)
        self.threads.append(thread); self.workers.append(worker); thread.start()

    def search_finished(self, data):
        self.search_button.setEnabled(True); self.is_loading = False; self.current_page = data["pageInfo"]["currentPage"]; self.has_next_page = data["pageInfo"]["hasNextPage"]
        new_results = data["media"]
        if self.current_page == 1: self.raw_results = []
        self.raw_results.extend(new_results)

        grouped = group_media_results(self.raw_results)
        self.results_title.setText(f"{len(self.raw_results)} entries · {len(grouped)} series · page {self.current_page}")
        if not grouped and self.current_page == 1:
            self.show_message("No results found"); return

        self._render_grouped(grouped)

    def _render_grouped(self, grouped):
        self.clear_results()
        for anime in grouped:
            card = WorkCard(anime, mode="search", add_callback=self.add_to_library)
            card.clicked.connect(self.anime_selected)
            self.grid_layout.addWidget(card)
        self._reflow_cards()

    def search_error(self, message):
        self.search_button.setEnabled(True); self.is_loading = False; self.clear_results()
        if "(403)" in message and "temporarily disabled" in message.lower(): text = "AniList is temporarily unavailable.\nYour offline library still works."
        elif "(429)" in message: text = "AniList is rate-limiting requests.\nPlease try again shortly."
        elif "(5" in message[:20]: text = "AniList is having server problems.\nPlease try again later."
        else: text = f"Search failed.\n{message}"
        self.results_title.setText("Search unavailable"); self.show_message(text)
        retry = QPushButton("Try again"); retry.clicked.connect(self.search_clicked); self.grid_layout.addWidget(retry, 1, 0)

    def show_message(self, text):
        panel = QFrame(); panel.setStyleSheet(f"background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 18px;")
        box = QVBoxLayout(panel); box.setContentsMargins(35, 60, 35, 60)
        label = QLabel(text); label.setAlignment(Qt.AlignCenter); label.setWordWrap(True); label.setStyleSheet(f"color: {COLORS['secondary']}; font-size: 14px; border: none;")
        box.addWidget(label); self.grid_layout.addWidget(panel, 0, 0, 1, 4)

    def clear_results(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

    def resizeEvent(self, event):
        super().resizeEvent(event); self._reflow_cards()

    def _reflow_cards(self):
        cards = []
        for i in range(self.grid_layout.count()):
            widget = self.grid_layout.itemAt(i).widget()
            if isinstance(widget, WorkCard): cards.append(widget)
        for card in cards: self.grid_layout.removeWidget(card)
        columns = max(1, self.results_scroll.viewport().width() // 230); columns = min(columns, max(1, len(cards)))
        for col in range(columns): self.grid_layout.setColumnStretch(col, 1)
        for i, card in enumerate(cards):
            row = i // columns; row_count = min(columns, len(cards) - row * columns); start_col = (columns - row_count) // 2
            self.grid_layout.addWidget(card, row, start_col + (i % columns), Qt.AlignHCenter)
