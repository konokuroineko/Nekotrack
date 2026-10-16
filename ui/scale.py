"""App-wide Qt interface scaling configured before QApplication is created."""

import os


SUPPORTED_UI_SCALES = (80, 90, 100, 110, 125, 150, 175, 200)


def configure_ui_scale(scale_percent):
    """Set Qt's global scale multiplier before QApplication construction.

    Qt still respects the operating system's display scale; this preference
    multiplies the app's geometry by the selected percentage. A restart is
    required because Qt reads QT_SCALE_FACTOR while initializing the GUI.
    """
    try:
        scale = int(scale_percent)
    except (TypeError, ValueError, OverflowError):
        scale = 100
    if scale not in SUPPORTED_UI_SCALES:
        scale = 100

    factor = scale / 100
    factor_text = f"{factor:.2f}".rstrip("0").rstrip(".")
    os.environ["QT_SCALE_FACTOR"] = factor_text
    return scale
