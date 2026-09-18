from collections import OrderedDict

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from api import get_media_details
from database import get_all_relation_cards, get_library_relation_sync_ids, get_connection, save_anime
from ui.theme import COLORS, SPACING
from ui.widgets.relation_card import RelationCard


RELATION_LABELS = {
    "ADAPTATION": "Adaptations",
    "SOURCE": "Source material",
    "PREQUEL": "Prequels",
    "SEQUEL": "Sequels",
    "PARENT": "Parent / origin",
    "SIDE_STORY": "Side stories",
    "CHARACTER": "Shared characters",
    "SUMMARY": "Summaries",
    "ALTERNATIVE": "Alternative versions",
    "SPIN_OFF": "Spin-offs",
    "OTHER": "Other connections",
    "SAME_UNIVERSE": "Same universe",
    "COMPILATION": "Compilations",
    "CONTAINS": "Contains",
}


class RelationSyncWorker(QObject):
    finished = Signal(object)

    def __init__(self, work_ids):
        super().__init__()
        self.work_ids = sorted(set(int(work_id) for work_id in work_ids))

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


class RelationshipPage(QWidget):
    work_selected = Signal(object)

    def __init__(self):
        super().__init__()
        self._all_relations = []
        self._sync_thread = None
        self._sync_worker = None
        self._sync_started = False
        self._sync_failed_ids = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(SPACING["xxl"], SPACING["xxl"], SPACING["xxl"], SPACING["xxl"])
        root.setSpacing(SPACING["lg"])

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("Relations")
        title.setStyleSheet(f"font-size: 30px; font-weight: 800; color: {COLORS['primary']};")
        self.count_label = QLabel("Related works saved locally")
        self.count_label.setStyleSheet(f"font-size: 12px; color: {COLORS['muted']};")
        title_box.addWidget(title)
        title_box.addWidget(self.count_label)
        header.addLayout(title_box)
        header.addStretch()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh)
        header.addWidget(self.refresh_button)
        root.addLayout(header)

        controls = QFrame()
        controls.setStyleSheet(f"QFrame {{ background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 14px; }}")
        controls_row = QHBoxLayout(controls)
        controls_row.setContentsMargins(10, 8, 10, 8)
        controls_row.setSpacing(8)
        self.filter_box = QComboBox()
        self.filter_box.setMinimumWidth(190)
        self.filter_box.currentTextChanged.connect(self._populate)
        controls_row.addWidget(QLabel("TYPE"), 0)
        controls_row.addWidget(self.filter_box)
        controls_row.addStretch()
        root.addWidget(controls)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.container = QWidget()
        self.content = QVBoxLayout(self.container)
        self.content.setContentsMargins(0, 0, 0, 20)
        self.content.setSpacing(12)
        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll, 1)
        self._populate_empty()

    def _populate_empty(self):
        while self.content.count():
            item = self.content.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        label = QLabel("No stored relations yet. Open a title from Search or let Relations sync your library.")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(f"color:{COLORS['muted']};font-size:14px;padding:80px;")
        self.content.addWidget(label)

    def _missing_relation_targets(self):
        connection = get_connection()
        rows = connection.execute("""
            SELECT DISTINCT work_relations.target_id
            FROM work_relations
            LEFT JOIN works ON works.id = work_relations.target_id
            WHERE works.id IS NULL
        """).fetchall()
        connection.close()
        return [int(row["target_id"]) for row in rows]

    def refresh(self, retry_failed=True):
        if retry_failed:
            self._sync_failed_ids.clear()
        rows = get_all_relation_cards()
        self._all_relations = list(rows)
        current = self.filter_box.currentData() if self.filter_box.count() else "All"
        types = OrderedDict()
        for row in rows:
            types[row["relation_type"]] = True
        self.filter_box.blockSignals(True)
        self.filter_box.clear()
        self.filter_box.addItem("All relation types", "All")
        for relation_type in sorted(types, key=lambda value: RELATION_LABELS.get(value, value.replace("_", " ").title())):
            self.filter_box.addItem(RELATION_LABELS.get(relation_type, relation_type.replace("_", " ").title()), relation_type)
        index = self.filter_box.findData(current)
        self.filter_box.setCurrentIndex(index if index >= 0 else 0)
        self.filter_box.blockSignals(False)
        self._populate()

        if not self._sync_started:
            work_ids = get_library_relation_sync_ids()
            work_ids.extend(self._missing_relation_targets())
            work_ids = [work_id for work_id in sorted(set(work_ids)) if work_id not in self._sync_failed_ids]
            if work_ids:
                self._start_relation_sync(work_ids)

    def _populate(self):
        while self.content.count():
            item = self.content.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._all_relations:
            self.count_label.setText("No related works saved locally")
            self._populate_empty()
            return

        selected = self.filter_box.currentData() or "All"
        rows = [row for row in self._all_relations if selected == "All" or row["relation_type"] == selected]
        self.count_label.setText(f"{len(rows)} related connection{'s' if len(rows) != 1 else ''}")

        if not rows:
            label = QLabel("No relations of this type.")
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet(f"color:{COLORS['muted']};font-size:14px;padding:70px;")
            self.content.addWidget(label)
            self.content.addStretch()
            return

        grouped = OrderedDict()
        for row in rows:
            grouped.setdefault(row["relation_type"], []).append(row)

        for relation_type, relation_rows in grouped.items():
            heading = QLabel(RELATION_LABELS.get(relation_type, relation_type.replace("_", " ").title()))
            heading.setStyleSheet(f"font-size:16px;font-weight:800;color:{COLORS['primary']};padding:10px 2px 2px;")
            self.content.addWidget(heading)
            wrapper = QWidget()
            grid = QVBoxLayout(wrapper)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(8)
            for row in relation_rows:
                card = RelationCard(dict(row))
                card.setToolTip(
                    f"{row['source_title'] or 'Unknown work'} → "
                    f"{RELATION_LABELS.get(relation_type, relation_type.replace('_', ' ').title())} → "
                    f"{row['title'] or 'Unknown work'}"
                )
                card.clicked.connect(self.work_selected)
                grid.addWidget(card)
            self.content.addWidget(wrapper)
        self.content.addStretch()

    def _start_relation_sync(self, work_ids):
        if self._sync_thread is not None and self._sync_thread.isRunning():
            return
        self._sync_started = True
        self.count_label.setText(f"Syncing {len(work_ids)} related title{'s' if len(work_ids) != 1 else ''}…")
        self._sync_thread = QThread(self)
        self._sync_worker = RelationSyncWorker(work_ids)
        self._sync_worker.moveToThread(self._sync_thread)
        self._sync_thread.started.connect(self._sync_worker.run)
        self._sync_worker.finished.connect(self._relation_sync_finished)
        self._sync_worker.finished.connect(self._sync_thread.quit)
        self._sync_thread.finished.connect(self._sync_worker.deleteLater)
        self._sync_thread.finished.connect(self._sync_thread.deleteLater)
        self._sync_thread.start()

    def _relation_sync_finished(self, succeeded_ids):
        succeeded_ids = {int(work_id) for work_id in (succeeded_ids or set())}
        attempted_ids = set(self._sync_worker.work_ids) if self._sync_worker is not None else set()
        self._sync_failed_ids.update(attempted_ids - succeeded_ids)
        self._sync_started = False
        self._sync_thread = None
        self._sync_worker = None
        self.refresh(retry_failed=False)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
