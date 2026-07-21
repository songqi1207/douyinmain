import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import routes.api as api_routes
from app import create_app


class FlaskGodDraftTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def test_generate_god_runs_coze_and_imports_draft_key_locally(self):
        key = {
            "kind": "jianying_draft_key",
            "meta": {"run_id": "flask-god-test"},
            "draft": {"width": 1080, "height": 1920, "name": "西王母"},
            "calls": [
                {
                    "call_id": "audio",
                    "tool": "add_audios",
                    "params": {"audio_infos": [{"audio_url": "https://example.test/a.mp3", "start": 0, "end": 1_000_000}]},
                },
                {
                    "call_id": "main_images",
                    "tool": "add_images",
                    "params": {"image_infos": [{"image_url": "https://example.test/a.jpg", "start": 0, "end": 1_000_000, "in_animation": "Kira游动"}]},
                },
                {
                    "call_id": "slide_a",
                    "tool": "add_captions",
                    "params": {"font": "出云龙", "in_animation": "滚入", "captions": [{"text": "西王母", "start": 0, "end": 500_000}]},
                },
                {
                    "call_id": "title_lock",
                    "tool": "add_captions",
                    "params": {"font": "出云龙", "in_animation": "放大", "captions": [{"text": "西王母", "start": 500_000, "end": 1_000_000}]},
                },
                {
                    "call_id": "main_captions",
                    "tool": "add_captions",
                    "params": {"font": "江湖体", "text_color": "#FFDE00", "captions": [{"text": "昆仑女仙之首", "start": 0, "end": 1_000_000}]},
                },
                {
                    "call_id": "camera_kf",
                    "tool": "add_keyframes",
                    "params": {"keyframes": [
                        {"segment_ref": {"call_id": "main_images", "index": 0}, "property": "KFTypePositionX", "time_offset": 0, "value": 0},
                        {"segment_ref": {"call_id": "main_images", "index": 0}, "property": "KFTypePositionY", "time_offset": 0, "value": 0},
                        {"segment_ref": {"call_id": "main_images", "index": 0}, "property": "UNIFORM_SCALE", "time_offset": 0, "value": 1},
                    ]},
                },
                {
                    "call_id": "effects",
                    "tool": "add_effects",
                    "params": {"effect_infos": [{"effect_title": "金粉闪闪", "start": 0, "end": 1_000_000}]},
                },
            ],
        }
        coze = MagicMock(status_code=200)
        coze.json.return_value = {
            "code": 0,
            "data": json.dumps(
                {"output": json.dumps({"draft_id": "remote-id", "draft_key": json.dumps(key, ensure_ascii=False)}, ensure_ascii=False)},
                ensure_ascii=False,
            ),
        }
        local_report = {
            "draft_id": "LOCAL-DRAFT-ID",
            "draft_name": "LOCAL-DRAFT-ID",
            "draft_dir": "C:/Jianying/LOCAL-DRAFT-ID",
            "warnings": [],
            "message": "草稿已写入",
        }

        with tempfile.TemporaryDirectory(prefix="flask-god-draft-") as temporary:
            draft_dir = Path(temporary) / "LOCAL-DRAFT-ID"
            draft_dir.mkdir()
            local_report["draft_dir"] = str(draft_dir)
            with (
                patch.dict(
                    os.environ,
                    {
                        "COZE_API_TOKEN": "test-token",
                        "COZE_WORKFLOW_OWN03": "published-workflow-id",
                        "MIHE_KEY": "test-mihe-key",
                    },
                ),
                patch.object(api_routes, "_FLASK_DRAFT_KEY_DIR", Path(temporary)),
                patch.object(api_routes.requests, "post", return_value=coze) as post,
                patch.object(api_routes, "import_draft_key", return_value=local_report) as import_key,
            ):
                response = self.client.post(
                    "/api/generate_god",
                    json={
                        "god_name": "西王母",
                        "desc": "昆仑女仙之首，凤冠霞帔",
                        "shuliang": "1",
                        "voice_id": "voice-1",
                    },
                )
                self.assertEqual(response.status_code, 200, response.text)
                payload = response.get_json()
                self.assertTrue(payload["success"])
                self.assertEqual(payload["draft_id"], "LOCAL-DRAFT-ID")
                self.assertEqual(payload["draft_dir"], str(draft_dir))
                self.assertEqual(payload["acceptance_report"]["status"], "passed")
                self.assertEqual(payload["acceptance_report"]["details"]["fonts"]["出云龙"], 2)

                request_json = post.call_args.kwargs["json"]
                self.assertEqual(request_json["workflow_id"], "published-workflow-id")
                self.assertEqual(request_json["parameters"]["zhuti"], "西王母")
                self.assertEqual(request_json["parameters"]["shuliang"], "1")
                self.assertEqual(request_json["parameters"]["mihe_key"], "test-mihe-key")
                import_key.assert_called_once_with(key, force=False, dry_run=False)

                downloaded = self.client.get(payload["download_url"])
                try:
                    self.assertEqual(downloaded.status_code, 200)
                    self.assertEqual(json.loads(downloaded.data), key)
                finally:
                    downloaded.close()

                acceptance = self.client.get(payload["acceptance_report_url"])
                try:
                    self.assertEqual(acceptance.status_code, 200)
                    saved_report = json.loads(acceptance.data)
                    self.assertEqual(saved_report["draft_id"], "LOCAL-DRAFT-ID")
                    self.assertEqual(saved_report["status_text"], "验收通过")
                finally:
                    acceptance.close()

    def test_coze_request_retries_without_broken_environment_proxy(self):
        direct_response = MagicMock(status_code=200)
        direct_session = MagicMock()
        direct_session.post.return_value = direct_response

        with (
            patch.object(
                api_routes.requests,
                "post",
                side_effect=api_routes.requests.exceptions.ProxyError("proxy unavailable"),
            ),
            patch.object(api_routes.requests, "Session", return_value=direct_session),
        ):
            response = api_routes._post_coze_workflow(
                "https://api.coze.cn/v1/workflow/run",
                headers={"Authorization": "Bearer test-token"},
                payload={"workflow_id": "test-id", "parameters": {}},
            )

        self.assertIs(response, direct_response)
        self.assertFalse(direct_session.trust_env)
        direct_session.post.assert_called_once()
        direct_session.close.assert_called_once()

    def test_local_bridge_allows_private_network_preflight(self):
        response = self.client.options(
            "/api/tools/create_draft_from_key",
            headers={
                "Origin": "https://example.test",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
                "Access-Control-Request-Private-Network": "true",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Access-Control-Allow-Private-Network"), "true")


if __name__ == "__main__":
    unittest.main()
