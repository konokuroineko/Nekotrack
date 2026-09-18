from pathlib import Path

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QPen, QColor, QFont, QFontMetrics
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import QFrame, QLabel, QMenu, QPushButton, QToolButton, QVBoxLayout, QSizePolicy

from database import save_cover_path
from ui.preferences import get
from ui.theme import COLORS


IMAGE_DIRECTORY = Path("data") / "images" / "works"


class CoverFrame(QFrame):
    """Poster with artwork clipped to the rounded frame and an accent outline."""
    def __init__(self, width=None, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._width = width or get("card_size")
        self.setFixedSize(self._width, round(self._width * 284 / 210))
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
        radius = get("corner_radius")
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        if not self._pixmap.isNull():
            scaled = self._pixmap.scaled(rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x = max(0, (scaled.width() - rect.width()) // 2)
            y = max(0, (scaled.height() - rect.height()) // 2)
            cropped = scaled.copy(x, y, rect.width(), rect.height())
            painter.save()
            painter.setClipPath(path)
            painter.drawPixmap(rect.topLeft(), cropped)
            painter.restore()
        painter.setPen(QPen(QColor(COLORS["accent"]), 3.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        painter.end()


class WorkCard(QFrame):
    clicked = Signal(object)
    bundle_edit_requested = Signal(object)
    remove_requested = Signal(object)
    auto_bundle_requested = Signal(object)
    progress_changed = Signal(int)
    add_requested = Signal(object)
    _cover_cache = {}
    _cover_failures = set()

    def __init__(self, work, progress_editable=False, mode="library", add_callback=None, parent=None):
        super().__init__(parent)
        self.work = work
        self.mode = mode
        self.add_callback = add_callback
        self._network_manager = QNetworkAccessManager(self)
        self._cover_reply = None
        self.setObjectName("posterCard")
        self.setCursor(Qt.PointingHandCursor)
        card_width = get("card_size") + 8
        self.setFixedWidth(card_width)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.menu_button = None
        if self.mode == "library":
            self.menu_button = QToolButton(self)
            self.menu_button.setText("⋮")
            self.menu_button.setCursor(Qt.PointingHandCursor)
            self.menu_button.setFixedSize(28, 28)
            self.menu_button.setStyleSheet(
                f"""
                QToolButton {{
                    background: rgba(0, 0, 0, 145);
                    color: white;
                    border: 1px solid rgba(255, 255, 255, 50);
                    border-radius: 8px;
                    font-size: 20px;
                    font-weight: 900;
                    padding: 0;
                }}
                QToolButton:hover {{
                    background: rgba(0, 0, 0, 190);
                }}
                """
            )
            self.menu_button.clicked.connect(self._show_library_menu)
            self.menu_button.move(card_width - self.menu_button.width() - 8, 8)
            self.menu_button.raise_()
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
        root.setSpacing(8)
        self.cover = CoverFrame(get("card_size"))
        root.addWidget(self.cover, 0, Qt.AlignHCenter)
        self._load_cover()

        full_title = self._title()
        title_font = QFont(self.font())
        title_font.setPointSize(max(8, int(get("font_size") or 13)))
        title_font.setWeight(QFont.Weight.Bold)
        title_metrics = QFontMetrics(title_font)
        fitted_title = self._fit_title_to_two_lines(full_title, card_width - 12, title_font)
        title = QLabel(fitted_title)
        title.setObjectName("title")
        title.setWordWrap(False)
        title.setFont(title_font)
        # Every card reserves the same two-line title area, keeping one-line
        # titles the same height as two-line titles.
        title.setFixedHeight(title_metrics.lineSpacing() * 2)
        title.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        title.setMargin(0)
        title.setToolTip(full_title)

        series_count = self._value("_series_count")
        summary = self._value("_bundle_summary")
        try:
            has_bundle = int(series_count or 0) > 1
        except (TypeError, ValueError):
            has_bundle = False

        # The normal title->metadata gap and the bundle indicator row use the
        # exact same vertical height. Bundle cards therefore stay the same
        # height as non-bundle cards without an extra empty row around the
        # indicator.
        series_font = QFont(self.font())
        series_font.setPointSize(10)
        series_font.setWeight(QFont.Weight.Bold)
        series_height = QFontMetrics(series_font).height()

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0 if has_bundle else series_height)
        content.addWidget(title)

        if has_bundle:
            series_info = QLabel(str(summary or f"{int(series_count)} entries"))
            series_info.setObjectName("seriesInfo")
            series_info.setFont(series_font)
            series_info.setFixedHeight(series_height)
            series_info.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            series_info.setMargin(0)
            series_info.setToolTip(str(summary or ""))
            content.addWidget(series_info)

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

        meta = None
        if meta_parts:
            meta = QLabel("  ·  ".join(meta_parts))
            meta.setObjectName("meta")
            meta.setMargin(0)
            content.addWidget(meta)

        root.addLayout(content)

        add_button = None
        if mode == "search":
            add_button = QPushButton("+  Add to Library")
            add_button.setObjectName("add")
            add_button.setCursor(Qt.PointingHandCursor)
            add_button.clicked.connect(self._add_clicked)
            root.addWidget(add_button)

        root.addStretch(1)
        self.adjustSize()
        target_height = (
            self.cover.height()
            + (2 * title_metrics.lineSpacing())
            + series_height
            + (meta.sizeHint().height() if meta is not None else 0)
            + (add_button.sizeHint().height() if add_button is not None else 0)
            + root.contentsMargins().top()
            + root.contentsMargins().bottom()
            + root.spacing() * (1 + (1 if add_button is not None else 0))
        )
        self.setFixedHeight(target_height)

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
        bundle_cover_work_id = self._value("_bundle_cover_work_id")
        if bundle_cover_work_id is not None:
            for member in self._value("_series_members") or []:
                if int(self._member_value(member, "id")) == int(bundle_cover_work_id):
                    cover_path = self._member_value(member, "cover_path")
                    break
        fallback = self._fallback_member()
        if not cover_path and fallback:
            cover_path = self._member_value(fallback, "cover_path")
        if cover_path:
            pixmap = QPixmap(str(cover_path))
            if not pixmap.isNull():
                self.cover.set_pixmap(pixmap)
                return
        cover_url = self._value("cover_url") or (self._value("coverImage") or {}).get("large")
        if bundle_cover_work_id is not None:
            for member in self._value("_series_members") or []:
                if int(self._member_value(member, "id")) == int(bundle_cover_work_id):
                    cover_url = self._member_value(member, "cover_url")
                    if not cover_url:
                        image = self._member_value(member, "coverImage")
                        cover_url = image.get("large") if isinstance(image, dict) else None
                    break
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
        self._cover_reply = None
        if reply is not None and reply.error() == reply.NetworkError.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()):
                self._cover_cache[cover_url] = pixmap
                self.cover.set_pixmap(pixmap)
                work_id = self._value("_bundle_cover_work_id") or self._value("_bundle_default_member_id") or self._value("id")
                if work_id:
                    try:
                        IMAGE_DIRECTORY.mkdir(parents=True, exist_ok=True)
                        path = IMAGE_DIRECTORY / f"{work_id}.jpg"
                        if pixmap.save(str(path), "JPG", 85):
                            save_cover_path(work_id, str(path))
                    except Exception:
                        pass
            else:
                self._cover_failures.add(cover_url)
        else:
            self._cover_failures.add(cover_url)
        if reply is not None:
            reply.deleteLater()

    def _add_clicked(self):
        self.add_requested.emit(self.work)
        if self.add_callback:
            self.add_callback(self.work, self.sender())

    def _title(self):
        title = self._value("title")
        if isinstance(title, dict):
            title = title.get("english") or title.get("romaji") or title.get("native")
        if title:
            return str(title)
        fallback = self._fallback_member()
        if fallback is not None:
            fallback_title = self._member_value(fallback, "title")
            if isinstance(fallback_title, dict):
                fallback_title = fallback_title.get("english") or fallback_title.get("romaji") or fallback_title.get("native")
            if fallback_title:
                return str(fallback_title)
        work_id = self._value("id")
        return f"Untitled · {work_id}" if work_id else "Untitled"

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.menu_button is not None:
            self.menu_button.move(self.width() - self.menu_button.width() - 8, 8)
            self.menu_button.raise_()

    def _show_library_menu(self):
        if self.mode != "library":
            return

        menu = QMenu(self)
        auto_action = menu.addAction("Auto Bundle")

        try:
            has_bundle = int(self._value("_series_count") or 0) > 1
        except (TypeError, ValueError):
            has_bundle = False

        edit_action = None
        if has_bundle:
            edit_action = menu.addAction("Edit Bundle Appearance…")

        menu.addSeparator()
        delete_action = menu.addAction("Delete")

        selected = menu.exec(
            self.menu_button.mapToGlobal(
                self.menu_button.rect().bottomLeft()
            )
        )

        if selected == auto_action:
            self.auto_bundle_requested.emit(self.work)
        elif edit_action is not None and selected == edit_action:
            self.bundle_edit_requested.emit(self.work)
        elif selected == delete_action:
            self.remove_requested.emit(self.work)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.work)
            return
        super().mousePressEvent(event)
