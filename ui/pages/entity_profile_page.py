from PySide6.QtCore import Qt, Signal, QUrl, QObject, QRunnable, QThreadPool, QRectF, QPoint, QRect, QSize
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QPen, QColor
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from api import get_entity_profile
from ui.theme import COLORS, muted_label_stylesheet
from ui.widgets.person_card import PersonCard
from ui.widgets.work_card import WorkCard


def _crop_pixmap_to_size(pixmap, size):
    """Fill a portrait frame and crop overflow instead of letterboxing artwork."""
    if pixmap is None or pixmap.isNull() or size.width() <= 0 or size.height() <= 0:
        return QPixmap()
    scaled = pixmap.scaled(
        size,
        Qt.KeepAspectRatioByExpanding,
        Qt.SmoothTransformation,
    )
    x = max(0, (scaled.width() - size.width()) // 2)
    y = max(0, (scaled.height() - size.height()) // 2)
    return scaled.copy(x, y, size.width(), size.height())


class _ProfileLoadSignals(QObject):
    finished = Signal(int, str, int, object, str)


class _ProfileLoadWorker(QRunnable):
    def __init__(self, token, fetch_kind, entity_id):
        super().__init__()
        self.token = int(token)
        self.fetch_kind = str(fetch_kind)
        self.entity_id = int(entity_id)
        self.signals = _ProfileLoadSignals()

    def run(self):
        try:
            profile = get_entity_profile(self.fetch_kind, self.entity_id)
            self.signals.finished.emit(
                self.token, self.fetch_kind, self.entity_id, profile, ""
            )
        except Exception as error:
            self.signals.finished.emit(
                self.token, self.fetch_kind, self.entity_id, None,
                f"{type(error).__name__}: {error}",
            )


class RoundedArtworkLabel(QLabel):
    """Artwork clipped inside a rounded frame, not merely given a rounded border."""

    def __init__(self, width, height, radius=10, parent=None):
        super().__init__(parent)
        self._radius = max(1, int(radius))
        self.setFixedSize(width, height)
        self.setAlignment(Qt.AlignCenter)
        self.setScaledContents(False)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background:transparent;border:none;padding:0;")

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        outer = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        outer_path = QPainterPath()
        outer_path.addRoundedRect(outer, self._radius, self._radius)
        painter.fillPath(outer_path, QColor(COLORS["background_alt"]))

        pixmap = self.pixmap()
        inner = outer.toRect().adjusted(2, 2, -2, -2)
        if pixmap is not None and not pixmap.isNull() and inner.width() > 0 and inner.height() > 0:
            cropped = _crop_pixmap_to_size(pixmap, inner.size())
            if not cropped.isNull():
                image_rect = QRectF(inner)
                image_path = QPainterPath()
                image_path.addRoundedRect(
                    image_rect, max(1, self._radius - 2), max(1, self._radius - 2)
                )
                painter.save()
                painter.setClipPath(image_path)
                painter.drawPixmap(inner, cropped)
                painter.restore()

        painter.setPen(QPen(QColor(COLORS["frame"]), 2.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(outer_path)
        painter.end()


class ClickableCharacterCredit(QFrame):
    """Clickable character portrait displayed beside its voice-acting work."""

    clicked = Signal(object)

    def __init__(self, character, parent=None):
        super().__init__(parent)
        character = character if isinstance(character, dict) else {}
        raw_name = character.get("name")
        if isinstance(raw_name, dict):
            name = raw_name.get("full") or raw_name.get("native") or "Unknown character"
        else:
            name = raw_name or "Unknown character"
        image = character.get("image")
        image_url = image.get("large") if isinstance(image, dict) else None
        try:
            character_id = int(character.get("id") or 0)
        except (TypeError, ValueError, OverflowError):
            character_id = 0
        self.character = {
            "id": character_id,
            "character_name": str(name),
            "character_image_url": image_url,
        }
        self.setFixedWidth(84)
        self.setMinimumHeight(112)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(str(name))
        self.setObjectName("creditCharacter")
        self.setStyleSheet(
            f"QFrame#creditCharacter {{ background:{COLORS['surface']};"
            f"border:1px solid {COLORS['frame']};border-radius:9px; }}"
            f"QFrame#creditCharacter:hover {{ border-color:{COLORS['accent']}; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)
        self.image = RoundedArtworkLabel(54, 72, 7)
        self.image.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.image, 0, Qt.AlignHCenter)
        self.name_label = QLabel(str(name))
        self.name_label.setWordWrap(True)
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setStyleSheet(
            f"background:transparent;border:none;color:{COLORS['primary']};font-size:10px;"
        )
        self.name_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.name_label)

        self._network = QNetworkAccessManager(self)
        self._reply = (
            self._network.get(QNetworkRequest(QUrl(str(image_url))))
            if image_url else None
        )
        if self._reply is not None:
            self._reply.finished.connect(self._image_finished)

    def _image_finished(self):
        reply = self._reply
        self._reply = None
        if reply is not None and reply.error() == QNetworkReply.NetworkError.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()):
                self.image.setPixmap(pixmap)
        if reply is not None:
            reply.deleteLater()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.character["id"] > 0:
            event.accept()
            self.clicked.emit(dict(self.character))
            return
        super().mousePressEvent(event)


class MediaCreditCard(QFrame):
    """Fully clickable work card; voice-acting cards expose clickable characters too."""

    work_selected = Signal(object)
    character_selected = Signal(object)

    def __init__(self, edge, credit_kind, parent=None):
        super().__init__(parent)
        edge = edge if isinstance(edge, dict) else {}
        node = edge.get("node") if isinstance(edge.get("node"), dict) else {}
        self.credit_kind = str(credit_kind or "")
        try:
            self.media_id = int(node.get("id") or 0)
        except (TypeError, ValueError, OverflowError):
            self.media_id = 0
        self.media_record = dict(node)
        if self.media_id > 0:
            self.media_record["id"] = self.media_id
        media_type = str(node.get("type") or "ANIME")
        title_data = node.get("title") if isinstance(node.get("title"), dict) else {}
        title = (
            title_data.get("english") or title_data.get("romaji")
            or title_data.get("native") or "Untitled work"
        )
        self.setObjectName("mediaCreditCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"QFrame#mediaCreditCard {{ background:{COLORS['surface']};"
            f"border:1px solid {COLORS['frame']};border-radius:12px; }}"
            f"QFrame#mediaCreditCard:hover {{ border-color:{COLORS['accent']}; }}"
        )
        if self.credit_kind == "voice_actor":
            self.setFixedSize(300, 150)
        else:
            self.setMinimumWidth(260)
            self.setMaximumWidth(420)
            self.setMinimumHeight(125)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 10, 10, 10)
        row.setSpacing(12)
        self.cover = RoundedArtworkLabel(72, 102, 8)
        self.cover.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row.addWidget(self.cover, 0, Qt.AlignVCenter)

        cover_data = node.get("coverImage")
        cover_url = cover_data.get("large") if isinstance(cover_data, dict) else None
        if cover_url:
            self._network = QNetworkAccessManager(self)
            self._reply = self._network.get(QNetworkRequest(QUrl(str(cover_url))))
            self._reply.finished.connect(self._image_finished)
        else:
            self._reply = None

        text_column = QVBoxLayout()
        title_label = QLabel(str(title))
        title_label.setObjectName("mediaCreditTitle")
        title_label.setWordWrap(True)
        if self.credit_kind == "voice_actor":
            title_label.setMaximumHeight(68)
        title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        title_label.setStyleSheet(
            f"background:transparent;border:none;color:{COLORS['primary']};"
            "font-weight:750;font-size:13px;"
        )
        text_column.addWidget(title_label)

        year = None
        start = node.get("startDate")
        if isinstance(start, dict):
            year = start.get("year")
        format_text = str(node.get("format") or media_type).replace("_", " ").title()
        metadata = QLabel(" · ".join(str(item) for item in (format_text, year) if item))
        metadata.setObjectName("mediaCreditMetadata")
        metadata.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        metadata.setStyleSheet(muted_label_stylesheet())
        if self.credit_kind != "voice_actor":
            text_column.addWidget(metadata)

        if self.credit_kind in {"character", "voice_actor"}:
            credit = edge.get("characterRole")
        else:
            credit = edge.get("staffRole") or edge.get("role")
        if credit:
            role = QLabel(str(credit))
            role.setObjectName("mediaCreditRole")
            role.setWordWrap(True)
            role.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            role.setStyleSheet(
                f"color:{COLORS['accent']};font-size:11px;font-weight:750;"
                "background:transparent;border:none;"
            )
            text_column.addWidget(role)
        text_column.addStretch(1)
        row.addLayout(text_column, 1)

        if self.credit_kind == "voice_actor":
            characters = edge.get("characters")
            characters = characters if isinstance(characters, list) else []
            valid_characters = []
            for character in characters:
                if not isinstance(character, dict):
                    continue
                try:
                    character_id = int(character.get("id") or 0)
                except (TypeError, ValueError, OverflowError):
                    continue
                if character_id > 0:
                    valid_characters.append(character)
            if valid_characters:
                cast_row = QHBoxLayout()
                cast_row.setContentsMargins(0, 0, 0, 0)
                cast_row.setSpacing(6)
                visible_characters = valid_characters[:4]
                self.character_cards = []
                for character in visible_characters:
                    character_card = ClickableCharacterCredit(character)
                    character_card.clicked.connect(self.character_selected.emit)
                    cast_row.addWidget(character_card, 0, Qt.AlignVCenter)
                    self.character_cards.append(character_card)
                row.addLayout(cast_row, 0)
            else:
                no_cast = QLabel("Character unavailable")
                no_cast.setWordWrap(True)
                no_cast.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                no_cast.setStyleSheet(muted_label_stylesheet())
                row.addWidget(no_cast, 0, Qt.AlignVCenter)

    def _image_finished(self):
        reply = self._reply
        self._reply = None
        if reply is not None and reply.error() == QNetworkReply.NetworkError.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()):
                self.cover.setPixmap(pixmap)
        if reply is not None:
            reply.deleteLater()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.media_id > 0:
            event.accept()
            self.work_selected.emit(dict(self.media_record))
            return
        super().mousePressEvent(event)


class ProfileFlowLayout(QLayout):
    """Wrap fixed-width profile credit cards into tidy poster rows."""

    def __init__(self, parent=None, h_spacing=10, v_spacing=14):
        super().__init__(parent)
        self._items = []
        self._h_spacing = int(h_spacing)
        self._v_spacing = int(v_spacing)
        self.setContentsMargins(0, 0, 0, 0)

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
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(
            margins.left() + margins.right(),
            margins.top() + margins.bottom(),
        )

    def _do_layout(self, rect, test_only):
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        x = effective.x()
        y = effective.y()
        row_height = 0
        used_any = False

        for item in self._items:
            size = item.sizeHint()
            if size.width() <= 0:
                continue
            if used_any and x + size.width() > effective.right() + 1:
                x = effective.x()
                y += row_height + self._v_spacing
                row_height = 0
                used_any = False
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), size))
            x += size.width() + self._h_spacing
            row_height = max(row_height, size.height())
            used_any = True

        if not used_any:
            return margins.top() + margins.bottom()
        return y + row_height - rect.y() + margins.bottom()


class ProfileWorkCreditCard(WorkCard):
    """Compact poster-style work card with a short, inspectable staff-role label."""

    def __init__(self, edge, parent=None):
        edge = edge if isinstance(edge, dict) else {}
        node = edge.get("node") if isinstance(edge.get("node"), dict) else {}
        work = dict(node)
        super().__init__(
            work,
            mode="search",
            show_add_button=False,
            parent=parent,
        )

        raw_role = edge.get("staffRole") or edge.get("role") or ""
        full_role = " ".join(str(raw_role).split())
        if not full_role:
            return

        role = QLabel(full_role)
        role.setObjectName("profileCreditRole")
        role.setWordWrap(True)
        role.setFixedHeight(30)
        role.setToolTip(full_role)
        role.setStyleSheet(
            f"background:transparent;border:none;color:{COLORS['muted']};"
            "font-size:10px;"
        )
        root = self.layout()
        root.insertWidget(max(0, root.count() - 1), role)
        self.setFixedHeight(self.height() + role.height() + root.spacing())


class EntityProfilePage(QWidget):
    """NekoTrack character and voice-actor profiles with internal work navigation."""

    back_requested = Signal()
    voice_actor_selected = Signal(object)
    character_selected = Signal(object)
    work_selected = Signal(object)

    def __init__(self):
        super().__init__()
        self._network_manager = QNetworkAccessManager(self)
        self._image_reply = None
        self._image_label = None
        self._request_token = 0
        self._workers = {}
        self._profile_cache = {}
        self.current_type = "character"
        self.current_record = {}
        self.source_work = None
        self.voice_actors = []
        self._remote_data = None
        self._remote_error = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        self.back_button = QPushButton("← Back")
        self.back_button.setCursor(Qt.PointingHandCursor)
        self.back_button.clicked.connect(self.back_requested.emit)
        header.addWidget(self.back_button)
        header.addStretch(1)
        self.page_status = QLabel("")
        self.page_status.setStyleSheet(muted_label_stylesheet())
        header.addWidget(self.page_status)
        root.addLayout(header)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(14)
        self.scroll_area.setWidget(self.content)
        root.addWidget(self.scroll_area, 1)

        self.refresh_theme()
        self.set_profile("character", {})

    def refresh_theme(self):
        self.setStyleSheet(
            f"""
            QPushButton {{
                color:{COLORS['primary']};
                background:{COLORS['surface']};
                border:1px solid {COLORS['border']};
                border-radius:10px;
                padding:9px 14px;
                font-weight:750;
            }}
            QPushButton:hover {{
                background:{COLORS['surface_hover']};
                border-color:{COLORS['accent']};
            }}
            QPushButton:disabled {{
                color:{COLORS['muted']};
                background:{COLORS['background_alt']};
            }}
            QFrame#profileHeader {{
                background:{COLORS['surface']};
                border:1px solid {COLORS['frame']};
                border-radius:18px;
            }}
            QFrame#profileSection {{
                background:{COLORS['surface']};
                border:1px solid {COLORS['frame']};
                border-radius:16px;
            }}
            QLabel#profileName {{
                color:{COLORS['primary']};
                font-size:30px;
                font-weight:900;
            }}
            QLabel#profileKind {{
                color:{COLORS['accent']};
                font-size:11px;
                font-weight:900;
                letter-spacing:1px;
            }}
            QLabel#profileFacts {{
                color:{COLORS['secondary']};
                font-size:13px;
            }}
            QLabel#profileSectionTitle {{
                color:{COLORS['primary']};
                font-size:17px;
                font-weight:850;
            }}
            QLabel#profileImage {{
                background:{COLORS['background_alt']};
                border:1px solid {COLORS['frame']};
                border-radius:14px;
            }}
            QLabel#profileInlineTitle {{
                color:{COLORS['accent']};
                font-size:10px;
                font-weight:900;
                letter-spacing:1px;
                background:transparent;
                border:none;
            }}
            QLabel#profileDescription {{
                color:{COLORS['secondary']};
                font-size:12px;
                background:transparent;
                border:none;
            }}
            """
        )
        for widget in self.findChildren(QWidget):
            updater = getattr(widget, "refresh_theme", None)
            if callable(updater):
                updater()

    @staticmethod
    def _value(item, key, fallback=None):
        if hasattr(item, "get"):
            try:
                value = item.get(key, fallback)
            except TypeError:
                value = item.get(key)
            return fallback if value is None else value
        try:
            value = item[key]
        except (KeyError, IndexError, TypeError):
            return fallback
        return fallback if value is None else value

    @staticmethod
    def _work_title(work):
        title = EntityProfilePage._value(work, "custom_title")
        if title:
            return str(title)
        title = EntityProfilePage._value(work, "title")
        if isinstance(title, dict):
            return str(
                title.get("english") or title.get("romaji")
                or title.get("native") or "Current work"
            )
        return str(title or EntityProfilePage._value(work, "english_title", "Current work"))

    @staticmethod
    def _name_from(value, fallback=""):
        if isinstance(value, dict):
            return str(value.get("full") or value.get("english") or value.get("romaji") or fallback)
        return str(value or fallback)

    @staticmethod
    def _image_url(value):
        if isinstance(value, dict):
            return value.get("large")
        return value

    @staticmethod
    def _format_date(value):
        if not isinstance(value, dict):
            return ""
        parts = [value.get(key) for key in ("year", "month", "day")]
        if not parts[0]:
            return ""
        try:
            year = int(parts[0])
            if parts[1] and parts[2]:
                return f"{year:04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
            if parts[1]:
                return f"{year:04d}-{int(parts[1]):02d}"
            return str(year)
        except (TypeError, ValueError, OverflowError):
            return str(parts[0])

    def profile_state(self):
        return {
            "entity_type": self.current_type,
            "record": dict(self.current_record),
            "source_work": self.source_work,
            "voice_actors": [dict(actor) for actor in self.voice_actors],
        }

    def _clear_content(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                self.content_layout.removeWidget(widget)
                widget.deleteLater()

    def set_profile(self, entity_type, record, source_work=None, voice_actors=None):
        raw_kind = str(entity_type or "").strip().lower()
        if raw_kind in {"voice_actor", "voice actor"}:
            normalized_kind = "voice_actor"
        elif raw_kind in {"staff", "person", "people"}:
            normalized_kind = "staff"
        else:
            normalized_kind = "character"

        self._request_token += 1
        token = self._request_token
        if self._image_reply is not None:
            try:
                self._image_reply.abort()
            except RuntimeError:
                pass
            self._image_reply = None

        self.current_type = normalized_kind
        try:
            self.current_record = dict(record or {})
        except (TypeError, ValueError):
            self.current_record = {}
        self.source_work = source_work
        saved_voices = voice_actors
        if saved_voices is None:
            saved_voices = self.current_record.get("voice_actors", [])
        self.voice_actors = [
            dict(actor) for actor in (saved_voices or [])
            if isinstance(actor, dict) or hasattr(actor, "keys")
        ]
        self._remote_data = None
        self._remote_error = ""
        self.page_status.setText("")
        self._render_profile()
        self._start_profile_load(token)

    def _start_profile_load(self, token):
        record = self.current_record
        raw_id = (
            self._value(record, "id")
            if self.current_type == "character"
            else self._value(record, "person_id", self._value(record, "id"))
        )
        try:
            entity_id = int(raw_id)
        except (TypeError, ValueError, OverflowError):
            return
        if entity_id <= 0:
            return
        fetch_kind = "Character" if self.current_type == "character" else "Staff"
        cached_profile = self._profile_cache.get((fetch_kind, entity_id))
        if isinstance(cached_profile, dict):
            self._remote_data = cached_profile
            self._remote_error = ""
            self.page_status.setText("Profile cached")
            self._render_profile()
            return
        self.page_status.setText("Loading profile details…")
        worker = _ProfileLoadWorker(token, fetch_kind, entity_id)
        self._workers[token] = worker
        worker.signals.finished.connect(self._profile_loaded)
        QThreadPool.globalInstance().start(worker)

    def _profile_loaded(self, token, fetch_kind, entity_id, profile, error):
        self._workers.pop(token, None)
        if token != self._request_token:
            return
        expected_kind = "Character" if self.current_type == "character" else "Staff"
        if fetch_kind != expected_kind:
            return
        current_id = (
            self._value(self.current_record, "id")
            if self.current_type == "character"
            else self._value(
                self.current_record, "person_id",
                self._value(self.current_record, "id"),
            )
        )
        try:
            current_id = int(current_id)
        except (TypeError, ValueError, OverflowError):
            return
        if current_id != entity_id:
            return

        if isinstance(profile, dict):
            self._remote_data = profile
            self._profile_cache[(fetch_kind, entity_id)] = profile
            self._remote_error = ""
            self.page_status.setText("Profile loaded")
        else:
            self._remote_error = str(error or "Profile details could not be loaded.")
            self.page_status.setText("Showing saved information")
        self._render_profile()

    def _render_profile(self):
        # Profile data and remote artwork can finish in either order. Cancel the
        # previous portrait request before replacing its target widget.
        if self._image_reply is not None:
            try:
                self._image_reply.abort()
            except RuntimeError:
                pass
            self._image_reply = None
        self._clear_content()
        record = self.current_record
        remote = self._remote_data if isinstance(self._remote_data, dict) else {}
        is_character = self.current_type == "character"
        is_voice_actor = self.current_type == "voice_actor"
        local_name_key = "character_name" if is_character else "name"
        name = (
            self._name_from(remote.get("name"))
            or self._name_from(self._value(record, local_name_key), "Unknown profile")
        )
        kind_label = (
            "CHARACTER PROFILE" if is_character
            else "VOICE ACTOR PROFILE" if is_voice_actor
            else "STAFF PROFILE"
        )
        image_path = (
            self._value(record, "character_image_path") if is_character
            else self._value(record, "image_path")
        )
        image_url = self._image_url(remote.get("image")) or (
            self._value(record, "character_image_url") if is_character
            else self._value(record, "image_url")
        )
        header = QFrame()
        header.setObjectName("profileHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(18, 18, 18, 18)
        row.setSpacing(20)

        artwork = RoundedArtworkLabel(180, 240, 14)
        artwork.setObjectName("profileImage")
        self._image_label = artwork
        pixmap = QPixmap(str(image_path)) if image_path else QPixmap()
        if not pixmap.isNull():
            self._set_artwork(pixmap)
        elif image_url:
            self._load_artwork(image_url)
        row.addWidget(artwork, 0, Qt.AlignTop)

        facts_column = QVBoxLayout()
        kind = QLabel(kind_label)
        kind.setObjectName("profileKind")
        facts_column.addWidget(kind)

        title = QLabel(name)
        title.setObjectName("profileName")
        title.setWordWrap(True)
        facts_column.addWidget(title)

        if is_character:
            role = str(self._value(record, "character_role", "") or "").replace("_", " ").title()
            if role:
                facts_column.addWidget(self._fact("Role in this bundle", role))
        else:
            local_roles = str(self._value(record, "role", "") or "")
            occupations = remote.get("primaryOccupations")
            if isinstance(occupations, list) and occupations:
                facts_column.addWidget(self._fact("Occupation", " · ".join(str(x) for x in occupations if x)))
            elif local_roles:
                facts_column.addWidget(self._fact("Credits in this bundle", local_roles.replace("\n", " · ")))
            language = remote.get("languageV2")
            if language:
                facts_column.addWidget(self._fact("Language", language))

        gender = str(remote.get("gender") or "").strip()
        age = str(remote.get("age") or "").strip()
        birth = self._format_date(remote.get("dateOfBirth"))
        blood_type = str(remote.get("bloodType") or "").strip()
        hometown = str(remote.get("homeTown") or "").strip()
        years_active = remote.get("yearsActive")
        facts = []
        for label, value in (
            ("Gender", gender), ("Age", age), ("Born", birth),
            ("Blood type", blood_type), ("Hometown", hometown),
        ):
            if value and value != "None":
                facts.append(f"{label}: {value}")
        if isinstance(years_active, list) and years_active:
            active_text = "–".join(str(item) for item in years_active if item is not None)
            if active_text:
                facts.append(f"Active: {active_text}")
        favourites = remote.get("favourites")
        if isinstance(favourites, int) and favourites > 0:
            facts.append(f"{favourites:,} favourites")
        for fact in facts:
            facts_column.addWidget(self._fact("", fact))

        description = str(
            remote.get("description")
            or self._value(record, "description", "")
            or ""
        ).strip()
        if description:
            about_title = QLabel("ABOUT")
            about_title.setObjectName("profileInlineTitle")
            facts_column.addWidget(about_title)
            description_label = QLabel(description)
            description_label.setObjectName("profileDescription")
            description_label.setWordWrap(True)
            description_label.setTextFormat(Qt.PlainText)
            description_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            facts_column.addWidget(description_label)
        elif self._remote_error:
            note = QLabel(
                "Biography unavailable. Showing the saved profile details."
            )
            note.setWordWrap(True)
            note.setStyleSheet(muted_label_stylesheet())
            facts_column.addWidget(note)

        if self.source_work is not None:
            facts_column.addWidget(self._fact("Opened from", self._work_title(self.source_work)))
        facts_column.addStretch(1)
        row.addLayout(facts_column, 1)
        self.content_layout.addWidget(header)

        if is_character:
            self._render_voice_actors()
            connection = remote.get("media")
            self._render_media_credits("Appears in", connection, "character")
        elif is_voice_actor:
            self._render_voice_acting_roles(remote.get("characterMedia"), remote)
        else:
            self._render_media_credits(
                "Staff credits", remote.get("staffMedia"), "staff"
            )

        if self._remote_error:
            error_row = QHBoxLayout()
            error_note = QLabel("Profile detail lookup failed; showing cached data.")
            error_note.setWordWrap(True)
            error_note.setStyleSheet(muted_label_stylesheet())
            error_row.addWidget(error_note, 1)
            retry = QPushButton("Retry")
            retry.setCursor(Qt.PointingHandCursor)
            retry.clicked.connect(
                lambda checked=False, token=self._request_token:
                    self._start_profile_load(token)
            )
            error_row.addWidget(retry)
            self.content_layout.addLayout(error_row)

        self.content_layout.addStretch(1)
        self.scroll_area.verticalScrollBar().setValue(0)

    def _render_voice_actors(self):
        section, body = self._section("Voice actors")
        if not self.voice_actors:
            empty = QLabel(
                "No voice actors are saved for this character yet. Credits are specific "
                "to each adaptation and will appear here as NekoTrack refreshes its cast data."
            )
            empty.setWordWrap(True)
            empty.setStyleSheet(muted_label_stylesheet())
            body.addWidget(empty)
        else:
            grid_host = QWidget()
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(12)
            ordered = sorted(
                self.voice_actors,
                key=lambda actor: (
                    0 if str(actor.get("language") or "").strip().lower()
                    in {"japanese", "ja", "jpn"} else 1,
                    str(actor.get("language") or ""),
                    str(actor.get("name") or ""),
                ),
            )
            for index, actor in enumerate(ordered):
                person = dict(actor)
                credits = [
                    credit for credit in (person.get("credits") or [])
                    if isinstance(credit, dict)
                ]
                languages = person.get("languages")
                language_labels = []
                if isinstance(languages, (list, tuple)):
                    for language in languages:
                        label = str(language or "").strip()
                        if label and label not in language_labels:
                            language_labels.append(label)
                if not language_labels:
                    for credit in credits:
                        label = str(credit.get("language") or "").strip()
                        if label and label not in language_labels:
                            language_labels.append(label)
                if not language_labels and person.get("language"):
                    language_labels = [str(person["language"]).strip()]

                credit_tooltip = []
                for credit in credits:
                    work_title = str(credit.get("work_title") or "").strip()
                    language = str(credit.get("language") or "").strip()
                    line = " · ".join(value for value in (language, work_title) if value)
                    if line and line not in credit_tooltip:
                        credit_tooltip.append(line)

                person["role"] = " · ".join(language_labels) or "Voice actor"
                card = PersonCard(person, portrait_size=(90, 120))
                if credit_tooltip:
                    card.setToolTip("\n".join(credit_tooltip))
                card.clicked.connect(self.voice_actor_selected.emit)
                grid.addWidget(card, index // 5, index % 5)
            body.addWidget(grid_host)
        self.content_layout.addWidget(section)

    def _render_voice_acting_roles(self, connection, remote):
        """Show work on the left and each credited character on the right."""
        del remote
        section, body = self._section("Voice acting roles")
        edges = connection.get("edges") if isinstance(connection, dict) else None
        roles_by_pair = {}
        role_priority = {"MAIN": 0, "SUPPORTING": 1, "BACKGROUND": 2}

        if isinstance(edges, list):
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                node = edge.get("node")
                node = node if isinstance(node, dict) else {}
                try:
                    work_id = int(node.get("id") or 0)
                except (TypeError, ValueError, OverflowError):
                    work_id = 0
                characters = edge.get("characters")
                if not isinstance(characters, list):
                    continue
                raw_role = str(edge.get("characterRole") or "").strip().upper()
                for character in characters:
                    if not isinstance(character, dict):
                        continue
                    try:
                        character_id = int(character.get("id") or 0)
                    except (TypeError, ValueError, OverflowError):
                        continue
                    if character_id <= 0:
                        continue

                    role_key = (work_id, character_id)
                    previous = roles_by_pair.get(role_key)
                    candidate_priority = role_priority.get(raw_role, 3)
                    previous_priority = role_priority.get(
                        str(previous.get("characterRole") or "").upper(), 3
                    ) if previous else 999
                    if previous is not None and candidate_priority >= previous_priority:
                        continue

                    role_edge = dict(edge)
                    role_edge["characterRole"] = raw_role
                    role_edge["characters"] = [dict(character)]
                    roles_by_pair[role_key] = role_edge

        if not roles_by_pair:
            empty = QLabel("No voice-acting character roles were found.")
            empty.setWordWrap(True)
            empty.setStyleSheet(muted_label_stylesheet())
            body.addWidget(empty)
        else:
            def role_sort_key(edge):
                node = edge.get("node") if isinstance(edge.get("node"), dict) else {}
                characters = edge.get("characters") or []
                character = characters[0] if characters and isinstance(characters[0], dict) else {}
                return (
                    role_priority.get(str(edge.get("characterRole") or "").upper(), 3),
                    str(self._work_title(node)).casefold(),
                    self._name_from(character.get("name"), "Unknown character").casefold(),
                    int(node.get("id") or 0),
                    int(character.get("id") or 0),
                )

            host = QWidget()
            flow = ProfileFlowLayout(host, h_spacing=10, v_spacing=12)
            for edge in sorted(roles_by_pair.values(), key=role_sort_key):
                card = MediaCreditCard(edge, "voice_actor")
                card.work_selected.connect(self.work_selected.emit)
                card.character_selected.connect(self.character_selected.emit)
                flow.addWidget(card)
            body.addWidget(host)
        self.content_layout.addWidget(section)

    def _render_media_credits(self, heading, connection, credit_kind):
        section, body = self._section(heading)
        edges = connection.get("edges") if isinstance(connection, dict) else None
        if not isinstance(edges, list) or not edges:
            message = (
                "No appearance data is available in the saved profile."
                if heading == "Appears in"
                else "No additional credits were found."
            )
            empty = QLabel(message)
            empty.setWordWrap(True)
            empty.setStyleSheet(muted_label_stylesheet())
            body.addWidget(empty)
        elif credit_kind == "staff":
            host = QWidget()
            flow = ProfileFlowLayout(host, h_spacing=10, v_spacing=14)
            for edge in [edge for edge in edges if isinstance(edge, dict)][:12]:
                card = ProfileWorkCreditCard(edge)
                card.clicked.connect(self.work_selected.emit)
                flow.addWidget(card)
            body.addWidget(host)
        else:
            host = QWidget()
            flow = ProfileFlowLayout(host, h_spacing=10, v_spacing=14)
            valid_edges = [edge for edge in edges if isinstance(edge, dict)]
            for edge in valid_edges[:12]:
                node = edge.get("node")
                if not isinstance(node, dict) or not node.get("id"):
                    continue
                card = WorkCard(dict(node), mode="library", show_add_button=False)
                card.clicked.connect(self.work_selected.emit)
                flow.addWidget(card)
            body.addWidget(host)
        self.content_layout.addWidget(section)

    def _section(self, title):
        frame = QFrame()
        frame.setObjectName("profileSection")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("profileSectionTitle")
        layout.addWidget(heading)
        return frame, layout

    @staticmethod
    def _fact(label, value):
        text = f"{label}: {value}" if label else str(value)
        fact = QLabel(text)
        fact.setObjectName("profileFacts")
        fact.setWordWrap(True)
        return fact

    def _load_artwork(self, url):
        if not url or self._image_label is None:
            return
        reply = self._network_manager.get(
            QNetworkRequest(QUrl(str(url)))
        )
        self._image_reply = reply
        target = self._image_label
        reply.finished.connect(
            lambda current=reply, image_target=target:
                self._image_finished(current, image_target)
        )

    def _image_finished(self, reply, target):
        if self._image_reply is reply:
            self._image_reply = None
        if (
            target is self._image_label
            and reply is not None
            and reply.error() == QNetworkReply.NetworkError.NoError
        ):
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()):
                self._set_artwork(pixmap)
        if reply is not None:
            reply.deleteLater()

    def _set_artwork(self, pixmap):
        if self._image_label is None or pixmap.isNull():
            return
        self._image_label.setPixmap(
            _crop_pixmap_to_size(pixmap, self._image_label.size())
        )

    def request_shutdown(self):
        self._request_token += 1
        if self._image_reply is not None:
            try:
                self._image_reply.abort()
            except RuntimeError:
                pass
            self._image_reply = None
