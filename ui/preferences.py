from PySide6.QtCore import QSettings


THEME_PRESETS = {
    "NekoTrack": {
        "description": "Warm amber on a dark graphite base.",
        "accent": "#e4a45e",
        "accent_hover": "#efb978",
        "frame_color": "#e4a45e",
        "background": "#0d0f10",
        "background_alt": "#0f1116",
        "sidebar": "#0b0d11",
        "surface": "#171a1d",
        "surface_alt": "#191d25",
        "surface_hover": "#1b1f22",
        "border": "#252b35",
        "border_hover": "#394250",
        "primary": "#f5f7fa",
        "secondary": "#aeb7c4",
        "muted": "#687384",
        "accent_soft": "#302116",
        "success": "#67d391",
        "danger": "#ef7474",
        "panel": "#11141a",
        "panel_soft": "#171b22",
        "card": "#181c1f",
        "card_hover": "#22272b",
    },
    "Sakura": {
        "description": "Soft pink accents with a plum-black base.",
        "accent": "#f08ca6",
        "accent_hover": "#ffabc0",
        "frame_color": "#d96d8f",
        "background": "#0f0d12",
        "background_alt": "#121018",
        "sidebar": "#0b0910",
        "surface": "#17131b",
        "surface_alt": "#1c1721",
        "surface_hover": "#211a25",
        "border": "#322632",
        "border_hover": "#493646",
        "primary": "#f8f1f5",
        "secondary": "#c8b8c2",
        "muted": "#8b7884",
        "accent_soft": "#321b27",
        "success": "#67d391",
        "danger": "#ef7474",
        "panel": "#121017",
        "panel_soft": "#19141d",
        "card": "#18131b",
        "card_hover": "#241a24",
    },
    "Ocean": {
        "description": "Cool blue highlights with a deep navy base.",
        "accent": "#62b3f4",
        "accent_hover": "#88c9ff",
        "frame_color": "#4e98d3",
        "background": "#0b0f14",
        "background_alt": "#0d1219",
        "sidebar": "#080d13",
        "surface": "#111821",
        "surface_alt": "#151e29",
        "surface_hover": "#17222e",
        "border": "#253240",
        "border_hover": "#3a5267",
        "primary": "#eff6fc",
        "secondary": "#b0c4d5",
        "muted": "#71869a",
        "accent_soft": "#10263a",
        "success": "#67d391",
        "danger": "#ef7474",
        "panel": "#0e151d",
        "panel_soft": "#151e28",
        "card": "#131c24",
        "card_hover": "#1a2732",
    },
    "Forest": {
        "description": "Leaf green accents with a rich evergreen base.",
        "accent": "#79c98a",
        "accent_hover": "#9ae3aa",
        "frame_color": "#5eae70",
        "background": "#0c110e",
        "background_alt": "#0f1511",
        "sidebar": "#080d0a",
        "surface": "#131b16",
        "surface_alt": "#18221b",
        "surface_hover": "#1b271f",
        "border": "#27372d",
        "border_hover": "#3d5544",
        "primary": "#eef7f0",
        "secondary": "#b3c8b8",
        "muted": "#718477",
        "accent_soft": "#16301d",
        "success": "#70d996",
        "danger": "#ef7474",
        "panel": "#101711",
        "panel_soft": "#162018",
        "card": "#151e18",
        "card_hover": "#1d2a20",
    },
    "Amethyst": {
        "description": "Violet accents over a dark midnight violet.",
        "accent": "#ad8cff",
        "accent_hover": "#c4abff",
        "frame_color": "#9272df",
        "background": "#0e0c13",
        "background_alt": "#11101a",
        "sidebar": "#090811",
        "surface": "#16131d",
        "surface_alt": "#1b1723",
        "surface_hover": "#201a2a",
        "border": "#30283d",
        "border_hover": "#493d5b",
        "primary": "#f6f1fc",
        "secondary": "#c0b5cf",
        "muted": "#83758f",
        "accent_soft": "#271d3b",
        "success": "#67d391",
        "danger": "#ef7474",
        "panel": "#121019",
        "panel_soft": "#191522",
        "card": "#17141e",
        "card_hover": "#221c2b",
    },
    "Crimson": {
        "description": "Crisp red accents with a dark charcoal-red base.",
        "accent": "#ed6d79",
        "accent_hover": "#ff929c",
        "frame_color": "#cf5662",
        "background": "#110c0e",
        "background_alt": "#150f11",
        "sidebar": "#0c080a",
        "surface": "#1a1315",
        "surface_alt": "#20171a",
        "surface_hover": "#261b1e",
        "border": "#3b282c",
        "border_hover": "#5a3a40",
        "primary": "#faeff1",
        "secondary": "#cdb8bc",
        "muted": "#8d777b",
        "accent_soft": "#351a1f",
        "success": "#67d391",
        "danger": "#ef7474",
        "panel": "#140f11",
        "panel_soft": "#1c1518",
        "card": "#1b1416",
        "card_hover": "#291b1f",
    },
}


_DEFAULTS = {
    **{key: value for key, value in THEME_PRESETS["NekoTrack"].items() if key != "description"},
    "theme_preset": "NekoTrack",
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


def settings():
    """Return NekoTrack's settings store and migrate the old AniTrack store once."""
    current = QSettings(_ORGANIZATION, _APPLICATION)
    legacy = QSettings(_LEGACY_ORGANIZATION, _LEGACY_APPLICATION)

    if current.value(_MIGRATION_KEY, False) != True:
        for key in legacy.allKeys():
            current.setValue(key, legacy.value(key))
        current.setValue(_MIGRATION_KEY, True)
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
