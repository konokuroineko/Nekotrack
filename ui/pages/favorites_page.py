"""A persistent Favorites destination, independent of Library membership."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from database import get_favorite_works, set_work_favorite
from diagnostics import log_exception
from ui.theme import COLORS, surface_rgba
from ui.widgets.work_card import WorkCard


class FavoritesPage(QWidget):
    work_selected = Signal(object)
    search_requested = Signal()

    def __init__(self):
        super().__init__()
        self._works = []
        self.setObjectName("favoritesPage")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("favoritesScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setObjectName("favoritesContent")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(34, 28, 34, 34)
        self.content_layout.setSpacing(18)
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll)
        self.refresh()

    def refresh(self):
        self._clear()
        header = QFrame()
        header.setObjectName("favoritesHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(22, 20, 22, 20)
        text = QVBoxLayout()
        text.setSpacing(5)
        title = QLabel("Favorites")
        title.setObjectName("favoritesTitle")
        subtitle = QLabel(
            "Keep the titles you love close, even when they are not in your Library."
        )
        subtitle.setObjectName("favoritesSubtitle")
        subtitle.setWordWrap(True)
        text.addWidget(title)
        text.addWidget(subtitle)
        header_layout.addLayout(text, 1)
        refresh_button = QPushButton("Refresh")
        refresh_button.setObjectName("favoritesAction")
        refresh_button.clicked.connect(self.refresh)
        header_layout.addWidget(refresh_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.content_layout.addWidget(header)
        try:
            self._works = [dict(row) for row in get_favorite_works()]
        except Exception as error:
            log_exception("favorites.load_failed", error)
            self._works = []
            self._show_empty("Favorites could not be loaded. Refresh to try again.")
            return

        if not self._works:
            self._show_empty(
                "Open any title and press Favorite to save it here. Favorites are separate from Library membership."
            )
            return

        count = QLabel(f"{len(self._works)} favorite{'s' if len(self._works) != 1 else ''}")
        count.setObjectName("favoritesCount")
        self.content_layout.addWidget(count)
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(22)
        columns = 4
        for index, work in enumerate(self._works):
            tile = QFrame()
            tile.setObjectName("favoritesTile")
            layout = QVBoxLayout(tile)
            layout.setContentsMargins(5, 5, 5, 10)
            layout.setSpacing(8)
            card = WorkCard(work, mode="library", parent=tile)
            card.clicked.connect(self.work_selected.emit)
            layout.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
            if work.get("status"):
                status = QLabel(f"In Library · {work['status']}")
            else:
                status = QLabel("Not in Library")
            status.setObjectName("favoritesStatus")
            status.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            layout.addWidget(status)
            remove = QPushButton("Remove favorite")
            remove.setObjectName("favoritesRemove")
            remove.setAccessibleName("Remove favorite")
            remove.clicked.connect(
                lambda _=False, work_id=work.get("id"): self._remove_favorite(work_id)
            )
            layout.addWidget(remove)
            grid.addWidget(tile, index // columns, index % columns, Qt.AlignmentFlag.AlignTop)
        self.content_layout.addWidget(grid_host)
        self.content_layout.addStretch(1)
        self._apply_theme()

    def _show_empty(self, message):
        empty = QFrame()
        empty.setObjectName("favoritesEmpty")
        box = QVBoxLayout(empty)
        box.setContentsMargins(22, 22, 22, 22)
        title = QLabel("Nothing favorited yet")
        title.setObjectName("favoritesTitle")
        detail = QLabel(message)
        detail.setObjectName("favoritesSubtitle")
        detail.setWordWrap(True)
        explore = QPushButton("Explore the catalog")
        explore.setObjectName("favoritesAction")
        explore.clicked.connect(self.search_requested.emit)
        box.addWidget(title)
        box.addWidget(detail)
        box.addWidget(explore, 0, Qt.AlignmentFlag.AlignLeft)
        self.content_layout.addWidget(empty)
        self.content_layout.addStretch(1)
        self._apply_theme()

    def _remove_favorite(self, work_id):
        try:
            set_work_favorite(work_id, False)
        except Exception as error:
            log_exception("favorites.remove_failed", error, work_id=work_id)
            return
        self.refresh()

    def _clear(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def refresh_theme(self):
        self._apply_theme()
        for card in self.findChildren(WorkCard):
            card.refresh_theme()

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QWidget#favoritesContent {{ background:transparent; }}
            QScrollArea#favoritesScroll {{ background:transparent; border:none; }}
            QFrame#favoritesHeader, QFrame#favoritesEmpty {{
                background:{surface_rgba('surface')}; border:1px solid {COLORS['frame']}; border-radius:14px;
            }}
            QLabel#favoritesTitle {{
                color:{COLORS['primary']}; background:transparent; font-size:22px; font-weight:850;
            }}
            QLabel#favoritesSubtitle {{
                color:{COLORS['secondary']}; background:transparent; font-size:12px;
            }}
            QLabel#favoritesCount {{
                color:{COLORS['muted']}; background:transparent; font-size:11px; font-weight:800;
            }}
            QLabel#favoritesStatus {{
                color:{COLORS['muted']}; background:transparent; font-size:10px;
            }}
            QFrame#favoritesTile {{
                background:transparent; border:1px solid transparent; border-radius:12px;
            }}
            QFrame#favoritesTile:hover {{
                background:{surface_rgba('surface')}; border-color:{COLORS['border']};
            }}
            QPushButton#favoritesAction {{
                background:{COLORS['accent']}; color:{COLORS['accent_text']}; border:1px solid {COLORS['accent']};
                border-radius:8px; padding:9px 13px; font-weight:800;
            }}
            QPushButton#favoritesRemove {{
                background:transparent; color:{COLORS['muted']}; border:1px solid {COLORS['border']};
                border-radius:8px; padding:7px 9px; font-size:10px;
            }}
            QPushButton#favoritesRemove:hover {{
                background:{surface_rgba('accent_soft')}; color:{COLORS['primary']}; border-color:{COLORS['accent']};
            }}
        """)


__all__ = ["FavoritesPage"]
