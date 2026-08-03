import tempfile
import unittest
from pathlib import Path

from desktop_bridge.jianying_uia_export import (
    _draft_search_query,
    JianyingUIAError,
    _description_matcher,
    _double_click_control,
    _draft_card_candidate_points,
    _export_field_points,
    _first_draft_card_point,
    _is_cross_process_jianying_popup,
    _popup_close_points,
    _resolve_export_path,
)


class _FakeControl:
    def __init__(self, description):
        self.description = description

    def GetPropertyValue(self, property_id):
        self.property_id = property_id
        return self.description


class _FakeClickableControl:
    def __init__(self, *, double_click_fails=False):
        self.double_click_fails = double_click_fails
        self.double_clicks = 0
        self.clicks = 0

    def DoubleClick(self, **_kwargs):
        self.double_clicks += 1
        if self.double_click_fails:
            raise RuntimeError("double click unavailable")

    def Click(self, **_kwargs):
        self.clicks += 1


class JianyingUIAExportTests(unittest.TestCase):
    def test_uuid_draft_search_uses_unique_prefix(self):
        self.assertEqual(
            _draft_search_query("EAB8433A-C232-4C5C-B10D-9EDCB3A5D69C"),
            "EAB",
        )
        self.assertEqual(_draft_search_query("神话故事草稿"), "神话故事草稿")

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

    def test_jianying_11_export_fields_have_coordinate_fallbacks(self):
        points = _export_field_points(0, 0, 960, 1080)

        self.assertEqual(points["title"], (801, 150))
        self.assertEqual(points["path"], (782, 209))
        self.assertEqual(points["confirm"], (761, 1040))

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

    def test_jianying_splash_dialog_can_be_closed_across_processes(self):
        self.assertTrue(_is_cross_process_jianying_popup("SplashDialog_QMLTYPE_481"))
        self.assertTrue(_is_cross_process_jianying_popup("LVInfoDialog_QMLTYPE_12"))
        self.assertFalse(_is_cross_process_jianying_popup("Popup_QMLTYPE_9"))
        self.assertFalse(_is_cross_process_jianying_popup("ExportWindow_QMLTYPE_3"))

    def test_popup_close_tries_title_bar_before_bottom_action(self):
        points = _popup_close_points(400, 200, 1200, 800)

        self.assertEqual(points[0], (1180, 224))
        self.assertEqual(points[1], (970, 745))

    def test_draft_card_uses_native_double_click(self):
        control = _FakeClickableControl()

        mode = _double_click_control(control)

        self.assertEqual(mode, "uia_double_click")
        self.assertEqual(control.double_clicks, 1)
        self.assertEqual(control.clicks, 0)

    def test_draft_card_falls_back_to_two_clicks(self):
        control = _FakeClickableControl(double_click_fails=True)

        mode = _double_click_control(control)

        self.assertEqual(mode, "uia_click_twice")
        self.assertEqual(control.double_clicks, 1)
        self.assertEqual(control.clicks, 2)


if __name__ == "__main__":
    unittest.main()
