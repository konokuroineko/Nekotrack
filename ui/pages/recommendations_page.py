"""Recommendations grounded in titles already saved in the local library."""

import threading
import time

from PySide6.QtCore import QObject, QPoint, QRect, QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from api import get_anime_discovery_page, get_media_recommendations
from database import (
    get_all_library,
    get_entity_favorites,
    get_recommendation_credit_profile,
    get_recommendation_history,
    get_work_favorites,
    record_recommendation_impressions,
    set_recommendation_feedback,
)
from diagnostics import log_exception
from ui.preferences import get
from ui.theme import COLORS
from recommendation_engine import (
    credit_profile_from_media_record,
    inject_rare_exploration,
    rank_candidates,
)
from ui.widgets.work_card import WorkCard


class RecommendationWorker(QObject):
    """Collect personalized seeds plus one bounded real anime-catalog batch."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self, library_rows, stop_event=None, catalog_page=1,
        existing_ids=None, refresh_cycle=0, fetch_seeds=True,
    ):
        super().__init__()
        self.library_rows = [dict(row) for row in (library_rows or []) if isinstance(row, dict)]
        self.stop_event = stop_event or threading.Event()
        self.catalog_page = max(1, self._safe_int(catalog_page, 1))
        self.catalog_next_page = self.catalog_page
        self.catalog_has_next = True
        self.existing_ids = {
            value for item in (existing_ids or [])
            if (value := self._work_id({"id": item})) is not None
        }
        self.refresh_cycle = self._safe_int(refresh_cycle, 0)
        self.fetch_seeds = bool(fetch_seeds)
        self.catalog_only = not self.fetch_seeds
        self.history = {}
        self.favorite_works = []
        self.favorite_entities = []
        self.credit_profile = {}
        self.source_weights = {}
        self.voice_language = str(get("recommendation_voice_language") or "ALL").upper()
        self.error_messages = []

    @staticmethod
    def _safe_int(value, default=0):
        if isinstance(value, bool):
            return default
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return default

    @staticmethod
    def _work_id(work):
        try:
            work_id = int(work.get("id"))
        except (TypeError, ValueError, OverflowError):
            return None
        return work_id if work_id > 0 else None

    @staticmethod
    def _title(work):
        title = work.get("title")
        if isinstance(title, dict):
            return str(title.get("english") or title.get("romaji") or title.get("native") or "Untitled")
        return str(title or "Untitled")

    @classmethod
    def _media_type(cls, work):
        return str(work.get("type") or "").strip().upper()

    @staticmethod
    def _seed_strength(work, favorite_ids, history):
        work_id = RecommendationWorker._work_id(work)
        state = history.get(work_id, {}) if work_id is not None else {}
        status = str(work.get("status") or "").casefold()
        score = 0.0
        if work_id in favorite_ids or work.get("_is_favorite"):
            score += 24.0
        if isinstance(state, dict) and state.get("feedback") == "like":
            score += 30.0
        score += {
            "watching": 12.0, "rewatching": 11.0, "reading": 12.0,
            "completed": 8.0, "planning": 3.0, "plan to watch": 3.0,
            "plan to read": 3.0,
        }.get(status, 0.0)
        try:
            rating = float(work.get("rating") or 0)
            if rating > 10:
                rating /= 10.0
            if 0 <= rating <= 10:
                score += rating * 1.5
        except (TypeError, ValueError, OverflowError):
            pass
        if RecommendationWorker._media_type(work) == "ANIME":
            score += 1.0
        return score

    def _read_learning_data(self):
        try:
            value = get_recommendation_history()
            self.history = value if isinstance(value, dict) else {}
        except Exception as error:
            self.history = {}
            log_exception("recommendations.history_read_failed", error)
        try:
            value = get_work_favorites()
            self.favorite_works = [dict(row) for row in (value or []) if isinstance(row, dict)]
        except Exception as error:
            self.favorite_works = []
            log_exception("recommendations.favorites_read_failed", error)
        try:
            value = get_entity_favorites()
            self.favorite_entities = [dict(row) for row in (value or []) if isinstance(row, dict)]
        except Exception as error:
            self.favorite_entities = []
            log_exception("recommendations.entity_favorites_read_failed", error)

    def _merge_candidate(self, suggestions, candidate, known_ids, source_id=None, source_title=None, catalog=False):
        if not isinstance(candidate, dict):
            return False
        work_id = self._work_id(candidate)
        if work_id is None or work_id in known_ids:
            return False
        kind = self._media_type(candidate)
        if kind not in {"ANIME", "MANGA"}:
            return False
        feedback = self.history.get(work_id, {})
        if isinstance(feedback, dict) and feedback.get("feedback") == "dislike":
            return False

        entry = suggestions.get(work_id)
        if entry is None:
            entry = dict(candidate)
            entry["_recommendation_source_ids"] = []
            entry["_recommendation_source_titles"] = []
            entry["_recommendation_count"] = 0
            entry["_recommendation_catalog_source"] = False
            suggestions[work_id] = entry
        else:
            # Keep richer metadata if one candidate source returned more fields.
            for key, value in candidate.items():
                if key not in entry or entry.get(key) in (None, "", [], {}):
                    entry[key] = value

        if source_id is not None and source_id not in entry["_recommendation_source_ids"]:
            entry["_recommendation_source_ids"].append(source_id)
            entry["_recommendation_source_titles"].append(str(source_title or "a saved title"))
            entry["_recommendation_count"] += 1
        if catalog:
            entry["_recommendation_catalog_source"] = True
            cover = entry.get("coverImage")
            if isinstance(cover, dict) and cover.get("large"):
                entry.setdefault("cover_url", cover["large"])
            start_date = entry.get("startDate")
            if isinstance(start_date, dict) and start_date.get("year") is not None:
                entry.setdefault("start_year", start_date["year"])
        return True

    def run(self):
        self._read_learning_data()
        if self.stop_event.is_set():
            self.finished.emit([])
            return

        known_ids = set(self.existing_ids)
        seeds_by_id = {}
        for row in self.library_rows:
            work_id = self._work_id(row)
            if work_id is None:
                continue
            known_ids.add(work_id)
            if self._media_type(row) in {"ANIME", "MANGA"}:
                seeds_by_id.setdefault(work_id, dict(row))

        favorite_ids = set()
        for work in self.favorite_works:
            work_id = self._work_id(work)
            if work_id is None:
                continue
            favorite_ids.add(work_id)
            known_ids.add(work_id)
            if self._media_type(work) in {"ANIME", "MANGA"}:
                seeds_by_id.setdefault(work_id, dict(work))

        # A positively rated recommendation can seed future discovery even before
        # the user chooses to add that work to their Library.
        for work_id, state in self.history.items():
            if not isinstance(state, dict) or state.get("feedback") != "like":
                continue
            metadata = state.get("metadata")
            if not isinstance(metadata, dict) or self._media_type(metadata) not in {"ANIME", "MANGA"}:
                continue
            safe_id = self._work_id(metadata) or self._work_id({"id": work_id})
            if safe_id is None:
                continue
            known_ids.add(safe_id)
            seeds_by_id.setdefault(safe_id, dict(metadata))

        source_rows = {}

        def merge_source_record(raw_record):
            if not isinstance(raw_record, dict):
                return
            work_id = self._work_id(raw_record)
            if work_id is None:
                return
            merged = source_rows.setdefault(work_id, {})
            for key, value in raw_record.items():
                if value in (None, "", [], {}):
                    continue
                if merged.get(key) in (None, "", [], {}):
                    merged[key] = value
                    continue
                if key in {"characters", "staff"} and isinstance(value, dict) and isinstance(merged.get(key), dict):
                    old_edges = merged[key].get("edges")
                    new_edges = value.get("edges")
                    if isinstance(old_edges, list) and isinstance(new_edges, list):
                        seen_credit_keys = set()
                        combined = []
                        for edge in old_edges + new_edges:
                            if not isinstance(edge, dict):
                                continue
                            node = edge.get("node") if isinstance(edge.get("node"), dict) else {}
                            credit_id = self._safe_int(node.get("id"), 0)
                            credit_key = (credit_id, str(edge.get("role") or "").casefold())
                            if credit_id > 0 and credit_key not in seen_credit_keys:
                                seen_credit_keys.add(credit_key)
                                combined.append(edge)
                        merged[key] = {"edges": combined[:60]}

        for row in self.library_rows:
            merge_source_record(dict(row))
        for row in self.favorite_works:
            merge_source_record(dict(row))
        favorite_source_ids = {
            self._work_id(item) for item in self.favorite_works
            if self._work_id(item) is not None
        }
        for raw_id, state in self.history.items():
            if not isinstance(state, dict):
                continue
            try:
                history_work_id = int(raw_id)
            except (TypeError, ValueError, OverflowError):
                history_work_id = 0
            if state.get("feedback") != "like" and history_work_id not in favorite_source_ids:
                continue
            metadata = state.get("metadata")
            if not isinstance(metadata, dict):
                continue
            if self._work_id(metadata) is None:
                try:
                    metadata = {"id": int(raw_id), **metadata}
                except (TypeError, ValueError, OverflowError):
                    continue
            merge_source_record(metadata)

        try:
            self.credit_profile = get_recommendation_credit_profile(list(source_rows))
            if not isinstance(self.credit_profile, dict):
                self.credit_profile = {}
        except Exception as error:
            self.credit_profile = {}
            log_exception("recommendations.credit_profile_read_failed", error)

        for work_id, record in source_rows.items():
            remote_credits = credit_profile_from_media_record(record)
            profile = self.credit_profile.setdefault(
                work_id, {"characters": [], "voice_actors": [], "staff": []}
            )
            for kind in ("characters", "voice_actors", "staff"):
                local_values = profile.get(kind)
                if not isinstance(local_values, list):
                    local_values = []
                local_values.extend(remote_credits[kind])
                profile[kind] = local_values

        favorites_ids = {
            self._work_id(item) for item in self.favorite_works
            if self._work_id(item) is not None
        }
        self.source_weights = {}
        for work_id, row in source_rows.items():
            state = self.history.get(work_id, self.history.get(str(work_id), {}))
            feedback = state.get("feedback") if isinstance(state, dict) else None
            status = str(row.get("status") or "").strip().casefold()
            weight = 1.0
            if work_id in favorites_ids or row.get("_is_favorite"):
                weight += 1.2
            if feedback == "like":
                weight += 1.8
            if status in {"watching", "rewatching", "reading", "in progress"}:
                weight += 0.75
            elif status == "completed":
                weight += 0.45
            try:
                rating = float(row.get("rating") or 0)
                if rating > 10:
                    rating /= 10.0
                if 0 <= rating <= 10:
                    weight += min(0.9, rating * 0.09)
            except (TypeError, ValueError, OverflowError):
                pass
            weight = min(3.5, max(0.35, weight))
            self.source_weights[work_id] = weight
            if work_id in self.credit_profile and isinstance(self.credit_profile[work_id], dict):
                self.credit_profile[work_id]["_source_weight"] = weight

        suggestions = {}
        errors = []
        successful_sources = 0

        if self.fetch_seeds:
            seeds = sorted(
                seeds_by_id.values(),
                key=lambda work: (
                    -self._seed_strength(work, favorite_ids, self.history),
                    self._title(work).casefold(),
                    self._work_id(work) or 0,
                ),
            )[:8]
            for seed in seeds:
                if self.stop_event.is_set():
                    self.finished.emit([])
                    return
                seed_id = self._work_id(seed)
                if seed_id is None:
                    continue
                try:
                    records = get_media_recommendations(seed_id, per_page=25)
                    successful_sources += 1
                except Exception as error:
                    errors.append(error)
                    self.error_messages.append(str(error))
                    log_exception(
                        "recommendations.seed_fetch_failed",
                        error,
                        work_id=seed_id,
                    )
                    continue
                for record in records or []:
                    if self.stop_event.is_set():
                        self.finished.emit([])
                        return
                    self._merge_candidate(
                        suggestions, record, known_ids,
                        source_id=seed_id, source_title=self._title(seed),
                    )

        # Catalog discovery is a permanent, paginated source, not just an empty
        # library placeholder. Initial load is bounded to one page; scroll-driven
        # continuation works through up to three provider pages per background batch.
        requested_page = self.catalog_page
        pages_this_batch = 0
        max_pages = 1 if self.fetch_seeds else 3
        new_catalog_candidates = 0
        sort_options = ("POPULARITY_DESC", "SCORE_DESC", "START_DATE_DESC", "ID_DESC")
        catalog_sort = sort_options[self.refresh_cycle % len(sort_options)]
        self.catalog_has_next = True
        self.catalog_next_page = requested_page

        while pages_this_batch < max_pages and not self.stop_event.is_set():
            try:
                payload = get_anime_discovery_page(
                    page=requested_page, per_page=25, sort=catalog_sort
                )
                successful_sources += 1
            except Exception as error:
                errors.append(error)
                self.error_messages.append(str(error))
                log_exception(
                    "recommendations.catalog_fetch_failed",
                    error,
                    page=requested_page,
                )
                self.catalog_next_page = requested_page
                self.catalog_has_next = True
                break

            pages_this_batch += 1
            page_info = payload.get("pageInfo") if isinstance(payload, dict) else {}
            page_info = page_info if isinstance(page_info, dict) else {}
            current_page = max(1, self._safe_int(page_info.get("currentPage"), requested_page))
            last_page = max(current_page, self._safe_int(page_info.get("lastPage"), current_page))
            has_next = page_info.get("hasNextPage")
            self.catalog_has_next = bool(has_next) if isinstance(has_next, bool) else current_page < last_page
            self.catalog_next_page = current_page + 1 if self.catalog_has_next else current_page

            media = payload.get("media") if isinstance(payload, dict) else []
            if isinstance(media, list):
                for candidate in media:
                    if self.stop_event.is_set():
                        self.finished.emit([])
                        return
                    if self._merge_candidate(suggestions, candidate, known_ids, catalog=True):
                        new_catalog_candidates += 1

            if self.fetch_seeds or not self.catalog_has_next or new_catalog_candidates >= 12:
                break
            requested_page = self.catalog_next_page
            # The existing IDs are filtered before insertion, so a provider page
            # containing only duplicates cannot create an infinite retry loop.

        if self.stop_event.is_set():
            self.finished.emit([])
            return
        if successful_sources == 0 and errors:
            self.failed.emit(
                "AniList discovery could not be loaded. Check your connection and try again."
            )
            return

        ranked = rank_candidates(
            suggestions.values(),
            history=self.history,
            favorite_works=self.favorite_works,
            rotation=self.refresh_cycle,
            credit_profile=self.credit_profile,
            favorite_entities=self.favorite_entities,
            voice_language=self.voice_language,
        )
        ranked = inject_rare_exploration(ranked, rotation=self.refresh_cycle, fraction=0.04)
        self.finished.emit(ranked)


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
        # A Home refresh can arrive while AniList is still being queried.
        # Keep the latest snapshot and restart only after the current QThread exits.
        self._pending_refresh = None
        self._shutting_down = False
        self._refresh_cycle = 0
        self._catalog_page = 1
        self._catalog_has_next = True
        self._candidate_ids = set()
        self._loading_more = False
        self._load_more_failed = False
        self._visibility_viewport = None
        self._active_scroll_bar = None
        self._tiles = []
        self._exposure_visible_since = {}
        self._exposure_counted = {}
        self._history = {}
        self._favorite_works = []
        self._favorite_entities = []
        self._credit_profile = {}
        self._source_weights = {}
        self._voice_language = str(get("recommendation_voice_language") or "ALL").upper()
        self._impression_timer = QTimer(self)
        self._impression_timer.setInterval(500)
        self._impression_timer.timeout.connect(self._track_visible_impressions)
        self._impression_timer.start()
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
        if self.scroll is not None:
            self.set_visibility_viewport(self.scroll.viewport(), self.scroll.verticalScrollBar())
        self._apply_theme()

    def set_visibility_viewport(self, viewport, scroll_bar=None):
        """Use the actual Home or Recommendations viewport for pagination and impressions."""
        self._visibility_viewport = viewport
        self._active_scroll_bar = scroll_bar
        if scroll_bar is None and self.scroll is not None:
            self._active_scroll_bar = self.scroll.verticalScrollBar()
        if self._active_scroll_bar is not None:
            try:
                self._active_scroll_bar.valueChanged.disconnect(self._scroll_value_changed)
            except (TypeError, RuntimeError):
                pass
            self._active_scroll_bar.valueChanged.connect(self._scroll_value_changed)

    def _scroll_value_changed(self, _value):
        self._maybe_load_more()

    def _active_scrollbar(self):
        if self._active_scroll_bar is not None:
            return self._active_scroll_bar
        if self.scroll is not None:
            return self.scroll.verticalScrollBar()
        return None

    def _maybe_load_more(self):
        if not self._catalog_has_next or self._loading_more or self._shutting_down:
            return
        bar = self._active_scrollbar()
        if bar is None or bar.maximum() <= 0:
            return
        threshold = max(200, int((self._visibility_viewport.height() if self._visibility_viewport else 600) * 0.45))
        if bar.value() >= max(0, bar.maximum() - threshold):
            self.load_more()

    def _track_visible_impressions(self):
        viewport = self._visibility_viewport
        if viewport is None or not viewport.isVisible() or self._shutting_down:
            return
        now = time.monotonic()
        pending_impressions = []
        for tile, work in list(self._tiles):
            work_id = RecommendationWorker._work_id(work)
            if work_id is None:
                continue
            visible = False
            try:
                if tile.isVisible():
                    tile_rect = QRect(tile.mapTo(viewport, QPoint(0, 0)), tile.size())
                    intersection = tile_rect.intersected(viewport.rect())
                    total_area = max(1, tile_rect.width() * tile_rect.height())
                    visible_area = max(0, intersection.width()) * max(0, intersection.height())
                    visible = not intersection.isEmpty() and visible_area / total_area >= 0.50
            except RuntimeError:
                continue

            if not visible:
                self._exposure_visible_since.pop(work_id, None)
                self._exposure_counted[work_id] = False
                continue
            self._exposure_visible_since.setdefault(work_id, now)
            if self._exposure_counted.get(work_id, False):
                continue
            if now - self._exposure_visible_since[work_id] < 1.25:
                continue
            pending_impressions.append((work_id, work))

        if not pending_impressions:
            return
        try:
            record_recommendation_impressions([work for _work_id, work in pending_impressions])
            for work_id, _work in pending_impressions:
                self._exposure_counted[work_id] = True
            history = get_recommendation_history()
            self._history = history if isinstance(history, dict) else {}
        except Exception as error:
            log_exception(
                "recommendations.impression_record_failed",
                error,
                work_ids=[work_id for work_id, _work in pending_impressions],
            )

    def load_more(self):
        if (
            self._shutting_down or self._thread is not None or self._loading_more
            or not self._catalog_has_next
        ):
            return
        self._loading_more = True
        self._load_more_failed = False
        if hasattr(self, "more_status"):
            self.more_status.setText("Finding more anime from AniList…")
        if hasattr(self, "load_more_button"):
            self.load_more_button.setEnabled(False)
        worker = RecommendationWorker(
            self._library_snapshot,
            self._stop_event,
            catalog_page=self._catalog_page,
            existing_ids=self._candidate_ids,
            refresh_cycle=self._refresh_cycle,
            fetch_seeds=False,
        )
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
            "A learning feed built from your collection, saved favorites, feedback, and the wider anime catalog."
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
        if self._shutting_down:
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
        self._library_snapshot = rows

        # Never replace a widget/worker while its thread is alive. If the
        # library changed (or the user explicitly refreshes), cancel the
        # current result, remember the newest snapshot, and restart in the
        # thread-finished callback. The stop event also suppresses stale results.
        if self._thread is not None:
            pending_force = bool(force) or bool(
                self._pending_refresh is not None and self._pending_refresh[0]
            )
            try:
                thread_running = self._thread.isRunning()
            except RuntimeError:
                thread_running = False

            if (
                thread_running
                and self._pending_refresh is None
                and not pending_force
                and signature == self._library_signature
            ):
                return

            self._pending_refresh = (pending_force, rows)
            self._stop_event.set()
            return

        if self._loaded and not force and signature == self._library_signature:
            self._render_results()
            return

        self._refresh_cycle += 1
        self._results = []
        self._candidate_ids = set()
        self._catalog_page = 1
        self._catalog_has_next = True
        self._load_more_failed = False
        self._loading_more = False
        self._stop_event = threading.Event()
        self._clear_content()
        self.content_layout.addWidget(self._header())
        self.status = QLabel("Finding recommendations from your saved titles…")
        self.status.setObjectName("recommendationsStatus")
        self.status.setWordWrap(True)
        self.content_layout.addWidget(self.status)
        self._library_signature = signature

        worker = RecommendationWorker(
            rows,
            self._stop_event,
            catalog_page=1,
            existing_ids=set(),
            refresh_cycle=self._refresh_cycle,
            fetch_seeds=True,
        )
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
        worker = self._worker
        incoming = [dict(item) for item in (results or []) if isinstance(item, dict)]
        if worker is not None:
            self._catalog_page = max(1, worker.catalog_next_page)
            self._catalog_has_next = bool(worker.catalog_has_next)
            self._history = dict(worker.history or {})
            self._favorite_works = list(worker.favorite_works or [])
            self._favorite_entities = list(worker.favorite_entities or [])
            self._credit_profile = dict(worker.credit_profile or {})
            self._source_weights = dict(worker.source_weights or {})
            self._voice_language = str(worker.voice_language or "ALL")
            self._loading_more = False
        if worker is not None and worker.catalog_only:
            existing = {
                RecommendationWorker._work_id(item) for item in self._results
            }
            self._results.extend(
                item for item in incoming
                if RecommendationWorker._work_id(item) not in existing
            )
        else:
            self._results = incoming
        self._results = inject_rare_exploration(
            rank_candidates(
                self._results,
                history=self._history,
                favorite_works=self._favorite_works,
                rotation=self._refresh_cycle,
                credit_profile=self._credit_profile,
                favorite_entities=self._favorite_entities,
                voice_language=self._voice_language,
            ),
            rotation=self._refresh_cycle,
            fraction=0.04,
        )
        self._candidate_ids = {
            work_id for item in self._results
            if (work_id := RecommendationWorker._work_id(item)) is not None
        }
        self._loaded = True
        self._load_more_failed = False
        self._render_results(preserve_scroll=bool(worker is not None and worker.catalog_only))

    def _recommendations_failed(self, message):
        if self._stop_event.is_set():
            return
        worker = self._worker
        if worker is not None and worker.catalog_only and self._results:
            self._loading_more = False
            self._load_more_failed = True
            self.more_status.setText(
                "More titles could not be loaded. Your current feed is still available; retry below."
            )
            self.load_more_button.setEnabled(True)
            return
        self._loaded = False
        self._loading_more = False
        self._clear_content()
        self.content_layout.addWidget(self._header())
        label = QLabel(message)
        label.setObjectName("recommendationsStatus")
        label.setWordWrap(True)
        self.content_layout.addWidget(label)
        retry = QPushButton("Retry discovery")
        retry.setObjectName("recommendationsRefresh")
        retry.clicked.connect(lambda: self.refresh(force=True))
        self.content_layout.addWidget(retry, 0, Qt.AlignmentFlag.AlignLeft)
        self.content_layout.addStretch(1)

    def _thread_finished(self, thread):
        # Ignore a stale completion signal if another lifecycle already took
        # ownership of the current worker.
        if self._thread is not thread:
            return

        self._thread = None
        self._worker = None
        self._loading_more = False

        if self._shutting_down:
            self._pending_refresh = None
            return

        pending = self._pending_refresh
        self._pending_refresh = None
        if pending is not None:
            force, rows = pending
            self.refresh(force=force, library_rows=rows)
            return

        button = self.findChild(QPushButton, "recommendationsRefresh")
        if button is not None:
            button.setEnabled(True)
        self._update_load_more_ui()
        QTimer.singleShot(0, self._maybe_load_more)

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

    def _render_results(self, preserve_scroll=True):
        old_bar = self._active_scrollbar()
        old_value = old_bar.value() if preserve_scroll and old_bar is not None else 0
        self._clear_content()
        self._tiles = []
        self.content_layout.addWidget(self._header())
        if not self._results:
            self._render_empty(
                "AniList did not return any usable titles for this batch. Retry discovery or use Search to explore the catalog."
            )
            return

        summary = QLabel(
            f"{len(self._results)} suggestions · titles already in your Library and explicit dislikes are excluded"
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
            self.width() if self.embedded else (
                self.scroll.viewport().width() or self.width() - 320
            ),
        )
        poster_width = int(get("card_size") or 210) + 8
        columns = max(2, min(5, (available_width - 50) // (poster_width + 16)))
        for index, work in enumerate(self._results):
            tile = QFrame()
            tile.setObjectName("recommendationsTile")
            layout = QVBoxLayout(tile)
            layout.setContentsMargins(5, 5, 5, 10)
            layout.setSpacing(7)
            card = WorkCard(
                work, mode="search", add_callback=self.add_callback,
                show_add_button=True, parent=tile,
            )
            card.clicked.connect(self.work_selected.emit)
            layout.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)

            reason = str(work.get("_recommendation_reason") or "Discovered from AniList")
            reason_label = QLabel(reason)
            reason_label.setObjectName("recommendationsReason")
            reason_label.setWordWrap(True)
            layout.addWidget(reason_label)

            work_id = RecommendationWorker._work_id(work)
            state = self._history.get(work_id, {}) if work_id is not None else {}
            feedback = state.get("feedback") if isinstance(state, dict) else None
            feedback_row = QHBoxLayout()
            feedback_row.setSpacing(6)
            like = QPushButton("♥" if feedback == "like" else "♡")
            like.setObjectName("recommendationsFeedback")
            like.setCheckable(True)
            like.setChecked(feedback == "like")
            like.setAccessibleName(
                "Remove recommendation like" if feedback == "like" else "Like recommendation"
            )
            like.setToolTip(
                "Your feedback improves future recommendations. Click to "
                + ("remove this like." if feedback == "like" else "like this title.")
            )
            like.setEnabled(work_id is not None)
            like.clicked.connect(
                lambda checked, item=dict(work): self._feedback_changed(
                    item, "like" if checked else None
                )
            )
            dislike = QPushButton("×")
            dislike.setObjectName("recommendationsFeedback")
            dislike.setCheckable(True)
            dislike.setChecked(feedback == "dislike")
            dislike.setAccessibleName("Not interested in this recommendation")
            dislike.setToolTip("Show fewer titles like this and stop recommending this title.")
            dislike.setEnabled(work_id is not None)
            dislike.clicked.connect(
                lambda checked, item=dict(work): self._feedback_changed(
                    item, "dislike" if checked else None
                )
            )
            feedback_row.addWidget(like)
            feedback_row.addWidget(dislike)
            feedback_row.addStretch(1)
            layout.addLayout(feedback_row)
            grid.addWidget(tile, index // columns, index % columns, Qt.AlignmentFlag.AlignTop)
            self._tiles.append((tile, dict(work)))

        self.content_layout.addWidget(grid_host)
        self.more_status = QLabel()
        self.more_status.setObjectName("recommendationsStatus")
        self.more_status.setWordWrap(True)
        self.content_layout.addWidget(self.more_status)
        self.load_more_button = QPushButton("Load more")
        self.load_more_button.setObjectName("recommendationsRefresh")
        self.load_more_button.clicked.connect(self.load_more)
        self.content_layout.addWidget(self.load_more_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.content_layout.addStretch(1)
        self._update_load_more_ui()
        self._apply_theme()
        if preserve_scroll and old_bar is not None:
            QTimer.singleShot(0, lambda bar=old_bar, value=old_value: bar.setValue(min(value, bar.maximum())))

    def _feedback_changed(self, work, feedback):
        work_id = RecommendationWorker._work_id(work)
        if work_id is None:
            return
        try:
            if not set_recommendation_feedback(work_id, feedback, work):
                raise RuntimeError("The recommendation feedback could not be saved.")
            value = get_recommendation_history()
            self._history = value if isinstance(value, dict) else {}
        except Exception as error:
            log_exception(
                "recommendations.feedback_save_failed",
                error,
                work_id=work_id,
                feedback=feedback,
            )
            if hasattr(self, "more_status"):
                self.more_status.setText("Your feedback could not be saved. Please try again.")
            return
        self._results = inject_rare_exploration(
            rank_candidates(
                self._results,
                history=self._history,
                favorite_works=self._favorite_works,
                rotation=self._refresh_cycle,
                credit_profile=self._credit_profile,
                favorite_entities=self._favorite_entities,
                voice_language=self._voice_language,
            ),
            rotation=self._refresh_cycle,
            fraction=0.04,
        )
        self._candidate_ids = {
            value for item in self._results
            if (value := RecommendationWorker._work_id(item)) is not None
        }
        self._render_results(preserve_scroll=True)

    def _update_load_more_ui(self):
        button = getattr(self, "load_more_button", None)
        status = getattr(self, "more_status", None)
        if button is None or status is None:
            return
        if self._loading_more:
            button.setEnabled(False)
            status.setText("Finding more anime from AniList…")
        elif self._load_more_failed:
            button.setEnabled(True)
            button.setText("Retry loading more")
            status.setText(
                "More titles could not be loaded. Your current feed is still available."
            )
        elif self._catalog_has_next:
            button.setEnabled(True)
            button.setText("Load more")
            status.setText("Scroll near the end of the feed to discover more titles, or load more now.")
        else:
            button.setEnabled(False)
            button.setText("Catalog exhausted")
            status.setText("You've reached the end of the currently available AniList catalog pages.")


    def _clear_content(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def request_shutdown(self):
        self._shutting_down = True
        self._impression_timer.stop()
        self._pending_refresh = None
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
            QPushButton#recommendationsFeedback {{
                background:{COLORS['surface_alt']}; color:{COLORS['secondary']};
                border:1px solid {COLORS['border']}; border-radius:8px;
                min-width:30px; max-width:30px; min-height:26px; max-height:26px;
                padding:0; font-size:13px; font-weight:850;
            }}
            QPushButton#recommendationsFeedback:hover,
            QPushButton#recommendationsFeedback:checked {{
                background:{COLORS['accent_soft']}; color:{COLORS['accent']};
                border-color:{COLORS['accent']};
            }}
            QFrame#recommendationsTile {{ background:transparent; border:1px solid transparent; border-radius:12px; }}
            QFrame#recommendationsTile:hover {{ background:{COLORS['surface']}; border-color:{COLORS['border']}; }}
            QPushButton#recommendationsRefresh {{
                background:{COLORS['accent']}; color:{COLORS['accent_text']}; border:1px solid {COLORS['accent']};
                border-radius:8px; padding:9px 13px; font-weight:800;
            }}
        """)


__all__ = ["RecommendationWorker", "RecommendationsPage"]
