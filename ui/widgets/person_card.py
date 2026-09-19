from pathlib import Path

from PySide6.QtCore import Signal, Qt, QUrl
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QPen, QColor
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from database import save_person_image_path
from ui.theme import COLORS, muted_label_stylesheet


class PersonArtwork(QFrame):
    """Portrait artwork clipped to a rounded frame like character artwork."""
    def __init__(self, width=120, height=120, radius=14, parent=None):
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


class PersonCard(QFrame):
    clicked = Signal(object)

    def __init__(self, person, parent=None):
        super().__init__(parent)
        self.person = person
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(152)
        self.setStyleSheet("QFrame { background: transparent; border: none; }")
        self._network_manager = QNetworkAccessManager(self)
        self._image_reply = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.image = PersonArtwork(120, 120, 14)
        image_path = self._value("image_path")
        if image_path:
            pixmap = QPixmap(str(image_path))
            if not pixmap.isNull():
                self.image.set_pixmap(pixmap)
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
                self.image.set_pixmap(pixmap)
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
