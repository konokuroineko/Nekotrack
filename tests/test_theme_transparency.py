"""Regression tests for translucent, theme-aware UI surface colors."""

import os
import re
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from ui.theme import (
    SURFACE_OPACITY,
    application_stylesheet,
    card_stylesheet,
    panel_stylesheet,
    retint_widget_styles,
    surface_rgba,
)


class ThemeTransparencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_surface_layers_have_different_opacity_levels(self):
        self.assertLess(SURFACE_OPACITY["background_alt"], SURFACE_OPACITY["surface"])
        self.assertLess(SURFACE_OPACITY["surface"], SURFACE_OPACITY["surface_alt"])
        self.assertLess(SURFACE_OPACITY["surface_alt"], SURFACE_OPACITY["surface_hover"])
        self.assertLess(SURFACE_OPACITY["card"], SURFACE_OPACITY["card_hover"])

        for key, percentage in SURFACE_OPACITY.items():
            with self.subTest(key=key):
                match = re.fullmatch(r"rgba\((\d+), (\d+), (\d+), (\d+)\)", surface_rgba(key))
                self.assertIsNotNone(match)
                self.assertEqual(int(match.group(4)), round(255 * percentage / 100))

    def test_shared_stylesheets_use_translucent_surface_colors(self):
        stylesheet = application_stylesheet()
        self.assertIn(f"background: {surface_rgba('surface')}", stylesheet)
        self.assertIn(f"background: {surface_rgba('surface_hover')}", stylesheet)
        self.assertIn(f"background: {surface_rgba('surface_alt')}", stylesheet)
        self.assertIn(f"background: {surface_rgba('surface')}", panel_stylesheet())
        self.assertIn(f"background: {surface_rgba('card')}", card_stylesheet())
        self.assertIn(f"background: {surface_rgba('card_hover')}", card_stylesheet())

    def test_live_theme_change_retints_rgba_without_losing_alpha(self):
        widget = QWidget()
        widget.setStyleSheet("QFrame { background: rgba(20, 17, 27, 199); }")
        widget.show()
        try:
            retint_widget_styles("Neko", "Sakura", False, False)
            self.assertIn("rgba(28, 21, 24, 199)", widget.styleSheet())
        finally:
            widget.close()


if __name__ == "__main__":
    unittest.main()
