from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget
from ui.theme import COLORS, SPACING


class CharacterPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING["xxl"], SPACING["xxl"], SPACING["xxl"], SPACING["xxl"])
        layout.setSpacing(SPACING["lg"])
        title = QLabel("Characters")
        title.setStyleSheet(f"font-size: 30px; font-weight: 800; color: {COLORS['primary']};")
        layout.addWidget(title)
        panel = QFrame()
        panel.setStyleSheet(f"QFrame {{ background: {COLORS['surface']}; border: 1px solid {COLORS['frame']}; border-radius: 16px; }}")
        box = QVBoxLayout(panel)
        message = QLabel("Character records imported from title details will be surfaced here.")
        message.setWordWrap(True)
        message.setAlignment(Qt.AlignCenter)
        message.setStyleSheet(f"color: {COLORS['muted']}; padding: 60px; font-size: 14px;")
        box.addWidget(message)
        layout.addWidget(panel)
        layout.addStretch()
