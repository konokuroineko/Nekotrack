from PySide6.QtCore import Signal, Qt, QUrl
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QPen, QColor
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import QFrame, QLabel, QHBoxLayout, QVBoxLayout

from ui.theme import COLORS, card_stylesheet, muted_label_stylesheet


class CharacterArtwork(QFrame):
    """Circular character artwork with the same accent frame used by poster covers."""
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

        if not self._pixmap.isNull():
            painter.setPen(QPen(QColor(COLORS["accent"]), 3.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

        painter.end()


class CharacterCard(QFrame):
    clicked = Signal(object)

    def __init__(self, character, parent=None):
        super().__init__(parent)
        self.character = character
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(card_stylesheet())
        self._network_manager = QNetworkAccessManager(self)
        self._image_reply = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        image = CharacterArtwork(72, 96, 14)
        image_path = self._value("character_image_path")
        image_url = self._value("character_image_url")

        if image_path:
            pixmap = QPixmap(str(image_path))
            if not pixmap.isNull():
                image.set_pixmap(pixmap)

        layout.addWidget(image, alignment=Qt.AlignTop)

        if image._pixmap.isNull():
            self._image_artwork = image
            self._load_image_url(image_url)
        else:
            self._image_artwork = image

        text_layout = QVBoxLayout()
        name = QLabel(self._value("character_name") or "Unknown character")
        name.setWordWrap(True)
        name.setStyleSheet(f"color: {COLORS['primary']}; font-weight: 600;")
        text_layout.addWidget(name)

        person_name = self._value("person_name")
        if person_name:
            voice = QLabel(f"Voice: {person_name}")
            voice.setWordWrap(True)
            voice.setStyleSheet(muted_label_stylesheet())
            text_layout.addWidget(voice)
        text_layout.addStretch()
        layout.addLayout(text_layout)

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
            if pixmap.loadFromData(reply.readAll()) and getattr(self, "_image_artwork", None) is not None:
                self._image_artwork.set_pixmap(pixmap)
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
