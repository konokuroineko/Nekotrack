import os
import shutil
import sys
import time
import uuid
from pathlib import Path

_BOOTSTRAP_STARTED_AT = time.perf_counter()

from PySide6.QtCore import QObject, QPointF, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPen, QPolygonF


APP_NAME = "NekoTrack"
WINDOWS_APP_USER_MODEL_ID = "konokuroineko.NekoTrack"


def _set_windows_app_user_model_id():
    """Keep NekoTrack windows grouped under its own identity, not Python's."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            WINDOWS_APP_USER_MODEL_ID
        )
    except (AttributeError, OSError):
        # The explicit taskbar ID is a Windows shell enhancement, not a startup
        # requirement; unsupported environments must still launch normally.
        pass


# Windows reads this identity when it first creates taskbar buttons. Set it
# before importing/constructing QApplication or any other visible Qt widgets.
_set_windows_app_user_model_id()


def _load_app_version():
    """Read the canonical version from the source tree or PyInstaller bundle."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    try:
        version = (bundle_root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        version = ""
    return version or "1.0.0"


APP_VERSION = _load_app_version()
APP_DATA_DIR = Path(
    os.environ.get("NEKOTRACK_DATA_DIR")
    or (Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")) / APP_NAME)
).expanduser().resolve()

from native_acceleration import BACKEND_NAME as NATIVE_ACCELERATION_BACKEND

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
    native_acceleration_backend=NATIVE_ACCELERATION_BACKEND,
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
from updater import (
    InstallerDownloader,
    UpdateChecker,
    _is_trusted_release_page_url,
    find_previous_update_backup,
    launch_update_helper,
)


log_event(
    "startup.python_bootstrap_completed",
    elapsed_ms=round((time.perf_counter() - _BOOTSTRAP_STARTED_AT) * 1000, 2),
)


class _UpdateUiBridge(QObject):
    update_available = Signal(object)
    no_update_available = Signal(bool)
    check_failed = Signal(str, bool)
    download_staged = Signal(str)
    download_failed = Signal(str)

    def __init__(self, parent=None, *, manual=False):
        super().__init__(parent)
        self.manual = bool(manual)

    @Slot(object)
    def relay_update_available(self, info):
        self.update_available.emit(info)

    @Slot()
    def relay_no_update_available(self):
        self.no_update_available.emit(self.manual)

    @Slot(str)
    def relay_check_failed(self, message):
        self.check_failed.emit(str(message), self.manual)

    @Slot(str)
    def relay_download_staged(self, backup_path):
        self.download_staged.emit(str(backup_path))

    @Slot(str)
    def relay_download_failed(self, message):
        self.download_failed.emit(str(message))


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


def _release_page_url(update_info):
    url = getattr(update_info, "release_url", None)
    return url if _is_trusted_release_page_url(url) else None


def _open_manual_release_page(window, update_info, message=None):
    release_url = _release_page_url(update_info)
    if not release_url:
        if message:
            QMessageBox.warning(window, "NekoTrack update", message)
        return
    if message:
        answer = QMessageBox.question(
            window,
            "NekoTrack update available",
            message + "\n\nOpen the official GitHub release page?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return
    QDesktopServices.openUrl(QUrl(release_url))


def _offer_update(window, update_info):
    if not update_info.asset_url or not update_info.asset_name:
        _open_manual_release_page(
            window,
            update_info,
            f"NekoTrack {update_info.version} is available, but this release has no supported executable asset.",
        )
        return

    # Source runs must never try to overwrite Python files or run a portable EXE
    # in place of their interpreter. Let the user download/install it manually.
    if not getattr(sys, "frozen", False):
        _open_manual_release_page(
            window,
            update_info,
            f"NekoTrack {update_info.version} is available. This copy is running from source, so it cannot update itself safely.",
        )
        return

    answer = QMessageBox.question(
        window,
        "NekoTrack update available",
        (
            f"NekoTrack {update_info.version} is available.\n\n"
            f"You are using {APP_VERSION}.\n\n"
            "NekoTrack will keep a verified copy of the current app and a consistent "
            "SQLite backup before replacing anything. If the updated app fails its "
            "first startup check, the previous version is restored automatically.\n\n"
            "Download and install this update now?"
        ),
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if answer != QMessageBox.Yes:
        return

    install_directory = Path(sys.executable).resolve().parent
    bundled_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    helper_script = bundled_root / "installer" / "safe_update.ps1"
    downloader = InstallerDownloader(
        update_info.asset_url,
        update_info.asset_name,
        window,
        digest=getattr(update_info, "digest", None),
        current_version=APP_VERSION,
        target_version=update_info.version,
        data_directory=APP_DATA_DIR,
        database_path=APP_DATA_DIR / "anime_tracker.db",
        install_directory=install_directory,
        current_executable=Path(sys.executable),
        helper_script=helper_script,
        process_id=os.getpid(),
    )

    bridge = _UpdateUiBridge(window)

    def failed(message):
        QMessageBox.warning(
            window,
            "NekoTrack update failed",
            "The update could not be staged. Your installed executable was not replaced.\n\n"
            + str(message),
        )

    def finished(backup_path):
        QMessageBox.information(
            window,
            "NekoTrack update is starting",
            "The update helper has been launched. The previous app and a database snapshot "
            "were saved before replacement. NekoTrack will close now.",
        )
        QApplication.quit()

    downloader.failed.connect(bridge.relay_download_failed)
    downloader.download_staged.connect(bridge.relay_download_staged)
    bridge.download_failed.connect(failed)
    bridge.download_staged.connect(finished)
    window._update_downloader = downloader
    window._update_download_bridge = bridge
    downloader.start()


def _preferred_update_asset():
    """Avoid running Setup against an unrelated portable/preview install."""
    if not getattr(sys, "frozen", False):
        return "setup"
    local_app_data = Path(
        os.environ.get("LOCALAPPDATA")
        or (Path.home() / "AppData" / "Local")
    )
    setup_directory = (local_app_data / "Programs" / APP_NAME).resolve()
    current_directory = Path(sys.executable).resolve().parent
    return (
        "setup"
        if os.path.normcase(str(current_directory)) == os.path.normcase(str(setup_directory))
        else "portable"
    )


def _check_for_updates(window, manual=False):
    existing = getattr(window, "_update_checker", None)
    if existing is not None:
        try:
            if existing.isRunning():
                if manual:
                    QMessageBox.information(window, "NekoTrack updates", "An update check is already running.")
                return
        except RuntimeError:
            pass

    checker = UpdateChecker(
        APP_VERSION,
        window,
        include_prereleases=(get("update_channel") == "preview"),
        preferred_asset=_preferred_update_asset(),
    )

    def update_available(info):
        _offer_update(window, info)

    def no_update():
        QMessageBox.information(window, "NekoTrack updates", f"NekoTrack {APP_VERSION} is up to date on the {get('update_channel')} channel.")

    def check_failed(message):
        log_event("updater.check_failed", error=message, manual=bool(manual))
        QMessageBox.warning(window, "NekoTrack update check failed", str(message))

    bridge = _UpdateUiBridge(window, manual=manual)
    checker.update_available.connect(bridge.relay_update_available)
    checker.no_update_available.connect(bridge.relay_no_update_available)
    checker.check_failed.connect(bridge.relay_check_failed)
    bridge.update_available.connect(update_available)
    bridge.no_update_available.connect(
        lambda manual_check: no_update() if manual_check else None
    )
    bridge.check_failed.connect(
        lambda message, manual_check: check_failed(message)
        if manual_check else log_event("updater.check_failed", error=message, manual=False)
    )
    window._update_checker = checker
    window._update_check_bridge = bridge
    checker.start()


def _rollback_previous_version(window):
    if not getattr(sys, "frozen", False):
        QMessageBox.information(
            window, "NekoTrack rollback",
            "Rollback is available in an installed Windows build, not when running python main.py.",
        )
        return

    backup = find_previous_update_backup(APP_DATA_DIR)
    if backup is None:
        QMessageBox.information(
            window, "NekoTrack rollback",
            "No complete previous-version backup was found in this app's data directory "
            "(update_backups).",
        )
        return

    answer = QMessageBox.question(
        window,
        "Restore previous NekoTrack version?",
        (
            "NekoTrack will restore the saved application executable and restart.\n\n"
            "Your current library, watch/read progress, preferences, and artwork will be left alone. "
            "The matching database snapshot will remain in the backup folder in case it is needed."
        ),
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if answer != QMessageBox.Yes:
        return

    install_directory = Path(sys.executable).resolve().parent
    bundled_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    helper_script = bundled_root / "installer" / "safe_update.ps1"
    try:
        launch_update_helper(
            helper_script, "RollbackOnly", install_directory, APP_DATA_DIR, backup,
            os.getpid(), attempt_id=uuid.uuid4().hex,
        )
    except Exception as error:
        QMessageBox.warning(window, "NekoTrack rollback failed", str(error))
        return
    QMessageBox.information(
        window, "NekoTrack rollback",
        "The recovery helper has started. NekoTrack will close and restore the previous executable.",
    )
    QApplication.quit()

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
    # Paint the main window first; start recommendations and episode metadata
    # only after the application is visibly ready.
    QTimer.singleShot(150, window.start_initial_background_work)

    window.check_updates_requested.connect(lambda: _check_for_updates(window, manual=True))
    window.rollback_requested.connect(lambda: _rollback_previous_version(window))

    health_file = os.environ.get("NEKOTRACK_UPDATE_HEALTH_FILE")
    if health_file:
        try:
            health_path = Path(health_file)
            health_path.parent.mkdir(parents=True, exist_ok=True)
            health_path.write_text(APP_VERSION, encoding="utf-8")
            log_event("updater.startup_health_written", version=APP_VERSION)
        except OSError as health_error:
            log_event("updater.startup_health_write_failed", error=str(health_error))

    if get("auto_check_updates"):
        # Don't start an 8-second network request during launch. Keep the update
        # check automatic, but start it only after the app has settled.
        def start_automatic_update_check():
            if (
                window.isVisible()
                and not getattr(window, "_shutdown_requested", False)
            ):
                _check_for_updates(window, manual=False)

        QTimer.singleShot(2_000, start_automatic_update_check)

    with log_operation("app.event_loop"):
        exit_code = app.exec()

    # A user may close NekoTrack while the background release check is in
    # flight. Let those bounded-timeout QThreads finish before their parent
    # window is destroyed; otherwise Qt can abort during shutdown.
    for worker_name in ("_update_checker", "_update_downloader"):
        worker = getattr(window, worker_name, None)
        if worker is None:
            continue
        try:
            if worker.isRunning():
                cancel = getattr(worker, "cancel", None)
                if callable(cancel):
                    cancel()
                else:
                    worker.requestInterruption()
                # Do not destroy a still-running QThread during app shutdown.
                # The downloader checks cancellation between chunks; checker
                # requests use a bounded network timeout.
                while worker.isRunning():
                    worker.wait(500)
        except RuntimeError:
            pass

    log_event("app.exit", exit_code=exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
