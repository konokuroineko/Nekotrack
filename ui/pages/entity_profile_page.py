from PySide6.QtCore import Qt, Signal, QUrl, QObject, QRunnable, QThreadPool
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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


class MediaCreditCard(QFrame):
    """A compact internal work-credit card with NekoTrack navigation."""
    work_selected = Signal(object)

    def __init__(self, edge, credit_kind, parent=None):
        super().__init__(parent)
        edge = edge if isinstance(edge, dict) else {}
        node = edge.get("node") if isinstance(edge.get("node"), dict) else {}
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
        self.setStyleSheet(
            f"QFrame#mediaCreditCard {{ background:{COLORS['surface']};"
            f"border:1px solid {COLORS['frame']};border-radius:12px; }}"
            f"QFrame#mediaCreditCard:hover {{ border-color:{COLORS['accent']}; }}"
        )
        self.setMinimumWidth(260)
        self.setMaximumWidth(420)
        self.setMinimumHeight(125)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 10, 10, 10)
        row.setSpacing(12)
        cover = QLabel()
        cover.setFixedSize(72, 102)
        cover.setAlignment(Qt.AlignCenter)
        cover.setScaledContents(False)
        cover.setStyleSheet(
            f"background:{COLORS['background_alt']};border:1px solid {COLORS['frame']};"
            "border-radius:8px;"
        )
        row.addWidget(cover, 0, Qt.AlignTop)

        cover_data = node.get("coverImage")
        cover_url = cover_data.get("large") if isinstance(cover_data, dict) else None
        if cover_url:
            self._network = QNetworkAccessManager(self)
            self._reply = self._network.get(QNetworkRequest(QUrl(str(cover_url))))
            self._reply.finished.connect(
                lambda label=cover, reply=self._reply: self._image_finished(label, reply)
            )
        else:
            self._reply = None

        text_column = QVBoxLayout()
        title_label = QLabel(str(title))
        title_label.setWordWrap(True)
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
        metadata.setStyleSheet(muted_label_stylesheet())
        text_column.addWidget(metadata)

        if credit_kind == "character":
            credit = edge.get("characterRole")
        elif credit_kind == "voice_actor":
            characters = edge.get("characters")
            character_names = []
            if isinstance(characters, list):
                for character in characters:
                    if not isinstance(character, dict):
                        continue
                    character_name = character.get("name")
                    if isinstance(character_name, dict):
                        character_name = character_name.get("full")
                    if character_name:
                        character_names.append(str(character_name))
            credit = (
                "Voices: " + ", ".join(character_names[:3])
                if character_names else edge.get("characterRole")
            )
        else:
            credit = edge.get("staffRole") or edge.get("role")
        if credit:
            role = QLabel(str(credit))
            role.setWordWrap(True)
            role.setStyleSheet(
                f"color:{COLORS['accent']};font-size:11px;font-weight:750;"
                "background:transparent;border:none;"
            )
            text_column.addWidget(role)

        text_column.addStretch(1)
        open_button = QPushButton("Open in NekoTrack →")
        open_button.setCursor(Qt.PointingHandCursor)
        open_button.setEnabled(self.media_id > 0)
        open_button.clicked.connect(self._open_media)
        text_column.addWidget(open_button, 0, Qt.AlignLeft)
        row.addLayout(text_column, 1)

    def _image_finished(self, label, reply):
        if reply is not None and reply.error() == QNetworkReply.NetworkError.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()):
                label.setPixmap(_crop_pixmap_to_size(pixmap, label.size()))
        if reply is not None:
            reply.deleteLater()

    def _open_media(self):
        if self.media_id > 0:
            self.work_selected.emit(dict(self.media_record))


class EntityProfilePage(QWidget):
    """NekoTrack character and voice-actor profiles with internal work navigation."""

    back_requested = Signal()
    voice_actor_selected = Signal(object)
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

        artwork = QLabel()
        artwork.setObjectName("profileImage")
        artwork.setFixedSize(180, 240)
        artwork.setAlignment(Qt.AlignCenter)
        artwork.setScaledContents(False)
        artwork.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
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
                    "Voice acting", remote.get("characterMedia"), "voice_actor"
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
                person.setdefault("role", str(person.get("language") or "Voice actor"))
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
                grid.addWidget(card, index // 3, index % 3)
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
