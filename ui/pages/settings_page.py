from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from database import get_all_library
from ui.preferences import defaults, get, reset, set_value
from ui.theme import COLORS, SPACING, refresh_theme


class SettingsPage(QWidget):
    settings_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(0, 0)
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setMinimumSize(0, 0)
        scroll.viewport().setStyleSheet("background: transparent;")

        content = QWidget()
        content.setMinimumSize(0, 0)
        content.setObjectName("settingsContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(SPACING["xxl"], SPACING["xxl"], SPACING["xxl"], SPACING["xxl"])
        layout.setSpacing(18)

        title = QLabel("Settings")
        title.setStyleSheet(f"font-size: 30px; font-weight: 800; color: {COLORS['primary']}; background: transparent;")
        layout.addWidget(title)

        subtitle = QLabel("Make AniTrack look and behave exactly how you want.")
        subtitle.setStyleSheet(f"color: {COLORS['muted']}; background: transparent;")
        layout.addWidget(subtitle)

        layout.addWidget(self._section("Appearance", [
            self._color_row("Accent color", "The color used for highlights, selection and the cover outline.", "accent"),
            self._color_row("Accent hover", "The lighter version used while hovering accent elements.", "accent_hover"),
            self._color_row("Frame color", "Color used for artwork outlines and UI frames.", "frame_color"),
            self._color_row("Background", "Main application background.", "background"),
            self._color_row("Surface", "Panels, controls and secondary surfaces.", "surface"),
            self._color_row("Surface hover", "Background used when interactive surfaces are hovered.", "surface_hover"),
            self._color_row("Card", "Library card background.", "card"),
            self._color_row("Card hover", "Library card background while hovered.", "card_hover"),
            self._combo_row("Card size", "Poster size in the Library.", "card_size", [("Compact", 180), ("Default", 210), ("Large", 240), ("Huge", 270)]),
            self._combo_row("UI scale", "Overall text size.", "font_size", [("Small", 12), ("Default", 13), ("Large", 14), ("Very large", 15)]),
            self._combo_row("Corner radius", "How rounded panels and cards are.", "corner_radius", [("Sharp", 6), ("Soft", 10), ("Rounded", 12), ("Very rounded", 16), ("Pill-like", 20)]),
        ]))

        layout.addWidget(self._section("Behavior", [
            self._check_row("Hover highlighting", "Highlight library cards when the pointer is over them.", "hover_highlight"),
            self._check_row("Smooth resize animation", "Animate Library cards when the number of columns changes.", "resize_animation"),
            self._combo_row("Animation speed", "Duration of Library reflow animations.", "animation_speed", [("Instant", 0), ("Fast", 180), ("Default", 260), ("Smooth", 380), ("Slow", 520)]),
            self._check_row("Open maximized", "Start AniTrack maximized every time.", "maximized"),
        ]))

        layout.addWidget(self._section("Data", [
            self._info_row("Library", f"{len(list(get_all_library()))} saved titles"),
            self._info_row("Storage", "Local SQLite database"),
            self._info_row("Artwork", "Cached locally when downloaded"),
            self._info_row("Metadata", "AniList powers online search and detail import"),
        ]))

        reset_button = QPushButton("Reset all appearance & behavior settings")
        reset_button.setCursor(Qt.PointingHandCursor)
        reset_button.clicked.connect(self._reset)
        layout.addWidget(reset_button, 0, Qt.AlignLeft)
        layout.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _section(self, name, widgets):
        panel = QFrame()
        panel.setMinimumSize(0, 0)
        panel.setStyleSheet(
            f"QFrame{{background:{COLORS['surface']};border:1px solid {COLORS['frame']};border-radius:{get('corner_radius')}px;}}"
        )
        box = QVBoxLayout(panel)
        box.setContentsMargins(22, 18, 22, 12)
        box.setSpacing(0)
        heading = QLabel(name.upper())
        heading.setStyleSheet(
            f"color:{COLORS['accent']};font-size:10px;font-weight:900;letter-spacing:1.4px;padding-bottom:8px;background:transparent;"
        )
        box.addWidget(heading)
        for widget in widgets:
            box.addWidget(widget)
        return panel

    def _row(self, name, description, control):
        row = QHBoxLayout()
        row.setContentsMargins(0, 11, 0, 11)
        row.setSpacing(18)
        text = QVBoxLayout()
        text.setSpacing(2)
        label = QLabel(name)
        label.setStyleSheet(f"font-weight:700;color:{COLORS['primary']};background:transparent;")
        desc = QLabel(description)
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{COLORS['muted']};font-size:11px;background:transparent;")
        text.addWidget(label)
        text.addWidget(desc)
        row.addLayout(text, 1)
        row.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)
        wrapper = QWidget()
        wrapper.setMinimumSize(0, 0)
        wrapper.setLayout(row)
        return wrapper

    def _color_row(self, name, description, key):
        button = QPushButton()
        button.setFixedWidth(110)
        button.setCursor(Qt.PointingHandCursor)
        self._paint_color_button(button, get(key))
        button.clicked.connect(lambda: self._pick_color(key, button))
        return self._row(name, description, button)

    def _paint_color_button(self, button, value):
        button.setText(value.upper())
        button.setStyleSheet(
            f"QPushButton{{background:{value};color:#101216;border:1px solid {COLORS['border']};border-radius:9px;padding:8px 12px;font-weight:800;}}"
            f"QPushButton:hover{{border-color:{COLORS['primary']};}}"
        )

    def _pick_color(self, key, button):
        color = QColorDialog.getColor(QColor(get(key)), self, f"Choose {key.replace('_', ' ').title()}")
        if color.isValid():
            set_value(key, color.name())
            self._paint_color_button(button, color.name())
            self._apply(key)

    def _combo_row(self, name, description, key, options):
        combo = QComboBox()
        combo.setMinimumWidth(150)
        for label, value in options:
            combo.addItem(label, value)
        current = get(key)
        for i in range(combo.count()):
            if combo.itemData(i) == current:
                combo.setCurrentIndex(i)
                break
        combo.currentIndexChanged.connect(lambda i, k=key, c=combo: self._changed(k, c.itemData(i)))
        return self._row(name, description, combo)

    def _check_row(self, name, description, key):
        check = QCheckBox()
        check.setChecked(get(key))
        check.stateChanged.connect(lambda state, k=key: self._changed(k, bool(state)))
        return self._row(name, description, check)

    def _info_row(self, name, value):
        value_label = QLabel(value)
        value_label.setStyleSheet(f"color:{COLORS['secondary']};background:transparent;")
        return self._row(name, "", value_label)

    def _changed(self, key, value):
        set_value(key, value)
        self._apply(key)

    def _apply(self, key=""):
        refresh_theme()
        self.settings_changed.emit(key)

    def _reset(self):
        reset()
        for key, value in defaults().items():
            set_value(key, value)
        self._apply("reset")
