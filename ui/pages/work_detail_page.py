from pathlib import Path

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QPixmap, QPainter, QPainterPath
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QInputDialog, QMessageBox, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget
)

from database import (
    add_manual_bundle_link, get_characters, get_episodes,
    get_manual_bundle_partners, get_relations, get_staff, get_work,
    remove_manual_bundle_link, save_cover_path, set_episode_progress, set_episode_watched,
)
from series import get_library_series
from ui.theme import COLORS, muted_label_stylesheet
from ui.widgets.character_card import CharacterCard
from ui.widgets.person_card import PersonCard
from ui.widgets.relation_card import RelationCard


IMAGE_DIRECTORY = Path("data") / "images" / "works"


class WorkDetailPage(QWidget):
    back_requested = Signal()
    person_selected = Signal(object)
    character_selected = Signal(object)
    relation_selected = Signal(object)
    bundle_changed = Signal()

    _cover_cache = {}
    _cover_failures = set()

    def __init__(self):
        super().__init__()
        self.work = None
        self._cover_manager = QNetworkAccessManager(self)
        self._cover_reply = None
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.scroll_area)

    def set_work(self, work):
        self.work = work
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
            QFrame#hero {{ background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 22px; }}
            QFrame#section {{ background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 18px; }}
            QFrame#episode {{ background: {COLORS['surface_alt']}; border: 1px solid {COLORS['border']}; border-radius: 10px; }}
            QFrame#episode:hover {{ border-color: {COLORS['border_hover']}; }}
            QFrame#progressTrack {{ background: {COLORS['border']}; border: 0; border-radius: 5px; }}
            QFrame#progressFill {{ background: {COLORS['accent']}; border: 0; border-radius: 5px; }}
            QSpinBox#episodeCounter {{ background: {COLORS['background_alt']}; color: {COLORS['primary']}; border: 1px solid {COLORS['border_hover']}; border-radius: 10px; padding: 8px 12px; font-size: 18px; font-weight: 850; min-width: 92px; }}
            QSpinBox#episodeCounter:focus {{ border-color: {COLORS['accent']}; }}
            QSpinBox#episodeCounter::up-button, QSpinBox#episodeCounter::down-button {{ width: 0; height: 0; border: 0; }}
            QPushButton#counterButton {{ background: {COLORS['surface_alt']}; color: {COLORS['primary']}; border: 1px solid {COLORS['border']}; border-radius: 10px; font-size: 18px; font-weight: 850; min-width: 38px; min-height: 38px; }}
            QPushButton#counterButton:hover {{ background: {COLORS['surface_hover']}; border-color: {COLORS['accent']}; }}
            QPushButton#bundleAction {{ background:{COLORS['accent']}; color:#111318; border:0; border-radius:10px; padding:8px 12px; font-weight:800; }}
            QPushButton#bundleAction:hover {{ background:{COLORS['accent_hover']}; }}
            QPushButton#bundleRemove {{ background:{COLORS['surface_alt']}; color:{COLORS['secondary']}; border:1px solid {COLORS['border']}; border-radius:10px; padding:8px 12px; font-weight:700; }}
            QPushButton#bundleRemove:hover {{ background:{COLORS['surface_hover']}; border-color:{COLORS['border_hover']}; color:{COLORS['primary']}; }}
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
        info.addWidget(title)
        alt = self._value("native") or self._value("title_native") or ""
        if alt:
            native = QLabel(str(alt)); native.setStyleSheet(muted_label_stylesheet()); info.addWidget(native)
        meta = "  ·  ".join(str(x) for x in [self._value("format"), self._value("start_year"), f"{self._value('episodes')} eps" if self._value("episodes") else None, f"{self._value('chapters')} ch" if self._value("chapters") else None] if x)
        if meta:
            metadata = QLabel(meta); metadata.setStyleSheet(f"color:{COLORS['secondary']};font-size:13px;"); info.addWidget(metadata)
        score = self._value("score") or self._value("averageScore")
        score_label = QLabel(f"★  {score}%" if score else "—  No score"); score_label.setStyleSheet(f"color:{COLORS['accent']};font-size:18px;font-weight:800;"); info.addWidget(score_label)

        bundle_row = QHBoxLayout()
        bundle_row.setSpacing(8)
        add_bundle = QPushButton("＋  Add to bundle")
        add_bundle.setObjectName("bundleAction")
        add_bundle.setCursor(Qt.PointingHandCursor)
        add_bundle.clicked.connect(self._add_to_bundle)
        remove_bundle = QPushButton("Remove manual link")
        remove_bundle.setObjectName("bundleRemove")
        remove_bundle.setCursor(Qt.PointingHandCursor)
        remove_bundle.clicked.connect(self._remove_manual_bundle_link)
        bundle_row.addWidget(add_bundle)
        bundle_row.addWidget(remove_bundle)
        bundle_row.addStretch()
        info.addLayout(bundle_row)

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

    def _add_to_bundle(self):
        work_id = self._value("id")
        if work_id is None:
            return

        current_id = int(work_id)
        groups = get_library_series()
        options = []
        current_group_ids = set()
        used_labels = set()

        for group in groups:
            members = group.get("_series_members") if hasattr(group, "get") else None
            members = members or []
            member_ids = {
                int(member["id"])
                for member in members
                if member["id"] is not None
            }
            if current_id in member_ids:
                current_group_ids = member_ids
                break

        for group in groups:
            members = group.get("_series_members") if hasattr(group, "get") else None
            members = members or []
            member_ids = {
                int(member["id"])
                for member in members
                if member["id"] is not None
            }
            representative_id = group.get("id") if hasattr(group, "get") else None
            if representative_id is None:
                continue
            representative_id = int(representative_id)
            if current_id in member_ids or member_ids & current_group_ids:
                continue

            summary = group.get("_bundle_summary") if hasattr(group, "get") else ""
            base_label = str(group.get("title") or "Untitled")
            if summary:
                base_label = f"{base_label}  —  {summary}"
            label = base_label
            suffix = 2
            while label in used_labels:
                label = f"{base_label} ({suffix})"
                suffix += 1
            used_labels.add(label)
            options.append((label, representative_id))

        if not options:
            QMessageBox.information(
                self,
                "Add to bundle",
                "There are no other library bundles to add this work to yet.",
            )
            return

        labels = [label for label, _ in options]
        selected, ok = QInputDialog.getItem(
            self,
            "Add to bundle",
            "Choose the bundle:",
            labels,
            0,
            False,
        )
        if not ok:
            return

        target_id = dict(options)[selected]
        if add_manual_bundle_link(current_id, target_id):
            self.bundle_changed.emit()
            refreshed = get_work(current_id)
            if refreshed:
                self.set_work(refreshed)
            QMessageBox.information(
                self,
                "Bundle updated",
                "The work was added to the selected bundle.",
            )


    def _remove_manual_bundle_link(self):
        work_id = self._value("id")
        if work_id is None:
            return

        partners = get_manual_bundle_partners(int(work_id))
        if not partners:
            QMessageBox.information(
                self,
                "Remove manual link",
                "This work has no manual bundle links.",
            )
            return

        options = []
        used_labels = set()
        for row in partners:
            base_label = str(row["partner_title"] or "Untitled")
            if row["partner_format"]:
                base_label += f"  —  {row['partner_format']}"
            label = base_label
            suffix = 2
            while label in used_labels:
                label = f"{base_label} ({suffix})"
                suffix += 1
            used_labels.add(label)
            options.append((label, int(row["partner_id"])))

        labels = [label for label, _ in options]
        selected, ok = QInputDialog.getItem(
            self,
            "Remove manual link",
            "Choose the manual link to remove:",
            labels,
            0,
            False,
        )
        if not ok:
            return

        target_id = next(target_id for label, target_id in options if label == selected)
        if remove_manual_bundle_link(int(work_id), target_id):
            self.bundle_changed.emit()
            refreshed = get_work(int(work_id))
            if refreshed:
                self.set_work(refreshed)


    def _progress_counter_changed(self, value):
        if self.work is None: return
        set_episode_progress(self._value("id"), value)
        refreshed = get_work(self._value("id"))
        if refreshed: self.set_work(refreshed)

    def _cropped_cover(self, pixmap, size, radius):
        scaled = pixmap.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = max(0, (scaled.width() - size.width()) // 2); y = max(0, (scaled.height() - size.height()) // 2)
        cropped = scaled.copy(x, y, size.width(), size.height()); result = QPixmap(size); result.fill(Qt.transparent)
        painter = QPainter(result); painter.setRenderHint(QPainter.Antialiasing); path = QPainterPath(); path.addRoundedRect(0, 0, size.width(), size.height(), radius, radius); painter.setClipPath(path); painter.drawPixmap(0, 0, cropped); painter.end(); return result

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
        frame = QFrame(); frame.setObjectName("section"); lay = QVBoxLayout(frame); lay.setContentsMargins(20, 18, 20, 20); lay.setSpacing(12); header = QLabel(title); header.setStyleSheet(f"font-size:17px;font-weight:800;color:{COLORS['primary']};"); lay.addWidget(header); container = QWidget(); grid = QGridLayout(container); grid.setContentsMargins(0, 0, 0, 0); grid.setHorizontalSpacing(12); grid.setVerticalSpacing(12)
        if not items:
            x = QLabel("Nothing stored locally yet."); x.setStyleSheet(muted_label_stylesheet()); grid.addWidget(x, 0, 0)
        else:
            for i, item in enumerate(items):
                card = cls(item); card.clicked.connect(signal); grid.addWidget(card, i // columns, i % columns)
        lay.addWidget(container); return frame

    def _relations(self):
        return self._grid_section("Relations", get_relations(self._value("id")), RelationCard, self.relation_selected, 2)

    def _value(self, key):
        if hasattr(self.work, "get"): return self.work.get(key)
        try: return self.work[key]
        except (KeyError, IndexError, TypeError): return None

    def _title(self):
        title = self._value("title")
        if isinstance(title, dict): return title.get("english") or title.get("romaji") or title.get("native") or "Untitled"
        return title or "Untitled"
