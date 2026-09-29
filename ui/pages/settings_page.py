from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from database import get_all_library
from ui.preferences import (
    THEME_PRESETS,
    apply_theme_preset,
    defaults,
    get,
    reset,
    set_value,
)
from ui.theme import COLORS, SPACING, refresh_theme, retint_widget_styles


class ThemePresetCard(QFrame):
    clicked = Signal(str)

    def __init__(self, name, theme, parent=None):
        super().__init__(parent)
        self.name = name
        self.theme = theme
        self.setObjectName("themePresetCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(78)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(12)

        preview = QFrame()
        preview.setFixedSize(56, 56)
        preview.setStyleSheet(
            f"background:{theme['background']};"
            f"border:1px solid {theme['border']};"
            f"border-radius:12px;"
        )
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(7, 7, 7, 7)
        preview_layout.setSpacing(5)

        top = QFrame()
        top.setStyleSheet(
            f"background:{theme['accent']};border-radius:4px;"
        )
        preview_layout.addWidget(top, 1)

        bottom = QFrame()
        bottom.setStyleSheet(
            f"background:{theme['surface']};border-radius:4px;"
        )
        preview_layout.addWidget(bottom, 1)

        layout.addWidget(preview)

        text = QVBoxLayout()
        text.setSpacing(2)

        title = QLabel(name)
        title.setObjectName("themePresetTitle")
        description = QLabel(theme["description"])
        description.setObjectName("themePresetDescription")
        description.setWordWrap(True)

        text.addWidget(title)
        text.addWidget(description)
        text.addStretch(1)
        layout.addLayout(text, 1)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.name)
        super().mousePressEvent(event)


class SettingsPage(QWidget):
    settings_changed = Signal(str)
    setup_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(0, 0)
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(
            SPACING["xxl"],
            SPACING["xxl"],
            SPACING["xxl"],
            SPACING["xxl"],
        )
        layout.setSpacing(22)

        title = QLabel("Settings")
        title.setObjectName("settingsTitle")
        layout.addWidget(title)

        subtitle = QLabel("Personalize NekoTrack without digging through raw values.")
        subtitle.setObjectName("settingsSubtitle")
        layout.addWidget(subtitle)

        layout.addWidget(self._section(
            "Appearance",
            [
                self._theme_selector(),
                self._combo_row(
                    "Card size",
                    "Choose how large Library posters should appear.",
                    "card_size",
                    [
                        ("Compact", 180),
                        ("Default", 210),
                        ("Large", 240),
                        ("Huge", 270),
                    ],
                ),
                self._combo_row(
                    "UI scale",
                    "Adjust the overall interface text size.",
                    "font_size",
                    [
                        ("Small", 12),
                        ("Default", 13),
                        ("Large", 14),
                        ("Very large", 15),
                    ],
                ),
                self._combo_row(
                    "Corner radius",
                    "Control how rounded cards and panels are.",
                    "corner_radius",
                    [
                        ("Sharp", 6),
                        ("Soft", 10),
                        ("Rounded", 12),
                        ("Very rounded", 16),
                        ("Pill-like", 20),
                    ],
                ),
            ],
        ))

        layout.addWidget(self._section(
            "Behavior",
            [
                self._check_row(
                    "Hover highlighting",
                    "Highlight Library cards while the pointer is over them.",
                    "hover_highlight",
                ),
                self._check_row(
                    "Smooth resize animation",
                    "Animate Library reflow when the number of columns changes.",
                    "resize_animation",
                ),
                self._combo_row(
                    "Animation speed",
                    "How quickly Library reflow animations run.",
                    "animation_speed",
                    [
                        ("Instant", 0),
                        ("Fast", 180),
                        ("Default", 260),
                        ("Smooth", 380),
                        ("Slow", 520),
                    ],
                ),
                self._check_row(
                    "Open maximized",
                    "Start NekoTrack maximized.",
                    "maximized",
                ),
                self._bundle_mode_row(),
            ],
        ))

        token_input = QLineEdit()
        token_input.setEchoMode(QLineEdit.Password)
        token_input.setPlaceholderText("TMDB API Read Access Token")
        token_input.setText(str(get("tmdb_api_token") or ""))

        save_token = QPushButton("Save")
        save_token.setObjectName("settingsAction")
        save_token.clicked.connect(
            lambda: self._save_tmdb_token(token_input.text())
        )

        token_row = QHBoxLayout()
        token_row.setSpacing(10)
        token_row.addWidget(token_input, 1)
        token_row.addWidget(save_token)

        token_wrapper = QWidget()
        token_wrapper.setLayout(token_row)

        layout.addWidget(self._section(
            "TMDB",
            [
                self._row(
                    "API Read Access Token",
                    "Used for episode metadata and episode artwork. Stored locally in NekoTrack settings.",
                    token_wrapper,
                )
            ],
        ))

        data_rows = [
            self._info_row("Library", f"{len(list(get_all_library()))} saved titles"),
            self._info_row("Storage", "Local SQLite database"),
            self._info_row("Artwork", "Cached locally when downloaded"),
            self._info_row("Metadata", "AniList + TMDB"),
        ]
        layout.addWidget(self._section("Data", data_rows))

        actions = QHBoxLayout()
        setup_button = QPushButton("Run setup wizard again")
        setup_button.setObjectName("settingsAction")
        setup_button.clicked.connect(self.setup_requested.emit)

        reset_button = QPushButton("Restore defaults")
        reset_button.setObjectName("settingsSecondaryAction")
        reset_button.clicked.connect(self._reset)

        actions.addWidget(setup_button)
        actions.addWidget(reset_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        self._apply_page_style()

    def refresh_theme(self):
        self._apply_page_style()
        current = str(get("theme_preset") or "Neko")
        for name, card in getattr(self, "theme_cards", {}).items():
            card.setProperty("selected", name == current)
            card.style().unpolish(card)
            card.style().polish(card)
            card.update()

    def _apply_page_style(self):
        self.setStyleSheet(
            f"""
            QLabel#settingsTitle {{
                color:{COLORS['primary']};
                font-size:30px;
                font-weight:850;
                background:transparent;
            }}
            QLabel#settingsSubtitle {{
                color:{COLORS['muted']};
                font-size:12px;
                background:transparent;
            }}
            QFrame#settingsSection {{
                background:{COLORS['surface']};
                border:1px solid {COLORS['border']};
                border-radius:14px;
            }}
            QLabel#settingsSectionTitle {{
                color:{COLORS['accent']};
                font-size:10px;
                font-weight:900;
                letter-spacing:1.4px;
                background:transparent;
            }}
            QLabel#settingsRowTitle {{
                color:{COLORS['primary']};
                font-size:13px;
                font-weight:750;
                background:transparent;
            }}
            QLabel#settingsRowDescription {{
                color:{COLORS['muted']};
                font-size:11px;
                background:transparent;
            }}
            QFrame#themePresetCard {{
                background:{COLORS['card']};
                border:1px solid {COLORS['border']};
                border-radius:12px;
            }}
            QFrame#themePresetCard:hover {{
                background:{COLORS['card_hover']};
                border-color:{COLORS['border_hover']};
            }}
            QFrame#themePresetCard[selected="true"] {{
                background:{COLORS['accent_soft']};
                border:2px solid {COLORS['accent']};
            }}
            QLabel#themePresetTitle {{
                color:{COLORS['primary']};
                font-size:13px;
                font-weight:800;
                background:transparent;
            }}
            QLabel#themePresetDescription {{
                color:{COLORS['muted']};
                font-size:10px;
                background:transparent;
            }}
            QComboBox {{
                min-width:120px;
            }}
            QLineEdit {{
                min-height:38px;
            }}
            QPushButton#settingsAction {{
                background:{COLORS['accent']};
                border:1px solid {COLORS['accent']};
                border-radius:9px;
                color:{COLORS['accent_text']};
                font-weight:800;
                padding:9px 14px;
            }}
            QPushButton#settingsAction:hover {{
                background:{COLORS['accent_hover']};
                border-color:{COLORS['accent_hover']};
            }}
            QPushButton#settingsSecondaryAction {{
                background:{COLORS['surface_alt']};
                border:1px solid {COLORS['border']};
                border-radius:9px;
                color:{COLORS['secondary']};
                font-weight:700;
                padding:9px 14px;
            }}
            QPushButton#settingsSecondaryAction:hover {{
                background:{COLORS['surface_hover']};
                color:{COLORS['primary']};
            }}
            QCheckBox {{
                background:transparent;
            }}
            QRadioButton {{
                background:transparent;
            }}
            """
        )

    def _section(self, name, widgets):
        panel = QFrame()
        panel.setObjectName("settingsSection")

        box = QVBoxLayout(panel)
        box.setContentsMargins(20, 17, 20, 10)
        box.setSpacing(0)

        title = QLabel(name.upper())
        title.setObjectName("settingsSectionTitle")
        box.addWidget(title)

        for widget in widgets:
            box.addWidget(widget)

        return panel

    def _row(self, name, description, control):
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 10, 0, 10)
        row.setSpacing(18)

        text = QVBoxLayout()
        text.setSpacing(2)

        title = QLabel(name)
        title.setObjectName("settingsRowTitle")
        desc = QLabel(description)
        desc.setObjectName("settingsRowDescription")
        desc.setWordWrap(True)

        text.addWidget(title)
        text.addWidget(desc)
        row.addLayout(text, 1)
        row.addWidget(control, 0, Qt.AlignVCenter)
        return wrapper

    def _theme_selector(self):
        wrapper = QWidget()
        grid = QVBoxLayout(wrapper)
        grid.setContentsMargins(0, 8, 0, 8)
        grid.setSpacing(8)

        current = str(get("theme_preset") or "Neko")
        self.theme_cards = {}

        for name, theme in THEME_PRESETS.items():
            card = ThemePresetCard(name, theme)
            card.setProperty("selected", name == current)
            card.style().unpolish(card)
            card.style().polish(card)
            card.clicked.connect(self._select_theme)
            self.theme_cards[name] = card
            grid.addWidget(card)

        return wrapper

    def _select_theme(self, name):
        if name not in THEME_PRESETS:
            return

        old_name = str(get("theme_preset") or "Neko")
        apply_theme_preset(name)
        retint_widget_styles(old_name, name)

        for card_name, card in self.theme_cards.items():
            card.setProperty("selected", card_name == name)
            card.style().unpolish(card)
            card.style().polish(card)

        self._apply("theme_preset")

    def _bundle_mode_row(self):
        group = QButtonGroup(self)
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 10, 0, 10)
        row.setSpacing(12)

        main_radio = QRadioButton("Main seasons only")
        extras_radio = QRadioButton("Include related extras")
        group.addButton(main_radio)
        group.addButton(extras_radio)

        mode = str(get("bundle_mode") or "main")
        if mode == "extras":
            extras_radio.setChecked(True)
        else:
            main_radio.setChecked(True)

        main_radio.toggled.connect(
            lambda checked: checked and self._changed("bundle_mode", "main")
        )
        extras_radio.toggled.connect(
            lambda checked: checked and self._changed("bundle_mode", "extras")
        )

        info = QVBoxLayout()
        title = QLabel("Automatic bundle contents")
        title.setObjectName("settingsRowTitle")
        desc = QLabel("Choose whether automatic bundles stay focused on seasons or include related extras.")
        desc.setObjectName("settingsRowDescription")
        desc.setWordWrap(True)
        info.addWidget(title)
        info.addWidget(desc)

        row.addLayout(info, 1)
        row.addWidget(main_radio)
        row.addWidget(extras_radio)
        return wrapper

    def _combo_row(self, name, description, key, options):
        combo = QComboBox()
        for label, value in options:
            combo.addItem(label, value)

        current = get(key)
        for index in range(combo.count()):
            if combo.itemData(index) == current:
                combo.setCurrentIndex(index)
                break

        combo.currentIndexChanged.connect(
            lambda index, k=key, c=combo: self._changed(
                k,
                c.itemData(index),
            )
        )
        return self._row(name, description, combo)

    def _check_row(self, name, description, key):
        check = QCheckBox()
        check.setChecked(get(key))
        check.stateChanged.connect(
            lambda state, k=key: self._changed(k, bool(state))
        )
        return self._row(name, description, check)

    def _info_row(self, name, value):
        value_label = QLabel(value)
        value_label.setObjectName("settingsRowDescription")
        return self._row(name, "", value_label)

    def _changed(self, key, value):
        set_value(key, value)
        self._apply(key)

    def _apply(self, key=""):
        refresh_theme()
        self.settings_changed.emit(key)

    def _save_tmdb_token(self, value):
        set_value("tmdb_api_token", str(value).strip())
        self._apply("tmdb_api_token")

    def _reset(self):
        reset()
        for key, value in defaults().items():
            set_value(key, value)
        self._apply("reset")
