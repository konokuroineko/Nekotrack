"""Security and resilience tests for the self-updater.

All network responses and process launches are mocked. These tests must never
download or execute a real installer.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import updater


VALID_URL = (
    "https://github.com/konokuroineko/Nekotrack/releases/download/"
    "v2.0.0/NekoTrack-Setup.exe"
)
VALID_CDN_URL = "https://release-assets.githubusercontent.com/assets/123/installer.exe"


def minimal_pe_payload(body=b"installer test payload"):
    """Return a tiny PE-shaped fixture; tests never execute this payload."""
    dos_header = bytearray(64)
    dos_header[:2] = b"MZ"
    pe_offset = 0x80
    dos_header[0x3C:0x40] = pe_offset.to_bytes(4, "little")
    return bytes(dos_header) + bytes(pe_offset - len(dos_header)) + b"PE\0\0" + body


class UpdateUrlValidationTests(unittest.TestCase):
    def test_release_assets_are_limited_to_this_repository_setup_executables(self):
        self.assertTrue(updater._is_trusted_release_asset_url(VALID_URL))
        self.assertTrue(
            updater._is_trusted_release_asset_url(
                "https://GITHUB.com/KonokuroiNeko/NekoTrack/releases/download/v2.0.0/NekoTrack-Setup-2.0.exe"
            )
        )

        rejected = [
            None,
            "",
            "http://github.com/konokuroineko/Nekotrack/releases/download/v2.0.0/NekoTrack-Setup.exe",
            "https://example.invalid/setup.exe",
            "https://github.com.evil.invalid/konokuroineko/Nekotrack/releases/download/v2.0.0/NekoTrack-Setup.exe",
            "https://github.com/attacker/Nekotrack/releases/download/v2.0.0/NekoTrack-Setup.exe",
            "https://github.com/konokuroineko/OtherProject/releases/download/v2.0.0/NekoTrack-Setup.exe",
            "https://user@github.com/konokuroineko/Nekotrack/releases/download/v2.0.0/NekoTrack-Setup.exe",
            "https://github.com:444/konokuroineko/Nekotrack/releases/download/v2.0.0/NekoTrack-Setup.exe",
            "https://github.com/konokuroineko/Nekotrack/releases/latest/download/NekoTrack-Setup.exe",
            "https://github.com/konokuroineko/Nekotrack/releases/download/v2.0.0/payload.exe",
            VALID_URL + "#untrusted-fragment",
            "https://github.com/konokuroineko/Nekotrack/releases/download/v2.0.0/NekoTrack-Setup.exe\\n@evil",
        ]
        for url in rejected:
            with self.subTest(url=repr(url)):
                self.assertFalse(updater._is_trusted_release_asset_url(url))

    def test_redirect_destination_must_remain_on_github_asset_hosts(self):
        self.assertTrue(updater._is_trusted_download_location(VALID_URL))
        self.assertTrue(updater._is_trusted_download_location(VALID_CDN_URL))
        self.assertTrue(
            updater._is_trusted_download_location(
                "https://objects.githubusercontent.com/assets/installer.exe"
            )
        )
        for url in (
            "http://release-assets.githubusercontent.com/assets/installer.exe",
            "https://githubusercontent.com.evil.invalid/assets/installer.exe",
            "https://raw.githubusercontent.com/attacker/repo/main/payload.exe",
            "https://user-images.githubusercontent.com/123/installer.exe",
            "https://attacker.invalid/NekoTrack-Setup.exe",
            "https://github.com/attacker/repo/releases/download/v2/NekoTrack-Setup.exe",
            "https://user@release-assets.githubusercontent.com/assets/installer.exe",
        ):
            with self.subTest(url=url):
                self.assertFalse(updater._is_trusted_download_location(url))

    def test_version_parser_tolerates_malformed_and_extreme_values(self):
        malformed = [
            None,
            True,
            2,
            1.5,
            [],
            {},
            object(),
            "",
            "latest",
            "1.2",
            "1.2.3-",
            ("9" * 5000) + ".0.0",
            "1.2.3-beta." + ("9" * 5000),
        ]
        for value in malformed:
            with self.subTest(value_type=type(value).__name__):
                key = updater._version_key(value)
                self.assertIsInstance(key, tuple)
                self.assertEqual(len(key), 5)
                self.assertFalse(updater.is_newer(value, "0.1.0"))

        self.assertTrue(updater.is_newer("v2.0.0-beta.10", "2.0.0-beta.9"))
        self.assertTrue(updater.is_newer("2.0.0", "2.0.0-rc.3"))
        self.assertFalse(updater.is_newer("2.0.0-beta.1", "2.0.0"))


class InstallerDownloaderSafetyTests(unittest.TestCase):
    def run_downloader(self, url=VALID_URL, name="NekoTrack-Setup.exe"):
        downloader = updater.InstallerDownloader(url, name)
        failures = []
        downloader.failed.connect(failures.append)
        with patch.object(updater.requests, "get") as request, patch.object(
            updater.subprocess, "Popen"
        ) as popen:
            downloader.run()
        return failures, request, popen

    def test_rejects_untrusted_urls_and_non_installer_names_before_network_access(self):
        cases = [
            ("https://example.invalid/NekoTrack-Setup.exe", "NekoTrack-Setup.exe"),
            ("http://github.com/konokuroineko/Nekotrack/releases/download/v2/NekoTrack-Setup.exe", "NekoTrack-Setup.exe"),
            ("https://github.com/attacker/Nekotrack/releases/download/v2/NekoTrack-Setup.exe", "NekoTrack-Setup.exe"),
            (VALID_URL, "payload.exe"),
            (VALID_URL, "NekoTrack-Setup.cmd"),
            (VALID_URL, None),
        ]
        for url, name in cases:
            with self.subTest(url=url, name=repr(name)):
                failures, request, popen = self.run_downloader(url, name)
                self.assertEqual(len(failures), 1)
                request.assert_not_called()
                popen.assert_not_called()

    def test_rejects_a_redirect_to_an_untrusted_host_before_reading_body(self):
        with tempfile.TemporaryDirectory() as directory:
            response = MagicMock()
            response.__enter__.return_value = response
            response.__exit__.return_value = False
            response.url = "https://attacker.invalid/payload.exe"
            response.headers = {}
            response.iter_content.return_value = [b"fake executable"]
            failures = []
            downloader = updater.InstallerDownloader(VALID_URL, "NekoTrack-Setup.exe")
            downloader.failed.connect(failures.append)

            with patch.object(updater.tempfile, "gettempdir", return_value=directory), patch.object(
                updater.requests, "get", return_value=response
            ), patch.object(updater.subprocess, "Popen") as popen:
                downloader.run()

            self.assertEqual(len(failures), 1)
            self.assertIn("untrusted host", failures[0])
            response.iter_content.assert_not_called()
            popen.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_untrusted_redirect_is_rejected_before_the_destination_is_contacted(self):
        with tempfile.TemporaryDirectory() as directory:
            redirect = Mock()
            redirect.status_code = 302
            redirect.headers = {"Location": "https://attacker.invalid/payload.exe"}
            redirect.close.return_value = None
            failures = []
            downloader = updater.InstallerDownloader(VALID_URL, "NekoTrack-Setup.exe")
            downloader.failed.connect(failures.append)

            with patch.object(updater.tempfile, "gettempdir", return_value=directory), patch.object(
                updater.requests, "get", return_value=redirect
            ) as request, patch.object(updater.subprocess, "Popen") as popen:
                downloader.run()

            self.assertEqual(len(failures), 1)
            self.assertIn("untrusted host", failures[0])
            request.assert_called_once_with(
                VALID_URL,
                headers={"Accept": "application/octet-stream"},
                stream=True,
                timeout=30,
                allow_redirects=False,
            )
            redirect.close.assert_called_once()
            popen.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_http_error_response_is_closed_before_download_raises(self):
        response = Mock()
        response.status_code = 503
        response.url = VALID_CDN_URL
        response.raise_for_status.side_effect = requests_error = updater.requests.HTTPError(
            "temporary upstream failure"
        )
        response.close.return_value = None

        with patch.object(updater.requests, "get", return_value=response):
            with self.assertRaises(updater.requests.HTTPError) as raised:
                updater._open_trusted_download(VALID_URL)

        self.assertIs(raised.exception, requests_error)
        response.close.assert_called_once()

    def test_github_release_redirect_to_trusted_cdn_is_followed_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            redirect = Mock()
            redirect.status_code = 302
            redirect.headers = {"Location": VALID_CDN_URL}
            redirect.close.return_value = None

            response = MagicMock()
            response.status_code = 200
            response.__enter__.return_value = response
            response.__exit__.return_value = False
            response.url = VALID_CDN_URL
            payload = minimal_pe_payload(b"safe")
            response.headers = {"Content-Length": str(len(payload))}
            response.iter_content.return_value = [payload]

            finished = []
            failures = []
            downloader = updater.InstallerDownloader(VALID_URL, "NekoTrack-Setup.exe")
            downloader.finished.connect(finished.append)
            downloader.failed.connect(failures.append)

            with patch.object(updater.tempfile, "gettempdir", return_value=directory), patch.object(
                updater.requests, "get", side_effect=[redirect, response]
            ) as request, patch.object(updater.subprocess, "Popen") as popen:
                downloader.run()

            self.assertEqual(failures, [])
            self.assertEqual(len(finished), 1)
            self.assertEqual(request.call_count, 2)
            self.assertEqual(request.call_args_list[0].kwargs["allow_redirects"], False)
            self.assertEqual(request.call_args_list[1].args[0], VALID_CDN_URL)
            self.assertEqual(request.call_args_list[1].kwargs["allow_redirects"], False)
            installer_path = Path(finished[0])
            self.assertEqual(installer_path.read_bytes(), payload)
            popen.assert_called_once_with([str(installer_path)], close_fds=True)

    def test_valid_download_is_bounded_written_to_a_unique_exe_and_launched(self):
        with tempfile.TemporaryDirectory() as directory:
            response = MagicMock()
            response.__enter__.return_value = response
            response.__exit__.return_value = False
            response.url = VALID_CDN_URL
            payload = minimal_pe_payload(b"nekotrack")
            response.headers = {"Content-Length": str(len(payload))}
            response.iter_content.return_value = [payload[:3], payload[3:]]
            finished = []
            failures = []
            downloader = updater.InstallerDownloader(VALID_URL, "NekoTrack-Setup.exe")
            downloader.finished.connect(finished.append)
            downloader.failed.connect(failures.append)

            with patch.object(updater.tempfile, "gettempdir", return_value=directory), patch.object(
                updater.requests, "get", return_value=response
            ) as request, patch.object(updater.subprocess, "Popen") as popen:
                downloader.run()

            request.assert_called_once_with(
                VALID_URL,
                headers={"Accept": "application/octet-stream"},
                stream=True,
                timeout=30,
                allow_redirects=False,
            )
            self.assertEqual(failures, [])
            self.assertEqual(len(finished), 1)
            installer_path = Path(finished[0])
            self.assertTrue(installer_path.exists())
            self.assertEqual(installer_path.suffix, ".exe")
            self.assertEqual(installer_path.read_bytes(), payload)
            popen.assert_called_once_with([str(installer_path)], close_fds=True)

    def test_declared_oversize_installer_is_rejected_before_creating_file(self):
        with tempfile.TemporaryDirectory() as directory:
            response = MagicMock()
            response.__enter__.return_value = response
            response.__exit__.return_value = False
            response.url = VALID_CDN_URL
            response.headers = {"Content-Length": str(1024)}
            response.iter_content.return_value = [b"must not be read"]
            failures = []
            downloader = updater.InstallerDownloader(VALID_URL, "NekoTrack-Setup.exe")
            downloader.failed.connect(failures.append)

            with patch.object(updater, "MAX_INSTALLER_BYTES", 16), patch.object(
                updater.tempfile, "gettempdir", return_value=directory
            ), patch.object(updater.requests, "get", return_value=response), patch.object(
                updater.subprocess, "Popen"
            ) as popen:
                downloader.run()

            self.assertEqual(len(failures), 1)
            self.assertIn("512 MiB", failures[0])
            response.iter_content.assert_not_called()
            popen.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_streamed_oversize_download_is_removed_and_never_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            response = MagicMock()
            response.__enter__.return_value = response
            response.__exit__.return_value = False
            response.url = VALID_CDN_URL
            response.headers = {}
            response.iter_content.return_value = [b"1234", b"5"]
            failures = []
            downloader = updater.InstallerDownloader(VALID_URL, "NekoTrack-Setup.exe")
            downloader.failed.connect(failures.append)

            with patch.object(updater, "MAX_INSTALLER_BYTES", 4), patch.object(
                updater.tempfile, "gettempdir", return_value=directory
            ), patch.object(updater.requests, "get", return_value=response), patch.object(
                updater.subprocess, "Popen"
            ) as popen:
                downloader.run()

            self.assertEqual(len(failures), 1)
            self.assertIn("exceeded", failures[0])
            popen.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_html_error_page_is_removed_and_never_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            html = b"<!doctype html><html><body>temporary error</body></html>"
            response = MagicMock()
            response.__enter__.return_value = response
            response.__exit__.return_value = False
            response.status_code = 200
            response.url = VALID_CDN_URL
            response.headers = {"Content-Length": str(len(html))}
            response.iter_content.return_value = [html]
            failures = []
            downloader = updater.InstallerDownloader(VALID_URL, "NekoTrack-Setup.exe")
            downloader.failed.connect(failures.append)

            with patch.object(updater.tempfile, "gettempdir", return_value=directory), patch.object(
                updater.requests, "get", return_value=response
            ), patch.object(updater.subprocess, "Popen") as popen:
                downloader.run()

            self.assertEqual(len(failures), 1)
            self.assertIn("valid Windows executable header", failures[0])
            popen.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_empty_installer_is_removed_and_never_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            response = MagicMock()
            response.__enter__.return_value = response
            response.__exit__.return_value = False
            response.url = VALID_CDN_URL
            response.headers = {"Content-Length": "0"}
            response.iter_content.return_value = [b"", None]
            failures = []
            downloader = updater.InstallerDownloader(VALID_URL, "NekoTrack-Setup.exe")
            downloader.failed.connect(failures.append)

            with patch.object(updater.tempfile, "gettempdir", return_value=directory), patch.object(
                updater.requests, "get", return_value=response
            ), patch.object(updater.subprocess, "Popen") as popen:
                downloader.run()

            self.assertEqual(len(failures), 1)
            self.assertIn("empty", failures[0])
            popen.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
