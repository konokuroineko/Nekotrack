import shutil
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from api import get_media_details
from database import (
    clear_bundle_override,
    delete_work_data,
    get_all_library,
    get_bundle_override,
    get_connection,
    save_anime,
    save_bundle_override,
)
from series import get_library_series
from ui.theme import COLORS


class AutoBundleWorker(QObject):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, work_ids):
        super().__init__()
        self.work_ids = [int(work_id) for work_id in work_ids]

    def run(self):
        succeeded = set()
        try:
            for work_id in self.work_ids:
                try:
                    details = get_media_details(work_id)
                    if details:
                        save_anime(details)
                        succeeded.add(work_id)
                except Exception:
                    continue
            self.finished.emit(succeeded)
        except Exception as error:
            self.error.emit(str(error))


class ManageLibraryPage(QWidget):
    changed = Signal()
    work_selected = Signal(object)

    def __init__(self):
        super().__init__()
        self.groups = []
        self._thread = None
        self._worker = None
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(38, 32, 38, 30)
        root.setSpacing(18)

        title = QLabel("Manage Library")
        title.setStyleSheet(
            f"font-size:32px;font-weight:850;color:{COLORS['primary']};"
        )
        root.addWidget(title)

        subtitle = QLabel(
            "Manage bundles, refresh AniList relationships, change bundle artwork, and delete local entries."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            f"font-size:12px;color:{COLORS['muted']};"
        )
        root.addWidget(subtitle)

        controls = QFrame()
        controls.setStyleSheet(
            f"QFrame{{background:{COLORS['surface']};border:1px solid {COLORS['border']};border-radius:14px;}}"
        )
        controls_row = QHBoxLayout(controls)
        controls_row.setContentsMargins(10, 9, 10, 9)
        controls_row.setSpacing(8)

        auto_all = QPushButton("Auto Bundle All")
        auto_all.setCursor(Qt.PointingHandCursor)
        auto_all.clicked.connect(self._auto_bundle_all)
        controls_row.addWidget(auto_all)

        refresh = QPushButton("Refresh")
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.clicked.connect(self.refresh)
        controls_row.addWidget(refresh)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color:{COLORS['muted']};font-size:11px;")
        controls_row.addWidget(self.status_label)
        controls_row.addStretch()

        root.addWidget(controls)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.container = QWidget()
        self.rows = QVBoxLayout(self.container)
        self.rows.setContentsMargins(0, 0, 0, 20)
        self.rows.setSpacing(10)
        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll, 1)

    def refresh(self):
        self.groups = list(get_library_series())
        while self.rows.count():
            item = self.rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not self.groups:
            empty = QLabel("Your Library is empty.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color:{COLORS['muted']};font-size:15px;padding:80px;"
            )
            self.rows.addWidget(empty)
            return

        for group in self.groups:
            self.rows.addWidget(self._make_row(group))
        self.rows.addStretch(1)

    def _make_row(self, group):
        members = list(group.get("_series_members") or [])
        bundle = len(members) > 1

        row = QFrame()
        row.setStyleSheet(
            f"""
            QFrame#manageRow {{
                background:{COLORS['surface']};
                border:1px solid {COLORS['border']};
                border-radius:14px;
            }}
            QFrame#manageRow:hover {{
                border-color:{COLORS['border_hover']};
            }}
            QLabel#manageTitle {{
                color:{COLORS['primary']};
                font-size:16px;
                font-weight:800;
            }}
            QLabel#manageMeta {{
                color:{COLORS['muted']};
                font-size:11px;
            }}
            QPushButton#manageAction {{
                background:{COLORS['surface_alt']};
                color:{COLORS['secondary']};
                border:1px solid {COLORS['border']};
                border-radius:8px;
                padding:8px 11px;
                font-weight:750;
            }}
            QPushButton#manageAction:hover {{
                background:{COLORS['surface_hover']};
                color:{COLORS['primary']};
                border-color:{COLORS['border_hover']};
            }}
            QPushButton#deleteAction:hover {{
                color:#d85b5b;
                border-color:#8a3f3f;
            }}
            """
        )
        row.setObjectName("manageRow")

        layout = QHBoxLayout(row)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(14)

        info = QVBoxLayout()
        info.setSpacing(4)

        title = QLabel(str(group.get("title") or "Untitled"))
        title.setObjectName("manageTitle")
        info.addWidget(title)

        summary = str(group.get("_bundle_summary") or "")
        if bundle:
            member_text = f"{len(members)} entries"
            if summary:
                member_text += f" · {summary}"
        else:
            member_text = "Not bundled"

        meta = QLabel(
            " · ".join(
                value
                for value in (
                    member_text,
                    str(group.get("format") or ""),
                    str(group.get("status") or ""),
                )
                if value
            )
        )
        meta.setObjectName("manageMeta")
        info.addWidget(meta)

        if bundle:
            member_names = ", ".join(self._member_title(member) for member in members)
            members_label = QLabel(member_names)
            members_label.setObjectName("manageMeta")
            members_label.setWordWrap(True)
            info.addWidget(members_label)

        layout.addLayout(info, 1)

        auto = QPushButton("Auto Bundle")
        auto.setObjectName("manageAction")
        auto.clicked.connect(
            lambda checked=False, g=group: self._auto_bundle_group(g)
        )
        layout.addWidget(auto)

        if bundle:
            edit = QPushButton("Edit Appearance")
            edit.setObjectName("manageAction")
            edit.clicked.connect(
                lambda checked=False, g=group: self._edit_bundle(g)
            )
            layout.addWidget(edit)

        delete_button = QPushButton("Delete")
        delete_button.setObjectName("deleteAction")
        delete_button.setProperty("deleteAction", True)
        delete_button.setCursor(Qt.PointingHandCursor)
        delete_button.clicked.connect(
            lambda checked=False, g=group: self._delete_group(g)
        )
        layout.addWidget(delete_button)

        return row

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

    def _library_ids(self):
        connection = get_connection()
        rows = connection.execute(
            """
            SELECT works.id
            FROM works
            JOIN user_library ON user_library.work_id = works.id
            ORDER BY works.id
            """
        ).fetchall()
        connection.close()
        return [int(row["id"]) for row in rows]

    def _start_auto_bundle(self, work_ids):
        if self._thread is not None and self._thread.isRunning():
            return
        work_ids = [int(work_id) for work_id in work_ids]
        if not work_ids:
            return

        self._thread = QThread(self)
        self._worker = AutoBundleWorker(work_ids)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._auto_bundle_finished)
        self._worker.error.connect(self._auto_bundle_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self.status_label.setText(f"Refreshing {len(work_ids)} library entr{'y' if len(work_ids) == 1 else 'ies'}…")
        self._thread.start()

    def _auto_bundle_group(self, group):
        members = group.get("_series_members") or []
        self._start_auto_bundle([member["id"] for member in members])

    def _auto_bundle_all(self):
        self._start_auto_bundle(self._library_ids())

    def _auto_bundle_finished(self, succeeded_ids):
        succeeded_count = len(succeeded_ids or set())
        self._thread = None
        self._worker = None
        self.refresh()
        self.status_label.setText(
            f"Refreshed {succeeded_count} entr{'y' if succeeded_count == 1 else 'ies'}; automatic bundles rebuilt."
        )
        self.changed.emit()

    def _auto_bundle_error(self, message):
        self._thread = None
        self._worker = None
        self.status_label.setText("Auto Bundle failed.")
        QMessageBox.warning(self, "Auto Bundle", f"Could not refresh relations: {message}")

    def _delete_group(self, group):
        members = list(group.get("_series_members") or [])
        if not members:
            return

        if len(members) == 1:
            member_ids = [int(members[0]["id"])]
            selected = self._member_title(members[0])
            mode = "entry"
        else:
            options = ["Delete entire bundle"] + [
                f"Delete: {self._member_title(member)}"
                for member in members
            ]
            selected, ok = QInputDialog.getItem(
                self,
                "Delete",
                "Choose what to delete:",
                options,
                0,
                False,
            )
            if not ok:
                return
            if selected == options[0]:
                member_ids = [int(member["id"]) for member in members]
                mode = "bundle"
            else:
                index = options.index(selected) - 1
                member_ids = [int(members[index]["id"])]
                selected = self._member_title(members[index])
                mode = "entry"

        if mode == "bundle":
            message = (
                f"Delete this bundle and all {len(member_ids)} local entries?\n\n"
                "This permanently removes their local NekoTrack data and cached covers."
            )
        else:
            message = (
                f"Delete “{selected}” from NekoTrack?\n\n"
                "This permanently removes its local data and cached cover."
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
        for work_id in member_ids:
            deleted = delete_work_data(work_id) or deleted

        if deleted:
            self.refresh()
            self.changed.emit()

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

        custom_title_check = QCheckBox("Use custom title")
        custom_title_check.setChecked(bool(override and override["custom_title"]))
        title_edit = QLineEdit(
            str(
                override["custom_title"]
                if override and override["custom_title"]
                else group.get("title") or ""
            )
        )
        title_edit.setPlaceholderText(self._member_title(default_member))
        title_edit.setEnabled(custom_title_check.isChecked())
        custom_title_check.toggled.connect(title_edit.setEnabled)
        title_box = QVBoxLayout()
        title_box.setSpacing(6)
        title_box.addWidget(custom_title_check)
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
            fmt = member["format"] or ""
            year = member["start_year"] or ""
            meta = " · ".join(str(value) for value in (fmt, year) if value)
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
        cover_box.setSpacing(6)
        cover_box.addWidget(cover_combo)
        choose = QPushButton("Choose custom image…")
        choose.clicked.connect(choose_custom)
        cover_box.addWidget(choose)
        cover_box.addWidget(path_label)
        form.addRow("Cover", cover_box)

        note = QLabel(
            f"Automatic uses the earliest item in the bundle: {self._member_title(default_member)}."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color:{COLORS['muted']};font-size:11px;"
        )
        root.addWidget(note)
        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        reset_button = buttons.addButton(
            "Reset appearance",
            QDialogButtonBox.ResetRole,
        )

        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        def reset():
            clear_bundle_override(member_ids)
            dialog.done(QDialog.Rejected)
            self.refresh()
            self.changed.emit()

        reset_button.clicked.connect(reset)
        root.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return

        title = title_edit.text().strip() if custom_title_check.isChecked() else None
        cover_mode, cover_value = cover_combo.currentData() or ("default", None)

        cover_work_id = None
        custom_cover_path = None

        if cover_mode == "member":
            cover_work_id = int(cover_value)
        elif cover_mode == "custom":
            source_path = str(cover_value or "").strip()
            if source_path:
                source = Path(source_path)
                if source.is_file():
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
            self.changed.emit()

    def closeEvent(self, event):
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(1500)
        super().closeEvent(event)
