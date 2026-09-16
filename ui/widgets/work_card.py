from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QFont, QFontMetrics, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QSizePolicy, QVBoxLayout

from ui.theme import COLORS, get
from ui.widgets.cover_frame import CoverFrame


class WorkCard(QFrame):
    _network_manager = QNetworkAccessManager()
    _cover_cache = {}
    _cover_failures = set()

    def __init__(self, work, progress_editable=False, mode="library", add_callback=None):
        super().__init__()
        self.work = work
        self.progress_editable = progress_editable
        self.mode = mode
        self.add_callback = add_callback
        self._cover_reply = None

        card_width = get("card_size")
        self.setObjectName("posterCard")
        self.setFixedWidth(card_width)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        hover_css = f"background: {COLORS['surface_hover']}; border-color: {COLORS['accent']};" if get("hover_highlight") else ""
        self.setStyleSheet(f"""
            QFrame#posterCard {{ background: transparent; border: 2px solid transparent; border-radius: {get('corner_radius') + 2}px; }}
            QFrame#posterCard:hover {{ {hover_css} }}
            QLabel {{ background: transparent; border: none; }}
            QLabel#title {{ color: {COLORS['primary']}; font-size: {get('font_size')}px; font-weight: 760; }}
            QFrame#posterCard:hover QLabel#title {{ color: {COLORS['accent_hover']}; }}
            QLabel#meta {{ color: {COLORS['muted']}; font-size: 11px; }}
            QLabel#seriesInfo {{ color: {COLORS['accent_hover']}; font-size: 10px; font-weight: 800; }}
            QPushButton#add {{ background: {COLORS['accent']}; color: #111318; border: none; border-radius: 8px; padding: 7px; font-weight: 800; }}
            QPushButton#add:hover {{ background: {COLORS['accent_hover']}; }}
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(4)
        self.cover = CoverFrame(get("card_size"))
        root.addWidget(self.cover, 0, Qt.AlignHCenter)
        self._load_cover()

        full_title = self._title()
        title_font = QFont(self.font())
        title_font.setPointSize(get("font_size"))
        title_font.setWeight(QFont.Weight.Bold)
        title_metrics = QFontMetrics(title_font)
        fitted_title = self._fit_title_to_two_lines(full_title, card_width - 12, title_font)
        title_line_count = max(1, fitted_title.count("\n") + 1)
        title = QLabel(fitted_title)
        title.setObjectName("title")
        title.setWordWrap(False)
        title.setFont(title_font)
        title.setFixedHeight(title_metrics.lineSpacing() * title_line_count)
        title.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        title.setToolTip(full_title)
        root.addWidget(title)

        series_count = self._value("_series_count")
        summary = self._value("_bundle_summary")
        try:
            has_bundle = int(series_count or 0) > 1
        except (TypeError, ValueError):
            has_bundle = False

        if has_bundle:
            series_info_font = QFont(self.font())
            series_info_font.setPointSize(10)
            series_info_font.setWeight(QFont.Weight.Bold)
            series_info = QLabel(str(summary or f"{int(series_count)} entries"))
            series_info.setObjectName("seriesInfo")
            series_info.setFont(series_info_font)
            series_info.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            series_info.setFixedHeight(QFontMetrics(series_info_font).lineSpacing())
            series_info.setToolTip(str(summary) if summary else "")
            root.addWidget(series_info)

        meta_parts = []
        fmt = self._value("format")
        year = self._value("start_year") or (self._value("startDate") or {}).get("year")
        if fmt:
            meta_parts.append(str(fmt).title())
        if year:
            meta_parts.append(str(year))
        score = self._value("averageScore")
        if mode == "search" and score:
            meta_parts.append(f"★ {score}")
        if meta_parts:
            meta = QLabel("  ·  ".join(meta_parts))
            meta.setObjectName("meta")
            root.addWidget(meta)
        if mode == "search":
            add_button = QPushButton("+  Add to Library")
            add_button.setObjectName("add")
            add_button.setCursor(Qt.PointingHandCursor)
            add_button.clicked.connect(self._add_clicked)
            root.addWidget(add_button)

    @staticmethod
    def _fit_title_to_two_lines(text, width, font):
        """Fit a title to at most two complete lines and elide overflow on line two."""
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

        return f"{first}\n{second}" if second else f"{first}\n{metrics.elidedText(' '.join(words[first_end:]), Qt.TextElideMode.ElideRight, width)}"

    def _value(self, key):
        if hasattr(self.work, "get"):
            return self.work.get(key)
        try:
            return self.work[key]
        except (KeyError, TypeError, IndexError):
            return None

    def _member_value(self, member, key):
        if hasattr(member, "get"):
            return member.get(key)
        try:
            return member[key]
        except (KeyError, TypeError, IndexError):
            return None

    def _fallback_member(self):
        for member in self._value("_series_members") or []:
            title = self._member_value(member, "title")
            if isinstance(title, dict):
                title = title.get("english") or title.get("romaji") or title.get("native")
            if title:
                return member
        return None

    def _load_cover(self):
        cover_path = self._value("cover_path")
        fallback = self._fallback_member()
        if not cover_path and fallback:
            cover_path = self._member_value(fallback, "cover_path")
        if cover_path:
            pixmap = QPixmap(str(cover_path))
            if not pixmap.isNull():
                self.cover.set_pixmap(pixmap)
                return
        cover_url = self._value("cover_url") or (self._value("coverImage") or {}).get("large")
        if not cover_url and fallback:
            cover_url = self._member_value(fallback, "cover_url")
            if not cover_url:
                image = self._member_value(fallback, "coverImage")
                cover_url = image.get("large") if isinstance(image, dict) else None
        if not cover_url:
            return
        cover_url = str(cover_url)
        cached = self._cover_cache.get(cover_url)
        if cached is not None and not cached.isNull():
            self.cover.set_pixmap(cached)
            return
        if cover_url in self._cover_failures:
            return
        self._cover_reply = self._network_manager.get(QNetworkRequest(QUrl(cover_url)))
        self._cover_reply.finished.connect(lambda: self._cover_finished(cover_url))

    def _cover_finished(self, cover_url):
        reply = self._cover_reply
        if reply is None:
            return
        if reply.error():
            self._cover_failures.add(cover_url)
            reply.deleteLater()
            self._cover_reply = None
            return
        data = reply.readAll()
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self._cover_cache[cover_url] = pixmap
            self.cover.set_pixmap(pixmap)
        reply.deleteLater()
        self._cover_reply = None

    def _title(self):
        title = self._value("title")
        if isinstance(title, dict):
            return title.get("english") or title.get("romaji") or title.get("native") or "Untitled"
        return str(title or "Untitled")

    def _add_clicked(self):
        if self.add_callback:
            self.add_callback(self.work)
