from PySide6.QtCore import QSettings


_DEFAULTS = {
    "accent": "#e4a45e",
    "accent_hover": "#efb978",
    "frame_color": "#e4a45e",
    "background": "#0d0f10",
    "surface": "#171a1d",
    "surface_hover": "#1b1f22",
    "card": "#181c1f",
    "card_hover": "#22272b",
    "font_size": 13,
    "card_size": 210,
    "card_gap": 24,
    "corner_radius": 12,
    "hover_highlight": True,
    "resize_animation": True,
    "animation_speed": 260,
    "maximized": True,
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

    # The rename previously allowed NekoTrack's new defaults to mask the old
    # AniTrack preferences. Migrate legacy values once, even when the new
    # store already contains defaults.
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


def defaults():
    return dict(_DEFAULTS)


def reset():
    qsettings = settings()
    qsettings.clear()
    # Keep the migration marker so Reset restores defaults rather than
    # immediately importing the legacy AniTrack preferences again.
    qsettings.setValue(_MIGRATION_KEY, True)
    qsettings.sync()
