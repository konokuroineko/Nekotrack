from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from database import get_all_library
from ui.theme import COLORS, SPACING


class HomePage(QWidget):
    def __init__(self): super().__init__(); self.refresh()

    def refresh(self):
        old=self.layout()
        if old:
            while old.count():
                item=old.takeAt(0)
                if item.widget(): item.widget().deleteLater()
        else: old=QVBoxLayout(self)
        old.setContentsMargins(48,44,48,44); old.setSpacing(24)
        library=list(get_all_library()); watching=sum(x["status"]=="Watching" for x in library); completed=sum(x["status"]=="Completed" for x in library); planned=sum(x["status"]=="Planning" for x in library)
        top=QHBoxLayout(); title=QLabel("Your library"); title.setStyleSheet(f"font-size:34px;font-weight:800;color:{COLORS['primary']};letter-spacing:-1px;"); top.addWidget(title); top.addStretch(); old.addLayout(top)
        cards=QHBoxLayout(); cards.setSpacing(16)
        data=[("ALL",len(library),"Titles saved",COLORS['accent']),("WATCHING",watching,"In progress",COLORS['success']),("COMPLETED",completed,"Finished",COLORS['primary']),("PLANNED",planned,"Up next",COLORS['secondary'])]
        for label,value,hint,accent in data:
            card=QFrame(); card.setObjectName("homeStat"); box=QVBoxLayout(card); box.setContentsMargins(22,20,22,20); box.setSpacing(5)
            l=QLabel(label); l.setObjectName("homeStatLabel"); l.setStyleSheet(f"font-size:10px;font-weight:800;letter-spacing:1.3px;color:{COLORS['muted']};")
            n=QLabel(str(value)); n.setObjectName("homeStatValue"); n.setStyleSheet(f"font-size:44px;font-weight:850;color:{accent};letter-spacing:-1px;")
            h=QLabel(hint); h.setObjectName("homeStatHint"); h.setStyleSheet(f"font-size:12px;color:{COLORS['secondary']};")
            box.addWidget(l); box.addWidget(n); box.addStretch(); box.addWidget(h); card.setMinimumHeight(170); cards.addWidget(card,1)
        old.addLayout(cards); old.addStretch()
        self.setStyleSheet(f"QFrame#homeStat{{background:{COLORS['surface']};border:1px solid {COLORS['frame']};border-radius:18px;}} QFrame#homeStat:hover{{background:{COLORS['surface_hover']};border-color:{COLORS['border_hover']};}}")

    def refresh_theme(self):
        self.setStyleSheet(f"QFrame#homeStat{{background:{COLORS['surface']};border:1px solid {COLORS['frame']};border-radius:18px;}} QFrame#homeStat:hover{{background:{COLORS['surface_hover']};border-color:{COLORS['border_hover']};}}")
        value_colors = {
            "ALL": COLORS["accent"],
            "WATCHING": COLORS["success"],
            "COMPLETED": COLORS["primary"],
            "PLANNED": COLORS["secondary"],
        }

        for card in self.findChildren(QFrame):
            if card.objectName() != "homeStat":
                continue
            label = card.findChild(QLabel, "homeStatLabel")
            value = card.findChild(QLabel, "homeStatValue")
            hint = card.findChild(QLabel, "homeStatHint")

            if label is not None:
                label.setStyleSheet(f"font-size:10px;font-weight:800;letter-spacing:1.3px;color:{COLORS['muted']};")
            if value is not None and label is not None:
                color = value_colors.get(label.text().upper(), COLORS["primary"])
                value.setStyleSheet(f"font-size:44px;font-weight:850;color:{color};letter-spacing:-1px;")
            if hint is not None:
                hint.setStyleSheet(f"font-size:12px;color:{COLORS['secondary']};")

            card.style().unpolish(card)
            card.style().polish(card)
            card.update()
