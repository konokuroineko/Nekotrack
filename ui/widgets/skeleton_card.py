"""Shared Search-style loading placeholder for result cards."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QSizePolicy, QVBoxLayout

from ui.preferences import get
from ui.theme import COLORS, surface_rgba


class SkeletonCard(QFrame):
    """Fixed-size result placeholder used until a work card is ready."""

    def __init__(self, parent=None):
        super().__init__(parent)
        card_size = get("card_size")
        card_width = card_size + 8
        cover_height = round(card_size * 284 / 210)
        card_height = cover_height + 112
        self.setFixedSize(card_width, card_height)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setObjectName("skeleton")
        self.setStyleSheet(f"""
            QFrame#skeleton {{
                background: transparent;
                border: 2px solid {COLORS['frame']};
                border-radius: {get('corner_radius') + 2}px;
            }}
            QFrame#skeletonFill {{
                background: {surface_rgba('surface_hover')};
                border: 1px solid {COLORS['frame']};
                border-radius: {get('corner_radius')}px;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(8)

        cover = QFrame()
        cover.setObjectName("skeletonFill")
        cover.setFixedSize(card_size, cover_height)
        root.addWidget(cover, 0, Qt.AlignHCenter)

        title_line_1 = QFrame()
        title_line_1.setObjectName("skeletonFill")
        title_line_1.setFixedHeight(9)
        title_line_1.setFixedWidth(max(80, card_width - 26))

        title_line_2 = QFrame()
        title_line_2.setObjectName("skeletonFill")
        title_line_2.setFixedHeight(9)
        title_line_2.setFixedWidth(max(55, card_width - 70))

        meta = QFrame()
        meta.setObjectName("skeletonFill")
        meta.setFixedHeight(8)
        meta.setFixedWidth(max(70, card_width - 90))

        root.addWidget(title_line_1)
        root.addWidget(title_line_2)
        root.addWidget(meta)
        root.addStretch(1)

