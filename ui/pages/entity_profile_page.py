from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.theme import COLORS, muted_label_stylesheet


class EntityProfilePage(QWidget):
    """Compact in-app character/staff profile with a link to the full AniList record."""

    back_requested = Signal()

    def __init__(self):
        super().__init__()
        self._network_manager = QNetworkAccessManager(self)
        self._image_reply = None
        self._image_label = None
        self._profile_url = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        self.back_button = QPushButton("← Back to work")
        self.back_button.setCursor(Qt.PointingHandCursor)
        self.back_button.clicked.connect(self.back_requested.emit)
        header.addWidget(self.back_button)
        header.addStretch(1)
        root.addLayout(header)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        self.scroll_area.setWidget(self.content)
        root.addWidget(self.scroll_area, 1)

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
            QFrame#profileHeader {{
                background:{COLORS['surface']};
                border:1px solid {COLORS['frame']};
                border-radius:18px;
            }}
            QLabel#profileName {{
                color:{COLORS['primary']};
                font-size:27px;
                font-weight:850;
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
                font-size:15px;
                font-weight:850;
            }}
            QLabel#profileImage {{
                background:{COLORS['background_alt']};
                border:1px solid {COLORS['frame']};
                border-radius:14px;
            }}
            """
        )
        self.set_profile("character", {})

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
            return str(title.get("english") or title.get("romaji") or title.get("native") or "Current work")
        return str(title or "Current work")

    def _clear_content(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                while child_layout.count():
                    child = child_layout.takeAt(0)
                    if child.widget() is not None:
                        child.widget().deleteLater()

    def set_profile(self, entity_type, record, source_work=None):
        entity_type = "staff" if str(entity_type).lower() in {"staff", "person", "people"} else "character"
        if self._image_reply is not None:
            try:
                self._image_reply.abort()
            except RuntimeError:
                pass
            self._image_reply = None

        self._clear_content()
        self._profile_url = None
        self._image_label = None

        is_character = entity_type == "character"
        kind_label = "CHARACTER PROFILE" if is_character else "STAFF PROFILE"
        name_key = "character_name" if is_character else "name"
        image_path_key = "character_image_path" if is_character else "image_path"
        image_url_key = "character_image_url" if is_character else "image_url"
        raw_id = self._value(record, "id") if is_character else self._value(record, "person_id")
        name = str(self._value(record, name_key, "Unknown character" if is_character else "Unknown staff member"))

        header = QFrame()
        header.setObjectName("profileHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(18, 18, 18, 18)
        row.setSpacing(18)

        artwork = QLabel()
        artwork.setObjectName("profileImage")
        artwork.setFixedSize(170, 220)
        artwork.setAlignment(Qt.AlignCenter)
        artwork.setScaledContents(False)
        artwork.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._image_label = artwork

        image_path = self._value(record, image_path_key)
        pixmap = QPixmap(str(image_path)) if image_path else QPixmap()
        if not pixmap.isNull():
            self._set_artwork(pixmap)
        else:
            image_url = self._value(record, image_url_key)
            if image_url:
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
            voice_name = self._value(record, "person_name")
            if voice_name:
                facts_column.addWidget(self._fact("Preferred voice actor", str(voice_name)))
        else:
            roles = str(self._value(record, "role", "") or "")
            if roles:
                facts_column.addWidget(self._fact("Credits in this bundle", roles.replace("\n", " · ")))

        if source_work is not None:
            facts_column.addWidget(
                self._fact("Opened from", self._work_title(source_work))
            )
        try:
            numeric_id = int(raw_id)
        except (TypeError, ValueError, OverflowError):
            numeric_id = 0
        if numeric_id > 0:
            noun = "character" if is_character else "staff"
            self._profile_url = f"https://anilist.co/{noun}/{numeric_id}"
            facts_column.addWidget(self._fact("AniList ID", str(numeric_id)))

        facts_column.addStretch(1)
        row.addLayout(facts_column, 1)
        self.content_layout.addWidget(header)

        credits_title = QLabel("About this profile")
        credits_title.setObjectName("profileSectionTitle")
        self.content_layout.addWidget(credits_title)
        if is_character:
            detail_text = (
                "This profile shows the character's cached cast information for the work "
                "you opened. The role shown above is the strongest role found across the "
                "current bundle. Voice actor selection prefers Japanese-language credits "
                "when AniList provides them."
            )
        else:
            detail_text = (
                "This profile shows the staff member's cached credits for the work or "
                "bundle you opened. Different bundled entries can give the same person "
                "different roles; NekoTrack combines those role labels on the work page."
            )
        detail = QLabel(detail_text)
        detail.setWordWrap(True)
        detail.setStyleSheet(muted_label_stylesheet())
        self.content_layout.addWidget(detail)

        if self._profile_url:
            open_button = QPushButton("Open full AniList profile ↗")
            open_button.setCursor(Qt.PointingHandCursor)
            open_button.clicked.connect(
                lambda checked=False, url=self._profile_url: QDesktopServices.openUrl(QUrl(url))
            )
            self.content_layout.addWidget(open_button, 0, Qt.AlignLeft)

        self.content_layout.addStretch(1)
        self.scroll_area.verticalScrollBar().setValue(0)

    @staticmethod
    def _fact(label, value):
        fact = QLabel(f"{label}: {value}")
        fact.setObjectName("profileFacts")
        fact.setWordWrap(True)
        return fact

    def _load_artwork(self, url):
        self._image_reply = self._network_manager.get(
            QNetworkRequest(QUrl(str(url)))
        )
        self._image_reply.finished.connect(self._image_finished)

    def _image_finished(self):
        reply = self._image_reply
        self._image_reply = None
        if reply is not None and reply.error() == reply.NetworkError.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()):
                self._set_artwork(pixmap)
        if reply is not None:
            reply.deleteLater()

    def _set_artwork(self, pixmap):
        if self._image_label is None or pixmap.isNull():
            return
        scaled = pixmap.scaled(
            self._image_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)

    def request_shutdown(self):
        if self._image_reply is not None:
            try:
                self._image_reply.abort()
            except RuntimeError:
                pass
            self._image_reply = None
