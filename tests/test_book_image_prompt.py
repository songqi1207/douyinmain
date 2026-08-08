import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BookImagePromptTests(unittest.TestCase):
    def test_generated_workflow_anchors_images_to_book_subject(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "book-workflow.json"
            subprocess.run(
                [
                    "node",
                    str(ROOT / "generate-book-template.js"),
                    "红楼梦",
                    "--author",
                    "曹雪芹",
                    "--out",
                    str(output),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            payload = json.loads(output.read_text(encoding="utf-8"))
            node = next(item for item in payload["json"]["nodes"] if item["id"] == "172269")
            params = node["data"]["inputs"]["inputParameters"]
            refs = {
                item["name"]: item["input"]["value"].get("content", {})
                for item in params
            }
            self.assertEqual(refs["subject"]["name"], "subject")
            self.assertEqual(refs["author"]["name"], "author")

            llm_params = {
                item["name"]: item["input"]["value"].get("content", "")
                for item in node["data"]["inputs"]["llmParam"]
            }
            self.assertIn("书名：{{subject}}", llm_params["prompt"])
            self.assertIn("作者：{{author}}", llm_params["prompt"])
            self.assertIn("具体人物、场景、物件或事件", llm_params["systemPrompt"])
            self.assertIn("不得串入其他作品", llm_params["systemPrompt"])
            self.assertNotIn("深刻理解哲学概念", llm_params["systemPrompt"])
            self.assertNotIn("featureless silhouette", llm_params["systemPrompt"])


if __name__ == "__main__":
    unittest.main()
