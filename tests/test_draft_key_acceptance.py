import tempfile
import unittest
from pathlib import Path

from utils.draft_key_acceptance import build_draft_key_acceptance_report


class DraftKeyAcceptanceTests(unittest.TestCase):
    def test_flags_broken_font_and_missing_god_template_parts(self):
        with tempfile.TemporaryDirectory(prefix="draft-acceptance-") as temporary:
            key = {
                "kind": "jianying_draft_key",
                "meta": {"unresolved_segment_ids": ["remote-segment"]},
                "calls": [
                    {
                        "call_id": "slide_a",
                        "tool": "add_captions",
                        "params": {
                            "font": "???? Bold",
                            "captions": [{"text": "财神", "start": 0, "end": 1_000_000}],
                        },
                    }
                ],
            }
            report = build_draft_key_acceptance_report(
                key,
                {"draft_id": "TEST", "draft_dir": str(Path(temporary)), "warnings": []},
                profile="god",
            )

        checks = {item["id"]: item for item in report["checks"]}
        self.assertEqual(report["status"], "failed")
        self.assertEqual(checks["font_integrity"]["result"], "failed")
        self.assertEqual(checks["segment_refs"]["result"], "failed")
        self.assertEqual(checks["image_animations"]["result"], "warning")
        self.assertEqual(report["details"]["fonts"], {"???? Bold": 1})


if __name__ == "__main__":
    unittest.main()
