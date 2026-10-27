import shutil
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, Signal, QEvent, QTimer, QPropertyAnimation, QEasingCurve, QThread, QUrl
from PySide6.QtGui import QColor
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget, QLayout

from api import get_media_relations_batch
from diagnostics import diagnostic_context, diagnostic_field, log_event, log_exception
from database import (
    clear_bundle_override,
    delete_work_data,
    get_automatic_bundle_memberships,
    get_bundle_override,
    get_connection,
    save_anime,
    save_automatic_bundle_membership,
    save_bundle_override,
)
from series import get_library_series, group_media_results
from ui.qml_bridge import QmlApplicationBridge
from ui.preferences import get
from ui.theme import COLORS, surface_rgba
from ui.widgets.work_card import WorkCard


def pending_relation_sync_ids(work_ids, checked_ids=(), failed_ids=()):
    """Return library IDs whose full relation snapshots have not been checked."""
    all_ids = {int(work_id) for work_id in work_ids}
    checked = {int(work_id) for work_id in checked_ids}
    failed = {int(work_id) for work_id in failed_ids}
    return sorted(all_ids - checked - failed)



def _backfill_automatic_bundle_memberships(work_ids, details_by_id):
    """Recover bundle snapshots for older libraries after a complete relation sync."""
    ids = {int(work_id) for work_id in work_ids}
    if len(ids) < 2 or not ids.issubset(details_by_id):
        return 0

    # Never overwrite a bundle explicitly captured from Search by the current
    # app version. Only backfill members that predate that persisted snapshot.
    existing_memberships = get_automatic_bundle_memberships(ids)
    protected_ids = {
        int(row["work_id"])
        for row in existing_memberships
        if int(row["work_id"]) in ids
    }

    results = []
    for work_id in sorted(ids):
        details = details_by_id.get(work_id)
        relations = details.get("relations") if isinstance(details, dict) else None
        if (
            not isinstance(details, dict)
            or details.get("id") != work_id
            or not isinstance(relations, dict)
            or not isinstance(relations.get("edges"), list)
        ):
            return 0
        results.append(details)

    # Reuse Search's own bundler against the complete set of synced Library
    # entries. It performs no new provider requests with enrich=False.
    groups = group_media_results(results, enrich=False)
    saved_count = 0
    for group in groups:
        members = group.get("_series_members") or [group]
        member_ids = sorted({
            int(member["id"])
            for member in members
            if isinstance(member, dict)
            and member.get("id") is not None
            and int(member["id"]) in ids
        })
        if len(member_ids) < 2 or protected_ids.intersection(member_ids):
            continue

        bundle_id = int(group.get("id") or member_ids[0])
        if bundle_id not in member_ids:
            bundle_id = member_ids[0]
        if save_automatic_bundle_membership(bundle_id, member_ids):
            saved_count += 1
            protected_ids.update(member_ids)

    if saved_count:
        log_event(
            "library.relation_sync.memberships_backfilled",
            input_count=len(ids),
            group_count=saved_count,
        )
    return saved_count


class RelationSyncWorker(QObject):
    finished = Signal(object)

    def __init__(self, work_ids, stop_event=None):
        super().__init__()
        self.work_ids = sorted({int(work_id) for work_id in work_ids})
        self.stop_event = stop_event

    def run(self):
        succeeded_ids = set()
        details_by_id = {}
        batch_completed = False
        try:
            fetched = get_media_relations_batch(self.work_ids)
            if isinstance(fetched, dict):
                details_by_id = fetched
            batch_completed = True
            log_event(
                "library.relation_sync.batch_completed",
                requested_count=len(self.work_ids),
                returned_count=len(details_by_id),
            )
        except Exception as error:
            # Don't turn a batch-wide AniList 429 into a separate retry sequence
            # for every Library item. Let a later refresh retry the batch.
            log_exception(
                "library.relation_sync.batch_failed",
                error,
                requested_count=len(self.work_ids),
            )

        for work_id in self.work_ids:
            if self.stop_event is not None and self.stop_event.is_set():
                break
            with diagnostic_context(workflow="library_relation_sync", work_id=work_id):
                log_event("library.relation_sync.item_started")
                details = details_by_id.get(work_id)
                if details is None and not batch_completed:
                    log_event(
                        "library.relation_sync.item_deferred_after_batch_failure",
                        expected_work_id=work_id,
                    )
                    continue
                if details is None:
                    try:
                        individual = get_media_relations_batch([work_id])
                        details = (
                            individual.get(work_id)
                            if isinstance(individual, dict)
                            else None
                        )
                    except Exception as error:
                        log_exception("library.relation_sync.item_failed", error)
                        continue

                if not isinstance(details, dict) or details.get("id") != work_id:
                    log_event(
                        "library.relation_sync.item_missing_details",
                        expected_work_id=work_id,
                    )
                    continue

                relation_data = details.get("relations")
                relation_edges = (
                    relation_data.get("edges")
                    if isinstance(relation_data, dict)
                    else None
                )
                if not isinstance(relation_edges, list):
                    log_event("library.relation_sync.item_missing_relation_snapshot")
                    continue

                try:
                    save_anime(details)
                except Exception as error:
                    log_exception("library.relation_sync.item_failed", error)
                    continue

                details_by_id[work_id] = details
                succeeded_ids.add(work_id)
                log_event(
                    "library.relation_sync.item_completed",
                    media_type=details.get("type"),
                    media_format=details.get("format"),
                    relation_count=len(relation_edges),
                    relation_types=sorted({
                        str(edge.get("relationType") or "")
                        for edge in relation_edges
                        if isinstance(edge, dict)
                    })[:30],
                )

        failed_ids = sorted(set(self.work_ids) - succeeded_ids)
        if not failed_ids:
            try:
                _backfill_automatic_bundle_memberships(
                    self.work_ids,
                    details_by_id,
                )
            except Exception as error:
                log_exception(
                    "library.relation_sync.membership_backfill_failed",
                    error,
                    library_work_count=len(self.work_ids),
                )

        log_event(
            "library.relation_sync.worker_completed",
            attempted_count=len(self.work_ids),
            succeeded_ids=sorted(succeeded_ids)[:100],
            failed_ids=failed_ids[:100],
        )
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

    def __init__(self, defer_initial_refresh=False):
        super().__init__()
        self.all_anime = []; self.anime_list = []; self.current_filter = "All"; self._cards = []; self._empty_label = None
        self._sync_thread = None; self._sync_worker = None; self._sync_done_ids = set(); self._sync_failed_ids = set()
        self._sync_threads = []; self._shutdown_event = threading.Event(); self._closing = False
        self._resize_timer = QTimer(self); self._resize_timer.setSingleShot(True); self._resize_timer.setInterval(140); self._resize_timer.timeout.connect(self._finish_resize)
        self._resize_layout_was_enabled = True; self._last_target_positions = None; self._animations = []
        # The app-level QML shell owns the visible Library route. Keep this
        # QWidget page only as a compatibility controller for bundle dialogs,
        # relation sync and the original interface fallback.
        self._defer_qml_load = False
        self._qml_disabled = True
        self._qml_failure_queued = False
        self.qml_bridge = None
        self.qml_widget = None
        self._using_qml = False
        self._build_legacy_shell()
        if defer_initial_refresh:
            # MainWindow opens on Home. Do not query/group the entire Library or
            # create all its cards before the first frame; _page_changed refreshes
            # the Library as soon as the user navigates to it.
            log_event("library.initial_refresh_deferred")
        else:
            # Standalone LibraryPage callers retain the original eager behavior.
            self.refresh()

    def _build_shell(self):
        self.qml_bridge = None
        self.qml_widget = None
        self._using_qml = False
        if self._qml_disabled:
            self._build_legacy_shell()
            return

        bridge = None
        quick = None
        try:
            bridge = QmlApplicationBridge(
                parent=self,
                library_loader=lambda: self.all_anime,
                auto_refresh=False,
            )
            quick = QQuickWidget(self)
            quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
            quick.setClearColor(QColor(0, 0, 0, 0))
            quick.rootContext().setContextProperty("qmlBridge", bridge)

            # Connect this before loading QML; Qt Quick may terminate the host
            # process on a scene-graph failure without an explicit handler.
            quick.statusChanged.connect(self._qml_status_changed)
            scene_graph_error = getattr(quick, "sceneGraphError", None)
            if scene_graph_error is not None:
                scene_graph_error.connect(self._qml_scene_graph_error)

            self.qml_bridge = bridge
            self.qml_widget = quick
            self._using_qml = True
            bridge.openWorkRequested.connect(self._open_qml_work)
            bridge.editBundleRequested.connect(self._edit_qml_bundle)
            bridge.deleteWorkRequested.connect(self._delete_qml_work)
            bridge.filterChanged.connect(self._on_qml_filter_changed)

            root = self.layout()
            if root is None:
                root = QVBoxLayout(self)
            else:
                while root.count():
                    item = root.takeAt(0)
                    widget = item.widget()
                    if widget is not None:
                        widget.setParent(None)
                        widget.deleteLater()
            root.setContentsMargins(0, 0, 0, 0)
            root.setSpacing(0)
            root.addWidget(quick)

            qml_path = Path(__file__).resolve().parents[1] / "qml" / "LibraryView.qml"
            quick.setSource(QUrl.fromLocalFile(str(qml_path)))
            if self._qml_disabled or quick.status() == QQuickWidget.Status.Error:
                self._queue_qml_fallback(
                    "QML Library view failed while loading: "
                    + "; ".join(error.toString() for error in quick.errors())
                )
                return

            log_event("qml_bridge.library_view_loaded")
            return
        except Exception as error:
            self._qml_disabled = True
            self._using_qml = False
            self.qml_widget = None
            self.qml_bridge = None
            if quick is not None:
                quick.deleteLater()
            if bridge is not None:
                bridge.deleteLater()
            log_exception("qml_bridge.library_view_unavailable", error)

        self._build_legacy_shell()

    def _build_legacy_shell(self):
        root = self.layout()
        if root is None:
            root = QVBoxLayout(self)
        else:
            while root.count():
                item = root.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.setParent(None)
                    widget.deleteLater()
        root.setContentsMargins(38, 32, 38, 30)
        root.setSpacing(18)
        header = QHBoxLayout(); title_box = QVBoxLayout(); title_box.setSpacing(2)
        title = QLabel("Library")
        self.title_label = title
        title.setStyleSheet(f"font-size:32px;font-weight:850;color:{COLORS['primary']};")
        self.count_label = QLabel("0 titles"); self.count_label.setStyleSheet(f"font-size:12px;color:{COLORS['muted']};")
        title_box.addWidget(title); title_box.addWidget(self.count_label); header.addLayout(title_box); header.addStretch(); root.addLayout(header)
        controls = QFrame()
        controls.setObjectName("libraryFilters")
        self.filter_controls = controls
        controls.setStyleSheet(
            f"QFrame#libraryFilters{{background:{surface_rgba('surface')};border:none;border-radius:14px;}}"
        )
        row = QHBoxLayout(controls); row.setContentsMargins(9, 8, 9, 8); row.setSpacing(6); self.filter_buttons = {}
        for name in ["All", "Watching", "Completed", "Planned"]:
            b = QPushButton(name)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda checked=False, value=name:self._set_filter(value))
            b.setObjectName("libraryFilterButton")
            b.setStyleSheet(self._filter_style(name == "All"))
            self.filter_buttons[name] = b
            row.addWidget(b)
        row.addStretch(); root.addWidget(controls)
        self.scroll_area = QScrollArea(); self.scroll_area.setWidgetResizable(True); self.scroll_area.setFrameShape(QFrame.NoFrame); self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.container = QWidget(); self.container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum); self.container.installEventFilter(self); self.flow_layout = FlowLayout(self.container)
        self.scroll_area.setWidget(self.container); root.addWidget(self.scroll_area, 1); self._set_filter("All")

    def _group_for_qml_work(self, work_id):
        def numeric_id(value):
            if isinstance(value, bool):
                return None
            try:
                return int(value)
            except (TypeError, ValueError, OverflowError):
                return None

        target = numeric_id(work_id)
        if target is None or target == 0:
            return None
        for group in self.all_anime:
            if numeric_id(group.get("id")) == target:
                return group
        for group in self.all_anime:
            for member in group.get("_series_members") or []:
                if numeric_id(member.get("id")) == target:
                    return group
        return None

    def _open_qml_work(self, work_id):
        group = self._group_for_qml_work(work_id)
        if group is not None:
            self.work_selected.emit(group)

    def _edit_qml_bundle(self, work_id):
        group = self._group_for_qml_work(work_id)
        if group is not None and len(group.get("_series_members") or []) > 1:
            self._edit_bundle(group)

    def _delete_qml_work(self, work_id):
        group = self._group_for_qml_work(work_id)
        if group is not None:
            self._delete_item(group)

    def _on_qml_filter_changed(self, value):
        self.current_filter = value

    def _queue_qml_fallback(self, reason, *, scene_graph_error=False):
        """Queue one safe fallback rather than allowing Qt Quick to exit the process."""
        if self._qml_failure_queued or (self._qml_disabled and self.qml_widget is None):
            return
        self._qml_failure_queued = True
        self._qml_disabled = True
        log_event(
            "qml_bridge.library_view_fallback_queued",
            reason=str(reason or "")[:2000],
            scene_graph_error=bool(scene_graph_error),
        )
        QTimer.singleShot(0, self._fallback_to_legacy)

    def _qml_scene_graph_error(self, error, message):
        """Handle Qt Quick renderer errors before Qt's fatal default is invoked."""
        self._queue_qml_fallback(
            f"Qt Quick scene-graph error {error}: {message}",
            scene_graph_error=True,
        )

    def _qml_status_changed(self, status):
        if status != QQuickWidget.Status.Error:
            return
        errors = []
        if self.qml_widget is not None:
            errors = [error.toString() for error in self.qml_widget.errors()]
        self._queue_qml_fallback(
            "QML Library view load failed: " + "; ".join(errors[:20])
        )

    def _fallback_to_legacy(self):
        previous_filter = self.current_filter
        layout = self.layout()
        if layout is not None and self.qml_widget is not None:
            layout.removeWidget(self.qml_widget)
            self.qml_widget.setParent(None)
            self.qml_widget.deleteLater()
        if self.qml_bridge is not None:
            self.qml_bridge.deleteLater()
        self.qml_widget = None
        self.qml_bridge = None
        self._using_qml = False
        self._qml_failure_queued = False
        self._build_legacy_shell()
        self._set_filter(
            previous_filter
            if previous_filter in ("All", "Watching", "Completed", "Planned")
            else "All"
        )
        self._apply_filter()
        self._populate()

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
        log_event("library.refresh.started", retry_failed=bool(retry_failed))
        if retry_failed:
            self._sync_failed_ids.clear()
        if not self._using_qml:
            self._cancel_resize_animation()
        self.all_anime = get_library_series()
        group_summary = []
        library_member_count = 0
        for group in self.all_anime[:100]:
            members = diagnostic_field(group, "_series_members") or [group]
            library_member_count += len(members)
            representative_title = diagnostic_field(group, "title")
            if isinstance(representative_title, dict):
                representative_title = (
                    representative_title.get("english")
                    or representative_title.get("romaji")
                    or representative_title.get("native")
                )
            group_summary.append({
                "representative_id": diagnostic_field(group, "id"),
                "representative_title": representative_title,
                "member_count": len(members),
                "members": [
                    {
                        "id": diagnostic_field(member, "id"),
                        "title": diagnostic_field(member, "title"),
                        "type": diagnostic_field(member, "type"),
                        "format": diagnostic_field(member, "format"),
                    }
                    for member in members[:50]
                ],
            })
        log_event(
            "library.refresh.grouped",
            group_count=len(self.all_anime),
            member_count=library_member_count,
            groups=group_summary,
        )
        self._apply_filter()
        self._populate()
        self._start_relation_sync()
        log_event("library.refresh.completed", visible_group_count=len(self.all_anime))

    def request_shutdown(self):
        """Stop scheduling relation work and let the active worker finish safely."""
        self._closing = True
        self._shutdown_event.set()
        for thread in list(self._sync_threads):
            try:
                thread.quit()
            except RuntimeError:
                pass

    def has_running_workers(self):
        for thread in list(self._sync_threads):
            try:
                if thread.isRunning():
                    return True
            except RuntimeError:
                continue
        return False

    def _relation_thread_finished(self, thread):
        if thread in self._sync_threads:
            self._sync_threads.remove(thread)

    def _start_relation_sync(self):
        if self._closing:
            return
        if self._sync_thread is not None and self._sync_thread.isRunning():
            log_event("library.relation_sync.already_running")
            return
        connection = get_connection()
        try:
            ids = [
                int(row["id"])
                for row in connection.execute(
                    "SELECT DISTINCT works.id FROM works "
                    "JOIN user_library ON user_library.work_id=works.id"
                ).fetchall()
            ]
        finally:
            connection.close()
        pending = pending_relation_sync_ids(
            ids,
            checked_ids=self._sync_done_ids,
            failed_ids=self._sync_failed_ids,
        )
        log_event(
            "library.relation_sync.plan",
            library_work_count=len(ids),
            library_work_ids=ids[:100],
            pending_relation_ids=pending[:100],
            pending_relation_count=len(pending),
            already_checked_ids=sorted(self._sync_done_ids)[:100],
            previously_failed_ids=sorted(self._sync_failed_ids)[:100],
        )
        if not pending:
            return
        self._sync_thread = QThread(self)
        self._sync_worker = RelationSyncWorker(pending, self._shutdown_event)
        self._sync_worker.moveToThread(self._sync_thread)
        self._sync_thread.started.connect(self._sync_worker.run)
        self._sync_worker.finished.connect(self._relation_sync_finished)
        self._sync_worker.finished.connect(self._sync_thread.quit)
        self._sync_threads.append(self._sync_thread)
        self._sync_thread.finished.connect(
            lambda t=self._sync_thread: self._relation_thread_finished(t)
        )
        self._sync_thread.finished.connect(self._sync_worker.deleteLater)
        self._sync_thread.finished.connect(self._sync_thread.deleteLater)
        self._sync_thread.start()

    def _relation_sync_finished(self, succeeded_ids):
        succeeded_ids = {int(work_id) for work_id in (succeeded_ids or set())}
        attempted_ids = set(self._sync_worker.work_ids) if self._sync_worker is not None else set()
        failed_ids = attempted_ids - succeeded_ids
        log_event(
            "library.relation_sync.finished",
            attempted_count=len(attempted_ids),
            succeeded_ids=sorted(succeeded_ids)[:100],
            failed_ids=sorted(failed_ids)[:100],
        )
        self._sync_done_ids.update(succeeded_ids)
        self._sync_failed_ids.update(failed_ids)
        self._sync_thread = None
        self._sync_worker = None
        if self._closing:
            return
        self.refresh(retry_failed=False)

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
        self._cancel_resize_animation(); self._apply_filter(); self._populate()
    def refresh_theme(self):
        if hasattr(self, "filter_controls"):
            self.filter_controls.setStyleSheet(
                f"QFrame#libraryFilters{{background:{surface_rgba('surface')};border:none;border-radius:14px;}}"
            )
        if hasattr(self, "title_label"):
            self.title_label.setStyleSheet(
                f"font-size:32px;font-weight:850;color:{COLORS['primary']};"
            )
        if hasattr(self, "count_label"):
            self.count_label.setStyleSheet(
                f"font-size:12px;color:{COLORS['muted']};"
            )
        if hasattr(self, "filter_buttons"):
            self._apply_filter_style_all()
        for card in getattr(self, "_cards", []):
            refresh = getattr(card, "refresh_theme", None)
            if refresh is not None:
                refresh()

    def _apply_filter_style_all(self):
        for name, button in getattr(self, "filter_buttons", {}).items():
            button.setStyleSheet(self._filter_style(name == self.current_filter))

    def _filter_style(self,active):
        focus = (
            f"QPushButton#libraryFilterButton:focus{{"
            f"background:{surface_rgba('surface_hover')};"
            f"border:1px solid {COLORS['nav_selected_frame']};"
            "outline:none;}"
        )
        if active:
            return (
                f"QPushButton#libraryFilterButton{{background:{surface_rgba('accent_soft')};"
                f"color:{COLORS['nav_selected_text']};"
                f"border:1px solid {COLORS['nav_selected_frame']};"
                f"border-radius:9px;padding:8px 15px;font-weight:800;}}"
                f"QPushButton#libraryFilterButton:hover{{background:{surface_rgba('surface')};}}"
                f"{focus}"
            )
        return (
            f"QPushButton#libraryFilterButton{{background:transparent;color:{COLORS['secondary']};"
            f"border:1px solid transparent;border-radius:9px;padding:8px 15px;font-weight:650;}}"
            f"QPushButton#libraryFilterButton:hover{{background:{surface_rgba('surface_hover')};"
            f"color:{COLORS['nav_selected_text']};"
            f"border-color:{COLORS['nav_selected_frame']};}}"
            f"{focus}"
        )
    def _apply_filter(self):
        wanted={"All":None,"Watching":"Watching","Completed":"Completed","Planned":"Planning"}[self.current_filter]; self.anime_list=[x for x in self.all_anime if wanted is None or x["status"]==wanted]
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
            card=WorkCard(anime,mode="library"); card.setSizePolicy(QSizePolicy.Fixed,QSizePolicy.Fixed); card.clicked.connect(self.work_selected); self._cards.append(card); self.flow_layout.addWidget(card)
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
