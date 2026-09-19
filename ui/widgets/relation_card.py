from PySide6.QtCore import Signal, Qt, QUrl
from PySide6.QtGui import QPixmap, QFont, QFontMetrics
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QSizePolicy

from ui.preferences import get
from ui.theme import COLORS
from ui.widgets.work_card import CoverFrame


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
    _cover_cache = {}
    _cover_failures = set()

    def __init__(self, relation, parent=None):
        super().__init__(parent)
        self.relation = relation
        self._network_manager = QNetworkAccessManager(self)
        self._cover_reply = None

        self.setObjectName("relationCard")
        self.setCursor(Qt.PointingHandCursor)
        card_width = get("card_size") + 8
        self.setFixedWidth(card_width)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setStyleSheet(
            f"""
            QFrame#relationCard {{
                background: transparent;
                border: 2px solid {COLORS['frame']};
                border-radius: {get('corner_radius') + 2}px;
            }}
            QFrame#relationCard:hover {{
                background: {COLORS['surface_hover']};
            }}
            QLabel {{
                background: transparent;
                border: none;
            }}
            QLabel#title {{
                color: {COLORS['primary']};
                font-size: {get('font_size')}px;
                font-weight: 760;
            }}
            QFrame#relationCard:hover QLabel#title {{
                color: {COLORS['accent_hover']};
            }}
            QLabel#meta {{
                color: {COLORS['muted']};
                font-size: 11px;
            }}
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(8)

        self.cover = CoverFrame(get("card_size"))
        root.addWidget(self.cover, 0, Qt.AlignHCenter)
        self._load_cover()

        title_font = QFont("Segoe UI", max(8, int(get("font_size") or 13)))
        title_font.setWeight(QFont.Weight.Bold)
        title_metrics = QFontMetrics(title_font)
        title_text = self._title()
        title = QLabel(self._fit_title_to_two_lines(title_text, card_width - 12, title_font))
        title.setObjectName("title")
        title.setFont(title_font)
        title.setWordWrap(False)
        title.setFixedHeight(title_metrics.lineSpacing() * 2)
        title.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        title.setMargin(0)
        title.setToolTip(title_text)
        root.addWidget(title)

        relation_type = self._value("relation_type") or "OTHER"
        relation_label = RELATION_LABELS.get(
            relation_type,
            relation_type.replace("_", " ").title(),
        )
        source_title = self._value("source_title")
        connection = f"{source_title or 'Related work'}  →  {relation_label}"

        meta = QLabel(connection)
        meta.setObjectName("meta")
        meta.setWordWrap(True)
        meta.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        meta.setMargin(0)
        root.addWidget(meta)

        root.addStretch(1)
        self.setFixedHeight(
            self.cover.height()
            + (2 * title_metrics.lineSpacing())
            + meta.sizeHint().height()
            + root.contentsMargins().top()
            + root.contentsMargins().bottom()
            + root.spacing() * 2
        )

    @staticmethod
    def _fit_title_to_two_lines(text, width, font):
        text = " ".join(str(text).split())
        if not text:
            return ""

        metrics = QFontMetrics(font)
        words = text.split()

        first = ""
        first_end = 0
        for index, word in enumerate(words):
            candidate = word if not first else f"{first} {word}"
            if metrics.horizontalAdvance(candidate) <= width:
                first = candidate
                first_end = index + 1
            else:
                break

        if first_end >= len(words):
            return first

        second = ""
        second_end = first_end
        for index in range(first_end, len(words)):
            candidate = words[index] if not second else f"{second} {words[index]}"
            if metrics.horizontalAdvance(candidate) <= width:
                second = candidate
                second_end = index + 1
            else:
                break

        if second_end < len(words):
            overflow = " ".join(words[second_end:])
            second = metrics.elidedText(
                f"{second} {overflow}" if second else overflow,
                Qt.TextElideMode.ElideRight,
                width,
            )

        return (
            f"{first}\n{second}"
            if second
            else f"{first}\n{metrics.elidedText(' '.join(words[first_end:]), Qt.TextElideMode.ElideRight, width)}"
        )

    def _title(self):
        title = self._value("title")
        if title:
            return str(title)
        target_id = self._value("target_id")
        return f"Related work · {target_id}" if target_id else "Related work"

    def _load_cover(self):
        cover_path = self._value("cover_path")
        if cover_path:
            pixmap = QPixmap(str(cover_path))
            if not pixmap.isNull():
                self.cover.set_pixmap(pixmap)
                return

        cover_url = self._value("cover_url")
        if not cover_url:
            image = self._value("coverImage") or {}
            cover_url = image.get("large")

        if not cover_url:
            return

        cover_url = str(cover_url)
        cached = self._cover_cache.get(cover_url)
        if cached is not None and not cached.isNull():
            self.cover.set_pixmap(cached)
            return

        if cover_url in self._cover_failures:
            return

        self._cover_reply = self._network_manager.get(
            QNetworkRequest(QUrl(cover_url))
        )
        self._cover_reply.finished.connect(self._cover_finished)

    def _cover_finished(self):
        reply = self._cover_reply
        self._cover_reply = None
        if reply is None or self._is_deleted():
            return

        if reply.error() == reply.NetworkError.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()) and not self._is_deleted():
                self._cover_cache[self._current_cover_url()] = pixmap
                self.cover.set_pixmap(pixmap)
            else:
                self._cover_failures.add(self._current_cover_url())
        else:
            self._cover_failures.add(self._current_cover_url())

        reply.deleteLater()

    def _current_cover_url(self):
        cover_url = self._value("cover_url")
        if not cover_url:
            image = self._value("coverImage") or {}
            cover_url = image.get("large")
        return str(cover_url) if cover_url else ""

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
