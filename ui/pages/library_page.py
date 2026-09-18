import shutil
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, Signal, QEvent, QTimer, QPropertyAnimation, QEasingCurve, QThread
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget, QLayout

from api import get_media_details
from database import clear_bundle_override, delete_work_data, get_all_library, get_bundle_override, get_connection, save_anime, save_bundle_override
from series import get_library_series
from ui.preferences import get
from ui.theme import COLORS
from ui.widgets.work_card import WorkCard


class RelationSyncWorker(QObject):
    finished = Signal(object)

    def __init__(self, work_ids):
        super().__init__()
        self.work_ids = work_ids

    def run(self):
        succeeded_ids = set()
        for work_id in self.work_ids:
            try:
                details = get_media_details(work_id)
                if details:
                    save_anime(details)
                    succeeded_ids.add(int(work_id))
            except Exception:
                continue
        self.finished.emit(succeeded_ids)


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, h_spacing=None, v_spacing=30):
        super().__init__(parent)
        self._items = []
        self._h_spacing = get("card_gap") if h_spacing is None else h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)
    def addItem(self, item): self._items.append(item)
    def count(self): return len(self._items)
    def itemAt(self, index): return self._items[index] if 0 <= index < len(self._items) else None
    def takeAt(self, index): return self._items.pop(index) if 0 <= index < len(self._items) else None
    def expandingDirections(self): return Qt.Orientations(Qt.Orientation(0))
    def hasHeightForWidth(self): return True
    def heightForWidth(self, width): return self._do_layout(QRect(0, 0, width, 0), True)
    def setGeometry(self, rect): super().setGeometry(rect); self._do_layout(rect, False)
    def sizeHint(self): return self.minimumSize()
    def minimumSize(self):
        size = QSize(); margins = self.contentsMargins()
        for item in self._items: size = size.expandedTo(item.minimumSize())
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
    def positions_for_rect(self, rect):
        margins = self.contentsMargins(); effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line_height = effective.x(), effective.y(), 0; positions = {}
        for item in self._items:
            widget_size = item.sizeHint()
            if widget_size.width() <= 0: continue
            next_x = x + widget_size.width()
            if x > effective.x() and next_x > effective.right() + 1:
                x = effective.x(); y += line_height + self._v_spacing; next_x = x + widget_size.width(); line_height = 0
            positions[item] = QRect(QPoint(x, y), widget_size); x = next_x + self._h_spacing; line_height = max(line_height, widget_size.height())
        return positions
    def _do_layout(self, rect, test_only):
        positions = self.positions_for_rect(rect)
        if not test_only:
            for item, geometry in positions.items(): item.setGeometry(geometry)
        if not positions: return self.contentsMargins().bottom()
        return max(g.bottom() for g in positions.values()) - rect.y() + self.contentsMargins().bottom()


class LibraryPage(QWidget):
    work_selected = Signal(object)

    def __init__(self):
        super().__init__()
        self.all_anime = []; self.anime_list = []; self.current_filter = "All"; self.current_sort = "Recently Added"; self._cards = []; self._empty_label = None
        self._sync_thread = None; self._sync_worker = None; self._sync_done_ids = set(); self._sync_failed_ids = set()
        self._resize_timer = QTimer(self); self._resize_timer.setSingleShot(True); self._resize_timer.setInterval(140); self._resize_timer.timeout.connect(self._finish_resize)
        self._resize_layout_was_enabled = True; self._last_target_positions = None; self._animations = []; self._build_shell(); self.refresh()

    def _build_shell(self):
        root = QVBoxLayout(self); root.setContentsMargins(38, 32, 38, 30); root.setSpacing(18)
        header = QHBoxLayout(); title_box = QVBoxLayout(); title_box.setSpacing(2)
        title = QLabel("Library"); title.setStyleSheet(f"font-size:32px;font-weight:850;color:{COLORS['primary']};")
        self.count_label = QLabel("0 titles"); self.count_label.setStyleSheet(f"font-size:12px;color:{COLORS['muted']};")
        title_box.addWidget(title); title_box.addWidget(self.count_label); header.addLayout(title_box); header.addStretch(); root.addLayout(header)
        controls = QFrame(); controls.setStyleSheet(f"QFrame{{background:{COLORS['surface']};border:1px solid {COLORS['border']};border-radius:14px;}}")
        row = QHBoxLayout(controls); row.setContentsMargins(9, 8, 9, 8); row.setSpacing(6); self.filter_buttons = {}
        for name in ["All", "Watching", "Completed", "Planned"]:
            b = QPushButton(name); b.setCheckable(True); b.setCursor(Qt.PointingHandCursor); b.clicked.connect(lambda checked=False, value=name:self._set_filter(value)); self.filter_buttons[name] = b; row.addWidget(b)
        divider = QFrame(); divider.setFixedWidth(1); divider.setStyleSheet(f"background:{COLORS['border']};border:0;"); row.addWidget(divider)
        label = QLabel("SORT"); label.setStyleSheet(f"font-size:10px;font-weight:800;color:{COLORS['muted']};letter-spacing:1px;"); row.addWidget(label)
        self.sort_box = QComboBox(); self.sort_box.addItems(["Recently Added", "Title", "Release Year"]); self.sort_box.setMinimumWidth(150); self.sort_box.currentTextChanged.connect(self._sort_changed); row.addWidget(self.sort_box); row.addStretch(); root.addWidget(controls)
        self.scroll_area = QScrollArea(); self.scroll_area.setWidgetResizable(True); self.scroll_area.setFrameShape(QFrame.NoFrame); self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.container = QWidget(); self.container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum); self.container.installEventFilter(self); self.flow_layout = FlowLayout(self.container)
        self.scroll_area.setWidget(self.container); root.addWidget(self.scroll_area, 1); self._set_filter("All")

    def eventFilter(self, watched, event):
        if watched is self.container and event.type() == QEvent.Resize and self._cards:
            if self.flow_layout.isEnabled(): self._resize_layout_was_enabled = True; self.flow_layout.setEnabled(False)
            self._resize_timer.start()
            target_rects = self.flow_layout.positions_for_rect(self.container.rect()); target_positions = {id(item.widget()):geometry.topLeft() for item,geometry in target_rects.items() if item.widget() is not None}
            if target_positions != self._last_target_positions:
                current_positions = {id(card):QPoint(card.pos()) for card in self._cards}; self._last_target_positions = target_positions
                if get("resize_animation") and get("animation_speed") > 0: self._animate_to_positions(current_positions, target_positions)
                else:
                    self._stop_animations()
                    for card in self._cards:
                        if id(card) in target_positions: card.move(target_positions[id(card)])
        return super().eventFilter(watched, event)

    def refresh(self, retry_failed=True):
        if retry_failed:
            self._sync_failed_ids.clear()
        self._cancel_resize_animation(); self.all_anime = get_library_series(); self._apply_filter(); self._apply_sort(); self._populate(); self._start_relation_sync()

    def _start_relation_sync(self):
        if self._sync_thread is not None and self._sync_thread.isRunning(): return
        connection = get_connection()
        ids = [int(row["id"]) for row in connection.execute("SELECT DISTINCT works.id FROM works JOIN user_library ON user_library.work_id=works.id").fetchall()]
        connected = {int(row["id"]) for row in connection.execute("SELECT DISTINCT source_id AS id FROM work_relations UNION SELECT DISTINCT target_id AS id FROM work_relations").fetchall()}
        connection.close()
        missing = [
            work_id for work_id in ids
            if work_id not in connected
            and work_id not in self._sync_done_ids
            and work_id not in self._sync_failed_ids
        ]
        if not missing: return
        self._sync_thread = QThread(self); self._sync_worker = RelationSyncWorker(missing); self._sync_worker.moveToThread(self._sync_thread)
        self._sync_thread.started.connect(self._sync_worker.run); self._sync_worker.finished.connect(self._relation_sync_finished); self._sync_worker.finished.connect(self._sync_thread.quit); self._sync_thread.finished.connect(self._sync_worker.deleteLater); self._sync_thread.finished.connect(self._sync_thread.deleteLater); self._sync_thread.start()

    def _relation_sync_finished(self, succeeded_ids):
        succeeded_ids = {int(work_id) for work_id in (succeeded_ids or set())}
        attempted_ids = set(self._sync_worker.work_ids) if self._sync_worker is not None else set()
        self._sync_done_ids.update(succeeded_ids)
        self._sync_failed_ids.update(attempted_ids - succeeded_ids)
        self._sync_thread = None; self._sync_worker = None
        self.refresh(retry_failed=False)

    def _auto_bundle_item(self, group):
        members = list(group.get("_series_members") or [])
        if not members:
            work_id = group.get("id")
            members = [group] if work_id is not None else []
        if not members:
            return
        if self._sync_thread is not None and self._sync_thread.isRunning():
            return

        work_ids = [int(member["id"]) for member in members]
        self._sync_thread = QThread(self)
        self._sync_worker = RelationSyncWorker(work_ids)
        self._sync_worker.moveToThread(self._sync_thread)
        self._sync_thread.started.connect(self._sync_worker.run)
        self._sync_worker.finished.connect(self._relation_sync_finished)
        self._sync_worker.finished.connect(self._sync_thread.quit)
        self._sync_thread.finished.connect(self._sync_worker.deleteLater)
        self._sync_thread.finished.connect(self._sync_thread.deleteLater)
        self._sync_thread.start()

    def _delete_item(self, group):
        members = list(group.get("_series_members") or [])
        if not members:
            return

        if len(members) == 1:
            selected_ids = [int(members[0]["id"])]
            selected_title = self._member_title(members[0])
        else:
            options = ["Delete entire bundle"] + [
                f"Delete: {self._member_title(member)}"
                for member in members
            ]
            choice, ok = QInputDialog.getItem(
                self,
                "Delete",
                "Choose what to delete:",
                options,
                0,
                False,
            )
            if not ok:
                return
            if choice == options[0]:
                selected_ids = [int(member["id"]) for member in members]
                selected_title = None
            else:
                index = options.index(choice) - 1
                selected_ids = [int(members[index]["id"])]
                selected_title = self._member_title(members[index])

        if selected_title is None:
            message = (
                f"Delete this bundle and all {len(selected_ids)} entries?\n\n"
                "This permanently removes their local NekoTrack data and cached covers."
            )
        else:
            message = (
                f"Delete “{selected_title}” from NekoTrack?\n\n"
                "This permanently removes its local NekoTrack data and cached cover."
            )

        answer = QMessageBox.question(
            self,
            "Confirm delete",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        deleted = False
        for work_id in selected_ids:
            deleted = delete_work_data(work_id) or deleted
        if deleted:
            self.refresh()

    def _edit_bundle(self, group):
        members = list(group.get("_series_members") or [])
        if len(members) < 2:
            return

        member_ids = [int(member["id"]) for member in members]
        default_member = members[0]
        override = get_bundle_override(member_ids)

        dialog = QDialog(self)
        dialog.setWindowTitle("Edit bundle appearance")
        dialog.setMinimumWidth(540)

        root = QVBoxLayout(dialog)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(16)

        heading = QLabel("Bundle appearance")
        heading.setStyleSheet(
            f"font-size:20px;font-weight:850;color:{COLORS['primary']};"
        )
        root.addWidget(heading)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignTop)
        form.setVerticalSpacing(12)

        custom_title = QCheckBox("Use custom title")
        custom_title.setChecked(bool(override and override["custom_title"]))
        title_edit = QLineEdit(
            str(
                override["custom_title"]
                if override and override["custom_title"]
                else group.get("title") or ""
            )
        )
        title_edit.setPlaceholderText(self._member_title(default_member))
        title_edit.setEnabled(custom_title.isChecked())
        custom_title.toggled.connect(title_edit.setEnabled)

        title_box = QVBoxLayout()
        title_box.addWidget(custom_title)
        title_box.addWidget(title_edit)
        form.addRow("Title", title_box)

        cover_combo = QComboBox()
        cover_combo.addItem(
            f"Automatic — {self._member_title(default_member)}",
            ("default", None),
        )

        selected_cover_id = (
            int(override["cover_work_id"])
            if override and override["cover_work_id"] is not None
            else None
        )
        selected_custom_path = (
            str(override["custom_cover_path"])
            if override and override["custom_cover_path"]
            else None
        )
        selected_index = 0

        for member in members:
            member_id = int(member["id"])
            label = self._member_title(member)
            meta = " · ".join(
                str(value)
                for value in (
                    member["format"] or "",
                    member["start_year"] or "",
                )
                if value
            )
            if meta:
                label = f"{label}  —  {meta}"
            cover_combo.addItem(label, ("member", member_id))
            if selected_cover_id == member_id:
                selected_index = cover_combo.count() - 1

        custom_index = cover_combo.count()
        cover_combo.addItem("Custom image…", ("custom", selected_custom_path))
        if selected_custom_path:
            selected_index = custom_index

        path_label = QLabel(selected_custom_path or "No custom image selected.")
        path_label.setWordWrap(True)
        path_label.setStyleSheet(
            f"color:{COLORS['muted']};font-size:11px;"
        )

        def choose_custom():
            path, _ = QFileDialog.getOpenFileName(
                dialog,
                "Choose bundle cover",
                "",
                "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
            )
            if not path:
                return
            path_label.setText(path)
            cover_combo.setItemData(custom_index, ("custom", path))
            cover_combo.setCurrentIndex(custom_index)

        def cover_changed(index):
            data = cover_combo.itemData(index) or ("default", None)
            path_label.setVisible(data[0] == "custom")
            if data[0] != "custom":
                path_label.setText("No custom image selected.")

        cover_combo.currentIndexChanged.connect(cover_changed)
        cover_combo.setCurrentIndex(selected_index)
        cover_changed(selected_index)

        cover_box = QVBoxLayout()
        cover_box.addWidget(cover_combo)
        choose_button = QPushButton("Choose custom image…")
        choose_button.clicked.connect(choose_custom)
        cover_box.addWidget(choose_button)
        cover_box.addWidget(path_label)
        form.addRow("Cover", cover_box)

        note = QLabel(
            f"Automatic uses the earliest item: {self._member_title(default_member)}."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color:{COLORS['muted']};font-size:11px;"
        )
        form.addRow("", note)
        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        reset = buttons.addButton(
            "Reset appearance",
            QDialogButtonBox.ResetRole,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        def reset_appearance():
            clear_bundle_override(member_ids)
            dialog.reject()
            self.refresh()

        reset.clicked.connect(reset_appearance)
        root.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return

        title = title_edit.text().strip() if custom_title.isChecked() else None
        cover_mode, cover_value = cover_combo.currentData() or ("default", None)
        cover_work_id = None
        custom_cover_path = None

        if cover_mode == "member":
            cover_work_id = int(cover_value)
        elif cover_mode == "custom":
            source_path = str(cover_value or "").strip()
            source = Path(source_path) if source_path else None
            if source is not None and source.is_file():
                bundle_dir = Path("data") / "images" / "bundles"
                bundle_dir.mkdir(parents=True, exist_ok=True)
                destination = bundle_dir / (
                    f"bundle_{int(default_member['id'])}{source.suffix.lower() or '.png'}"
                )
                try:
                    if source.resolve() != destination.resolve():
                        shutil.copy2(source, destination)
                    custom_cover_path = str(destination)
                except Exception:
                    custom_cover_path = str(source)

        if save_bundle_override(
            member_ids,
            int(default_member["id"]),
            custom_title=title,
            cover_work_id=cover_work_id,
            custom_cover_path=custom_cover_path,
        ):
            self.refresh()

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

    def _set_filter(self,value):
        self.current_filter=value
        for name,button in self.filter_buttons.items(): button.setChecked(name==value); button.setStyleSheet(self._filter_style(name==value))
        self._cancel_resize_animation(); self._apply_filter(); self._apply_sort(); self._populate()
    def _filter_style(self,active):
        if active: return f"QPushButton{{background:{COLORS['accent']};color:#101216;border:0;border-radius:9px;padding:8px 15px;font-weight:800;}}"
        return f"QPushButton{{background:transparent;color:{COLORS['secondary']};border:0;border-radius:9px;padding:8px 15px;font-weight:650;}}QPushButton:hover{{background:{COLORS['surface_hover']};color:{COLORS['primary']};}}"
    def _apply_filter(self):
        wanted={"All":None,"Watching":"Watching","Completed":"Completed","Planned":"Planning"}[self.current_filter]; self.anime_list=[x for x in self.all_anime if wanted is None or x["status"]==wanted]
    def _apply_sort(self):
        if self.current_sort=="Title": self.anime_list.sort(key=lambda x:(x["title"] or "").lower())
        elif self.current_sort=="Release Year": self.anime_list.sort(key=lambda x:x["start_year"] or 0,reverse=True)
        else: self.anime_list.sort(key=lambda x:x["id"],reverse=True)
    def _sort_changed(self,value): self.current_sort=value; self._cancel_resize_animation(); self._populate()
    def _clear_cards(self):
        self._cancel_resize_animation()
        while self.flow_layout.count():
            item=self.flow_layout.takeAt(0); widget=item.widget()
            if widget is not None: widget.deleteLater()
        self._cards=[]; self._empty_label=None
    def _populate(self):
        self._clear_cards(); self.count_label.setText(f"{len(self.anime_list)} title{'s' if len(self.anime_list)!=1 else ''}")
        if not self.anime_list:
            empty=QLabel("Nothing here yet\n\nAdd titles from Search to build your collection."); empty.setAlignment(Qt.AlignCenter); empty.setStyleSheet(f"color:{COLORS['muted']};font-size:15px;padding:100px;"); self.flow_layout.addWidget(empty); self._empty_label=empty; return
        for anime in self.anime_list:
            card=WorkCard(anime,mode="library"); card.setSizePolicy(QSizePolicy.Fixed,QSizePolicy.Fixed); card.clicked.connect(self.work_selected); card.auto_bundle_requested.connect(self._auto_bundle_item); card.bundle_edit_requested.connect(self._edit_bundle); card.remove_requested.connect(self._delete_item); self._cards.append(card); self.flow_layout.addWidget(card)
        self.flow_layout.invalidate(); self.flow_layout.activate(); self._last_target_positions={id(card):QPoint(card.pos()) for card in self._cards}
    def _animate_to_positions(self,start_positions,target_positions):
        self._stop_animations(); animations=[]; duration=get("animation_speed")
        for card in self._cards:
            old_pos=start_positions.get(id(card),QPoint(card.pos())); new_pos=target_positions.get(id(card))
            if new_pos is None: continue
            card.move(old_pos)
            if old_pos==new_pos: continue
            animation=QPropertyAnimation(card,b"pos",self); animation.setDuration(duration); animation.setStartValue(old_pos); animation.setEndValue(new_pos); animation.setEasingCurve(QEasingCurve.Type.OutCubic); animations.append(animation); animation.start()
        self._animations=animations
    def _finish_resize(self):
        self._stop_animations(); self.flow_layout.setEnabled(self._resize_layout_was_enabled); self.flow_layout.invalidate(); self.flow_layout.activate(); self._last_target_positions={id(card):QPoint(card.pos()) for card in self._cards}
    def _stop_animations(self):
        for animation in self._animations: animation.stop(); animation.deleteLater()
        self._animations=[]
    def _cancel_resize_animation(self):
        self._resize_timer.stop(); self._stop_animations(); self._last_target_positions=None; self.flow_layout.setEnabled(True); self.flow_layout.invalidate(); self.flow_layout.activate()
