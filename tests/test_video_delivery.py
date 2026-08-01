import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import video_delivery
import workflow_jobs


class VideoDeliveryTests(unittest.TestCase):
    def test_r2_export_requires_every_secret_setting(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(video_delivery.r2_export_configured())
        with patch.dict(
            os.environ,
            {
                "R2_EXPORT_ENABLED": "1",
                "R2_EXPORT_UPLOAD_URL": "https://worker.test/exports",
                "R2_EXPORT_PUBLIC_BASE_URL": "https://worker.test/exports",
                "R2_EXPORT_UPLOAD_TOKEN": "secret",
            },
            clear=True,
        ):
            self.assertTrue(video_delivery.r2_export_configured())

    def test_compress_video_uses_web_compatible_visual_quality_settings(self):
        with tempfile.TemporaryDirectory(prefix="video-compress-test-") as temporary:
            root = Path(temporary)
            source = root / "source.mp4"
            destination = root / "web.mp4"
            source.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 4096)

            def write_output(command, **_kwargs):
                Path(command[-1]).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"y" * 512)
                return MagicMock(returncode=0, stdout="", stderr="")

            with patch("video_delivery.subprocess.run", side_effect=write_output) as run:
                result = video_delivery.compress_video_for_web(source, destination)

            command = run.call_args.args[0]
            self.assertEqual(result, destination.resolve())
            self.assertIn("libx264", command)
            self.assertEqual(command[command.index("-crf") + 1], "20")
            self.assertEqual(command[command.index("-preset") + 1], "slow")
            self.assertEqual(command[command.index("-b:a") + 1], "128k")
            self.assertIn("+faststart", command)

    def test_compress_video_uses_a_unique_work_file_for_each_attempt(self):
        with tempfile.TemporaryDirectory(prefix="video-compress-work-file-test-") as temporary:
            root = Path(temporary)
            source = root / "source.mp4"
            destination = root / "web.mp4"
            source.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 4096)
            work_files = []

            def write_output(command, **_kwargs):
                work_file = Path(command[-1])
                work_files.append(work_file)
                work_file.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"y" * 512)
                return MagicMock(returncode=0, stdout="", stderr="")

            with patch("video_delivery.subprocess.run", side_effect=write_output):
                video_delivery.compress_video_for_web(source, destination)
                video_delivery.compress_video_for_web(source, destination)

            self.assertEqual(len(set(work_files)), 2)

    def test_r2_upload_uses_bearer_auth_and_returns_public_url(self):
        with tempfile.TemporaryDirectory(prefix="video-upload-test-") as temporary:
            source = Path(temporary) / "video.mp4"
            source.write_bytes(b"\x00\x00\x00\x18ftypmp42")
            response = MagicMock(status_code=201, text="")
            with (
                patch.dict(
                    os.environ,
                    {
                        "R2_EXPORT_UPLOAD_URL": "https://worker.test/exports",
                        "R2_EXPORT_PUBLIC_BASE_URL": "https://cdn.test/exports",
                        "R2_EXPORT_UPLOAD_TOKEN": "server-secret",
                    },
                    clear=True,
                ),
                patch("video_delivery.requests.put", return_value=response) as put,
            ):
                url = video_delivery.upload_video_to_r2(source, "job-device-web.mp4")

            self.assertEqual(url, "https://cdn.test/exports/job-device-web.mp4")
            self.assertEqual(put.call_args.args[0], "https://worker.test/exports/job-device-web.mp4")
            self.assertEqual(put.call_args.kwargs["headers"]["Authorization"], "Bearer server-secret")
            self.assertEqual(put.call_args.kwargs["headers"]["Content-Type"], "video/mp4")

    def test_completed_device_job_can_reference_r2_url(self):
        job = {
            "id": "job-id",
            "render_device_id": "device-id",
            "status": "rendering",
        }
        with (
            patch.object(workflow_jobs, "get_job", return_value=job),
            patch.object(workflow_jobs, "_update_job") as update,
            patch.object(workflow_jobs, "append_job_log"),
        ):
            completed = workflow_jobs.complete_device_render_job(
                "job-id",
                "device-id",
                "job-id-device.mp4",
                result_url="https://cdn.test/exports/job-id-device-web.mp4",
            )

        self.assertTrue(completed)
        results = json.loads(update.call_args.kwargs["results_json"])
        self.assertEqual(results[0]["url"], "https://cdn.test/exports/job-id-device-web.mp4")
        self.assertEqual(update.call_args.kwargs["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
