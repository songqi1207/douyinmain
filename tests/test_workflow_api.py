import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["WORKFLOW_DATA_DIR"] = tempfile.mkdtemp(prefix="workflow-api-tests-")
os.environ["WORKFLOW_PROVIDER_MODE"] = "demo"
os.environ["WORKFLOW_QUEUE_MODE"] = "inline"
os.environ["SITE_ADMIN_EMAIL"] = "admin@example.test"
os.environ["SITE_ADMIN_PASSWORD"] = "admin-test-password-123"
os.environ["SMTP_HOST"] = "smtp.example.test"
os.environ["SMTP_FROM"] = "noreply@example.test"

from fastapi.testclient import TestClient

from fastapi_app import app
from workflow_jobs import _provider_inputs


class WorkflowApiTests(unittest.TestCase):
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
            self.assertEqual(output_names, ["draft_key"])
            self.assertTrue(
                any(str(node.get("id")) == "300201" for node in result.json()["json"]["nodes"])
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
