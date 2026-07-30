import json
import os
import unittest
from unittest.mock import patch

from workflow_registry import (
    apply_workflow_input_defaults,
    configured_workflow_input_defaults,
)


class WorkflowInputDefaultsTests(unittest.TestCase):
    def test_loads_defaults_by_normalized_workflow_code(self):
        with patch.dict(
            os.environ,
            {
                "WORKFLOW_INPUT_DEFAULTS_JSON": json.dumps(
                    {"own03": {"scene_count": 12, "fengge": "水墨"}},
                    ensure_ascii=False,
                )
            },
            clear=False,
        ):
            result = configured_workflow_input_defaults()

        self.assertEqual(result["OWN03"]["scene_count"], 12)
        self.assertEqual(result["OWN03"]["fengge"], "水墨")

    def test_per_run_non_empty_inputs_override_defaults(self):
        with patch.dict(
            os.environ,
            {
                "WORKFLOW_INPUT_DEFAULTS_JSON": json.dumps(
                    {
                        "OWN03": {
                            "theme": "默认神名",
                            "scene_count": 12,
                            "voice_id": "default-voice",
                        }
                    },
                    ensure_ascii=False,
                )
            },
            clear=False,
        ):
            result = apply_workflow_input_defaults(
                "OWN03",
                {"theme": "哪吒", "scene_count": "", "voice_id": "selected-voice"},
            )

        self.assertEqual(
            result,
            {"theme": "哪吒", "scene_count": 12, "voice_id": "selected-voice"},
        )

    def test_invalid_json_falls_back_to_no_defaults(self):
        with patch.dict(
            os.environ,
            {"WORKFLOW_INPUT_DEFAULTS_JSON": "{broken"},
            clear=False,
        ):
            self.assertEqual(configured_workflow_input_defaults(), {})


if __name__ == "__main__":
    unittest.main()
