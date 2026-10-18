import datetime
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from PySide6.QtCore import QThread, Signal


REPO_API_URL = "https://api.github.com/repos/konokuroineko/Nekotrack/releases"
REQUEST_TIMEOUT = 8
MAX_INSTALLER_BYTES = 512 * 1024 * 1024
MAX_INSTALLER_REDIRECTS = 5
RELEASE_OWNER = "konokuroineko"
RELEASE_REPO = "Nekotrack"


def _https_url_parts(value):
    """Parse an HTTPS URL while rejecting credentials and unusual ports."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        return None
    return parsed


def _is_setup_asset_name(value):
    if not isinstance(value, str):
        return False
    name = value.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    return "setup" in name and name.endswith(".exe")


def _is_supported_update_asset_name(value):
    if not isinstance(value, str):
        return False
    name = value.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    return _is_setup_asset_name(name) or name == "nekotrack.exe"


def _is_trusted_release_asset_url(value, expected_name=None):
    """Accept only installer assets published in this repository's releases."""
    parsed = _https_url_parts(value)
    if parsed is None or parsed.hostname.casefold() != "github.com" or parsed.fragment:
        return False

    parts = parsed.path.split("/")
    return (
        len(parts) == 7
        and parts[0] == ""
        and parts[1].casefold() == RELEASE_OWNER.casefold()
        and parts[2].casefold() == RELEASE_REPO.casefold()
        and parts[3:5] == ["releases", "download"]
        and bool(parts[5])
        and _is_supported_update_asset_name(parts[6])
        and (
            expected_name is None
            or (
                isinstance(expected_name, str)
                and expected_name.casefold() == parts[6].casefold()
                and _is_supported_update_asset_name(expected_name)
            )
        )
    )


def _is_trusted_release_page_url(value):
    """Accept only release pages on the official NekoTrack GitHub repository."""
    parsed = _https_url_parts(value)
    if parsed is None or parsed.hostname.casefold() != "github.com" or parsed.fragment:
        return False

    parts = parsed.path.split("/")
    return (
        len(parts) == 6
        and parts[0] == ""
        and parts[1].casefold() == RELEASE_OWNER.casefold()
        and parts[2].casefold() == RELEASE_REPO.casefold()
        and parts[3:5] == ["releases", "tag"]
        and bool(parts[5])
    )


def _is_trusted_download_location(value):
    """Validate the final URL after GitHub redirects a release asset download."""
    parsed = _https_url_parts(value)
    if parsed is None or parsed.fragment:
        return False
    host = parsed.hostname.casefold()
    if host == "github.com":
        return _is_trusted_release_asset_url(value)

    # Do not trust every githubusercontent.com subdomain: that includes places
    # where arbitrary user-controlled files can be hosted. These are the exact
    # documented/observed release-asset delivery hosts.
    return host in {
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
        "github-production-release-asset-2e65be.s3.amazonaws.com",
    }


def _open_trusted_download(start_url):
    """Follow only HTTPS redirects to GitHub's own release-asset infrastructure.

    Requests' automatic redirect handling contacts a redirect destination before
    the caller can inspect it. Disable that behavior so an unexpected redirect
    is rejected before any request is made to the destination.
    """
    url = start_url
    redirect_codes = {301, 302, 303, 307, 308}
    for _ in range(MAX_INSTALLER_REDIRECTS + 1):
        response = requests.get(
            url,
            headers={"Accept": "application/octet-stream"},
            stream=True,
            timeout=30,
            allow_redirects=False,
        )
        status_code = getattr(response, "status_code", None)
        if status_code in redirect_codes:
            headers = getattr(response, "headers", None) or {}
            location = headers.get("Location")
            response.close()
            if not isinstance(location, str) or not location.strip():
                raise ValueError("GitHub returned a redirect without a location.")
            destination = urljoin(url, location.strip())
            if not _is_trusted_download_location(destination):
                raise ValueError("GitHub redirected the installer download to an untrusted host.")
            url = destination
            continue

        try:
            response.raise_for_status()
            final_url = getattr(response, "url", None) or url
            if not _is_trusted_download_location(final_url):
                raise ValueError("The installer response came from an untrusted host.")
        except Exception:
            # The caller's context manager is entered only after this function
            # returns. Close streaming responses here whenever validation fails.
            response.close()
            raise
        return response

    raise ValueError("The installer download exceeded the redirect limit.")


def _is_windows_pe_installer(path):
    """Reject empty/error pages masquerading as .exe files before launching."""
    try:
        with Path(path).open("rb") as handle:
            dos_header = handle.read(64)
            if len(dos_header) < 64 or dos_header[:2] != b"MZ":
                return False
            pe_offset = int.from_bytes(dos_header[0x3C:0x40], "little")
            if pe_offset < 64 or pe_offset > MAX_INSTALLER_BYTES - 4:
                return False
            handle.seek(pe_offset)
            return handle.read(4) == b"PE\0\0"
    except (OSError, TypeError, ValueError, OverflowError):
        return False


_VERSION_PATTERN = re.compile(
    r"^(\d+)\.(\d+)\.(\d+)(?:-([a-zA-Z]+)(?:\.(\d+))?(?:-[A-Za-z0-9][A-Za-z0-9.-]*)?)?$"
)


def _version_match(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value[:1].casefold() == "v":
        value = value[1:]
    return _VERSION_PATTERN.fullmatch(value)


def _version_key(value):
    match = _version_match(value)
    if not match:
        return (0, 0, 0, -1, 0)

    try:
        major, minor, patch = (int(match.group(index)) for index in (1, 2, 3))
        stage_number = int(match.group(5) or 0)
    except (ValueError, OverflowError):
        # Extremely long digit strings can exceed Python's safe integer parser
        # limits. A malformed tag must not abort the rest of the update feed.
        return (0, 0, 0, -1, 0)

    stage = (match.group(4) or "stable").lower()
    stage_rank = {"dev": 0, "alpha": 1, "beta": 2, "rc": 3, "stable": 4}.get(stage, -1)
    return (major, minor, patch, stage_rank, stage_number)


def _display_release_version(value):
    """Normalize a release tag to the version portion understood by the updater."""
    match = _version_match(value)
    if not match:
        return None
    version = ".".join(match.group(index) for index in (1, 2, 3))
    stage = match.group(4)
    stage_number = match.group(5)
    if stage:
        version += f"-{stage.lower()}"
        if stage_number:
            version += f".{stage_number}"
    return version


def is_newer(remote_version, current_version):
    return _version_key(remote_version) > _version_key(current_version)


class UpdateInfo:
    def __init__(
        self, version, asset_url=None, asset_name=None, release_url=None,
        digest=None,
    ):
        self.version = version
        self.asset_url = asset_url
        self.asset_name = asset_name
        self.release_url = release_url
        self.digest = digest


class UpdateChecker(QThread):
    update_available = Signal(object)
    no_update_available = Signal()
    check_failed = Signal(str)

    def __init__(self, current_version, parent=None, include_prereleases=False, preferred_asset="setup"):
        super().__init__(parent)
        self.current_version = current_version
        self.include_prereleases = bool(include_prereleases)
        self.preferred_asset = "portable" if str(preferred_asset).casefold() == "portable" else "setup"

    def run(self):
        try:
            response = requests.get(
                REPO_API_URL,
                params={"per_page": 10},
                headers={"Accept": "application/vnd.github+json"},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            releases = response.json()
            if not isinstance(releases, list):
                raise ValueError("GitHub returned an unexpected release-list response.")

            candidates = []
            for release in releases:
                if not isinstance(release, dict) or release.get("draft") is True:
                    continue
                if release.get("prerelease") is True and not self.include_prereleases:
                    continue

                tag = release.get("tag_name")
                version = _display_release_version(tag)
                if not version or not is_newer(tag, self.current_version):
                    continue

                release_url = release.get("html_url")
                if not _is_trusted_release_page_url(release_url):
                    continue

                assets = release.get("assets")
                supported_assets = []
                if isinstance(assets, list):
                    for asset in assets:
                        if not isinstance(asset, dict):
                            continue
                        name = asset.get("name")
                        url = asset.get("browser_download_url")
                        if not isinstance(name, str) or not isinstance(url, str) or not url.strip():
                            continue
                        if not _is_supported_update_asset_name(name):
                            continue
                        if not _is_trusted_release_asset_url(url, expected_name=name):
                            continue

                        # An installed Setup build prefers Setup; a portable
                        # or isolated preview install prefers the portable EXE
                        # so an update never targets a different install folder.
                        is_portable_exe = name.casefold() == "nekotrack.exe"
                        priority = (
                            0 if is_portable_exe else 1
                        ) if self.preferred_asset == "portable" else (
                            0 if _is_setup_asset_name(name) else 1
                        )
                        digest = asset.get("digest")
                        if not isinstance(digest, str) or not re.fullmatch(
                            r"sha256:[0-9a-fA-F]{64}", digest
                        ):
                            digest = None
                        supported_assets.append((priority, name, url, digest))

                supported_assets.sort(key=lambda item: item[0])
                selected = supported_assets[0] if supported_assets else None
                candidates.append((
                    _version_key(tag),
                    UpdateInfo(
                        version,
                        selected[2] if selected else None,
                        selected[1] if selected else None,
                        release_url,
                        selected[3] if selected else None,
                    ),
                ))

            if candidates:
                candidates.sort(key=lambda candidate: candidate[0], reverse=True)
                self.update_available.emit(candidates[0][1])
            else:
                self.no_update_available.emit()

        except Exception as exc:
            self.check_failed.emit(str(exc))


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_previous_update_backup(data_directory):
    """Find the newest complete backup, ignoring incomplete/corrupt folders."""
    root = Path(data_directory) / "update_backups"
    if not root.is_dir():
        return None
    candidates = []
    for folder in root.iterdir():
        if not folder.is_dir():
            continue
        try:
            manifest = json.loads(
                (folder / "manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError, TypeError):
            continue
        if not _is_windows_pe_installer(folder / "NekoTrack.exe"):
            continue
        candidates.append((str(manifest.get("created_at") or folder.name), folder))
    return max(candidates, key=lambda pair: pair[0])[1].resolve() if candidates else None


def create_update_backup(
    current_executable, data_directory, database_path, current_version, target_version
):
    """Back up the current exe and a consistent SQLite snapshot before replacement."""
    executable = Path(current_executable).resolve()
    data_dir = Path(data_directory).resolve()
    if not executable.is_file() or not _is_windows_pe_installer(executable):
        raise ValueError("A valid installed NekoTrack executable could not be found.")
    data_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.datetime.now(datetime.timezone.utc)
    created_at = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    folder_name = now.strftime("%Y%m%dT%H%M%S%fZ")
    backup_directory = (
        data_dir / "update_backups" / f"{folder_name}-{uuid.uuid4().hex[:8]}"
    )
    backup_directory.mkdir(parents=True, exist_ok=False)
    try:
        backup_executable = backup_directory / "NekoTrack.exe"
        shutil.copy2(executable, backup_executable)
        executable_digest = _sha256_file(executable)
        if _sha256_file(backup_executable) != executable_digest:
            raise OSError("The previous NekoTrack executable backup failed verification.")

        source_database = Path(database_path)
        database_backed_up = False
        if source_database.is_file():
            # SQLite backup() includes committed WAL data unlike copying the
            # main database file directly while the application is open.
            source_connection = sqlite3.connect(str(source_database), timeout=15)
            destination_connection = None
            try:
                destination_connection = sqlite3.connect(
                    str(backup_directory / "anime_tracker.db")
                )
                source_connection.backup(destination_connection)
                destination_connection.commit()
            finally:
                source_connection.close()
                if destination_connection is not None:
                    destination_connection.close()
            if not (backup_directory / "anime_tracker.db").is_file():
                raise OSError("The database backup was not created.")
            database_backed_up = True

        manifest = {
            "created_at": created_at,
            "from_version": str(current_version),
            "to_version": str(target_version),
            "executable_sha256": executable_digest,
            "database_backed_up": database_backed_up,
            "database_file": "anime_tracker.db" if database_backed_up else None,
        }
        (backup_directory / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return backup_directory
    except Exception:
        # Delete only this invocation's incomplete backup; never touch user data.
        shutil.rmtree(backup_directory, ignore_errors=True)
        raise


def persist_update_helper(helper_script, data_directory):
    """Copy the helper to durable app data before a one-file app exits."""
    source = Path(helper_script)
    if not source.is_file():
        raise ValueError("The safe update helper is missing from this NekoTrack build.")
    data_root = Path(data_directory).resolve()
    helper_directory = data_root / "update_helpers"
    helper_directory.mkdir(parents=True, exist_ok=True)
    expected_digest = _sha256_file(source)
    persistent = helper_directory / f"safe_update_{expected_digest[:16]}.ps1"
    if persistent.is_file() and _sha256_file(persistent) == expected_digest:
        return persistent
    temporary = helper_directory / (persistent.name + ".tmp")
    shutil.copy2(source, temporary)
    if _sha256_file(temporary) != expected_digest:
        temporary.unlink(missing_ok=True)
        raise OSError("The recovery helper failed its copy-integrity check.")
    temporary.replace(persistent)
    return persistent


def launch_update_helper(
    helper_script, action, install_directory, data_directory, backup_directory,
    wait_for_pid, expected_version=None, staged_executable=None, installer_path=None,
    attempt_id=None, restore_database=False,
):
    """Use a separate PowerShell process; Windows cannot replace its running exe."""
    if os.name != "nt":
        raise ValueError("In-place updating is available only on Windows.")
    persistent_helper = persist_update_helper(helper_script, data_directory)

    command = [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-WindowStyle", "Hidden", "-File", str(persistent_helper),
        "-Action", str(action),
        "-InstallDirectory", str(Path(install_directory).resolve()),
        "-DataDirectory", str(Path(data_directory).resolve()),
        "-BackupDirectory", str(Path(backup_directory).resolve()) if backup_directory else "",
        "-WaitForPid", str(int(wait_for_pid or 0)),
    ]
    if expected_version:
        command.extend(["-ExpectedVersion", str(expected_version)])
    if staged_executable:
        command.extend(["-StagedExecutable", str(Path(staged_executable).resolve())])
    if installer_path:
        command.extend(["-InstallerPath", str(Path(installer_path).resolve())])
    if attempt_id:
        command.extend(["-AttemptId", str(attempt_id)])
    if restore_database:
        command.append("-RestoreDatabase")

    return subprocess.Popen(
        command,
        cwd=str(Path(install_directory).resolve()),
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


class InstallerDownloader(QThread):
    """Download and validate an update, then stage it for a rollback-aware helper."""

    download_staged = Signal(str)
    failed = Signal(str)

    def __init__(
        self, asset_url, asset_name, parent=None, *, digest=None,
        current_version=None, target_version=None, data_directory=None,
        database_path=None, install_directory=None, current_executable=None,
        helper_script=None, process_id=None,
    ):
        super().__init__(parent)
        self.asset_url = asset_url
        self.asset_name = asset_name
        self.digest = digest
        self.current_version = str(current_version or "unknown")
        self.target_version = str(target_version or "unknown")
        self.data_directory = Path(data_directory) if data_directory else None
        self.database_path = Path(database_path) if database_path else None
        self.install_directory = Path(install_directory) if install_directory else None
        self.current_executable = Path(current_executable) if current_executable else None
        self.helper_script = Path(helper_script) if helper_script else None
        self.process_id = int(process_id or os.getpid())
        self._cancel_event = threading.Event()

    def cancel(self):
        """Ask the worker to stop before modifying any installed files."""
        self._cancel_event.set()
        self.requestInterruption()

    def _raise_if_cancelled(self):
        if self._cancel_event.is_set() or self.isInterruptionRequested():
            raise RuntimeError("The update was cancelled. The installed application was not changed.")

    def run(self):
        temp_path = None
        try:
            self._raise_if_cancelled()
            if not _is_trusted_release_asset_url(
                self.asset_url, expected_name=self.asset_name
            ):
                raise ValueError("The update URL is not a trusted NekoTrack GitHub release asset.")
            if not _is_supported_update_asset_name(self.asset_name):
                raise ValueError("The update asset is not a supported NekoTrack Windows build.")

            byte_count = 0
            with _open_trusted_download(self.asset_url) as response:
                headers = getattr(response, "headers", None) or {}
                raw_length = headers.get("Content-Length")
                if raw_length not in (None, ""):
                    try:
                        declared_length = int(raw_length)
                    except (TypeError, ValueError, OverflowError):
                        raise ValueError("The update server returned an invalid content length.")
                    if declared_length < 0:
                        raise ValueError("The update server returned an invalid content length.")
                    if declared_length > MAX_INSTALLER_BYTES:
                        raise ValueError("The update is larger than the allowed 512 MiB limit.")

                with tempfile.NamedTemporaryFile(
                    prefix="NekoTrack-update-",
                    suffix=".exe",
                    dir=tempfile.gettempdir(),
                    delete=False,
                ) as handle:
                    temp_path = Path(handle.name)
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        self._raise_if_cancelled()
                        if not chunk:
                            continue
                        byte_count += len(chunk)
                        if byte_count > MAX_INSTALLER_BYTES:
                            raise ValueError("The update exceeded the allowed 512 MiB download limit.")
                        handle.write(chunk)

            self._raise_if_cancelled()
            if byte_count == 0:
                raise ValueError("The update download was empty.")
            if not _is_windows_pe_installer(temp_path):
                raise ValueError("The downloaded file does not have a valid Windows executable header.")

            if self.digest:
                algorithm, separator, expected = self.digest.partition(":")
                if separator != ":" or algorithm.casefold() != "sha256" or not re.fullmatch(
                    r"[0-9a-fA-F]{64}", expected
                ):
                    raise ValueError("The release contains an invalid SHA-256 digest.")
                if _sha256_file(temp_path).casefold() != expected.casefold():
                    raise ValueError("The downloaded update failed its SHA-256 integrity check.")

            # Legacy test/developer callers can still validate the downloader in
            # isolation. The app itself always supplies every safe-update path.
            configured = all((
                self.data_directory is not None,
                self.install_directory is not None,
                self.current_executable is not None,
                self.helper_script is not None,
            ))
            if not configured:
                if _is_setup_asset_name(self.asset_name):
                    subprocess.Popen([str(temp_path)], close_fds=True)
                    self.download_staged.emit(str(temp_path))
                    # A started installer can still be reading this file.
                    # The standalone caller owns this legacy download artifact.
                    temp_path = None
                    return
                raise ValueError("Safe updating requires an installed NekoTrack build and recovery helper.")

            if self.current_executable.resolve().parent != self.install_directory.resolve():
                raise ValueError("The installed executable path does not match its installation directory.")

            backup_directory = create_update_backup(
                self.current_executable,
                self.data_directory,
                self.database_path or (self.data_directory / "anime_tracker.db"),
                self.current_version,
                self.target_version,
            )
            attempt_id = uuid.uuid4().hex
            staging_directory = self.data_directory / "update_staging" / attempt_id
            staging_directory.mkdir(parents=True, exist_ok=False)
            staged_path = staging_directory / self.asset_name
            shutil.copy2(temp_path, staged_path)
            if _sha256_file(staged_path) != _sha256_file(temp_path):
                raise OSError("The staged update failed its integrity check.")

            action = "InstallSetup" if _is_setup_asset_name(self.asset_name) else "UpdatePortable"
            launch_update_helper(
                self.helper_script,
                action,
                self.install_directory,
                self.data_directory,
                backup_directory,
                self.process_id,
                expected_version=self.target_version,
                staged_executable=staged_path if action == "UpdatePortable" else None,
                installer_path=staged_path if action == "InstallSetup" else None,
                attempt_id=attempt_id,
                restore_database=True,
            )
            self.download_staged.emit(str(backup_directory))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
