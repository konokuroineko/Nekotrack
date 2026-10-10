"""Adversarial tests for cover-cache path, URL, payload, and image bounds."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage

import image_cache


VALID_URL = "https://images.example.invalid/covers/work.png"


def png_bytes(width=16, height=24):
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(0xFF7350A0)
    buffer = QBuffer()
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise RuntimeError("Could not open an in-memory image buffer")
    if not image.save(buffer, "PNG"):
        raise RuntimeError("Could not create PNG test fixture")
    payload = bytes(buffer.data())
    buffer.close()
    return payload


def response_for(payload, content_length=None, url=VALID_URL):
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.raise_for_status.return_value = None
    response.url = url
    response.headers = {}
    if content_length is not None:
        response.headers["Content-Length"] = str(content_length)
    response.iter_content.return_value = [payload]
    return response


class CoverCacheInputSafetyTests(unittest.TestCase):
    def test_cover_ids_accept_signed_numeric_provider_ids_and_reject_path_inputs(self):
        self.assertEqual(image_cache._safe_work_id(42), "42")
        self.assertEqual(image_cache._safe_work_id("-42"), "-42")
        self.assertEqual(image_cache._safe_work_id(-42), "-42")

        invalid_ids = [
            None,
            True,
            False,
            0,
            "0",
            "",
            "../outside",
            "../../other/file",
            "1/../../evil",
            "/tmp/evil",
            "12.jpg",
            "+42",
            1.5,
            [],
            {},
            "9" * 100,
            2**80,
        ]
        for work_id in invalid_ids:
            with self.subTest(work_id=repr(work_id)):
                with self.assertRaises(ValueError):
                    image_cache._safe_work_id(work_id)

    def test_cover_url_requires_an_unambiguous_https_url(self):
        self.assertEqual(
            image_cache._safe_image_url(" https://images.example.invalid/a.png "),
            "https://images.example.invalid/a.png",
        )

        invalid_urls = [
            None,
            "",
            17,
            "file:///etc/passwd",
            "data:image/png;base64,AAAA",
            "http://images.example.invalid/a.png",
            "https://user:pass@images.example.invalid/a.png",
            "https://images.example.invalid:444/a.png",
            "https://images.example.invalid/a.png#fragment",
            "https:///missing-host/a.png",
            "https://[invalid-ipv6/a.png",
            "https://127.0.0.1/a.png",
            "https://10.1.2.3/a.png",
            "https://[::1]/a.png",
            "https://metadata.google.internal/metadata",
        ]
        for url in invalid_urls:
            with self.subTest(url=repr(url)):
                with self.assertRaises(ValueError):
                    image_cache._safe_image_url(url)

    def test_path_traversal_and_invalid_urls_never_reach_the_network(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            image_cache, "IMAGE_DIRECTORY", Path(directory) / "works"
        ), patch.object(image_cache.requests, "get") as request:
            for work_id in ("../../NekoTrack-settings", "1/../../outside"):
                with self.subTest(work_id=work_id):
                    with self.assertRaises(ValueError):
                        image_cache.download_cover(work_id, VALID_URL)
            with self.assertRaises(ValueError):
                image_cache.download_cover(12, "file:///tmp/pretend.png")

            request.assert_not_called()
            self.assertEqual(list(Path(directory).rglob("*")), [])

    def test_redirect_to_a_private_host_is_rejected_before_following(self):
        redirect = Mock()
        redirect.status_code = 302
        redirect.headers = {"Location": "https://127.0.0.1/private.png"}
        redirect.close.return_value = None
        with tempfile.TemporaryDirectory() as directory, patch.object(
            image_cache, "IMAGE_DIRECTORY", Path(directory) / "works"
        ), patch.object(image_cache.requests, "get", return_value=redirect) as request:
            with self.assertRaisesRegex(ValueError, "private or local"):
                image_cache.download_cover(12, VALID_URL)

        request.assert_called_once_with(VALID_URL, timeout=15, stream=True, allow_redirects=False)
        redirect.close.assert_called_once()
        self.assertEqual(list(Path(directory).rglob("*")), [])

    def test_redirect_to_a_public_https_cdn_is_followed(self):
        payload = png_bytes(16, 24)
        final_url = "https://cdn.example.com/covers/work.png"
        redirect = Mock()
        redirect.status_code = 302
        redirect.headers = {"Location": final_url}
        redirect.close.return_value = None
        response = response_for(payload, len(payload), url=final_url)

        with tempfile.TemporaryDirectory() as directory, patch.object(
            image_cache, "IMAGE_DIRECTORY", Path(directory) / "works"
        ), patch.object(image_cache.requests, "get", side_effect=[redirect, response]) as request:
            saved = Path(image_cache.download_cover(12, VALID_URL))
            self.assertTrue(saved.is_file())

        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[0].args[0], VALID_URL)
        self.assertEqual(request.call_args_list[1].args[0], final_url)
        self.assertTrue(all(call.kwargs["allow_redirects"] is False for call in request.call_args_list))

    def test_valid_cover_is_streamed_resized_and_saved_inside_cache(self):
        payload = png_bytes(32, 48)
        response = response_for(payload, len(payload))
        with tempfile.TemporaryDirectory() as directory:
            image_directory = Path(directory) / "safe" / "works"
            with patch.object(image_cache, "IMAGE_DIRECTORY", image_directory), patch.object(
                image_cache.requests, "get", return_value=response
            ) as request:
                saved = Path(image_cache.download_cover(-42, VALID_URL))

            request.assert_called_once_with(VALID_URL, timeout=15, stream=True, allow_redirects=False)
            self.assertEqual(saved, image_directory / "-42.jpg")
            self.assertTrue(saved.is_file())
            image = QImage(str(saved))
            self.assertFalse(image.isNull())
            self.assertLessEqual(image.width(), 400)
            self.assertLessEqual(image.height(), 600)

    def test_declared_oversize_payload_is_rejected_before_reading_body(self):
        response = response_for(b"ignored", content_length=11)
        with tempfile.TemporaryDirectory() as directory, patch.object(
            image_cache, "IMAGE_DIRECTORY", Path(directory) / "works"
        ), patch.object(image_cache, "MAX_COVER_BYTES", 10), patch.object(
            image_cache.requests, "get", return_value=response
        ):
            with self.assertRaisesRegex(ValueError, "20 MiB"):
                image_cache.download_cover(12, VALID_URL)

        response.iter_content.assert_not_called()
        self.assertEqual(list(Path(directory).rglob("*")), [])

    def test_streamed_oversize_payload_is_rejected_before_any_file_is_created(self):
        response = response_for(b"", content_length=None)
        response.iter_content.return_value = [b"123456", b"78901"]
        with tempfile.TemporaryDirectory() as directory, patch.object(
            image_cache, "IMAGE_DIRECTORY", Path(directory) / "works"
        ), patch.object(image_cache, "MAX_COVER_BYTES", 10), patch.object(
            image_cache.requests, "get", return_value=response
        ):
            with self.assertRaisesRegex(ValueError, "exceeded"):
                image_cache.download_cover(12, VALID_URL)

        self.assertEqual(list(Path(directory).rglob("*")), [])

    def test_failed_atomic_save_preserves_existing_cover_and_cleans_temporary_file(self):
        class FailingImage:
            def scaled(self, *args, **kwargs):
                return self

            def save(self, *args, **kwargs):
                return False

        payload = png_bytes(16, 24)
        response = response_for(payload, len(payload))
        with tempfile.TemporaryDirectory() as directory:
            image_directory = Path(directory) / "works"
            image_directory.mkdir()
            existing = image_directory / "12.jpg"
            original_bytes = b"previous valid cover"
            existing.write_bytes(original_bytes)

            with patch.object(image_cache, "IMAGE_DIRECTORY", image_directory), patch.object(
                image_cache, "_decode_cover", return_value=FailingImage()
            ), patch.object(image_cache.requests, "get", return_value=response):
                with self.assertRaisesRegex(OSError, "Could not save cover image"):
                    image_cache.download_cover(12, VALID_URL)

            self.assertEqual(existing.read_bytes(), original_bytes)
            self.assertEqual(list(image_directory.iterdir()), [existing])

    def test_corrupt_image_is_not_saved(self):
        response = response_for(b"not an image")
        with tempfile.TemporaryDirectory() as directory, patch.object(
            image_cache, "IMAGE_DIRECTORY", Path(directory) / "works"
        ), patch.object(image_cache.requests, "get", return_value=response):
            with self.assertRaisesRegex(ValueError, "supported image"):
                image_cache.download_cover(12, VALID_URL)

        self.assertEqual(list(Path(directory).rglob("*")), [])

    def test_excessive_image_dimensions_are_rejected_before_decode(self):
        # This small PNG has a maliciously wide header but an actual body from a
        # normal image. Size metadata is checked before QImageReader decodes it.
        payload = png_bytes(8193, 1)
        response = response_for(payload, len(payload))
        with tempfile.TemporaryDirectory() as directory, patch.object(
            image_cache, "IMAGE_DIRECTORY", Path(directory) / "works"
        ), patch.object(image_cache.requests, "get", return_value=response):
            with self.assertRaisesRegex(ValueError, "dimensions are too large"):
                image_cache.download_cover(12, VALID_URL)

        self.assertEqual(list(Path(directory).rglob("*")), [])


if __name__ == "__main__":
    unittest.main()
