from PySide6.QtCore import Qt, Signal, QUrl, QObject, QRunnable, QThreadPool, QRectF
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QPen, QColor
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
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
        self.setMinimumWidth(260)
        self.setMaximumWidth(1600 if self.credit_kind == "voice_actor" else 420)
        self.setMinimumHeight(142 if self.credit_kind == "voice_actor" else 125)

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
        title_label.setWordWrap(True)
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
        metadata.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        metadata.setStyleSheet(muted_label_stylesheet())
        text_column.addWidget(metadata)

        if self.credit_kind == "character":
            credit = edge.get("characterRole")
        elif self.credit_kind == "voice_actor":
            credit = None
        else:
            credit = edge.get("staffRole") or edge.get("role")
        if credit:
            role = QLabel(str(credit))
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
                cast_container = QWidget()
                cast_column = QVBoxLayout(cast_container)
                cast_column.setContentsMargins(4, 0, 0, 0)
                cast_column.setSpacing(5)
                cast_title = QLabel("CHARACTERS")
                cast_title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                cast_title.setStyleSheet(
                    f"background:transparent;border:none;color:{COLORS['accent']};"
                    "font-size:9px;font-weight:850;letter-spacing:1px;"
                )
                cast_column.addWidget(cast_title)
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
                extra_count = len(valid_characters) - len(visible_characters)
                if extra_count > 0:
                    extra = QLabel(f"+{extra_count}")
                    extra.setToolTip(", ".join(
                        (
                            item.get("name", {}).get("full", "Unknown character")
                            if isinstance(item.get("name"), dict)
                            else str(item.get("name") or "Unknown character")
                        )
                        for item in valid_characters[4:]
                    ))
                    extra.setStyleSheet(
                        f"color:{COLORS['muted']};background:transparent;border:none;"
                        "font-weight:800;"
                    )
                    extra.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                    cast_row.addWidget(extra, 0, Qt.AlignVCenter)
                cast_column.addLayout(cast_row)
                row.addWidget(cast_container, 0, Qt.AlignVCenter)
            else:
                no_cast = QLabel("Character credits unavailable")
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
            QLabel#profileDescription {{
                color:{COLORS['secondary']};
                font-size:13px;
                line-height:1.35;
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

        if self.source_work is not None:
            facts_column.addWidget(self._fact("Opened from", self._work_title(self.source_work)))
        facts_column.addStretch(1)
        row.addLayout(facts_column, 1)
        self.content_layout.addWidget(header)

        description = str(remote.get("description") or self._value(record, "description", "") or "").strip()
        if description:
            section, layout = self._section("About")
            description_label = QLabel(description)
            description_label.setObjectName("profileDescription")
            description_label.setWordWrap(True)
            description_label.setTextFormat(Qt.PlainText)
            description_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(description_label)
            self.content_layout.addWidget(section)
        elif self._remote_error:
            section, layout = self._section("About")
            note = QLabel(
                "The detailed biography could not be loaded. Your saved character "
                "or staff information is still available below."
            )
            note.setWordWrap(True)
            note.setStyleSheet(muted_label_stylesheet())
            layout.addWidget(note)
            self.content_layout.addWidget(section)

        if is_character:
            self._render_voice_actors()
            connection = remote.get("media")
            self._render_media_credits("Appears in", connection, "character")
        else:
            if is_voice_actor:
                self._render_media_credits(
                    "Voice acting roles", remote.get("characterMedia"), "voice_actor"
                )
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
                credits = person.get("credits")
                role_labels = []
                if isinstance(credits, list):
                    for credit in credits:
                        if not isinstance(credit, dict):
                            continue
                        work_title = str(credit.get("work_title") or "").strip()
                        work_id = credit.get("work_id")
                        if not work_title and work_id is not None:
                            work_title = f"Work {work_id}"
                        language = str(credit.get("language") or "").strip()
                        if language and work_title:
                            label = f"{language} · {work_title}"
                        else:
                            label = language or work_title
                        if label and label not in role_labels:
                            role_labels.append(label)
                languages = person.get("languages")
                if not role_labels:
                    if isinstance(languages, (list, tuple)):
                        role_labels = [
                            str(language).strip()
                            for language in languages
                            if str(language).strip()
                        ]
                    if not role_labels and person.get("language"):
                        role_labels = [str(person["language"]).strip()]
                person["role"] = " / ".join(role_labels) or "Voice actor"
                card = PersonCard(person, portrait_size=(90, 120))
                card.clicked.connect(self.voice_actor_selected.emit)
                grid.addWidget(card, index // 5, index % 5)
            body.addWidget(grid_host)
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
        else:
            host = QWidget()
            grid = QGridLayout(host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(10)
            valid_edges = [edge for edge in edges if isinstance(edge, dict)]
            for index, edge in enumerate(valid_edges[:12]):
                card = MediaCreditCard(edge, credit_kind)
                card.work_selected.connect(self.work_selected.emit)
                card.character_selected.connect(self.character_selected.emit)
                if credit_kind == "voice_actor":
                    grid.addWidget(card, index, 0, 1, 3)
                else:
                    grid.addWidget(card, index // 3, index % 3)
            if credit_kind == "voice_actor":
                for column in range(3):
                    grid.setColumnStretch(column, 1)
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
