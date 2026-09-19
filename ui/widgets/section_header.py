from PySide6.QtWidgets import QLabel

from ui.theme import COLORS, FONT_SIZES


class SectionHeader(QLabel):

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['primary']};
                font-size: {FONT_SIZES['heading']}px;
                font-weight: 600;
                padding: 4px 0 8px;
                border-bottom: 1px solid {COLORS['frame']};
            }}
        """)
