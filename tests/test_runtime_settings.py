import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import routes.api as api_routes
from app import create_app
from utils.runtime_settings import update_dotenv_file


class RuntimeSettingsTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def test_update_dotenv_preserves_other_lines_and_removes_duplicate_key(self):
        with tempfile.TemporaryDirectory(prefix="runtime-settings-") as temporary:
            env_path = Path(temporary) / ".env"
            env_path.write_text(
                "# existing\nOTHER=value\nMIHE_KEY=old-one\nMIHE_KEY=old-two\n",
                encoding="utf-8",
            )
            update_dotenv_file(env_path, {"MIHE_KEY": "new key#1", "COZE_API_TOKEN": "pat_new"})
            content = env_path.read_text(encoding="utf-8")

        self.assertIn("# existing", content)
        self.assertIn("OTHER=value", content)
        self.assertEqual(content.count("MIHE_KEY="), 1)
        self.assertIn('MIHE_KEY="new key#1"', content)
        self.assertIn('COZE_API_TOKEN="pat_new"', content)

    def test_frontend_can_replace_keys_without_receiving_secret_values(self):
        with tempfile.TemporaryDirectory(prefix="runtime-settings-api-") as temporary:
            env_path = Path(temporary) / ".env"
            env_path.write_text("OTHER=keep\nMIHE_KEY=old-key-value\n", encoding="utf-8")
            with (
                patch.object(api_routes, "_SETTINGS_ENV_PATH", env_path),
                patch.dict(
                    os.environ,
                    {
                        "MIHE_KEY": "old-key-value",
                        "COZE_API_TOKEN": "old-token-value",
                        "COZE_WORKFLOW_OWN03": "1111111111111111111",
                    },
                ),
            ):
                response = self.client.post(
                    "/api/config",
                    json={
                        "mihe_key": "new-mihe-key-value",
                        "coze_api_token": "pat_new-coze-token",
                        "coze_workflow_own03": "7664662207942869032",
                    },
                )
                self.assertEqual(response.status_code, 200, response.text)
                payload = response.get_json()
                self.assertTrue(payload["success"])
                self.assertTrue(payload["mihe_key_configured"])
                self.assertTrue(payload["coze_api_token_configured"])
                self.assertTrue(payload["coze_workflow_own03_configured"])
                self.assertNotIn("new-mihe-key-value", response.text)
                self.assertNotIn("pat_new-coze-token", response.text)
                self.assertEqual(os.environ["MIHE_KEY"], "new-mihe-key-value")

                config_response = self.client.get("/api/config")
                config_payload = config_response.get_json()
                self.assertNotIn("mihe_key", config_payload)
                self.assertNotIn("coze_api_token", config_payload)

            saved = env_path.read_text(encoding="utf-8")
            self.assertIn('MIHE_KEY="new-mihe-key-value"', saved)
            self.assertIn('COZE_API_TOKEN="pat_new-coze-token"', saved)
            self.assertIn('COZE_WORKFLOW_OWN03="7664662207942869032"', saved)
            self.assertIn("OTHER=keep", saved)

    def test_remote_host_cannot_write_settings(self):
        response = self.client.post(
            "/api/config",
            json={"mihe_key": "should-not-be-written"},
            headers={"Host": "example.test"},
            environ_overrides={"REMOTE_ADDR": "203.0.113.8"},
        )
        self.assertEqual(response.status_code, 403)

    def test_non_local_browser_origin_cannot_write_local_settings(self):
        response = self.client.post(
            "/api/config",
            json={"mihe_key": "should-not-be-written"},
            headers={"Origin": "https://malicious.example"},
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
