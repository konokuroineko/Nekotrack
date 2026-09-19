from ui.preferences import get


COLORS = {
    "background": get("background"),
    "background_alt": "#0f1116",
    "sidebar": "#0b0d11",
    "surface": get("surface"),
    "surface_alt": "#191d25",
    "surface_hover": get("surface_hover"),
    "border": "#252b35",
    "border_hover": "#394250",
    "primary": "#f5f7fa",
    "secondary": "#aeb7c4",
    "muted": "#687384",
    "accent": get("accent"),
    "accent_hover": get("accent_hover"),
    "frame": get("frame_color"),
    "accent_soft": "#302116",
    "success": "#67d391",
    "danger": "#ef7474",
    "panel": "#11141a",
    "panel_soft": "#171b22",
    "card": get("card"),
    "card_hover": get("card_hover"),
}

FONT_SIZES = {"tiny": 10, "small": 11, "body": get("font_size"), "subtitle": 12, "large": 16, "heading": 24, "page_title": 32}
SPACING = {"xs": 4, "sm": 8, "md": 14, "lg": 20, "xl": 28, "xxl": 40}


def refresh_theme():
    COLORS.update({
        "background": get("background"),
        "surface": get("surface"),
        "surface_hover": get("surface_hover"),
        "card": get("card"),
        "card_hover": get("card_hover"),
        "accent": get("accent"),
        "accent_hover": get("accent_hover"),
        "frame": get("frame_color"),
    })
    FONT_SIZES["body"] = get("font_size")


def application_stylesheet():
    radius = get("corner_radius")
    return f"""
        * {{ outline: none; }}
        QMainWindow {{ background: {COLORS['background']}; color: {COLORS['primary']}; }}
        QWidget {{ background: transparent; color: {COLORS['primary']}; font-family: "Segoe UI"; font-size: {FONT_SIZES['body']}px; }}
        QLabel, QCheckBox, QRadioButton {{ background: transparent; }}
        QToolTip {{ background: {COLORS['surface_alt']}; color: {COLORS['primary']}; border: 1px solid {COLORS['border']}; padding: 7px 9px; }}
        QLineEdit, QComboBox, QSpinBox {{ background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: {radius}px; color: {COLORS['primary']}; padding: 10px 12px; selection-background-color: {COLORS['accent']}; }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {COLORS['accent']}; }}
        QPushButton {{ background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: {max(6, radius - 3)}px; color: {COLORS['secondary']}; padding: 9px 13px; font-weight: 600; }}
        QPushButton:hover {{ background: {COLORS['surface_hover']}; border-color: {COLORS['border_hover']}; color: {COLORS['primary']}; }}
        QPushButton:pressed {{ background: {COLORS['surface_alt']}; }}
        QPushButton:disabled {{ color: {COLORS['muted']}; background: {COLORS['background_alt']}; }}
        QScrollArea {{ border: none; background: transparent; }}
        QScrollArea > QWidget > QWidget {{ background: transparent; }}
        QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px 0; }}
        QScrollBar::handle:vertical {{ background: {COLORS['border']}; border-radius: 4px; min-height: 36px; }}
        QScrollBar::handle:vertical:hover {{ background: {COLORS['muted']}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar:horizontal {{ background: transparent; height: 8px; }}
        QScrollBar::handle:horizontal {{ background: {COLORS['border']}; border-radius: 4px; min-width: 36px; }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    """


def panel_stylesheet(radius=None):
    radius = get("corner_radius") if radius is None else radius
    return f"QFrame {{ background: {COLORS['surface']}; border: 1px solid {COLORS['frame']}; border-radius: {radius}px; }}"


def card_stylesheet(radius=None):
    radius = get("corner_radius") if radius is None else radius
    return f"QFrame {{ background: {COLORS['card']}; border: 2px solid {COLORS['frame']}; border-radius: {radius}px; }} QFrame:hover {{ background: {COLORS['card_hover']}; border-color: {COLORS['frame']}; }}"


def muted_label_stylesheet():
    return f"color: {COLORS['muted']}; font-size: 12px;"
