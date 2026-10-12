from pathlib import Path

from PySide6.QtCore import Signal, Qt, QUrl
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QPen, QColor
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QSizePolicy,
    QWidget,
)

from database import save_character_image_path, save_person_image_path
from ui.theme import COLORS, card_stylesheet, muted_label_stylesheet


class CharacterArtwork(QFrame):
    """Portrait artwork clipped to a rounded frame."""
    def __init__(self, width=72, height=96, radius=14, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap()
        self.setFixedSize(width, height)
        self._radius = radius
        self.setAttribute(Qt.WA_TranslucentBackground)

    def set_pixmap(self, pixmap):
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        rect = self.rect().adjusted(2, 2, -2, -2)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)

        if not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            x = max(0, (scaled.width() - rect.width()) // 2)
            y = max(0, (scaled.height() - rect.height()) // 2)
            cropped = scaled.copy(x, y, rect.width(), rect.height())
            painter.save()
            painter.setClipPath(path)
            painter.drawPixmap(rect.topLeft(), cropped)
            painter.restore()
            painter.setPen(QPen(QColor(COLORS["frame"]), 3.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

        painter.end()


class VoiceActorMiniCard(QFrame):
    """An independently clickable voice-actor credit nested inside a character card."""
    clicked = Signal(object)

    def __init__(self, actor, parent=None):
        super().__init__(parent)
        self.actor = dict(actor or {})
        self.setObjectName("voiceActorMiniCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(118)
        self.setStyleSheet(
            f"QFrame#voiceActorMiniCard {{ background:{COLORS['surface']};"
            f"border:1px solid {COLORS['frame']};border-radius:12px; }}"
            f"QFrame#voiceActorMiniCard:hover {{ border-color:{COLORS['accent']};"
            f"background:{COLORS['surface_hover']}; }}"
        )
        self._network_manager = QNetworkAccessManager(self)
        self._image_reply = None
        self._person_id = self._value("person_id")
        self._image = CharacterArtwork(58, 72, 10)
        self._image.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)
        layout.addWidget(self._image, 0, Qt.AlignHCenter)

        image_path = self._value("person_image_path", "image_path")
        image_url = self._value("person_image_url", "image_url")
        pixmap = QPixmap(str(image_path)) if image_path else QPixmap()
        if not pixmap.isNull():
            self._image.set_pixmap(pixmap)
        elif image_url:
            self._load_image_url(image_url)

        name = QLabel(str(self._value("person_name", "name") or "Voice actor"))
        name.setObjectName("voiceActorMiniName")
        name.setWordWrap(True)
        name.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        name.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        name.setStyleSheet(
            f"background:transparent;border:none;color:{COLORS['primary']};"
            "font-size:11px;font-weight:700;"
        )
        layout.addWidget(name)

        language = self._value("person_language", "language")
        language_text = str(language or "Voice actor")
        language_label = QLabel(language_text)
        language_label.setWordWrap(True)
        language_label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        language_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        language_label.setStyleSheet(muted_label_stylesheet())
        layout.addWidget(language_label)

        self.setToolTip(f"Open voice actor profile: {name.text()}")

    def _value(self, primary, fallback=None):
        value = self.actor.get(primary)
        if value is None and fallback:
            value = self.actor.get(fallback)
        return value

    def _load_image_url(self, url):
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
                self._image.set_pixmap(pixmap)
                if self._person_id is not None:
                    try:
                        directory = Path("data") / "images" / "people"
                        directory.mkdir(parents=True, exist_ok=True)
                        path = directory / f"{int(self._person_id)}.jpg"
                        if pixmap.save(str(path), "JPG", 90):
                            save_person_image_path(self._person_id, path)
                    except (OSError, TypeError, ValueError, OverflowError):
                        pass
        if reply is not None:
            reply.deleteLater()

    def refresh_theme(self):
        self.setStyleSheet(
            f"QFrame#voiceActorMiniCard {{ background:{COLORS['surface']};"
            f"border:1px solid {COLORS['frame']};border-radius:12px; }}"
            f"QFrame#voiceActorMiniCard:hover {{ border-color:{COLORS['accent']};"
            f"background:{COLORS['surface_hover']}; }}"
        )
        for label in self.findChildren(QLabel):
            if label.objectName() == "voiceActorMiniName":
                label.setStyleSheet(
                    f"background:transparent;border:none;color:{COLORS['primary']};"
                    "font-size:11px;font-weight:700;"
                )
            else:
                label.setStyleSheet(muted_label_stylesheet())
        self._image.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            event.accept()
            self.clicked.emit(self.actor)
            return
        super().mousePressEvent(event)


class CharacterCard(QFrame):
    clicked = Signal(object)
    voice_actor_clicked = Signal(object)

    def __init__(self, character, parent=None):
        super().__init__(parent)
        self.character = character
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(card_stylesheet())
        self._network_manager = QNetworkAccessManager(self)
        self._image_reply = None
        self._character_id = self._value("id")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        image = CharacterArtwork(88, 116, 14)
        self._image_artwork = image
        image_path = self._value("character_image_path")
        image_url = self._value("character_image_url")
        pixmap = QPixmap(str(image_path)) if image_path else QPixmap()
        if not pixmap.isNull():
            image.set_pixmap(pixmap)
        elif image_url:
            self._load_image_url(image_url)
        layout.addWidget(image, alignment=Qt.AlignTop)

        text_layout = QGridLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setHorizontalSpacing(8)
        text_layout.setVerticalSpacing(6)

        role = self._value("character_role")
        if role:
            role_label = QLabel(str(role).replace("_", " ").title())
            role_label.setObjectName("characterRole")
            role_label.setWordWrap(True)
            role_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            role_label.setStyleSheet(
                f"background:transparent;border:none;color:{COLORS['accent']};"
                "font-size:12px;font-weight:800;"
            )
            text_layout.addWidget(role_label, 0, 0)

        name = QLabel(self._value("character_name") or "Unknown character")
        name.setObjectName("characterName")
        name.setWordWrap(True)
        name.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        name.setStyleSheet(
            f"background:transparent;border:none;color:{COLORS['primary']};"
            "font-size:14px;font-weight:750;"
        )
        text_layout.addWidget(name, 1, 0)

        hint = QLabel("Open character profile  ↗")
        hint.setObjectName("characterProfileHint")
        hint.setStyleSheet(muted_label_stylesheet())
        text_layout.addWidget(hint, 2, 0)
        text_layout.setRowStretch(3, 1)
        layout.addLayout(text_layout, 1)

        person_name = self._value("person_name")
        person_id = self._value("person_id")
        if person_id is not None and person_name:
            actor = {
                "person_id": person_id,
                "name": person_name,
                "image_path": self._value("person_image_path"),
                "image_url": self._value("person_image_url"),
                "language": self._value("person_language"),
            }
            actor_card = VoiceActorMiniCard(actor)
            actor_card.clicked.connect(self.voice_actor_clicked.emit)
            layout.addWidget(actor_card, 0, Qt.AlignTop)
        else:
            empty_actor = QFrame()
            empty_actor.setFixedWidth(118)
            empty_layout = QVBoxLayout(empty_actor)
            empty_layout.setContentsMargins(8, 8, 8, 8)
            empty_layout.setSpacing(5)
            placeholder = QLabel("No voice\ncredit cached")
            placeholder.setWordWrap(True)
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet(muted_label_stylesheet())
            empty_layout.addWidget(placeholder, 1)
            empty_actor.setToolTip(
                "No voice actor was saved for this specific adaptation."
            )
            layout.addWidget(empty_actor, 0, Qt.AlignTop)

    def refresh_theme(self):
        self.setStyleSheet(card_stylesheet())
        label_styles = {
            "characterRole": (
                f"background:transparent;border:none;color:{COLORS['accent']};"
                "font-size:12px;font-weight:800;"
            ),
            "characterName": (
                f"background:transparent;border:none;color:{COLORS['primary']};"
                "font-size:14px;font-weight:750;"
            ),
            "characterProfileHint": muted_label_stylesheet(),
        }
        for label in self.findChildren(QLabel):
            stylesheet = label_styles.get(label.objectName())
            if stylesheet is not None:
                label.setStyleSheet(stylesheet)
        for widget in self.findChildren(QWidget):
            updater = getattr(widget, "refresh_theme", None)
            if callable(updater):
                updater()
        self.update()

    def _load_image_url(self, url):
        if not url:
            return
        self._image_reply = self._network_manager.get(
            QNetworkRequest(QUrl(str(url)))
        )
        self._image_reply.finished.connect(self._image_finished)

    def _image_finished(self):
        reply = self._image_reply
        self._image_reply = None
        if reply is not None and reply.error() == reply.NetworkError.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()) and self._image_artwork is not None:
                self._image_artwork.set_pixmap(pixmap)
                if self._character_id is not None:
                    try:
                        directory = Path("data") / "images" / "characters"
                        directory.mkdir(parents=True, exist_ok=True)
                        path = directory / f"{int(self._character_id)}.jpg"
                        if pixmap.save(str(path), "JPG", 90):
                            save_character_image_path(self._character_id, path)
                    except (OSError, TypeError, ValueError, OverflowError):
                        pass
        if reply is not None:
            reply.deleteLater()

    def _value(self, key):
        if hasattr(self.character, "get"):
            return self.character.get(key)
        try:
            return self.character[key]
        except (KeyError, TypeError):
            return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.character)
        super().mousePressEvent(event)
