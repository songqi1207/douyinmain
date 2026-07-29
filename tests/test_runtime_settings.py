import tempfile
import unittest
from pathlib import Path

from utils.runtime_settings import update_dotenv_file


class RuntimeSettingsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
