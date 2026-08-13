import base64
import hashlib
import hmac
import json
import unittest

from direct_upload_tokens import create_direct_upload_token


class DirectUploadTokenTests(unittest.TestCase):
    def test_token_is_signed_and_scoped_to_one_object(self):
        token = create_direct_upload_token(
            "test-secret",
            object_key="exports/job-1.mp4",
            job_id="job-1",
            device_id="device-1",
            size_bytes=12345,
            ttl_seconds=600,
            now=1000,
        )
        payload_segment, signature_segment = token.split(".")
        expected = hmac.new(b"test-secret", payload_segment.encode("ascii"), hashlib.sha256).digest()
        actual = base64.urlsafe_b64decode(signature_segment + "=" * (-len(signature_segment) % 4))
        self.assertTrue(hmac.compare_digest(actual, expected))
        payload = json.loads(
            base64.urlsafe_b64decode(payload_segment + "=" * (-len(payload_segment) % 4)).decode("utf-8")
        )
        self.assertEqual(payload["key"], "exports/job-1.mp4")
        self.assertEqual(payload["size_bytes"], 12345)
        self.assertEqual(payload["exp"], 1600)


if __name__ == "__main__":
    unittest.main()
