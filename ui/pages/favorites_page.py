"""A persistent Favorites destination for character, voice-actor, and staff profiles."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from database import get_entity_favorites, set_entity_favorite
from diagnostics import log_exception
from ui.theme import COLORS, surface_rgba


class FavoritesPage(QWidget):
    entity_selected = Signal(str, object)
    search_requested = Signal()

    def __init__(self):
        super().__init__()
        self._favorites = []
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
            "Your saved characters, voice actors, and production staff."
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
            rows = get_entity_favorites()
            self._favorites = [
                dict(row) for row in (rows or [])
                if isinstance(row, dict) or hasattr(row, "keys")
            ]
        except Exception as error:
            log_exception("favorites.entity_load_failed", error)
            self._favorites = []
            self._show_empty("Favorites could not be loaded. Refresh to try again.")
            return

        valid = []
        for row in self._favorites:
            kind = str(row.get("entity_type") or "").strip().casefold()
            if kind not in {"character", "voice_actor", "staff"}:
                continue
            try:
                entity_id = int(row.get("entity_id"))
            except (TypeError, ValueError, OverflowError):
                continue
            if entity_id <= 0:
                continue
            item = dict(row)
            item["entity_type"] = kind
            item["entity_id"] = entity_id
            item["entity_name"] = str(item.get("entity_name") or "").strip()
            valid.append(item)
        self._favorites = valid

        if not self._favorites:
            self._show_empty(
                "Open a character, voice actor, or production staff profile and use its favorite control to save it here."
            )
            return

        count = QLabel(
            f"{len(self._favorites)} saved profile{'s' if len(self._favorites) != 1 else ''}"
        )
        count.setObjectName("favoritesCount")
        self.content_layout.addWidget(count)
        grid_host = QWidget()
        grid_host.setObjectName("favoritesGridHost")
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        for column in range(3):
            grid.setColumnStretch(column, 1)

        for index, favorite in enumerate(self._favorites):
            kind = favorite["entity_type"]
            entity_id = favorite["entity_id"]
            name = favorite["entity_name"] or f"Unknown {self._kind_label(kind).lower()}"
            record = self._profile_record(favorite)
            tile = QFrame()
            tile.setObjectName("favoritesTile")
            layout = QVBoxLayout(tile)
            layout.setContentsMargins(16, 14, 16, 14)
            layout.setSpacing(9)

            type_label = QLabel(self._kind_label(kind))
            type_label.setObjectName("favoritesKind")
            layout.addWidget(type_label)

            title = QLabel(name)
            title.setObjectName("favoritesEntityName")
            title.setWordWrap(True)
            title.setToolTip(name)
            layout.addWidget(title)

            language = str(favorite.get("language") or "").strip()
            if kind == "voice_actor" and language:
                language_label = QLabel(language.replace("_", " ").replace("-", " ").title())
                language_label.setObjectName("favoritesLanguage")
                layout.addWidget(language_label)

            actions = QHBoxLayout()
            actions.setSpacing(8)
            open_button = QPushButton("Open profile")
            open_button.setObjectName("favoritesOpen")
            open_button.clicked.connect(
                lambda _checked=False, entity_kind=kind, item=record:
                    self.entity_selected.emit(entity_kind, item)
            )
            remove_button = QPushButton("Remove")
            remove_button.setObjectName("favoritesRemove")
            remove_button.setAccessibleName(f"Remove {name} from favorites")
            remove_button.clicked.connect(
                lambda _checked=False, entity_kind=kind, item_id=entity_id:
                    self._remove_favorite(entity_kind, item_id)
            )
            actions.addWidget(open_button, 1)
            actions.addWidget(remove_button)
            layout.addLayout(actions)
            grid.addWidget(tile, index // 3, index % 3, Qt.AlignmentFlag.AlignTop)

        self.content_layout.addWidget(grid_host)
        self.content_layout.addStretch(1)
        self._apply_theme()

    @staticmethod
    def _kind_label(kind):
        return {
            "character": "Character",
            "voice_actor": "Voice actor",
            "staff": "Production staff",
        }.get(kind, "Profile")

    @staticmethod
    def _profile_record(favorite):
        entity_id = int(favorite["entity_id"])
        name = str(favorite.get("entity_name") or "")
        kind = favorite["entity_type"]
        if kind == "character":
            return {"id": entity_id, "character_name": name, "name": name}
        return {
            "id": entity_id,
            "person_id": entity_id,
            "name": name,
            "language": favorite.get("language"),
        }

    def _show_empty(self, message):
        empty = QFrame()
        empty.setObjectName("favoritesEmpty")
        box = QVBoxLayout(empty)
        box.setContentsMargins(22, 22, 22, 22)
        title = QLabel("No saved profiles yet")
        title.setObjectName("favoritesTitle")
        detail = QLabel(message)
        detail.setObjectName("favoritesSubtitle")
        detail.setWordWrap(True)
        explore = QPushButton("Explore titles")
        explore.setObjectName("favoritesAction")
        explore.clicked.connect(self.search_requested.emit)
        box.addWidget(title)
        box.addWidget(detail)
        box.addWidget(explore, 0, Qt.AlignmentFlag.AlignLeft)
        self.content_layout.addWidget(empty)
        self.content_layout.addStretch(1)
        self._apply_theme()

    def _remove_favorite(self, entity_type, entity_id):
        try:
            saved = set_entity_favorite(entity_type, entity_id, False)
            if not saved:
                raise RuntimeError("The favorite state was rejected by the local database.")
        except Exception as error:
            log_exception(
                "favorites.entity_remove_failed",
                error,
                entity_type=entity_type,
                entity_id=entity_id,
            )
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

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QWidget#favoritesContent {{ background:transparent; }}
            QScrollArea#favoritesScroll {{ background:transparent; border:none; }}
            QFrame#favoritesHeader, QFrame#favoritesEmpty {{
                background:{surface_rgba('surface')}; border:1px solid {COLORS['frame']}; border-radius:14px;
            }}
            QFrame#favoritesTile {{
                background:{surface_rgba('surface')}; border:1px solid {COLORS['frame']}; border-radius:12px;
            }}
            QFrame#favoritesTile:hover {{ border-color:{COLORS['accent']}; }}
            QLabel#favoritesTitle {{
                color:{COLORS['primary']}; background:transparent; font-size:22px; font-weight:850;
            }}
            QLabel#favoritesSubtitle {{
                color:{COLORS['secondary']}; background:transparent; font-size:12px;
            }}
            QLabel#favoritesCount {{
                color:{COLORS['muted']}; background:transparent; font-size:11px; font-weight:800;
            }}
            QLabel#favoritesKind {{
                color:{COLORS['accent']}; background:transparent; font-size:10px; font-weight:850;
            }}
            QLabel#favoritesEntityName {{
                color:{COLORS['primary']}; background:transparent; font-size:15px; font-weight:800;
            }}
            QLabel#favoritesLanguage {{
                color:{COLORS['secondary']}; background:transparent; font-size:11px;
            }}
            QPushButton#favoritesAction {{
                background:{COLORS['accent']}; color:{COLORS['accent_text']}; border:1px solid {COLORS['accent']};
                border-radius:8px; padding:9px 13px; font-weight:800;
            }}
            QPushButton#favoritesAction:hover {{ background:{COLORS['accent_hover']}; }}
            QPushButton#favoritesOpen {{
                background:{surface_rgba('surface_alt')}; color:{COLORS['primary']}; border:1px solid {COLORS['border']};
                border-radius:8px; padding:8px 11px; font-weight:800;
            }}
            QPushButton#favoritesOpen:hover {{ border-color:{COLORS['accent']}; }}
            QPushButton#favoritesRemove {{
                background:transparent; color:{COLORS['secondary']}; border:1px solid {COLORS['border']};
                border-radius:8px; padding:8px 10px; font-weight:750;
            }}
            QPushButton#favoritesRemove:hover {{
                background:{surface_rgba('surface_hover')}; color:{COLORS['primary']}; border-color:{COLORS['accent']};
            }}
        """)


