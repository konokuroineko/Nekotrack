from pathlib import Path

from PySide6.QtCore import Signal, Qt, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from database import save_person_image_path
from ui.theme import COLORS, card_stylesheet, muted_label_stylesheet


class PersonCard(QFrame):
    clicked = Signal(object)

    def __init__(self, person, parent=None):
        super().__init__(parent)
        self.person = person
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(card_stylesheet())
        self._network_manager = QNetworkAccessManager(self)
        self._image_reply = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.image = QLabel()
        self.image.setFixedSize(120, 120)
        self.image.setAlignment(Qt.AlignCenter)
        image_path = self._value("image_path")
        if image_path:
            pixmap = QPixmap(str(image_path))
            if not pixmap.isNull():
                self.image.setPixmap(pixmap.scaled(
                    self.image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                ))
        else:
            self._load_image_url(self._value("image_url"))
        layout.addWidget(self.image, alignment=Qt.AlignCenter)

        name = QLabel(self._value("name") or "Unknown person")
        name.setWordWrap(True)
        name.setStyleSheet(f"color: {COLORS['primary']}; font-weight: 600;")
        name.setAlignment(Qt.AlignCenter)
        layout.addWidget(name)

        role = self._value("role")
        if role:
            role_label = QLabel(role)
            role_label.setStyleSheet(muted_label_stylesheet())
            role_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(role_label)

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
            if pixmap.loadFromData(reply.readAll()):
                self.image.setPixmap(pixmap.scaled(
                    self.image.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                ))
                person_id = self._value("person_id")
                if person_id is not None:
                    try:
                        directory = Path("data") / "images" / "people"
                        directory.mkdir(parents=True, exist_ok=True)
                        path = directory / f"{int(person_id)}.jpg"
                        if pixmap.save(str(path), "JPG", 90):
                            save_person_image_path(person_id, path)
                    except Exception:
                        pass
        if reply is not None:
            reply.deleteLater()

    def _value(self, key):
        if hasattr(self.person, "get"):
            return self.person.get(key)
        try:
            return self.person[key]
        except (KeyError, TypeError):
            return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.person)
        super().mousePressEvent(event)
