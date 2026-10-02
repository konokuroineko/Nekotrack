from PySide6.QtCore import QSettings


THEME_PRESETS = {
    "Neko": {
        "description": "Midnight graphite with deep violet and soft lavender.",
        "nav_selected_text": "#c5a3ff",
        "nav_selected_frame": "#7650b8",
        "accent_text": "#120d1a",
        "font_size": 13,
        "card_size": 210,
        "card_gap": 24,
        "corner_radius": 14,
        "accent": "#a678ff",
        "accent_hover": "#c09cff",
        "frame_color": "#8c62dc",
        "background": "#0b0911",
        "background_alt": "#0f0c16",
        "sidebar": "#07060c",
        "surface": "#14111b",
        "surface_alt": "#191521",
        "surface_hover": "#1e1928",
        "border": "#2b2438",
        "border_hover": "#44375a",
        "primary": "#f5f0fb",
        "secondary": "#c4b9d2",
        "muted": "#82758f",
        "accent_soft": "#281a3e",
        "success": "#72d39a",
        "danger": "#ef7474",
        "panel": "#100d16",
        "panel_soft": "#18131f",
        "card": "#16121d",
        "card_hover": "#20182a",
    },

    "Sakura": {
        "description": "Soft blossom pink over a deep plum-brown base.",
        "nav_selected_text": "#ffabc0",
        "nav_selected_frame": "#d96d8f",
        "accent_text": "#210f16",
        "font_size": 13,
        "card_size": 210,
        "card_gap": 24,
        "corner_radius": 16,
        "accent": "#eb8fa8",
        "accent_hover": "#f5abc0",
        "frame_color": "#d56f8e",
        "background": "#120e10",
        "background_alt": "#181215",
        "sidebar": "#0c090b",
        "surface": "#1c1518",
        "surface_alt": "#241a1f",
        "surface_hover": "#2c2025",
        "border": "#3c2b31",
        "border_hover": "#594049",
        "primary": "#f8f0f3",
        "secondary": "#ccb9c0",
        "muted": "#927d85",
        "accent_soft": "#38202a",
        "success": "#6fd19a",
        "danger": "#e86f6f",
        "panel": "#171114",
        "panel_soft": "#20161a",
        "card": "#1e161a",
        "card_hover": "#281c21",
    },
    "Ocean": {
        "description": "Clean teal highlights with a deep slate base.",
        "nav_selected_text": "#7ad8cd",
        "nav_selected_frame": "#3e9f96",
        "accent_text": "#071917",
        "font_size": 13,
        "card_size": 210,
        "card_gap": 24,
        "corner_radius": 12,
        "accent": "#59c2b6",
        "accent_hover": "#7ad8cd",
        "frame_color": "#46a99f",
        "background": "#0c1111",
        "background_alt": "#101716",
        "sidebar": "#080c0c",
        "surface": "#111918",
        "surface_alt": "#17211f",
        "surface_hover": "#1c2926",
        "border": "#283b38",
        "border_hover": "#3d5752",
        "primary": "#edf7f5",
        "secondary": "#b5c9c5",
        "muted": "#728983",
        "accent_soft": "#12312d",
        "success": "#6fd39a",
        "danger": "#e86f6f",
        "panel": "#0e1514",
        "panel_soft": "#15201e",
        "card": "#131d1b",
        "card_hover": "#1a2825",
    },
    "Forest": {
        "description": "Leaf green accents with a rich evergreen base.",
        "nav_selected_text": "#9ae3aa",
        "nav_selected_frame": "#5eae70",
        "accent_text": "#0d1b10",
        "font_size": 13,
        "card_size": 210,
        "card_gap": 24,
        "corner_radius": 14,
        "accent": "#79c98a",
        "accent_hover": "#9ae3aa",
        "frame_color": "#5eae70",
        "background": "#0c110e",
        "background_alt": "#111711",
        "sidebar": "#080d0a",
        "surface": "#141b16",
        "surface_alt": "#19231b",
        "surface_hover": "#1f2a21",
        "border": "#293a2e",
        "border_hover": "#415b48",
        "primary": "#eef7f0",
        "secondary": "#b6c9ba",
        "muted": "#728579",
        "accent_soft": "#17301d",
        "success": "#70d996",
        "danger": "#e86f6f",
        "panel": "#101711",
        "panel_soft": "#162019",
        "card": "#151e18",
        "card_hover": "#1d2920",
    },
    "Classic": {
        "description": "Muted brass accents on a straightforward graphite base.",
        "nav_selected_text": "#efb978",
        "nav_selected_frame": "#b98045",
        "accent_text": "#19140b",
        "font_size": 13,
        "card_size": 210,
        "card_gap": 24,
        "corner_radius": 12,
        "accent": "#d6ad63",
        "accent_hover": "#e7c783",
        "frame_color": "#bd924c",
        "background": "#101112",
        "background_alt": "#15171a",
        "sidebar": "#0b0d10",
        "surface": "#181b1e",
        "surface_alt": "#1d2126",
        "surface_hover": "#23282d",
        "border": "#2b3037",
        "border_hover": "#434b56",
        "primary": "#f2f4f6",
        "secondary": "#b5bec8",
        "muted": "#74808c",
        "accent_soft": "#332817",
        "success": "#69cf96",
        "danger": "#e86f6f",
        "panel": "#111419",
        "panel_soft": "#181c22",
        "card": "#191d20",
        "card_hover": "#242a2e",
    },
    "Crimson": {
        "description": "Crisp red accents with a dark charcoal base.",
        "nav_selected_text": "#ff929c",
        "nav_selected_frame": "#cf5662",
        "accent_text": "#210b0e",
        "font_size": 13,
        "card_size": 210,
        "card_gap": 24,
        "corner_radius": 14,
        "accent": "#e46f79",
        "accent_hover": "#f48e98",
        "frame_color": "#c65560",
        "background": "#120d0f",
        "background_alt": "#181012",
        "sidebar": "#0d080a",
        "surface": "#1b1416",
        "surface_alt": "#24191c",
        "surface_hover": "#2b1e21",
        "border": "#3e2a2e",
        "border_hover": "#5b3a40",
        "primary": "#faeff1",
        "secondary": "#ccb8bd",
        "muted": "#8e777d",
        "accent_soft": "#351a1f",
        "success": "#6fd39a",
        "danger": "#ed7373",
        "panel": "#160f11",
        "panel_soft": "#1f1518",
        "card": "#1d1517",
        "card_hover": "#291b1e",
    },
}
_DEFAULTS = {
    **{key: value for key, value in THEME_PRESETS["Neko"].items() if key != "description"},
    "theme_preset": "Neko",
    "font_size": 13,
    "card_size": 210,
    "card_gap": 24,
    "corner_radius": 12,
    "hover_highlight": True,
    "resize_animation": True,
    "animation_speed": 260,
    "maximized": True,
    "tmdb_api_token": "",
    "bundle_mode": "main",
    "setup_complete": False,
}

_ORGANIZATION = "NekoTrack"
_APPLICATION = "NekoTrack"
_LEGACY_ORGANIZATION = "AniTrack"
_LEGACY_APPLICATION = "AniTrack"

_MIGRATION_KEY = "_legacy_anitrack_preferences_migrated"

_THEME_PALETTE_VERSION = 4


def settings():
    """Return NekoTrack's settings store and migrate the old AniTrack store once."""
    current = QSettings(_ORGANIZATION, _APPLICATION)
    legacy = QSettings(_LEGACY_ORGANIZATION, _LEGACY_APPLICATION)

    if current.value(_MIGRATION_KEY, False) != True:
        for key in legacy.allKeys():
            current.setValue(key, legacy.value(key))
        current.setValue(_MIGRATION_KEY, True)
        current.sync()

    # Migrate legacy theme names into the new palette.
    stored_theme = str(current.value("theme_preset", "") or "")
    if stored_theme in ("NekoTrack", "Amethyst") or stored_theme not in THEME_PRESETS:
        stored_theme = "Neko"
        current.setValue("theme_preset", stored_theme)

    # Replace every saved theme color from older palette versions. This keeps
    # an existing install from resurrecting removed colors from QSettings.
    if int(current.value("_theme_palette_version", 0) or 0) != _THEME_PALETTE_VERSION:
        theme = THEME_PRESETS[stored_theme]
        for key, value in theme.items():
            if key != "description":
                current.setValue(key, value)
        current.setValue("_theme_palette_version", _THEME_PALETTE_VERSION)
        current.sync()

    return current


def get(key):
    default = _DEFAULTS[key]
    value = settings().value(key, default)

    if isinstance(default, bool):
        if isinstance(value, str):
            return value.lower() in ("1", "true", "yes", "on")
        return bool(value)

    if isinstance(default, int):
        try:
            value = int(value)
        except (TypeError, ValueError):
            return default
        if key == "font_size":
            return max(8, value)
        return value

    return value


def set_value(key, value):
    if key == "font_size":
        try:
            value = max(8, int(value))
        except (TypeError, ValueError):
            value = _DEFAULTS["font_size"]
    settings().setValue(key, value)
    settings().sync()


def apply_theme_preset(name):
    theme = THEME_PRESETS.get(str(name))
    if theme is None:
        raise ValueError(f"Unknown NekoTrack theme preset: {name}")

    qsettings = settings()
    qsettings.setValue("theme_preset", str(name))
    for key, value in theme.items():
        if key != "description":
            qsettings.setValue(key, value)
    qsettings.sync()


def defaults():
    return dict(_DEFAULTS)


def reset():
    qsettings = settings()
    qsettings.clear()
    qsettings.setValue(_MIGRATION_KEY, True)
    qsettings.sync()
