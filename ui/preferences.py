from PySide6.QtCore import QSettings


_DEFAULTS = {
    "accent": "#ff9f43",
    "accent_hover": "#ffb765",
    "frame_color": "#ff9f43",
    "background": "#0a0b0e",
    "surface": "#13161c",
    "surface_hover": "#202631",
    "card": "#12151b",
    "card_hover": "#1a1f27",
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


def settings():
    """Return NekoTrack's settings store, migrating old AniTrack keys when needed."""
    current = QSettings(_ORGANIZATION, _APPLICATION)
    legacy = QSettings(_LEGACY_ORGANIZATION, _LEGACY_APPLICATION)

    # The app was renamed from AniTrack to NekoTrack. Copy only keys that do
    # not already exist so an existing NekoTrack preference is never replaced.
    legacy_keys = legacy.allKeys()
    if legacy_keys:
        current_keys = set(current.allKeys())
        changed = False
        for key in legacy_keys:
            if key not in current_keys:
                current.setValue(key, legacy.value(key))
                changed = True
        if changed:
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
    qsettings.sync()
