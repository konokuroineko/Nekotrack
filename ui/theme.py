from PySide6.QtGui import QColor, QPalette
import re

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from ui.preferences import get


# Resolved colors used by widget styles from themes that existed before
# the current preset system. Existing widgets can still carry these values
# when a theme is changed without rebuilding the widget tree.
LEGACY_STYLE_COLORS = {
    "#30283d": "border",
    "#493d5b": "border_hover",
    "#83758f": "muted",
    "#c0b5cf": "secondary",
    "#f6f1fc": "primary",
    "#271d3b": "accent_soft",
    "#121019": "panel",
    "#191522": "panel_soft",
    "#17141e": "card",
    "#221c2b": "card_hover",
    # One-off fixed colors from the pre-theme UI.
    "#594025": "accent",
    "#101216": "accent_text",
    "#111318": "accent_text",
    "#121417": "accent_text",
    "#c94343": "danger",
    "#e05252": "danger",
    "#ff8585": "danger",
}

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

    # Qt's native palette can otherwise introduce its own blue selection,
    # focus, and link colors that sit on top of the themed stylesheet.
    app = QApplication.instance()
    if app is not None:
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
            QPalette.ColorRole.Highlight: COLORS["accent"],
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
            role_colors[accent_role] = COLORS["accent"]

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
    """Replace resolved old-theme colors in existing widget-local stylesheets."""
    from ui.preferences import THEME_PRESETS

    old_theme = THEME_PRESETS.get(str(old_theme_name))
    new_theme = THEME_PRESETS.get(str(new_theme_name))
    app = QApplication.instance()
    if old_theme is None or new_theme is None or app is None:
        return

    color_keys = [key for key in COLOR_KEYS if key in old_theme and key in new_theme]
    replacements = {
        str(old_theme[key]).lower(): str(new_theme[key])
        for key in color_keys
        if old_theme[key] and new_theme[key]
    }

    # Colors can coincide in one preset (for example accent/frame in Classic).
    # In those cases, resolve the replacement from the CSS property using the
    # most likely semantic role.
    ambiguous = {
        source: [
            key for key in color_keys
            if str(old_theme[key]).lower() == source
            and str(new_theme[key]) != source
        ]
        for source in replacements
    }

    def replace_stylesheet(style):
        if not style:
            return style

        pattern = re.compile(r"#[0-9A-Fa-f]{6}(?=[^0-9A-Fa-f]|$)")

        def replace(match):
            source = match.group(0).lower()

            # Clean up colors from removed/legacy styles even when the current
            # widget was created under a different historical theme.
            legacy_key = LEGACY_STYLE_COLORS.get(source)
            if legacy_key:
                return str(new_theme.get(legacy_key) or match.group(0))

            keys = ambiguous.get(source)
            if not keys:
                return replacements.get(source, match.group(0))

            # Inspect the CSS property immediately preceding this color.
            before = style[max(0, match.start() - 80):match.start()].lower()
            if "border-color:" in before or "border:" in before:
                for key in ("frame_color", "border_hover", "border"):
                    if key in keys:
                        return str(new_theme[key])
            if "selection-background-color:" in before or "background:" in before or "background-color:" in before:
                for key in ("accent", "accent_hover", "surface_hover", "surface_alt", "surface", "background"):
                    if key in keys:
                        return str(new_theme[key])
            if "color:" in before:
                for key in ("accent_text", "accent", "primary", "secondary", "muted"):
                    if key in keys:
                        return str(new_theme[key])
            return replacements.get(source, match.group(0))

        return pattern.sub(replace, style)

    for widget in app.allWidgets():
        style = widget.styleSheet()
        if not style:
            continue
        new_style = replace_stylesheet(style)
        if new_style != style:
            widget.setStyleSheet(new_style)
        widget.update()

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
