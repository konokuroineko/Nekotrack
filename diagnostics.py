"""Persistent, privacy-conscious diagnostics for NekoTrack.

The app writes rotating logs under the per-user NekoTrack data directory.
Run python diagnostics.py --export-to-repo to collect a shareable report.
This module intentionally avoids importing Qt or any application modules.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import importlib.util
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import platform
from pathlib import Path
import re
import struct
import sys
import threading
import time
from typing import Any


APP_NAME = "NekoTrack"
PROJECT_ROOT = Path(__file__).resolve().parent
LOG_FILE_NAME = "nekotrack.log"
MAX_LOG_BYTES = 2_000_000
LOG_BACKUP_COUNT = 4
MAX_FIELD_TEXT = 800
MAX_EXPORT_BYTES = 12_000_000

_LOGGER = logging.getLogger("nekotrack")
_EVENT_CONTEXT = ContextVar("nekotrack_event_context", default={})
_LOCK = threading.RLock()
_CONFIGURED = False
_CONFIGURED_DATA_DIR: Path | None = None
_FILE_HANDLER: RotatingFileHandler | None = None
_QT_MESSAGE_HANDLER = None
_ORIGINAL_SYS_EXCEPTHOOK = sys.excepthook
_ORIGINAL_THREAD_EXCEPTHOOK = getattr(threading, "excepthook", None)
_ORIGINAL_UNRAISABLEHOOK = getattr(sys, "unraisablehook", None)

_SECRET_ASSIGNMENT = re.compile(
    r"""(?i)(["']?\b(?:tmdb[_-]?api[_-]?token|api[_-]?token|api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret|client_secret)\b["']?\s*[:=]\s*)"""
    r"""("[^"]*"|'[^']*'|[^&\s,;}\]]+)"""
)
_AUTH_HEADER = re.compile(
    r"""(?i)(["']?\b(?:proxy-)?authorization\b["']?\s*[:=]\s*["']?(?:bearer|basic)\s+)[^\s,;}"']+"""
)
_BEARER_VALUE = re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]{12,}")
_URL_SECRET = re.compile(
    r"(?i)([?&](?:tmdb[_-]?api[_-]?token|api[_-]?token|api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)=)[^&#\s]+"
)
_SENSITIVE_KEY = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|authorization|cookie)"
)
_OMIT_KEYS = {
    "query", "variables", "payload", "body", "request_body", "response_body",
    "response_text", "headers", "sql", "description", "notes", "synopsis",
}


def default_app_data_dir() -> Path:
    """Match the application data directory selected by main.py."""
    base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_NAME


def log_directory(app_data_dir: str | os.PathLike[str] | None = None) -> Path:
    root = Path(app_data_dir) if app_data_dir is not None else (
        _CONFIGURED_DATA_DIR or default_app_data_dir()
    )
    return root / "logs"


def get_log_path() -> Path:
    """Return the currently configured log file path."""
    return log_directory() / LOG_FILE_NAME


def _replace_path(text: str, path: Path, label: str) -> str:
    try:
        raw = str(path)
        if raw and raw != ".":
            text = re.sub(re.escape(raw), label, text, flags=re.IGNORECASE)
            alternate = raw.replace("\\", "/")
            if alternate != raw:
                text = re.sub(re.escape(alternate), label, text, flags=re.IGNORECASE)
    except (OSError, RuntimeError, ValueError):
        pass
    return text


def redact_text(value: Any, app_data_dir: str | os.PathLike[str] | None = None,
                project_root: str | os.PathLike[str] | None = None) -> str:
    """Redact credentials and the most common personal path fragments."""
    text = str(value)
    text = _AUTH_HEADER.sub(r"\1<redacted>", text)
    text = _URL_SECRET.sub(r"\1<redacted>", text)
    text = _SECRET_ASSIGNMENT.sub(r"\1<redacted>", text)
    text = _BEARER_VALUE.sub(r"\1<redacted>", text)

    data_dir = Path(app_data_dir) if app_data_dir is not None else (
        _CONFIGURED_DATA_DIR or default_app_data_dir()
    )
    root_dir = Path(project_root) if project_root is not None else PROJECT_ROOT
    text = _replace_path(text, data_dir, "<APP_DATA_DIR>")
    text = _replace_path(text, root_dir, "<PROJECT_ROOT>")
    text = _replace_path(text, Path.home(), "<USER_HOME>")
    return text


def _safe_value(key: str, value: Any, depth: int = 0) -> Any:
    """Limit and sanitize event metadata before it reaches the log."""
    key_text = str(key)
    if _SENSITIVE_KEY.search(key_text):
        return "<redacted>"
    if key_text.casefold() in _OMIT_KEYS:
        return "<omitted>"
    if depth > 4:
        return "<maximum nesting omitted>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Path):
        return redact_text(value)
    if isinstance(value, dict):
        safe = {}
        for index, (child_key, child_value) in enumerate(value.items()):
            if index >= 30:
                safe["_remaining_fields"] = "omitted"
                break
            safe[str(child_key)] = _safe_value(str(child_key), child_value, depth + 1)
        return safe
    if isinstance(value, (list, tuple, set, frozenset)):
        values = list(value)
        safe_values = [
            _safe_value(key_text, item, depth + 1)
            for item in values[:100]
        ]
        if len(values) > 100:
            safe_values.append("<remaining items omitted>")
        return safe_values
    text = redact_text(value)
    if len(text) > MAX_FIELD_TEXT:
        text = text[:MAX_FIELD_TEXT] + "…<truncated>"
    return text


def _event_payload(event: str, fields: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "event": str(event),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "thread": threading.current_thread().name,
    }
    for key, value in (_EVENT_CONTEXT.get() or {}).items():
        payload[str(key)] = _safe_value(str(key), value)
    for key, value in fields.items():
        payload[str(key)] = _safe_value(str(key), value)
    return payload


@contextmanager
def diagnostic_context(**fields: Any):
    """Attach identifiers to events emitted during the current operation/thread."""
    inherited = dict(_EVENT_CONTEXT.get() or {})
    inherited.update(fields)
    token = _EVENT_CONTEXT.set(inherited)
    try:
        yield
    finally:
        _EVENT_CONTEXT.reset(token)

def log_event(event: str, level: int = logging.INFO, **fields: Any) -> None:
    """Write one JSON-formatted event without allowing diagnostics to break the app."""
    try:
        payload = _event_payload(event, fields)
        _LOGGER.log(
            level,
            "%s",
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
        )
    except Exception:
        try:
            _LOGGER.warning("diagnostics.event_write_failed event=%s", str(event)[:100])
        except Exception:
            pass


def log_exception(event: str, error: BaseException, **fields: Any) -> None:
    """Write error context and a traceback, with formatter-level redaction."""
    try:
        fields.setdefault("error_type", type(error).__name__)
        fields.setdefault("error", str(error))
        payload = _event_payload(event, fields)
        _LOGGER.error(
            "%s",
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
            exc_info=(type(error), error, error.__traceback__),
        )
    except Exception:
        try:
            _LOGGER.error("diagnostics.exception_write_failed event=%s", str(event)[:100])
        except Exception:
            pass


class _RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


def _handle_uncaught_exception(exc_type, exc_value, exc_tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        _ORIGINAL_SYS_EXCEPTHOOK(exc_type, exc_value, exc_tb)
        return
    try:
        _LOGGER.critical(
            "Uncaught main-thread exception",
            exc_info=(exc_type, exc_value, exc_tb),
        )
    finally:
        _ORIGINAL_SYS_EXCEPTHOOK(exc_type, exc_value, exc_tb)


def _handle_thread_exception(args) -> None:
    try:
        _LOGGER.critical(
            "Uncaught background-thread exception in %s",
            getattr(args.thread, "name", "<unknown>"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
    finally:
        if _ORIGINAL_THREAD_EXCEPTHOOK:
            _ORIGINAL_THREAD_EXCEPTHOOK(args)


def _handle_unraisable_exception(args) -> None:
    try:
        object_name = getattr(args.object, "__qualname__", type(args.object).__name__)
        _LOGGER.error(
            "Unraisable exception in %s: %s",
            object_name,
            args.err_msg or "",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
    finally:
        if _ORIGINAL_UNRAISABLEHOOK:
            _ORIGINAL_UNRAISABLEHOOK(args)


def configure_logging(app_data_dir: str | os.PathLike[str] | None = None) -> Path:
    """Install the rotating file handler and process-level crash hooks."""
    global _CONFIGURED, _CONFIGURED_DATA_DIR, _FILE_HANDLER
    target_dir = Path(app_data_dir) if app_data_dir is not None else default_app_data_dir()
    with _LOCK:
        if _CONFIGURED and _CONFIGURED_DATA_DIR == target_dir and _FILE_HANDLER:
            return Path(_FILE_HANDLER.baseFilename)

        target_log_dir = target_dir / "logs"
        target_log_dir.mkdir(parents=True, exist_ok=True)

        root_logger = logging.getLogger()
        for existing in list(root_logger.handlers):
            if getattr(existing, "_nekotrack_diagnostics_handler", False):
                root_logger.removeHandler(existing)
                try:
                    existing.close()
                except Exception:
                    pass

        handler = RotatingFileHandler(
            target_log_dir / LOG_FILE_NAME,
            maxBytes=MAX_LOG_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
            delay=False,
        )
        handler._nekotrack_diagnostics_handler = True
        handler.setLevel(logging.INFO)
        handler.setFormatter(_RedactingFormatter(
            "%(asctime)s.%(msecs)03d %(levelname)s [%(threadName)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        root_logger.addHandler(handler)
        root_logger.setLevel(min(root_logger.level or logging.INFO, logging.INFO))

        logging.captureWarnings(True)
        sys.excepthook = _handle_uncaught_exception
        if hasattr(threading, "excepthook"):
            threading.excepthook = _handle_thread_exception
        if hasattr(sys, "unraisablehook"):
            sys.unraisablehook = _handle_unraisable_exception

        _CONFIGURED = True
        _CONFIGURED_DATA_DIR = target_dir
        _FILE_HANDLER = handler
        log_event(
            "diagnostics.logging_started",
            log_file=LOG_FILE_NAME,
            rotation_bytes=MAX_LOG_BYTES,
            backup_count=LOG_BACKUP_COUNT,
        )
        return Path(handler.baseFilename)


@contextmanager
def log_operation(operation: str, **fields: Any):
    """Record start, elapsed time, completion, and failures around an operation."""
    started = time.monotonic()
    log_event("operation.started", operation=operation, **fields)
    try:
        yield
    except BaseException as error:
        log_exception(
            "operation.failed",
            error,
            operation=operation,
            elapsed_ms=round((time.monotonic() - started) * 1000, 2),
            **fields,
        )
        raise
    else:
        log_event(
            "operation.completed",
            operation=operation,
            elapsed_ms=round((time.monotonic() - started) * 1000, 2),
            **fields,
        )


def install_qt_message_handler() -> bool:
    """Capture Qt warnings/errors without making Qt a dependency of this module."""
    global _QT_MESSAGE_HANDLER
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except Exception:
        return False

    level_map = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def _qt_handler(mode, context, message):
        level = level_map.get(mode, logging.WARNING)
        log_event(
            "qt.message",
            level=level,
            qt_level=getattr(mode, "name", str(mode)),
            category=getattr(context, "category", None),
            file=Path(context.file).name if getattr(context, "file", None) else None,
            line=getattr(context, "line", None),
            message=message,
        )

    _QT_MESSAGE_HANDLER = _qt_handler
    try:
        qInstallMessageHandler(_qt_handler)
    except Exception as error:
        log_exception("diagnostics.qt_handler_install_failed", error)
        _QT_MESSAGE_HANDLER = None
        return False
    log_event("diagnostics.qt_handler_installed")
    return True


def log_runtime_snapshot(app_version: str | None = None,
                         database_name: str = "anime_tracker.db") -> None:
    """Record useful environment metadata without dumping user data or DB contents."""
    data_dir = _CONFIGURED_DATA_DIR or default_app_data_dir()
    database = data_dir / database_name
    try:
        database_exists = database.is_file()
        database_size = database.stat().st_size if database_exists else None
    except OSError:
        database_exists, database_size = False, None
    try:
        from PySide6 import __version__ as pyside_version
    except Exception:
        pyside_version = None
    log_event(
        "runtime.snapshot",
        app=APP_NAME,
        app_version=app_version,
        python_version=sys.version.split()[0],
        python_executable=Path(sys.executable).name,
        os_name=platform.system(),
        os_release=platform.release(),
        platform=platform.platform(),
        architecture=struct.calcsize("P") * 8,
        frozen=bool(getattr(sys, "frozen", False)),
        pyside_version=pyside_version,
        database_exists=database_exists,
        database_size_bytes=database_size,
        log_rotation_bytes=MAX_LOG_BYTES,
        log_backup_count=LOG_BACKUP_COUNT,
    )


def _source_version(project_root: Path) -> str | None:
    try:
        source = (project_root / "main.py").read_text(encoding="utf-8", errors="replace")
        match = re.search(r'^\s*APP_VERSION\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
        return match.group(1) if match else None
    except OSError:
        return None


def _ordered_log_files(directory: Path) -> list[Path]:
    try:
        files = [path for path in directory.glob(LOG_FILE_NAME + "*") if path.is_file()]
    except OSError:
        return []
    active = [path for path in files if path.name == LOG_FILE_NAME]
    backups = [path for path in files if path.name != LOG_FILE_NAME]
    backups.sort(
        key=lambda path: int(path.name.rsplit(".", 1)[-1])
        if path.name.rsplit(".", 1)[-1].isdigit() else -1,
        reverse=True,
    )
    return backups + active


def export_diagnostics(
    output_path: str | os.PathLike[str] | None = None,
    app_data_dir: str | os.PathLike[str] | None = None,
    project_root: str | os.PathLike[str] | None = None,
) -> Path:
    """Create a plain-text report in the repository root or at an explicit path."""
    root_dir = Path(project_root) if project_root is not None else PROJECT_ROOT
    data_dir = Path(app_data_dir) if app_data_dir is not None else (
        _CONFIGURED_DATA_DIR or default_app_data_dir()
    )
    files = _ordered_log_files(data_dir / "logs")
    if output_path is None:
        destination = root_dir / "nekotrack_diagnostics.txt"
    else:
        destination = Path(output_path)
        if not destination.is_absolute():
            destination = root_dir / destination

    database = data_dir / "anime_tracker.db"
    try:
        database_exists = database.is_file()
        database_size = database.stat().st_size if database_exists else None
    except OSError:
        database_exists, database_size = False, None
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary = [
        "NEKOTRACK DIAGNOSTIC REPORT",
        f"Created: {now}",
        f"App version: {_source_version(root_dir) or 'unknown (frozen build or source not found)'}",
        f"Python: {sys.version.split()[0]}",
        f"OS: {platform.platform()}",
        f"Architecture: {struct.calcsize('P') * 8}-bit",
        f"PySide6 installed: {importlib.util.find_spec('PySide6') is not None}",
        f"Database file exists: {database_exists}",
        f"Database file size: {database_size if database_size is not None else 'unknown'} bytes",
        f"Log files included: {', '.join(path.name for path in files) if files else 'none'}",
        "",
        "Privacy: database contents, user notes, and cover images are not included.",
        "Credential-like values and common personal path fragments are redacted.",
        "Review this report before sharing it. Catalog titles and exception details may appear.",
        "",
        "=" * 78,
        "APPLICATION LOGS (oldest to newest)",
        "=" * 78,
        "",
    ]
    chunks = ["\n".join(summary)]
    if not files:
        chunks.append("No application log files were found. Launch NekoTrack once, then export again.\n")
    else:
        for path in files:
            try:
                contents = path.read_text(encoding="utf-8", errors="replace")
            except OSError as error:
                contents = f"<could not read log file: {type(error).__name__}>\n"
            contents = redact_text(contents, app_data_dir=data_dir, project_root=root_dir)
            chunks.append(f"\n--- {path.name} ---\n{contents}\n")

    report_text = "".join(chunks)
    if len(report_text.encode("utf-8", errors="replace")) > MAX_EXPORT_BYTES:
        encoded = report_text.encode("utf-8", errors="replace")
        suffix = encoded[-(MAX_EXPORT_BYTES - 100_000):].decode("utf-8", errors="replace")
        report_text = (
            "\n".join(summary)
            + "\n\n<older log content truncated by export size limit>\n"
            + suffix
        )
    report_text = redact_text(report_text, app_data_dir=data_dir, project_root=root_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(report_text)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export NekoTrack application logs into a shareable text file."
    )
    parser.add_argument(
        "--export-to-repo",
        action="store_true",
        help="Write nekotrack_diagnostics.txt in the repository root (default output).",
    )
    parser.add_argument(
        "--output",
        help="Optional output path; relative paths are resolved from the repository root.",
    )
    parser.add_argument(
        "--tail",
        type=int,
        metavar="LINES",
        help="Print the last N lines of the current application log instead of exporting.",
    )
    parser.add_argument(
        "--show-path",
        action="store_true",
        help="Print the current application log path.",
    )
    args = parser.parse_args(argv)

    if args.show_path:
        print(get_log_path())
        return 0
    if args.tail is not None:
        count = max(1, min(args.tail, 5000))
        files = _ordered_log_files(log_directory())
        if not files:
            print("No NekoTrack log exists yet. Launch the app first.")
            return 1
        try:
            lines = files[-1].read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as error:
            print(f"Could not read log: {type(error).__name__}")
            return 1
        print("\n".join(redact_text(line) for line in lines[-count:]))
        return 0
    if args.export_to_repo or args.output:
        # Export reads the app's existing log. Do not open a second rotating
        # handler here; that could conflict with the still-running desktop app.
        output = export_diagnostics(args.output)
        print(f"Exported diagnostics: {output}")
        print("Review the report before sharing it; it may contain catalog titles and exception details.")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
