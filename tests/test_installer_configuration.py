from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InstallerConfigurationTests(unittest.TestCase):
    def test_old_rollback_shortcut_is_removed_on_upgrade_not_recreated(self):
        script = (ROOT / "installer" / "NekoTrack.iss").read_text(encoding="utf-8")
        self.assertNotIn(
            'Name: "{group}\\Restore Previous NekoTrack Version"',
            script,
        )
        self.assertIn(
            'Type: files; Name: "{group}\\Restore Previous NekoTrack Version.lnk"',
            script,
        )

    def test_installer_uses_current_x64_architecture_identifier(self):
        script = (ROOT / "installer" / "NekoTrack.iss").read_text(encoding="utf-8")
        self.assertIn("ArchitecturesInstallIn64BitMode=x64compatible", script)
        self.assertNotIn("ArchitecturesInstallIn64BitMode=x64\n", script)

    def test_windows_app_identity_matches_the_installed_shortcuts(self):
        installer = (ROOT / "installer" / "NekoTrack.iss").read_text(encoding="utf-8")
        entrypoint = (ROOT / "main.py").read_text(encoding="utf-8")
        app_id = "konokuroineko.NekoTrack"
        self.assertIn(f'AppUserModelID: "{app_id}"', installer)
        self.assertIn(f'WINDOWS_APP_USER_MODEL_ID = "{app_id}"', entrypoint)
        self.assertIn("_set_windows_app_user_model_id()", entrypoint)

    def test_build_script_detects_per_user_inno_setup(self):
        script = (ROOT / "installer" / "build-installer.ps1").read_text(encoding="utf-8")
        self.assertIn('Programs\\Inno Setup 7\\ISCC.exe', script)
        self.assertIn('$isccPath = $candidatePaths |', script)

    def test_build_script_bundles_the_production_qml_view_and_qt_import_modules(self):
        script = (ROOT / "installer" / "build-installer.ps1").read_text(encoding="utf-8")
        self.assertIn('Join-Path $repoRoot "ui\\qml"', script)
        self.assertIn('--add-data "ui\\qml;ui\\qml"', script)
        self.assertIn('--add-data "$qtQmlDirectory;PySide6/Qt/qml"', script)
        self.assertIn('$qmlFile in @("LibraryView.qml", "ApplicationShell.qml", "PosterCard.qml", "NekoImage.qml", "NekoCheckBox.qml", "NekoSpinBox.qml", "NekoRoundedImage.qml")', script)
        self.assertIn('--add-data "ui\\qml;ui\\qml"', script)
        self.assertIn('--add-data "$qtQmlDirectory;PySide6/Qt/qml"', script)

    def test_installer_keeps_the_custom_executable_icon(self):
        script = (ROOT / "installer" / "build-installer.ps1").read_text(encoding="utf-8")
        self.assertIn('--icon "assets\\NekoTrack.ico"', script)
        installer = (ROOT / "installer" / "NekoTrack.iss").read_text(encoding="utf-8")
        self.assertIn("SetupIconFile=..\\assets\\NekoTrack.ico", installer)


if __name__ == "__main__":
    unittest.main()
