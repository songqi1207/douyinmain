import sys
import tempfile
import unittest
from pathlib import Path

from windows_render_worker import (
    RenderWorkerBusy,
    RenderWorkerError,
    WindowsRenderPipeline,
    WorkerConfig,
    extract_render_draft_id,
)


TEST_DRAFT_ID = "fdee55ea-0ba9-484d-8e6a-1abcbaaad15b"
TEST_DRAFT_KEY = {
    "kind": "jianying_draft_key",
    "draft": {"width": 1080, "height": 1920, "name": "测试草稿"},
    "calls": [
        {
            "call_id": "caption",
            "tool": "add_captions",
            "params": {"captions": [{"text": "测试", "start": 0, "end": 1_000_000}]},
        }
    ],
}


def make_config(output_dir: Path, **overrides):
    values = {
        "api_token": "test-secret",
        "draft_root": output_dir / "drafts",
        "jianying_exe": Path(sys.executable),
        "output_dir": output_dir,
        "public_base_url": "http://render-worker.test:8765",
        "export_driver": "unconfigured",
        "export_command": (),
        "mihe_timeout_seconds": 10,
        "draft_timeout_seconds": 30,
        "export_timeout_seconds": 60,
        "dry_run": True,
    }
    values.update(overrides)
    return WorkerConfig(**values)


class WindowsRenderWorkerTests(unittest.TestCase):
    def test_extracts_uuid_from_main_backend_contract(self):
        payload = {
            "job_id": "job-1",
            "workflow_code": "G159",
            "drafts": [f"https://mihe.example/draft/{TEST_DRAFT_ID}"],
        }
        self.assertEqual(extract_render_draft_id(payload), TEST_DRAFT_ID)

    def test_rejects_payload_without_uuid(self):
        with self.assertRaises(RenderWorkerError):
            extract_render_draft_id({"drafts": ["not-a-draft"]})

    def test_dry_run_returns_signed_mp4_url(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary).resolve()
            pipeline = WindowsRenderPipeline(make_config(output_dir))
            result = pipeline.render({"job_id": "job-1", "drafts": [TEST_DRAFT_ID]})
            output_path = Path(result["output_path"])
            self.assertTrue(output_path.is_file())
            self.assertIn("/videos/job-1-", result["video_url"])
            signature = result["video_url"].split("signature=", 1)[1]
            self.assertTrue(pipeline.verify_video_signature(output_path.name, signature))
            self.assertEqual(pipeline.status()["last_job"]["status"], "succeeded")

    def test_dry_run_accepts_draft_key_without_mihe_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary).resolve()
            pipeline = WindowsRenderPipeline(make_config(output_dir))
            result = pipeline.render({"job_id": "draft-key-job", "draft_key": TEST_DRAFT_KEY})

            self.assertTrue(Path(result["output_path"]).is_file())
            self.assertEqual(pipeline.status()["last_job"]["status"], "succeeded")
            self.assertNotEqual(result["draft_id"], TEST_DRAFT_ID)

    def test_busy_worker_rejects_second_job(self):
        with tempfile.TemporaryDirectory() as temporary:
            pipeline = WindowsRenderPipeline(make_config(Path(temporary).resolve()))
            self.assertTrue(pipeline._render_lock.acquire(blocking=False))
            try:
                with self.assertRaises(RenderWorkerBusy):
                    pipeline.render({"draft_id": TEST_DRAFT_ID})
            finally:
                pipeline._render_lock.release()

    def test_command_export_driver_expands_placeholders_without_shell(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output_path = root / "result.mp4"
            command = (
                sys.executable,
                "-c",
                "from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(b'mp4')",
                "{output_path}",
            )
            pipeline = WindowsRenderPipeline(
                make_config(root, dry_run=False, export_driver="command", export_command=command)
            )
            pipeline._active_job = {"stage": "test"}
            pipeline._export_draft(TEST_DRAFT_ID, root / TEST_DRAFT_ID, output_path)
            self.assertEqual(output_path.read_bytes(), b"mp4")


if __name__ == "__main__":
    unittest.main()
