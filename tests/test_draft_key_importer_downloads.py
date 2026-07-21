import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

import utils.draft_key_importer as draft_importer


class _Response:
    content = b"downloaded-asset"
    headers = {}

    @staticmethod
    def raise_for_status():
        return None


class DraftKeyImporterDownloadTests(unittest.TestCase):
    def test_proxy_failure_falls_back_to_direct_connection(self):
        direct_session = MagicMock()
        direct_session.get.return_value = _Response()

        with tempfile.TemporaryDirectory(prefix="draft-key-download-") as temporary:
            with (
                patch.object(draft_importer, "_CACHE_DIR", Path(temporary)),
                patch.object(
                    draft_importer.requests,
                    "get",
                    side_effect=requests.exceptions.ProxyError("proxy unavailable"),
                ),
                patch.object(
                    draft_importer.requests,
                    "Session",
                    return_value=direct_session,
                ),
            ):
                asset_map, failed = draft_importer._prefetch_assets(
                    ["https://example.com/frame.png"]
                )

        self.assertEqual(failed, {})
        self.assertIn("https://example.com/frame.png", asset_map)
        self.assertFalse(direct_session.trust_env)
        direct_session.get.assert_called_once_with(
            "https://example.com/frame.png",
            timeout=draft_importer._DOWNLOAD_TIMEOUT,
        )
        direct_session.close.assert_called_once()

    def test_duplicate_urls_are_downloaded_once(self):
        response = _Response()
        with tempfile.TemporaryDirectory(prefix="draft-key-download-") as temporary:
            with (
                patch.object(draft_importer, "_CACHE_DIR", Path(temporary)),
                patch.object(draft_importer.requests, "get", return_value=response) as get,
            ):
                asset_map, failed = draft_importer._prefetch_assets(
                    ["https://example.com/voice.mp3", "https://example.com/voice.mp3"]
                )

        self.assertEqual(failed, {})
        self.assertEqual(len(asset_map), 1)
        get.assert_called_once()

    def test_cdn_image_pseudo_suffix_is_replaced_with_real_png_suffix(self):
        response = _Response()
        response.content = b"\x89PNG\r\n\x1a\n" + b"png-data"
        response.headers = {"Content-Type": "image/png"}
        url = "https://example.com/frame.png~tplv-image.image?signature=test"

        with tempfile.TemporaryDirectory(prefix="draft-key-download-") as temporary:
            with (
                patch.object(draft_importer, "_CACHE_DIR", Path(temporary)),
                patch.object(draft_importer.requests, "get", return_value=response),
            ):
                asset_map, failed = draft_importer._prefetch_assets([url])
                cached = Path(asset_map[url])
                self.assertTrue(cached.is_file())
                self.assertEqual(cached.suffix, ".png")

        self.assertEqual(failed, {})

    def test_existing_pseudo_suffix_cache_is_migrated(self):
        url = "https://example.com/frame.image"
        with tempfile.TemporaryDirectory(prefix="draft-key-download-") as temporary:
            cache_dir = Path(temporary)
            digest = draft_importer.hashlib.sha1(url.encode("utf-8")).hexdigest()
            stale = cache_dir / f"{digest}.image"
            stale.write_bytes(b"\x89PNG\r\n\x1a\n" + b"png-data")
            with patch.object(draft_importer, "_CACHE_DIR", cache_dir):
                local_path, error = draft_importer._download_asset(url)

            self.assertIsNone(error)
            self.assertEqual(Path(local_path).suffix, ".png")
            self.assertFalse(stale.exists())


if __name__ == "__main__":
    unittest.main()
