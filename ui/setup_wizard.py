import requests

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.preferences import (
    THEME_PRESETS,
    apply_theme_preset,
    get,
    set_value,
)


class ThemeCard(QFrame):
    clicked = Signal(str)

    def __init__(self, name, theme_data, parent=None):
        super().__init__(parent)
        self.name = name
        self.theme_data = theme_data
        self.setObjectName("themeCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(190, 125)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 13, 14, 13)
        layout.setSpacing(8)

        swatches = QHBoxLayout()
        swatches.setSpacing(5)
        for key in ("accent", "surface", "card", "background"):
            swatch = QFrame()
            swatch.setFixedHeight(24)
            swatch.setStyleSheet(
                f"background:{theme_data[key]};border-radius:6px;"
                f"border:1px solid {theme_data['border']};"
            )
            swatches.addWidget(swatch, 1)
        layout.addLayout(swatches)

        title = QLabel(name)
        title.setObjectName("themeTitle")
        layout.addWidget(title)

        description = QLabel(theme_data["description"])
        description.setObjectName("themeDescription")
        description.setWordWrap(True)
        layout.addWidget(description)
        layout.addStretch(1)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.name)
        super().mousePressEvent(event)


class TMDBTestWorker(QObject):
    finished = Signal(bool, str)

    def __init__(self, token):
        super().__init__()
        self.token = token

    def run(self):
        try:
            response = requests.get(
                "https://api.themoviedb.org/3/configuration",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "accept": "application/json",
                },
                timeout=10,
            )
            response.raise_for_status()
            self.finished.emit(True, "TMDB connection successful.")
        except requests.RequestException as error:
            detail = str(error).strip() or "The request failed."
            self.finished.emit(False, f"TMDB connection failed: {detail}")


class SetupWizard(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NekoTrack Setup")
        self.setModal(True)
        self.setMinimumSize(900, 620)
        self.resize(980, 650)

        self.selected_theme = str(get("theme_preset") or "NekoTrack")
        if self.selected_theme not in THEME_PRESETS:
            self.selected_theme = "NekoTrack"
        self.bundle_mode = str(get("bundle_mode") or "main")
        if self.bundle_mode not in {"main", "extras"}:
            self.bundle_mode = "main"

        self._tmdb_thread = None
        self._tmdb_worker = None
        self._build()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("setupSidebar")
        sidebar.setFixedWidth(250)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(25, 28, 22, 28)
        side.setSpacing(4)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(9)
        mark = QLabel("N")
        mark.setObjectName("setupMark")
        brand = QLabel("NekoTrack")
        brand.setObjectName("setupBrand")
        brand_row.addWidget(mark)
        brand_row.addWidget(brand)
        brand_row.addStretch(1)
        side.addLayout(brand_row)
        side.addSpacing(42)

        side_intro = QLabel("SETUP")
        side_intro.setObjectName("setupOverline")
        side.addWidget(side_intro)

        self.step_labels = []
        for number, title in (
            ("01", "Welcome"),
            ("02", "Theme"),
            ("03", "Bundling"),
            ("04", "TMDB"),
        ):
            label = QLabel(f"{number}   {title}")
            label.setProperty("setupStep", True)
            self.step_labels.append(label)
            side.addWidget(label)
            side.addSpacing(5)

        side.addStretch(1)
        footer = QLabel("NekoTrack v1 setup")
        footer.setObjectName("setupFooter")
        side.addWidget(footer)

        content = QFrame()
        content.setObjectName("setupContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(42, 35, 42, 30)
        content_layout.setSpacing(0)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._welcome_page())
        self.pages.addWidget(self._theme_page())
        self.pages.addWidget(self._bundle_page())
        self.pages.addWidget(self._tmdb_page())
        content_layout.addWidget(self.pages, 1)

        nav = QHBoxLayout()
        nav.setContentsMargins(0, 24, 0, 0)
        nav.setSpacing(9)
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self._back)
        self.back_button.setVisible(False)
        nav.addWidget(self.back_button)
        nav.addStretch(1)

        self.next_button = QPushButton("Continue")
        self.next_button.setObjectName("setupPrimary")
        self.next_button.clicked.connect(self._next)
        nav.addWidget(self.next_button)

        content_layout.addLayout(nav)

        root.addWidget(sidebar)
        root.addWidget(content, 1)

        self._apply_wizard_style()
        self._set_step(0)

    def _heading(self, title, subtitle):
        title_label = QLabel(title)
        title_label.setObjectName("setupHeading")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("setupSubtitle")
        subtitle_label.setWordWrap(True)
        return title_label, subtitle_label

    def _welcome_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 20, 4, 10)
        layout.setSpacing(14)

        title, subtitle = self._heading(
            "Welcome to NekoTrack",
            "A few choices now, then NekoTrack is ready to use.",
        )
        layout.addWidget(title)
        layout.addWidget(subtitle)

        panel = QFrame()
        panel.setObjectName("setupFeaturePanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(24, 22, 24, 22)
        panel_layout.setSpacing(14)

        for heading, text in (
            (
                "AniList",
                "Search, canonical metadata, characters, staff and series relationships.",
            ),
            (
                "TMDB",
                "Episode metadata and episode artwork, stored locally after download.",
            ),
            (
                "Your library",
                "Your existing library stays where it is. This setup only saves preferences.",
            ),
        ):
            row = QVBoxLayout()
            row.setSpacing(3)
            item_heading = QLabel(heading)
            item_heading.setObjectName("setupFeatureHeading")
            item_text = QLabel(text)
            item_text.setObjectName("setupFeatureText")
            item_text.setWordWrap(True)
            row.addWidget(item_heading)
            row.addWidget(item_text)
            panel_layout.addLayout(row)

        layout.addWidget(panel)
        layout.addStretch(1)
        return page

    def _theme_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 20, 4, 10)
        layout.setSpacing(14)

        title, subtitle = self._heading(
            "Pick your look",
            "Choose a preset now. You can change it later in Settings.",
        )
        layout.addWidget(title)
        layout.addWidget(subtitle)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        self.theme_cards = {}
        names = list(THEME_PRESETS)
        for index, name in enumerate(names):
            card = ThemeCard(name, THEME_PRESETS[name])
            card.clicked.connect(self._select_theme)
            self.theme_cards[name] = card
            grid.addWidget(card, index // 2, index % 2)

        layout.addLayout(grid)
        layout.addStretch(1)
        return page

    def _bundle_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 20, 4, 10)
        layout.setSpacing(14)

        title, subtitle = self._heading(
            "How should bundles work?",
            "This only controls automatic bundling. You can still manually bundle anything later.",
        )
        layout.addWidget(title)
        layout.addWidget(subtitle)

        group = QButtonGroup(self)
        options = (
            (
                "main",
                "Main seasons only",
                "Automatically group the main TV / TV Short season chain. Extras such as Break Time, OVAs and specials stay separate.",
            ),
            (
                "extras",
                "Include related extras",
                "Also automatically group related extras when NekoTrack can identify them as part of the same series family.",
            ),
        )
        for value, heading, description in options:
            card = QFrame()
            card.setObjectName("bundleOption")
            row = QHBoxLayout(card)
            row.setContentsMargins(16, 14, 16, 14)
            row.setSpacing(12)

            radio = QRadioButton()
            radio.setProperty("bundleValue", value)
            radio.toggled.connect(lambda checked, v=value: self._bundle_toggled(v, checked))
            group.addButton(radio)
            row.addWidget(radio, 0, Qt.AlignTop)

            text_box = QVBoxLayout()
            text_box.setSpacing(3)
            heading_label = QLabel(heading)
            heading_label.setObjectName("bundleHeading")
            description_label = QLabel(description)
            description_label.setObjectName("bundleDescription")
            description_label.setWordWrap(True)
            text_box.addWidget(heading_label)
            text_box.addWidget(description_label)
            row.addLayout(text_box, 1)

            layout.addWidget(card)
            if value == self.bundle_mode:
                radio.setChecked(True)

        layout.addStretch(1)
        return page

    def _tmdb_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 20, 4, 10)
        layout.setSpacing(14)

        title, subtitle = self._heading(
            "Connect TMDB",
            "NekoTrack uses a TMDB API Read Access Token for episode data and episode artwork.",
        )
        layout.addWidget(title)
        layout.addWidget(subtitle)

        panel = QFrame()
        panel.setObjectName("setupFeaturePanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(20, 20, 20, 20)
        panel_layout.setSpacing(10)

        token_label = QLabel("API Read Access Token")
        token_label.setObjectName("setupFeatureHeading")
        panel_layout.addWidget(token_label)

        self.tmdb_token = QLineEdit()
        self.tmdb_token.setEchoMode(QLineEdit.Password)
        self.tmdb_token.setPlaceholderText("Paste your TMDB v4 API Read Access Token")
        self.tmdb_token.setText(str(get("tmdb_api_token") or ""))
        panel_layout.addWidget(self.tmdb_token)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.test_button = QPushButton("Test connection")
        self.test_button.clicked.connect(self._test_tmdb)
        actions.addWidget(self.test_button)
        panel_layout.addLayout(actions)

        self.tmdb_status = QLabel("You can skip this for now and add the token later in Settings.")
        self.tmdb_status.setObjectName("setupStatus")
        self.tmdb_status.setWordWrap(True)
        panel_layout.addWidget(self.tmdb_status)

        layout.addWidget(panel)
        layout.addStretch(1)
        return page

    def _bundle_toggled(self, value, checked):
        if checked:
            self.bundle_mode = value

    def _select_theme(self, name):
        self.selected_theme = name
        for card_name, card in self.theme_cards.items():
            card.setProperty("selected", card_name == name)
            card.style().unpolish(card)
            card.style().polish(card)
        self._apply_wizard_style()

    def _set_step(self, index):
        self.pages.setCurrentIndex(index)
        self.back_button.setVisible(index > 0)
        self.next_button.setText("Finish setup" if index == self.pages.count() - 1 else "Continue")
        for position, label in enumerate(self.step_labels):
            label.setProperty("active", position == index)
            label.style().unpolish(label)
            label.style().polish(label)

    def _back(self):
        index = max(0, self.pages.currentIndex() - 1)
        self._set_step(index)

    def _next(self):
        index = self.pages.currentIndex()
        if index == self.pages.count() - 1:
            self._finish()
            return
        self._set_step(index + 1)

    def _finish(self):
        apply_theme_preset(self.selected_theme)
        set_value("bundle_mode", self.bundle_mode)
        set_value("tmdb_api_token", self.tmdb_token.text().strip())
        set_value("setup_complete", True)
        self.accept()

    def _test_tmdb(self):
        token = self.tmdb_token.text().strip()
        if not token:
            self.tmdb_status.setText("Enter a token first.")
            return

        self.test_button.setEnabled(False)
        self.tmdb_status.setText("Testing TMDB connection…")

        self._tmdb_thread = QThread(self)
        self._tmdb_worker = TMDBTestWorker(token)
        self._tmdb_worker.moveToThread(self._tmdb_thread)
        self._tmdb_thread.started.connect(self._tmdb_worker.run)
        self._tmdb_worker.finished.connect(self._tmdb_result)
        self._tmdb_worker.finished.connect(self._tmdb_thread.quit)
        self._tmdb_thread.finished.connect(self._tmdb_worker.deleteLater)
        self._tmdb_thread.finished.connect(self._tmdb_thread_finished)
        self._tmdb_thread.start()

    def _tmdb_result(self, success, message):
        self.tmdb_status.setText(message)
        self.tmdb_status.setProperty("success", bool(success))
        self.tmdb_status.style().unpolish(self.tmdb_status)
        self.tmdb_status.style().polish(self.tmdb_status)

    def _tmdb_thread_finished(self):
        self.test_button.setEnabled(True)
        if self._tmdb_thread is not None:
            self._tmdb_thread.deleteLater()
        self._tmdb_thread = None
        self._tmdb_worker = None

    def _apply_wizard_style(self):
        theme = THEME_PRESETS[self.selected_theme]
        self.setStyleSheet(
            f"""
            QDialog {{
                background:{theme['background']};
                color:{theme['primary']};
            }}
            QFrame#setupSidebar {{
                background:{theme['sidebar']};
                border-right:1px solid {theme['border']};
            }}
            QFrame#setupContent {{
                background:{theme['background']};
            }}
            QLabel {{
                background:transparent;
                color:{theme['primary']};
                font-family:"Segoe UI";
            }}
            QLabel#setupMark {{
                background:{theme['accent']};
                color:#111318;
                border-radius:9px;
                min-width:38px;
                max-width:38px;
                min-height:38px;
                max-height:38px;
                font-size:19px;
                font-weight:900;
                qproperty-alignment:AlignCenter;
            }}
            QLabel#setupBrand {{
                font-size:19px;
                font-weight:800;
                padding-left:3px;
            }}
            QLabel#setupOverline {{
                color:{theme['muted']};
                font-size:10px;
                font-weight:900;
                letter-spacing:1.5px;
                padding-left:4px;
            }}
            QLabel[setupStep="true"] {{
                color:{theme['muted']};
                border-radius:9px;
                padding:10px 10px;
                font-size:12px;
                font-weight:700;
            }}
            QLabel[setupStep="true"][active="true"] {{
                background:{theme['accent_soft']};
                color:{theme['accent_hover']};
            }}
            QLabel#setupFooter {{
                color:{theme['muted']};
                font-size:10px;
                padding-left:4px;
            }}
            QLabel#setupHeading {{
                color:{theme['primary']};
                font-size:31px;
                font-weight:850;
            }}
            QLabel#setupSubtitle {{
                color:{theme['secondary']};
                font-size:13px;
                line-height:1.4;
            }}
            QFrame#setupFeaturePanel, QFrame#bundleOption {{
                background:{theme['surface']};
                border:1px solid {theme['border']};
                border-radius:14px;
            }}
            QLabel#setupFeatureHeading, QLabel#bundleHeading {{
                color:{theme['primary']};
                font-size:14px;
                font-weight:800;
            }}
            QLabel#setupFeatureText, QLabel#bundleDescription {{
                color:{theme['muted']};
                font-size:12px;
            }}
            QFrame#themeCard {{
                background:{theme['card']};
                border:1px solid {theme['border']};
                border-radius:14px;
            }}
            QFrame#themeCard:hover {{
                background:{theme['card_hover']};
                border-color:{theme['border_hover']};
            }}
            QFrame#themeCard[selected="true"] {{
                border:2px solid {theme['accent']};
                background:{theme['accent_soft']};
            }}
            QLabel#themeTitle {{
                color:{theme['primary']};
                font-size:13px;
                font-weight:800;
            }}
            QLabel#themeDescription {{
                color:{theme['muted']};
                font-size:10px;
            }}
            QRadioButton {{
                background:transparent;
                color:{theme['primary']};
            }}
            QLineEdit {{
                background:{theme['card']};
                border:1px solid {theme['border']};
                border-radius:10px;
                color:{theme['primary']};
                padding:11px 12px;
                selection-background-color:{theme['accent']};
            }}
            QLineEdit:focus {{
                border-color:{theme['accent']};
            }}
            QPushButton {{
                background:{theme['surface']};
                border:1px solid {theme['border']};
                border-radius:10px;
                color:{theme['secondary']};
                padding:10px 15px;
                font-weight:700;
            }}
            QPushButton:hover {{
                background:{theme['surface_hover']};
                border-color:{theme['border_hover']};
                color:{theme['primary']};
            }}
            QPushButton#setupPrimary {{
                background:{theme['accent']};
                border-color:{theme['accent']};
                color:#121417;
                min-width:130px;
            }}
            QPushButton#setupPrimary:hover {{
                background:{theme['accent_hover']};
                border-color:{theme['accent_hover']};
            }}
            QLabel#setupStatus {{
                color:{theme['muted']};
                font-size:11px;
            }}
            QLabel#setupStatus[success="true"] {{
                color:{theme['success']};
            }}
            QLabel#setupStatus[success="false"] {{
                color:{theme['danger']};
            }}
            """
        )
