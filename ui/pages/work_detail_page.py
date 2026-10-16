import threading

from api import (
    cache_tmdb_episode_image,
    get_media_details,
    get_media_staff_page,
    get_tmdb_episode_data,
)
from html import escape as html_escape
from pathlib import Path
from shiboken6 import isValid

from PySide6.QtCore import QObject, Qt, Signal, QUrl, QSize, QPoint, QRect, QThread, QTimer
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QPen, QColor
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QProgressBar,
    QLineEdit, QScrollArea, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget, QWidgetAction
)

from diagnostics import log_exception

from database import (
    add_manual_bundle_link, add_to_library, characters_are_loaded, delete_work_data, get_bundle_characters,
    get_alternate_titles, get_bundle_relations, get_bundle_staff, get_connection, get_episodes,
    get_reading_progress, get_staff, is_work_in_library, is_work_favorite,
    get_tmdb_mapping, get_work, get_provider_metadata,
    save_work_display_override, set_work_favorite, save_anime, save_characters, save_cover_path,
    save_episode_thumbnail_path, save_episodes, save_provider_metadata, save_staff, save_tmdb_mapping,
    set_episode_watched, set_reading_progress_count,
)
from series import get_library_series
from ui.display_identity import copy_custom_cover, get_display_override, invalidate_display_override
from ui.branding import navigation_icon
from ui.preferences import get
from ui.pages.search_page import SearchPage
from ui.theme import COLORS, muted_label_stylesheet
from ui.widgets.character_card import CharacterCard
from ui.widgets.person_card import PersonCard
from ui.widgets.relation_card import RelationCard


IMAGE_DIRECTORY = Path("data") / "images" / "works"


class EpisodeSyncWorker(QObject):
    finished = Signal(int, object)
    error = Signal(int, str)

    def __init__(
        self,
        work_id,
        title_variants,
        start_date,
        end_date=None,
        expected_episodes=None,
        tmdb_id=None,
        tmdb_season_number=None,
        media_format=None,
    ):
        super().__init__()
        self.work_id = int(work_id)
        self.title_variants = list(title_variants or [])
        self.start_date = start_date
        self.end_date = end_date
        self.expected_episodes = expected_episodes
        self.tmdb_id = tmdb_id
        self.tmdb_season_number = tmdb_season_number
        self.media_format = media_format

    def run(self):
        try:
            payload = get_tmdb_episode_data(
                self.title_variants,
                self.start_date,
                self.end_date,
                self.expected_episodes,
                self.tmdb_id,
                self.tmdb_season_number,
                self.media_format,
            )
            self.finished.emit(self.work_id, payload)
        except Exception as error:
            self.error.emit(self.work_id, str(error))


class StaffPageWorker(QObject):
    """Fetch the next bounded page of AniList credits for each eligible work."""

    pages_loaded = Signal(object)

    def __init__(self, requests, stop_event):
        super().__init__()
        self.requests = list(requests or [])[:50]
        self.stop_event = stop_event

    def run(self):
        results = []
        for work_id, anilist_id, page in self.requests:
            if self.stop_event.is_set():
                break
            try:
                payload = get_media_staff_page(anilist_id, page=page, per_page=15)
                edges = payload.get("edges") if isinstance(payload, dict) else None
                page_info = payload.get("pageInfo") if isinstance(payload, dict) else None
                if not isinstance(edges, list):
                    raise RuntimeError("AniList returned an invalid staff page.")
                save_staff(work_id, edges, replace_snapshot=False)
                if isinstance(page_info, dict):
                    save_provider_metadata(
                        work_id,
                        "anilist_staff_page_info",
                        page_info,
                        provider_id=anilist_id,
                    )
                results.append({
                    "work_id": int(work_id),
                    "page": int(page),
                    "edge_count": len(edges),
                    "page_info": page_info if isinstance(page_info, dict) else {},
                })
            except Exception as error:
                results.append({
                    "work_id": int(work_id),
                    "page": int(page),
                    "error": str(error),
                })
        self.pages_loaded.emit(results)


class EpisodeImageCacheWorker(QObject):
    finished = Signal(int)
    error = Signal(int, str)

    def __init__(self, work_id, episodes, stop_event=None):
        super().__init__()
        self.work_id = int(work_id)
        self.episodes = [dict(episode) for episode in (episodes or [])]
        self.stop_event = stop_event

    def run(self):
        errors = []
        for episode in self.episodes:
            if self.stop_event is not None and self.stop_event.is_set():
                break
            number = episode.get("episodeNumber")
            url = episode.get("thumbnail")
            if number is None or not url:
                continue

            try:
                local_path = cache_tmdb_episode_image(
                    url,
                    self.work_id,
                    number,
                )
                if local_path:
                    save_episode_thumbnail_path(
                        self.work_id,
                        number,
                        local_path,
                    )
            except Exception as error:
                errors.append(f"Episode {int(number)}: {error}")

        if errors:
            self.error.emit(self.work_id, "; ".join(errors[:3]))
        else:
            self.finished.emit(self.work_id)


class EpisodeArtwork(QLabel):
    _cache = {}

    def __init__(self, work_id=None, episode_number=None, parent=None):
        super().__init__(parent)
        self.work_id = int(work_id) if work_id is not None else None
        self.episode_number = int(episode_number) if episode_number is not None else None
        self.setFixedSize(180, 102)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            f"background:{COLORS['background_alt']};border-radius:10px;"
            f"color:{COLORS['muted']};font-size:11px;font-weight:800;"
        )

    def refresh_theme(self):
        self.setStyleSheet(
            f"background:{COLORS['background_alt']};border-radius:10px;"
            f"color:{COLORS['muted']};font-size:11px;font-weight:800;"
        )
        self.update()

    def load(self, url):
        url = str(url or "").strip()
        if not url:
            self._show_fallback("NO IMAGE")
            return

        local_path = Path(url)
        if local_path.is_file():
            pixmap = QPixmap(str(local_path))
            if not pixmap.isNull():
                self._cache[url] = pixmap
                self.setText("")
                self.setPixmap(self._cropped(pixmap))
                return

        cached = self._cache.get(url)
        if cached is not None and not cached.isNull():
            self.setText("")
            self.setPixmap(self._cropped(cached))
            return

        # Remote episode URLs are intentionally never fetched by the widget.
        # The background episode-image cache worker owns all TMDB downloads.
        self._show_fallback("CACHING…")

    def _show_fallback(self, text):
        self.setPixmap(QPixmap())
        self.setText(text)

    def _cropped(self, pixmap):
        size = self.size()
        scaled = pixmap.scaled(
            size,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        x = max(0, (scaled.width() - size.width()) // 2)
        y = max(0, (scaled.height() - size.height()) // 2)
        cropped = scaled.copy(x, y, size.width(), size.height())

        result = QPixmap(size)
        result.fill(Qt.transparent)

        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        rect = result.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)

        painter.save()
        painter.setClipPath(path)
        painter.drawPixmap(rect.topLeft(), cropped)
        painter.restore()
        painter.end()
        return result



class EpisodeCard(QFrame):
    watched_changed = Signal(int, bool)

    def __init__(self, episode, parent=None):
        super().__init__(parent)
        self.episode = episode
        self.setObjectName("episodeCard")
        self.setMinimumHeight(126)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 14, 12)
        layout.setSpacing(14)

        artwork = EpisodeArtwork(
            episode["work_id"],
            episode["episode_number"],
        )
        artwork.load(episode["thumbnail_url"])
        layout.addWidget(artwork, 0, Qt.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(4)

        top = QHBoxLayout()
        number = QLabel(f"EPISODE {int(episode['episode_number']):02d}")
        number.setObjectName("detailEpisodeNumber")
        number.setStyleSheet(
            f"color:{COLORS['accent']};font-size:11px;font-weight:900;"
            "letter-spacing:0.6px;"
        )
        top.addWidget(number)

        date = QLabel(self._format_date(episode["air_date"]))
        date.setObjectName("detailEpisodeDate")
        date.setStyleSheet(f"color:{COLORS['muted']};font-size:11px;")
        top.addStretch()
        if date.text():
            top.addWidget(date)
        body.addLayout(top)

        title = QLabel(episode["title"] or f"Episode {episode['episode_number']}")
        title.setObjectName("detailEpisodeTitle")
        title.setWordWrap(True)
        title.setStyleSheet(
            f"color:{COLORS['primary']};font-size:15px;font-weight:800;"
        )
        body.addWidget(title)

        description_text = str(episode["description"] or "").strip()
        description = QLabel(
            description_text if description_text else "Synopsis unavailable."
        )
        description.setObjectName("detailEpisodeDescription")
        description.setWordWrap(True)
        description.setTextFormat(Qt.PlainText)
        description.setMaximumHeight(42)
        description.setStyleSheet(
            f"color:{COLORS['secondary']};font-size:12px;"
        )
        body.addWidget(description, 1)

        layout.addLayout(body, 1)

        watched = QCheckBox()
        watched.setChecked(bool(episode["watched"]))
        watched.setCursor(Qt.PointingHandCursor)
        watched.toggled.connect(
            lambda checked, n=int(episode["episode_number"]):
                self.watched_changed.emit(n, checked)
        )
        layout.addWidget(watched, 0, Qt.AlignTop)

    def refresh_theme(self):
        styles = {
            "detailEpisodeNumber": f"color:{COLORS['accent']};font-size:11px;font-weight:900;letter-spacing:0.6px;",
            "detailEpisodeDate": f"color:{COLORS['muted']};font-size:11px;",
            "detailEpisodeTitle": f"color:{COLORS['primary']};font-size:15px;font-weight:800;",
            "detailEpisodeDescription": f"color:{COLORS['secondary']};font-size:12px;",
        }
        for label in self.findChildren(QLabel):
            stylesheet = styles.get(label.objectName())
            if stylesheet is not None:
                label.setStyleSheet(stylesheet)
        for artwork in self.findChildren(EpisodeArtwork):
            artwork.refresh_theme()
        for button in self.findChildren(QPushButton, "detailBackButton"):
            button.setIcon(navigation_icon("back", COLORS["secondary"]))
        self.update()

    @staticmethod
    def _format_date(value):
        text = str(value or "").strip()
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            year, month, day = text.split("-")
            months = (
                "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
            )
            try:
                return f"{months[int(month) - 1]} {int(day)}, {year}"
            except (ValueError, IndexError):
                pass
        return text




class StaffFlowLayout(QLayout):
    """Tightly pack fixed-width staff cards and center each row."""
    def __init__(self, parent=None, h_spacing=8, v_spacing=12):
        super().__init__(parent)
        self._items = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        margins = self.contentsMargins()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size + QSize(
            margins.left() + margins.right(),
            margins.top() + margins.bottom(),
        )

    def _do_layout(self, rect, test_only):
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )

        rows = []
        current_row = []
        current_width = 0
        current_height = 0

        for item in self._items:
            size = item.sizeHint()
            if size.width() <= 0:
                continue

            added_width = size.width() if not current_row else self._h_spacing + size.width()
            if current_row and current_width + added_width > effective.width():
                rows.append((current_row, current_width, current_height))
                current_row = []
                current_width = 0
                current_height = 0
                added_width = size.width()

            current_row.append((item, size))
            current_width += added_width
            current_height = max(current_height, size.height())

        if current_row:
            rows.append((current_row, current_width, current_height))

        if rows:
            # Use the full-row width as the common anchor so an incomplete
            # final row starts at exactly the same horizontal position.
            anchor_width = rows[0][1]
            anchor_x = effective.x() + max(0, (effective.width() - anchor_width) // 2)
        else:
            anchor_x = effective.x()

        y = effective.y()
        for row, row_width, row_height in rows:
            x = anchor_x
            for item, size in row:
                if not test_only:
                    item.setGeometry(QRect(QPoint(x, y), size))
                x += size.width() + self._h_spacing
            y += row_height + self._v_spacing

        if not rows:
            return margins.top() + margins.bottom()

        return y - self._v_spacing - rect.y() + margins.bottom()


class BundleSearchDialog(QDialog):
    def __init__(self, excluded_ids=None, parent=None):
        super().__init__(parent)
        self.selected_work = None
        self.excluded_ids = {int(work_id) for work_id in (excluded_ids or set())}

        self.setWindowTitle("Add to bundle")
        self.setMinimumSize(1120, 760)
        self.resize(1180, 800)

        self.search_page = SearchPage(
            lambda *_args: None,
            selection_mode=True,
        )
        self.search_page.setParent(self)
        self.search_page.anime_selected.connect(self._select_work)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.search_page)

        self.setStyleSheet(
            f"QDialog {{ background:{COLORS['background']}; }}"
        )
        self.finished.connect(lambda _result: self.search_page.shutdown_workers())

    def _select_work(self, work):
        try:
            work_id = int(work["id"])
        except (KeyError, TypeError, ValueError):
            return
        if work_id in self.excluded_ids:
            return

        self.selected_work = work
        self.accept()


class BundleRemoveDialog(QDialog):
    def __init__(self, partners, parent=None):
        super().__init__(parent)
        self.selected_id = None
        self.setWindowTitle("Remove from bundle")
        self.setMinimumSize(500, 420)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)

        heading = QLabel("Remove from bundle")
        heading.setStyleSheet(
            f"font-size:21px;font-weight:850;color:{COLORS['primary']};"
        )
        root.addWidget(heading)

        subtitle = QLabel("Choose the bundled item you want to remove from your Library.")
        subtitle.setStyleSheet(f"color:{COLORS['secondary']};font-size:12px;")
        root.addWidget(subtitle)

        self.list = QListWidget()
        self.list.setSpacing(5)
        self.list.itemDoubleClicked.connect(self._choose_item)
        root.addWidget(self.list, 1)

        for row in partners or []:
            label = str(row["partner_title"] or "Untitled")
            meta = " · ".join(
                str(value)
                for value in (row["partner_type"], row["partner_format"])
                if value
            )
            if meta:
                label += f"\n{meta}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, int(row["partner_id"]))
            item.setSizeHint(QSize(0, 58))
            self.list.addItem(item)

        if not partners:
            empty = QListWidgetItem("No other bundled items found.")
            empty.setFlags(Qt.NoItemFlags)
            self.list.addItem(empty)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        remove_button = buttons.addButton("Delete selected item", QDialogButtonBox.AcceptRole)
        remove_button.setEnabled(bool(partners))
        remove_button.clicked.connect(self._choose_selected)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.setStyleSheet(
            f"""
            QDialog {{ background:{COLORS['background']}; }}
            QListWidget {{
                background:{COLORS['surface']};
                color:{COLORS['primary']};
                border:1px solid {COLORS['border']};
                border-radius:12px;
                padding:6px;
            }}
            QListWidget::item {{
                background:transparent;
                border:1px solid transparent;
                border-radius:9px;
                padding:10px 12px;
            }}
            QListWidget::item:hover, QListWidget::item:selected {{
                background:{COLORS['surface_hover']};
                border-color:{COLORS['accent']};
            }}
        """
        )

        if partners:
            self.list.setCurrentRow(0)

    def _choose_selected(self):
        self._choose_item(self.list.currentItem())

    def _choose_item(self, item):
        if item is None:
            return
        partner_id = item.data(Qt.UserRole)
        if partner_id is None:
            return
        self.selected_id = int(partner_id)
        self.accept()


class WorkDetailPage(QWidget):
    back_requested = Signal()
    person_selected = Signal(object)
    character_selected = Signal(object)
    voice_actor_selected = Signal(object)
    relation_selected = Signal(object)
    bundle_changed = Signal()
    bundle_edit_requested = Signal(object)
    staff_thread_stopped = Signal(object, object)

    _cover_cache = {}
    _cover_failures = set()

    def __init__(self):
        super().__init__()
        self.work = None
        self.mangabaka_metadata = None
        self.mangabaka_volume_records = []
        self.mangabaka_news = []
        self._selected_episode_work_id = None
        self._shutdown_event = threading.Event()
        self._episode_sync_thread = None
        self._episode_sync_worker = None
        self._episode_sync_work_id = None
        self._episode_image_cache_threads = {}
        self._episode_image_cache_workers = {}
        self._staff_next_pages = {}
        self._staff_exhausted_ids = set()
        self._staff_page_errors = {}
        self._staff_visible_counts = {}
        self._staff_sync_thread = None
        self._staff_sync_worker = None
        self._staff_loading = False
        self.staff_thread_stopped.connect(self._staff_thread_finished)
        self._detail_build_token = 0
        self._detail_content_cache = {}
        self._episode_sync_completed = set()
        self._episode_sync_errors = {}
        self._episode_source_status = {}
        self._cover_manager = QNetworkAccessManager(self)
        self._cover_reply = None
        self._delete_overlay = None
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.scroll_area)

    def _skeleton_block(self, height=10, width=None, object_name="detailSkeletonBlock"):
        block = QFrame()
        block.setObjectName(object_name)
        block.setFixedHeight(int(height))
        if width is not None:
            block.setFixedWidth(int(width))
        else:
            block.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return block

    def _detail_section_skeleton(self, title, card_count=4, variant="portrait"):
        """Build a stable card-shaped placeholder for one pending detail section."""
        frame = QFrame()
        frame.setObjectName("detailSkeletonSection")
        frame.setProperty("_skeleton_section_title", str(title))
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(14)

        heading_row = QHBoxLayout()
        heading = QLabel(str(title))
        heading.setObjectName("detailSkeletonHeading")
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        heading_row.addWidget(self._skeleton_block(9, 72))
        layout.addLayout(heading_row)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        cover_height = 88 if variant == "poster" else 112
        columns = 4
        for index in range(max(1, int(card_count))):
            card = QFrame()
            card.setObjectName("detailSkeletonCard")
            card.setFixedWidth(145)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(8, 8, 8, 10)
            card_layout.setSpacing(8)
            card_layout.addWidget(
                self._skeleton_block(cover_height, None, "detailSkeletonCover")
            )
            card_layout.addWidget(self._skeleton_block(9, 104))
            card_layout.addWidget(self._skeleton_block(8, 76))
            card_layout.addStretch(1)
            grid.addWidget(card, index // columns, index % columns, Qt.AlignTop)
        layout.addLayout(grid)
        return frame

    def _episode_skeleton_strip(self):
        """Build horizontal episode placeholders without starting network work."""
        strip = QWidget()
        strip.setObjectName("detailSkeletonEpisodeStrip")
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(12)
        for _index in range(4):
            card = QFrame()
            card.setObjectName("detailSkeletonEpisodeCard")
            card.setFixedWidth(156)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(8, 8, 8, 10)
            card_layout.setSpacing(8)
            card_layout.addWidget(
                self._skeleton_block(82, None, "detailSkeletonCover")
            )
            card_layout.addWidget(self._skeleton_block(10, 112))
            card_layout.addWidget(self._skeleton_block(8, 76))
            layout.addWidget(card, 0, Qt.AlignTop)
        layout.addStretch(1)
        return strip

    def _set_cover_placeholder(self, label, loading, text):
        """Switch the hero cover between skeleton and honest missing-cover states."""
        if label is None or not isValid(label):
            return
        label.setPixmap(QPixmap())
        label.setProperty("coverLoading", bool(loading))
        label.setText(str(text))
        style = label.style()
        if style is not None:
            style.unpolish(label)
            style.polish(label)
        label.update()

    def request_shutdown(self):
        """Cancel queued episode-image work and stop detail-page QThreads safely."""
        self._shutdown_event.set()
        threads = []
        if self._episode_sync_thread is not None:
            threads.append(self._episode_sync_thread)
        if self._staff_sync_thread is not None:
            threads.append(self._staff_sync_thread)
        threads.extend(self._episode_image_cache_threads.values())
        for thread in threads:
            try:
                thread.quit()
            except RuntimeError:
                pass
        if self._cover_reply is not None:
            try:
                self._cover_reply.abort()
            except RuntimeError:
                pass

    def _detail_cache_key(self, work_ids):
        return tuple(int(work_id) for work_id in work_ids)

    def _detail_work_ids(self):
        """Return each distinct work ID represented by this detail page."""
        members = self._value("_series_members") or []
        ids = []

        for member in members:
            try:
                work_id = int(member["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if work_id not in ids:
                ids.append(work_id)

        if ids:
            return ids

        work_id = self._value("id")
        try:
            return [int(work_id)] if work_id is not None else []
        except (TypeError, ValueError):
            return []

    def _prepare_detail_state(self, work):
        self.work = work
        detail_ids = self._detail_work_ids()
        for work_id in detail_ids:
            self._staff_next_pages.setdefault(work_id, 2)
        self._staff_visible_counts.setdefault(tuple(detail_ids), 12)

        self.mangabaka_metadata = self._value("_mangabaka")
        self.mangabaka_volume_records = []
        self.mangabaka_news = []
        primary_id = self._value("id")
        if not isinstance(self.mangabaka_metadata, dict):
            for provider_work_id in detail_ids or ([primary_id] if primary_id is not None else []):
                try:
                    saved_metadata = get_provider_metadata(int(provider_work_id), "mangabaka")
                except Exception:
                    saved_metadata = None
                if isinstance(saved_metadata, dict):
                    self.mangabaka_metadata = saved_metadata
                    primary_id = provider_work_id
                    break
        if primary_id is not None:
            try:
                saved_volumes = get_provider_metadata(int(primary_id), "mangabaka_volumes")
                if isinstance(saved_volumes, list):
                    self.mangabaka_volume_records = saved_volumes
            except Exception:
                self.mangabaka_volume_records = []
            try:
                saved_news = get_provider_metadata(int(primary_id), "mangabaka_news")
                if isinstance(saved_news, list):
                    self.mangabaka_news = saved_news
            except Exception:
                self.mangabaka_news = []

        previous_selected = self._selected_episode_work_id
        if previous_selected in detail_ids:
            self._selected_episode_work_id = previous_selected
        elif detail_ids:
            self._selected_episode_work_id = detail_ids[0]
        else:
            self._selected_episode_work_id = self._value("id")

        return detail_ids

    def _local_detail_ready(self, detail_ids):
        if not detail_ids:
            return False, False

        try:
            detail_data_ready = all(
                characters_are_loaded(work_id)
                for work_id in detail_ids
            )
        except Exception:
            detail_data_ready = False

        episode_data_ready = True
        if self._is_reading_media():
            return detail_data_ready, True

        for work_id in detail_ids:
            try:
                work_row = get_work(work_id)
                expected = int(work_row["episodes"] or 0) if work_row is not None else 0
                saved = get_episodes(work_id)
                if expected > 0 and not saved:
                    episode_data_ready = False
                    break
            except Exception:
                episode_data_ready = False
                break

        return detail_data_ready, episode_data_ready

    def _build_detail_content(self, detail_ids, defer_missing=True):
        detail_data_ready, episode_data_ready = self._local_detail_ready(detail_ids)

        content = QWidget()
        content.setProperty("_detail_cache_key", self._detail_cache_key(detail_ids))
        content.setProperty(
            "_detail_cacheable",
            bool(detail_data_ready and episode_data_ready),
        )
        root = QVBoxLayout(content)
        root.setContentsMargins(42, 34, 42, 50)
        root.setSpacing(22)

        back = QPushButton()
        back.setObjectName("detailBackButton")
        back.setIcon(navigation_icon("back", COLORS["secondary"]))
        back.setIconSize(QSize(22, 22))
        back.setFixedSize(42, 42)
        back.setAccessibleName("Back")
        back.setToolTip("Back")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self.back_requested)
        root.addWidget(back, alignment=Qt.AlignLeft)
        root.addWidget(self._hero())

        episode_host = QFrame()
        episode_host.setObjectName("section")
        episode_host.setProperty("_episodes_section", True)
        episode_layout = QVBoxLayout(episode_host)
        episode_layout.setContentsMargins(20, 18, 20, 20)

        if self._is_reading_media():
            reading_frame = self._reading_section()
            reading_frame.setProperty("_reading_section", True)
            episode_host.deleteLater()
            episode_host = reading_frame
        elif episode_data_ready:
            ready_episode_frame = self._episodes_section()
            ready_episode_frame.setProperty("_episodes_section", True)
            episode_host.deleteLater()
            episode_host = ready_episode_frame
        else:
            loading_episodes = QLabel("Loading episode data…")
            loading_episodes.setObjectName("detailEpisodeLoadingLabel")
            loading_episodes.setWordWrap(True)
            episode_layout.addWidget(loading_episodes)
            episode_layout.addWidget(self._episode_skeleton_strip())
        root.addWidget(episode_host)

        mangabaka_section = self._mangabaka_section()
        if mangabaka_section is not None:
            root.addWidget(mangabaka_section)

        if detail_data_ready:
            detail_host = QWidget()
            detail_host.setObjectName("detailSectionsHost")
            detail_layout = QVBoxLayout(detail_host)
            detail_layout.setContentsMargins(0, 0, 0, 0)
            detail_layout.setSpacing(22)
            self._build_detail_sections_local(
                detail_layout,
                detail_ids,
            )
        else:
            detail_host = QWidget()
            detail_host.setObjectName("detailSectionsHost")
            detail_layout = QVBoxLayout(detail_host)
            detail_layout.setContentsMargins(0, 0, 0, 0)
            detail_layout.setSpacing(22)
            detail_layout.addWidget(
                self._detail_section_skeleton("Characters", 4, "portrait")
            )
            detail_layout.addWidget(
                self._detail_section_skeleton("Staff", 6, "portrait")
            )
            detail_layout.addWidget(
                self._detail_section_skeleton("Relations", 6, "poster")
            )
        root.addWidget(detail_host)
        root.addStretch()

        if defer_missing and (not episode_data_ready or not detail_data_ready):
            token = self._detail_build_token
            if not episode_data_ready:
                QTimer.singleShot(
                    40,
                    lambda token=token, page=content, host=episode_host:
                        self._populate_episode_section(token, page, host),
                )
            if not detail_data_ready:
                QTimer.singleShot(
                    40,
                    lambda token=token, page=content, host=detail_host, ids=list(detail_ids):
                        self._populate_detail_sections(token, page, host, ids),
                )

        return content, detail_data_ready and episode_data_ready

    def preload_work(self, work):
        """Build a fully prepared Library detail view ahead of the next click."""
        if work is None:
            return False

        # Never replace the currently displayed work while warming the cache.
        current_work = self.work
        current_selected = self._selected_episode_work_id
        current_errors = self._episode_sync_errors
        current_token = self._detail_build_token

        try:
            detail_ids = [
                int(member["id"])
                for member in (work.get("_series_members") or [])
            ] if hasattr(work, "get") else []

            if not detail_ids:
                detail_ids = [int(work["id"])]

            key = self._detail_cache_key(detail_ids)
            if key in self._detail_content_cache:
                return True

            self._prepare_detail_state(work)
            content, ready = self._build_detail_content(
                detail_ids,
                defer_missing=False,
            )
            if not ready:
                content.deleteLater()
                return False

            self._detail_content_cache[key] = content
            return True
        except Exception as error:
            print(f"Detail preload failed: {error}")
            return False
        finally:
            self.work = current_work
            self._selected_episode_work_id = current_selected
            self._episode_sync_errors = current_errors
            self._detail_build_token = current_token

    def preload_works(self, works):
        """Warm prepared Library detail views one at a time between event-loop turns."""
        queue = list(works or [])

        def preload_next():
            if not queue:
                return
            self.preload_work(queue.pop(0))
            if queue:
                QTimer.singleShot(0, preload_next)

        QTimer.singleShot(0, preload_next)

    def invalidate_detail_cache(self, work_ids=None):
        ids = {
            int(work_id)
            for work_id in (work_ids or [])
            if work_id is not None
        }

        for key in list(self._detail_content_cache):
            if not ids or ids.intersection(key):
                content = self._detail_content_cache.pop(key)
                content.deleteLater()

    def set_work(self, work):
        previous_selected_episode_id = self._selected_episode_work_id
        self._episode_sync_errors = {}
        self._detail_build_token += 1

        detail_ids = self._prepare_detail_state(work)
        if previous_selected_episode_id in detail_ids:
            self._selected_episode_work_id = previous_selected_episode_id

        old_content = self.scroll_area.takeWidget()
        if old_content is not None:
            old_key = old_content.property("_detail_cache_key")
            old_cacheable = bool(old_content.property("_detail_cacheable"))
            if old_cacheable and old_key:
                self._detail_content_cache[tuple(old_key)] = old_content
            else:
                old_content.deleteLater()

        key = self._detail_cache_key(detail_ids)
        cached = self._detail_content_cache.pop(key, None)

        if cached is not None:
            self.scroll_area.setWidget(cached)
            self._apply_detail_styles()
            return

        content, _ready = self._build_detail_content(
            detail_ids,
            defer_missing=True,
        )
        self.scroll_area.setWidget(content)
        self._apply_detail_styles()

    def _apply_detail_styles(self):
        self.setStyleSheet(f"""
            QPushButton#back {{ background: transparent; border: 0; color: {COLORS['secondary']}; padding: 5px 0; font-weight: 750; }}
            QPushButton#back:hover {{ color: {COLORS['primary']}; }}
            QFrame#hero {{ background: {COLORS['surface']}; border: 1px solid {COLORS['frame']}; border-radius: 22px; }}
            QFrame#section {{ background: {COLORS['surface']}; border: 1px solid {COLORS['frame']}; border-radius: 18px; }}
            QFrame#episodeCard {{
                background: {COLORS['surface_alt']};
                border: 1px solid {COLORS['border']};
                border-radius: 14px;
            }}
            QFrame#episodeCard:hover {{
                background: {COLORS['surface_hover']};
                border-color: {COLORS['border_hover']};
            }}
            QFrame#detailSkeletonSection {{
                background:{COLORS['surface']};
                border:1px solid {COLORS['frame']};
                border-radius:16px;
            }}
            QFrame#detailSkeletonCard, QFrame#detailSkeletonEpisodeCard {{
                background:{COLORS['surface_alt']};
                border:1px solid {COLORS['border']};
                border-radius:10px;
            }}
            QFrame#detailSkeletonBlock, QFrame#detailSkeletonCover {{
                background:{COLORS['surface_hover']};
                border:1px solid {COLORS['border']};
                border-radius:6px;
            }}
            QFrame#detailSkeletonCover {{ border-radius:8px; }}
            QLabel#detailSkeletonHeading {{
                color:{COLORS['primary']};
                background:transparent;
                font-size:16px;
                font-weight:850;
            }}
            QLabel#detailEpisodeLoadingLabel {{
                color:{COLORS['muted']};
                background:transparent;
                font-size:11px;
                font-weight:700;
            }}
            QLabel#detailHeroCover {{
                color:{COLORS['muted']};
                background:{COLORS['background_alt']};
                border-radius:14px;
            }}
            QLabel#detailHeroCover[coverLoading="true"] {{
                color:{COLORS['muted']};
                background:{COLORS['surface_alt']};
                border:1px solid {COLORS['border']};
                border-radius:14px;
                font-size:11px;
                font-weight:750;
            }}
            QFrame#readingKindSection {{
                background:{COLORS['surface_alt']};
                border:1px solid {COLORS['border']};
                border-radius:12px;
            }}
            QSpinBox#readingProgressCount {{
                min-width:110px;
                color:{COLORS['primary']};
                background:{COLORS['surface']};
                border:1px solid {COLORS['border']};
                border-radius:8px;
                padding:6px 8px;
            }}
            QSpinBox#readingProgressCount:disabled {{
                color:{COLORS['muted']};
                background:{COLORS['surface_alt']};
            }}
            QPushButton#detailBackButton {{ background:transparent; border:1px solid transparent; border-radius:21px; padding:0; }}
            QPushButton#detailBackButton:hover {{ background:{COLORS['surface_hover']}; border-color:{COLORS['border']}; }}
            QPushButton#detailBackButton:pressed {{ background:{COLORS['accent_soft']}; }}
            QToolButton#detailMenu {{ background:transparent; color:{COLORS['primary']}; border:2px solid transparent; border-radius:{get('corner_radius') + 2}px; font-size:30px; font-weight:900; padding:0; }}
            QToolButton#detailMenu:hover {{ background:{COLORS['surface_hover']}; color:{COLORS['accent_hover']}; border-color:{COLORS['accent']}; }}
            QPushButton#detailFavoriteButton, QPushButton#detailCustomizeButton {{
                background:{COLORS['surface_alt']}; color:{COLORS['primary']}; border:1px solid {COLORS['border']};
                border-radius:8px; padding:8px 10px; font-size:11px; font-weight:800;
            }}
            QPushButton#detailFavoriteButton:hover, QPushButton#detailCustomizeButton:hover {{
                background:{COLORS['accent_soft']}; border-color:{COLORS['accent']};
            }}
            QPushButton#detailFavoriteButton:checked {{
                background:{COLORS['accent_soft']}; color:{COLORS['accent']}; border-color:{COLORS['accent']};
            }}
            QFrame#deleteOverlay {{ background:{COLORS['surface']}; border:1px solid {COLORS['frame']}; border-radius:18px; }}
            QLabel#deleteTitle {{ color:{COLORS['primary']}; font-size:19px; font-weight:850; }}
            QLabel#deleteMessage {{ color:{COLORS['secondary']}; font-size:12px; }}
            QPushButton#deleteCancel {{ background:{COLORS['surface_alt']}; color:{COLORS['secondary']}; border:1px solid {COLORS['border']}; border-radius:9px; padding:9px 16px; font-weight:750; }}
            QPushButton#deleteCancel:hover {{ background:{COLORS['surface_hover']}; color:{COLORS['primary']}; }}
            QPushButton#deleteConfirm {{ background:{COLORS['danger']}; color:{COLORS['primary']}; border:0; border-radius:9px; padding:9px 18px; font-weight:850; }}
            QPushButton#deleteBundle {{ background:{COLORS['danger']}; color:{COLORS['primary']}; border:0; border-radius:9px; padding:9px 14px; font-weight:850; }}
            QPushButton#deleteBundle:hover {{ background:{COLORS['danger']}; }}
            QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {COLORS['border_hover']}; background: {COLORS['background_alt']}; }}
            QCheckBox::indicator:checked {{ background: {COLORS['accent']}; border-color: {COLORS['accent']}; }}
        """)

    def refresh_theme(self):
        self._apply_detail_styles()

        roots = []
        current = self.scroll_area.widget()
        if current is not None:
            roots.append(current)
        roots.extend(self._detail_content_cache.values())

        seen = set()
        for content in roots:
            if content is None or id(content) in seen:
                continue
            seen.add(id(content))

            # These section frames have their own local stylesheet, which takes
            # precedence over the page's stylesheet and must be regenerated.
            for frame in content.findChildren(QFrame):
                if frame.objectName() in {"charactersSection", "section"}:
                    frame.setStyleSheet(self._detail_section_frame_stylesheet())

            # Cards and episode widgets use local stylesheets too. Refresh them
            # individually; artwork borders repaint from the live COLORS map.
            for widget in content.findChildren(QWidget):
                updater = getattr(widget, "refresh_theme", None)
                if callable(updater):
                    updater()

            label_styles = {
                "detailHeroTitle": f"font-size:34px;font-weight:850;color:{COLORS['primary']};letter-spacing:-1px;",
                "detailHeroNativeTitle": muted_label_stylesheet(),
                "detailHeroMetadata": f"color:{COLORS['secondary']};font-size:13px;",
                "detailHeroScore": f"color:{COLORS['accent']};font-size:18px;font-weight:800;",
                "detailHeroDescription": f"color:{COLORS['secondary']};font-size:14px;",
                "detailSectionHeader": f"font-size:17px;font-weight:800;color:{COLORS['primary']};",
                "readingSectionTitle": f"font-size:17px;font-weight:800;color:{COLORS['primary']};",
                "readingKindHeading": f"font-size:14px;font-weight:850;color:{COLORS['primary']};",
                "readingKindProgress": f"color:{COLORS['accent']};font-size:11px;font-weight:850;",
            }
            for label in content.findChildren(QLabel):
                stylesheet = label_styles.get(label.objectName())
                if stylesheet is not None:
                    label.setStyleSheet(stylesheet)
                    label.update()

            content.update()

    def _populate_episode_section(self, token, content, host):
        if token != self._detail_build_token:
            return
        if self.scroll_area.widget() is not content:
            return

        new_frame = self._episodes_section(defer_cards=True)
        new_frame.setProperty("_episodes_section", True)

        root = content.layout()
        if root is None:
            return

        index = root.indexOf(host)
        if index < 0:
            return

        root.replaceWidget(host, new_frame)
        host.deleteLater()

        episodes = getattr(new_frame, "_pending_episode_cards", None)
        if episodes:
            QTimer.singleShot(
                0,
                lambda token=token, page=content, frame=new_frame, data=episodes:
                    self._populate_episode_cards(token, page, frame, data, 0),
            )


    def _populate_episode_cards(self, token, content, frame, episodes, offset):
        if token != self._detail_build_token:
            return
        if self.scroll_area.widget() is not content:
            return

        root = content.layout()
        if root is None or root.indexOf(frame) < 0:
            return

        layout = frame.layout()
        if layout is None:
            return

        batch_size = 6
        end = min(offset + batch_size, len(episodes))
        for ep in episodes[offset:end]:
            card = EpisodeCard(ep)
            card.watched_changed.connect(self._episode_toggled)
            layout.addWidget(card)

        if end < len(episodes):
            QTimer.singleShot(
                0,
                lambda token=token, page=content, current=frame, data=episodes, next_offset=end:
                    self._populate_episode_cards(
                        token,
                        page,
                        current,
                        data,
                        next_offset,
                    ),
            )


    def _build_detail_sections_local(self, layout, detail_ids):
        """Build all detail sections directly from already-prepared local data."""
        layout.addWidget(
            self._grid_section(
                "Characters",
                get_bundle_characters(detail_ids),
                CharacterCard,
                self.character_selected,
                4,
                empty_message=self._detail_empty_message("Characters", detail_ids),
            )
        )
        layout.addWidget(
            self._staff_section(detail_ids, get_bundle_staff(detail_ids))
        )
        layout.addWidget(
            self._grid_section(
                "Relations",
                get_bundle_relations(detail_ids),
                RelationCard,
                self.relation_selected,
                6,
                empty_message=self._detail_empty_message("Relations", detail_ids),
            )
        )


    def _populate_detail_sections(self, token, content, host, detail_ids):
        if token != self._detail_build_token:
            return
        if self.scroll_area.widget() is not content:
            return

        layout = host.layout()
        if layout is None:
            return

        loading = None
        for index in range(layout.count()):
            candidate = layout.itemAt(index).widget()
            if (
                candidate is not None
                and candidate.property("_skeleton_section_title") == "Characters"
            ):
                loading = candidate
                break
        if loading is None:
            loading = self._detail_section_skeleton("Characters", 4, "portrait")
            layout.insertWidget(0, loading)
            layout.insertWidget(
                1, self._detail_section_skeleton("Staff", 6, "portrait")
            )
            layout.insertWidget(
                2, self._detail_section_skeleton("Relations", 6, "poster")
            )

        QTimer.singleShot(
            0,
            lambda token=token, page=content, target_layout=layout, label=loading, ids=list(detail_ids):
                self._populate_detail_section(
                    token,
                    page,
                    target_layout,
                    label,
                    ids,
                    "Characters",
                    get_bundle_characters,
                    CharacterCard,
                    self.character_selected,
                    4,
                ),
        )


    def _populate_detail_section(
        self,
        token,
        content,
        layout,
        loading,
        detail_ids,
        title,
        data_getter,
        card_class,
        signal,
        columns,
    ):
        if token != self._detail_build_token:
            return
        if self.scroll_area.widget() is not content:
            return

        loading_index = layout.indexOf(loading)
        if loading_index < 0:
            return

        try:
            items = data_getter(detail_ids)
        except Exception as error:
            print(f"{title} section failed to load: {error}")
            items = []

        loading_index = layout.indexOf(loading)
        if loading_index < 0:
            return
        if title == "Staff":
            section_widget = self._staff_section(detail_ids, items)
        else:
            section_widget = self._grid_section(
                title,
                items,
                card_class,
                signal,
                columns,
                empty_message=self._detail_empty_message(title, detail_ids),
            )
        layout.insertWidget(loading_index, section_widget)
        layout.removeWidget(loading)
        loading.deleteLater()

        next_specs = {
            "Characters": (
                "Staff",
                get_bundle_staff,
                PersonCard,
                self.person_selected,
                6,
                "portrait",
            ),
            "Staff": (
                "Relations",
                get_bundle_relations,
                RelationCard,
                self.relation_selected,
                6,
                "poster",
            ),
        }
        spec = next_specs.get(title)
        if spec is None:
            return

        next_title, next_getter, next_class, next_signal, next_columns, variant = spec
        next_loading = None
        for index in range(layout.count()):
            candidate = layout.itemAt(index).widget()
            if (
                candidate is not None
                and candidate.property("_skeleton_section_title") == next_title
            ):
                next_loading = candidate
                break
        if next_loading is None:
            section_index = layout.indexOf(section_widget)
            next_loading = self._detail_section_skeleton(
                next_title, next_columns, variant
            )
            layout.insertWidget(section_index + 1, next_loading)

        QTimer.singleShot(
            0,
            lambda token=token, page=content, target_layout=layout, label=next_loading,
                   ids=list(detail_ids), next_title=next_title, getter=next_getter,
                   cls=next_class, slot=next_signal, cols=next_columns:
                self._populate_detail_section(
                    token,
                    page,
                    target_layout,
                    label,
                    ids,
                    next_title,
                    getter,
                    cls,
                    slot,
                    cols,
                ),
        )

    def _mangabaka_section(self):
        """Show the preserved MangaBaka record without discarding provider-only fields."""
        data = self.mangabaka_metadata
        if not isinstance(data, dict):
            return None

        frame = QFrame()
        frame.setObjectName("section")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(10)

        heading = QLabel("MangaBaka metadata")
        heading.setStyleSheet(
            f"font-size:17px;font-weight:850;color:{COLORS['primary']};"
        )
        layout.addWidget(heading)

        def text_values(value, name_keys=("name", "title", "name_path")):
            if not isinstance(value, list):
                value = [value] if value not in (None, "") else []
            values = []
            for entry in value:
                if isinstance(entry, dict):
                    found = next((entry.get(key) for key in name_keys if entry.get(key)), None)
                    if found:
                        values.append(str(found))
                elif isinstance(entry, str) and entry.strip():
                    values.append(entry.strip())
            return list(dict.fromkeys(values))

        def add_line(label, value):
            if value in (None, "", [], {}):
                return
            row = QLabel(
                f"<b>{html_escape(str(label))}</b> "
                f"{html_escape(str(value))}"
            )
            row.setWordWrap(True)
            row.setTextFormat(Qt.RichText)
            row.setStyleSheet(f"font-size:12px;color:{COLORS['secondary']};")
            layout.addWidget(row)

        published = data.get("published") or {}
        if isinstance(published, dict):
            published_text = " – ".join(
                str(value) for value in (
                    published.get("start_date") or published.get("start"),
                    published.get("end_date") or published.get("end"),
                )
                if value
            )
        else:
            published_text = str(published or "")

        type_text = str(data.get("type") or "").replace("_", " ").title()
        status_text = str(data.get("status") or "").replace("_", " ").title()
        record_state = str(data.get("state") or "").replace("_", " ").title()
        facts = []
        if type_text:
            facts.append(type_text)
        if status_text:
            facts.append(status_text)
        if record_state:
            facts.append(f"Catalog record: {record_state}")
        if data.get("rating") is not None:
            facts.append(f"Rating {data.get('rating')}/100")
        if data.get("content_rating"):
            facts.append(f"Content: {data.get('content_rating')}")
        if data.get("is_licensed") is not None:
            facts.append("Licensed" if data.get("is_licensed") else "Unlicensed")
        if published_text:
            facts.append(f"Published {published_text}")
        if data.get("last_updated_at"):
            facts.append(f"Metadata updated {data.get('last_updated_at')}")
        anime_data = data.get("anime")
        if isinstance(anime_data, dict) and anime_data.get("exists") is not None:
            anime_text = "Yes" if anime_data.get("exists") else "No"
            anime_dates = " – ".join(
                str(value) for value in (anime_data.get("start"), anime_data.get("end")) if value
            )
            facts.append(f"Anime adaptation: {anime_text}" + (f" ({anime_dates})" if anime_dates else ""))
        add_line("Series", " · ".join(facts))

        if data.get("total_chapters") is not None:
            add_line("Chapters", data.get("total_chapters"))
        if data.get("final_volume") is not None:
            add_line("Final volume", data.get("final_volume"))

        authors = text_values(data.get("authors"))
        artists = text_values(data.get("artists"))
        publishers = text_values(data.get("publishers"))
        if authors:
            add_line("Authors", ", ".join(authors))
        if artists:
            add_line("Artists", ", ".join(artists))
        if publishers:
            add_line("Publishers", ", ".join(publishers))

        tags = data.get("tags") or []
        genres = []
        other_tags = []
        if isinstance(tags, list):
            for tag in tags:
                if not isinstance(tag, dict):
                    continue
                tag_name = str(tag.get("name_path") or tag.get("name") or "").strip()
                if not tag_name or tag.get("is_explicit"):
                    continue
                if tag.get("is_genre"):
                    genres.append(tag_name)
                else:
                    other_tags.append(tag_name)
        genres.extend(text_values(data.get("genres")))
        if genres:
            add_line("Genres", ", ".join(dict.fromkeys(genres)))
        if other_tags:
            add_line("Tags", ", ".join(dict.fromkeys(other_tags)))

        title_records = data.get("titles") or []
        title_lines = []
        if isinstance(title_records, list):
            title_records = sorted(
                [item for item in title_records if isinstance(item, dict) and item.get("title")],
                key=lambda item: (not bool(item.get("is_primary")), str(item.get("language") or "")),
            )
            for record in title_records[:14]:
                language = str(record.get("language") or "other")
                traits = ", ".join(str(item) for item in (record.get("traits") or []))
                title_lines.append(
                    f"{language}: {record.get('title')}"
                    + (f" ({traits})" if traits else "")
                )
        if title_lines:
            add_line("Known titles", " | ".join(title_lines))

        link_lines = []
        raw_links = data.get("links") or []
        if isinstance(raw_links, list):
            for item in raw_links[:12]:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("name_display") or item.get("name") or item.get("type") or "Source")
                url = str(item.get("url") or "").strip()
                if url.startswith("https://"):
                    link_lines.append(f"{label}: {url}")
                elif label:
                    link_lines.append(label)
        if link_lines:
            add_line("External links", " | ".join(link_lines))

        if self.mangabaka_volume_records:
            volume_lines = []
            for volume in self.mangabaka_volume_records[:16]:
                if not isinstance(volume, dict):
                    continue
                label = str(volume.get("title") or f"Volume {volume.get('number', '?')}")
                extras = []
                if volume.get("isbn"):
                    extras.append(f"ISBN {volume['isbn']}")
                if volume.get("published"):
                    extras.append(str(volume["published"]))
                volume_lines.append(label + (f" ({'; '.join(extras)})" if extras else ""))
            if volume_lines:
                add_line("Published volume records", " | ".join(volume_lines))

        if self.mangabaka_news:
            news_lines = []
            for news in self.mangabaka_news[:8]:
                if not isinstance(news, dict):
                    continue
                title = str(news.get("title") or news.get("headline") or news.get("name") or "").strip()
                summary = str(news.get("summary") or news.get("description") or news.get("excerpt") or "").strip()
                published_at = str(
                    news.get("published_at") or news.get("published")
                    or news.get("created_at") or news.get("date") or ""
                ).strip()
                url = str(news.get("url") or news.get("link") or "").strip()
                parts = [part for part in (title, published_at, summary) if part]
                if url.startswith("https://"):
                    parts.append(url)
                if parts:
                    news_lines.append(" — ".join(parts))
            if news_lines:
                add_line("MangaBaka news", " | ".join(news_lines))

        attribution = QLabel("Metadata aggregated by MangaBaka; source-site data remains subject to its own terms.")
        attribution.setWordWrap(True)
        attribution.setStyleSheet(f"font-size:10px;color:{COLORS['muted']};")
        layout.addWidget(attribution)
        return frame

    def _hero(self):
        hero = QFrame(); hero.setObjectName("hero")
        box = QHBoxLayout(hero); box.setContentsMargins(24, 24, 28, 24); box.setSpacing(30)
        cover = QLabel()
        cover.setObjectName("detailHeroCover")
        cover.setFixedSize(235, 335)
        cover.setAlignment(Qt.AlignCenter)
        cover.setProperty("coverLoading", False)
        members = self._value("_series_members") or []
        is_bundle = len(members) > 1
        try:
            is_bundle = is_bundle or int(self._value("_series_count") or 0) > 1
        except (TypeError, ValueError, OverflowError):
            pass
        override = get_display_override(self._value("id")) if not is_bundle else {}
        path = override.get("custom_cover_path") or self._value("cover_path")
        if path:
            pix = QPixmap(str(path))
            if not pix.isNull(): cover.setPixmap(self._cropped_cover(pix, cover.size(), 14))
        if cover.pixmap() is None or cover.pixmap().isNull():
            self._load_remote_cover(cover)
        box.addWidget(cover, alignment=Qt.AlignTop)

        info = QVBoxLayout(); info.setSpacing(10)
        title = QLabel(self._title()); title.setObjectName("detailHeroTitle"); title.setWordWrap(True)
        title.setStyleSheet(f"font-size:34px;font-weight:850;color:{COLORS['primary']};letter-spacing:-1px;")
        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        title_row.addWidget(title, 1)
        if self._library_group() is not None:
            menu_button = QToolButton()
            menu_button.setObjectName("detailMenu")
            menu_button.setText("⋮")
            menu_button.setFixedSize(42, 42)
            menu_button.setCursor(Qt.PointingHandCursor)
            menu_button.clicked.connect(self._show_detail_menu)
            title_row.addWidget(menu_button, 0, Qt.AlignTop)

        if self._value("id") is not None:
            try:
                favorite_work_id = int(self._value("id"))
            except (TypeError, ValueError, OverflowError):
                favorite_work_id = None
            if favorite_work_id is not None:
                favorite_enabled = is_work_favorite(favorite_work_id)
                favorite_button = QPushButton(
                    "♥ Favorited" if favorite_enabled else "♡ Favorite"
                )
                favorite_button.setObjectName("detailFavoriteButton")
                favorite_button.setCheckable(True)
                favorite_button.setChecked(favorite_enabled)
                favorite_button.setAccessibleName("Toggle favorite")
                favorite_button.setToolTip("Save this title independently of Library membership")
                favorite_button.clicked.connect(
                    lambda checked, work_id=favorite_work_id, button=favorite_button:
                        self._toggle_favorite(work_id, checked, button)
                )
                title_row.addWidget(favorite_button, 0, Qt.AlignTop)

                members = self._value("_series_members") or []
                is_bundle = len(members) > 1
                try:
                    is_bundle = is_bundle or int(self._value("_series_count") or 0) > 1
                except (TypeError, ValueError, OverflowError):
                    pass
                if not is_bundle:
                    customize_button = QPushButton("Customize")
                    customize_button.setObjectName("detailCustomizeButton")
                    customize_button.setAccessibleName("Customize title and cover")
                    customize_button.setToolTip("Set a global display title or cover for this title")
                    customize_button.clicked.connect(self._open_display_identity_editor)
                    title_row.addWidget(customize_button, 0, Qt.AlignTop)
        info.addLayout(title_row)
        alt = self._value("native") or self._value("title_native") or ""
        if alt:
            native = QLabel(str(alt)); native.setObjectName("detailHeroNativeTitle"); native.setStyleSheet(muted_label_stylesheet()); info.addWidget(native)
        if self._is_reading_media():
            chapter_total = self._value("chapters")
            volume_total = self._value("volumes")
            counts = [
                f"{chapter_total} chapters" if chapter_total else None,
                f"{volume_total} volumes" if volume_total else None,
            ]
        else:
            counts = [
                f"{self._value('episodes')} eps" if self._value("episodes") else None,
                f"{self._value('chapters')} ch" if self._value("chapters") else None,
            ]
        meta = "  ·  ".join(
            str(value)
            for value in [self._value("format"), self._value("start_year"), *counts]
            if value
        )
        if meta:
            metadata = QLabel(meta); metadata.setObjectName("detailHeroMetadata"); metadata.setStyleSheet(f"color:{COLORS['secondary']};font-size:13px;"); info.addWidget(metadata)
        score = self._value("score") or self._value("averageScore")
        score_label = QLabel(f"★  {score}%" if score else "—  No score"); score_label.setObjectName("detailHeroScore"); score_label.setStyleSheet(f"color:{COLORS['accent']};font-size:18px;font-weight:800;"); info.addWidget(score_label)

        info.addSpacing(10)
        description = QLabel(self._value("description") or "No description saved locally.")
        description.setObjectName("detailHeroDescription")
        description.setWordWrap(True)
        description.setTextFormat(Qt.RichText)
        description.setStyleSheet(f"color:{COLORS['secondary']};font-size:14px;")
        info.addWidget(description)
        info.addStretch()

        box.addLayout(info, 1)
        return hero

    def _load_remote_cover(self, label):
        work_id = self._value("id")
        cover_url = self._value("cover_url") or (self._value("coverImage") or {}).get("large")
        if not work_id or not cover_url:
            self._set_cover_placeholder(label, False, "NO COVER")
            return
        cover_url = str(cover_url)
        cached = self._cover_cache.get(cover_url)
        if cached is not None and not cached.isNull():
            label.setProperty("coverLoading", False)
            label.setText("")
            label.setPixmap(self._cropped_cover(cached, label.size(), 14))
            label.style().unpolish(label)
            label.style().polish(label)
            return
        if cover_url in self._cover_failures:
            self._set_cover_placeholder(label, False, "COVER UNAVAILABLE")
            return
        self._set_cover_placeholder(label, True, "Loading artwork…")
        reply = self._cover_manager.get(QNetworkRequest(QUrl(cover_url)))
        self._cover_reply = reply
        reply.finished.connect(
            lambda label=label, work_id=work_id, cover_url=cover_url, reply=reply:
                self._remote_cover_finished(label, work_id, cover_url, reply)
        )

    def _remote_cover_finished(self, label, work_id, cover_url, reply=None):
        # Multiple page builds can leave more than one cover request in flight.
        # Use the reply that fired this callback rather than whichever reply was
        # most recently stored on the page.
        if reply is None:
            reply = self._cover_reply
        if self._cover_reply is reply:
            self._cover_reply = None

        if reply is not None and reply.error() == reply.NetworkError.NoError:
            pix = QPixmap()
            if pix.loadFromData(reply.readAll()):
                self._cover_cache[cover_url] = pix

                # The user can navigate away before the network finishes. Qt
                # deletes the old hero QLabel with its page content, while the
                # reply can still complete. Cache/save the image, but never
                # touch an invalid C++ widget wrapper.
                if label is not None and isValid(label):
                    try:
                        label.setProperty("coverLoading", False)
                        label.setText("")
                        label.setPixmap(self._cropped_cover(pix, label.size(), 14))
                        label.style().unpolish(label)
                        label.style().polish(label)
                        label.update()
                    except RuntimeError:
                        pass

                try:
                    IMAGE_DIRECTORY.mkdir(parents=True, exist_ok=True)
                    path = IMAGE_DIRECTORY / f"{work_id}.jpg"
                    if pix.save(str(path), "JPG", 85):
                        save_cover_path(work_id, str(path))
                except Exception:
                    pass
            else:
                self._cover_failures.add(cover_url)
                if label is not None and isValid(label):
                    self._set_cover_placeholder(label, False, "COVER UNAVAILABLE")
        else:
            self._cover_failures.add(cover_url)
            if label is not None and isValid(label):
                self._set_cover_placeholder(label, False, "COVER UNAVAILABLE")

        if reply is not None:
            reply.deleteLater()

    def _library_group(self):
        # Library cards already carry their complete series grouping. Reuse it
        # instead of rebuilding every Library series when opening a detail page.
        members = self._value("_series_members")
        if members:
            return self.work

        # Search/relation entries may not have a cached Library group, so keep
        # the old lookup as a fallback for those paths.
        work_id = self._value("id")
        if work_id is None:
            return None
        current_id = int(work_id)
        for group in get_library_series():
            group_members = group.get("_series_members") or []
            if any(int(member["id"]) == current_id for member in group_members):
                return group
        return None

    def _show_detail_menu(self):
        group = self._library_group()
        if group is None:
            return

        menu = QMenu(self)
        menu.setStyleSheet(
            f"""
            QMenu {{
                background: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 12px;
                padding: 6px;
            }}
            QPushButton#detailMenuItem {{
                background: transparent;
                color: {COLORS['secondary']};
                border: 1px solid transparent;
                border-radius: 9px;
                padding: 8px 12px;
                text-align: left;
                font-weight: 700;
            }}
            QPushButton#detailMenuItem:hover {{
                background: {COLORS['surface_hover']};
                border-color: {COLORS['accent']};
                color: {COLORS['primary']};
            }}
            QPushButton#detailDeleteItem {{
                background: transparent;
                color: {COLORS['danger']};
                border: 1px solid transparent;
                border-radius: 9px;
                padding: 8px 12px;
                text-align: left;
                font-weight: 800;
            }}
            QPushButton#detailDeleteItem:hover {{
                background: {COLORS['surface_hover']};
                border-color: {COLORS['accent']};
                color: {COLORS['danger']};
            }}
            """
        )

        def add_item(text, object_name, callback):
            action = QWidgetAction(menu)
            button = QPushButton(text)
            button.setObjectName(object_name)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda: (menu.hide(), callback()))
            action.setDefaultWidget(button)
            menu.addAction(action)

        add_item("Add to bundle", "detailMenuItem", self._open_add_bundle_dialog)
        add_item("Remove from bundle", "detailMenuItem", self._open_remove_bundle_dialog)

        menu.addSeparator()

        try:
            has_bundle = len(group.get("_series_members") or []) > 1
        except (TypeError, ValueError):
            has_bundle = False

        if has_bundle:
            add_item(
                "Edit Bundle Appearance…",
                "detailMenuItem",
                lambda: self.bundle_edit_requested.emit(group),
            )

        menu.addSeparator()
        add_item("Delete", "detailDeleteItem", lambda: self._show_delete_confirmation(group))

        button = self.sender()
        menu.exec(
            button.mapToGlobal(button.rect().bottomLeft())
            if isinstance(button, QToolButton)
            else self.mapToGlobal(self.rect().center())
        )

    def _open_add_bundle_dialog(self):
        group = self._library_group()
        if group is None:
            return

        excluded_ids = {
            int(member["id"])
            for member in (group.get("_series_members") or [])
            if member["id"] is not None
        }
        dialog = BundleSearchDialog(excluded_ids=excluded_ids, parent=self)
        if dialog.exec() != QDialog.Accepted or dialog.selected_work is None:
            return

        selected = dialog.selected_work
        work_id = int(selected["id"])
        current_id = int(self._value("id"))

        try:
            details = get_media_details(work_id)
            if not details:
                raise RuntimeError("Could not load that work.")

            save_anime(details)
            character_connection = details.get("characters")
            character_edges = (
                character_connection.get("edges")
                if isinstance(character_connection, dict)
                else None
            )
            if details.get("_characters_snapshot_valid", True) is False:
                save_characters(work_id, None)
            else:
                save_characters(work_id, character_edges)
            staff_connection = details.get("staff")
            staff_edges = (
                staff_connection.get("edges")
                if isinstance(staff_connection, dict)
                else None
            )
            save_staff(work_id, staff_edges)
            # Episode metadata is synchronized by get_episode_data() for the
            # exact AniList member. AniList streamingEpisodes is not an
            # episode-numbered database source.

            connection = get_connection()
            in_library = connection.execute(
                "SELECT 1 FROM user_library WHERE work_id = ? LIMIT 1",
                (work_id,),
            ).fetchone() is not None
            connection.close()

            if not in_library:
                add_to_library(work_id, "Planning")

            if not add_manual_bundle_link(current_id, work_id):
                QMessageBox.information(
                    self,
                    "Bundle unchanged",
                    "That work is already linked to this bundle.",
                )
                return

            self.bundle_changed.emit()
            refreshed = get_work(current_id)
            if refreshed:
                self.set_work(refreshed)
        except Exception as error:
            QMessageBox.critical(self, "Could not add to bundle", str(error))

    def _open_remove_bundle_dialog(self):
        work_id = self._value("id")
        if work_id is None:
            return

        group = self._library_group()
        if group is None:
            return

        members = list(group.get("_series_members") or [])
        partners = [
            {
                "partner_id": int(member["id"]),
                "partner_title": self._member_title(member),
                "partner_type": member["type"],
                "partner_format": member["format"],
            }
            for member in members
            if int(member["id"]) != int(work_id)
        ]

        dialog = BundleRemoveDialog(partners, parent=self)
        if dialog.exec() != QDialog.Accepted or dialog.selected_id is None:
            return

        selected_id = int(dialog.selected_id)

        # "Remove from bundle" means remove that bundled library entry entirely.
        # It must not merely unlink the item and leave it in the Library.
        if not delete_work_data(selected_id):
            QMessageBox.critical(
                self,
                "Could not remove bundled item",
                "The selected bundled item could not be removed from NekoTrack.",
            )
            return

        connection = get_connection()
        still_exists = connection.execute(
            "SELECT 1 FROM works WHERE id = ? LIMIT 1",
            (selected_id,),
        ).fetchone() is not None
        still_in_library = connection.execute(
            "SELECT 1 FROM user_library WHERE work_id = ? LIMIT 1",
            (selected_id,),
        ).fetchone() is not None
        connection.close()

        if still_exists or still_in_library:
            QMessageBox.critical(
                self,
                "Remove failed",
                "The selected bundled item was not fully removed from NekoTrack.",
            )
            return

        self.bundle_changed.emit()
        refreshed = get_work(int(work_id))
        if refreshed:
            self.set_work(refreshed)
        else:
            self.work = None
            self.back_requested.emit()

    def _show_delete_confirmation(self, group):
        if self._delete_overlay is not None:
            self._delete_overlay.deleteLater()
            self._delete_overlay = None

        members = list(group.get("_series_members") or [])
        current_id = int(self._value("id"))
        is_bundle = len(members) > 1

        overlay = QFrame(self)
        overlay.setObjectName("deleteOverlay")
        overlay.setFixedWidth(460)
        layout = QVBoxLayout(overlay)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        title = QLabel("Delete from NekoTrack?")
        title.setObjectName("deleteTitle")
        layout.addWidget(title)

        message = QLabel(
            "This will permanently remove the selected local data and cached cover."
            if not is_bundle
            else "Choose the bundle entry you want to permanently remove, or delete the entire bundle."
        )
        message.setObjectName("deleteMessage")
        message.setWordWrap(True)
        layout.addWidget(message)

        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel = QPushButton("Cancel")
        cancel.setObjectName("deleteCancel")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(lambda: self._close_delete_overlay(overlay))
        buttons.addWidget(cancel)

        if is_bundle:
            member_list = QListWidget()
            member_list.setObjectName("deleteMemberList")
            member_list.setMinimumHeight(min(220, max(90, 58 * min(len(members), 4))))
            member_list.setMaximumHeight(260)
            member_list.setStyleSheet(
                f"""
                QListWidget#deleteMemberList {{
                    background: {COLORS['background_alt']};
                    border: 1px solid {COLORS['frame']};
                    border-radius: 9px;
                    padding: 4px;
                    color: {COLORS['primary']};
                }}
                QListWidget#deleteMemberList::item {{
                    padding: 9px 10px;
                    border: 1px solid transparent;
                    border-radius: 7px;
                    color: {COLORS['secondary']};
                }}
                QListWidget#deleteMemberList::item:hover {{
                    background: {COLORS['surface_hover']};
                    border-color: {COLORS['accent']};
                    color: {COLORS['primary']};
                }}
                QListWidget#deleteMemberList::item:selected {{
                    background: {COLORS['accent_soft']};
                    border-color: {COLORS['accent']};
                    color: {COLORS['primary']};
                }}
                """
            )
            selected_row = 0
            for index, member in enumerate(members):
                item = QListWidgetItem(self._member_title(member))
                item.setData(Qt.UserRole, int(member["id"]))
                member_list.addItem(item)
                if int(member["id"]) == current_id:
                    selected_row = index
            member_list.setCurrentRow(selected_row)
            layout.addWidget(member_list)

            entry_button = QPushButton("Delete selected entry")
            entry_button.setObjectName("deleteConfirm")
            entry_button.setCursor(Qt.PointingHandCursor)
            entry_button.clicked.connect(
                lambda: self._delete_selected_bundle_member(member_list, overlay)
            )
            buttons.addWidget(entry_button)

            bundle_button = QPushButton("Delete entire bundle")
            bundle_button.setObjectName("deleteBundle")
            bundle_button.setCursor(Qt.PointingHandCursor)
            bundle_button.clicked.connect(
                lambda: self._delete_from_detail(
                    [int(member["id"]) for member in members],
                    overlay,
                )
            )
            buttons.addWidget(bundle_button)
        else:
            confirm = QPushButton("Delete")
            confirm.setObjectName("deleteConfirm")
            confirm.setCursor(Qt.PointingHandCursor)
            confirm.clicked.connect(
                lambda: self._delete_from_detail([current_id], overlay)
            )
            buttons.addWidget(confirm)

        layout.addLayout(buttons)
        overlay.adjustSize()
        x = max(18, (self.width() - overlay.width()) // 2)
        y = max(18, (self.height() - overlay.height()) // 2)
        overlay.move(x, y)
        overlay.raise_()
        overlay.show()
        self._delete_overlay = overlay

    def _close_delete_overlay(self, overlay):
        if overlay is self._delete_overlay:
            self._delete_overlay = None
        overlay.deleteLater()

    def _delete_selected_bundle_member(self, member_list, overlay):
        item = member_list.currentItem()
        if item is None:
            return
        self._delete_from_detail([int(item.data(Qt.UserRole))], overlay)

    def _delete_from_detail(self, work_ids, overlay):
        target_ids = [int(work_id) for work_id in work_ids]
        deleted_ids = []

        for work_id in target_ids:
            if delete_work_data(work_id):
                deleted_ids.append(work_id)

        overlay.deleteLater()
        self._delete_overlay = None

        # Verify the exact selected entries are gone before rebuilding the
        # Library. This prevents a stale bundle view from hiding a failed delete.
        remaining_ids = []
        connection = get_connection()
        for work_id in target_ids:
            if connection.execute(
                "SELECT 1 FROM works WHERE id = ? LIMIT 1",
                (work_id,),
            ).fetchone() is not None:
                remaining_ids.append(work_id)
        connection.close()

        if remaining_ids:
            QMessageBox.critical(
                self,
                "Delete failed",
                "NekoTrack could not remove the selected entry from its local database.",
            )
            return

        if deleted_ids:
            self.bundle_changed.emit()
            self.work = None
            self.back_requested.emit()

    def _cropped_cover(self, pixmap, size, radius):
        scaled = pixmap.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = max(0, (scaled.width() - size.width()) // 2); y = max(0, (scaled.height() - size.height()) // 2)
        cropped = scaled.copy(x, y, size.width(), size.height()); result = QPixmap(size); result.fill(Qt.transparent)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = result.rect().adjusted(2, 2, -2, -2)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.save()
        painter.setClipPath(path)
        painter.drawPixmap(rect.topLeft(), cropped.scaled(rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        painter.restore()
        painter.setPen(QPen(QColor(COLORS["accent"]), 3.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        painter.end()
        return result

    def _is_reading_media(self):
        """True for AniList Manga entries, including light novels and one-shots."""
        media_type = str(self._value("type") or "").upper()
        media_format = str(self._value("format") or "").upper()
        return media_type == "MANGA" or media_format in {
            "MANGA", "NOVEL", "ONE_SHOT",
        }

    def _work_count(self, work, key):
        """Read a published count, falling back to saved MangaBaka metadata.

        Older imports can have a blank count when MangaBaka's preferred field
        existed with a null value. The raw provider payload is retained locally,
        so use its alternate count fields rather than leaving the tracker unusable.
        """
        def parse_count(raw):
            if raw is None or isinstance(raw, bool):
                return 0
            try:
                count = int(raw)
                return count if count > 0 else 0
            except (TypeError, ValueError, OverflowError):
                pass
            if isinstance(raw, str):
                import re
                match = re.search(r"(?<![-0-9])[0-9]+", raw)
                if match:
                    try:
                        return max(0, int(match.group(0)))
                    except (TypeError, ValueError, OverflowError):
                        return 0
            return 0

        try:
            value = parse_count(work[key])
        except (KeyError, IndexError, TypeError):
            value = 0
        if value:
            return value

        try:
            work_id = int(work["id"])
        except (KeyError, IndexError, TypeError, ValueError, OverflowError):
            return 0
        try:
            metadata = get_provider_metadata(work_id, "mangabaka")
        except Exception:
            metadata = None
        if not isinstance(metadata, dict):
            return 0

        if key == "chapters":
            fields = ("total_chapters", "chapters", "chapter_count")
        elif key == "volumes":
            fields = ("total_volumes", "volumes", "final_volume", "volume_count")
        else:
            fields = ()

        for field in fields:
            value = parse_count(metadata.get(field))
            if value:
                return value
        return 0

    def _reading_section(self):
        """Show honest numeric chapter/volume progress without fictional item cards."""
        members = self._episode_members()
        member_ids = {int(member["id"]) for member in members}
        if self._selected_episode_work_id not in member_ids:
            self._selected_episode_work_id = (
                int(members[0]["id"]) if members else self._value("id")
            )
        selected_id = self._selected_episode_work_id
        selected_work = get_work(selected_id) if selected_id is not None else None
        if selected_work is None:
            selected_work = self.work

        frame = QFrame()
        frame.setObjectName("section")
        frame.setProperty("_reading_section", True)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("Reading progress")
        title.setObjectName("readingSectionTitle")
        title.setStyleSheet(
            f"font-size:17px;font-weight:800;color:{COLORS['primary']};"
        )
        header.addWidget(title)
        header.addStretch(1)

        if len(members) > 1:
            selected_index = next(
                (
                    index
                    for index, member in enumerate(members, start=1)
                    if int(member["id"]) == int(selected_id)
                ),
                1,
            )
            member_button = QToolButton()
            member_button.setText(f"Entry {selected_index}  ▾")
            member_button.setPopupMode(QToolButton.InstantPopup)
            member_button.setCursor(Qt.PointingHandCursor)
            menu = QMenu(member_button)
            for index, member in enumerate(members, start=1):
                member_id = int(member["id"])
                action = menu.addAction(
                    f"Entry {index} — {self._member_title(member)}"
                )
                action.setCheckable(True)
                action.setChecked(member_id == int(selected_id))
                action.triggered.connect(
                    lambda checked=False, work_id=member_id:
                        self._reading_member_changed(work_id)
                )
            member_button.setMenu(menu)
            header.addWidget(member_button)

        layout.addLayout(header)

        if selected_id is None:
            empty = QLabel("Save this work to your Library to track reading progress.")
            empty.setWordWrap(True)
            empty.setStyleSheet(muted_label_stylesheet())
            layout.addWidget(empty)
            return frame

        is_in_library = is_work_in_library(selected_id)

        if not is_in_library:
            note = QLabel(
                "Reading progress is saved to your Library and restored when you return."
            )
            note.setWordWrap(True)
            note.setStyleSheet(muted_label_stylesheet())
            layout.addWidget(note)

            track_button = QPushButton("＋  Track this work in Library")
            track_button.setObjectName("trackReadingWorkButton")
            track_button.setCursor(Qt.PointingHandCursor)
            track_button.clicked.connect(
                lambda checked=False, wid=int(selected_id): self._start_reading_tracking(wid)
            )
            layout.addWidget(track_button, 0, Qt.AlignLeft)

        chapter_total = self._work_count(selected_work, "chapters")
        volume_total = self._work_count(selected_work, "volumes")
        self._reading_kind_section(
            layout, int(selected_id), "chapter", chapter_total, is_in_library
        )
        self._reading_kind_section(
            layout, int(selected_id), "volume", volume_total, is_in_library
        )
        return frame

    def _reading_kind_section(
        self, parent_layout, work_id, item_type, total, enabled=True
    ):
        label = "Chapters" if item_type == "chapter" else "Volumes"
        section = QFrame()
        section.setObjectName("readingKindSection")
        box = QVBoxLayout(section)
        box.setContentsMargins(12, 12, 12, 12)
        box.setSpacing(8)

        header = QHBoxLayout()
        heading = QLabel(label)
        heading.setObjectName("readingKindHeading")
        heading.setStyleSheet(
            f"font-size:14px;font-weight:850;color:{COLORS['primary']};"
        )
        header.addWidget(heading)
        header.addStretch(1)

        read_count, _ = get_reading_progress(work_id, item_type, total)
        if total > 0:
            read_count = min(read_count, total)
        progress_label = QLabel(
            f"{read_count} / {total} read"
            if total
            else f"{read_count} read · total unknown"
        )
        progress_label.setObjectName("readingKindProgress")
        progress_label.setStyleSheet(
            f"color:{COLORS['accent']};font-size:11px;font-weight:850;"
        )
        header.addWidget(progress_label)
        box.addLayout(header)

        progress_bar = None
        if total > 0:
            progress_bar = QProgressBar()
            progress_bar.setObjectName("readingProgressBar")
            progress_bar.setRange(0, 100)
            progress_bar.setValue(round(100 * min(read_count, total) / total))
            progress_bar.setTextVisible(False)
            progress_bar.setFixedHeight(7)
            progress_bar.setStyleSheet(
                f"QProgressBar {{ background:{COLORS['background_alt']};"
                f"border:0;border-radius:3px; }}"
                f"QProgressBar::chunk {{ background:{COLORS['accent']};"
                "border-radius:3px; }}"
            )
            box.addWidget(progress_bar)

        control_row = QHBoxLayout()
        description = QLabel(
            "How many have you read?"
            if total
            else "Enter the number you've read; the total is not known."
        )
        description.setWordWrap(True)
        description.setStyleSheet(muted_label_stylesheet())
        control_row.addWidget(description, 1)

        counter = QSpinBox()
        counter.setObjectName("readingProgressCount")
        counter.setMinimum(0)
        counter.setMaximum(min(max(total, 1), 1_000_000) if total else 1_000_000)
        counter.setSingleStep(1)
        counter.setKeyboardTracking(False)
        counter.setSuffix(f" / {total}" if total else " read")
        counter.setValue(min(read_count, counter.maximum()))
        counter.setEnabled(bool(enabled))
        counter.setToolTip(
            f"Number of {label.lower()} read for this entry."
        )
        counter.valueChanged.connect(
            lambda value, wid=work_id, kind=item_type, total_hint=total,
                   status_label=progress_label, bar=progress_bar:
                self._reading_progress_changed(
                    wid, kind, value, total_hint, status_label, bar
                )
        )
        control_row.addWidget(counter, 0, Qt.AlignVCenter)
        box.addLayout(control_row)
        parent_layout.addWidget(section)

    def _start_reading_tracking(self, work_id):
        """Create library membership first, then enable the persistent counters."""
        try:
            add_to_library(int(work_id), "Planning")
        except Exception as error:
            QMessageBox.warning(
                self, "Could not start reading tracker",
                f"NekoTrack could not add this work to your Library.\n\n{error}",
            )
            return
        self._replace_reading_section()
        self.bundle_changed.emit()

    def _reading_progress_changed(
        self, work_id, item_type, read_count, total_hint, label, progress_bar=None
    ):
        saved_count, _total = set_reading_progress_count(
            work_id, item_type, read_count, total_hint
        )
        label.setText(
            f"{saved_count} / {total_hint} read"
            if total_hint
            else f"{saved_count} read · total unknown"
        )
        if progress_bar is not None and total_hint:
            progress_bar.setValue(round(100 * min(saved_count, total_hint) / total_hint))

    def _reading_member_changed(self, work_id):
        self._selected_episode_work_id = int(work_id)
        self._replace_reading_section()

    def _replace_reading_section(self):
        content = self.scroll_area.widget()
        root = content.layout() if content is not None else None
        if root is None:
            return

        for index in range(root.count()):
            item = root.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget is None or not widget.property("_reading_section"):
                continue
            new_frame = self._reading_section()
            new_frame.setProperty("_reading_section", True)
            root.replaceWidget(widget, new_frame)
            widget.deleteLater()
            return

    def _episodes_section(self, defer_cards=False):
        if self._is_reading_media():
            return self._reading_section()

        members = self._episode_members()
        member_ids = {int(member["id"]) for member in members}
        if self._selected_episode_work_id not in member_ids:
            self._selected_episode_work_id = (
                int(members[0]["id"])
                if members
                else self._value("id")
            )

        selected_id = self._selected_episode_work_id
        episodes = get_episodes(selected_id) if selected_id is not None else []
        if selected_id is not None and episodes:
            self._start_episode_image_cache(
                selected_id,
                [dict(episode) for episode in episodes],
            )

        frame = QFrame()
        frame.setObjectName("section")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(20, 18, 20, 20)
        lay.setSpacing(10)

        header = QHBoxLayout()

        if len(members) > 1:
            selected_season = next(
                (
                    index
                    for index, member in enumerate(members, start=1)
                    if int(member["id"]) == int(selected_id)
                ),
                1,
            )
            title = QLabel(f"Season {selected_season} Episodes")
        else:
            title = QLabel("Episodes")

        title.setStyleSheet(
            f"font-size:17px;font-weight:800;color:{COLORS['primary']};"
        )
        header.addWidget(title)

        source_status = self._episode_source_status.get(int(selected_id), {}) if selected_id is not None else {}
        source_text = "TMDB"
        if source_status:
            source_text = f"TMDB {source_status.get('tmdb', 0)}"
        source = QLabel(source_text)
        source.setStyleSheet(
            f"""
            QLabel {{
                color:{COLORS['secondary']};
                background:{COLORS['surface_alt']};
                border:1px solid {COLORS['border']};
                border-radius:8px;
                padding:4px 8px;
                font-size:10px;
                font-weight:800;
            }}
            """
        )
        header.addWidget(source)

        header.addStretch()

        watched = sum(1 for ep in episodes if ep["watched"])
        total = len(episodes)
        count = QLabel(
            f"{watched} / {total} watched"
            if total
            else "No episode list saved"
        )
        count.setStyleSheet(f"color:{COLORS['accent']};font-weight:800;")
        header.addWidget(count)

        if len(members) > 1:
            season_button = QToolButton()
            season_button.setText(f"Season {selected_season}  ▾")
            season_button.setPopupMode(QToolButton.InstantPopup)
            season_button.setCursor(Qt.PointingHandCursor)
            season_button.setStyleSheet(
                f"""
                QToolButton {{
                    background:{COLORS['surface_alt']};
                    color:{COLORS['primary']};
                    border:1px solid {COLORS['border']};
                    border-radius:9px;
                    padding:7px 12px;
                    font-weight:800;
                }}
                QToolButton:hover {{
                    background:{COLORS['surface_hover']};
                    border-color:{COLORS['accent']};
                }}
                QToolButton::menu-indicator {{
                    image:none;
                    width:0px;
                }}
                """
            )

            menu = QMenu(season_button)
            for index, member in enumerate(members, start=1):
                member_id = int(member["id"])
                member_title = self._member_title(member)
                release_date = self._member_release_date(member)
                action = menu.addAction(
                    f"Season {index}  —  {member_title}  ·  {release_date}"
                )
                action.setCheckable(True)
                action.setChecked(member_id == int(selected_id))
                action.triggered.connect(
                    lambda checked=False, work_id=member_id:
                        self._episode_season_changed(work_id)
                )
            season_button.setMenu(menu)
            header.addWidget(season_button)

        lay.addLayout(header)

        selected_work = get_work(selected_id) if selected_id is not None else None

        # Refresh each season once per detail-page session. This also clears
        # stale thumbnail URLs left by earlier episode imports.
        if (
            selected_id is not None
            and not episodes
            and selected_id not in self._episode_sync_completed
            and selected_id not in self._episode_sync_errors
        ):
            (
                title_variants,
                start_date,
                end_date,
                expected_episodes,
                tmdb_id,
                tmdb_season_number,
                media_format,
            ) = self._episode_tmdb_context(
                selected_id,
                members,
                selected_work,
            )
            self._start_episode_sync(
                selected_id,
                title_variants,
                start_date,
                end_date,
                expected_episodes,
                tmdb_id,
                tmdb_season_number,
                media_format,
            )

        if not episodes:
            sync_error = self._episode_sync_errors.get(int(selected_id)) if selected_id is not None else None
            loading_state = (
                not sync_error
                and selected_work is not None
                and int(selected_work["episodes"] or 0) > 0
            )
            message = (
                f"Could not load episode data: {sync_error}"
                if sync_error
                else (
                    "Loading episode data…"
                    if loading_state
                    else "No episode data is available for this season."
                )
            )
            label = QLabel(message)
            label.setObjectName(
                "detailEpisodeLoadingLabel" if loading_state else "detailEpisodeMessage"
            )
            label.setStyleSheet(muted_label_stylesheet())
            label.setWordWrap(True)
            lay.addWidget(label)
            if loading_state:
                lay.addWidget(self._episode_skeleton_strip())
            return frame

        if defer_cards:
            frame._pending_episode_cards = [dict(ep) for ep in episodes]
        else:
            for ep in episodes:
                card = EpisodeCard(ep)
                card.watched_changed.connect(self._episode_toggled)
                lay.addWidget(card)

        return frame

    def _episode_members(self):
        members = list(self._value("_series_members") or [])
        if not members:
            current = self.work
            return [current] if current is not None else []

        def sort_key(member):
            if hasattr(member, "get"):
                start_date = member.get("startDate") or {}
                year = start_date.get("year") or member.get("start_year")
                month = start_date.get("month") or member.get("start_month") or 0
                day = start_date.get("day") or member.get("start_day") or 0
            else:
                year = member["start_year"]
                month = member["start_month"] if "start_month" in member.keys() else 0
                day = member["start_day"] if "start_day" in member.keys() else 0

            return (
                year is None,
                year or 9999,
                month or 0,
                day or 0,
                int(member["id"]),
            )

        return sorted(members, key=sort_key)

    def _episode_season_changed(self, work_id):
        self._selected_episode_work_id = int(work_id)
        self._replace_episode_section()

    def _episode_tmdb_context(self, selected_id, members, selected_work=None):
        selected_id = int(selected_id)
        selected_work = selected_work or get_work(selected_id)
        if selected_work is None:
            raise RuntimeError("Selected season is no longer available.")

        index = next(
            (
                index
                for index, member in enumerate(members, start=1)
                if int(member["id"]) == selected_id
            ),
            1,
        )

        def member_date(member):
            if hasattr(member, "get"):
                year = member.get("start_year")
                month = member.get("start_month") or 0
                day = member.get("start_day") or 0
            else:
                year = member["start_year"]
                month = member["start_month"] if "start_month" in member.keys() else 0
                day = member["start_day"] if "start_day" in member.keys() else 0
            if year is None:
                return None
            return f"{int(year):04d}-{int(month or 1):02d}-{int(day or 1):02d}"

        start_date = member_date(members[index - 1])
        end_date = member_date(members[index]) if index < len(members) else None

        title_variants = [
            str(selected_work["title"] or "").strip(),
            str(self._member_title(selected_work) or "").strip(),
            *get_alternate_titles(selected_id),
        ]
        title_variants = list(dict.fromkeys(value for value in title_variants if value))

        tmdb_id, tmdb_season_number = get_tmdb_mapping(selected_id)

        expected_episodes = selected_work["episodes"]
        media_format = str(selected_work["format"] or "").upper()

        return (
            title_variants,
            start_date,
            end_date,
            expected_episodes,
            tmdb_id,
            tmdb_season_number,
            media_format,
        )

    def _start_episode_sync(
        self,
        work_id,
        title_variants,
        start_date,
        end_date,
        expected_episodes,
        tmdb_id,
        tmdb_season_number,
        media_format=None,
    ):
        if self._shutdown_event.is_set() or self._is_reading_media():
            return
        work_id = int(work_id)

        if work_id in self._episode_sync_completed:
            return

        if self._episode_sync_thread is not None:
            try:
                if self._episode_sync_thread.isRunning():
                    return
            except RuntimeError:
                # Qt has already deleted the underlying QThread object.
                self._episode_sync_thread = None
                self._episode_sync_worker = None
                self._episode_sync_work_id = None

        self._episode_sync_work_id = work_id
        self._episode_sync_thread = QThread(self)
        self._episode_sync_worker = EpisodeSyncWorker(
            work_id,
            title_variants,
            start_date,
            end_date,
            expected_episodes,
            tmdb_id,
            tmdb_season_number,
            media_format,
        )
        self._episode_sync_worker.moveToThread(self._episode_sync_thread)

        self._episode_sync_thread.started.connect(
            self._episode_sync_worker.run
        )
        self._episode_sync_worker.finished.connect(self._episode_sync_finished)
        self._episode_sync_worker.error.connect(self._episode_sync_error)
        worker = self._episode_sync_worker
        thread = self._episode_sync_thread
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        # Clear Python references before Qt destroys the C++ QThread object.
        thread.finished.connect(
            lambda t=thread: self._episode_sync_thread_finished(t)
        )
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _episode_sync_thread_finished(self, thread):
        if self._episode_sync_thread is thread:
            self._episode_sync_thread = None
            self._episode_sync_worker = None
            self._episode_sync_work_id = None


    def _start_episode_image_cache(self, work_id, episodes):
        if self._shutdown_event.is_set():
            return
        work_id = int(work_id)
        if work_id in self._episode_image_cache_threads:
            return

        cacheable = [
            dict(episode)
            for episode in (episodes or [])
            if episode.get("episodeNumber") is not None
            and str(episode.get("thumbnail") or "").strip()
            and not Path(str(episode.get("thumbnail"))).is_file()
        ]
        if not cacheable:
            return

        thread = QThread(self)
        worker = EpisodeImageCacheWorker(work_id, cacheable, self._shutdown_event)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(self._episode_image_cache_finished)
        worker.error.connect(self._episode_image_cache_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._episode_image_cache_threads[work_id] = thread
        self._episode_image_cache_workers[work_id] = worker
        thread.start()

    def _episode_image_cache_finished(self, work_id):
        work_id = int(work_id)
        self._episode_image_cache_cleanup(work_id)
        if self._shutdown_event.is_set():
            return

        if self._selected_episode_work_id == work_id:
            self._replace_episode_section()

    def _episode_image_cache_error(self, work_id, error):
        work_id = int(work_id)
        self._episode_image_cache_cleanup(work_id)
        if self._shutdown_event.is_set():
            return
        print(f"TMDB episode image cache failed for work {work_id}: {error}")

        # Some images may have succeeded before one failed. Rebuild the
        # selected season so any newly cached local files appear immediately.
        if self._selected_episode_work_id == work_id:
            self._replace_episode_section()

    def _episode_image_cache_cleanup(self, work_id):
        self._episode_image_cache_threads.pop(int(work_id), None)
        self._episode_image_cache_workers.pop(int(work_id), None)


    def _episode_sync_finished(self, work_id, payload):
        work_id = int(work_id)
        payload = payload or {}
        episodes = payload.get("episodes") or []
        self._episode_sync_errors.pop(work_id, None)
        self._episode_source_status[work_id] = {
            "tmdb": int(payload.get("tmdb_count") or 0),
        }

        tmdb_id = payload.get("tmdb_id")
        tmdb_season_number = payload.get("tmdb_season_number")
        if tmdb_id is not None:
            save_tmdb_mapping(
                work_id,
                tmdb_id,
                tmdb_season_number,
            )
        save_episodes(work_id, episodes)
        self._episode_sync_completed.add(work_id)
        if self._shutdown_event.is_set():
            return
        self._start_episode_image_cache(work_id, episodes)

        if self._selected_episode_work_id == work_id:
            self._replace_episode_section()

    def _episode_sync_error(self, work_id, error):
        work_id = int(work_id)
        self._episode_sync_errors[work_id] = str(error)
        if self._shutdown_event.is_set():
            return

        if self._selected_episode_work_id == work_id:
            content = self.scroll_area.widget()
            root = content.layout() if content is not None else None
            if root is not None:
                for index in range(root.count()):
                    item = root.itemAt(index)
                    widget = item.widget() if item is not None else None
                    if widget is None or not widget.property("_episodes_section"):
                        continue
                    labels = widget.findChildren(QLabel, "detailEpisodeLoadingLabel")
                    for label in labels:
                        label.setText(f"Could not load episode data: {error}")
                        label.setObjectName("detailEpisodeMessage")
                        label.setStyleSheet(muted_label_stylesheet())
                        label.style().unpolish(label)
                        label.style().polish(label)
                        layout = widget.layout()
                        if layout is not None:
                            for child_index in range(layout.count()):
                                child_item = layout.itemAt(child_index)
                                child = child_item.widget() if child_item is not None else None
                                if child is not None and child.objectName() == "detailSkeletonEpisodeStrip":
                                    layout.removeWidget(child)
                                    child.deleteLater()
                                    break
                        break
                    break

    def _replace_episode_section(self):
        content = self.scroll_area.widget()
        if content is None:
            return

        root = content.layout()
        if root is None:
            return

        for index in range(root.count()):
            item = root.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget is None or not widget.property("_episodes_section"):
                continue

            old_frame = widget
            new_frame = self._episodes_section(defer_cards=True)
            new_frame.setProperty("_episodes_section", True)
            root.replaceWidget(old_frame, new_frame)
            old_frame.deleteLater()

            episodes = getattr(new_frame, "_pending_episode_cards", None)
            if episodes:
                token = self._detail_build_token
                QTimer.singleShot(
                    0,
                    lambda token=token, page=content, frame=new_frame, data=episodes:
                        self._populate_episode_cards(token, page, frame, data, 0),
                )
            return

    def _episode_toggled(self, number, checked):
        work_id = self._selected_episode_work_id
        if work_id is None:
            work_id = self._value("id")

        set_episode_watched(work_id, number, checked)

        episodes = get_episodes(work_id)
        watched = sum(1 for ep in episodes if ep["watched"])
        total = len(episodes)

        content = self.scroll_area.widget()
        if content is None or content.layout() is None:
            return

        root = content.layout()
        for index in range(root.count()):
            item = root.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget is None or not widget.property("_episodes_section"):
                continue

            labels = widget.findChildren(QLabel)
            for label in labels:
                if label.text().endswith("watched") or label.text() == "No episode list saved":
                    label.setText(
                        f"{watched} / {total} watched"
                        if total
                        else "No episode list saved"
                    )
                    break
            return

    def _detail_section_frame_stylesheet(self):
        return (
            f"QFrame#charactersSection {{ background:{COLORS['surface']}; border:1px solid {COLORS['frame']}; border-radius:18px; }}"
            f" QFrame#section {{ background:{COLORS['surface']}; border:1px solid {COLORS['frame']}; border-radius:18px; }}"
        )

    @staticmethod
    def _detail_empty_message(title, detail_ids):
        ids = []
        for work_id in detail_ids or []:
            try:
                ids.append(int(work_id))
            except (TypeError, ValueError, OverflowError):
                continue
        if ids and all(work_id < 0 for work_id in ids):
            if title == "Characters":
                return (
                    "No character cast is available from this MangaBaka entry "
                    "or its explicitly linked AniList metadata."
                )
            if title == "Staff":
                return (
                    "No full staff-credit list is available from this MangaBaka entry "
                    "or an explicitly linked AniList record. Available authors and "
                    "artists are shown in MangaBaka metadata."
                )
            if title == "Relations":
                return (
                    "Neither MangaBaka nor explicitly linked AniList metadata has "
                    "related-work links available for this entry."
                )
        return "Nothing stored locally yet."

    def _staff_page_requests(self, detail_ids):
        requests = []
        for local_work_id in detail_ids or []:
            try:
                local_work_id = int(local_work_id)
            except (TypeError, ValueError, OverflowError):
                continue
            if local_work_id == 0 or local_work_id in self._staff_exhausted_ids:
                continue

            # Most local works use their AniList ID as their work ID. A
            # MangaBaka-only work may keep a negative local ID but have an
            # explicitly linked AniList record stored alongside it.
            anilist_id = local_work_id if local_work_id > 0 else None
            if anilist_id is None:
                try:
                    linked_record = get_provider_metadata(
                        local_work_id, "anilist_media_id"
                    )
                    raw_anilist_id = (
                        linked_record.get("id")
                        if isinstance(linked_record, dict) else None
                    )
                    anilist_id = int(raw_anilist_id)
                except (TypeError, ValueError, OverflowError):
                    anilist_id = None
            if anilist_id is None or anilist_id <= 0:
                continue

            try:
                saved_staff_count = len(get_staff(local_work_id))
            except Exception:
                saved_staff_count = 0
            try:
                page_info = get_provider_metadata(
                    local_work_id, "anilist_staff_page_info"
                )
            except Exception:
                page_info = None
            if isinstance(page_info, dict) and page_info.get("hasNextPage") is False:
                self._staff_exhausted_ids.add(local_work_id)
                continue
            if (
                not isinstance(page_info, dict)
                or page_info.get("hasNextPage") is not True
            ):
                # Backward compatibility for databases created before page
                # information was cached alongside the initial credit list.
                if saved_staff_count < 15:
                    continue
                saved_next_page = 2
            else:
                try:
                    saved_next_page = max(
                        2, int(page_info.get("currentPage") or 1) + 1
                    )
                except (TypeError, ValueError, OverflowError):
                    saved_next_page = 2

            # The DB pageInfo is persisted, so use it to resume correctly after
            # an application restart. The in-memory counter can only move this
            # forward, never back to an already-imported page.
            next_page = max(
                saved_next_page,
                self._staff_next_pages.get(local_work_id, saved_next_page),
            )
            requests.append((local_work_id, anilist_id, next_page))
        return requests

    def _staff_section(self, detail_ids, items=None):
        items = list(items if items is not None else get_bundle_staff(detail_ids))
        section_key = tuple(int(work_id) for work_id in (detail_ids or []))
        visible_count = self._staff_visible_counts.setdefault(section_key, 12)

        frame = QFrame()
        frame.setObjectName("section")
        frame.setProperty("_staff_section", True)
        frame.setProperty("_detail_section_ids", list(section_key))
        frame.setStyleSheet(self._detail_section_frame_stylesheet())
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(12)

        header = QLabel("Staff")
        header.setObjectName("detailSectionHeader")
        header.setStyleSheet(
            f"font-size:17px;font-weight:800;color:{COLORS['primary']};"
        )
        layout.addWidget(header)

        container = QWidget()
        flow = StaffFlowLayout(container, h_spacing=8, v_spacing=12)
        if not items:
            empty = QLabel(self._detail_empty_message("Staff", detail_ids))
            empty.setWordWrap(True)
            empty.setStyleSheet(muted_label_stylesheet())
            flow.addWidget(empty)
        else:
            for person in items[:max(0, visible_count)]:
                card = PersonCard(person)
                card.clicked.connect(self.person_selected)
                flow.addWidget(card)
        layout.addWidget(container)

        actions = QHBoxLayout()
        actions.addStretch(1)
        if len(items) > visible_count:
            more_local = QPushButton(
                f"Show 12 more staff ({len(items) - visible_count} remaining)"
            )
            more_local.setObjectName("staffMoreButton")
            more_local.setCursor(Qt.PointingHandCursor)
            more_local.clicked.connect(
                lambda checked=False, ids=list(section_key):
                    self._show_more_staff(ids)
            )
            actions.addWidget(more_local)

        requests = self._staff_page_requests(detail_ids)
        if requests:
            if self._staff_loading:
                text = "Loading staff credits…"
            elif any(
                work_id in self._staff_page_errors
                for work_id, _anilist_id, _page in requests
            ):
                text = "Retry loading staff credits"
            else:
                text = "Load more credits from AniList"
            load_api = QPushButton(text)
            load_api.setObjectName("staffMoreButton")
            load_api.setCursor(Qt.PointingHandCursor)
            load_api.setEnabled(not self._staff_loading)
            load_api.clicked.connect(self._load_more_staff_pages)
            actions.addWidget(load_api)
        if actions.count() > 1:
            layout.addLayout(actions)
        return frame

    def _show_more_staff(self, detail_ids):
        key = tuple(int(work_id) for work_id in (detail_ids or []))
        self._staff_visible_counts[key] = self._staff_visible_counts.get(key, 12) + 12
        self._replace_staff_section()

    def _load_more_staff_pages(self):
        if self._staff_loading or self._shutdown_event.is_set():
            return
        detail_ids = self._detail_work_ids()
        requests = self._staff_page_requests(detail_ids)
        if not requests:
            self._replace_staff_section()
            return

        self._staff_loading = True
        worker = StaffPageWorker(requests, self._shutdown_event)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.pages_loaded.connect(self._staff_pages_loaded)
        worker.pages_loaded.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(
            lambda current_thread=thread, current_worker=worker:
                self.staff_thread_stopped.emit(current_thread, current_worker)
        )
        self._staff_sync_thread = thread
        self._staff_sync_worker = worker
        self._replace_staff_section()
        thread.start()

    def _staff_pages_loaded(self, results):
        for result in results or []:
            try:
                work_id = int(result.get("work_id"))
            except (TypeError, ValueError, OverflowError, AttributeError):
                continue
            if result.get("error"):
                self._staff_page_errors[work_id] = str(result["error"])
                continue
            self._staff_page_errors.pop(work_id, None)
            page_info = result.get("page_info") or {}
            try:
                current_page = int(page_info.get("currentPage") or result.get("page") or 1)
            except (TypeError, ValueError, OverflowError):
                current_page = int(result.get("page") or 1)
            has_next = page_info.get("hasNextPage") is True
            edge_count = int(result.get("edge_count") or 0)
            if not has_next or edge_count == 0 or current_page >= 100:
                self._staff_exhausted_ids.add(work_id)
            else:
                self._staff_next_pages[work_id] = current_page + 1

    def _staff_thread_finished(self, thread, worker):
        if self._staff_sync_thread is thread:
            self._staff_sync_thread = None
            self._staff_sync_worker = None
        self._staff_loading = False
        try:
            thread.deleteLater()
        except RuntimeError:
            pass
        self._replace_staff_section()

    def _replace_staff_section(self):
        contents = [self.scroll_area.widget(), *self._detail_content_cache.values()]
        seen_contents = set()
        for content in contents:
            if content is None or id(content) in seen_contents:
                continue
            seen_contents.add(id(content))
            root = content.layout()
            if root is None:
                continue
            for index in range(root.count()):
                item = root.itemAt(index)
                old_frame = item.widget() if item is not None else None
                if old_frame is None or not old_frame.property("_staff_section"):
                    continue
                ids = old_frame.property("_detail_section_ids") or []
                items = get_bundle_staff(ids)
                new_frame = self._staff_section(ids, items)
                root.replaceWidget(old_frame, new_frame)
                old_frame.deleteLater()
                break

    def _grid_section(self, title, items, cls, signal, columns, empty_message=None):
        frame = QFrame()
        frame.setObjectName("charactersSection" if title == "Characters" else "section")
        frame.setStyleSheet(self._detail_section_frame_stylesheet())
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(20, 18, 20, 20)
        lay.setSpacing(12)

        header = QLabel(title)
        header.setObjectName("detailSectionHeader")
        header.setStyleSheet(
            f"font-size:17px;font-weight:800;color:{COLORS['primary']};"
        )
        lay.addWidget(header)

        if title in {"Staff", "Relations"}:
            container = QWidget()
            flow = StaffFlowLayout(container, h_spacing=8, v_spacing=12)

            if not items:
                empty = QLabel(empty_message or "Nothing stored locally yet.")
                empty.setWordWrap(True)
                empty.setStyleSheet(muted_label_stylesheet())
                flow.addWidget(empty)
            else:
                for item in items:
                    card = cls(item)
                    card.clicked.connect(signal)
                    flow.addWidget(card)

            lay.addWidget(container)
            return frame

        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        if not items:
            empty = QLabel(empty_message or "Nothing stored locally yet.")
            empty.setWordWrap(True)
            empty.setStyleSheet(muted_label_stylesheet())
            grid.addWidget(empty, 0, 0)
        else:
            for index, item in enumerate(items):
                card = cls(item)
                card.clicked.connect(signal)
                if isinstance(card, CharacterCard):
                    card.voice_actor_clicked.connect(self.voice_actor_selected.emit)
                grid.addWidget(card, index // columns, index % columns)

        lay.addWidget(container)
        return frame

    @staticmethod
    def _member_release_date(member):
        """Format a member's stored/AniList start date."""
        if hasattr(member, "get"):
            start_date = member.get("startDate") or {}
            year = start_date.get("year") or member.get("start_year")
            month = start_date.get("month") or member.get("start_month")
            day = start_date.get("day") or member.get("start_day")
        else:
            year = member["start_year"]
            month = member["start_month"] if "start_month" in member.keys() else None
            day = member["start_day"] if "start_day" in member.keys() else None

        if year and month and day:
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        if year:
            return str(year)
        return "Unknown date"

    @staticmethod
    def _member_title(member):
        title = member["title"]
        if isinstance(title, dict):
            return str(
                title.get("english")
                or title.get("romaji")
                or title.get("native")
                or "Untitled"
            )
        return str(title or "Untitled")

    def _value(self, key):
        if hasattr(self.work, "get"): return self.work.get(key)
        try: return self.work[key]
        except (KeyError, IndexError, TypeError): return None

    def _toggle_favorite(self, work_id, favorite, button):
        try:
            try:
                snapshot = dict(self.work)
            except (TypeError, ValueError):
                snapshot = {}
            set_work_favorite(work_id, bool(favorite), snapshot)
        except Exception as error:
            log_exception("favorites.toggle_failed", error, work_id=work_id)
            QMessageBox.warning(
                self,
                "Favorite could not be saved",
                "NekoTrack could not update this title's favorite state.",
            )
            button.setChecked(not bool(favorite))
            return
        button.setText("♥ Favorited" if favorite else "♡ Favorite")
        button.setToolTip(
            "Remove this title from Favorites" if favorite
            else "Save this title independently of Library membership"
        )

    def _refresh_identity_after_edit(self, work_id):
        current_work = self.work
        try:
            numeric_id = int(work_id)
        except (TypeError, ValueError, OverflowError):
            return
        invalidate_display_override(numeric_id)
        self.invalidate_detail_cache([numeric_id])
        current_content = self.scroll_area.takeWidget()
        if current_content is not None:
            current_content.deleteLater()
        self.set_work(current_work)

    def _open_display_identity_editor(self):
        raw_work_id = self._value("id")
        try:
            work_id = int(raw_work_id)
        except (TypeError, ValueError, OverflowError):
            return

        override = get_display_override(work_id)
        dialog = QDialog(self)
        dialog.setWindowTitle("Customize title and cover")
        dialog.setModal(True)
        dialog.setMinimumWidth(440)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)

        title_label = QLabel("Global display title")
        title_label.setObjectName("identityEditorLabel")
        title_input = QLineEdit()
        title_input.setObjectName("customDisplayTitle")
        title_input.setAccessibleName("Global display title")
        title_input.setPlaceholderText("Leave blank to use the provider title")
        title_input.setMaxLength(200)
        title_input.setText(str(override.get("custom_title") or ""))

        cover_label = QLabel("Custom cover artwork")
        cover_label.setObjectName("identityEditorLabel")
        chosen_source = {"path": None}
        existing_cover = override.get("custom_cover_path")
        cover_preview = QLabel(
            Path(str(existing_cover)).name if existing_cover
            else "Using provider artwork"
        )
        cover_preview.setObjectName("identityCoverName")
        cover_preview.setWordWrap(True)
        cover_choice = QCheckBox("Use provider's default cover")
        cover_choice.setObjectName("identityProviderCover")
        cover_choice.setChecked(not bool(existing_cover))

        browse_button = QPushButton("Choose image…")
        browse_button.setObjectName("identityBrowseCover")

        def browse_cover():
            source, _selected_filter = QFileDialog.getOpenFileName(
                dialog,
                "Choose custom cover artwork",
                "",
                "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
            )
            if not source:
                return
            chosen_source["path"] = source
            cover_choice.setChecked(False)
            cover_preview.setText(Path(source).name)

        browse_button.clicked.connect(browse_cover)
        cover_choice.toggled.connect(
            lambda checked: cover_preview.setText(
                "Using provider artwork" if checked
                else Path(str(chosen_source["path"] or existing_cover or "Selected image")).name
            )
        )
        layout.addWidget(title_label)
        layout.addWidget(title_input)
        layout.addWidget(cover_label)
        layout.addWidget(cover_preview)
        layout.addWidget(browse_button, 0, Qt.AlignLeft)
        layout.addWidget(cover_choice)

        actions = QHBoxLayout()
        actions.addStretch(1)
        reset_button = QPushButton("Reset")
        reset_button.setObjectName("identityReset")
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        actions.addWidget(reset_button)
        actions.addWidget(button_box)
        layout.addLayout(actions)

        def persist_override():
            try:
                if cover_choice.isChecked():
                    cover_path = None
                elif chosen_source["path"]:
                    cover_path = copy_custom_cover(chosen_source["path"])
                else:
                    cover_path = existing_cover
                title_value = " ".join(title_input.text().split()).strip() or None
                save_work_display_override(work_id, title_value, cover_path)
                self._refresh_identity_after_edit(work_id)
                dialog.accept()
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                QMessageBox.warning(
                    dialog,
                    "Customization could not be saved",
                    str(error),
                )

        def reset_override():
            try:
                save_work_display_override(work_id, None, None)
                self._refresh_identity_after_edit(work_id)
                dialog.accept()
            except Exception as error:
                log_exception("display_identity.reset_failed", error, work_id=work_id)
                QMessageBox.warning(
                    dialog,
                    "Customization could not be reset",
                    "NekoTrack could not reset this title's display overrides.",
                )

        button_box.accepted.connect(persist_override)
        button_box.rejected.connect(dialog.reject)
        reset_button.clicked.connect(reset_override)

        dialog.setStyleSheet(f"""
            QLabel#identityEditorLabel {{
                color:{COLORS['primary']}; background:transparent; font-size:12px; font-weight:800;
            }}
            QLabel#identityCoverName {{
                color:{COLORS['secondary']}; background:{COLORS['surface_alt']};
                border:1px solid {COLORS['border']}; border-radius:8px; padding:10px;
            }}
            QPushButton#identityBrowseCover, QPushButton#identityReset {{
                background:{COLORS['surface_alt']}; color:{COLORS['primary']};
                border:1px solid {COLORS['border']}; border-radius:8px; padding:8px 10px;
            }}
        """)
        dialog.exec()

    def _title(self):
        members = self._value("_series_members") or []
        is_bundle = len(members) > 1
        try:
            is_bundle = is_bundle or int(self._value("_series_count") or 0) > 1
        except (TypeError, ValueError, OverflowError):
            pass
        if not is_bundle:
            override = get_display_override(self._value("id"))
            custom_title = override.get("custom_title")
            if isinstance(custom_title, str) and custom_title.strip():
                return custom_title.strip()
        title = self._value("title")
        if isinstance(title, dict): return title.get("english") or title.get("romaji") or title.get("native") or "Untitled"
        return title or "Untitled"
