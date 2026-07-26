import hashlib
import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ["WORKFLOW_DATA_DIR"] = tempfile.mkdtemp(prefix="workflow-api-tests-")
os.environ["WORKFLOW_PROVIDER_MODE"] = "demo"
os.environ["WORKFLOW_QUEUE_MODE"] = "inline"
os.environ["SITE_ADMIN_EMAIL"] = "admin@example.test"
os.environ["SITE_ADMIN_PASSWORD"] = "admin-test-password-123"
os.environ["SMTP_HOST"] = "smtp.example.test"
os.environ["SMTP_FROM"] = "noreply@example.test"
os.environ["COZE_API_TOKEN"] = ""
os.environ["COZE_WORKFLOW_GOD"] = ""
os.environ["COZE_WORKFLOW_OWN01"] = ""
os.environ["COZE_WORKFLOW_OWN02"] = ""
os.environ["COZE_WORKFLOW_OWN03"] = ""
os.environ["MIHE_KEY"] = ""

from fastapi.testclient import TestClient

import fastapi_app
from fastapi_app import app
import workflow_jobs
from workflow_jobs import _post_coze_workflow, _provider_inputs, _run_coze
from workflow_registry import get_workflow


class WorkflowApiTests(unittest.TestCase):
    def test_fastapi_endpoint_parameters_avoid_python_310_union_syntax(self):
        for route in app.routes:
            endpoint = getattr(route, "endpoint", None)
            if endpoint is None:
                continue
            for parameter in inspect.signature(endpoint).parameters.values():
                self.assertNotIn(
                    " | ",
                    str(parameter.annotation),
                    f"{endpoint.__name__}.{parameter.name} is not compatible with Python 3.8",
                )

    def test_helper_download_is_versioned_and_never_cached(self):
        with tempfile.TemporaryDirectory(prefix="helper-download-") as temporary:
            root = Path(temporary)
            executable = root / "dist" / "AIVideoCreator.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"MZ-versioned-helper")
            with patch.object(fastapi_app, "ROOT", root):
                response = fastapi_app.api_download_draft_bridge()
            self.assertEqual(Path(response.path), executable)
            self.assertIn("AI-Video-Creator-v1.3.4.exe", response.headers["content-disposition"])
            self.assertIn("no-store", response.headers["cache-control"])
            self.assertEqual(response.headers["x-helper-version"], "1.3.4")
            self.assertEqual(
                response.headers["x-content-sha256"],
                hashlib.sha256(executable.read_bytes()).hexdigest(),
            )

    @classmethod
    def setUpClass(cls):
        cls.admin_client = TestClient(app)
        admin_login = cls.admin_client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.test", "password": "admin-test-password-123"},
        )
        assert admin_login.status_code == 200, admin_login.text

        cls.client = TestClient(app)
        applied = cls.client.post(
            "/api/v1/auth/register",
            json={"email": "workflow-user@example.test"},
        )
        assert applied.status_code == 202, applied.text
        sent = {}

        def capture_email(email, temporary_password, login_url):
            sent.update(email=email, password=temporary_password, login_url=login_url)

        with patch("fastapi_app.send_registration_approved", side_effect=capture_email):
            approved = cls.admin_client.post(
                f"/api/v1/admin/registration-applications/{applied.json()['application']['id']}/approve"
            )
        assert approved.status_code == 200, approved.text
        assert "password" not in approved.text.lower()
        assert sent["email"] == "workflow-user@example.test"
        logged_in = cls.client.post(
            "/api/v1/auth/login",
            json={"email": sent["email"], "password": sent["password"]},
        )
        assert logged_in.status_code == 200, logged_in.text
        assert logged_in.json()["user"]["must_change_password"] is True
        cls.user_password = "workflow-user-password-123"
        changed = cls.client.post(
            "/api/v1/auth/password",
            json={
                "current_password": sent["password"],
                "new_password": cls.user_password,
            },
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["user"]["must_change_password"] is False

    def test_account_login_and_server_side_favorites(self):
        anonymous = TestClient(app)
        self.assertEqual(anonymous.get("/api/v1/jobs").status_code, 401)
        self.assertEqual(
            anonymous.post("/api/v1/favorites/workflow", json={"resource_id": "G259"}).status_code,
            401,
        )

        favorite = self.client.post("/api/v1/favorites/workflow", json={"resource_id": "G259"})
        self.assertEqual(favorite.status_code, 200)
        self.assertTrue(favorite.json()["selected"])
        me = self.client.get("/api/v1/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertIn("G259", me.json()["workflow_favorites"])

        voices = self.client.get("/api/v1/voices")
        self.assertEqual(voices.status_code, 200)
        self.assertEqual(voices.json()["total"], len(voices.json()["voices"]))
        self.assertEqual(voices.json()["available"], voices.json()["total"] > 0)
        self.assertIn(voices.json()["provider"], {"local-system", "external"})

    def test_registration_is_admin_approved_and_email_delivery_is_required(self):
        anonymous = TestClient(app)
        application = anonymous.post(
            "/api/v1/auth/register",
            json={"email": "pending-user@example.test"},
        )
        self.assertEqual(application.status_code, 202, application.text)
        self.assertNotIn("password", application.text.lower())
        self.assertEqual(
            anonymous.get("/api/v1/admin/registration-applications").status_code,
            401,
        )
        self.assertEqual(
            self.client.get("/api/v1/admin/registration-applications").status_code,
            403,
        )

        pending = self.admin_client.get("/api/v1/admin/registration-applications")
        self.assertEqual(pending.status_code, 200)
        self.assertTrue(pending.json()["email_service"]["configured"])
        self.assertIn("pending-user@example.test", {item["email"] for item in pending.json()["items"]})

        application_id = application.json()["application"]["id"]
        with patch("fastapi_app.email_delivery_status", return_value={"configured": False, "sender": None, "message": "SMTP 未配置"}):
            blocked = self.admin_client.post(
                f"/api/v1/admin/registration-applications/{application_id}/approve"
            )
        self.assertEqual(blocked.status_code, 503)
        still_pending = self.admin_client.get("/api/v1/admin/registration-applications").json()["items"]
        self.assertIn(application_id, {item["id"] for item in still_pending})

        failing = anonymous.post(
            "/api/v1/auth/register",
            json={"email": "smtp-failure@example.test"},
        )
        failing_id = failing.json()["application"]["id"]
        attempted_password = {}

        def fail_smtp(email, temporary_password, login_url):
            attempted_password["value"] = temporary_password
            raise OSError("smtp refused")

        with patch("fastapi_app.send_registration_approved", side_effect=fail_smtp):
            failed = self.admin_client.post(
                f"/api/v1/admin/registration-applications/{failing_id}/approve"
            )
        self.assertEqual(failed.status_code, 502)
        pending_after_failure = self.admin_client.get("/api/v1/admin/registration-applications").json()["items"]
        failed_application = next(item for item in pending_after_failure if item["id"] == failing_id)
        self.assertEqual(failed_application["delivery_status"], "failed")
        rejected_login = anonymous.post(
            "/api/v1/auth/login",
            json={"email": "smtp-failure@example.test", "password": attempted_password["value"]},
        )
        self.assertEqual(rejected_login.status_code, 401)

    def test_temporary_password_requires_change_and_rotates_sessions(self):
        email = "password-change-user@example.test"
        applicant = TestClient(app)
        applied = applicant.post("/api/v1/auth/register", json={"email": email})
        self.assertEqual(applied.status_code, 202, applied.text)
        delivered = {}

        def capture_email(target, temporary_password, login_url):
            delivered.update(
                email=target,
                password=temporary_password,
                login_url=login_url,
            )

        with patch("fastapi_app.send_registration_approved", side_effect=capture_email):
            approved = self.admin_client.post(
                f"/api/v1/admin/registration-applications/{applied.json()['application']['id']}/approve"
            )
        self.assertEqual(approved.status_code, 200, approved.text)

        first = TestClient(app)
        second = TestClient(app)
        for client in (first, second):
            login_response = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": delivered["password"]},
            )
            self.assertEqual(login_response.status_code, 200, login_response.text)
            self.assertTrue(login_response.json()["user"]["must_change_password"])

        blocked = first.post("/api/v1/render-devices/pairing-codes")
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json()["detail"]["code"], "password_change_required")

        wrong = first.post(
            "/api/v1/auth/password",
            json={"current_password": "wrong-password", "new_password": "new-password-123"},
        )
        self.assertEqual(wrong.status_code, 422)
        self.assertEqual(wrong.json()["detail"]["code"], "invalid_current_password")

        changed = first.post(
            "/api/v1/auth/password",
            json={
                "current_password": delivered["password"],
                "new_password": "new-password-123",
            },
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertFalse(changed.json()["user"]["must_change_password"])
        self.assertIsNone(second.get("/api/v1/auth/me").json()["user"])
        self.assertEqual(
            TestClient(app).post(
                "/api/v1/auth/login",
                json={"email": email, "password": delivered["password"]},
            ).status_code,
            401,
        )

    def test_categories_and_catalog(self):
        response = self.client.get("/api/v1/categories")
        self.assertEqual(response.status_code, 200)
        counts = {item["name"]: item["count"] for item in response.json()["categories"]}
        self.assertEqual(
            counts,
            {"起号": 4, "电商": 1, "养生": 1, "减肥": 1, "财经": 1, "自有工作流": 3},
        )

        catalog = self.client.get("/api/v1/workflows", params={"category": "电商"})
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual(catalog.json()["total"], 1)
        self.assertEqual(catalog.json()["items"][0]["code"], "G263")

        expected_ranked = {"电商": "G263", "养生": "G129", "减肥": "G159", "财经": "G222"}
        for category, expected_code in expected_ranked.items():
            ranked = self.client.get("/api/v1/workflows", params={"category": category})
            self.assertEqual(ranked.status_code, 200)
            self.assertEqual([item["code"] for item in ranked.json()["items"]], [expected_code])

        starter_catalog = self.client.get("/api/v1/workflows", params={"category": "起号"})
        self.assertEqual(starter_catalog.status_code, 200)
        self.assertEqual(
            {item["code"] for item in starter_catalog.json()["items"]},
            {"G259", "G258", "G168", "G45"},
        )

        owned = self.client.get("/api/v1/workflows", params={"category": "自有工作流"})
        self.assertEqual(owned.status_code, 200)
        self.assertEqual({item["code"] for item in owned.json()["items"]}, {"OWN01", "OWN02", "OWN03"})
        self.assertTrue(all(item["status"] == "online" for item in owned.json()["items"]))

    def test_owned_book_cigarette_and_god_workflows_generate_downloadable_drafts(self):
        examples = [
            ("OWN01", {"theme": "活着"}),
            ("OWN02", {"theme": "红塔山"}),
            ("OWN03", {"theme": "哪吒"}),
        ]
        for code, inputs in examples:
            created = self.client.post(
                "/api/v1/jobs",
                json={"workflow_code": code, "category": "自有工作流", "inputs": inputs},
            )
            self.assertEqual(created.status_code, 202, created.text)
            job = self.client.get(f"/api/v1/jobs/{created.json()['job']['id']}").json()["job"]
            self.assertEqual(job["status"], "succeeded", job)
            self.assertEqual(job["results"][0]["type"], "draft")
            result = self.client.get(job["results"][0]["url"])
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["type"], "coze-workflow-clipboard-data")
            end = next(
                node
                for node in result.json()["json"]["nodes"]
                if str(node.get("id")) == "900001"
            )
            output_names = [
                item["name"]
                for item in end["data"]["inputs"]["inputParameters"]
            ]
            self.assertEqual(output_names[-2:], ["draft_id", "draft_key"])
            self.assertIn("output", output_names)
            self.assertTrue(
                any(str(node.get("id")) == "390001" for node in result.json()["json"]["nodes"])
            )

    def test_starter_workflow_schemas_and_document_upload(self):
        g259 = self.client.get("/api/v1/workflows/G259", params={"category": "起号"})
        self.assertEqual(g259.status_code, 200)
        schema = {field["name"]: field for field in g259.json()["workflow"]["input_schema"]}
        self.assertEqual(set(schema), {"theme"})
        self.assertEqual(g259.json()["workflow"]["generation_mode"], "workflow_template")

        upload = self.client.post(
            "/api/v1/assets",
            files={"file": ("novel.docx", b"PK\x03\x04workflow-test", "application/octet-stream")},
        )
        self.assertEqual(upload.status_code, 201)
        self.assertEqual(
            upload.json()["asset"]["mime_type"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    def test_reference_workflow_input_aliases(self):
        g259 = _provider_inputs(
            {"content_mode": "life_story", "title": "中彩票五百万", "text": "", "voice_notice": "hidden"},
            "G259",
        )
        self.assertEqual(g259["biaoti"], "中彩票五百万的一生")
        self.assertNotIn("content_mode", g259)
        self.assertNotIn("voice_notice", g259)

        g258 = _provider_inputs({"title": "孩子写作业拖拉", "text": ""}, "G258")
        self.assertEqual(g258["biaoti"], "孩子写作业拖拉")

        g168 = _provider_inputs({"novel_document": "asset-placeholder"}, "G168")
        self.assertEqual(g168["text"], "asset-placeholder")

        g45 = _provider_inputs(
            {"title": "停止内耗", "ip_name": "成长栏目", "text": "正文", "left_text": "女性成长"},
            "G45",
        )
        self.assertEqual(g45["author"], "成长栏目")
        self.assertEqual(g45["content"], "正文")
        self.assertEqual(g45["left_text"], "女性成长")

    def test_published_god_workflow_maps_frontend_inputs_to_coze_parameters(self):
        with patch.dict(os.environ, {"MIHE_KEY": "server-side-mihe-key"}):
            params = _provider_inputs(
                {
                    "god_name": "西王母",
                    "description": "昆仑女仙之首，凤冠霞帔",
                    "scene_count": 1,
                    "script": "西王母的故事",
                    "audio_url": "https://example.test/bgm.mp3",
                    "voice_id": "voice-1",
                },
                "OWN03",
            )

        self.assertEqual(params["zhuti"], "西王母")
        self.assertEqual(params["shuliang"], "1")
        self.assertEqual(params["wenan"], "西王母的故事")
        self.assertEqual(params["audio"], "https://example.test/bgm.mp3")
        self.assertEqual(params["yinse"], "voice-1")
        self.assertIn("西王母为昆仑女仙之首", params["fengge"])
        self.assertEqual(params["mihe_key"], "server-side-mihe-key")
        for browser_name in ("god_name", "description", "scene_count", "script", "audio_url", "voice_id"):
            self.assertNotIn(browser_name, params)

    def test_published_book_and_cigarette_map_one_theme_to_private_parameters(self):
        with patch.dict(
            os.environ,
            {
                "MIHE_KEY": "server-side-mihe-key",
                "BOOK_ACCOUNT_NAME": "不应显示的账号名",
                "BOOK_DEFAULT_IMAGE_COUNT": "1",
                "BOOK_DEFAULT_VOICE_ID": "voice-book",
                "CIGARETTE_LEFT_TEXT": "未成年人禁止吸烟",
                "CIGARETTE_LEFT_TOP_TEXT": "吸烟有害身体健康",
            },
        ):
            book = _provider_inputs(
                {"theme": "克林索尔的最后夏天｜黑塞"},
                "OWN01",
            )
            cigarette = _provider_inputs({"theme": "中华"}, "OWN02")

        self.assertEqual(
            book,
            {
                "account_name": "  ",
                "author": "黑塞",
                "img_count": "2",
                "subject": "克林索尔的最后夏天",
                "yinse": "voice-book",
                "mihe_key": "server-side-mihe-key",
            },
        )
        self.assertEqual(
            cigarette,
            {
                "left": "未成年人禁止吸烟",
                "left_top": "吸烟有害身体健康",
                "xiangyan_name": "中华",
            },
        )
        self.assertNotIn("theme", book)
        self.assertNotIn("theme", cigarette)

    def test_incomplete_published_book_and_cigarette_drafts_are_rejected(self):
        for code, missing_id in (
            ("OWN01", "call_191365"),
            ("OWN02", "call_557577"),
        ):
            with self.subTest(code=code):
                expected = workflow_jobs._EXPECTED_PUBLISHED_DRAFT_CALL_IDS[code]
                key = {
                    "kind": "jianying_draft_key",
                    "meta": {"unresolved_segment_ids": []},
                    "draft": {"width": 1080, "height": 1920, "name": "测试"},
                    "calls": [
                        {"call_id": call_id, "tool": "add_images", "params": {}}
                        for call_id in sorted(expected - {missing_id})
                    ],
                }

                with self.assertRaises(workflow_jobs.ProviderError) as raised:
                    workflow_jobs._validate_published_draft_completeness(
                        {"workflow_code": code},
                        key,
                    )

                self.assertEqual(raised.exception.code, "incomplete_draft_key")
                self.assertIn(missing_id, str(raised.exception))

    def test_empty_optional_cigarette_border_branch_is_accepted(self):
        required = workflow_jobs._EXPECTED_PUBLISHED_DRAFT_CALL_IDS["OWN02"]
        optional = workflow_jobs._OPTIONAL_PUBLISHED_DRAFT_CALL_IDS["OWN02"]
        key = {
            "calls": [
                {"call_id": call_id, "tool": "test", "params": {"items": [{}]}}
                for call_id in required
            ],
            "meta": {
                "unresolved_segment_ids": [],
                "skipped_empty_calls": [
                    {"call_id": call_id}
                    for call_id in optional
                ],
            },
        }

        workflow_jobs._validate_published_draft_completeness(
            {"workflow_code": "OWN02"},
            key,
        )

    def test_complete_published_book_draft_accepts_two_space_watermark(self):
        expected = workflow_jobs._EXPECTED_PUBLISHED_DRAFT_CALL_IDS["OWN01"]
        calls = [
            {"call_id": call_id, "tool": "add_images", "params": {}}
            for call_id in sorted(expected)
        ]
        watermark = next(call for call in calls if call["call_id"] == "call_138594")
        watermark.update(
            {
                "tool": "add_captions",
                "params": {
                    "captions": [
                        {"text": "  ", "start": 0, "end": 1_000_000}
                    ]
                },
            }
        )
        key = {
            "meta": {"unresolved_segment_ids": []},
            "calls": calls,
        }

        workflow_jobs._validate_published_draft_completeness(
            {"workflow_code": "OWN01"},
            key,
        )
        watermark["params"]["captions"][0]["text"] = "被工作流改掉的水印"
        workflow_jobs._normalize_published_draft_key(
            {"workflow_code": "OWN01"},
            key,
        )
        self.assertEqual(
            watermark["params"]["captions"][0]["text"],
            "  ",
        )

    def test_background_coze_request_uses_direct_session_by_default(self):
        direct_response = MagicMock(status_code=200)
        direct_session = MagicMock()
        direct_session.post.return_value = direct_response

        with (
            patch.dict(
                os.environ,
                {
                    "COZE_USE_ENV_PROXY": "",
                    "COZE_CONNECT_TIMEOUT_SECONDS": "45",
                },
            ),
            patch.object(workflow_jobs.requests, "post") as proxied_post,
            patch.object(workflow_jobs.requests, "Session", return_value=direct_session),
            self.assertLogs("workflow.jobs", level="INFO") as captured,
        ):
            response = _post_coze_workflow(
                "https://api.coze.cn/v1/workflow/run",
                headers={"Authorization": "Bearer test-token"},
                payload={"workflow_id": "test-workflow", "parameters": {"theme": "测试"}},
                job_id="job-log-test",
                workflow_code="OWN03",
            )

        self.assertIs(response, direct_response)
        proxied_post.assert_not_called()
        self.assertFalse(direct_session.trust_env)
        direct_session.post.assert_called_once()
        self.assertEqual(direct_session.post.call_args.kwargs["timeout"], (45, 900))
        direct_session.close.assert_called_once()
        log_output = "\n".join(captured.output)
        self.assertIn("job-log-test", log_output)
        self.assertIn("transport=direct", log_output)
        self.assertNotIn("test-token", log_output)
        self.assertNotIn("测试", log_output)

    def test_background_coze_connect_timeout_retries_automatically(self):
        direct_response = MagicMock(status_code=200)
        direct_session = MagicMock()
        direct_session.post.side_effect = [
            workflow_jobs.requests.exceptions.ConnectTimeout("connect timed out"),
            direct_response,
        ]

        with (
            patch.dict(
                os.environ,
                {
                    "COZE_USE_ENV_PROXY": "",
                    "COZE_CONNECT_ATTEMPTS": "3",
                    "COZE_CONNECT_TIMEOUT_SECONDS": "45",
                },
            ),
            patch.object(workflow_jobs.requests, "Session", return_value=direct_session),
            self.assertLogs("workflow.jobs", level="INFO") as captured,
        ):
            response = _post_coze_workflow(
                "https://api.coze.cn/v1/workflow/run",
                headers={"Authorization": "Bearer test-token"},
                payload={"workflow_id": "test-workflow", "parameters": {}},
                job_id="connect-retry-test",
                workflow_code="OWN02",
            )

        self.assertIs(response, direct_response)
        self.assertEqual(direct_session.post.call_count, 2)
        self.assertIn(
            "coze_connect_timeout",
            "\n".join(captured.output),
        )
        direct_session.close.assert_called_once()

    def test_background_coze_request_retries_without_environment_proxy(self):
        proxy_error = workflow_jobs.requests.exceptions.ProxyError("proxy unavailable")
        direct_response = MagicMock(status_code=200)
        direct_session = MagicMock()
        direct_session.post.return_value = direct_response

        with (
            patch.dict(os.environ, {"COZE_USE_ENV_PROXY": "true"}),
            patch.object(workflow_jobs.requests, "post", side_effect=proxy_error) as proxied_post,
            patch.object(workflow_jobs.requests, "Session", return_value=direct_session),
        ):
            response = _post_coze_workflow(
                "https://api.coze.cn/v1/workflow/run",
                headers={"Authorization": "Bearer test-token"},
                payload={"workflow_id": "test-workflow", "parameters": {"theme": "测试"}},
            )

        self.assertIs(response, direct_response)
        proxied_post.assert_called_once()
        self.assertFalse(direct_session.trust_env)
        direct_session.post.assert_called_once()
        direct_session.close.assert_called_once()

    def test_background_coze_timeout_becomes_provider_error(self):
        direct_session = MagicMock()
        direct_session.post.side_effect = workflow_jobs.requests.exceptions.Timeout("timed out")

        with (
            patch.dict(os.environ, {"COZE_USE_ENV_PROXY": ""}),
            patch.object(workflow_jobs.requests, "Session", return_value=direct_session),
        ):
            with self.assertRaises(workflow_jobs.ProviderError) as raised:
                _post_coze_workflow(
                    "https://api.coze.cn/v1/workflow/run",
                    headers={"Authorization": "Bearer test-token"},
                    payload={"workflow_id": "test-workflow", "parameters": {}},
                )

        self.assertEqual(raised.exception.code, "provider_timeout")
        direct_session.close.assert_called_once()

    def test_published_god_workflow_saves_nested_draft_key_result(self):
        key = {
            "kind": "jianying_draft_key",
            "meta": {"run_id": "coze-result-test"},
            "draft": {"width": 1080, "height": 1920, "name": "测试草稿"},
            "calls": [
                {
                    "call_id": "caption",
                    "tool": "add_captions",
                    "params": {"captions": [{"text": "测试", "start": 0, "end": 1_000_000}]},
                }
            ],
        }
        nested = json.dumps(
            {"output": json.dumps({"draft_id": "remote-draft-id", "draft_key": json.dumps(key, ensure_ascii=False)}, ensure_ascii=False)},
            ensure_ascii=False,
        )
        response = MagicMock(status_code=200)
        response.json.return_value = {"code": 0, "data": nested}
        response.iter_lines.return_value = [
            "event: Message",
            "data: " + json.dumps(
                {
                    "content": nested,
                    "content_type": "text",
                    "node_id": "900001",
                    "node_title": "End",
                    "node_is_finish": True,
                },
                ensure_ascii=False,
            ),
            "event: Done",
            "data: " + json.dumps({"debug_url": "https://example.test/debug"}),
        ]

        with tempfile.TemporaryDirectory(prefix="coze-draft-key-") as temporary:
            result_dir = Path(temporary)
            with (
                patch.dict(
                    os.environ,
                    {
                        "COZE_API_TOKEN": "test-token",
                        "COZE_WORKFLOW_OWN03": "published-workflow-id",
                        "COZE_USE_ENV_PROXY": "true",
                        "MIHE_KEY": "test-mihe-key",
                    },
                ),
                patch.object(workflow_jobs, "RESULT_DIR", result_dir),
                patch.object(workflow_jobs.requests, "post", return_value=response) as post,
            ):
                results = _run_coze(
                    {
                        "id": "job-id",
                        "workflow_code": "OWN03",
                        "category": "自有工作流",
                        "inputs": {"god_name": "西王母", "scene_count": 1},
                    }
                )

            self.assertEqual(results[0]["format"], "draft_key")
            self.assertEqual(results[0]["remote_draft_id"], "remote-draft-id")
            saved = result_dir / Path(results[0]["url"]).name
            self.assertEqual(json.loads(saved.read_text(encoding="utf-8")), key)
            request_body = post.call_args.kwargs["json"]
            self.assertEqual(request_body["workflow_id"], "published-workflow-id")
            self.assertEqual(request_body["parameters"]["mihe_key"], "test-mihe-key")

    def test_configured_owned_workflows_switch_to_one_theme_draft_mode(self):
        with patch.dict(
            os.environ,
            {
                "COZE_API_TOKEN": "test-token",
                "COZE_WORKFLOW_OWN01": "published-book-id",
                "COZE_WORKFLOW_OWN02": "published-cigarette-id",
                "COZE_WORKFLOW_OWN03": "published-workflow-id",
                "WORKFLOW_RENDER_API_URL": "http://render-worker.test/render",
            },
        ):
            workflows = [get_workflow(code) for code in ("OWN01", "OWN02", "OWN03")]

        for workflow in workflows:
            self.assertEqual(workflow["generation_mode"], "draft")
            self.assertEqual(workflow["status"], "online")
            self.assertEqual(
                {field["name"] for field in workflow["input_schema"]},
                {"theme"},
            )

    def test_published_god_job_renders_draft_key_on_windows_worker(self):
        key = {
            "kind": "jianying_draft_key",
            "meta": {"run_id": "published-job-test"},
            "draft": {"width": 1080, "height": 1920, "name": "西王母"},
            "calls": [
                {
                    "call_id": "caption",
                    "tool": "add_captions",
                    "params": {"captions": [{"text": "西王母", "start": 0, "end": 1_000_000}]},
                }
            ],
        }
        coze_response = MagicMock(status_code=200)
        coze_response.json.return_value = {
            "code": 0,
            "data": json.dumps(
                {"output": json.dumps({"draft_id": "remote-id", "draft_key": key}, ensure_ascii=False)},
                ensure_ascii=False,
            ),
        }
        coze_response.iter_lines.return_value = [
            "event: Message",
            "data: " + json.dumps(
                {
                    "content": coze_response.json.return_value["data"],
                    "content_type": "text",
                    "node_id": "900001",
                    "node_title": "End",
                    "node_is_finish": True,
                },
                ensure_ascii=False,
            ),
            "event: Done",
            "data: " + json.dumps({"debug_url": "https://example.test/debug"}),
        ]
        render_response = MagicMock(status_code=200)
        render_response.json.return_value = {
            "status": "success",
            "videos": ["http://render-worker.test/videos/job.mp4?signature=test"],
        }
        video_response = MagicMock(status_code=200)
        video_response.headers = {"Content-Length": "3"}
        video_response.iter_content.return_value = [b"mp4"]

        with (
            patch.dict(
                os.environ,
                {
                    "COZE_API_TOKEN": "test-token",
                    "COZE_WORKFLOW_OWN03": "published-workflow-id",
                    "COZE_USE_ENV_PROXY": "true",
                    "MIHE_KEY": "test-mihe-key",
                    "WORKFLOW_RENDER_API_URL": "http://render-worker.test/render",
                    "WORKFLOW_RENDER_API_TOKEN": "render-token",
                },
            ),
            patch.object(workflow_jobs.requests, "post", side_effect=[coze_response, render_response]) as post,
            patch.object(workflow_jobs.requests, "get", return_value=video_response) as get,
        ):
            created = self.client.post(
                "/api/v1/jobs",
                json={
                    "workflow_code": "OWN03",
                    "category": "自有工作流",
                    "inputs": {"god_name": "西王母", "scene_count": 1},
                },
            )

            self.assertEqual(created.status_code, 202, created.text)
            job_id = created.json()["job"]["id"]
            job = self.client.get(f"/api/v1/jobs/{job_id}").json()["job"]
            self.assertEqual(job["status"], "succeeded", job)
            self.assertEqual(job["results"][0]["type"], "video")
            self.assertTrue(job["results"][0]["url"].endswith(".mp4"))
            downloaded = self.client.get(job["results"][0]["url"])
            self.assertEqual(downloaded.status_code, 200)
            self.assertEqual(downloaded.headers["content-type"], "video/mp4")
            self.assertEqual(downloaded.content, b"mp4")
            render_call = post.call_args_list[1]
            self.assertEqual(render_call.kwargs["json"]["draft_key"], key)
            self.assertEqual(render_call.kwargs["headers"]["Authorization"], "Bearer render-token")
            get.assert_called_once_with(
                "http://render-worker.test/videos/job.mp4?signature=test",
                stream=True,
                timeout=(20, 1800),
            )

    def test_new_frontend_can_render_uploaded_draft_key_to_hosted_mp4(self):
        key = {
            "kind": "jianying_draft_key",
            "meta": {"run_id": "frontend-direct-export"},
            "draft": {"width": 1080, "height": 1920, "name": "直接导出"},
            "calls": [
                {
                    "call_id": "caption",
                    "tool": "add_captions",
                    "params": {"captions": [{"text": "直接导出", "start": 0, "end": 1_000_000}]},
                }
            ],
        }
        render_response = MagicMock(status_code=200)
        render_response.json.return_value = {
            "status": "success",
            "videos": ["http://render-worker.test/videos/direct.mp4?signature=test"],
        }
        video_response = MagicMock(status_code=200)
        video_response.headers = {"Content-Length": "3"}
        video_response.iter_content.return_value = [b"mp4"]

        with tempfile.TemporaryDirectory(prefix="direct-draft-key-render-") as temporary:
            with (
                patch.dict(
                    os.environ,
                    {
                        "WORKFLOW_RENDER_API_URL": "http://render-worker.test/render",
                        "WORKFLOW_RENDER_API_TOKEN": "render-token",
                    },
                ),
                patch.object(workflow_jobs, "RESULT_DIR", Path(temporary)),
                patch.object(workflow_jobs.requests, "post", return_value=render_response) as post,
                patch.object(workflow_jobs.requests, "get", return_value=video_response),
            ):
                created = self.client.post("/api/v1/draft-key-renders", json={"draft_key": key})
                self.assertEqual(created.status_code, 202, created.text)
                job_id = created.json()["job"]["id"]
                job = self.client.get(f"/api/v1/jobs/{job_id}").json()["job"]
                self.assertEqual(job["workflow_code"], "DRAFT_KEY_EXPORT")
                self.assertEqual(job["status"], "succeeded", job)
                self.assertEqual(job["results"][0]["type"], "video")
                hosted = self.client.get(job["results"][0]["url"])
                self.assertEqual(hosted.status_code, 200)
                self.assertEqual(hosted.headers["content-type"], "video/mp4")
                self.assertEqual(hosted.content, b"mp4")
                self.assertEqual(post.call_args.kwargs["json"]["draft_key"], key)

    def test_reference_workflow_json_is_public_and_packages_are_member_only(self):
        selected = [
            ("起号", "G259"), ("起号", "G258"), ("起号", "G168"), ("起号", "G45"),
            ("电商", "G263"), ("养生", "G129"), ("减肥", "G159"), ("财经", "G222"),
        ]
        download_root = Path(__file__).resolve().parents[1] / "downloads" / "reference_workflows"

        anonymous = TestClient(app)
        self.assertEqual(
            anonymous.get("/api/v1/workflows/G259/downloads", params={"category": "起号"}).status_code,
            401,
        )
        public_json = anonymous.get("/api/v1/workflows/G259/download/json", params={"category": "起号"})
        self.assertEqual(public_json.status_code, 200)
        self.assertEqual(public_json.json()["type"], "coze-workflow-clipboard-data")
        self.assertEqual(
            anonymous.get("/api/v1/workflows/G259/download/package", params={"category": "起号"}).status_code,
            401,
        )

        for category, code in selected:
            self.assertTrue((download_root / category / code / "workflow.json").is_file())
            listing = self.client.get(f"/api/v1/workflows/{code}/downloads", params={"category": category})
            self.assertEqual(listing.status_code, 200)
            self.assertEqual({item["kind"] for item in listing.json()["files"]}, {"json", "package"})
            for forbidden in ("attachment_token", "source_url", "feishu", "password"):
                self.assertNotIn(forbidden, listing.text.lower())

            json_file = self.client.get(f"/api/v1/workflows/{code}/download/json", params={"category": category})
            package = self.client.get(f"/api/v1/workflows/{code}/download/package", params={"category": category})
            self.assertEqual(json_file.status_code, 200)
            self.assertEqual(json_file.json()["type"], "coze-workflow-clipboard-data")
            self.assertEqual(package.status_code, 200)
            self.assertTrue(package.content.startswith(b"PK"))

        traversal = self.client.get("/api/v1/workflows/G259/download/json", params={"category": "../"})
        self.assertEqual(traversal.status_code, 404)

    def test_z_user_computer_can_pair_claim_and_return_native_mp4(self):
        pairing = self.client.post("/api/v1/render-devices/pairing-codes")
        self.assertEqual(pairing.status_code, 201, pairing.text)
        code = pairing.json()["code"]

        paired = TestClient(app).post(
            "/api/v1/render-agent/pair",
            json={
                "code": code,
                "name": "测试剪映电脑",
                "platform": "windows",
                "capabilities": {"jianying_native_export": True, "ffmpeg": False},
            },
        )
        self.assertEqual(paired.status_code, 200, paired.text)
        device_id = paired.json()["device_id"]
        token = paired.json()["device_token"]
        headers = {"Authorization": f"Bearer {token}"}

        repeated = TestClient(app).post(
            "/api/v1/render-agent/pair",
            json={"code": code, "name": "重复设备"},
        )
        self.assertEqual(repeated.status_code, 422)

        heartbeat = TestClient(app).post(
            "/api/v1/render-agent/heartbeat",
            headers=headers,
            json={"capabilities": {"jianying_native_export": True, "ffmpeg": False}},
        )
        self.assertEqual(heartbeat.status_code, 200, heartbeat.text)
        self.assertTrue(heartbeat.json()["device"]["online"])

        key = {
            "kind": "jianying_draft_key",
            "run_id": "device-agent-api-test",
            "draft": {"name": "设备导出测试", "width": 1080, "height": 1920, "fps": 30},
            "calls": [
                {
                    "call_id": "caption",
                    "tool": "add_captions",
                    "params": {"captions": [{"text": "本机导出", "start": 0, "end": 1_000_000}]},
                }
            ],
        }
        with tempfile.TemporaryDirectory(prefix="device-render-result-") as temporary:
            with (
                patch.dict(os.environ, {"WORKFLOW_RENDER_API_URL": ""}),
                patch.object(workflow_jobs, "RESULT_DIR", Path(temporary)),
                patch.object(fastapi_app, "RESULT_DIR", Path(temporary)),
            ):
                created = self.client.post("/api/v1/draft-key-renders", json={"draft_key": key})
                self.assertEqual(created.status_code, 202, created.text)
                job_id = created.json()["job"]["id"]
                waiting = self.client.get(f"/api/v1/jobs/{job_id}").json()["job"]
                self.assertEqual(waiting["status"], "rendering", waiting)
                self.assertEqual(waiting["stage"], "waiting_for_device")

                claimed = TestClient(app).post("/api/v1/render-agent/claim", headers=headers)
                self.assertEqual(claimed.status_code, 200, claimed.text)
                self.assertEqual(claimed.json()["task"]["job_id"], job_id)
                self.assertEqual(claimed.json()["task"]["draft_key"], key)

                mp4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
                completed = TestClient(app).post(
                    f"/api/v1/render-agent/jobs/{job_id}/complete",
                    headers=headers,
                    files={"video": ("result.mp4", mp4, "video/mp4")},
                )
                self.assertEqual(completed.status_code, 200, completed.text)
                self.assertEqual(completed.json()["job"]["status"], "succeeded")
                result_url = completed.json()["job"]["results"][0]["url"]
                hosted = self.client.get(result_url)
                self.assertEqual(hosted.status_code, 200)
                self.assertEqual(hosted.content, mp4)

                failed_created = self.client.post("/api/v1/draft-key-renders", json={"draft_key": key})
                self.assertEqual(failed_created.status_code, 202, failed_created.text)
                failed_job_id = failed_created.json()["job"]["id"]
                failed_claim = TestClient(app).post("/api/v1/render-agent/claim", headers=headers)
                self.assertEqual(failed_claim.status_code, 200, failed_claim.text)
                self.assertEqual(failed_claim.json()["task"]["job_id"], failed_job_id)
                with self.assertLogs("workflow.jobs", level="WARNING") as captured:
                    failed = TestClient(app).post(
                        f"/api/v1/render-agent/jobs/{failed_job_id}/fail",
                        headers=headers,
                        json={
                            "code": "device_render_failed",
                            "message": "剪映窗口在导出前意外关闭",
                        },
                    )
                self.assertEqual(failed.status_code, 200, failed.text)
                failed_job = failed.json()["job"]
                self.assertEqual(failed_job["status"], "failed")
                self.assertEqual(failed_job["error"]["code"], "device_render_failed")
                self.assertEqual(failed_job["error"]["message"], "剪映窗口在导出前意外关闭")
                self.assertIn("device_render_failed", "\n".join(captured.output))
                self.assertIn(failed_job_id, "\n".join(captured.output))

        removed = self.client.delete(f"/api/v1/render-devices/{device_id}")
        self.assertEqual(removed.status_code, 204, removed.text)
        self.assertEqual(TestClient(app).post("/api/v1/render-agent/heartbeat", headers=headers).status_code, 401)

    def test_public_schema_never_exposes_secret_inputs(self):
        response = self.client.get("/api/v1/workflows/G247", params={"category": "电商"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        names = {field["name"] for field in body["workflow"]["input_schema"]}
        self.assertEqual(names, {"name", "image"})
        serialized = response.text.lower()
        for secret_name in ("api_token", "st_api_key", "hs_api_key", "feishu_url", "attachment_token"):
            self.assertNotIn(secret_name, serialized)

    def test_g247_upload_and_inline_demo_job(self):
        upload = self.client.post(
            "/api/v1/assets",
            files={"file": ("shoe.png", b"\x89PNG\r\n\x1a\nworkflow-test", "image/png")},
        )
        self.assertEqual(upload.status_code, 201)
        asset_id = upload.json()["asset"]["id"]

        created = self.client.post(
            "/api/v1/jobs",
            json={
                "workflow_code": "G247",
                "category": "电商",
                "inputs": {"name": "轻量通勤鞋", "image": [asset_id]},
            },
        )
        self.assertEqual(created.status_code, 202)
        job_id = created.json()["job"]["id"]
        completed = self.client.get(f"/api/v1/jobs/{job_id}")
        self.assertEqual(completed.status_code, 200)
        job = completed.json()["job"]
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["results"][0]["type"], "image")
        self.assertNotIn("cost_cents", job)
        self.assertNotIn("price_cents", job)

    def test_g218_demo_result_and_job_records(self):
        g218 = self.client.post(
            "/api/v1/jobs",
            json={"workflow_code": "G218", "category": "养生", "inputs": {"title": "夏季养生", "num": 3}},
        )
        self.assertEqual(g218.status_code, 202)
        g218_job = self.client.get(f"/api/v1/jobs/{g218.json()['job']['id']}").json()["job"]
        self.assertEqual(g218_job["status"], "succeeded")
        self.assertEqual(g218_job["results"][0]["type"], "image")

        records = self.client.get("/api/v1/jobs")
        self.assertEqual(records.status_code, 200)
        self.assertGreaterEqual(records.json()["total"], 2)
        self.assertIn("created_at", records.json()["items"][0])
        self.assertNotIn("inputs", records.json()["items"][0])
        filtered = self.client.get(
            "/api/v1/jobs",
            params={"status": "succeeded", "workflow_code": "G218"},
        )
        self.assertEqual(filtered.status_code, 200)
        self.assertGreaterEqual(filtered.json()["total"], 1)
        self.assertTrue(
            all(item["workflow_code"] == "G218" for item in filtered.json()["items"])
        )
        self.assertEqual(
            next(
                item
                for item in filtered.json()["items"]
                if item["id"] == g218_job["id"]
            )["display_title"],
            "夏季养生",
        )
        self.assertNotIn("inputs", filtered.text)
        self.assertNotIn("draft_key", filtered.text)
        invalid_filter = self.client.get("/api/v1/jobs", params={"status": "unknown"})
        self.assertEqual(invalid_filter.status_code, 422)

    def test_all_selected_reference_workflows_build_topic_json(self):
        examples = [
            ("起号", "G259", "中彩票五百万的一生", {"biaoti": "中彩票五百万的一生"}),
            ("起号", "G258", "孩子写作业拖拉怎么办", {"biaoti": "孩子写作业拖拉怎么办"}),
            ("起号", "G168", "重生后成为商业大亨", {"text": "重生后成为商业大亨"}),
            ("起号", "G45", "停止精神内耗", {"title": "停止精神内耗"}),
            ("电商", "G263", "夏季防晒衣", {"subject": "夏季防晒衣", "name": "夏季防晒衣"}),
            ("养生", "G129", "夏季祛湿", {"theme": "夏季祛湿"}),
            ("减肥", "G159", "坚持运动第30天", {"title": "坚持运动第30天"}),
            ("财经", "G222", "蜜雪冰城商业模式", {"business": "蜜雪冰城商业模式"}),
        ]
        for category, code, theme, expected_defaults in examples:
            created = self.client.post(
                "/api/v1/jobs",
                json={"workflow_code": code, "category": category, "inputs": {"theme": theme}},
            )
            self.assertEqual(created.status_code, 202, created.text)
            job = self.client.get(f"/api/v1/jobs/{created.json()['job']['id']}").json()["job"]
            self.assertEqual(job["status"], "succeeded", job)
            self.assertEqual(job["results"][0]["type"], "draft")
            result = self.client.get(job["results"][0]["url"])
            self.assertEqual(result.status_code, 200)
            payload = result.json()
            start = next(node for node in payload["json"]["nodes"] if str(node.get("type")) == "1")
            defaults = {item["name"]: item.get("defaultValue") for item in start["data"]["outputs"]}
            for name, value in expected_defaults.items():
                self.assertEqual(defaults[name], value)

    def test_catalog_supports_reference_sort_modes(self):
        for sort in ("newest", "favorites", "downloads", "views", "name"):
            response = self.client.get(
                "/api/v1/workflows",
                params={"category": "全部", "sort": sort, "page_size": 100},
            )
            self.assertEqual(response.status_code, 200)
            self.assertGreater(response.json()["total"], 0)

    def test_real_views_downloads_and_home_summary(self):
        before = self.client.get("/api/v1/workflows/G258", params={"category": "起号"}).json()["workflow"]
        first_views = before["stats"]["views"]
        repeated = self.client.get("/api/v1/workflows/G258", params={"category": "起号"}).json()["workflow"]
        self.assertEqual(repeated["stats"]["views"], first_views)

        catalog = self.client.get("/api/v1/workflows", params={"category": "起号"}).json()["items"]
        g258 = next(item for item in catalog if item["code"] == "G258")
        self.assertEqual(g258["stats"]["views"], first_views)

        downloads_before = g258["stats"]["downloads"]
        downloaded = self.client.get("/api/v1/workflows/G258/download/json", params={"category": "起号"})
        self.assertEqual(downloaded.status_code, 200)
        refreshed = self.client.get("/api/v1/workflows", params={"category": "起号"}).json()["items"]
        refreshed_g258 = next(item for item in refreshed if item["code"] == "G258")
        self.assertEqual(refreshed_g258["stats"]["downloads"], downloads_before + 1)

        summary = self.client.get("/api/v1/site-summary")
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["catalog"]["workflows"], 11)
        self.assertGreaterEqual(summary.json()["activity"]["downloads"], 1)

    def test_tts_catalog_never_returns_fictional_placeholder_voices(self):
        catalog = self.client.get("/api/v1/voices").json()
        self.assertNotIn("warm_female", {voice["id"] for voice in catalog["voices"]})
        if not catalog["voices"]:
            return
        generated = self.client.post(
            "/api/v1/tts",
            json={"voice_id": catalog["voices"][0]["id"], "text": "真实配音测试", "speed_ratio": 1},
        )
        self.assertEqual(generated.status_code, 201, generated.text)
        self.assertEqual(generated.json()["audio"]["message"], "ok")
        self.assertNotIn("placeholder", generated.text.lower())

    def test_validation_unknown_workflow_and_path_safety(self):
        missing = self.client.post(
            "/api/v1/jobs",
            json={"workflow_code": "G218", "category": "养生", "inputs": {"num": 2}},
        )
        self.assertEqual(missing.status_code, 422)

        unknown = self.client.post(
            "/api/v1/jobs",
            json={"workflow_code": "G246", "category": "电商", "inputs": {}},
        )
        self.assertEqual(unknown.status_code, 404)

        traversal = self.client.get("/api/v1/workflows/not-a-code/preview", params={"category": "../"})
        self.assertEqual(traversal.status_code, 404)

    def test_react_build_is_served_for_catalog_and_detail_routes(self):
        catalog = self.client.get("/business")
        detail = self.client.get("/business/workflows/G247?category=电商")
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual(detail.status_code, 200)
        self.assertIn("<div id=\"root\"></div>", catalog.text)


if __name__ == "__main__":
    unittest.main()
