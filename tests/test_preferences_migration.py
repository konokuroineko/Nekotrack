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


if __name__ == "__main__":
    unittest.main()
