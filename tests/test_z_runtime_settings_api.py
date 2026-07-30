"""Runtime settings API tests, ordered after the shared FastAPI fixture module."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import fastapi_app


WORKFLOWS = [
    {
        "code": "OWN01",
        "name": "书单视频",
        "category": "自有工作流",
        "input_schema": [{"name": "theme", "label": "书名", "type": "text", "required": True}],
    },
    {
        "code": "OWN03",
        "name": "神话视频",
        "category": "自有工作流",
        "input_schema": [{"name": "theme", "label": "神名", "type": "text", "required": True}],
    },
]


class RuntimeSettingsApiTests(unittest.TestCase):
    def test_settings_masks_secret_and_returns_workflow_ids(self):
        with (
            patch.object(fastapi_app, "_require_admin", return_value={"id": "admin"}),
            patch.object(fastapi_app, "list_workflows", return_value=WORKFLOWS),
            patch.dict(
                os.environ,
                {
                    "MIHE_KEY": "secret-key-1234",
                    "COZE_WORKFLOW_OWN01": "7654321098765432101",
                    "COZE_WORKFLOW_OWN03": "7654321098765432103",
                    "WORKFLOW_INPUT_DEFAULTS_JSON": json.dumps(
                        {"OWN03": {"scene_count": 12, "voice_id": "voice-1"}},
                        ensure_ascii=False,
                    ),
                },
                clear=False,
            ),
        ):
            result = fastapi_app.api_admin_runtime_settings(object())

        self.assertTrue(result["mihe_key"]["configured"])
        self.assertEqual(result["mihe_key"]["masked"], "••••1234")
        self.assertNotIn("secret-key-1234", json.dumps(result, ensure_ascii=False))
        self.assertEqual(result["workflows"][0]["workflow_id"], "7654321098765432101")
        self.assertEqual(result["workflows"][0]["input_schema"][0]["name"], "author")
        self.assertEqual(
            next(item for item in result["workflows"] if item["code"] == "OWN03")["input_defaults"],
            {"scene_count": 12, "voice_id": "voice-1"},
        )

    def test_update_persists_key_and_ids_and_syncs_god_alias(self):
        with tempfile.TemporaryDirectory(prefix="runtime-settings-api-") as temporary:
            env_path = Path(temporary) / ".env"
            env_path.write_text("OTHER=keep\nMIHE_KEY=old\n", encoding="utf-8")
            with (
                patch.object(fastapi_app, "_require_admin", return_value={"id": "admin"}),
                patch.object(fastapi_app, "RUNTIME_ENV_PATH", env_path),
                patch.object(fastapi_app, "list_workflows", return_value=WORKFLOWS),
                patch.dict(os.environ, {}, clear=False),
            ):
                result = fastapi_app.api_update_admin_runtime_settings(
                    object(),
                    {
                        "mihe_key": "new key#1234",
                        "workflow_ids": {
                            "OWN01": "7654321098765432101",
                            "OWN03": "7654321098765432103",
                        },
                        "workflow_inputs": {
                            "OWN01": {"scene_count": 8},
                            "OWN03": {"scene_count": 12, "voice_id": "voice-1"},
                        },
                    },
                )
                self.assertEqual(os.environ["MIHE_KEY"], "new key#1234")
                self.assertEqual(os.environ["COZE_WORKFLOW_OWN03"], "7654321098765432103")
                self.assertEqual(os.environ["COZE_WORKFLOW_GOD"], "7654321098765432103")
                self.assertEqual(
                    json.loads(os.environ["WORKFLOW_INPUT_DEFAULTS_JSON"])["OWN03"]["scene_count"],
                    12,
                )

            content = env_path.read_text(encoding="utf-8")

        self.assertIn("OTHER=keep", content)
        self.assertIn('MIHE_KEY="new key#1234"', content)
        self.assertIn('COZE_WORKFLOW_OWN01="7654321098765432101"', content)
        self.assertIn('COZE_WORKFLOW_GOD="7654321098765432103"', content)
        self.assertIn("WORKFLOW_INPUT_DEFAULTS_JSON=", content)
        self.assertEqual(result["mihe_key"]["masked"], "••••1234")

    def test_update_rejects_invalid_workflow_id(self):
        with (
            patch.object(fastapi_app, "_require_admin", return_value={"id": "admin"}),
            patch.object(fastapi_app, "list_workflows", return_value=WORKFLOWS),
        ):
            with self.assertRaises(HTTPException) as raised:
                fastapi_app.api_update_admin_runtime_settings(
                    object(),
                    {"workflow_ids": {"OWN01": "not-a-coze-id"}},
                )

        self.assertEqual(raised.exception.status_code, 422)

    def test_update_rejects_secret_inside_workflow_inputs(self):
        with (
            patch.object(fastapi_app, "_require_admin", return_value={"id": "admin"}),
            patch.object(fastapi_app, "list_workflows", return_value=WORKFLOWS),
        ):
            with self.assertRaises(HTTPException) as raised:
                fastapi_app.api_update_admin_runtime_settings(
                    object(),
                    {
                        "workflow_ids": {},
                        "workflow_inputs": {"OWN03": {"api_key": "must-not-be-returned"}},
                    },
                )

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail["code"], "sensitive_workflow_input")

    def test_settings_requires_admin(self):
        denied = HTTPException(status_code=403, detail={"code": "admin_required"})
        with patch.object(fastapi_app, "_require_admin", side_effect=denied):
            with self.assertRaises(HTTPException) as raised:
                fastapi_app.api_admin_runtime_settings(object())

        self.assertEqual(raised.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
