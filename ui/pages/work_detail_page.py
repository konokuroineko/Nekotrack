from api import get_media_details
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QUrl, QSize
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QPen, QColor
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget, QWidgetAction
)

from database import (
    add_manual_bundle_link, add_to_library, delete_work_data, get_characters, get_connection,
    get_episodes, get_relations, get_staff, get_work,
    save_anime, save_characters, save_cover_path, save_episodes, save_staff,
    set_episode_progress, set_episode_watched,
)
from series import get_library_series
from ui.preferences import get
from ui.pages.search_page import SearchPage
from ui.theme import COLORS, muted_label_stylesheet
from ui.widgets.character_card import CharacterCard
from ui.widgets.person_card import PersonCard
from ui.widgets.relation_card import RelationCard


IMAGE_DIRECTORY = Path("data") / "images" / "works"



class BundleSearchDialog(QDialog):
    def __init__(self, excluded_ids=None, parent=None):
        super().__init__(parent)
        self.selected_work = None
        self.excluded_ids = {int(work_id) for work_id in (excluded_ids or set())}

        self.setWindowTitle("Add to bundle")
        self.setMinimumSize(1120, 760)
        self.resize(1180, 800)

        self.search_page = SearchPage(
            lambda *_args: None,
            selection_mode=True,
        )
        self.search_page.setParent(self)
        self.search_page.anime_selected.connect(self._select_work)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.search_page)

        self.setStyleSheet(
            f"QDialog {{ background:{COLORS['background']}; }}"
        )
        self.finished.connect(lambda _result: self.search_page.shutdown_workers())

    def _select_work(self, work):
        try:
            work_id = int(work["id"])
        except (KeyError, TypeError, ValueError):
            return
        if work_id in self.excluded_ids:
            return

        self.selected_work = work
        self.accept()


class BundleRemoveDialog(QDialog):
    def __init__(self, partners, parent=None):
        super().__init__(parent)
        self.selected_id = None
        self.setWindowTitle("Remove from bundle")
        self.setMinimumSize(500, 420)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)

        heading = QLabel("Remove from bundle")
        heading.setStyleSheet(
            f"font-size:21px;font-weight:850;color:{COLORS['primary']};"
        )
        root.addWidget(heading)

        subtitle = QLabel("Choose the bundled item you want to remove from your Library.")
        subtitle.setStyleSheet(f"color:{COLORS['secondary']};font-size:12px;")
        root.addWidget(subtitle)

        self.list = QListWidget()
        self.list.setSpacing(5)
        self.list.itemDoubleClicked.connect(self._choose_item)
        root.addWidget(self.list, 1)

        for row in partners or []:
            label = str(row["partner_title"] or "Untitled")
            meta = " · ".join(
                str(value)
                for value in (row["partner_type"], row["partner_format"])
                if value
            )
            if meta:
                label += f"\n{meta}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, int(row["partner_id"]))
            item.setSizeHint(QSize(0, 58))
            self.list.addItem(item)

        if not partners:
            empty = QListWidgetItem("No other bundled items found.")
            empty.setFlags(Qt.NoItemFlags)
            self.list.addItem(empty)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        remove_button = buttons.addButton("Delete selected item", QDialogButtonBox.AcceptRole)
        remove_button.setEnabled(bool(partners))
        remove_button.clicked.connect(self._choose_selected)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.setStyleSheet(
            f"""
            QDialog {{ background:{COLORS['background']}; }}
            QListWidget {{
                background:{COLORS['surface']};
                color:{COLORS['primary']};
                border:1px solid {COLORS['border']};
                border-radius:12px;
                padding:6px;
            }}
            QListWidget::item {{
                background:transparent;
                border:1px solid transparent;
                border-radius:9px;
                padding:10px 12px;
            }}
            QListWidget::item:hover, QListWidget::item:selected {{
                background:{COLORS['surface_hover']};
                border-color:{COLORS['accent']};
            }}
        """
        )

        if partners:
            self.list.setCurrentRow(0)

    def _choose_selected(self):
        self._choose_item(self.list.currentItem())

    def _choose_item(self, item):
        if item is None:
            return
        partner_id = item.data(Qt.UserRole)
        if partner_id is None:
            return
        self.selected_id = int(partner_id)
        self.accept()


class WorkDetailPage(QWidget):
    back_requested = Signal()
    person_selected = Signal(object)
    character_selected = Signal(object)
    relation_selected = Signal(object)
    bundle_changed = Signal()
    auto_bundle_requested = Signal(object)
    bundle_edit_requested = Signal(object)

    _cover_cache = {}
    _cover_failures = set()

    def __init__(self):
        super().__init__()
        self.work = None
        self._cover_manager = QNetworkAccessManager(self)
        self._cover_reply = None
        self._delete_overlay = None
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.scroll_area)

    def set_work(self, work):
        self.work = work
        if self._delete_overlay is not None:
            self._delete_overlay.deleteLater()
            self._delete_overlay = None
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(42, 34, 42, 50)
        root.setSpacing(22)
        back = QPushButton("‹  Back to Library")
        back.setObjectName("back")
        back.clicked.connect(self.back_requested)
        root.addWidget(back, alignment=Qt.AlignLeft)
        root.addWidget(self._hero())
        root.addWidget(self._description())
        root.addWidget(self._episodes_section())
        root.addWidget(self._grid_section("Characters", get_characters(self._value("id")), CharacterCard, self.character_selected, 4))
        root.addWidget(self._grid_section("Staff", get_staff(self._value("id")), PersonCard, self.person_selected, 4))
        root.addWidget(self._relations())
        root.addStretch()
        self.scroll_area.setWidget(content)
        self.setStyleSheet(f"""
            QPushButton#back {{ background: transparent; border: 0; color: {COLORS['secondary']}; padding: 5px 0; font-weight: 750; }}
            QPushButton#back:hover {{ color: {COLORS['primary']}; }}
            QFrame#hero {{ background: {COLORS['surface']}; border: 1px solid {COLORS['frame']}; border-radius: 22px; }}
            QFrame#section {{ background: {COLORS['surface']}; border: 1px solid {COLORS['frame']}; border-radius: 18px; }}
            QFrame#episode {{ background: {COLORS['surface_alt']}; border: 1px solid {COLORS['frame']}; border-radius: 10px; }}
            QFrame#episode:hover {{ border-color: {COLORS['border_hover']}; }}
            QFrame#progressTrack {{ background: {COLORS['border']}; border: 0; border-radius: 5px; }}
            QFrame#progressFill {{ background: {COLORS['accent']}; border: 0; border-radius: 5px; }}
            QSpinBox#episodeCounter {{ background: {COLORS['background_alt']}; color: {COLORS['primary']}; border: 1px solid {COLORS['border_hover']}; border-radius: 10px; padding: 8px 12px; font-size: 18px; font-weight: 850; min-width: 92px; }}
            QSpinBox#episodeCounter:focus {{ border-color: {COLORS['accent']}; }}
            QSpinBox#episodeCounter::up-button, QSpinBox#episodeCounter::down-button {{ width: 0; height: 0; border: 0; }}
            QPushButton#counterButton {{ background: {COLORS['surface_alt']}; color: {COLORS['primary']}; border: 1px solid {COLORS['border']}; border-radius: 10px; font-size: 18px; font-weight: 850; min-width: 38px; min-height: 38px; }}
            QPushButton#counterButton:hover {{ background: {COLORS['surface_hover']}; border-color: {COLORS['accent']}; }}
            QToolButton#detailMenu {{ background:transparent; color:{COLORS['primary']}; border:2px solid transparent; border-radius:{get('corner_radius') + 2}px; font-size:30px; font-weight:900; padding:0; }}
            QToolButton#detailMenu:hover {{ background:{COLORS['surface_hover']}; color:{COLORS['accent_hover']}; border-color:{COLORS['accent']}; }}
            QFrame#deleteOverlay {{ background:{COLORS['surface']}; border:1px solid {COLORS['frame']}; border-radius:18px; }}
            QLabel#deleteTitle {{ color:{COLORS['primary']}; font-size:19px; font-weight:850; }}
            QLabel#deleteMessage {{ color:{COLORS['secondary']}; font-size:12px; }}
            QPushButton#deleteCancel {{ background:{COLORS['surface_alt']}; color:{COLORS['secondary']}; border:1px solid {COLORS['border']}; border-radius:9px; padding:9px 16px; font-weight:750; }}
            QPushButton#deleteCancel:hover {{ background:{COLORS['surface_hover']}; color:{COLORS['primary']}; }}
            QPushButton#deleteConfirm {{ background:#c94343; color:white; border:0; border-radius:9px; padding:9px 18px; font-weight:850; }}
            QPushButton#deleteConfirm:hover {{ background:#e05252; }}
            QPushButton#deleteBundle {{ background:#c94343; color:white; border:0; border-radius:9px; padding:9px 14px; font-weight:850; }}
            QPushButton#deleteBundle:hover {{ background:#e05252; }}
            QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {COLORS['border_hover']}; background: {COLORS['background_alt']}; }}
            QCheckBox::indicator:checked {{ background: {COLORS['accent']}; border-color: {COLORS['accent']}; }}
        """)

    def _hero(self):
        hero = QFrame(); hero.setObjectName("hero")
        box = QHBoxLayout(hero); box.setContentsMargins(24, 24, 28, 24); box.setSpacing(30)
        cover = QLabel(); cover.setFixedSize(235, 335); cover.setAlignment(Qt.AlignCenter)
        cover.setStyleSheet(f"background:{COLORS['background_alt']}; border-radius:14px;")
        path = self._value("cover_path")
        if path:
            pix = QPixmap(str(path))
            if not pix.isNull(): cover.setPixmap(self._cropped_cover(pix, cover.size(), 14))
        if cover.pixmap() is None or cover.pixmap().isNull():
            cover.setText("NO COVER")
            cover.setStyleSheet(f"color:{COLORS['muted']}; background:{COLORS['background_alt']}; border-radius:14px;")
            self._load_remote_cover(cover)
        box.addWidget(cover, alignment=Qt.AlignTop)

        info = QVBoxLayout(); info.setSpacing(10)
        title = QLabel(self._title()); title.setWordWrap(True)
        title.setStyleSheet(f"font-size:34px;font-weight:850;color:{COLORS['primary']};letter-spacing:-1px;")
        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        title_row.addWidget(title, 1)
        if self._library_group() is not None:
            menu_button = QToolButton()
            menu_button.setObjectName("detailMenu")
            menu_button.setText("⋮")
            menu_button.setFixedSize(42, 42)
            menu_button.setCursor(Qt.PointingHandCursor)
            menu_button.clicked.connect(self._show_detail_menu)
            title_row.addWidget(menu_button, 0, Qt.AlignTop)
        info.addLayout(title_row)
        alt = self._value("native") or self._value("title_native") or ""
        if alt:
            native = QLabel(str(alt)); native.setStyleSheet(muted_label_stylesheet()); info.addWidget(native)
        meta = "  ·  ".join(str(x) for x in [self._value("format"), self._value("start_year"), f"{self._value('episodes')} eps" if self._value("episodes") else None, f"{self._value('chapters')} ch" if self._value("chapters") else None] if x)
        if meta:
            metadata = QLabel(meta); metadata.setStyleSheet(f"color:{COLORS['secondary']};font-size:13px;"); info.addWidget(metadata)
        score = self._value("score") or self._value("averageScore")
        score_label = QLabel(f"★  {score}%" if score else "—  No score"); score_label.setStyleSheet(f"color:{COLORS['accent']};font-size:18px;font-weight:800;"); info.addWidget(score_label)

        info.addSpacing(10)
        progress_title = QLabel("Episode progress"); progress_title.setStyleSheet(f"color:{COLORS['secondary']};font-size:12px;font-weight:800;"); info.addWidget(progress_title)
        progress_row = QHBoxLayout(); progress_row.setSpacing(8)
        minus = QPushButton("−"); minus.setObjectName("counterButton"); minus.setCursor(Qt.PointingHandCursor)
        plus = QPushButton("+"); plus.setObjectName("counterButton"); plus.setCursor(Qt.PointingHandCursor)
        counter = QSpinBox(); counter.setObjectName("episodeCounter")
        total = max(0, int(self._value("episodes") or 0)); current = max(0, int(self._value("progress_episodes") or 0))
        counter.setRange(0, total if total else 99999); counter.setValue(min(current, counter.maximum())); counter.setAlignment(Qt.AlignCenter); counter.setButtonSymbols(QSpinBox.NoButtons)
        minus.clicked.connect(lambda: counter.setValue(counter.value() - 1)); plus.clicked.connect(lambda: counter.setValue(counter.value() + 1)); counter.valueChanged.connect(self._progress_counter_changed)
        progress_row.addWidget(minus); progress_row.addWidget(counter); progress_row.addWidget(plus); progress_row.addStretch(); info.addLayout(progress_row)
        progress_track = QFrame(); progress_track.setObjectName("progressTrack"); progress_track.setFixedHeight(8)
        progress_fill = QFrame(progress_track); progress_fill.setObjectName("progressFill")
        ratio = (current / total) if total else 0; progress_fill.setGeometry(0, 0, round(420 * min(1.0, ratio)), 8); info.addWidget(progress_track)
        progress_count = QLabel(f"{current} of {total} episodes" if total else "Episode count unavailable"); progress_count.setStyleSheet(muted_label_stylesheet()); info.addWidget(progress_count); info.addStretch()
        self._episode_counter = counter; self._progress_fill = progress_fill; self._progress_track = progress_track; self._progress_count = progress_count
        box.addLayout(info, 1)
        return hero

    def _load_remote_cover(self, label):
        work_id = self._value("id")
        cover_url = self._value("cover_url") or (self._value("coverImage") or {}).get("large")
        if not work_id or not cover_url: return
        cover_url = str(cover_url)
        cached = self._cover_cache.get(cover_url)
        if cached is not None and not cached.isNull():
            label.setPixmap(self._cropped_cover(cached, label.size(), 14)); return
        if cover_url in self._cover_failures: return
        self._cover_reply = self._cover_manager.get(QNetworkRequest(QUrl(cover_url)))
        self._cover_reply.finished.connect(lambda: self._remote_cover_finished(label, work_id, cover_url))

    def _remote_cover_finished(self, label, work_id, cover_url):
        reply = self._cover_reply; self._cover_reply = None
        if reply is not None and reply.error() == reply.NetworkError.NoError:
            pix = QPixmap()
            if pix.loadFromData(reply.readAll()):
                self._cover_cache[cover_url] = pix
                label.setText(""); label.setPixmap(self._cropped_cover(pix, label.size(), 14))
                try:
                    IMAGE_DIRECTORY.mkdir(parents=True, exist_ok=True)
                    path = IMAGE_DIRECTORY / f"{work_id}.jpg"
                    if pix.save(str(path), "JPG", 85): save_cover_path(work_id, str(path))
                except Exception:
                    pass
            else: self._cover_failures.add(cover_url)
        else: self._cover_failures.add(cover_url)
        if reply is not None: reply.deleteLater()

    def _library_group(self):
        work_id = self._value("id")
        if work_id is None:
            return None
        current_id = int(work_id)
        for group in get_library_series():
            members = group.get("_series_members") or []
            if any(int(member["id"]) == current_id for member in members):
                return group
        return None

    def _show_detail_menu(self):
        group = self._library_group()
        if group is None:
            return

        menu = QMenu(self)
        menu.setStyleSheet(
            f"""
            QMenu {{
                background: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 12px;
                padding: 6px;
            }}
            QPushButton#detailMenuItem {{
                background: transparent;
                color: {COLORS['secondary']};
                border: 1px solid transparent;
                border-radius: 9px;
                padding: 8px 12px;
                text-align: left;
                font-weight: 700;
            }}
            QPushButton#detailMenuItem:hover {{
                background: {COLORS['surface_hover']};
                border-color: {COLORS['accent']};
                color: {COLORS['primary']};
            }}
            QPushButton#detailDeleteItem {{
                background: transparent;
                color: #ef7474;
                border: 1px solid transparent;
                border-radius: 9px;
                padding: 8px 12px;
                text-align: left;
                font-weight: 800;
            }}
            QPushButton#detailDeleteItem:hover {{
                background: {COLORS['surface_hover']};
                border-color: {COLORS['accent']};
                color: #ff8585;
            }}
            """
        )

        def add_item(text, object_name, callback):
            action = QWidgetAction(menu)
            button = QPushButton(text)
            button.setObjectName(object_name)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda: (menu.hide(), callback()))
            action.setDefaultWidget(button)
            menu.addAction(action)

        add_item("Add to bundle", "detailMenuItem", self._open_add_bundle_dialog)
        add_item("Remove from bundle", "detailMenuItem", self._open_remove_bundle_dialog)

        menu.addSeparator()
        add_item("Auto Bundle", "detailMenuItem", lambda: self.auto_bundle_requested.emit(group))

        try:
            has_bundle = len(group.get("_series_members") or []) > 1
        except (TypeError, ValueError):
            has_bundle = False

        if has_bundle:
            add_item(
                "Edit Bundle Appearance…",
                "detailMenuItem",
                lambda: self.bundle_edit_requested.emit(group),
            )

        menu.addSeparator()
        add_item("Delete", "detailDeleteItem", lambda: self._show_delete_confirmation(group))

        button = self.sender()
        menu.exec(
            button.mapToGlobal(button.rect().bottomLeft())
            if isinstance(button, QToolButton)
            else self.mapToGlobal(self.rect().center())
        )

    def _open_add_bundle_dialog(self):
        group = self._library_group()
        if group is None:
            return

        excluded_ids = {
            int(member["id"])
            for member in (group.get("_series_members") or [])
            if member["id"] is not None
        }
        dialog = BundleSearchDialog(excluded_ids=excluded_ids, parent=self)
        if dialog.exec() != QDialog.Accepted or dialog.selected_work is None:
            return

        selected = dialog.selected_work
        work_id = int(selected["id"])
        current_id = int(self._value("id"))

        try:
            details = get_media_details(work_id)
            if not details:
                raise RuntimeError("Could not load that work.")

            save_anime(details)
            save_characters(work_id, (details.get("characters") or {}).get("edges"))
            save_staff(work_id, (details.get("staff") or {}).get("edges"))
            save_episodes(work_id, details.get("streamingEpisodes"))

            connection = get_connection()
            in_library = connection.execute(
                "SELECT 1 FROM user_library WHERE work_id = ? LIMIT 1",
                (work_id,),
            ).fetchone() is not None
            connection.close()

            if not in_library:
                add_to_library(work_id, "Planning")

            if not add_manual_bundle_link(current_id, work_id):
                QMessageBox.information(
                    self,
                    "Bundle unchanged",
                    "That work is already linked to this bundle.",
                )
                return

            self.bundle_changed.emit()
            refreshed = get_work(current_id)
            if refreshed:
                self.set_work(refreshed)
        except Exception as error:
            QMessageBox.critical(self, "Could not add to bundle", str(error))

    def _open_remove_bundle_dialog(self):
        work_id = self._value("id")
        if work_id is None:
            return

        group = self._library_group()
        if group is None:
            return

        members = list(group.get("_series_members") or [])
        partners = [
            {
                "partner_id": int(member["id"]),
                "partner_title": self._member_title(member),
                "partner_type": member["type"],
                "partner_format": member["format"],
            }
            for member in members
            if int(member["id"]) != int(work_id)
        ]

        dialog = BundleRemoveDialog(partners, parent=self)
        if dialog.exec() != QDialog.Accepted or dialog.selected_id is None:
            return

        selected_id = int(dialog.selected_id)

        # "Remove from bundle" means remove that bundled library entry entirely.
        # It must not merely unlink the item and leave it in the Library.
        if not delete_work_data(selected_id):
            QMessageBox.critical(
                self,
                "Could not remove bundled item",
                "The selected bundled item could not be removed from NekoTrack.",
            )
            return

        connection = get_connection()
        still_exists = connection.execute(
            "SELECT 1 FROM works WHERE id = ? LIMIT 1",
            (selected_id,),
        ).fetchone() is not None
        still_in_library = connection.execute(
            "SELECT 1 FROM user_library WHERE work_id = ? LIMIT 1",
            (selected_id,),
        ).fetchone() is not None
        connection.close()

        if still_exists or still_in_library:
            QMessageBox.critical(
                self,
                "Remove failed",
                "The selected bundled item was not fully removed from NekoTrack.",
            )
            return

        self.bundle_changed.emit()
        refreshed = get_work(int(work_id))
        if refreshed:
            self.set_work(refreshed)
        else:
            self.work = None
            self.back_requested.emit()

    def _show_delete_confirmation(self, group):
        if self._delete_overlay is not None:
            self._delete_overlay.deleteLater()
            self._delete_overlay = None

        members = list(group.get("_series_members") or [])
        current_id = int(self._value("id"))
        is_bundle = len(members) > 1

        overlay = QFrame(self)
        overlay.setObjectName("deleteOverlay")
        overlay.setFixedWidth(460)
        layout = QVBoxLayout(overlay)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        title = QLabel("Delete from NekoTrack?")
        title.setObjectName("deleteTitle")
        layout.addWidget(title)

        message = QLabel(
            "This will permanently remove the selected local data and cached cover."
            if not is_bundle
            else "Choose the bundle entry you want to permanently remove, or delete the entire bundle."
        )
        message.setObjectName("deleteMessage")
        message.setWordWrap(True)
        layout.addWidget(message)

        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel = QPushButton("Cancel")
        cancel.setObjectName("deleteCancel")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(lambda: self._close_delete_overlay(overlay))
        buttons.addWidget(cancel)

        if is_bundle:
            member_list = QListWidget()
            member_list.setObjectName("deleteMemberList")
            member_list.setMinimumHeight(min(220, max(90, 58 * min(len(members), 4))))
            member_list.setMaximumHeight(260)
            member_list.setStyleSheet(
                f"""
                QListWidget#deleteMemberList {{
                    background: {COLORS['background_alt']};
                    border: 1px solid {COLORS['frame']};
                    border-radius: 9px;
                    padding: 4px;
                    color: {COLORS['primary']};
                }}
                QListWidget#deleteMemberList::item {{
                    padding: 9px 10px;
                    border: 1px solid transparent;
                    border-radius: 7px;
                    color: {COLORS['secondary']};
                }}
                QListWidget#deleteMemberList::item:hover {{
                    background: {COLORS['surface_hover']};
                    border-color: {COLORS['accent']};
                    color: {COLORS['primary']};
                }}
                QListWidget#deleteMemberList::item:selected {{
                    background: {COLORS['accent_soft']};
                    border-color: {COLORS['accent']};
                    color: {COLORS['primary']};
                }}
                """
            )
            selected_row = 0
            for index, member in enumerate(members):
                item = QListWidgetItem(self._member_title(member))
                item.setData(Qt.UserRole, int(member["id"]))
                member_list.addItem(item)
                if int(member["id"]) == current_id:
                    selected_row = index
            member_list.setCurrentRow(selected_row)
            layout.addWidget(member_list)

            entry_button = QPushButton("Delete selected entry")
            entry_button.setObjectName("deleteConfirm")
            entry_button.setCursor(Qt.PointingHandCursor)
            entry_button.clicked.connect(
                lambda: self._delete_selected_bundle_member(member_list, overlay)
            )
            buttons.addWidget(entry_button)

            bundle_button = QPushButton("Delete entire bundle")
            bundle_button.setObjectName("deleteBundle")
            bundle_button.setCursor(Qt.PointingHandCursor)
            bundle_button.clicked.connect(
                lambda: self._delete_from_detail(
                    [int(member["id"]) for member in members],
                    overlay,
                )
            )
            buttons.addWidget(bundle_button)
        else:
            confirm = QPushButton("Delete")
            confirm.setObjectName("deleteConfirm")
            confirm.setCursor(Qt.PointingHandCursor)
            confirm.clicked.connect(
                lambda: self._delete_from_detail([current_id], overlay)
            )
            buttons.addWidget(confirm)

        layout.addLayout(buttons)
        overlay.adjustSize()
        x = max(18, (self.width() - overlay.width()) // 2)
        y = max(18, (self.height() - overlay.height()) // 2)
        overlay.move(x, y)
        overlay.raise_()
        overlay.show()
        self._delete_overlay = overlay

    def _close_delete_overlay(self, overlay):
        if overlay is self._delete_overlay:
            self._delete_overlay = None
        overlay.deleteLater()

    def _delete_selected_bundle_member(self, member_list, overlay):
        item = member_list.currentItem()
        if item is None:
            return
        self._delete_from_detail([int(item.data(Qt.UserRole))], overlay)

    def _delete_from_detail(self, work_ids, overlay):
        target_ids = [int(work_id) for work_id in work_ids]
        deleted_ids = []

        for work_id in target_ids:
            if delete_work_data(work_id):
                deleted_ids.append(work_id)

        overlay.deleteLater()
        self._delete_overlay = None

        # Verify the exact selected entries are gone before rebuilding the
        # Library. This prevents a stale bundle view from hiding a failed delete.
        remaining_ids = []
        connection = get_connection()
        for work_id in target_ids:
            if connection.execute(
                "SELECT 1 FROM works WHERE id = ? LIMIT 1",
                (work_id,),
            ).fetchone() is not None:
                remaining_ids.append(work_id)
        connection.close()

        if remaining_ids:
            QMessageBox.critical(
                self,
                "Delete failed",
                "NekoTrack could not remove the selected entry from its local database.",
            )
            return

        if deleted_ids:
            self.bundle_changed.emit()
            self.work = None
            self.back_requested.emit()

    def _progress_counter_changed(self, value):
        if self.work is None: return
        set_episode_progress(self._value("id"), value)
        refreshed = get_work(self._value("id"))
        if refreshed: self.set_work(refreshed)

    def _cropped_cover(self, pixmap, size, radius):
        scaled = pixmap.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = max(0, (scaled.width() - size.width()) // 2); y = max(0, (scaled.height() - size.height()) // 2)
        cropped = scaled.copy(x, y, size.width(), size.height()); result = QPixmap(size); result.fill(Qt.transparent)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = result.rect().adjusted(2, 2, -2, -2)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.save()
        painter.setClipPath(path)
        painter.drawPixmap(rect.topLeft(), cropped.scaled(rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        painter.restore()
        painter.setPen(QPen(QColor(COLORS["accent"]), 3.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        painter.end()
        return result

    def _description(self):
        frame = QFrame(); frame.setObjectName("section"); lay = QVBoxLayout(frame); lay.setContentsMargins(20, 18, 20, 20); lay.setSpacing(10)
        header = QLabel("Overview"); header.setStyleSheet(f"font-size:17px;font-weight:800;color:{COLORS['primary']};"); lay.addWidget(header)
        label = QLabel(self._value("description") or "No description saved locally."); label.setWordWrap(True); label.setTextFormat(Qt.PlainText); label.setStyleSheet(f"color:{COLORS['secondary']};font-size:14px;"); lay.addWidget(label); return frame

    def _episodes_section(self):
        episodes = get_episodes(self._value("id")); frame = QFrame(); frame.setObjectName("section"); lay = QVBoxLayout(frame); lay.setContentsMargins(20, 18, 20, 20); lay.setSpacing(10)
        header = QHBoxLayout(); title = QLabel("Episodes"); title.setStyleSheet(f"font-size:17px;font-weight:800;color:{COLORS['primary']};"); header.addWidget(title); header.addStretch(); watched = sum(1 for ep in episodes if ep["watched"]); total = len(episodes); count = QLabel(f"{watched} / {total} watched" if total else "No episode list saved"); count.setStyleSheet(f"color:{COLORS['accent']};font-weight:800;"); header.addWidget(count); lay.addLayout(header)
        if not episodes:
            x = QLabel("Use the episode counter above to track progress. Detailed episode data will appear here when saved locally."); x.setStyleSheet(muted_label_stylesheet()); x.setWordWrap(True); lay.addWidget(x); return frame
        for ep in episodes:
            row = QFrame(); row.setObjectName("episode"); r = QHBoxLayout(row); r.setContentsMargins(12, 9, 14, 9); cb = QCheckBox(); cb.setChecked(bool(ep["watched"])); r.addWidget(cb); num = QLabel(f"EP {ep['episode_number']:02d}"); num.setMinimumWidth(52); num.setStyleSheet(f"color:{COLORS['accent']};font-weight:850;"); r.addWidget(num); ep_title = QLabel(ep["title"] or "Episode"); ep_title.setStyleSheet(f"color:{COLORS['primary']};font-weight:650;"); r.addWidget(ep_title, 1); date = QLabel(str(ep["air_date"] or "")); date.setStyleSheet(muted_label_stylesheet()); r.addWidget(date); cb.toggled.connect(lambda checked, n=ep["episode_number"]: self._episode_toggled(n, checked)); lay.addWidget(row)
        return frame

    def _episode_toggled(self, number, checked):
        set_episode_watched(self._value("id"), number, checked); refreshed = get_work(self._value("id")); self.set_work(refreshed or self.work)

    def _grid_section(self, title, items, cls, signal, columns):
        frame = QFrame(); frame.setObjectName("section"); frame.setStyleSheet(f"QFrame#section {{ background:{COLORS['surface']}; border:1px solid {COLORS['frame']}; border-radius:18px; }}"); lay = QVBoxLayout(frame); lay.setContentsMargins(20, 18, 20, 20); lay.setSpacing(12); header = QLabel(title); header.setStyleSheet(f"font-size:17px;font-weight:800;color:{COLORS['primary']};"); lay.addWidget(header); container = QWidget(); grid = QGridLayout(container); grid.setContentsMargins(0, 0, 0, 0); grid.setHorizontalSpacing(12); grid.setVerticalSpacing(12)
        if not items:
            x = QLabel("Nothing stored locally yet."); x.setStyleSheet(muted_label_stylesheet()); grid.addWidget(x, 0, 0)
        else:
            for i, item in enumerate(items):
                card = cls(item); card.clicked.connect(signal); grid.addWidget(card, i // columns, i % columns)
        lay.addWidget(container); return frame

    def _relations(self):
        return self._grid_section("Relations", get_relations(self._value("id")), RelationCard, self.relation_selected, 2)

    @staticmethod
    def _member_title(member):
        title = member["title"]
        if isinstance(title, dict):
            return str(
                title.get("english")
                or title.get("romaji")
                or title.get("native")
                or "Untitled"
            )
        return str(title or "Untitled")

    def _value(self, key):
        if hasattr(self.work, "get"): return self.work.get(key)
        try: return self.work[key]
        except (KeyError, IndexError, TypeError): return None

    def _title(self):
        title = self._value("title")
        if isinstance(title, dict): return title.get("english") or title.get("romaji") or title.get("native") or "Untitled"
        return title or "Untitled"
