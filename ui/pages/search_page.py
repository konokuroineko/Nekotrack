from threading import Event

from PySide6.QtCore import QObject, QThread, Qt, Signal, QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from api import get_media_by_anilist_url, parse_anilist_url, search_anime
from series import group_media_results
from ui.preferences import get
from ui.theme import COLORS
from ui.widgets.work_card import WorkCard


class InfiniteScrollArea(QScrollArea):
    scroll_to_bottom = Signal()

    def __init__(self):
        super().__init__()
        self.verticalScrollBar().valueChanged.connect(self._check)
        self._last_trigger = -1

    def _check(self):
        bar = self.verticalScrollBar()
        value = bar.value()
        threshold = max(0, bar.maximum() - 260)
        if value >= threshold and value != self._last_trigger:
            self._last_trigger = value
            self.scroll_to_bottom.emit()

    def reset_trigger(self):
        self._last_trigger = -1


class SkeletonCard(QFrame):
    """Fixed-size result placeholder used until a work card is ready."""

    def __init__(self, parent=None):
        super().__init__(parent)
        card_size = get("card_size")
        card_width = card_size + 8
        cover_height = round(card_size * 284 / 210)
        card_height = cover_height + 112
        self.setFixedSize(card_width, card_height)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setObjectName("skeleton")
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

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(8)

        cover = QFrame()
        cover.setObjectName("skeletonFill")
        cover.setFixedSize(card_size, cover_height)
        root.addWidget(cover, 0, Qt.AlignHCenter)

        title_line_1 = QFrame()
        title_line_1.setObjectName("skeletonFill")
        title_line_1.setFixedHeight(9)
        title_line_1.setFixedWidth(max(80, card_width - 26))

        title_line_2 = QFrame()
        title_line_2.setObjectName("skeletonFill")
        title_line_2.setFixedHeight(9)
        title_line_2.setFixedWidth(max(55, card_width - 70))

        meta = QFrame()
        meta.setObjectName("skeletonFill")
        meta.setFixedHeight(8)
        meta.setFixedWidth(max(70, card_width - 90))

        root.addWidget(title_line_1)
        root.addWidget(title_line_2)
        root.addWidget(meta)
        root.addStretch(1)


class SearchWorker(QObject):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, search_text, page, media_type, media_format, filters, include_relations=True):
        super().__init__()
        self.search_text = search_text
        self.page = page
        self.media_type = media_type
        self.media_format = media_format
        self.filters = filters
        self.include_relations = include_relations

    def run(self):
        try:
            if self.page == 1 and parse_anilist_url(self.search_text) is not None:
                media = get_media_by_anilist_url(
                    self.search_text,
                    include_relations=self.include_relations,
                )
                self.finished.emit(
                    {
                        "pageInfo": {
                            "currentPage": 1,
                            "lastPage": 1,
                            "hasNextPage": False,
                        },
                        "media": [media] if media else [],
                    }
                )
                return

            data = search_anime(
                self.search_text,
                self.page,
                media_type=self.media_type,
                media_format=self.media_format,
                include_relations=self.include_relations,
                **self.filters,
            )
            self.finished.emit(data)
        except Exception as error:
            self.error.emit(str(error))


class SeriesEnrichmentWorker(QObject):
    finished = Signal(int, object)
    error = Signal(int, str)

    def __init__(self, results, stop_event, generation):
        super().__init__()
        self.results = list(results)
        self.stop_event = stop_event
        self.generation = generation
        self.snapshot_count = len(self.results)

    def run(self):
        try:
            grouped = group_media_results(
                self.results,
                enrich=True,
                max_requests=0,
                delay=0.35,
                stop_event=self.stop_event,
            )
            self.finished.emit(
                self.generation,
                {
                    "snapshot_count": self.snapshot_count,
                    "grouped": grouped,
                },
            )
        except Exception as error:
            self.error.emit(self.generation, str(error))


class SearchPage(QWidget):
    anime_selected = Signal(object)

    def __init__(self, add_to_library, selection_mode=False):
        super().__init__()
        self.add_to_library = add_to_library
        self.selection_mode = selection_mode
        self.current_search = ""
        self.current_media_type = None
        self.current_media_format = None
        self.current_filters = {}
        self.current_page = 1
        self.has_next_page = False
        self.is_loading = False
        self.has_searched = False
        self.search_threads = []
        self.search_workers = []

        self.enrichment_thread = None
        self.enrichment_worker = None
        self.enrichment_stop = None
        self.enrichment_generation = 0
        self.enrichment_pending = False
        self.enrichment_restart_pending = False

        self.raw_results = []
        self.displayed_items = []
        self.pending_items = []
        self.pending_timer = None
        self.pending_batch_active = False
        self.pending_batch_generation = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(34, 30, 34, 28)
        root.setSpacing(20)

        intro = QVBoxLayout()
        intro.setSpacing(3)
        heading = QLabel("Discover")
        heading.setStyleSheet(f"font-size: 34px; font-weight: 850; color: {COLORS['primary']};")
        sub = QLabel("Search the AniList catalog and build your library.")
        sub.setStyleSheet(f"font-size: 12px; color: {COLORS['muted']};")
        intro.addWidget(heading)
        intro.addWidget(sub)
        root.addLayout(intro)

        search_panel = QFrame()
        search_panel.setStyleSheet(
            f"QFrame {{ background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 16px; }}"
        )
        panel = QVBoxLayout(search_panel)
        panel.setContentsMargins(12, 12, 12, 12)
        panel.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Title, character, franchise, or AniList link...")
        self.search.setMinimumHeight(46)
        self.search.setClearButtonEnabled(True)
        self.search_button = QPushButton("Search")
        self.search_button.setMinimumHeight(46)
        self.search_button.setMinimumWidth(100)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.search_button)
        panel.addLayout(bar)

        self.filters_button = QPushButton("Filters")
        self.filters_button.setFixedHeight(40)
        self.filters_button.setMinimumWidth(82)
        panel.addWidget(self.filters_button, 0, Qt.AlignLeft)

        self.filters_panel = QFrame()
        self.filters_panel.setVisible(False)
        self.filters_panel.setStyleSheet(
            f"QFrame {{ background: {COLORS['background']}; border: 1px solid {COLORS['border']}; border-radius: 12px; }} QLabel {{ background: transparent; border: none; }}"
        )
        filters_layout = QGridLayout(self.filters_panel)
        filters_layout.setContentsMargins(12, 12, 12, 12)
        filters_layout.setHorizontalSpacing(10)
        filters_layout.setVerticalSpacing(5)

        self.media_filter = self._make_combo(["All", "Anime", "Manga", "Novels"])
        self.format_filter = self._make_combo(["All", "TV", "TV Short", "Movie", "OVA", "ONA", "Special", "Music"])
        self.status_filter = self._make_combo(["All", "Finished", "Releasing", "Not Yet Released", "Cancelled", "Hiatus"])
        self.season_filter = self._make_combo(["All", "Winter", "Spring", "Summer", "Fall"])
        self.year_filter = QLineEdit()
        self.year_filter.setPlaceholderText("e.g. 2024")
        self.year_filter.setFixedHeight(38)
        self.min_score_filter = QComboBox()
        self.min_score_filter.addItems(["Any score", "50+", "60+", "70+", "80+", "90+"])
        self.min_score_filter.setFixedHeight(38)
        self.sort_filter = self._make_combo(["Relevance", "Popularity", "Score", "Newest", "Oldest", "Title A–Z", "Title Z–A"])
        self.genre_filter = QLineEdit()
        self.genre_filter.setPlaceholderText("e.g. Fantasy, Action")
        self.genre_filter.setFixedHeight(38)
        self.tag_filter = QLineEdit()
        self.tag_filter.setPlaceholderText("e.g. Isekai, Reincarnation")
        self.tag_filter.setFixedHeight(38)

        self.fast_search = QCheckBox("Fast Search")
        self.fast_search.setToolTip("Skip series and bundle enrichment. Results are shown directly from AniList.")
        self.fast_search.setCursor(Qt.PointingHandCursor)
        self.fast_search.stateChanged.connect(self.fast_search_changed)
        if self.selection_mode:
            self.fast_search.setChecked(True)
            self.fast_search.hide()

        fields = [
            ("Type", self.media_filter, 0, 0),
            ("Format", self.format_filter, 0, 1),
            ("Status", self.status_filter, 0, 2),
            ("Season", self.season_filter, 0, 3),
            ("Year", self.year_filter, 1, 0),
            ("Minimum score", self.min_score_filter, 1, 1),
            ("Sort", self.sort_filter, 1, 2),
            ("Genre", self.genre_filter, 1, 3),
            ("Tag", self.tag_filter, 2, 0),
        ]
        for label_text, widget, row, col in fields:
            label = QLabel(label_text)
            label.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {COLORS['muted']}; padding-left: 2px;")
            filters_layout.addWidget(label, row * 2, col)
            filters_layout.addWidget(widget, row * 2 + 1, col)

        filters_layout.addWidget(self.fast_search, 6, 0, 1, 2, Qt.AlignLeft)

        self.clear_filters_button = QPushButton("Clear filters")
        self.clear_filters_button.setFixedHeight(38)
        filters_layout.addWidget(self.clear_filters_button, 6, 2, 1, 2, Qt.AlignLeft)
        panel.addWidget(self.filters_panel)
        root.addWidget(search_panel)

        result_head = QHBoxLayout()
        self.results_title = QLabel("Ready to search")
        self.results_title.setStyleSheet(f"font-size: 15px; font-weight: 750; color: {COLORS['primary']};")
        result_head.addWidget(self.results_title)
        result_head.addStretch()
        root.addLayout(result_head)

        self.results_scroll = InfiniteScrollArea()
        self.results_scroll.setWidgetResizable(True)
        self.results_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.results_scroll.setFrameShape(QFrame.NoFrame)
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(4, 4, 4, 20)
        self.grid_layout.setHorizontalSpacing(22)
        self.grid_layout.setVerticalSpacing(30)
        self.results_scroll.setWidget(self.grid_container)
        self.results_scroll.scroll_to_bottom.connect(self.load_more_results)
        root.addWidget(self.results_scroll, 1)

        self.search_button.clicked.connect(self.search_clicked)
        self.search.returnPressed.connect(self.search_clicked)
        self.media_filter.currentIndexChanged.connect(self.media_filter_changed)
        self.filters_button.clicked.connect(self.toggle_filters)
        self.clear_filters_button.clicked.connect(self.clear_filters)
        self._refresh_format_filter()

    def _make_combo(self, items):
        combo = QComboBox()
        combo.addItems(items)
        combo.setFixedHeight(38)
        return combo

    def toggle_filters(self):
        visible = not self.filters_panel.isVisible()
        self.filters_panel.setVisible(visible)
        self.filters_button.setText("Hide filters" if visible else "Filters")

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
        if self.has_searched and not self.is_loading:
            self.search_clicked()

    def selected_media_filter(self):
        return {
            "All": (None, None),
            "Anime": ("ANIME", None),
            "Manga": ("MANGA", "MANGA"),
            "Novels": ("MANGA", "NOVEL"),
        }[self.media_filter.currentText()]

    def selected_filters(self):
        format_map = {
            "TV": "TV", "TV Short": "TV_SHORT", "Movie": "MOVIE", "OVA": "OVA",
            "ONA": "ONA", "Special": "SPECIAL", "Music": "MUSIC", "Manga": "MANGA",
            "Novel": "NOVEL", "One Shot": "ONE_SHOT",
        }
        status_map = {
            "Finished": "FINISHED", "Releasing": "RELEASING", "Not Yet Released": "NOT_YET_RELEASED",
            "Cancelled": "CANCELLED", "Hiatus": "HIATUS",
        }
        season_map = {"Winter": "WINTER", "Spring": "SPRING", "Summer": "SUMMER", "Fall": "FALL"}
        sort_map = {
            "Relevance": "SEARCH_MATCH", "Popularity": "POPULARITY_DESC", "Score": "SCORE_DESC",
            "Newest": "START_DATE_DESC", "Oldest": "START_DATE", "Title A–Z": "TITLE_ROMAJI",
            "Title Z–A": "TITLE_ROMAJI_DESC",
        }
        year = self.year_filter.text().strip()
        year = year if year.isdigit() and len(year) == 4 else None
        min_score = self.min_score_filter.currentText()
        min_score = int(min_score[:-1]) if min_score.endswith("+") else None
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

    def fast_search_changed(self, _state):
        # Switching modes on an existing result set should immediately rebuild
        # the results using the selected search mode.
        if self.has_searched and not self.is_loading:
            self.search_clicked()

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
        if self.has_searched and not self.is_loading:
            self.search_clicked()

    def search_clicked(self):
        text = self.search.text().strip()
        if self.is_loading:
            return

        self._stop_pending_render()
        self._stop_enrichment()
        self.enrichment_generation += 1
        self.enrichment_restart_pending = False

        self.current_search = text
        self.current_media_type, self.current_media_format = self.selected_media_filter()
        self.current_filters = self.selected_filters()
        self.current_page = 1
        self.has_next_page = False
        self.raw_results = []
        self.displayed_items = []
        self.pending_items = []
        self.pending_batch_active = False
        self.has_searched = True

        self._clear_results()
        self._append_skeletons(20)
        self.results_title.setText("Browsing AniList" if not text else f"Searching for \"{text}\"")
        self._start_search(1)

    def load_more_results(self):
        if (
            not self.has_searched
            or self.is_loading
            or self.enrichment_pending
            or self.pending_batch_active
            or not self.has_next_page
        ):
            return
        self.is_loading = True
        self._append_skeletons(20)
        self._start_search(self.current_page + 1)

    def _start_search(self, page):
        self.is_loading = True
        worker = SearchWorker(
            self.current_search,
            page,
            self.current_media_type,
            self.current_media_format,
            self.current_filters,
            include_relations=not self.fast_search.isChecked(),
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self.search_finished)
        worker.error.connect(self.search_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda t=thread, w=worker: self._search_thread_finished(t, w))
        self.search_threads.append(thread)
        self.search_workers.append(worker)
        thread.start()

    def _search_thread_finished(self, thread, worker):
        if thread in self.search_threads:
            self.search_threads.remove(thread)
        if worker in self.search_workers:
            self.search_workers.remove(worker)
        thread.deleteLater()

    def search_finished(self, data):
        self.search_button.setEnabled(True)
        self.is_loading = False
        self.current_page = data["pageInfo"]["currentPage"]
        self.has_next_page = data["pageInfo"]["hasNextPage"]

        new_results = data["media"]

        if self.current_page == 1:
            self.raw_results = []
        self.raw_results.extend(new_results)

        # Do not render a provisional grouping here.  Relation discovery is
        # what determines the real series/season bundle, so rendering this
        # search payload first can briefly show incorrect counts such as
        # "2 seasons" for Demon Slayer before enrichment catches up.
        if self.fast_search.isChecked():
            # Fast Search deliberately bypasses the entire series/bundle
            # enrichment pipeline and renders AniList's raw results directly.
            if self.current_page == 1:
                self._clear_results()
                self.displayed_items = []
            for item in new_results:
                self.displayed_items.append(item)
                self._replace_first_skeleton(item)
            self._update_results_title()
            self.results_scroll.reset_trigger()
            QTimer.singleShot(0, self.results_scroll._check)
            return

        self.pending_items = []
        self.pending_batch_active = False
        self.displayed_items = []
        self._update_results_title()
        self._start_enrichment()

    def _start_pending_render(self):
        self._stop_pending_render()
        if not self.pending_items:
            self.pending_batch_active = False
            self._update_results_title()
            self._start_enrichment()
            QTimer.singleShot(0, self.results_scroll.reset_trigger)
            QTimer.singleShot(0, self.results_scroll._check)
            return

        self.pending_batch_active = True
        self.pending_batch_generation += 1
        self.pending_timer = QTimer(self)
        self.pending_timer.setInterval(75)
        self.pending_timer.timeout.connect(self._render_next_item)
        self.pending_timer.start()
        self._render_next_item()

    def _render_next_item(self):
        if not self.pending_items:
            self._stop_pending_render()
            self.pending_batch_active = False
            self._update_results_title()
            self._start_enrichment()
            self.results_scroll.reset_trigger()
            QTimer.singleShot(0, self.results_scroll._check)
            return

        item = self.pending_items.pop(0)
        self.displayed_items.append(item)
        self._replace_first_skeleton(item)
        self._update_results_title()

        if not self.pending_items:
            self._stop_pending_render()
            self.pending_batch_active = False
            self._start_enrichment()
            self.results_scroll.reset_trigger()
            QTimer.singleShot(0, self.results_scroll._check)

    def _replace_first_skeleton(self, item):
        skeleton = None
        row = column = 0
        skeleton_candidates = []

        for index in range(self.grid_layout.count()):
            widget = self.grid_layout.itemAt(index).widget()
            if isinstance(widget, SkeletonCard):
                current_row, current_column, _, _ = self.grid_layout.getItemPosition(index)
                skeleton_candidates.append((current_row, current_column, widget))

        if skeleton_candidates:
            _, _, skeleton = min(
                skeleton_candidates,
                key=lambda value: (value[0], value[1]),
            )
            index = self.grid_layout.indexOf(skeleton)
            row, column, _, _ = self.grid_layout.getItemPosition(index)

        card = WorkCard(item, mode="search", add_callback=self.add_to_library, show_add_button=not self.selection_mode)
        card.clicked.connect(self.anime_selected)

        if skeleton is not None:
            self.grid_layout.removeWidget(skeleton)
            skeleton.deleteLater()
            self.grid_layout.addWidget(card, row, column, 1, 1, Qt.AlignHCenter)
        else:
            self.grid_layout.addWidget(card, 0, 0, 1, 1, Qt.AlignHCenter)

        self._reflow_results()

    def _append_skeletons(self, count):
        for _ in range(count):
            self.grid_layout.addWidget(SkeletonCard())
        self._reflow_results()

    def _trim_skeletons_to_pending(self):
        skeletons = [
            self.grid_layout.itemAt(index).widget()
            for index in range(self.grid_layout.count())
            if isinstance(self.grid_layout.itemAt(index).widget(), SkeletonCard)
        ]
        extra = max(0, len(skeletons) - len(self.pending_items))
        for skeleton in skeletons[:extra]:
            self.grid_layout.removeWidget(skeleton)
            skeleton.deleteLater()
        self._reflow_results()

    def _start_enrichment(self):
        if self.fast_search.isChecked():
            return
        if not self.raw_results:
            return

        if self.enrichment_thread is not None:
            self.enrichment_restart_pending = True
            return

        self.enrichment_pending = True
        self.enrichment_restart_pending = False
        self._update_results_title()
        stop_event = Event()
        thread = QThread(self)
        worker = SeriesEnrichmentWorker(list(self.raw_results), stop_event, self.enrichment_generation)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self.enrichment_finished)
        worker.error.connect(self.enrichment_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._enrichment_thread_finished)
        self.enrichment_stop = stop_event
        self.enrichment_thread = thread
        self.enrichment_worker = worker
        thread.start()

    def _enrichment_thread_finished(self):
        thread = self.enrichment_thread
        self.enrichment_thread = None
        self.enrichment_worker = None
        self.enrichment_stop = None
        if thread is not None:
            thread.deleteLater()

        if not self.has_searched:
            self.enrichment_pending = False
            self.enrichment_restart_pending = False
            return

        if self.enrichment_restart_pending:
            self.enrichment_restart_pending = False
            self.enrichment_pending = True
            QTimer.singleShot(0, self._start_enrichment)
        else:
            self.enrichment_pending = False
            self._update_results_title()

    def _stop_enrichment(self):
        if self.enrichment_stop is not None:
            self.enrichment_stop.set()
        self.enrichment_pending = False
        self.enrichment_restart_pending = False

    def enrichment_finished(self, generation, payload):
        if generation != self.enrichment_generation:
            return

        snapshot_count = payload.get("snapshot_count", -1) if isinstance(payload, dict) else -1
        grouped = payload.get("grouped", []) if isinstance(payload, dict) else payload

        # Pagination may have appended another page while this enrichment pass
        # was running. Never rebuild the UI from a stale snapshot; wait for the
        # replacement enrichment pass to process the newer result set instead.
        if snapshot_count != len(self.raw_results):
            self.enrichment_restart_pending = True
            return

        # The UI is held at skeleton state while enrichment runs, so once
        # the snapshot is complete we can replace the provisional grid in one
        # step and show only fully-resolved grouped results.
        self._render_grouped_preserving_skeletons(grouped, 0)

    def enrichment_error(self, generation, message):
        if generation != self.enrichment_generation:
            return
        if self.enrichment_restart_pending:
            return
        self.enrichment_pending = False
        self._update_results_title()

    def _render_grouped_preserving_skeletons(self, grouped, skeleton_count):
        self._clear_results()
        self.displayed_items = list(grouped)
        for item in grouped:
            card = WorkCard(item, mode="search", add_callback=self.add_to_library, show_add_button=not self.selection_mode)
            card.clicked.connect(self.anime_selected)
            self.grid_layout.addWidget(card)
        self._append_skeletons(skeleton_count)
        self._reflow_results()
        self._update_results_title()

    def _update_results_title(self):
        count = len(self.displayed_items)
        if self.is_loading:
            self.results_title.setText("Loading…")
        elif self.enrichment_pending:
            self.results_title.setText(f"{count} result{'s' if count != 1 else ''} · refining")
        elif self.fast_search.isChecked():
            self.results_title.setText(f"{count} result{'s' if count != 1 else ''} · fast")
        else:
            self.results_title.setText(f"{count} result{'s' if count != 1 else ''}")

    def _clear_results(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _stop_pending_render(self):
        if self.pending_timer is not None:
            self.pending_timer.stop()
            self.pending_timer.deleteLater()
            self.pending_timer = None

    def _reflow_results(self):
        widgets = []
        for index in range(self.grid_layout.count()):
            widget = self.grid_layout.itemAt(index).widget()
            if isinstance(widget, (WorkCard, SkeletonCard)):
                row, column, _, _ = self.grid_layout.getItemPosition(index)
                widgets.append((row, column, widget))

        if not widgets:
            return

        widgets.sort(key=lambda value: (value[0], value[1]))
        ordered_widgets = [widget for _, _, widget in widgets]

        for index in range(self.grid_layout.count() - 1, -1, -1):
            self.grid_layout.takeAt(index)

        width = max(1, self.results_scroll.viewport().width())
        columns = max(1, width // 230)
        columns = min(columns, len(ordered_widgets))

        for col in range(columns):
            self.grid_layout.setColumnStretch(col, 1)

        for i, widget in enumerate(ordered_widgets):
            row = i // columns
            column = i % columns
            self.grid_layout.addWidget(
                widget,
                row,
                column,
                1,
                1,
                Qt.AlignHCenter,
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow_results()

    def _start_search_error(self, message):
        self.is_loading = False
        self.search_button.setEnabled(True)
        self._stop_pending_render()
        self.pending_items = []
        self.pending_batch_active = False
        self._update_results_title()
        if "429" in message or "too many requests" in message.lower():
            self._update_results_title()
            return
        self._clear_results()
        label = QLabel(f"Search failed: {message}")
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {COLORS['muted']}; padding: 30px;")
        self.grid_layout.addWidget(label, 0, 0, 1, 1, Qt.AlignHCenter)

    def search_error(self, message):
        self._start_search_error(message)

    def closeEvent(self, event):
        self.shutdown_workers()
        super().closeEvent(event)

    def shutdown_workers(self):
        self._stop_pending_render()
        self._stop_enrichment()
        for thread in list(self.search_threads):
            thread.quit()
            thread.wait(1500)
        if self.enrichment_thread is not None:
            self.enrichment_thread.quit()
            self.enrichment_thread.wait(3000)
        self.search_threads.clear()
        self.search_workers.clear()