import unittest
from unittest.mock import patch

import ui.preferences as preferences


class MemorySettings:
    stores = {}

    def __init__(self, organization, application):
        self.store = self.stores.setdefault((organization, application), {})

    def value(self, key, default=None):
        return self.store.get(key, default)

    def setValue(self, key, value):
        self.store[key] = value

    def allKeys(self):
        return list(self.store)

    def sync(self):
        pass


class PreferenceMigrationTests(unittest.TestCase):
    def setUp(self):
        MemorySettings.stores = {
            ("NekoTrack", "NekoTrack"): {
                preferences._MIGRATION_KEY: "true",
                "theme_preset": "Ocean",
                "_theme_palette_version": "6",
                "accent": "#000080",
                "font_size": "15",
                "card_size": "240",
                "corner_radius": "18",
            },
            ("AniTrack", "AniTrack"): {
                "theme_preset": "Neko",
                "accent": "#000080",
                "font_size": "11",
            },
        }

    def test_old_extras_mode_migrates_to_all_individual_options(self):
        MemorySettings.stores[("NekoTrack", "NekoTrack")]["bundle_mode"] = "extras"

        with patch.object(preferences, "QSettings", MemorySettings):
            settings = preferences.settings()

        for key in preferences.BUNDLE_OPTION_KEYS:
            self.assertTrue(settings.value(key), key)
        self.assertTrue(settings.value("_bundle_options_v1_migrated"))

    def test_old_main_mode_defaults_each_optional_format_to_disabled(self):
        MemorySettings.stores[("NekoTrack", "NekoTrack")]["bundle_mode"] = "main"

        with patch.object(preferences, "QSettings", MemorySettings):
            settings = preferences.settings()

        for key in preferences.BUNDLE_OPTION_KEYS:
            self.assertFalse(settings.value(key), key)

    def test_string_true_migration_flag_does_not_restore_legacy_colors(self):
        with patch.object(preferences, "QSettings", MemorySettings):
            settings = preferences.settings()

        self.assertEqual(settings.value("theme_preset"), "Ocean")
        self.assertEqual(settings.value("accent"), preferences.THEME_PRESETS["Ocean"]["accent"])
        self.assertEqual(settings.value("_theme_palette_version"), preferences._THEME_PALETTE_VERSION)

        # Palette cleanup must not reset unrelated user preferences.
        self.assertEqual(settings.value("font_size"), "15")
        self.assertEqual(settings.value("card_size"), "240")
        self.assertEqual(settings.value("corner_radius"), "18")

    def test_invalid_palette_version_recovers_without_resetting_layout_preferences(self):
        MemorySettings.stores[("NekoTrack", "NekoTrack")].update({
            "theme_preset": "Sakura",
            "_theme_palette_version": "not-a-version",
            "accent": "#000080",
        })

        with patch.object(preferences, "QSettings", MemorySettings):
            settings = preferences.settings()

        self.assertEqual(settings.value("theme_preset"), "Sakura")
        self.assertEqual(settings.value("accent"), preferences.THEME_PRESETS["Sakura"]["accent"])
        self.assertEqual(settings.value("_theme_palette_version"), preferences._THEME_PALETTE_VERSION)
        self.assertEqual(settings.value("font_size"), "15")
        self.assertEqual(settings.value("card_size"), "240")
        self.assertEqual(settings.value("corner_radius"), "18")


    def test_corrupt_numeric_preferences_are_bounded(self):
        MemorySettings.stores[("NekoTrack", "NekoTrack")].update({
            "_theme_palette_version": preferences._THEME_PALETTE_VERSION,
            "_bundle_options_v1_migrated": True,
            "font_size": float("inf"),
            "card_size": -500,
            "card_gap": 1000000,
            "corner_radius": -1,
            "animation_speed": 10**9,
        })

        with patch.object(preferences, "QSettings", MemorySettings):
            self.assertEqual(preferences.get("font_size"), 36)
            self.assertEqual(preferences.get("card_size"), 120)
            self.assertEqual(preferences.get("card_gap"), 120)
            self.assertEqual(preferences.get("corner_radius"), 0)
            self.assertEqual(preferences.get("animation_speed"), 2000)

    def test_corrupt_boolean_and_string_preferences_fall_back_safely(self):
        MemorySettings.stores[("NekoTrack", "NekoTrack")].update({
            "_theme_palette_version": preferences._THEME_PALETTE_VERSION,
            "_bundle_options_v1_migrated": True,
            "hover_highlight": {"unexpected": "object"},
            "resize_animation": " maybe ",
            "maximized": " off ",
            "tmdb_api_token": ["not", "a", "string"],
        })

        with patch.object(preferences, "QSettings", MemorySettings):
            self.assertTrue(preferences.get("hover_highlight"))
            self.assertTrue(preferences.get("resize_animation"))
            self.assertFalse(preferences.get("maximized"))
            self.assertEqual(preferences.get("tmdb_api_token"), "")

    def test_set_value_cannot_persist_pathological_ui_values(self):
        MemorySettings.stores[("NekoTrack", "NekoTrack")].update({
            "_theme_palette_version": preferences._THEME_PALETTE_VERSION,
            "_bundle_options_v1_migrated": True,
        })

        with patch.object(preferences, "QSettings", MemorySettings):
            preferences.set_value("card_size", -400)
            preferences.set_value("font_size", 1000000)
            preferences.set_value("hover_highlight", "maybe")
            settings = preferences.settings()

        self.assertEqual(settings.value("card_size"), 120)
        self.assertEqual(settings.value("font_size"), 36)
        self.assertTrue(settings.value("hover_highlight"))


if __name__ == "__main__":
    unittest.main()
