import os
import shutil
import sys
from pathlib import Path


APP_NAME = "NekoTrack"
APP_VERSION = "0.1.0-beta.2"
APP_DATA_DIR = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")) / APP_NAME


def _legacy_data_dir():
    """Return the directory used by older portable/source builds."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def prepare_user_data():
    """Create the per-user data directory and migrate an older local data set once."""
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

    legacy_dir = _legacy_data_dir()
    legacy_db = legacy_dir / "anime_tracker.db"
    target_db = APP_DATA_DIR / "anime_tracker.db"

    if not target_db.exists() and legacy_db.exists() and legacy_db.resolve() != target_db.resolve():
        shutil.copy2(legacy_db, target_db)

    legacy_images = legacy_dir / "data" / "images"
    target_images = APP_DATA_DIR / "data" / "images"
    if legacy_images.exists() and not target_images.exists() and legacy_images.resolve() != target_images.resolve():
        target_images.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(legacy_images, target_images)

    os.chdir(APP_DATA_DIR)


prepare_user_data()

from PySide6.QtWidgets import QApplication, QMessageBox

from ui.main_window import MainWindow
from ui.preferences import get
from updater import InstallerDownloader, UpdateChecker


def _offer_update(window, update_info):
    answer = QMessageBox.question(
        window,
        "NekoTrack update available",
        f"NekoTrack {update_info.version} is available.\n\nYou are using {APP_VERSION}.\n\nDownload and install the update now?",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )
    if answer != QMessageBox.Yes:
        return

    downloader = InstallerDownloader(update_info.asset_url, update_info.asset_name, window)

    def failed(message):
        QMessageBox.warning(window, "Update failed", f"NekoTrack could not download the update.\n\n{message}")
        downloader.deleteLater()

    def finished(_path):
        downloader.deleteLater()
        QMessageBox.information(window, "Update downloaded", "The installer has been opened. NekoTrack will now close so the update can be installed.")
        QApplication.quit()

    downloader.failed.connect(failed)
    downloader.finished.connect(finished)
    window._update_downloader = downloader
    downloader.start()


def _check_for_updates(window):
    checker = UpdateChecker(APP_VERSION, window)
    checker.update_available.connect(lambda info: _offer_update(window, info))
    window._update_checker = checker
    checker.start()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    if get("maximized"):
        window.showMaximized()
    else:
        window.show()

    # Update checks run in the background so startup is not blocked by network/VPN latency.
    _check_for_updates(window)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
