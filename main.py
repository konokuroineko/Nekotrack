import os
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF


APP_NAME = "NekoTrack"
APP_VERSION = "0.1.0-beta.2"
APP_DATA_DIR = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")) / APP_NAME

from diagnostics import (
    configure_logging,
    install_qt_message_handler,
    log_event,
    log_operation,
    log_runtime_snapshot,
)


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


try:
    configure_logging(APP_DATA_DIR)
except Exception as logging_error:
    # Diagnostics are best-effort and must never prevent startup.
    print(f"NekoTrack could not initialize its log file: {logging_error}", file=sys.stderr)
log_event(
    "startup.bootstrap",
    app_version=APP_VERSION,
    frozen=bool(getattr(sys, "frozen", False)),
    executable=Path(sys.executable).name,
)
with log_operation("startup.prepare_user_data"):
    prepare_user_data()

from PySide6.QtWidgets import QApplication, QComboBox, QMessageBox, QProxyStyle, QStyle

install_qt_message_handler()

from ui.branding import application_icon
from ui.main_window import MainWindow
from ui.preferences import get
from ui.scale import configure_ui_scale
from ui.theme import COLORS
from ui.setup_wizard import SetupWizard
from updater import InstallerDownloader, UpdateChecker


class NekoProxyStyle(QProxyStyle):
    """Use Qt styling without the platform focus rectangle."""
    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PrimitiveElement.PE_FrameFocusRect:
            return
        if (
            element == QStyle.PrimitiveElement.PE_IndicatorArrowDown
            and isinstance(widget, QComboBox)
        ):
            center = option.rect.center()
            color = COLORS["accent"] if widget.underMouse() else COLORS["muted"]
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            pen = QPen(QColor(color), 1.8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolyline(QPolygonF([
                QPointF(center.x() - 4.0, center.y() - 1.0),
                QPointF(center.x(), center.y() + 3.0),
                QPointF(center.x() + 4.0, center.y() - 1.0),
            ]))
            painter.restore()
            return
        super().drawPrimitive(element, option, painter, widget)


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
    log_event(
        "app.launch",
        setup_forced="--setup" in sys.argv,
        argument_count=len(sys.argv),
    )
    # Qt reads this multiplier during QApplication construction, so user scale
    # preferences must be applied before the first GUI application is created.
    ui_scale = get("ui_scale")
    configure_ui_scale(ui_scale)
    log_event("startup.ui_scale_configured", ui_scale_percent=ui_scale)
    with log_operation("startup.create_qapplication"):
        app = QApplication(sys.argv)
    app.setStyle(NekoProxyStyle("Fusion"))
    app.setWindowIcon(application_icon())
    log_runtime_snapshot(APP_VERSION)

    # The first-launch wizard configures preferences only; it does not touch
    # the user's SQLite library or cached artwork. --setup is a developer/user
    # testing switch that reopens the wizard without resetting any data.
    force_setup = "--setup" in sys.argv
    setup_complete = bool(get("setup_complete"))
    log_event(
        "startup.setup_check",
        forced=force_setup,
        setup_complete=setup_complete,
    )
    if force_setup or not setup_complete:
        with log_operation("startup.setup_wizard", forced=force_setup):
            wizard = SetupWizard()
            wizard.exec()

    with log_operation("startup.create_main_window"):
        window = MainWindow()
    if get("maximized"):
        window.showMaximized()
    else:
        window.show()

    log_event("app.ready", maximized=bool(get("maximized")))
    # Update checks run in the background so startup is not blocked by network/VPN latency.
    _check_for_updates(window)

    with log_operation("app.event_loop"):
        exit_code = app.exec()
    log_event("app.exit", exit_code=exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
