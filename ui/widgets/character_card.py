from PySide6.QtCore import Signal, Qt, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import QFrame, QLabel, QHBoxLayout, QVBoxLayout

from ui.theme import COLORS, card_stylesheet, muted_label_stylesheet


class CharacterCard(QFrame):
    clicked = Signal(object)

    def __init__(self, character, parent=None):
        super().__init__(parent)
        self.character = character
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(card_stylesheet())
        self._network_manager = QNetworkAccessManager(self)
        self._image_reply = None
        self._image_label = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        image = QLabel()
        image.setFixedSize(72, 96)
        image.setAlignment(Qt.AlignCenter)
        image_path = self._value("character_image_path")
        image_url = self._value("character_image_url")

        if image_path:
            pixmap = QPixmap(str(image_path))
            if not pixmap.isNull():
                image.setPixmap(
                    pixmap.scaled(
                        image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                )

        self._image_label = image
        layout.addWidget(image)

        if image.pixmap() is None or image.pixmap().isNull():
            self._load_image_url(image_url)

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
            if pixmap.loadFromData(reply.readAll()) and self._image_label is not None:
                self._image_label.setPixmap(
                    pixmap.scaled(
                        self._image_label.size(),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )
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
