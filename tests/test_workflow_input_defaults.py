import json
import os
import unittest
from unittest.mock import patch

from workflow_registry import (
    apply_workflow_input_defaults,
    configured_workflow_input_defaults,
    runtime_input_schema,
)
from workflow_jobs import _provider_inputs


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

    def test_owned_workflow_runtime_schema_exposes_existing_fields(self):
        schema = runtime_input_schema({"code": "OWN03", "input_schema": []})

        self.assertEqual(
            [field["name"] for field in schema],
            ["shuliang", "yinse", "audio", "wenan", "fengge", "cankao"],
        )

    def test_cigarette_runtime_text_overrides_are_sent_to_provider(self):
        result = _provider_inputs(
            {
                "theme": "中华",
                "left": "左侧自定义",
                "left_top": "左上角自定义",
            },
            "OWN02",
        )

        self.assertEqual(result["xiangyan_name"], "中华")
        self.assertEqual(result["left"], "左侧自定义")
        self.assertEqual(result["left_top"], "左上角自定义")


if __name__ == "__main__":
    unittest.main()
