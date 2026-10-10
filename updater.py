import re
import subprocess
import tempfile
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


def _is_trusted_release_asset_url(value):
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
        and _is_setup_asset_name(parts[6])
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

        response.raise_for_status()
        final_url = getattr(response, "url", None) or url
        if not _is_trusted_download_location(final_url):
            response.close()
            raise ValueError("The installer response came from an untrusted host.")
        return response

    raise ValueError("The installer download exceeded the redirect limit.")


def _version_key(value):
    if not isinstance(value, str):
        return (0, 0, 0, -1, 0)
    value = value.strip().lstrip("v")
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:-([a-zA-Z]+)(?:\.(\d+))?)?$", value)
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
                    if not isinstance(name, str) or not isinstance(url, str) or not url.strip():
                        continue
                    if _is_setup_asset_name(name) and _is_trusted_release_asset_url(url):
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
            # Defense in depth: do not let callers bypass the release-feed URL
            # validation and execute a program downloaded from an arbitrary host.
            if not _is_trusted_release_asset_url(self.asset_url):
                raise ValueError("The installer URL is not a trusted NekoTrack GitHub release asset.")
            if not _is_setup_asset_name(self.asset_name):
                raise ValueError("The update asset is not a NekoTrack Setup executable.")

            byte_count = 0
            with _open_trusted_download(self.asset_url) as response:

                headers = getattr(response, "headers", None) or {}
                raw_length = headers.get("Content-Length")
                if raw_length not in (None, ""):
                    try:
                        declared_length = int(raw_length)
                    except (TypeError, ValueError, OverflowError):
                        raise ValueError("The installer server returned an invalid content length.")
                    if declared_length < 0:
                        raise ValueError("The installer server returned an invalid content length.")
                    if declared_length > MAX_INSTALLER_BYTES:
                        raise ValueError("The installer is larger than the allowed 512 MiB limit.")

                with tempfile.NamedTemporaryFile(
                    prefix="NekoTrack-update-",
                    suffix=".exe",
                    dir=tempfile.gettempdir(),
                    delete=False,
                ) as handle:
                    temp_path = Path(handle.name)
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        if not chunk:
                            continue
                        byte_count += len(chunk)
                        if byte_count > MAX_INSTALLER_BYTES:
                            raise ValueError("The installer exceeded the allowed 512 MiB download limit.")
                        handle.write(chunk)

            if byte_count == 0:
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
