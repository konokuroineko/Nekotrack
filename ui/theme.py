from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from ui.preferences import get


COLOR_KEYS = (
    "background",
    "background_alt",
    "sidebar",
    "surface",
    "surface_alt",
    "surface_hover",
    "border",
    "border_hover",
    "primary",
    "secondary",
    "muted",
    "accent",
    "accent_hover",
    "accent_text",
    "frame_color",
    "accent_soft",
    "success",
    "danger",
    "panel",
    "panel_soft",
    "card",
    "card_hover",
    "nav_selected_text",
    "nav_selected_frame",
)


COLORS = {
    **{key: get(key) for key in COLOR_KEYS},
    "frame": get("frame_color"),
}

FONT_SIZES = {
    "tiny": 10,
    "small": 11,
    "body": get("font_size"),
    "subtitle": 12,
    "large": 16,
    "heading": 24,
    "page_title": 32,
}
SPACING = {"xs": 4, "sm": 8, "md": 14, "lg": 20, "xl": 28, "xxl": 40}


def refresh_theme():
    for key in COLOR_KEYS:
        COLORS[key] = get(key)
    COLORS["frame"] = get("frame_color")
    FONT_SIZES["body"] = get("font_size")

    app = QApplication.instance()
    if app is None:
        return

    # Keep Qt's palette roles on the same semantic palette as the stylesheet.
    palette = app.palette()
    role_colors = {
        QPalette.ColorRole.Window: COLORS["background"],
        QPalette.ColorRole.WindowText: COLORS["primary"],
        QPalette.ColorRole.Base: COLORS["surface"],
        QPalette.ColorRole.AlternateBase: COLORS["surface_alt"],
        QPalette.ColorRole.ToolTipBase: COLORS["surface_alt"],
        QPalette.ColorRole.ToolTipText: COLORS["primary"],
        QPalette.ColorRole.Text: COLORS["primary"],
        QPalette.ColorRole.Button: COLORS["surface"],
        QPalette.ColorRole.ButtonText: COLORS["secondary"],
        QPalette.ColorRole.Link: COLORS["accent"],
        QPalette.ColorRole.LinkVisited: COLORS["accent"],
        QPalette.ColorRole.Highlight: COLORS["nav_selected_frame"],
        QPalette.ColorRole.HighlightedText: COLORS["accent_text"],
        QPalette.ColorRole.PlaceholderText: COLORS["muted"],
        QPalette.ColorRole.BrightText: COLORS["primary"],
        QPalette.ColorRole.Light: COLORS["surface_hover"],
        QPalette.ColorRole.Midlight: COLORS["border_hover"],
        QPalette.ColorRole.Mid: COLORS["border"],
        QPalette.ColorRole.Dark: COLORS["background"],
        QPalette.ColorRole.Shadow: COLORS["background"],
    }
    accent_role = getattr(QPalette.ColorRole, "Accent", None)
    if accent_role is not None:
        role_colors[accent_role] = COLORS["nav_selected_frame"]

    for role, value in role_colors.items():
        color = QColor(value)
        for group in (
            QPalette.ColorGroup.Active,
            QPalette.ColorGroup.Inactive,
            QPalette.ColorGroup.Disabled,
        ):
            palette.setColor(group, role, color)

    app.setPalette(palette)


def retint_widget_styles(old_theme_name, new_theme_name):
    """Compatibility hook for the settings page.

    Theme changes are applied through the semantic theme roles and live refresh
    methods. Existing widgets are refreshed directly, so no historical color
    rewriting is needed here.
    """
    return


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
        QPushButton:focus {{ border-color: {COLORS['accent']}; outline: none; }}
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
