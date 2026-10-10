import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from PySide6.QtCore import QThread, Signal


REPO_API_URL = "https://api.github.com/repos/konokuroineko/Nekotrack/releases"
REQUEST_TIMEOUT = 8
MAX_INSTALLER_BYTES = 512 * 1024 * 1024
RELEASE_ASSET_PREFIX = "/konokuroineko/Nekotrack/releases/download/"


def _is_trusted_release_asset_url(value):
    """Accept only HTTPS installer assets published in this repository's releases."""
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlparse(value.strip())
        if (
            parsed.scheme.lower() != "https"
            or parsed.hostname is None
            or parsed.hostname.lower() != "github.com"
            or parsed.port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
        ):
            return False
        path = unquote(parsed.path)
        if not path.startswith(RELEASE_ASSET_PREFIX):
            return False
        parts = path.split("/")
        # /owner/repo/releases/download/<tag>/<asset name...>
        return (
            len(parts) >= 7
            and all(part and part not in {".", ".."} for part in parts[1:])
            and parts[1] == "konokuroineko"
            and parts[2] == "Nekotrack"
            and parts[3:5] == ["releases", "download"]
        )
    except (TypeError, ValueError):
        return False


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
            if not isinstance(releases, list):
                raise ValueError("GitHub returned an unexpected release-list response.")

            for release in releases:
                # A single malformed release or asset should not hide later
                # valid releases from the update feed.
                if not isinstance(release, dict):
                    continue
                if release.get("draft") is True:
                    continue

                tag = release.get("tag_name")
                if not isinstance(tag, str):
                    continue
                version = tag.strip().lstrip("v")
                if not version or not is_newer(version, self.current_version):
                    continue

                assets = release.get("assets")
                if not isinstance(assets, list):
                    continue
                installer = None
                for asset in assets:
                    if not isinstance(asset, dict):
                        continue
                    name = asset.get("name")
                    url = asset.get("browser_download_url")
                    if (
                        not isinstance(name, str)
                        or not isinstance(url, str)
                        or not url.strip()
                        or not _is_trusted_release_asset_url(url)
                    ):
                        continue
                    lowered_name = name.casefold()
                    if lowered_name.endswith(".exe") and "setup" in lowered_name:
                        installer = asset
                        break

                if installer:
                    self.update_available.emit(
                        UpdateInfo(
                            version,
                            installer["browser_download_url"],
                            installer["name"],
                        )
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
        temp_path = None
        try:
            if not self.asset_url:
                raise ValueError("The update does not contain an installer download URL.")
            if not _is_trusted_release_asset_url(self.asset_url):
                raise ValueError("The installer URL is not a trusted NekoTrack GitHub release asset.")

            suffix = Path(self.asset_name or "").suffix
            if suffix.lower() != ".exe":
                raise ValueError("The update asset must be a Windows .exe installer.")

            with requests.get(
                self.asset_url,
                headers={"Accept": "application/octet-stream"},
                stream=True,
                timeout=30,
            ) as response:
                response.raise_for_status()
                content_length = response.headers.get("Content-Length")
                try:
                    declared_size = int(content_length) if content_length is not None else None
                except (TypeError, ValueError, OverflowError):
                    declared_size = None
                if declared_size is not None and declared_size > MAX_INSTALLER_BYTES:
                    raise ValueError(
                        f"The installer exceeds the {MAX_INSTALLER_BYTES // (1024 * 1024)} MiB download limit."
                    )

                # Use an unpredictable, exclusively created file: a fixed name in
                # the temp directory can collide with another process or follow a symlink.
                with tempfile.NamedTemporaryFile(
                    prefix="NekoTrack-update-",
                    suffix=".exe",
                    dir=tempfile.gettempdir(),
                    delete=False,
                ) as handle:
                    temp_path = Path(handle.name)
                    total_bytes = 0
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        if not chunk:
                            continue
                        total_bytes += len(chunk)
                        if total_bytes > MAX_INSTALLER_BYTES:
                            raise ValueError(
                                f"The installer exceeds the {MAX_INSTALLER_BYTES // (1024 * 1024)} MiB download limit."
                            )
                        handle.write(chunk)

            if temp_path is None or total_bytes == 0:
                raise ValueError("The installer download was empty.")
            subprocess.Popen([str(temp_path)], close_fds=True)
            self.finished.emit(str(temp_path))
        except Exception as exc:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            self.failed.emit(str(exc))