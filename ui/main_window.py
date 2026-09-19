import threading

from PySide6.QtCore import QObject, Signal, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from database import add_to_library, get_work, initialize_database, save_anime, save_characters, save_cover_path, save_episodes, save_staff
from image_cache import download_cover
from ui.navigation import NavigationController
from ui.preferences import get
from ui.theme import COLORS, application_stylesheet, refresh_theme
from ui.pages.character_page import CharacterPage
from ui.pages.home_page import HomePage
from ui.pages.library_page import LibraryPage
from ui.pages.person_page import PersonPage
from ui.pages.relationship_page import RelationshipPage
from ui.pages.search_page import SearchPage
from ui.pages.settings_page import SettingsPage
from ui.pages.work_detail_page import WorkDetailPage


class ImageWorker(QObject):
    finished = Signal(int, object)
    error = Signal(int, str)

    def __init__(self, work_id, image_url):
        super().__init__()
        self.work_id = work_id
        self.image_url = image_url

    def run(self):
        try:
            self.finished.emit(self.work_id, download_cover(self.work_id, self.image_url))
        except Exception as error:
            self.error.emit(self.work_id, str(error))


class NavigationButton(QPushButton):
    def __init__(self, icon_text, label):
        super().__init__()
        self.label = label
        self.setText(f"{icon_text}  {label}")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(44)
        self.setProperty("navButton", True)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        initialize_database()
        self.setWindowTitle("NekoTrack")
        self.resize(1380, 860)
        self.image_threads = []
        self.navigation_buttons = {}
        self._settings_rebuild_pending = False
        self.setup_ui()

    def setup_ui(self):
        refresh_theme()
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(250)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 22, 18, 20)
        side.setSpacing(5)

        brand = QHBoxLayout()
        mark = QLabel("N")
        mark.setObjectName("brandMark")
        word = QLabel("NekoTrack")
        word.setObjectName("brandWord")
        brand.addWidget(mark)
        brand.addWidget(word)
        brand.addStretch()
        side.addLayout(brand)
        side.addSpacing(32)

        self.stack = QStackedWidget()
        self.navigation = NavigationController(self.stack)
        self.library_page = LibraryPage()
        self.search_page = SearchPage(self.add_to_library)
        self.work_detail_page = WorkDetailPage()
        self.settings_page = SettingsPage()
        self.relationship_page = RelationshipPage()
        pages = {
            "home": HomePage(),
            "collections": self.library_page,
            "search": self.search_page,
            "work_detail": self.work_detail_page,
            "person": PersonPage(),
            "character": CharacterPage(),
            "relationships": self.relationship_page,
            "settings": self.settings_page,
        }
        for name, page in pages.items():
            self.navigation.add_page(name, page)

        self._section(side, "LIBRARY", [("⌂", "Home", "home"), ("▦", "Library", "collections"), ("⌕", "Search", "search")])
        self._section(side, "EXPLORE", [("♙", "People", "person"), ("♧", "Characters", "character"), ("◇", "Relations", "relationships")])
        side.addStretch()
        self._add_nav(side, "⚙", "Settings", "settings")

        self.navigation.page_changed.connect(self.update_navigation_state)
        self.navigation.page_changed.connect(self._page_changed)
        self.library_page.work_selected.connect(self.show_work_details)
        self.search_page.anime_selected.connect(self.show_search_work)
        self.work_detail_page.back_requested.connect(lambda: self.navigation.show("collections"))
        self.work_detail_page.auto_bundle_requested.connect(self.library_page._auto_bundle_item)
        self.work_detail_page.bundle_edit_requested.connect(self.library_page._edit_bundle)
        self.work_detail_page.relation_selected.connect(self.show_relation)
        self.work_detail_page.bundle_changed.connect(self._refresh_library_after_bundle_change)
        self.relationship_page.work_selected.connect(self.show_relation)
        self.settings_page.settings_changed.connect(self.apply_settings)

        root_layout.addWidget(sidebar)
        root_layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.setStyleSheet(
            application_stylesheet()
            + f"""
            QFrame#sidebar {{ background:{COLORS['sidebar']}; border-right:1px solid {COLORS['border']}; }}
            QLabel#brandMark {{ background:{COLORS['accent']}; color:#111; border-radius:9px; font-size:19px; font-weight:900; min-width:38px; max-width:38px; min-height:38px; max-height:38px; qproperty-alignment:AlignCenter; }}
            QLabel#brandWord {{ color:{COLORS['primary']}; font-size:19px; font-weight:800; letter-spacing:-.4px; padding-left:7px; }}
            QPushButton[navButton="true"] {{ background:transparent; border:1px solid transparent; color:{COLORS['secondary']}; border-radius:10px; padding:11px 13px; text-align:left; font-size:13px; font-weight:600; }}
            QPushButton[navButton="true"]:hover {{ background:{COLORS['surface']}; color:{COLORS['primary']}; }}
            QPushButton[navButton="true"]:checked {{ background:{COLORS['accent_soft']}; border-color:#594025; color:{COLORS['accent_hover']}; }}
        """
        )
        self.navigation.show("home")

    def _refresh_library_after_bundle_change(self):
        # Wait until the detail-page deletion/link change has fully returned to
        # the event loop, then rebuild the Library from the current database state.
        QTimer.singleShot(0, self.library_page.refresh)

    def _page_changed(self, page_name):
        if page_name == "collections":
            # Rebuild the library when returning to it so relation-sync failures
            # can be retried through the normal page refresh path.
            self.library_page.refresh()
        elif page_name == "relationships":
            self.relationship_page.refresh()

    def apply_settings(self, changed_key=""):
        if self._settings_rebuild_pending:
            return
        self._settings_rebuild_pending = True
        QTimer.singleShot(0, lambda key=changed_key: self._rebuild_for_settings(key))

    def _rebuild_for_settings(self, changed_key):
        self._settings_rebuild_pending = False
        current_page = "home"
        if hasattr(self, "navigation"):
            current_widget = self.stack.currentWidget()
            for name, page in self.navigation.pages.items():
                if page is current_widget:
                    current_page = name
                    break
        was_maximized = self.isMaximized()
        was_fullscreen = self.isFullScreen()
        normal_geometry = self.normalGeometry()
        self.setUpdatesEnabled(False)
        try:
            if hasattr(self, "search_page"):
                self.search_page.shutdown_workers()
            self.navigation_buttons = {}
            self.setup_ui()
            self.navigation.show(current_page)
        finally:
            self.setUpdatesEnabled(True)
        if changed_key == "maximized":
            if get("maximized"):
                self.showMaximized()
            else:
                self.showNormal()
                if normal_geometry.isValid():
                    self.setGeometry(normal_geometry)
        elif was_fullscreen:
            self.showFullScreen()
        elif was_maximized:
            self.showMaximized()
        else:
            self.showNormal()
            if normal_geometry.isValid():
                self.setGeometry(normal_geometry)

    def _section(self, layout, title, items):
        label = QLabel(title)
        label.setStyleSheet(f"color:{COLORS['muted']}; font-size:10px; font-weight:800; letter-spacing:1.5px; padding:7px 12px 5px;")
        layout.addWidget(label)
        for icon, text, name in items:
            self._add_nav(layout, icon, text, name)
        layout.addSpacing(14)

    def _add_nav(self, layout, icon, label, page_name):
        button = NavigationButton(icon, label)
        self.navigation_buttons[page_name] = button
        button.clicked.connect(lambda checked=False, n=page_name: self.navigation.show(n))
        layout.addWidget(button)

    def update_navigation_state(self, page_name):
        for name, button in self.navigation_buttons.items():
            button.setChecked(name == page_name)

    def show_work_details(self, work):
        self.work_detail_page.set_work(work)
        self.navigation.show("work_detail")

    def show_search_work(self, work):
        try:
            from api import get_media_details
            details = get_media_details(work["id"])
            save_anime(details)
            save_characters(work["id"], (details.get("characters") or {}).get("edges"))
            save_staff(work["id"], (details.get("staff") or {}).get("edges"))
            save_episodes(work["id"], details.get("streamingEpisodes"))
            self.show_work_details(get_work(work["id"]) or work)
        except Exception:
            self.show_work_details(work)

    def show_relation(self, relation):
        if not relation:
            return
        try:
            target_id = relation["target_id"]
        except (KeyError, TypeError, IndexError):
            target_id = relation.get("target_id") if hasattr(relation, "get") else None
        work = get_work(target_id) if target_id else None
        if work:
            self.show_work_details(work)

    def add_to_library(self, anime, button):
        try:
            from api import get_media_details
            details = get_media_details(anime["id"])
            save_anime(details)
            save_characters(anime["id"], (details.get("characters") or {}).get("edges"))
            save_episodes(anime["id"], details.get("streamingEpisodes"))
            save_staff(anime["id"], (details.get("staff") or {}).get("edges"))
            add_to_library(anime["id"], "Planning")
            self.library_page.refresh()
            button.setText("Added")
            button.setEnabled(False)
            self.start_cover_download(anime["id"], (details.get("coverImage") or {}).get("large"), button)
        except Exception as error:
            button.setText("Error")
            self.search_page.results_title.setText(f"Could not save: {error}")

    def start_cover_download(self, work_id, image_url, button):
        if not image_url:
            return
        worker = ImageWorker(work_id, image_url)
        worker.finished.connect(self.cover_download_finished)
        worker.error.connect(self.cover_download_error)
        thread = threading.Thread(target=worker.run, daemon=True)
        self.image_threads.append(thread)
        thread.start()
        button.setProperty("cover_work_id", work_id)

    def cover_download_finished(self, work_id, cover_path):
        if cover_path:
            save_cover_path(work_id, cover_path)
        self._finish_cover_button(work_id)

    def cover_download_error(self, work_id, message):
        self._finish_cover_button(work_id, f"Cover unavailable: {message}")

    def _finish_cover_button(self, work_id, tooltip=None):
        for button in self.findChildren(QPushButton):
            if button.property("cover_work_id") == work_id:
                button.setText("Added")
                button.setToolTip(tooltip or "")
                break
