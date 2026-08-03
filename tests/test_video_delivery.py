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
            self.assertEqual(command[command.index("-preset") + 1], "medium")
            self.assertEqual(command[command.index("-b:a") + 1], "128k")
            self.assertEqual(command[command.index("-maxrate") + 1], "5000k")
            self.assertIn("scale=1920:1080", command[command.index("-vf") + 1])
            self.assertIn("fps=30", command[command.index("-vf") + 1])
            self.assertIn("-map_metadata", command)
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

    def test_large_r2_upload_uses_multipart_protocol(self):
        with tempfile.TemporaryDirectory(prefix="video-multipart-upload-test-") as temporary:
            source = Path(temporary) / "large.mp4"
            source.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 64)
            created = MagicMock(status_code=201, text="")
            created.json.return_value = {"uploadId": "upload-123"}
            uploaded = MagicMock(status_code=200, text="")
            uploaded.json.return_value = {"partNumber": 1, "etag": "etag-1"}
            completed = MagicMock(status_code=201, text="")
            session = MagicMock()
            session.post.side_effect = [created, completed]
            session.put.return_value = uploaded
            with (
                patch.dict(
                    os.environ,
                    {
                        "R2_EXPORT_UPLOAD_URL": "https://worker.test/exports",
                        "R2_EXPORT_PUBLIC_BASE_URL": "https://cdn.test/exports",
                        "R2_EXPORT_UPLOAD_TOKEN": "server-secret",
                        "R2_EXPORT_SINGLE_UPLOAD_MAX_BYTES": "8",
                    },
                    clear=True,
                ),
                patch("video_delivery.requests.Session", return_value=session),
            ):
                url = video_delivery.upload_video_to_r2(source, "large.mp4")

            self.assertEqual(url, "https://cdn.test/exports/large.mp4")
            self.assertEqual(session.post.call_args_list[0].kwargs["params"], {"action": "mpu-create"})
            self.assertEqual(session.put.call_args.kwargs["params"]["action"], "mpu-uploadpart")
            self.assertEqual(session.put.call_args.kwargs["params"]["uploadId"], "upload-123")
            self.assertEqual(session.post.call_args_list[1].kwargs["params"]["action"], "mpu-complete")
            self.assertEqual(
                session.post.call_args_list[1].kwargs["json"],
                {"parts": [{"partNumber": 1, "etag": "etag-1"}]},
            )
            session.delete.assert_not_called()

    def test_failed_multipart_upload_is_aborted(self):
        with tempfile.TemporaryDirectory(prefix="video-multipart-abort-test-") as temporary:
            source = Path(temporary) / "large.mp4"
            source.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 64)
            created = MagicMock(status_code=201, text="")
            created.json.return_value = {"uploadId": "upload-456"}
            rejected = MagicMock(status_code=400, text="part rejected")
            session = MagicMock()
            session.post.return_value = created
            session.put.return_value = rejected
            with (
                patch.dict(
                    os.environ,
                    {
                        "R2_EXPORT_UPLOAD_URL": "https://worker.test/exports",
                        "R2_EXPORT_PUBLIC_BASE_URL": "https://cdn.test/exports",
                        "R2_EXPORT_UPLOAD_TOKEN": "server-secret",
                        "R2_EXPORT_SINGLE_UPLOAD_MAX_BYTES": "8",
                    },
                    clear=True,
                ),
                patch("video_delivery.requests.Session", return_value=session),
            ):
                with self.assertRaisesRegex(video_delivery.VideoDeliveryError, "分片 1 上传失败"):
                    video_delivery.upload_video_to_r2(source, "large.mp4")

            self.assertEqual(session.delete.call_args.kwargs["params"]["action"], "mpu-abort")
            self.assertEqual(session.delete.call_args.kwargs["params"]["uploadId"], "upload-456")

    def test_single_upload_413_falls_back_to_multipart(self):
        with tempfile.TemporaryDirectory(prefix="video-upload-413-test-") as temporary:
            source = Path(temporary) / "video.mp4"
            source.write_bytes(b"\x00\x00\x00\x18ftypmp42")
            response = MagicMock(status_code=413, text="<html>too large</html>")
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
                patch("video_delivery.requests.put", return_value=response),
                patch("video_delivery._upload_video_multipart") as multipart,
            ):
                url = video_delivery.upload_video_to_r2(source, "video.mp4")

            self.assertEqual(url, "https://cdn.test/exports/video.mp4")
            multipart.assert_called_once()

    def test_r2_delete_uses_bearer_auth_for_owned_export_url(self):
        response = MagicMock(status_code=204, text="")
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
            patch("video_delivery.requests.delete", return_value=response) as delete,
        ):
            removed = video_delivery.delete_video_from_r2(
                "https://cdn.test/exports/job-device-preview.mp4"
            )

        self.assertTrue(removed)
        self.assertEqual(delete.call_args.args[0], "https://worker.test/exports/job-device-preview.mp4")
        self.assertEqual(delete.call_args.kwargs["headers"]["Authorization"], "Bearer server-secret")

    def test_publish_falls_back_to_lossless_remux_when_compression_fails(self):
        with tempfile.TemporaryDirectory(prefix="video-remux-fallback-") as temporary:
            source = Path(temporary) / "source.mp4"
            source.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 4096)
            with (
                patch.object(
                    video_delivery,
                    "compress_video_for_web",
                    side_effect=video_delivery.VideoDeliveryError("encode failed"),
                ),
                patch.object(video_delivery, "remux_video_for_web", return_value=source) as remux,
                patch.object(
                    video_delivery,
                    "upload_video_to_r2",
                    side_effect=["https://cdn.test/original.mp4", "https://cdn.test/preview.mp4"],
                ),
            ):
                result = video_delivery.publish_device_video("job-id", source)

            self.assertEqual(result[0], "https://cdn.test/original.mp4")
            self.assertEqual(result[1], "https://cdn.test/original.mp4")
            self.assertEqual(result[4], "original_fallback")
            remux.assert_called_once()

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

    def test_background_delivery_promotes_local_result_to_r2_url(self):
        job = {
            "id": "job-id",
            "status": "succeeded",
            "results": [
                {
                    "type": "video",
                    "url": "/api/v1/job-results/job-id-device.mp4",
                    "downloadable": True,
                }
            ],
        }
        with (
            patch.object(workflow_jobs, "get_job", return_value=job),
            patch.object(workflow_jobs, "_update_job") as update,
        ):
            promoted = workflow_jobs.promote_device_render_result(
                "job-id",
                "job-id-device.mp4",
                "https://cdn.test/exports/job-id-device-web.mp4",
                "https://cdn.test/exports/job-id-device-original.mp4",
            )

        self.assertTrue(promoted)
        results = json.loads(update.call_args.kwargs["results_json"])
        self.assertEqual(results[0]["url"], "https://cdn.test/exports/job-id-device-web.mp4")
        self.assertEqual(results[0]["download_url"], "https://cdn.test/exports/job-id-device-original.mp4")


if __name__ == "__main__":
    unittest.main()
