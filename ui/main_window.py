import threading

from api import get_media_details, get_tmdb_episode_data
from PySide6.QtCore import QObject, Signal, QThread, Qt, QTimer
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from database import (
    add_to_library,
    characters_are_loaded,
    get_alternate_titles,
    get_connection,
    get_episodes,
    get_tmdb_mapping,
    get_work,
    initialize_database,
    save_anime,
    save_characters,
    save_cover_path,
    save_episodes,
    save_staff,
    save_tmdb_mapping,
)
from image_cache import download_cover
from ui.navigation import NavigationController
from ui.preferences import get
from ui.setup_wizard import SetupWizard
from ui.theme import COLORS, application_stylesheet, refresh_theme
from ui.pages.home_page import HomePage
from ui.pages.library_page import LibraryPage
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
            save_staff(
                self.work_id,
                (details.get("staff") or {}).get("edges"),
            )

            # Library entries should be fully prepared before the user opens
            # their detail page. Episode metadata is fetched here, in the
            # existing background worker, rather than on the click path.
            title_data = details.get("title") or {}
            title_variants = [
                str(title_data.get("english") or "").strip(),
                str(title_data.get("romaji") or "").strip(),
                str(title_data.get("native") or "").strip(),
                *get_alternate_titles(self.work_id),
                *[
                    str(value).strip()
                    for value in (details.get("synonyms") or [])
                ],
            ]
            title_variants = list(
                dict.fromkeys(value for value in title_variants if value)
            )

            start_date_data = details.get("startDate") or {}
            end_date_data = details.get("endDate") or {}

            def format_date(date_data):
                year = date_data.get("year")
                if year is None:
                    return None
                month = date_data.get("month") or 1
                day = date_data.get("day") or 1
                return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

            start_date = format_date(start_date_data)
            end_date = format_date(end_date_data)
            expected_episodes = details.get("episodes")
            media_format = str(details.get("format") or "").upper()
            tmdb_id, tmdb_season_number = get_tmdb_mapping(self.work_id)

            # Episode preloading is best-effort. A missing TMDB token or a
            # temporary provider failure must not prevent Library import.
            try:
                episode_payload = get_tmdb_episode_data(
                    title_variants,
                    start_date,
                    end_date,
                    expected_episodes,
                    tmdb_id,
                    tmdb_season_number,
                    media_format,
                )
                resolved_tmdb_id = episode_payload.get("tmdb_id")
                resolved_season = episode_payload.get("tmdb_season_number")
                if resolved_tmdb_id is not None:
                    save_tmdb_mapping(
                        self.work_id,
                        resolved_tmdb_id,
                        resolved_season,
                    )
                save_episodes(
                    self.work_id,
                    episode_payload.get("episodes") or [],
                )
            except Exception as episode_error:
                print(
                    f"Episode preload failed for work {self.work_id}: "
                    f"{episode_error}"
                )

            self.finished.emit(self.work_id, details)
        except Exception as error:
            self.error.emit(self.work_id, str(error))



class LibraryEpisodePreloadWorker(QObject):
    finished = Signal(int, object)
    error = Signal(int, str)

    def __init__(self, work_ids):
        super().__init__()
        self.work_ids = [int(work_id) for work_id in work_ids]

    def run(self):
        for work_id in self.work_ids:
            try:
                connection_work = get_work(work_id)
                if connection_work is None:
                    continue

                existing_episodes = get_episodes(work_id)
                if existing_episodes:
                    continue

                title_variants = [
                    str(connection_work["title"] or "").strip(),
                    *get_alternate_titles(work_id),
                ]
                title_variants = list(
                    dict.fromkeys(value for value in title_variants if value)
                )
                if not title_variants:
                    continue

                year = connection_work["start_year"]
                if year is None:
                    continue

                month = connection_work["start_month"] or 1
                day = connection_work["start_day"] or 1
                start_date = (
                    f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
                )

                tmdb_id, tmdb_season_number = get_tmdb_mapping(work_id)
                payload = get_tmdb_episode_data(
                    title_variants,
                    start_date,
                    None,
                    connection_work["episodes"],
                    tmdb_id,
                    tmdb_season_number,
                    str(connection_work["format"] or "").upper(),
                )

                resolved_tmdb_id = payload.get("tmdb_id")
                if resolved_tmdb_id is not None:
                    save_tmdb_mapping(
                        work_id,
                        resolved_tmdb_id,
                        payload.get("tmdb_season_number"),
                    )

                episodes = payload.get("episodes") or []
                if episodes:
                    save_episodes(work_id, episodes)

                self.finished.emit(work_id, episodes)
            except Exception as error:
                self.error.emit(work_id, str(error))


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
        self.navigation_buttons = {}
        self._settings_rebuild_pending = False
        self._detail_enrichment_ids = set()
        self._library_episode_preload_thread = None
        self._library_episode_preload_worker = None
        self.setup_ui()
        QTimer.singleShot(250, self._start_existing_library_episode_preload)

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
        pages = {
            "home": HomePage(),
            "collections": self.library_page,
            "search": self.search_page,
            "work_detail": self.work_detail_page,
            "settings": self.settings_page,
        }
        for name, page in pages.items():
            self.navigation.add_page(name, page)

        self._section(side, "LIBRARY", [("⌂", "Home", "home"), ("▦", "Library", "collections"), ("⌕", "Search", "search")])
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
        self.settings_page.settings_changed.connect(self.apply_settings)
        self.settings_page.setup_requested.connect(self.open_setup_wizard)

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
        QTimer.singleShot(500, self._preload_library_details)

    def _preload_library_details(self):
        try:
            self.work_detail_page.preload_works(list(self.library_page.all_anime or []))
        except Exception as error:
            print(f"Library detail preload failed: {error}")

    def _refresh_library_after_bundle_change(self):
        # Wait until the detail-page deletion/link change has fully returned to
        # the event loop, then rebuild the Library from the current database state.
        QTimer.singleShot(0, self.library_page.refresh)

    def _page_changed(self, page_name):
        if page_name == "collections":
            # Rebuild the library when returning to it so relation-sync failures
            # can be retried through the normal page refresh path.
            self.library_page.refresh()

    def open_setup_wizard(self):
        wizard = SetupWizard(self)
        result = wizard.exec()
        if result == QDialog.Accepted:
            self.apply_settings("setup")

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

    def _start_existing_library_episode_preload(self):
        if (
            self._library_episode_preload_thread is not None
            and self._library_episode_preload_thread.isRunning()
        ):
            return

        connection = get_connection()
        try:
            library_ids = [
                int(row["id"])
                for row in connection.execute(
                    """
                    SELECT works.id
                    FROM works
                    JOIN user_library ON user_library.work_id = works.id
                    WHERE COALESCE(works.episodes, 0) > 0
                    ORDER BY user_library.added_date
                    """
                ).fetchall()
            ]
        except Exception:
            return
        finally:
            connection.close()

        missing_ids = []
        for work_id in library_ids:
            try:
                if not get_episodes(work_id):
                    missing_ids.append(work_id)
            except Exception:
                continue

        if not missing_ids:
            return

        worker = LibraryEpisodePreloadWorker(missing_ids)
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(self._library_episode_preloaded)
        worker.error.connect(
            lambda work_id, message:
                print(
                    f"Existing library episode preload failed for "
                    f"{work_id}: {message}"
                )
        )
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda t=thread: self._library_episode_preload_thread_finished(t)
        )

        self._library_episode_preload_thread = thread
        self._library_episode_preload_worker = worker
        thread.start()

    def _library_episode_preloaded(self, work_id, episodes):
        try:
            self.work_detail_page._start_episode_image_cache(
                int(work_id),
                [dict(episode) for episode in (episodes or [])],
            )

            # Episode data is now complete, so the corresponding detail view
            # can finally be built and placed in the same global cache used by
            # newly imported Library entries.
            for group in self.library_page.all_anime or []:
                members = group.get("_series_members") or []
                if any(int(member["id"]) == int(work_id) for member in members):
                    self.work_detail_page.preload_work(group)
                    break
        except Exception as error:
            print(
                f"Existing library preload failed for work {work_id}: "
                f"{error}"
            )

    def _library_episode_preload_thread_finished(self, thread):
        if self._library_episode_preload_thread is thread:
            self._library_episode_preload_thread = None
            self._library_episode_preload_worker = None


    def show_work_details(self, work):
        # Open the detail page immediately. Older library entries may still
        # need their full AniList character/staff payload, so enrich them in
        # the existing background worker instead of blocking the click.
        self.work_detail_page.set_work(work)
        self.navigation.show("work_detail")

        members = []
        raw_members = work.get("_series_members") if hasattr(work, "get") else None
        if raw_members:
            members.extend(raw_members)
        else:
            members.append(work)

        seen = set()
        for member in members:
            work_id = member.get("id") if hasattr(member, "get") else None
            try:
                work_id = int(work_id)
            except (TypeError, ValueError):
                continue
            if work_id in seen or work_id in self._detail_enrichment_ids:
                continue
            seen.add(work_id)

            try:
                needs_enrichment = not characters_are_loaded(work_id)
            except Exception:
                needs_enrichment = False

            if not needs_enrichment:
                continue

            self._detail_enrichment_ids.add(work_id)
            worker = LibraryImportWorker(work_id)
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


    def show_search_work(self, work):
        try:
            from api import get_media_details
            details = get_media_details(work["id"])
            save_anime(details)
            save_characters(work["id"], (details.get("characters") or {}).get("edges"))
            save_staff(work["id"], (details.get("staff") or {}).get("edges"))
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
        work_id = int(work_id)
        self._detail_enrichment_ids.discard(work_id)

        # Continue the preload by caching the already-saved TMDB episode
        # artwork. This is entirely background work and also benefits works
        # that are already open.
        try:
            episodes = get_episodes(work_id)
            self.work_detail_page._start_episode_image_cache(
                work_id,
                [dict(episode) for episode in episodes],
            )
        except Exception as error:
            print(
                f"Episode image preload failed for work {work_id}: {error}"
            )

        # Warm the imported Library entry so its detail widgets are ready
        # before the user opens it.
        def _preload_imported_group():
            try:
                for group in self.library_page.all_anime or []:
                    members = group.get("_series_members") or []
                    if any(int(member["id"]) == work_id for member in members):
                        self.work_detail_page.preload_work(group)
                        return
                saved = get_work(work_id)
                if saved is not None:
                    self.work_detail_page.preload_work(saved)
            except Exception as error:
                print(f"Library detail preload failed for work {work_id}: {error}")

        QTimer.singleShot(0, _preload_imported_group)

        # Refresh an already-open detail page after background enrichment so
        # newly imported characters/staff appear without another click.
        current_work = getattr(self.work_detail_page, "work", None)
        if current_work is None:
            return

        try:
            current_ids = {
                int(member["id"])
                for member in self.work_detail_page._detail_work_ids()
            }
        except Exception:
            current_ids = set()

        if work_id in current_ids:
            self.work_detail_page.set_work(current_work)

    def _library_import_error(self, work_id, message):
        self._detail_enrichment_ids.discard(int(work_id))
        # The basic library entry remains usable when optional full metadata
        # enrichment fails.
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
