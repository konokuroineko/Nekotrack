from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, Signal, QEvent, QTimer, QPropertyAnimation, QEasingCurve, QThread
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget, QLayout

from api import get_media_details
from database import get_all_library, get_connection, save_anime
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
