import re
import sys
from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from ui.preferences import THEME_PRESETS, get, palette_for_mode


_BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
_CHECKBOX_CHECKMARK = (_BUNDLE_ROOT / "assets" / "checkbox-check.svg").as_posix()


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

# Theme surfaces use a shared alpha scale so every theme lets the selected
# wallpaper show through while keeping stronger layers readable.
SURFACE_OPACITY = {
    "sidebar": 82,
    "background_alt": 76,
    "surface": 78,
    "surface_alt": 85,
    "surface_hover": 92,
    "panel": 77,
    "panel_soft": 84,
    "card": 81,
    "card_hover": 92,
    "accent_soft": 88,
}


def surface_rgba(key):
    """Return a theme color as an RGBA stylesheet color at its layer opacity."""
    key = str(key)
    value = COLORS.get(key)
    if value is None:
        return "transparent"
    color = QColor(str(value))
    if not color.isValid():
        return str(value)
    opacity = max(0, min(100, int(SURFACE_OPACITY.get(key, 100))))
    alpha = round(255 * opacity / 100)
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"


def refresh_theme():
    theme_name = str(get("theme_preset") or "Neko")
    base_theme = THEME_PRESETS.get(theme_name, THEME_PRESETS["Neko"])
    active_theme = palette_for_mode(base_theme, get("light_mode"))
    for key in COLOR_KEYS:
        COLORS[key] = active_theme.get(key, get(key))
    COLORS["frame"] = active_theme.get("frame_color", get("frame_color"))
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


def retint_widget_styles(
    old_theme_name,
    new_theme_name,
    old_light_mode=None,
    new_light_mode=None,
):
    """Retint inline styles from the previous active palette to the new one.

    Widgets often build stylesheets once from COLORS. Map only colors from the
    previous theme and mode; searching every preset creates false ambiguities
    and leaves stale dark colors behind in White mode.
    """
    if old_light_mode is None:
        old_light_mode = get("light_mode")
    if new_light_mode is None:
        new_light_mode = get("light_mode")
    old_light_mode = bool(old_light_mode)
    new_light_mode = bool(new_light_mode)

    base_theme = THEME_PRESETS.get(str(new_theme_name))
    if not base_theme:
        return
    old_base_theme = THEME_PRESETS.get(
        str(old_theme_name), THEME_PRESETS["Neko"]
    )
    old_theme = palette_for_mode(old_base_theme, old_light_mode)
    new_theme = palette_for_mode(base_theme, new_light_mode)
    if (
        str(old_theme_name) == str(new_theme_name)
        and old_light_mode == new_light_mode
    ):
        return

    # Match each color in its previous semantic role. Do not mix palettes from
    # unrelated themes, where a coincidentally repeated hex value can map to
    # several different destinations.
    candidates = {}
    for key in COLOR_KEYS:
        old_color = old_theme.get(key)
        new_color = new_theme.get(key)
        if (
            isinstance(old_color, str)
            and isinstance(new_color, str)
            and old_color.startswith("#")
            and new_color.startswith("#")
            and old_color.lower() != new_color.lower()
        ):
            candidates.setdefault(old_color.lower(), set()).add(new_color)

    # If the same literal represents different semantic roles in the theme
    # catalog, leave it untouched rather than guessing which role it meant.
    replacements = {
        old_color: next(iter(new_colors))
        for old_color, new_colors in candidates.items()
        if len(new_colors) == 1
    }
    if not replacements:
        return

    color_pattern = re.compile(
        "|".join(re.escape(color) for color in sorted(replacements, key=len, reverse=True)),
        re.IGNORECASE,
    )
    rgba_pattern = re.compile(
        r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)",
        re.IGNORECASE,
    )
    rgb_candidates = {}
    for old_color, new_color in replacements.items():
        old_rgb = QColor(old_color)
        new_rgb = QColor(new_color)
        old_key = (old_rgb.red(), old_rgb.green(), old_rgb.blue())
        new_value = (new_rgb.red(), new_rgb.green(), new_rgb.blue())
        rgb_candidates.setdefault(old_key, set()).add(new_value)
    rgba_replacements = {
        old_rgb: next(iter(new_values))
        for old_rgb, new_values in rgb_candidates.items()
        if len(new_values) == 1
    }

    def retint_rgba(match):
        old_rgb = tuple(int(match.group(index)) for index in (1, 2, 3))
        new_rgb = rgba_replacements.get(old_rgb)
        if new_rgb is None:
            return match.group(0)
        return (
            f"rgba({new_rgb[0]}, {new_rgb[1]}, {new_rgb[2]}, "
            f"{match.group(4)})"
        )

    app = QApplication.instance()
    if app is None:
        return

    def is_theme_preview(widget):
        # Theme cards and their swatches intentionally display each preset's
        # own palette and must not be recolored to the currently active theme.
        parent = widget
        while parent is not None:
            if isinstance(parent, QDialog):
                return True
            if parent.objectName() in {"themePresetCard", "themeCard"}:
                return True
            parent = parent.parentWidget()
        return False

    widgets = []
    for window in app.topLevelWidgets():
        if isinstance(window, QDialog):
            continue
        widgets.append(window)
        widgets.extend(window.findChildren(QWidget))

    seen = set()
    for widget in widgets:
        if id(widget) in seen or is_theme_preview(widget):
            continue
        seen.add(id(widget))
        stylesheet = widget.styleSheet()
        if not stylesheet:
            continue

        updated = color_pattern.sub(
            lambda match: replacements[match.group(0).lower()],
            stylesheet,
        )
        updated = rgba_pattern.sub(retint_rgba, updated)
        if updated == stylesheet:
            continue

        widget.setStyleSheet(updated)
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()


def application_stylesheet():
    radius = get("corner_radius")
    checkbox_checkmark = _CHECKBOX_CHECKMARK.replace('"', '\\"')
    return f"""
        * {{ outline: none; }}
        QMainWindow {{ background: {COLORS['background']}; color: {COLORS['primary']}; }}
        QWidget {{ background: transparent; color: {COLORS['primary']}; font-family: "Segoe UI"; font-size: {FONT_SIZES['body']}px; }}
        QLabel, QCheckBox, QRadioButton {{ background: transparent; }}
        QCheckBox {{ spacing: 8px; }}
        QCheckBox::indicator {{
            width: 18px; height: 18px;
            background: {surface_rgba('surface_alt')};
            border: 1px solid {COLORS['border']};
            border-radius: 5px;
        }}
        QCheckBox::indicator:hover {{
            background: {surface_rgba('surface_hover')};
            border-color: {COLORS['accent']};
        }}
        QCheckBox::indicator:pressed {{
            background: {surface_rgba('accent_soft')};
            border-color: {COLORS['accent']};
        }}
        QCheckBox::indicator:checked {{
            background: {COLORS['accent']};
            border: 1px solid {COLORS['accent']};
            image: url("${checkbox_checkmark}");
        }}
        QCheckBox::indicator:checked:hover {{
            background: {COLORS['accent_hover']};
            border-color: {COLORS['accent_hover']};
        }}
        QCheckBox::indicator:disabled {{
            background: {surface_rgba('background_alt')};
            border-color: {COLORS['border']};
        }}
        QCheckBox::indicator:checked:disabled {{
            background: {COLORS['muted']};
            border-color: {COLORS['muted']};
        }}
        QToolTip {{ background: {surface_rgba('surface_alt')}; color: {COLORS['primary']}; border: 1px solid {COLORS['border']}; padding: 7px 9px; }}
        QLineEdit, QComboBox, QSpinBox {{ background: {surface_rgba('surface')}; border: 1px solid {COLORS['border']}; border-radius: {radius}px; color: {COLORS['primary']}; padding: 10px 12px; selection-background-color: {COLORS['accent']}; }}
        QComboBox {{ padding-right: 34px; }}
        QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right; width: 32px; border: none; background: transparent; }}
        QComboBox QAbstractItemView {{ background: {surface_rgba('surface')}; color: {COLORS['primary']}; border: 1px solid {COLORS['border']}; border-radius: 10px; padding: 4px; outline: none; selection-background-color: {surface_rgba('accent_soft')}; }}
        QComboBox QAbstractItemView::item {{ min-height: 28px; padding: 6px 10px; border-radius: 6px; }}
        QComboBox QAbstractItemView::item:hover {{ background: {surface_rgba('surface_hover')}; color: {COLORS['primary']}; }}
        QComboBox QAbstractItemView::item:selected {{ background: {surface_rgba('accent_soft')}; color: {COLORS['nav_selected_text']}; }}
        QSlider::groove:horizontal {{ height: 6px; background: {COLORS['border']}; border: none; border-radius: 3px; }}
        QSlider::sub-page:horizontal {{ background: {COLORS['accent']}; border: none; border-radius: 3px; }}
        QSlider::add-page:horizontal {{ background: {surface_rgba('surface_alt')}; border: none; border-radius: 3px; }}
        QSlider::handle:horizontal {{ width: 16px; margin: -6px 0; background: {COLORS['primary']}; border: 2px solid {COLORS['accent']}; border-radius: 8px; }}
        QSlider::handle:horizontal:hover {{ background: {COLORS['accent_hover']}; border-color: {COLORS['accent_hover']}; }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {COLORS['accent']}; }}
        QPushButton {{ background: {surface_rgba('surface')}; border: 1px solid {COLORS['border']}; border-radius: {max(6, radius - 3)}px; color: {COLORS['secondary']}; padding: 9px 13px; font-weight: 600; }}
        QPushButton:hover {{ background: {surface_rgba('surface_hover')}; border-color: {COLORS['border_hover']}; color: {COLORS['primary']}; }}
        QPushButton:pressed {{ background: {surface_rgba('surface_alt')}; }}
        QPushButton:focus {{ border-color: {COLORS['accent']}; outline: none; }}
        QPushButton:disabled {{ color: {COLORS['muted']}; background: {surface_rgba('background_alt')}; }}
        QScrollArea {{ border: none; background: transparent; }}
        QScrollArea > QWidget > QWidget {{ background: transparent; }}
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 3px 1px; border: none; }}
        QScrollBar::handle:vertical {{ background: {COLORS['border']}; border-radius: 5px; min-height: 42px; margin: 1px; }}
        QScrollBar::handle:vertical:hover {{ background: {COLORS['accent']}; }}
        QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 1px 3px; border: none; }}
        QScrollBar::handle:horizontal {{ background: {COLORS['border']}; border-radius: 5px; min-width: 42px; margin: 1px; }}
        QScrollBar::handle:horizontal:hover {{ background: {COLORS['accent']}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; height: 0px; border: none; background: transparent; image: none; }}
        QScrollBar::up-arrow, QScrollBar::down-arrow, QScrollBar::left-arrow, QScrollBar::right-arrow {{ width: 0px; height: 0px; border: none; image: none; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    """


def panel_stylesheet(radius=None):
    radius = get("corner_radius") if radius is None else radius
    return f"QFrame {{ background: {surface_rgba('surface')}; border: 1px solid {COLORS['frame']}; border-radius: {radius}px; }}"


def card_stylesheet(radius=None):
    radius = get("corner_radius") if radius is None else radius
    return f"QFrame {{ background: {surface_rgba('card')}; border: 2px solid {COLORS['frame']}; border-radius: {radius}px; }} QFrame:hover {{ background: {surface_rgba('card_hover')}; border-color: {COLORS['frame']}; }}"


def muted_label_stylesheet():
    return f"color: {COLORS['muted']}; font-size: 12px;"
