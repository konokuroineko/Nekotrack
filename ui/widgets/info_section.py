from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from ui.theme import COLORS, SPACING
from ui.widgets.section_header import SectionHeader


class InfoSection(QFrame):

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background: {COLORS['panel']};
                border: 1px solid {COLORS['frame']};
                border-radius: 8px;
            }}
        """)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(
            SPACING['md'], SPACING['md'],
            SPACING['md'], SPACING['md']
        )
        self.layout.setSpacing(SPACING['md'])
        self.layout.addWidget(SectionHeader(title))

    def add_widget(self, widget):
        self.layout.addWidget(widget)

    def add_message(self, message):
        label = QLabel(message)
        label.setStyleSheet(f"color: {COLORS['muted']};")
        self.add_widget(label)
