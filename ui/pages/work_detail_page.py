from api import (
    cache_tmdb_episode_image,
    get_media_details,
    get_tmdb_episode_data,
)
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, QUrl, QSize, QPoint, QRect, QThread, QTimer
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QPen, QColor
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget, QWidgetAction
)

from database import (
    add_manual_bundle_link, add_to_library, characters_are_loaded, delete_work_data, get_bundle_characters,
    get_alternate_titles, get_bundle_relations, get_bundle_staff, get_connection, get_episodes,
    get_tmdb_mapping,
    get_work, save_anime, save_characters, save_cover_path, save_episode_thumbnail_path,
    save_episodes, save_staff,
    save_tmdb_mapping, set_episode_watched,
)
from series import get_library_series
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


class EpisodeImageCacheWorker(QObject):
    finished = Signal(int)
    error = Signal(int, str)

    def __init__(self, work_id, episodes):
        super().__init__()
        self.work_id = int(work_id)
        self.episodes = [dict(episode) for episode in (episodes or [])]

    def run(self):
        errors = []
        for episode in self.episodes:
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
    relation_selected = Signal(object)
    bundle_changed = Signal()
    bundle_edit_requested = Signal(object)

    _cover_cache = {}
    _cover_failures = set()

    def __init__(self):
        super().__init__()
        self.work = None
        self._selected_episode_work_id = None
        self._episode_sync_thread = None
        self._episode_sync_worker = None
        self._episode_sync_work_id = None
        self._episode_image_cache_threads = {}
        self._episode_image_cache_workers = {}
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

        back = QPushButton("‹  Back to Library")
        back.setObjectName("back")
        back.clicked.connect(self.back_requested)
        root.addWidget(back, alignment=Qt.AlignLeft)
        root.addWidget(self._hero())

        episode_host = QFrame()
        episode_host.setObjectName("section")
        episode_host.setProperty("_episodes_section", True)
        episode_layout = QVBoxLayout(episode_host)
        episode_layout.setContentsMargins(20, 18, 20, 20)

        if episode_data_ready:
            ready_episode_frame = self._episodes_section()
            ready_episode_frame.setProperty("_episodes_section", True)
            episode_host.deleteLater()
            episode_host = ready_episode_frame
        else:
            episode_layout.addWidget(QLabel("Loading episode data…"))
        root.addWidget(episode_host)

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
            loading_details = QLabel("Loading details…")
            loading_details.setStyleSheet(muted_label_stylesheet())
            detail_layout.addWidget(loading_details)
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
            QToolButton#detailMenu {{ background:transparent; color:{COLORS['primary']}; border:2px solid transparent; border-radius:{get('corner_radius') + 2}px; font-size:30px; font-weight:900; padding:0; }}
            QToolButton#detailMenu:hover {{ background:{COLORS['surface_hover']}; color:{COLORS['accent_hover']}; border-color:{COLORS['accent']}; }}
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
                "detailHeroCover": f"color:{COLORS['muted']};background:{COLORS['background_alt']};border-radius:14px;",
                "detailHeroTitle": f"font-size:34px;font-weight:850;color:{COLORS['primary']};letter-spacing:-1px;",
                "detailHeroNativeTitle": muted_label_stylesheet(),
                "detailHeroMetadata": f"color:{COLORS['secondary']};font-size:13px;",
                "detailHeroScore": f"color:{COLORS['accent']};font-size:18px;font-weight:800;",
                "detailHeroDescription": f"color:{COLORS['secondary']};font-size:14px;",
                "detailSectionHeader": f"font-size:17px;font-weight:800;color:{COLORS['primary']};",
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
            )
        )
        layout.addWidget(
            self._grid_section(
                "Staff",
                get_bundle_staff(detail_ids),
                PersonCard,
                self.person_selected,
                6,
            )
        )
        layout.addWidget(
            self._grid_section(
                "Relations",
                get_bundle_relations(detail_ids),
                RelationCard,
                self.relation_selected,
                6,
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

        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        loading = QLabel("Loading characters…")
        loading.setStyleSheet(muted_label_stylesheet())
        layout.addWidget(loading)

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

        loading.deleteLater()
        layout.addWidget(
            self._grid_section(
                title,
                items,
                card_class,
                signal,
                columns,
            )
        )

        next_specs = {
            "Characters": (
                "Staff",
                get_bundle_staff,
                PersonCard,
                self.person_selected,
                6,
            ),
            "Staff": (
                "Relations",
                get_bundle_relations,
                RelationCard,
                self.relation_selected,
                6,
            ),
        }
        spec = next_specs.get(title)
        if spec is None:
            return

        next_title, next_getter, next_class, next_signal, next_columns = spec
        next_loading = QLabel(f"Loading {next_title.lower()}…")
        next_loading.setStyleSheet(muted_label_stylesheet())
        layout.addWidget(next_loading)

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

    def _hero(self):
        hero = QFrame(); hero.setObjectName("hero")
        box = QHBoxLayout(hero); box.setContentsMargins(24, 24, 28, 24); box.setSpacing(30)
        cover = QLabel(); cover.setObjectName("detailHeroCover"); cover.setFixedSize(235, 335); cover.setAlignment(Qt.AlignCenter)
        cover.setStyleSheet(f"background:{COLORS['background_alt']}; border-radius:14px;")
        path = self._value("cover_path")
        if path:
            pix = QPixmap(str(path))
            if not pix.isNull(): cover.setPixmap(self._cropped_cover(pix, cover.size(), 14))
        if cover.pixmap() is None or cover.pixmap().isNull():
            cover.setText("NO COVER")
            cover.setStyleSheet(f"color:{COLORS['muted']}; background:{COLORS['background_alt']}; border-radius:14px;")
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
        info.addLayout(title_row)
        alt = self._value("native") or self._value("title_native") or ""
        if alt:
            native = QLabel(str(alt)); native.setObjectName("detailHeroNativeTitle"); native.setStyleSheet(muted_label_stylesheet()); info.addWidget(native)
        meta = "  ·  ".join(str(x) for x in [self._value("format"), self._value("start_year"), f"{self._value('episodes')} eps" if self._value("episodes") else None, f"{self._value('chapters')} ch" if self._value("chapters") else None] if x)
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
        if not work_id or not cover_url: return
        cover_url = str(cover_url)
        cached = self._cover_cache.get(cover_url)
        if cached is not None and not cached.isNull():
            label.setPixmap(self._cropped_cover(cached, label.size(), 14)); return
        if cover_url in self._cover_failures: return
        self._cover_reply = self._cover_manager.get(QNetworkRequest(QUrl(cover_url)))
        self._cover_reply.finished.connect(lambda: self._remote_cover_finished(label, work_id, cover_url))

    def _remote_cover_finished(self, label, work_id, cover_url):
        reply = self._cover_reply; self._cover_reply = None
        if reply is not None and reply.error() == reply.NetworkError.NoError:
            pix = QPixmap()
            if pix.loadFromData(reply.readAll()):
                self._cover_cache[cover_url] = pix
                label.setText(""); label.setPixmap(self._cropped_cover(pix, label.size(), 14))
                try:
                    IMAGE_DIRECTORY.mkdir(parents=True, exist_ok=True)
                    path = IMAGE_DIRECTORY / f"{work_id}.jpg"
                    if pix.save(str(path), "JPG", 85): save_cover_path(work_id, str(path))
                except Exception:
                    pass
            else: self._cover_failures.add(cover_url)
        else: self._cover_failures.add(cover_url)
        if reply is not None: reply.deleteLater()

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
            save_characters(work_id, (details.get("characters") or {}).get("edges"))
            save_staff(work_id, (details.get("staff") or {}).get("edges"))
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

    def _episodes_section(self, defer_cards=False):
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
            message = (
                f"Could not load episode data: {sync_error}"
                if sync_error
                else (
                    "Loading episode data…"
                    if selected_work is not None
                    and int(selected_work["episodes"] or 0) > 0
                    else "No episode data is available for this season."
                )
            )
            x = QLabel(message)
            x.setStyleSheet(muted_label_stylesheet())
            x.setWordWrap(True)
            lay.addWidget(x)
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
        worker = EpisodeImageCacheWorker(work_id, cacheable)
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

        if self._selected_episode_work_id == work_id:
            self._replace_episode_section()

    def _episode_image_cache_error(self, work_id, error):
        work_id = int(work_id)
        self._episode_image_cache_cleanup(work_id)
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
        self._start_episode_image_cache(work_id, episodes)

        if self._selected_episode_work_id == work_id:
            self._replace_episode_section()

    def _episode_sync_error(self, work_id, error):
        work_id = int(work_id)
        self._episode_sync_errors[work_id] = str(error)

        if self._selected_episode_work_id == work_id:
            content = self.scroll_area.widget()
            root = content.layout() if content is not None else None
            if root is not None:
                for index in range(root.count()):
                    item = root.itemAt(index)
                    widget = item.widget() if item is not None else None
                    if widget is None or not widget.property("_episodes_section"):
                        continue
                    labels = widget.findChildren(QLabel)
                    for label in labels:
                        if label.text() == "Loading episode data…":
                            label.setText(f"Could not load episode data: {error}")
                            label.setStyleSheet(muted_label_stylesheet())
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

    def _grid_section(self, title, items, cls, signal, columns):
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
                empty = QLabel("Nothing stored locally yet.")
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
            x = QLabel("Nothing stored locally yet.")
            x.setStyleSheet(muted_label_stylesheet())
            grid.addWidget(x, 0, 0)
        else:
            for i, item in enumerate(items):
                card = cls(item)
                card.clicked.connect(signal)
                grid.addWidget(card, i // columns, i % columns)

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

    def _title(self):
        title = self._value("title")
        if isinstance(title, dict): return title.get("english") or title.get("romaji") or title.get("native") or "Untitled"
        return title or "Untitled"
