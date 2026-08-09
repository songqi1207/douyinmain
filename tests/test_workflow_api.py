import hashlib
import base64
import inspect
import json
import os
import sqlite3
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
os.environ["DEFAULT_GENERATION_CREDITS"] = "10000"
os.environ["COZE_API_TOKEN"] = ""
os.environ["COZE_WORKFLOW_GOD"] = ""
os.environ["COZE_WORKFLOW_OWN01"] = ""
os.environ["COZE_WORKFLOW_OWN02"] = ""
os.environ["COZE_WORKFLOW_OWN03"] = ""
os.environ["MIHE_KEY"] = ""
os.environ["PASSWORD_VAULT_KEY"] = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")

from fastapi.testclient import TestClient

import fastapi_app
from fastapi_app import app
import workflow_jobs
from workflow_jobs import _post_coze_workflow, _provider_inputs, _run_coze
from workflow_registry import get_workflow, runtime_input_schema


class WorkflowApiTests(unittest.TestCase):
    def test_device_progress_stage_does_not_regress_during_export(self):
        job = {
            "id": "job-stage-test",
            "status": "rendering",
            "stage": "device_exporting",
            "progress": 92,
            "render_device_id": "device-stage-test",
        }
        with (
            patch.object(workflow_jobs, "get_job", return_value=job),
            patch.object(workflow_jobs, "_update_job") as update_job,
            patch.object(workflow_jobs, "append_job_log"),
        ):
            reported = workflow_jobs.report_device_render_progress(
                job["id"],
                "device-stage-test",
                stage="device_preparing",
                progress=92,
                message="剪映正在生成 MP4 文件…",
            )

        self.assertTrue(reported)
        self.assertEqual(update_job.call_args.kwargs["stage"], "device_exporting")
        self.assertEqual(update_job.call_args.kwargs["progress"], 92)

    def test_update_job_persists_resolved_inputs(self):
        job = workflow_jobs.create_job("G45", "起号", {"theme": "原始主题"})

        workflow_jobs._update_job(
            job["id"],
            inputs_json=json.dumps({"theme": "更新主题", "author": "作者"}, ensure_ascii=False),
        )

        self.assertEqual(
            workflow_jobs.get_job(job["id"])["inputs"],
            {"theme": "更新主题", "author": "作者"},
        )

    def test_runtime_voice_inputs_use_concrete_voice_names(self):
        with patch.dict(
            os.environ,
            {
                "COZE_VOICE_OPTIONS_JSON": json.dumps(
                    [
                        {"label": "爽快思思 / Skye", "value": "7620288417930297386"},
                        {"label": "自定义音色", "value": "voice-custom"},
                    ],
                    ensure_ascii=False,
                )
            },
        ):
            schema = runtime_input_schema({"code": "OWN03", "input_schema": []})

        voice = next(field for field in schema if field["name"] == "yinse")
        self.assertEqual(voice["label"], "默认配音音色")
        self.assertEqual(voice["type"], "select")
        self.assertGreaterEqual(len(voice["options"]), 42)
        self.assertIn(
            {"label": "悬疑解说", "value": "7468512265134932019"},
            voice["options"],
        )
        self.assertIn(
            {"label": "自定义音色", "value": "voice-custom"},
            voice["options"],
        )

    def test_public_job_message_hides_provider_internals(self):
        message = workflow_jobs._public_job_message(
            "开始调用扣子工作流（workflow_id=7664842340859691042，草稿生成第 1/2 次），"
            "扣子已响应（HTTP 200），draft_key 已生成"
        )

        for forbidden in ("扣子", "Coze", "coze", "workflow_id", "draft_key", "HTTP 200"):
            self.assertNotIn(forbidden, message)
        self.assertIn("内容生成服务", message)
        self.assertIn("视频草稿", message)
        self.assertEqual(
            workflow_jobs._public_job_message("incomplete_draft_key"),
            "incomplete_draft_key",
        )

    def test_coze_end_stream_event_is_not_shown_as_user_node_log(self):
        response = MagicMock()
        response.iter_lines.return_value = [
            "event: Message",
            "data: " + json.dumps(
                {
                    "content": json.dumps({"draft_key": {"calls": []}}, ensure_ascii=False),
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

        with (
            patch.object(workflow_jobs, "append_job_log") as append_log,
            patch.object(workflow_jobs, "_update_job"),
        ):
            result = workflow_jobs._read_coze_stream(response, job_id="job-id", workflow_code="OWN02")

        self.assertEqual(result, {"draft_key": {"calls": []}})
        logged_messages = [call.args[1] for call in append_log.call_args_list]
        self.assertNotIn("扣子节点开始：End", logged_messages)
        self.assertNotIn("扣子节点完成：End", logged_messages)
        self.assertEqual(logged_messages, ["内容生成完成，正在整理视频草稿"])

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
            self.assertIn("AI-Video-Creator-v1.4.77.exe", response.headers["content-disposition"])
            self.assertIn("no-store", response.headers["cache-control"])
            self.assertEqual(response.headers["x-helper-version"], "1.4.77")
            self.assertEqual(
                response.headers["x-content-sha256"],
                hashlib.sha256(executable.read_bytes()).hexdigest(),
            )

    def test_render_status_exposes_latest_helper_version(self):
        response = self.client.get("/api/v1/draft-key-renders/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["latest_helper_version"], "1.4.77")

    def test_spa_index_must_revalidate_after_frontend_deploy(self):
        with tempfile.TemporaryDirectory(prefix="frontend-dist-") as temporary:
            frontend_dist = Path(temporary)
            (frontend_dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
            with patch.object(fastapi_app, "FRONTEND_DIST", frontend_dist):
                response = fastapi_app._spa_index()

        self.assertIn("no-cache", response.headers["cache-control"])
        self.assertIn("must-revalidate", response.headers["cache-control"])

    def test_compatible_jianying_download_uses_verified_official_cdn(self):
        response = fastapi_app.api_download_compatible_jianying()

        self.assertEqual(response.status_code, 307)
        self.assertEqual(
            response.headers["location"],
            "https://lf3-package.vlabstatic.com/obj/faceu-packages/"
            "Jianying_5_9_0_11632_jianyingpro_0_creatortool.exe",
        )
        self.assertEqual(response.headers["x-jianying-version"], "5.9.0.11632")
        self.assertEqual(
            response.headers["x-content-sha256"],
            "C0919B9A6D499FB8659DE3D314D25B10"
            "C7892F9072CB3AD00BEF62A89D13E399",
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

    def test_account_quota_is_private_and_admin_can_adjust_it(self):
        before = self.client.get("/api/v1/account/quota")
        self.assertEqual(before.status_code, 200, before.text)
        quota = before.json()["quota"]
        self.assertFalse(quota["unlimited"])
        self.assertEqual(quota["storage_limit_bytes"], 5 * 1024**3)
        self.assertEqual(TestClient(app).get("/api/v1/account/quota").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/admin/user-quotas").status_code, 403)

        adjusted = self.admin_client.put(
            f"/api/v1/admin/user-quotas/{quota['user']['id']}",
            json={"generation_delta": 3, "storage_limit_gb": 7},
        )
        self.assertEqual(adjusted.status_code, 200, adjusted.text)
        self.assertEqual(adjusted.json()["quota"]["generation_balance"], quota["generation_balance"] + 3)
        self.assertEqual(adjusted.json()["quota"]["storage_limit_bytes"], 7 * 1024**3)

        restored = self.admin_client.put(
            f"/api/v1/admin/user-quotas/{quota['user']['id']}",
            json={"generation_delta": -3, "storage_limit_gb": 5},
        )
        self.assertEqual(restored.status_code, 200, restored.text)

    def test_admin_can_reveal_and_reset_encrypted_user_password(self):
        from site_accounts import DB_PATH, authenticate_user, register_user

        created = register_user("vaultuser", "vault-password-123")
        endpoint = f"/api/v1/admin/users/{created['id']}/password"

        self.assertEqual(
            self.client.post(f"{endpoint}/reveal", json={"admin_password": "admin-test-password-123"}).status_code,
            403,
        )
        wrong_admin = self.admin_client.post(
            f"{endpoint}/reveal",
            json={"admin_password": "wrong-admin-password"},
        )
        self.assertEqual(wrong_admin.status_code, 403)

        revealed = self.admin_client.post(
            f"{endpoint}/reveal",
            json={"admin_password": "admin-test-password-123"},
        )
        self.assertEqual(revealed.status_code, 200, revealed.text)
        self.assertEqual(revealed.json()["password"], "vault-password-123")
        self.assertIn("no-store", revealed.headers["cache-control"])

        reset = self.admin_client.post(
            f"{endpoint}/reset",
            json={
                "admin_password": "admin-test-password-123",
                "new_password": "vault-password-456",
            },
        )
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(reset.json()["password"], "vault-password-456")
        self.assertIsNone(authenticate_user("vaultuser", "vault-password-123"))
        self.assertIsNotNone(authenticate_user("vaultuser", "vault-password-456"))

        with sqlite3.connect(DB_PATH) as db:
            actions = [row[0] for row in db.execute(
                "SELECT action FROM password_vault_audit WHERE target_user_id = ? ORDER BY created_at",
                (created["id"],),
            )]
        self.assertEqual(actions, ["reveal", "reset"])

    def test_admin_can_list_all_user_creations_while_user_cannot(self):
        user = self.client.get("/api/v1/auth/me").json()["user"]
        job = workflow_jobs.create_job(
            "G45",
            "起号",
            {"theme": "管理员全站记录测试主题"},
            user_id=user["id"],
            price_points=100,
        )

        self.assertEqual(self.client.get("/api/v1/admin/jobs").status_code, 403)
        response = self.admin_client.get(
            "/api/v1/admin/jobs",
            params={"q": "管理员全站记录测试主题", "user_id": user["id"]},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["summary"]["users"], 1)
        self.assertEqual(payload["items"][0]["id"], job["id"])
        self.assertEqual(payload["items"][0]["display_title"], "管理员全站记录测试主题")
        self.assertEqual(payload["items"][0]["user"]["email"], "workflow-user@example.test")
        self.assertNotIn("inputs", payload["items"][0])

    def test_admin_configures_double_cost_pricing_without_exposing_provider_breakdown(self):
        self.assertEqual(self.client.get("/api/v1/admin/workflow-pricing").status_code, 403)
        listing = self.admin_client.get("/api/v1/admin/workflow-pricing")
        self.assertEqual(listing.status_code, 200, listing.text)
        original = next(
            item["pricing"] for item in listing.json()["items"]
            if item["workflow"]["code"] == "OWN02"
        )
        updated = self.admin_client.put(
            "/api/v1/admin/workflow-pricing/OWN02",
            json={"coze_cost_points": 7, "mihe_cost_points": 3},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["pricing"]["provider_cost_points"], 10)
        self.assertEqual(updated.json()["pricing"]["price_points"], 20)

        public = self.client.get("/api/v1/workflows/OWN02?category=自有工作流")
        self.assertEqual(public.status_code, 200, public.text)
        public_pricing = public.json()["workflow"]["pricing"]
        self.assertEqual(public_pricing["price_points"], 20)
        self.assertNotIn("coze_cost_points", public_pricing)
        self.assertNotIn("mihe_cost_points", public_pricing)

        restored = self.admin_client.put(
            "/api/v1/admin/workflow-pricing/OWN02",
            json={
                "coze_cost_points": original["coze_cost_points"],
                "mihe_cost_points": original["mihe_cost_points"],
            },
        )
        self.assertEqual(restored.status_code, 200, restored.text)

    def test_job_result_files_require_owner_and_completed_status(self):
        user_id = self.client.get("/api/v1/auth/me").json()["user"]["id"]
        with tempfile.TemporaryDirectory(prefix="private-job-results-") as temporary:
            result_dir = Path(temporary)
            video_name = "private-result-device.mp4"
            draft_name = "private-result-draft-key.json"
            (result_dir / video_name).write_bytes(b"\x00\x00\x00\x18ftypmp42")
            (result_dir / draft_name).write_text('{"secret":"draft"}', encoding="utf-8")

            completed = workflow_jobs.create_job(
                "G218", "养生", {"title": "private video", "num": 3}, user_id=user_id
            )
            workflow_jobs._update_job(
                completed["id"],
                status="succeeded",
                stage="completed",
                progress=100,
                results_json=json.dumps(
                    [{"type": "video", "url": f"/api/v1/job-results/{video_name}"}]
                ),
            )
            rendering = workflow_jobs.create_job(
                "OWN01", "自有工作流", {"theme": "private draft"}, user_id=user_id
            )
            workflow_jobs._update_job(
                rendering["id"],
                status="rendering",
                stage="device_exporting",
                progress=92,
                results_json=json.dumps(
                    [{"type": "draft", "url": f"/api/v1/job-results/{draft_name}"}]
                ),
            )

            with (
                patch.object(workflow_jobs, "RESULT_DIR", result_dir),
                patch.object(fastapi_app, "RESULT_DIR", result_dir),
            ):
                self.assertEqual(self.client.get(f"/api/v1/job-results/{video_name}").status_code, 200)
                self.assertEqual(TestClient(app).get(f"/api/v1/job-results/{video_name}").status_code, 401)
                self.assertEqual(self.admin_client.get(f"/api/v1/job-results/{video_name}").status_code, 404)
                self.assertEqual(self.client.get(f"/api/v1/job-results/{draft_name}").status_code, 404)

            public_rendering = self.client.get(f"/api/v1/jobs/{rendering['id']}").json()["job"]
            self.assertEqual(public_rendering["results"], [])

            workflow_jobs._update_job(
                rendering["id"], status="succeeded", stage="completed", progress=100
            )
            public_completed_draft = self.client.get(f"/api/v1/jobs/{rendering['id']}").json()["job"]
            self.assertEqual(public_completed_draft["results"], [])
            self.assertEqual(self.client.get(f"/api/v1/job-results/{draft_name}").status_code, 404)

    def test_registration_notifies_admin_when_notification_inbox_is_configured(self):
        anonymous = TestClient(app)
        with patch.dict(
            os.environ,
            {"REGISTRATION_NOTIFICATION_EMAIL": "admin-alerts@example.test"},
        ), patch("fastapi_app.send_registration_application_received") as send_notification:
            application = anonymous.post(
                "/api/v1/auth/register",
                json={"email": "notify-admin@example.test"},
            )

        self.assertEqual(application.status_code, 202, application.text)
        send_notification.assert_called_once_with(
            "notify-admin@example.test",
            "http://127.0.0.1:8000/business/admin/registrations",
        )

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
            self.assertEqual(job["results"], [])

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

    def test_published_book_defaults_to_stable_booklist_pacing(self):
        with patch.dict(
            os.environ,
            {
                "BOOK_DEFAULT_IMAGE_COUNT": "",
                "BOOK_DEFAULT_VOICE_ID": "",
            },
            clear=False,
        ):
            params = _provider_inputs({"theme": "Book Title|Author Name"}, "OWN01")

        self.assertEqual(params["subject"], "Book Title")
        self.assertEqual(params["author"], "Author Name")
        self.assertEqual(params["img_count"], "10")

    def test_published_book_inline_author_replaces_placeholder_default(self):
        params = _provider_inputs(
            {"theme": "克林索尔的最后夏天｜黑塞", "author": "佚名"},
            "OWN01",
        )

        self.assertEqual(params["subject"], "克林索尔的最后夏天")
        self.assertEqual(params["author"], "黑塞")

    def test_published_book_removes_author_credit_suffix_before_workflow(self):
        params = _provider_inputs(
            {"theme": "\u7ea2\u697c\u68a6", "author": "\u66f9\u96ea\u82b9 \u8457\u8457"},
            "OWN01",
        )

        self.assertEqual(params["author"], "\u66f9\u96ea\u82b9")

    @patch("workflow_jobs._lookup_book_author", return_value="余华")
    def test_published_book_looks_up_missing_author(self, lookup_author):
        params = _provider_inputs({"theme": "活着", "author": "佚名"}, "OWN01")

        self.assertEqual(params["author"], "余华")
        lookup_author.assert_called_once_with("活着")

    def test_douban_book_suggestion_uses_exact_book_and_strips_country(self):
        author = workflow_jobs._douban_suggestion_author(
            "克林索尔的最后夏天",
            [
                {"title": "克林索尔的最后夏天", "type": "m", "author_name": "电影导演"},
                {"title": "克林索尔的最后夏天", "type": "b", "author_name": "[德] 赫尔曼·黑塞"},
            ],
        )

        self.assertEqual(author, "赫尔曼·黑塞")

    def test_published_book_replaces_encoding_damaged_default_author(self):
        with (
            patch.dict(os.environ, {"BOOK_DEFAULT_AUTHOR": "??"}),
            patch("workflow_jobs._lookup_book_author", return_value=""),
        ):
            params = _provider_inputs({"theme": "活着"}, "OWN01")

        self.assertEqual(params["subject"], "活着")
        self.assertEqual(params["author"], "佚名")

    def test_published_cigarette_replaces_encoding_damaged_corner_text(self):
        with patch.dict(
            os.environ,
            {
                "CIGARETTE_LEFT_TEXT": "????????",
                "CIGARETTE_LEFT_TOP_TEXT": "\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd",
            },
        ):
            params = _provider_inputs({"theme": "中华"}, "OWN02")

        self.assertEqual(params["left"], "未成年人禁止吸烟")
        self.assertEqual(params["left_top"], "吸烟有害身体健康")

    def test_incomplete_published_book_and_cigarette_drafts_are_rejected(self):
        for code, missing_id in (
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
                self.assertNotIn(missing_id, str(raised.exception))
                self.assertNotIn("缺少操作节点", str(raised.exception))
                self.assertIn("生成的视频草稿不完整", str(raised.exception))

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

    def test_empty_optional_book_body_images_are_kept_absent(self):
        required = workflow_jobs._EXPECTED_PUBLISHED_DRAFT_CALL_IDS["OWN01"]
        optional = workflow_jobs._OPTIONAL_PUBLISHED_DRAFT_CALL_IDS["OWN01"]
        key = {
            "calls": [
                {"call_id": call_id, "tool": "test", "params": {"items": [{}]}}
                for call_id in sorted(required - optional)
            ],
            "meta": {
                "unresolved_segment_ids": [],
                "skipped_empty_calls": [
                    {"call_id": call_id}
                    for call_id in sorted(optional)
                ],
            },
        }

        workflow_jobs._validate_published_draft_completeness(
            {"workflow_code": "OWN01"},
            key,
        )
        self.assertNotIn("call_191365", {call["call_id"] for call in key["calls"]})
        self.assertNotIn("call_300101", {call["call_id"] for call in key["calls"]})

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

    def test_published_book_draft_splits_long_captions_into_two_lines(self):
        original = (
            "活着，在我们中国的语言里充满了力量，它的力量不是来自于喊叫，"
            "也不是来自于进攻，而是忍受，去忍受生命赋予我们的责任，去忍受"
            "现实给予我们的幸福和苦难、无聊和平庸。"
        )
        style = {"font_size": 14, "text_color": "#ffffff", "in_animation": "打字机"}
        key = {
            "calls": [
                {
                    "call_id": "call_143757",
                    "tool": "add_captions",
                    "params": {
                        "captions": [
                            {
                                "text": original,
                                "start": 45_460_000,
                                "end": 63_124_000,
                                **style,
                            }
                        ]
                    },
                }
            ]
        }

        workflow_jobs._normalize_published_draft_key({"workflow_code": "OWN01"}, key)

        captions = key["calls"][0]["params"]["captions"]
        self.assertGreater(len(captions), 1)
        self.assertEqual(key["calls"][0]["params"]["transform_y"], -1200)
        self.assertEqual(captions[0]["start"], 45_460_000)
        self.assertEqual(captions[-1]["end"], 63_124_000)
        self.assertEqual("".join(item["text"].replace("\n", "") for item in captions), original)
        for previous, current in zip(captions, captions[1:]):
            self.assertEqual(previous["end"], current["start"])
        for caption in captions:
            lines = caption["text"].splitlines()
            self.assertLessEqual(len(lines), 2)
            self.assertTrue(all(0 < len(line) <= 9 for line in lines))
            self.assertEqual(caption["transform_y"], -1200)
            for key_name, value in style.items():
                self.assertEqual(caption[key_name], value)

    def test_published_book_draft_prefers_semantic_caption_breaks(self):
        text = "师徒四人，就像四季里的风，春的炽热，夏的温润，秋的深沉。"

        parts = workflow_jobs._own01_split_caption_text(text)

        self.assertEqual(
            parts,
            ["师徒四人，\n就像四季里的风，", "春的炽热，\n夏的温润，", "秋的深沉。"],
        )

    def test_published_cigarette_draft_repairs_question_mark_corner_text(self):
        key = {
            "calls": [
                {
                    "call_id": "call_273408",
                    "tool": "add_captions",
                    "params": {"captions": [{"text": "????????", "start": 0, "end": 1}]},
                },
                {
                    "call_id": "call_1733515",
                    "tool": "add_captions",
                    "params": {"captions": [{"text": "????????", "start": 0, "end": 1}]},
                },
            ]
        }
        with patch.dict(
            os.environ,
            {
                "CIGARETTE_LEFT_TEXT": "????????",
                "CIGARETTE_LEFT_TOP_TEXT": "????????",
            },
        ):
            workflow_jobs._normalize_published_draft_key(
                {"workflow_code": "OWN02"},
                key,
            )

        self.assertEqual(
            key["calls"][0]["params"]["captions"][0]["text"],
            "吸烟有害身体健康",
        )
        self.assertEqual(
            key["calls"][1]["params"]["captions"][0]["text"],
            "未成年人禁止吸烟",
        )

    def test_published_god_draft_bounds_image_entrance_animation_duration(self):
        key = {
            "calls": [
                {
                    "call_id": "main_images",
                    "tool": "add_images",
                    "params": {
                        "image_infos": [
                            {
                                "image_url": "https://example.test/scene.png",
                                "start": 22_500_000,
                                "end": 29_724_000,
                                "in_animation": "light_zoom",
                                "in_animation_duration": 7_224_000,
                            }
                        ]
                    },
                }
            ]
        }

        workflow_jobs._normalize_published_draft_key({"workflow_code": "OWN03"}, key)

        self.assertEqual(
            key["calls"][0]["params"]["image_infos"][0]["in_animation"],
            "light_zoom",
        )
        self.assertEqual(
            key["calls"][0]["params"]["image_infos"][0]["in_animation_duration"],
            7_224_000,
        )

        opening = {
            "calls": [
                {
                    "call_id": "intro_images",
                    "tool": "add_images",
                    "params": {
                        "image_infos": [{"in_animation": "Kira游动", "in_animation_duration": 800_000}]
                    },
                },
                {
                    "call_id": "main_images",
                    "tool": "add_images",
                    "params": {
                        "image_infos": [{"in_animation": "轻微放大", "in_animation_duration": 800_000}]
                    },
                },
                {"call_id": "camera_kf", "tool": "add_keyframes", "params": {"keyframes": []}},
            ]
        }
        workflow_jobs._normalize_published_draft_key({"workflow_code": "OWN03"}, opening)
        self.assertEqual(opening["calls"][0]["params"]["image_infos"][0]["in_animation"], "Kira游动")
        self.assertEqual(opening["calls"][1]["params"]["image_infos"][0]["in_animation"], "轻微放大")
        self.assertEqual([call["call_id"] for call in opening["calls"]], ["intro_images", "main_images", "camera_kf"])

        exported = {
            "meta": {"workflow": "神工作流_米核插件+draft_key记录"},
            "calls": [
                {"call_id": "camera_kf", "tool": "add_keyframes", "params": {"keyframes": []}},
                {"call_id": "opening_fx", "tool": "add_effects", "params": {"effect_infos": []}},
                {"call_id": "main_images", "tool": "add_images", "params": {"image_infos": [{"in_animation": "轻微放大", "in_animation_duration": 7_000_000}]}},
            ],
        }
        workflow_jobs._normalize_published_draft_key({"workflow_code": "DRAFT_KEY_EXPORT"}, exported)
        self.assertEqual(
            [call["call_id"] for call in exported["calls"]],
            ["camera_kf", "opening_fx", "main_images"],
        )
        exported_main = next(call for call in exported["calls"] if call["call_id"] == "main_images")
        self.assertEqual(exported_main["params"]["image_infos"][0]["in_animation"], "轻微放大")

    def test_published_god_maps_newer_image_animation_aliases(self):
        key = {
            "calls": [
                {
                    "call_id": "main_images",
                    "tool": "add_images",
                    "params": {
                        "image_infos": [
                            {"in_animation": "动感缩小", "start": 0, "end": 4_000_000},
                            {"in_animation": "轻微放大", "start": 4_000_000, "end": 8_000_000},
                        ]
                    },
                }
            ]
        }
        workflow_jobs._normalize_published_draft_key({"workflow_code": "OWN03"}, key)
        infos = key["calls"][0]["params"]["image_infos"]
        self.assertEqual([item["in_animation"] for item in infos], ["动感缩小", "轻微放大"])

    def test_published_god_tail_keeps_animation_metadata(self):
        key = {
            "calls": [
                {
                    "call_id": "main_images",
                    "tool": "add_images",
                    "params": {
                        "image_infos": [
                            {
                                "image_url": "https://example.test/scene.png",
                                "start": 0,
                                "end": 4_000_000,
                                "in_animation": "light_zoom",
                                "in_animation_duration": 4_000_000,
                                "out_animation": "fade",
                                "out_animation_duration": 800_000,
                            }
                        ]
                    },
                }
            ]
        }
        workflow_jobs._normalize_published_draft_key({"workflow_code": "OWN03"}, key)

        main = next(call for call in key["calls"] if call["call_id"] == "main_images")
        tail = next(call for call in key["calls"] if call["call_id"] == "main_tail_images")
        tail_info = tail["params"]["image_infos"][0]
        self.assertEqual(main["params"]["image_infos"][0]["end"], 1_500_000)
        self.assertEqual(tail_info["start"], 1_500_000)
        self.assertEqual(tail_info["end"], 4_000_000)
        self.assertEqual(tail_info["in_animation"], "light_zoom")
        self.assertEqual(tail_info["out_animation"], "fade")
        self.assertEqual(tail_info["in_animation_duration"], 2_500_000)
        self.assertEqual(tail_info["out_animation_duration"], 800_000)

    def test_published_god_repairs_existing_static_tail(self):
        key = {
            "calls": [
                {
                    "call_id": "main_images",
                    "tool": "add_images",
                    "params": {
                        "image_infos": [
                            {
                                "start": 0,
                                "end": 4_000_000,
                                "in_animation": "轻微放大",
                                "in_animation_duration": 4_000_000,
                                "in_animation_resource_id": "resource-main",
                                "in_animation_effect_id": "effect-main",
                            }
                        ]
                    },
                },
                {
                    "call_id": "main_tail_images",
                    "tool": "add_images",
                    "params": {
                        "image_infos": [{"start": 1_500_000, "end": 4_000_000}]
                    },
                },
            ]
        }
        workflow_jobs._normalize_published_draft_key({"workflow_code": "OWN03"}, key)

        tail = next(call for call in key["calls"] if call["call_id"] == "main_tail_images")
        tail_info = tail["params"]["image_infos"][0]
        self.assertEqual(tail_info["in_animation"], "轻微放大")
        self.assertEqual(tail_info["in_animation_resource_id"], "resource-main")
        self.assertEqual(tail_info["in_animation_effect_id"], "effect-main")
        self.assertEqual(tail_info["in_animation_duration"], 2_500_000)

    def test_draft_with_unrepaired_encoding_damaged_caption_is_rejected(self):
        key = {
            "meta": {"unresolved_segment_ids": []},
            "calls": [
                {
                    "call_id": "caption",
                    "tool": "add_captions",
                    "params": {
                        "captions": [
                            {"text": "标题???", "start": 0, "end": 1_000_000}
                        ]
                    },
                }
            ],
        }

        with self.assertRaises(workflow_jobs.ProviderError) as raised:
            workflow_jobs._validate_published_draft_completeness(
                {"workflow_code": "OWN03"},
                key,
            )

        self.assertEqual(raised.exception.code, "incomplete_draft_key")
        self.assertIn("字幕", str(raised.exception))

    def test_book_draft_does_not_reuse_intro_images_as_body_images(self):
        expected = workflow_jobs._EXPECTED_PUBLISHED_DRAFT_CALL_IDS["OWN01"]
        handwritten_ids = {"call_191365", "call_300101", "call_169833", "call_143757"}
        calls = [
            {"call_id": call_id, "tool": "add_audios", "params": {"audio_infos": [{}]}}
            for call_id in sorted(expected - handwritten_ids)
        ]
        calls.append(
            {
                "call_id": "call_169833",
                "tool": "add_images",
                "params": {
                    "image_infos": [
                        {
                            "image_url": "https://example.test/cover.png",
                            "start": 0,
                            "end": 1_000_000,
                            "width": 1024,
                            "height": 1024,
                        }
                    ]
                },
            }
        )
        calls.append(
            {
                "call_id": "call_143757",
                "tool": "add_captions",
                "params": {
                    "captions": [
                        {"text": "正文一", "start": 1_000_000, "end": 3_000_000},
                        {"text": "正文二", "start": 3_000_000, "end": 5_000_000},
                    ]
                },
            }
        )
        key = {
            "meta": {
                "unresolved_segment_ids": [],
                "skipped_empty_calls": [
                    {"call_id": "call_191365"},
                    {"call_id": "call_300101"},
                ],
            },
            "calls": calls,
        }

        workflow_jobs._repair_own01_missing_body_images(
            {"id": "", "workflow_code": "OWN01"},
            key,
        )
        workflow_jobs._validate_published_draft_completeness(
            {"workflow_code": "OWN01"},
            key,
        )

        repaired = {call["call_id"]: call for call in key["calls"]}
        self.assertNotIn("call_191365", repaired)
        self.assertNotIn("call_300101", repaired)
        self.assertNotIn("fallback_repaired_calls", key["meta"])

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

    def test_incomplete_owned_draft_is_generated_again_once(self):
        first_response = MagicMock(status_code=200)
        second_response = MagicMock(status_code=200)
        incomplete = workflow_jobs.ProviderError(
            "incomplete_draft_key",
            "缺少操作节点：call_175877",
        )
        completed_results = [{"type": "draft", "format": "draft_key"}]
        job = {
            "id": "incomplete-retry-test",
            "workflow_code": "OWN02",
            "category": "自有工作流",
            "inputs": {"theme": "中华"},
        }

        with (
            patch.dict(
                os.environ,
                {
                    "COZE_API_TOKEN": "test-token",
                    "COZE_WORKFLOW_OWN02": "published-cigarette-id",
                    "COZE_INCOMPLETE_DRAFT_ATTEMPTS": "2",
                },
            ),
            patch.object(
                workflow_jobs,
                "_post_coze_workflow",
                side_effect=[first_response, second_response],
            ) as post_workflow,
            patch.object(
                workflow_jobs,
                "_read_coze_stream",
                side_effect=[{"draft_key": "first"}, {"draft_key": "second"}],
            ),
            patch.object(
                workflow_jobs,
                "_save_draft_key_result",
                side_effect=[incomplete, completed_results],
            ) as save_result,
            patch.object(workflow_jobs, "_update_job"),
            patch.object(workflow_jobs, "append_job_log") as append_log,
            self.assertLogs("workflow.jobs", level="WARNING") as captured,
        ):
            results = _run_coze(job)

        self.assertEqual(results, completed_results)
        self.assertEqual(post_workflow.call_count, 2)
        self.assertEqual(save_result.call_count, 2)
        first_response.close.assert_called_once()
        second_response.close.assert_called_once()
        self.assertIn("coze_incomplete_draft_retry", "\n".join(captured.output))
        self.assertTrue(
            any(
                "自动重新生成" in call.args[1]
                for call in append_log.call_args_list
            )
        )

    def test_published_book_sandbox_end_error_retries_with_stable_image_count(self):
        first_response = MagicMock(status_code=200)
        second_response = MagicMock(status_code=200)
        sandbox_error = workflow_jobs.ProviderError(
            "provider_error",
            "request sandbox failed err:Cannot read properties of undefined (reading 'end')",
        )
        completed_results = [{"type": "draft", "format": "draft_key"}]
        job = {
            "id": "book-sandbox-retry-test",
            "workflow_code": "OWN01",
            "category": "自有工作流",
            "inputs": {"theme": "Book Title|Author Name"},
        }

        with (
            patch.dict(
                os.environ,
                {
                    "COZE_API_TOKEN": "test-token",
                    "COZE_WORKFLOW_OWN01": "published-book-id",
                    "COZE_INCOMPLETE_DRAFT_ATTEMPTS": "2",
                    "BOOK_DEFAULT_IMAGE_COUNT": "28",
                    "BOOK_FALLBACK_IMAGE_COUNT": "10",
                },
            ),
            patch.object(
                workflow_jobs,
                "_post_coze_workflow",
                side_effect=[first_response, second_response],
            ) as post_workflow,
            patch.object(
                workflow_jobs,
                "_read_coze_stream",
                side_effect=[sandbox_error, {"draft_key": "second"}],
            ),
            patch.object(
                workflow_jobs,
                "_save_draft_key_result",
                return_value=completed_results,
            ),
            patch.object(workflow_jobs, "_update_job"),
            patch.object(workflow_jobs, "append_job_log"),
        ):
            results = _run_coze(job)

        self.assertEqual(results, completed_results)
        self.assertEqual(post_workflow.call_count, 2)
        first_payload = post_workflow.call_args_list[0].kwargs["payload"]
        second_payload = post_workflow.call_args_list[1].kwargs["payload"]
        self.assertEqual(first_payload["parameters"]["img_count"], "28")
        self.assertEqual(second_payload["parameters"]["img_count"], "10")
        first_response.close.assert_called_once()
        second_response.close.assert_called_once()

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

    def test_workflow_template_draft_jobs_are_queued_for_device_rendering(self):
        key = {
            "kind": "jianying_draft_key",
            "meta": {"run_id": "workflow-template-device-render"},
            "draft": {"width": 1080, "height": 1920, "name": "模板草稿导出"},
            "calls": [
                {
                    "call_id": "caption",
                    "tool": "add_captions",
                    "params": {"captions": [{"text": "模板草稿导出", "start": 0, "end": 1_000_000}]},
                }
            ],
        }
        with tempfile.TemporaryDirectory(prefix="template-device-render-") as temporary:
            result_dir = Path(temporary)
            draft_file = result_dir / "own02-template-draft-key.json"
            draft_file.write_text(json.dumps(key, ensure_ascii=False), encoding="utf-8")
            job = {
                "id": "template-device-job",
                "workflow_code": "OWN02",
                "category": "自有工作流",
                "inputs": {"theme": "中华"},
                "render_device_id": "device-1",
            }
            results = [
                {
                    "type": "draft",
                    "format": "draft_key",
                    "url": f"/api/v1/job-results/{draft_file.name}",
                    "downloadable": True,
                }
            ]
            with (
                patch.object(workflow_jobs, "RESULT_DIR", result_dir),
                patch.object(workflow_jobs, "get_job", return_value=job),
                patch.object(workflow_jobs, "_update_job") as update_job,
                patch.object(workflow_jobs, "_run_local_workflow", return_value=results),
                patch.object(
                    workflow_jobs,
                    "get_workflow",
                    return_value={"output_type": "draft", "generation_mode": "workflow_template"},
                ),
                patch.object(workflow_jobs, "append_job_log"),
            ):
                workflow_jobs.execute_job(job["id"])

            self.assertTrue(
                any(
                    call.kwargs.get("status") == "rendering"
                    and call.kwargs.get("stage") == "waiting_for_device"
                    for call in update_job.call_args_list
                ),
                update_job.call_args_list,
            )

    def test_local_cigarette_workflow_outputs_importable_draft_key(self):
        with tempfile.TemporaryDirectory(prefix="local-cigarette-draft-key-") as temporary:
            result_dir = Path(temporary)
            job = {
                "id": "local-cigarette-job",
                "workflow_code": "OWN02",
                "category": "自有工作流",
                "inputs": {"theme": "中华"},
            }
            with (
                patch.object(workflow_jobs, "RESULT_DIR", result_dir),
                patch.object(workflow_jobs, "_update_job"),
                patch.object(workflow_jobs, "append_job_log"),
            ):
                results = workflow_jobs._run_local_workflow(job)

            self.assertEqual(results[0]["type"], "draft")
            self.assertEqual(results[0]["format"], "draft_key")
            saved = result_dir / Path(results[0]["url"]).name
            self.assertTrue(saved.is_file())
            key = json.loads(saved.read_text(encoding="utf-8"))
            self.assertEqual(key["kind"], "jianying_draft_key")
            self.assertTrue(key["calls"])
            self.assertIn("中华", saved.read_text(encoding="utf-8"))

    def test_local_cigarette_job_waits_for_device_export(self):
        with (
            patch.object(
                fastapi_app,
                "preferred_device",
                return_value={"id": "device-1", "name": "SONGQI", "online": True},
            ),
            patch.object(
                workflow_jobs,
                "get_workflow",
                return_value={
                    "status": "online",
                    "output_type": "draft",
                    "generation_mode": "workflow_template",
                    "input_schema": [{"name": "theme", "type": "text", "required": True}],
                },
            ),
            patch.object(
                fastapi_app,
                "get_workflow",
                return_value={
                    "status": "online",
                    "output_type": "draft",
                    "generation_mode": "workflow_template",
                    "input_schema": [{"name": "theme", "type": "text", "required": True}],
                },
            ),
        ):
            created = self.client.post(
                "/api/v1/jobs",
                json={
                    "workflow_code": "OWN02",
                    "category": "自有工作流",
                    "inputs": {"theme": "中华"},
                },
            )

        self.assertEqual(created.status_code, 202, created.text)
        job_id = created.json()["job"]["id"]
        job = self.client.get(f"/api/v1/jobs/{job_id}").json()["job"]
        self.assertEqual(job["status"], "rendering", job)
        self.assertEqual(job["stage"], "waiting_for_device", job)
        self.assertEqual(job["results"], [])

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

    def test_shared_admin_render_device_serves_ordinary_users_without_exposure(self):
        pairing = self.admin_client.post("/api/v1/render-devices/pairing-codes")
        self.assertEqual(pairing.status_code, 201, pairing.text)
        paired = TestClient(app).post(
            "/api/v1/render-agent/pair",
            json={
                "code": pairing.json()["code"],
                "name": "ADMIN-RENDER",
                "platform": "windows",
                "capabilities": {"jianying_native_export": True},
            },
        )
        self.assertEqual(paired.status_code, 200, paired.text)
        device_id = paired.json()["device_id"]
        headers = {"Authorization": f"Bearer {paired.json()['device_token']}"}
        heartbeat = TestClient(app).post(
            "/api/v1/render-agent/heartbeat",
            headers=headers,
            json={"capabilities": {"jianying_native_export": True}},
        )
        self.assertEqual(heartbeat.status_code, 200, heartbeat.text)

        try:
            status = self.client.get("/api/v1/draft-key-renders/status")
            self.assertEqual(status.status_code, 200, status.text)
            self.assertTrue(status.json()["configured"])
            self.assertTrue(status.json()["device_online"])
            self.assertTrue(status.json()["shared_device"])
            self.assertEqual(status.json()["devices"], [])
            self.assertEqual(self.client.get("/api/v1/render-devices").json()["items"], [])

            key = {
                "kind": "jianying_draft_key",
                "run_id": "shared-admin-device-test",
                "draft": {"name": "共享设备测试", "width": 1080, "height": 1920, "fps": 30},
                "calls": [
                    {
                        "call_id": "caption",
                        "tool": "add_captions",
                        "params": {"captions": [{"text": "共享设备", "start": 0, "end": 1_000_000}]},
                    }
                ],
            }
            created = self.client.post("/api/v1/draft-key-renders", json={"draft_key": key})
            self.assertEqual(created.status_code, 202, created.text)
            job_id = created.json()["job"]["id"]

            claimed = TestClient(app).post("/api/v1/render-agent/claim", headers=headers)
            self.assertEqual(claimed.status_code, 200, claimed.text)
            self.assertEqual(claimed.json()["task"]["job_id"], job_id)

            failed = TestClient(app).post(
                f"/api/v1/render-agent/jobs/{job_id}/fail",
                headers=headers,
                json={"code": "test_cleanup", "message": "测试完成"},
            )
            self.assertEqual(failed.status_code, 200, failed.text)
            self.assertEqual(self.client.get(f"/api/v1/jobs/{job_id}").json()["job"]["status"], "failed")
        finally:
            removed = self.admin_client.delete(f"/api/v1/render-devices/{device_id}")
            self.assertEqual(removed.status_code, 204, removed.text)

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
                self.assertIsNone(waiting["error"])

                claimed = TestClient(app).post("/api/v1/render-agent/claim", headers=headers)
                self.assertEqual(claimed.status_code, 200, claimed.text)
                self.assertEqual(claimed.json()["task"]["job_id"], job_id)
                self.assertEqual(claimed.json()["task"]["draft_key"], key)
                claimed_job = self.client.get(f"/api/v1/jobs/{job_id}").json()["job"]
                self.assertEqual(claimed_job["stage"], "device_preparing")
                self.assertEqual(claimed_job["progress"], 82)

                progress_report = TestClient(app).post(
                    f"/api/v1/render-agent/jobs/{job_id}/progress",
                    headers=headers,
                    json={
                        "stage": "device_draft_ready",
                        "progress": 85,
                        "message": "本机剪映草稿已经写入：ABC123",
                    },
                )
                self.assertEqual(progress_report.status_code, 200, progress_report.text)
                self.assertEqual(progress_report.json()["job"]["stage"], "device_draft_ready")
                self.assertEqual(progress_report.json()["job"]["progress"], 85)
                progress_logs = self.client.get(f"/api/v1/jobs/{job_id}/logs").json()["items"]
                self.assertIn("本机剪映草稿已经写入：ABC123", [item["message"] for item in progress_logs])

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
            self.assertEqual(job["results"], [])

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
