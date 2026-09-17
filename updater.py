import re
import subprocess
import tempfile
from pathlib import Path

import requests

try:
    from PySide6.QtCore import QThread, Signal
except ImportError:  # keep version logic importable without PySide6 (tests/tooling)
    QThread = object

    class Signal:
        """No-op stand-in for class-body signal declarations.

        The threaded updater classes are only instantiated by the desktop app,
        which always ships PySide6 (see requirements.txt).
        """

        def __init__(self, *args, **kwargs):
            pass


REPO_API_URL = "https://api.github.com/repos/konokuroineko/Nekotrack/releases"
REQUEST_TIMEOUT = 8


def _version_key(value):
    value = value.strip().lstrip("v")
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:-([a-zA-Z]+)(?:\.(\d+))?)?$", value)
    if not match:
        return (0, 0, 0, -1, 0)

    stage = (match.group(4) or "stable").lower()
    stage_rank = {"dev": 0, "alpha": 1, "beta": 2, "rc": 3, "stable": 4}.get(stage, -1)
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        stage_rank,
        int(match.group(5) or 0),
    )


def is_newer(remote_version, current_version):
    return _version_key(remote_version) > _version_key(current_version)


class UpdateInfo:
    def __init__(self, version, asset_url, asset_name):
        self.version = version
        self.asset_url = asset_url
        self.asset_name = asset_name


class UpdateChecker(QThread):
    update_available = Signal(object)
    check_failed = Signal(str)

    def __init__(self, current_version, parent=None):
        super().__init__(parent)
        self.current_version = current_version

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

            for release in releases:
                if release.get("draft"):
                    continue
                tag = release.get("tag_name") or ""
                version = tag.lstrip("v")
                if not version or not is_newer(version, self.current_version):
                    continue

                assets = release.get("assets") or []
                installer = next(
                    (
                        asset for asset in assets
                        if str(asset.get("name", "")).lower().endswith(".exe")
                        and "setup" in str(asset.get("name", "")).lower()
                    ),
                    None,
                )
                if installer:
                    self.update_available.emit(
                        UpdateInfo(version, installer.get("browser_download_url"), installer.get("name"))
                    )
                    return

        except Exception as exc:
            self.check_failed.emit(str(exc))


class InstallerDownloader(QThread):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, asset_url, asset_name, parent=None):
        super().__init__(parent)
        self.asset_url = asset_url
        self.asset_name = asset_name

    def run(self):
        try:
            if not self.asset_url:
                raise ValueError("The update does not contain an installer download URL.")

            suffix = Path(self.asset_name or "NekoTrack-Setup.exe").suffix or ".exe"
            temp_path = Path(tempfile.gettempdir()) / f"NekoTrack-update{suffix}"

            with requests.get(
                self.asset_url,
                headers={"Accept": "application/octet-stream"},
                stream=True,
                timeout=30,
            ) as response:
                response.raise_for_status()
                with temp_path.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            handle.write(chunk)

            subprocess.Popen([str(temp_path)], close_fds=True)
            self.finished.emit(str(temp_path))
        except Exception as exc:
            self.failed.emit(str(exc))
