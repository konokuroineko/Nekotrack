import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from database import get_all_library
from ui.bundle_options import BUNDLE_OPTION_GROUPS, BUNDLE_OPTION_KEYS
from ui.preferences import (
    THEME_PRESETS,
    UI_SCALE_OPTIONS,
    apply_theme_preset,
    defaults,
    get,
    palette_for_mode,
    reset,
    set_value,
)
from ui.theme import COLORS, SPACING, refresh_theme, retint_widget_styles, surface_rgba
from ui.widgets.switch_control import SwitchControl


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
        self.preview = preview
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(7, 7, 7, 7)
        preview_layout.setSpacing(5)

        top = QFrame()
        preview_layout.addWidget(top, 1)

        bottom = QFrame()
        preview_layout.addWidget(bottom, 1)
        self.top_swatch = top
        self.bottom_swatch = bottom
        self.set_preview_mode(get("light_mode"))

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

    def set_preview_mode(self, light_mode):
        palette = palette_for_mode(self.theme, light_mode)
        self.preview.setStyleSheet(
            f"background:{palette['background']};"
            f"border:1px solid {palette['border']};border-radius:12px;"
        )
        self.top_swatch.setStyleSheet(
            f"background:{palette['accent']};border-radius:4px;"
        )
        self.bottom_swatch.setStyleSheet(
            f"background:{palette['surface']};border-radius:4px;"
        )

    def refresh_theme(self, selected=False):
        # Apply these colors directly to the card, instead of relying only on
        # the parent page's selector rules. This prevents stale custom colors
        # and dynamic-property styling from leaving a blue outline behind.
        background = COLORS["accent_soft"] if selected else COLORS["card"]
        border = (
            f"2px solid {COLORS['accent']}"
            if selected
            else f"1px solid {COLORS['frame']}"
        )
        hover_background = (
            COLORS["accent_soft"] if selected else COLORS["card_hover"]
        )
        self.setStyleSheet(
            f"""
            QFrame#themePresetCard {{
                background:{background};
                border:{border};
                border-radius:12px;
            }}
            QFrame#themePresetCard:hover {{
                background:{hover_background};
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
            """
        )
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.name)
        super().mousePressEvent(event)


class SettingsPage(QWidget):
    settings_changed = Signal(str)
    setup_requested = Signal()
    restart_requested = Signal()

    def __init__(self, background_manager=None):
        super().__init__()
        self.background_manager = background_manager
        self._active_ui_scale = self._read_active_ui_scale()
        self._ui_scale_combo = None
        self._ui_scale_restart_action = None
        self._background_list = None
        self._background_status = None
        self._background_interval = None
        self._background_overlay_slider = None
        self._background_overlay_value = None
        self.setMinimumSize(0, 0)
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget(self)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(
            SPACING["xxl"], SPACING["xxl"], SPACING["xxl"], SPACING["md"]
        )
        header_layout.setSpacing(7)
        title = QLabel("Settings")
        title.setObjectName("settingsTitle")
        subtitle = QLabel(
            "Everything that makes NekoTrack yours, organized by what it controls."
        )
        subtitle.setObjectName("settingsSubtitle")
        subtitle.setWordWrap(True)
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        outer.addWidget(header)

        self.category_tabs = QTabWidget(self)
        self.category_tabs.setObjectName("settingsTabs")
        self.category_tabs.setDocumentMode(True)
        outer.addWidget(self.category_tabs, 1)
        self._category_layouts = {}

        def add_category(name):
            tab = QWidget()
            tab.setObjectName(
                "settingsCategory_"
                + name.lower().replace(" ", "_").replace("&", "and")
            )
            tab_outer = QVBoxLayout(tab)
            tab_outer.setContentsMargins(0, 0, 0, 0)
            scroll = QScrollArea(tab)
            scroll.setObjectName("settingsCategoryScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            content = QWidget()
            content.setObjectName("settingsCategoryContent")
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(
                SPACING["xxl"], SPACING["lg"], SPACING["xxl"], SPACING["xxl"]
            )
            content_layout.setSpacing(18)
            scroll.setWidget(content)
            tab_outer.addWidget(scroll)
            self.category_tabs.addTab(tab, name)
            self._category_layouts[name] = content_layout
            return content_layout

        general = add_category("General")
        appearance = add_category("Appearance")
        library = add_category("Library")
        discovery = add_category("Discovery")
        integrations = add_category("Integrations")
        data_storage = add_category("Data & Storage")
        advanced = add_category("Advanced")

        general.addWidget(self._section(
            "Startup",
            [
                self._check_row(
                    "Open maximized",
                    "Start NekoTrack maximized.",
                    "maximized",
                ),
            ],
        ))

        appearance.addWidget(self._section(
            "Theme",
            [
                self._theme_selector(),
                self._check_row(
                    "White mode",
                    "Use light surfaces while keeping your selected theme and accent color.",
                    "light_mode",
                ),
            ],
        ))
        appearance.addWidget(self._section(
            "Interface scale",
            [
                self._combo_row(
                    "UI scale",
                    "Choose a scale for the whole interface. Restart to apply it.",
                    "ui_scale",
                    [
                        (
                            f"{scale}%",
                            scale,
                        )
                        for scale in UI_SCALE_OPTIONS
                    ],
                ),
                self._scale_restart_action(),
            ],
        ))
        appearance.addWidget(self._section(
            "Cards and surfaces",
            [
                self._combo_row(
                    "Card size",
                    "Choose how large posters appear in Library, Search, and Recommendations.",
                    "card_size",
                    [
                        ("Compact", 180),
                        ("Default", 210),
                        ("Large", 240),
                        ("Huge", 270),
                    ],
                ),
                self._combo_row(
                    "Interface text size",
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

        appearance.addWidget(self._section(
            "Background image",
            [self._background_options_widget()],
        ))

        library.addWidget(self._section(
            "Card behavior",
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
            ],
        ))
        library.addWidget(self._section(
            "Bundling",
            [self._bundle_options_row()],
        ))
        discovery.addWidget(self._section(
            "Recommendations",
            [
                self._combo_row(
                    "Voice-actor language",
                    "Choose which voice performances influence recommendations. Production staff remain language-neutral.",
                    "recommendation_voice_language",
                    [
                        ("Japanese audio / sub", "JA"),
                        ("English dub", "EN"),
                        ("All voice languages / no preference", "ALL"),
                    ],
                ),
            ],
        ))

        token_input = QLineEdit()
        token_input.setEchoMode(QLineEdit.EchoMode.Password)
        token_input.setPlaceholderText("TMDB API Read Access Token")
        token_input.setText(str(get("tmdb_api_token") or ""))
        token_input.setAccessibleName("TMDB API Read Access Token")

        save_token = QPushButton("Save token")
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
        integrations.addWidget(self._section(
            "TMDB episode metadata",
            [
                self._row(
                    "API Read Access Token",
                    "Used for episode metadata and episode artwork. Stored locally in NekoTrack settings.",
                    token_wrapper,
                ),
            ],
        ))

        data_rows = [
            self._info_row("Library", f"{len(list(get_all_library()))} saved titles"),
            self._info_row("Database", "Local SQLite · anime_tracker.db"),
            self._info_row("Artwork", "Cached on this device when downloaded"),
            self._info_row("Catalog metadata", "AniList + MangaBaka + TMDB"),
        ]
        data_storage.addWidget(self._section("Local data", data_rows))

        setup_button = QPushButton("Run setup wizard again")
        setup_button.setObjectName("settingsAction")
        setup_button.clicked.connect(self.setup_requested.emit)
        reset_button = QPushButton("Restore defaults")
        reset_button.setObjectName("settingsSecondaryAction")
        reset_button.clicked.connect(self._reset)
        advanced.addWidget(self._section(
            "Application",
            [
                self._row(
                    "Setup",
                    "Reopen first-run configuration without deleting your library.",
                    setup_button,
                ),
                self._row(
                    "Preferences",
                    "Reset preferences to their defaults. Your saved library and progress are kept.",
                    reset_button,
                ),
            ],
        ))

        for category_layout in self._category_layouts.values():
            category_layout.addStretch(1)

        self.refresh_theme()

    def _background_options_widget(self):
        wrapper = QWidget(self)
        wrapper.setObjectName("backgroundOptions")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        if self.background_manager is None:
            note = QLabel("Background customization is unavailable in this view.")
            note.setObjectName("backgroundStatus")
            note.setWordWrap(True)
            layout.addWidget(note)
            return wrapper

        intro = QLabel(
            "Choose local artwork. NekoTrack stores a validated copy in its own user-data folder."
        )
        intro.setObjectName("backgroundIntro")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._background_list = QListWidget()
        self._background_list.setObjectName("backgroundImageList")
        self._background_list.setMinimumHeight(78)
        self._background_list.setMaximumHeight(135)
        self._background_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._background_list.setAccessibleName("Selected background images")
        layout.addWidget(self._background_list)

        image_actions = QHBoxLayout()
        add_button = QPushButton("Add images…")
        add_button.setObjectName("backgroundAddImages")
        add_button.clicked.connect(self._choose_background_images)
        remove_button = QPushButton("Remove selected")
        remove_button.setObjectName("backgroundRemoveImage")
        remove_button.clicked.connect(self._remove_selected_background)
        image_actions.addWidget(add_button)
        image_actions.addWidget(remove_button)
        image_actions.addStretch(1)
        layout.addLayout(image_actions)

        timing_row = QHBoxLayout()
        timing_label = QLabel("Background behavior")
        timing_label.setObjectName("backgroundControlLabel")
        self._background_interval = QComboBox()
        self._background_interval.setObjectName("backgroundInterval")
        self._background_interval.setAccessibleName("Background slideshow interval")
        for label, value in (
            ("Off", -1), ("Static image", 0), ("Every 30 seconds", 30),
            ("Every 1 minute", 60), ("Every 5 minutes", 300),
            ("Every 15 minutes", 900), ("Every 30 minutes", 1800),
        ):
            self._background_interval.addItem(label, value)
        current = self._background_interval.findData(self.background_manager.interval)
        self._background_interval.setCurrentIndex(current if current >= 0 else 0)
        self._background_interval.currentIndexChanged.connect(
            lambda index: self.background_manager.set_interval(
                self._background_interval.itemData(index)
            )
        )
        timing_row.addWidget(timing_label)
        timing_row.addWidget(self._background_interval, 1)
        layout.addLayout(timing_row)

        overlay_row = QHBoxLayout()
        overlay_label = QLabel("Contrast overlay")
        overlay_label.setObjectName("backgroundControlLabel")
        self._background_overlay_slider = QSlider(Qt.Orientation.Horizontal)
        self._background_overlay_slider.setObjectName("backgroundOverlay")
        self._background_overlay_slider.setRange(35, 90)
        self._background_overlay_slider.setValue(self.background_manager.overlay_opacity)
        self._background_overlay_slider.setAccessibleName("Background contrast overlay percentage")
        self._background_overlay_value = QLabel(f"{self.background_manager.overlay_opacity}%")
        self._background_overlay_value.setObjectName("backgroundOverlayValue")
        self._background_overlay_slider.valueChanged.connect(self._background_overlay_changed)
        overlay_row.addWidget(overlay_label)
        overlay_row.addWidget(self._background_overlay_slider, 1)
        overlay_row.addWidget(self._background_overlay_value)
        layout.addLayout(overlay_row)

        self._background_status = QLabel()
        self._background_status.setObjectName("backgroundStatus")
        self._background_status.setWordWrap(True)
        layout.addWidget(self._background_status)
        self.background_manager.images_changed.connect(self._refresh_background_list)
        self._refresh_background_list()
        return wrapper

    def _refresh_background_list(self):
        if self._background_list is None or self.background_manager is None:
            return
        selected = self.background_manager.selected_path
        self._background_list.clear()
        selected_row = -1
        for index, path in enumerate(self.background_manager.paths):
            item = QListWidgetItem(Path(path).name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self._background_list.addItem(item)
            if path == selected:
                selected_row = index
        if selected_row >= 0:
            self._background_list.setCurrentRow(selected_row)

    def _choose_background_images(self):
        if self.background_manager is None:
            return
        paths, _filter = QFileDialog.getOpenFileNames(
            self, "Choose background images", "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not paths:
            return
        added = self.background_manager.add_images(paths)
        self._refresh_background_list()
        if self._background_status is not None:
            if self.background_manager.last_errors:
                self._background_status.setText(
                    f"Added {added} image(s). {len(self.background_manager.last_errors)} file(s) were skipped; "
                    "use a readable PNG, JPG, WEBP, or BMP up to 20 MiB."
                )
            elif added:
                self._background_status.setText(f"Added {added} image(s) to NekoTrack's background collection.")
            else:
                self._background_status.setText("Nothing new was added; these images may already be selected.")

    def _remove_selected_background(self):
        if self.background_manager is None or self._background_list is None:
            return
        item = self._background_list.currentItem()
        if item is None:
            if self._background_status is not None:
                self._background_status.setText("Select an image to remove it.")
            return
        removed = self.background_manager.remove_image(item.data(Qt.ItemDataRole.UserRole))
        if self._background_status is not None:
            self._background_status.setText(
                "Background image removed." if removed else "The background image could not be removed."
            )

    def _background_overlay_changed(self, value):
        if self._background_overlay_value is not None:
            self._background_overlay_value.setText(f"{int(value)}%")
        if self.background_manager is not None:
            self.background_manager.set_overlay_opacity(value)

    def refresh_theme(self):
        self._apply_page_style()
        current = str(get("theme_preset") or "Neko")
        for name, card in getattr(self, "theme_cards", {}).items():
            selected = name == current
            card.setProperty("selected", selected)
            card.set_preview_mode(get("light_mode"))
            card.refresh_theme(selected)

        # Give section headers and action buttons explicit theme colors. These
        # were previously inherited from the page stylesheet, which could
        # retain the old custom accent color after a preset switch.
        for label in self.findChildren(QLabel):
            if label.objectName() == "settingsSectionTitle":
                label.setStyleSheet(
                    f"color:{COLORS['accent']};font-size:10px;"
                    "font-weight:900;letter-spacing:1.4px;"
                    "background:transparent;"
                )

        for button in self.findChildren(QPushButton):
            if button.objectName() == "settingsAction":
                button.setStyleSheet(
                    f"""
                    QPushButton#settingsAction {{
                        background:{COLORS['accent']};
                        border:1px solid {COLORS['accent']};
                        border-radius:9px;
                        color:{COLORS['accent_text']};
                        font-weight:800;
                        padding:9px 14px;
                        min-height:38px;
                    }}
                    QPushButton#settingsAction:hover {{
                        background:{COLORS['accent_hover']};
                        border-color:{COLORS['accent_hover']};
                    }}
                    """
                )
            elif button.objectName() == "settingsSecondaryAction":
                button.setStyleSheet(
                    f"""
                    QPushButton#settingsSecondaryAction {{
                        background:{surface_rgba('surface_alt')};
                        border:1px solid {COLORS['frame']};
                        border-radius:9px;
                        color:{COLORS['secondary']};
                        font-weight:700;
                        padding:9px 14px;
                        min-height:38px;
                    }}
                    QPushButton#settingsSecondaryAction:hover {{
                        background:{surface_rgba('surface_hover')};
                        color:{COLORS['primary']};
                    }}
                    """
                )

        # Re-polish the updated widgets so Qt discards cached style metrics and
        # colors immediately, not just the next time the page is recreated.
        for widget in self.findChildren(QWidget):
            style = widget.style()
            style.unpolish(widget)
            style.polish(widget)
            widget.update()

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
                background:{surface_rgba('surface')};
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
                background:{surface_rgba('card')};
                border:1px solid {COLORS['frame']};
                border-radius:12px;
            }}
            QFrame#themePresetCard:hover {{
                background:{surface_rgba('card_hover')};
                border-color:{COLORS['accent']};
            }}
            QFrame#themePresetCard[selected="true"] {{
                background:{surface_rgba('accent_soft')};
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
            QFrame#bundleSettingOption {{
                background:{surface_rgba('card')};
                border:1px solid {COLORS['border']};
                border-radius:10px;
            }}
            QFrame#bundleSettingOption:hover {{
                background:{surface_rgba('card_hover')};
                border-color:{COLORS['accent']};
            }}
            QFrame#bundleAlwaysOn {{
                background:{surface_rgba('accent_soft')};
                border:1px solid {COLORS['border_hover']};
                border-radius:9px;
            }}
            QLabel#bundleAlwaysTitle {{
                color:{COLORS['primary']};
                font-size:12px;
                font-weight:800;
                background:transparent;
            }}
            QLabel#bundleAlwaysDetail {{
                color:{COLORS['accent']};
                font-size:12px;
                font-weight:800;
                background:transparent;
            }}
            QLabel#bundleGroupLabel {{
                color:{COLORS['accent']};
                font-size:10px;
                font-weight:900;
                letter-spacing:1.3px;
                padding-top:4px;
                background:transparent;
            }}
            QCheckBox#bundleOptionCheck {{
                color:{COLORS['primary']};
                font-size:12px;
                font-weight:800;
                spacing:8px;
                background:transparent;
            }}
            QLabel#bundleOptionDescription {{
                color:{COLORS['muted']};
                font-size:10px;
                background:transparent;
            }}
            QTabWidget#settingsTabs::pane {{
                background:transparent;
                border:1px solid {COLORS['border']};
                border-radius:12px;
                top:-1px;
            }}
            QTabBar::tab {{
                background:{surface_rgba('surface_alt')};
                color:{COLORS['secondary']};
                border:1px solid {COLORS['border']};
                border-bottom:none;
                border-top-left-radius:9px;
                border-top-right-radius:9px;
                padding:10px 14px;
                margin-right:4px;
                font-size:11px;
                font-weight:750;
            }}
            QTabBar::tab:selected {{
                background:{surface_rgba('accent_soft')};
                color:{COLORS['nav_selected_text']};
                border-color:{COLORS['accent']};
            }}
            QTabBar::tab:hover:!selected {{
                background:{surface_rgba('surface_hover')};
                color:{COLORS['primary']};
            }}
            QTabWidget#settingsTabs QScrollArea#settingsCategoryScroll {{
                background:transparent;
                border:none;
            }}
            QListWidget#backgroundImageList {{
                background:{surface_rgba('surface_alt')};
                color:{COLORS['primary']};
                border:1px solid {COLORS['border']};
                border-radius:9px;
                padding:4px;
            }}
            QListWidget#backgroundImageList::item {{ padding:6px 8px; border-radius:6px; }}
            QListWidget#backgroundImageList::item:selected {{
                background:{surface_rgba('accent_soft')}; color:{COLORS['nav_selected_text']};
            }}
            QLabel#backgroundIntro, QLabel#backgroundStatus {{
                color:{COLORS['muted']}; background:transparent; font-size:11px;
            }}
            QLabel#backgroundControlLabel {{
                color:{COLORS['secondary']}; background:transparent; font-size:11px; font-weight:700;
            }}
            QLabel#backgroundOverlayValue {{
                color:{COLORS['accent']}; background:transparent; font-size:11px; font-weight:800; min-width:34px;
            }}
            QComboBox {{
                min-width:120px;
            }}
            QLabel#uiScaleRestartLabel {{
                color:{COLORS['secondary']}; background:transparent; font-size:11px;
            }}
            QPushButton#uiScaleRestartButton {{
                background:{COLORS['accent']}; border:1px solid {COLORS['accent']};
                border-radius:9px; color:{COLORS['accent_text']}; font-weight:800; padding:8px 14px;
            }}
            QPushButton#uiScaleRestartButton:hover {{
                background:{COLORS['accent_hover']}; border-color:{COLORS['accent_hover']};
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
                background:{surface_rgba('surface_alt')};
                border:1px solid {COLORS['border']};
                border-radius:9px;
                color:{COLORS['secondary']};
                font-weight:700;
                padding:9px 14px;
            }}
            QPushButton#settingsSecondaryAction:hover {{
                background:{surface_rgba('surface_hover')};
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

    def _bundle_options_row(self):
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 14, 0, 14)
        layout.setSpacing(9)

        title = QLabel("Automatic bundle contents")
        title.setObjectName("settingsRowTitle")
        description = QLabel(
            "TV seasons and TV Shorts are always grouped. Choose exactly which related formats may join them."
        )
        description.setObjectName("settingsRowDescription")
        description.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(description)

        always = QFrame()
        always.setObjectName("bundleAlwaysOn")
        always_layout = QHBoxLayout(always)
        always_layout.setContentsMargins(12, 9, 12, 9)
        always_title = QLabel("Always included")
        always_title.setObjectName("bundleAlwaysTitle")
        always_detail = QLabel("TV seasons + TV Shorts")
        always_detail.setObjectName("bundleAlwaysDetail")
        always_layout.addWidget(always_title)
        always_layout.addStretch(1)
        always_layout.addWidget(always_detail)
        layout.addWidget(always)

        self.bundle_checkboxes = {}
        for group_title, options in BUNDLE_OPTION_GROUPS:
            group_label = QLabel(group_title)
            group_label.setObjectName("bundleGroupLabel")
            layout.addWidget(group_label)

            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(10)

            for index, (key, label, detail) in enumerate(options):
                card = QFrame()
                card.setObjectName("bundleSettingOption")
                card_layout = QVBoxLayout(card)
                card_layout.setContentsMargins(12, 10, 12, 10)
                card_layout.setSpacing(5)

                checkbox = QCheckBox(label)
                checkbox.setObjectName("bundleOptionCheck")
                checkbox.setChecked(get(key))
                checkbox.toggled.connect(
                    lambda enabled, option_key=key: self._changed(
                        option_key, bool(enabled)
                    )
                )
                self.bundle_checkboxes[key] = checkbox

                detail_label = QLabel(detail)
                detail_label.setObjectName("bundleOptionDescription")
                detail_label.setWordWrap(True)
                card_layout.addWidget(checkbox)
                card_layout.addWidget(detail_label)
                grid.addWidget(card, index // 2, index % 2)

            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            layout.addLayout(grid)

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
        if key == "ui_scale":
            combo.setObjectName("uiScaleCombo")
            self._ui_scale_combo = combo
            combo.currentIndexChanged.connect(self._update_ui_scale_restart_visibility)
        return self._row(name, description, combo)

    @staticmethod
    def _read_active_ui_scale():
        """Read the scale factor applied before QApplication was created."""
        configured = get("ui_scale")
        factor_text = os.environ.get("QT_SCALE_FACTOR")
        if factor_text is None:
            return configured
        try:
            active = int(round(float(factor_text) * 100))
        except (TypeError, ValueError, OverflowError):
            return configured
        return active if active in UI_SCALE_OPTIONS else configured

    def _scale_restart_action(self):
        wrapper = QWidget()
        wrapper.setObjectName("uiScaleRestartAction")
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(12)

        note = QLabel("Your scale choice is saved. Restart now to apply it.")
        note.setObjectName("uiScaleRestartLabel")
        note.setWordWrap(True)
        layout.addWidget(note, 1)

        button = QPushButton("Restart now")
        button.setObjectName("uiScaleRestartButton")
        button.setAccessibleName("Restart NekoTrack to apply UI scale")
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(lambda checked=False: self.restart_requested.emit())
        layout.addWidget(button)

        wrapper.setVisible(False)
        self._ui_scale_restart_action = wrapper
        self._update_ui_scale_restart_visibility()
        return wrapper

    def _update_ui_scale_restart_visibility(self, _index=None):
        if self._ui_scale_combo is None or self._ui_scale_restart_action is None:
            return
        selected = self._ui_scale_combo.currentData()
        self._ui_scale_restart_action.setVisible(selected != self._active_ui_scale)

    def _check_row(self, name, description, key):
        check = SwitchControl()
        check.setAccessibleName(name)
        check.setToolTip(description)
        check.setChecked(get(key))
        if key == "light_mode":
            check.setObjectName("lightModeToggle")
            check.toggled.connect(self._set_light_mode)
        else:
            check.toggled.connect(
                lambda checked, k=key: self._changed(k, bool(checked))
            )
        return self._row(name, description, check)

    def _set_light_mode(self, enabled):
        old_mode = bool(get("light_mode"))
        new_mode = bool(enabled)
        if old_mode == new_mode:
            return
        theme_name = str(get("theme_preset") or "Neko")
        set_value("light_mode", new_mode)
        retint_widget_styles(
            theme_name,
            theme_name,
            old_light_mode=old_mode,
            new_light_mode=new_mode,
        )
        self._apply("light_mode")

    def _info_row(self, name, value):
        value_label = QLabel(value)
        value_label.setObjectName("settingsRowDescription")
        return self._row(name, "", value_label)

    def _changed(self, key, value):
        set_value(key, value)
        if key in BUNDLE_OPTION_KEYS:
            set_value(
                "bundle_mode",
                "extras" if all(get(option_key) for option_key in BUNDLE_OPTION_KEYS) else "main",
            )
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
