from PySide6.QtCore import Signal, Qt, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import QFrame, QLabel, QHBoxLayout, QVBoxLayout

from ui.theme import COLORS, card_stylesheet, muted_label_stylesheet


RELATION_LABELS = {
    "ADAPTATION": "Adaptation",
    "SOURCE": "Source material",
    "PREQUEL": "Prequel",
    "SEQUEL": "Sequel",
    "PARENT": "Parent / origin",
    "SIDE_STORY": "Side story",
    "CHARACTER": "Shared characters",
    "SUMMARY": "Summary",
    "ALTERNATIVE": "Alternative version",
    "SPIN_OFF": "Spin-off",
    "OTHER": "Other connection",
    "SAME_UNIVERSE": "Same universe",
    "COMPILATION": "Compilation",
    "CONTAINS": "Contains",
}


class RelationCard(QFrame):
    clicked = Signal(object)

    def __init__(self, relation, parent=None):
        super().__init__(parent)
        self.relation = relation
        self._network_manager = QNetworkAccessManager(self)
        self._cover_reply = None
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(128)
        self.setStyleSheet(card_stylesheet())

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        self.image = QLabel()
        self.image.setFixedSize(72, 100)
        layout.addWidget(self.image)
        self._load_cover()

        text_layout = QVBoxLayout()
        title = QLabel(self._title())
        title.setStyleSheet(
            f"background: transparent; border: none; color: {COLORS['primary']}; font-weight: 650;"
        )
        title.setWordWrap(True)
        text_layout.addWidget(title)

        relation_type = self._value("relation_type") or "OTHER"
        relation_label = RELATION_LABELS.get(relation_type, relation_type.replace("_", " ").title())
        source_title = self._value("source_title")
        connection_label = QLabel(
            f"{source_title or 'Related work'}  →  {relation_label}"
        )
        connection_label.setWordWrap(True)
        connection_label.setStyleSheet(
            f"background: transparent; border: none; color: {COLORS['muted']}; font-size: 11px;"
        )
        text_layout.addWidget(connection_label)
        text_layout.addStretch()
        layout.addLayout(text_layout)

    def _title(self):
        title = self._value("title")
        if title:
            return str(title)
        target_id = self._value("target_id")
        return f"Related work · {target_id}" if target_id else "Related work"

    def _load_cover(self):
        image_path = self._value("cover_path")
        if image_path:
            pixmap = QPixmap(str(image_path))
            if not pixmap.isNull():
                self._set_cover(pixmap)
                return

        image_url = self._value("cover_url")
        if not image_url:
            cover_image = self._value("coverImage") or {}
            image_url = cover_image.get("large")
        if image_url:
            self._cover_reply = self._network_manager.get(QNetworkRequest(QUrl(str(image_url))))
            self._cover_reply.finished.connect(self._cover_finished)

    def _cover_finished(self):
        reply = self._cover_reply
        self._cover_reply = None
        if reply is None or self._is_deleted():
            return
        if reply.error() == reply.NetworkError.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()) and not self._is_deleted():
                self._set_cover(pixmap)
        reply.deleteLater()

    def _set_cover(self, pixmap):
        self.image.setPixmap(pixmap.scaled(self.image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _value(self, key):
        if hasattr(self.relation, "get"):
            return self.relation.get(key)
        try:
            return self.relation[key]
        except (IndexError, KeyError, TypeError):
            return None

    def _is_deleted(self):
        try:
            self.objectName()
            return False
        except RuntimeError:
            return True

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.relation)
            event.accept()
            return
        super().mousePressEvent(event)
