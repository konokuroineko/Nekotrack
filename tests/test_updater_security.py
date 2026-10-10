"""Security and failure-path tests for NekoTrack's auto-updater."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import updater


def _response(chunks, headers=None):
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.raise_for_status.return_value = None
    response.headers = headers or {}
    response.iter_content.return_value = iter(chunks)
    return response


class UpdateAssetURLTests(unittest.TestCase):
    def test_only_trusted_https_release_assets_are_accepted(self):
        self.assertTrue(updater._is_trusted_release_asset_url(
            "https://github.com/konokuroineko/Nekotrack/releases/download/v1.2.3/NekoTrack-Setup.exe"
        ))
        self.assertFalse(updater._is_trusted_release_asset_url(
            "http://github.com/konokuroineko/Nekotrack/releases/download/v1.2.3/NekoTrack-Setup.exe"
        ))
        self.assertFalse(updater._is_trusted_release_asset_url(
            "https://github.com.attacker.invalid/konokuroineko/Nekotrack/releases/download/v1.2.3/Setup.exe"
        ))
        self.assertFalse(updater._is_trusted_release_asset_url(
            "https://user@github.com/konokuroineko/Nekotrack/releases/download/v1.2.3/Setup.exe"
        ))
        self.assertFalse(updater._is_trusted_release_asset_url(
            "https://github.com:444/konokuroineko/Nekotrack/releases/download/v1.2.3/Setup.exe"
        ))
        self.assertFalse(updater._is_trusted_release_asset_url(
            "https://github.com/other/repo/releases/download/v1.2.3/Setup.exe"
        ))
        self.assertFalse(updater._is_trusted_release_asset_url(
            "https://github.com/konokuroineko/Nekotrack/releases/download/v1.2.3/%2e%2e/Setup.exe"
        ))
        for value in (None, "", 123, "not a URL"):
            with self.subTest(value=value):
                self.assertFalse(updater._is_trusted_release_asset_url(value))


class InstallerDownloaderSecurityTests(unittest.TestCase):
    def _run_downloader(self, url, name="NekoTrack-Setup.exe"):
        downloader = updater.InstallerDownloader(url, name)
        finished = []
        failed = []
        downloader.finished.connect(finished.append)
        downloader.failed.connect(failed.append)
        downloader.run()
        return finished, failed

    def test_untrusted_url_is_rejected_before_network_or_process_launch(self):
        with patch("updater.requests.get") as get, patch("updater.subprocess.Popen") as popen:
            finished, failed = self._run_downloader(
                "https://attacker.invalid/NekoTrack-Setup.exe"
            )
        get.assert_not_called()
        popen.assert_not_called()
        self.assertEqual(finished, [])
        self.assertEqual(len(failed), 1)
        self.assertIn("trusted NekoTrack GitHub release asset", failed[0])

    def test_download_uses_unique_temp_file_and_preserves_legacy_fixed_name(self):
        with tempfile.TemporaryDirectory() as directory:
            temp_dir = Path(directory)
            legacy_path = temp_dir / "NekoTrack-update.exe"
            legacy_path.write_bytes(b"do not overwrite")
            response = _response([b"installer-", b"payload"], {"Content-Length": "17"})

            with (
                patch.object(updater.tempfile, "gettempdir", return_value=directory),
                patch("updater.requests.get", return_value=response),
                patch("updater.subprocess.Popen") as popen,
            ):
                finished, failed = self._run_downloader(
                    "https://github.com/konokuroineko/Nekotrack/releases/download/v1.2.3/NekoTrack-Setup.exe"
                )

            self.assertEqual(failed, [])
            self.assertEqual(len(finished), 1)
            installer_path = Path(finished[0])
            self.assertNotEqual(installer_path, legacy_path)
            self.assertTrue(installer_path.name.startswith("NekoTrack-update-"))
            self.assertEqual(installer_path.read_bytes(), b"installer-payload")
            self.assertEqual(legacy_path.read_bytes(), b"do not overwrite")
            popen.assert_called_once_with([str(installer_path)], close_fds=True)
            installer_path.unlink(missing_ok=True)

    def test_rejects_declared_oversized_download_before_creating_a_file(self):
        with tempfile.TemporaryDirectory() as directory:
            response = _response([b"payload"], {"Content-Length": "5"})
            with (
                patch.object(updater, "MAX_INSTALLER_BYTES", 4),
                patch.object(updater.tempfile, "gettempdir", return_value=directory),
                patch("updater.requests.get", return_value=response),
                patch("updater.subprocess.Popen") as popen,
            ):
                finished, failed = self._run_downloader(
                    "https://github.com/konokuroineko/Nekotrack/releases/download/v1.2.3/NekoTrack-Setup.exe"
                )
            popen.assert_not_called()
            self.assertEqual(finished, [])
            self.assertEqual(len(failed), 1)
            self.assertIn("download limit", failed[0])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_stream_size_limit_cleans_up_partial_download(self):
        with tempfile.TemporaryDirectory() as directory:
            response = _response([b"123", b"456"])
            with (
                patch.object(updater, "MAX_INSTALLER_BYTES", 4),
                patch.object(updater.tempfile, "gettempdir", return_value=directory),
                patch("updater.requests.get", return_value=response),
                patch("updater.subprocess.Popen") as popen,
            ):
                finished, failed = self._run_downloader(
                    "https://github.com/konokuroineko/Nekotrack/releases/download/v1.2.3/NekoTrack-Setup.exe"
                )
            popen.assert_not_called()
            self.assertEqual(finished, [])
            self.assertEqual(len(failed), 1)
            self.assertIn("download limit", failed[0])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_empty_download_is_rejected_and_temp_file_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            response = _response([])
            with (
                patch.object(updater.tempfile, "gettempdir", return_value=directory),
                patch("updater.requests.get", return_value=response),
                patch("updater.subprocess.Popen") as popen,
            ):
                finished, failed = self._run_downloader(
                    "https://github.com/konokuroineko/Nekotrack/releases/download/v1.2.3/NekoTrack-Setup.exe"
                )
            popen.assert_not_called()
            self.assertEqual(finished, [])
            self.assertEqual(len(failed), 1)
            self.assertIn("download was empty", failed[0])
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
