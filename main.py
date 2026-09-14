import os
import shutil
import sys
from pathlib import Path


APP_NAME = "NekoTrack"
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

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.preferences import get


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    if get("maximized"):
        window.showMaximized()
    else:
        window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
