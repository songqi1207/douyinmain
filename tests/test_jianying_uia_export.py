import tempfile
import unittest
from pathlib import Path

from desktop_bridge.jianying_uia_export import (
    JianyingUIAError,
    _description_matcher,
    _draft_card_candidate_points,
    _first_draft_card_point,
    _resolve_export_path,
)


class _FakeControl:
    def __init__(self, description):
        self.description = description

    def GetPropertyValue(self, property_id):
        self.property_id = property_id
        return self.description


class JianyingUIAExportTests(unittest.TestCase):
    def test_full_description_matcher_uses_qml_property(self):
        exact = _description_matcher(
            "HomePageDraftTitle:ABC",
            exact=True,
        )
        partial = _description_matcher("MainWindowTitleBarExportBtn")
        control = _FakeControl("HomePageDraftTitle:ABC")

        self.assertTrue(exact(control, 2))
        self.assertFalse(exact(_FakeControl("HomePageDraftTitle:AB"), 2))
        self.assertTrue(
            partial(_FakeControl("prefix:MainWindowTitleBarExportBtn"), 2)
        )
        self.assertEqual(control.property_id, 30159)

    def test_export_path_accepts_file_or_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            direct = _resolve_export_path(
                str(root / "rendered.mp4"),
                "DRAFT-ID",
            )
            folder = _resolve_export_path(
                str(root) + "\\",
                "DRAFT-ID",
            )

            self.assertEqual(direct, (root / "rendered.mp4").resolve())
            self.assertEqual(folder, (root / "DRAFT-ID.mp4").resolve())

    def test_empty_export_path_is_rejected(self):
        with self.assertRaises(JianyingUIAError):
            _resolve_export_path("", "DRAFT-ID")

    def test_first_draft_card_coordinate_matches_legacy_click_point(self):
        self.assertEqual(
            _first_draft_card_point(100, 200, 2100, 1400),
            (610, 1130),
        )

    def test_draft_card_candidates_include_known_legacy_restart_point(self):
        self.assertIn(
            (770, 1046),
            _draft_card_candidate_points(100, 200, 2100, 1400),
        )


if __name__ == "__main__":
    unittest.main()
