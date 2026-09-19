import threading

from api import get_media_details, get_media_episodes
from PySide6.QtCore import QObject, Signal, QThread, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from database import add_to_library, characters_are_loaded, get_episodes, get_work, initialize_database, save_anime, save_characters, save_cover_path, save_episodes, save_staff
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


class LibraryImportWorker(QObject):
    finished = Signal(int, object)
    error = Signal(int, str)

    def __init__(self, work_id):
        super().__init__()
        self.work_id = int(work_id)

    def run(self):
        try:
            details = get_media_details(self.work_id)
            if not details:
                raise RuntimeError("AniList returned no details for this work.")

            save_anime(details)
            save_characters(
                self.work_id,
                (details.get("characters") or {}).get("edges"),
            )
            save_episodes(
                self.work_id,
                details.get("streamingEpisodes"),
            )
            save_staff(
                self.work_id,
                (details.get("staff") or {}).get("edges"),
            )
            self.finished.emit(self.work_id, details)
        except Exception as error:
            self.error.emit(self.work_id, str(error))



class EpisodeImportWorker(QObject):
    finished = Signal(int, object)
    error = Signal(int, str)

    def __init__(self, work_id):
        super().__init__()
        self.work_id = int(work_id)

    def run(self):
        try:
            episodes = get_media_episodes(self.work_id)
            save_episodes(self.work_id, episodes)
            self.finished.emit(self.work_id, episodes)
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
        self.library_import_threads = []
        self.library_import_workers = []
        self.episode_import_threads = []
        self.episode_import_workers = []
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
            QFrame#sidebar {{ background:{COLORS['sidebar']}; border-right:1px solid {COLORS['frame']}; }}
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
        # Older library entries were imported with only AniList's first
        # character page. Refresh them once so the detail page can show the
        # complete character list without re-importing the work manually.
        work_id = work.get("id") if hasattr(work, "get") else None
        if work_id and not characters_are_loaded(work_id):
            try:
                details = get_media_details(work_id)
                if details:
                    save_anime(details)
                    save_characters(work_id, (details.get("characters") or {}).get("edges"))
                    save_staff(work_id, (details.get("staff") or {}).get("edges"))
                    save_episodes(work_id, details.get("streamingEpisodes"))
                    work = get_work(work_id) or work
            except Exception:
                pass

        self.work_detail_page.set_work(work)
        self.navigation.show("work_detail")
        self._sync_missing_bundle_episodes(work)


    def _sync_missing_bundle_episodes(self, work):
        members = list(work.get("_series_members") or []) if hasattr(work, "get") else []
        if not members:
            members = [work]

        for member in members:
            try:
                work_id = int(member["id"])
            except (KeyError, TypeError, ValueError):
                continue

            if get_episodes(work_id):
                continue

            worker = EpisodeImportWorker(work_id)
            thread = QThread(self)
            worker.moveToThread(thread)

            thread.started.connect(worker.run)
            worker.finished.connect(self._episode_import_finished)
            worker.error.connect(self._episode_import_error)
            worker.finished.connect(thread.quit)
            worker.error.connect(thread.quit)
            thread.finished.connect(worker.deleteLater)
            thread.finished.connect(
                lambda t=thread, w=worker:
                    self._episode_import_thread_finished(t, w)
            )

            self.episode_import_threads.append(thread)
            self.episode_import_workers.append(worker)
            thread.start()

    def _episode_import_finished(self, work_id, episodes):
        current = self.work_detail_page.work
        if current is None:
            return

        members = list(current.get("_series_members") or []) if hasattr(current, "get") else []
        ids = {int(member["id"]) for member in members if member.get("id") is not None}
        current_id = current.get("id") if hasattr(current, "get") else None

        if current_id is not None:
            ids.add(int(current_id))

        if int(work_id) in ids:
            self.work_detail_page._replace_episode_section()

    def _episode_import_error(self, work_id, message):
        return

    def _episode_import_thread_finished(self, thread, worker):
        if thread in self.episode_import_threads:
            self.episode_import_threads.remove(thread)
        if worker in self.episode_import_workers:
            self.episode_import_workers.remove(worker)
        thread.deleteLater()


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
            primary_id = int(anime["id"])

            # A bundled Search result carries every member in _series_members.
            # Add the whole bundle instead of only the representative result.
            members = anime.get("_series_members") if hasattr(anime, "get") else None
            if not members:
                members = [anime]

            bundle_members = []
            seen_ids = set()
            for member in members:
                try:
                    member_id = int(member["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                if member_id in seen_ids:
                    continue
                seen_ids.add(member_id)
                bundle_members.append(member)

            if not bundle_members:
                bundle_members = [anime]

            for member in bundle_members:
                member_id = int(member["id"])

                # Save the lightweight Search/enriched result immediately so
                # the Library knows about every bundle member.
                save_anime(member)
                add_to_library(member_id, "Planning")

                # Fetch the expensive full payload in the background.
                worker = LibraryImportWorker(member_id)
                thread = QThread(self)
                worker.moveToThread(thread)

                thread.started.connect(worker.run)
                worker.finished.connect(self._library_import_finished)
                worker.error.connect(self._library_import_error)
                worker.finished.connect(thread.quit)
                worker.error.connect(thread.quit)
                thread.finished.connect(worker.deleteLater)
                thread.finished.connect(
                    lambda t=thread, w=worker: self._library_import_thread_finished(t, w)
                )

                self.library_import_threads.append(thread)
                self.library_import_workers.append(worker)
                thread.start()

            button.setText("Added")
            button.setEnabled(False)
            self.library_page.refresh()

            # Covers will be loaded/cached normally by the Library cards.
            # Start the representative cover download as before.
            self.start_cover_download(
                primary_id,
                (anime.get("coverImage") or {}).get("large"),
                button,
            )
        except Exception as error:
            button.setText("Error")
            self.search_page.results_title.setText(f"Could not save: {error}")


    def _library_import_finished(self, work_id, details):
        # The library entry already exists. The worker has now filled in the
        # heavier metadata such as characters, voice actors, episodes, and staff.
        return

    def _library_import_error(self, work_id, message):
        # The basic library entry was already saved. Keep it usable even when
        # the optional full metadata import fails.
        return

    def _library_import_thread_finished(self, thread, worker):
        if thread in self.library_import_threads:
            self.library_import_threads.remove(thread)
        if worker in self.library_import_workers:
            self.library_import_workers.remove(worker)
        thread.deleteLater()


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
