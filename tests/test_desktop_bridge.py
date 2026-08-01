import hashlib
import base64
import inspect
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from desktop_bridge.core import (
    BridgeError,
    ensure_mihe_sync,
    export_mihe_server_draft_json,
    extract_draft_key,
    extract_mihe_draft_id,
    import_draft_payload,
    import_mihe_server_draft,
)
from desktop_bridge.device_agent import (
    _cloud_resource_wait_seconds,
    _prime_jianying_cloud_resources,
    _run_native_export,
    _run_pyjianying_export,
    normalize_site_url,
    pair_with_site,
)
from desktop_bridge.draft_core import (
    BridgeError as DraftCoreBridgeError,
    detect_jianying_version,
    prefer_newest_jianying_executable,
)
from desktop_bridge.paths import app_data_dir
from desktop_bridge.click_calibration import (
    normalize_export_click,
    normalize_export_confirm_click,
    valid_export_calibration,
    valid_export_confirm_calibration,
)
import desktop_bridge.app as bridge_app
from desktop_bridge.app import DraftBridgeApp
import desktop_bridge.windows_integration as windows_integration
import desktop_bridge.updater as updater
from desktop_bridge.windows_integration import parse_protocol_url


class DesktopBridgeTests(unittest.TestCase):
    def test_jianying_export_click_calibration_uses_relative_window_coordinates(self):
        calibration = normalize_export_click(1145, 17, (0, 0, 1280, 800))

        self.assertAlmostEqual(calibration["x_from_right_ratio"], 0.105469, places=6)
        self.assertAlmostEqual(calibration["y_from_top_ratio"], 0.02125, places=6)
        self.assertEqual(
            valid_export_calibration(calibration),
            {
                "x_from_right_ratio": calibration["x_from_right_ratio"],
                "y_from_top_ratio": calibration["y_from_top_ratio"],
            },
        )

    def test_jianying_export_click_calibration_rejects_unrelated_clicks(self):
        with self.assertRaises(ValueError):
            normalize_export_click(1400, 17, (0, 0, 1280, 800))
        self.assertIsNone(
            valid_export_calibration(
                {"x_from_right_ratio": 0.9, "y_from_top_ratio": 0.5}
            )
        )

    def test_jianying_export_confirm_calibration_uses_dialog_coordinates(self):
        calibration = normalize_export_confirm_click(762, 1040, (0, 0, 960, 1080))

        self.assertAlmostEqual(calibration["x_from_right_ratio"], 0.20625, places=6)
        self.assertAlmostEqual(calibration["y_from_bottom_ratio"], 0.037037, places=6)
        self.assertEqual(
            valid_export_confirm_calibration(calibration),
            {
                "x_from_right_ratio": calibration["x_from_right_ratio"],
                "y_from_bottom_ratio": calibration["y_from_bottom_ratio"],
            },
        )

    def test_load_settings_accepts_utf8_bom(self):
        with tempfile.TemporaryDirectory(prefix="helper-settings-bom-") as temporary:
            path = Path(temporary) / "settings.json"
            path.write_text('{"site_url": "http://example.test"}', encoding="utf-8-sig")
            with patch.object(bridge_app, "_settings_path", return_value=path):
                self.assertEqual(bridge_app._load_settings()["site_url"], "http://example.test")

    def test_background_start_hides_window_before_building_widgets(self):
        source = inspect.getsource(DraftBridgeApp.__init__)

        self.assertLess(source.index("self.root.withdraw()"), source.index("self._build_ui()"))

    def test_headless_helper_can_open_explicit_click_calibration(self):
        source = inspect.getsource(bridge_app.run_headless_agent)
        handler_source = inspect.getsource(DraftBridgeApp._handle_protocol_url)

        self.assertIn('get("action") == "calibrate"', source)
        self.assertIn("start_export_click_calibration", source)
        self.assertIn('action == "calibrate"', handler_source)

    @patch("pyJianYingDraft.JianyingController")
    def test_pyjianyingdraft_controller_exports_requested_draft(
        self,
        controller_type,
    ):
        with tempfile.TemporaryDirectory(prefix="pyjianying-controller-test-") as temporary:
            root = Path(temporary)
            executable = root / "JianyingPro.exe"
            output_path = root / "result.mp4"
            executable.write_bytes(b"exe")
            controller = controller_type.return_value

            class DraftNotFound(Exception):
                pass

            def write_export(_name, destination, **_kwargs):
                Path(destination).write_bytes(b"mp4")

            side_effect_items = [
                DraftNotFound("draft list is still loading"),
                None,
            ]

            def export_with_retry(*args, **kwargs):
                outcome = side_effect_items.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                write_export(*args, **kwargs)

            controller.export_draft.side_effect = export_with_retry

            with patch.dict(
                os.environ,
                {
                    "DEVICE_JIANYING_DRAFT_WAIT_SECONDS": "10",
                    "DEVICE_JIANYING_DRAFT_RETRY_SECONDS": "0",
                },
            ):
                result = _run_pyjianying_export(
                    "DRAFT-ID",
                    output_path,
                    executable,
                    900,
                    "job-id",
                )

            self.assertEqual(result.read_bytes(), b"mp4")
            self.assertEqual(controller.export_draft.call_count, 2)
            controller.export_draft.assert_called_with(
                "DRAFT-ID",
                str(output_path),
                timeout=900,
            )

    @patch("desktop_bridge.device_agent.time.sleep")
    @patch("desktop_bridge.device_agent.subprocess.Popen")
    @patch("pyJianYingDraft.JianyingController")
    def test_pyjianyingdraft_launch_enables_full_accessibility(
        self,
        controller_type,
        popen,
        _sleep,
    ):
        with tempfile.TemporaryDirectory(prefix="pyjianying-launch-test-") as temporary:
            root = Path(temporary)
            executable = root / "JianyingPro.exe"
            output_path = root / "result.mp4"
            executable.write_bytes(b"exe")
            controller = MagicMock()
            controller_type.side_effect = [
                RuntimeError("window not ready"),
                controller,
            ]

            def write_export(_name, destination, **_kwargs):
                Path(destination).write_bytes(b"mp4")

            controller.export_draft.side_effect = write_export

            result = _run_pyjianying_export(
                "DRAFT-ID",
                output_path,
                executable,
                900,
                "job-id",
            )

            self.assertEqual(result.read_bytes(), b"mp4")
            self.assertEqual(
                popen.call_args.args[0],
                [
                    str(executable),
                    "--force-renderer-accessibility",
                    "--enable-accessibility",
                ],
            )

    @patch("desktop_bridge.device_agent.subprocess.run")
    @patch("desktop_bridge.device_agent._run_pyjianying_export")
    @patch("desktop_bridge.device_agent.import_draft_payload")
    def test_native_export_uses_pyjianyingdraft_before_compatibility_driver(
        self,
        import_payload,
        run_pyjianying,
        run_compatibility_driver,
    ):
        with tempfile.TemporaryDirectory(prefix="pyjianying-primary-test-") as temporary:
            root = Path(temporary)
            draft_root = root / "drafts"
            output_root = root / "output"
            executable = root / "JianyingPro.exe"
            draft_root.mkdir()
            executable.write_bytes(b"exe")
            import_payload.return_value = {
                "draft_id": "DRAFT-ID",
                "draft_name": "DRAFT-ID",
                "draft_dir": str(draft_root / "DRAFT-ID"),
                "track_count": 2,
                "segment_count": 3,
                "warnings": [],
            }

            def write_primary_result(_name, output_path, *_args, **_kwargs):
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"mp4")
                return output_path

            run_pyjianying.side_effect = write_primary_result

            result = _run_native_export(
                {"job_id": "job-id", "draft_key": {"calls": []}},
                str(draft_root),
                str(executable),
                output_root,
            )

            self.assertEqual(result.read_bytes(), b"mp4")
            run_pyjianying.assert_called_once()
            run_compatibility_driver.assert_not_called()

    def test_cloud_resource_wait_scales_and_can_be_overridden(self):
        self.assertEqual(_cloud_resource_wait_seconds(0), 0)
        self.assertEqual(_cloud_resource_wait_seconds(1), 15)
        self.assertEqual(_cloud_resource_wait_seconds(100), 60)
        with patch.dict(
            os.environ,
            {"DEVICE_JIANYING_RESOURCE_WAIT_SECONDS": "27"},
        ):
            self.assertEqual(_cloud_resource_wait_seconds(100), 27)

    @patch("desktop_bridge.device_agent.time.sleep")
    def test_cloud_resource_preload_opens_draft_and_waits_in_editor(self, sleep):
        controller = MagicMock()
        controller.app_status = "home"
        draft_title = controller.app.TextControl.return_value
        draft_title.Exists.return_value = True
        draft_button = draft_title.GetParentControl.return_value

        def update_window_state():
            if draft_button.DoubleClick.called:
                controller.app_status = "edit"

        controller.get_window.side_effect = update_window_state

        result = _prime_jianying_cloud_resources(
            controller,
            "神话解说",
            22,
            "job-id",
        )

        self.assertTrue(result)
        draft_button.DoubleClick.assert_called_once()
        self.assertEqual(controller.switch_to_home.call_count, 2)
        sleep.assert_any_call(22)

    @patch("desktop_bridge.device_agent._run_pyjianying_export")
    @patch("desktop_bridge.device_agent.import_draft_payload")
    def test_native_export_stops_before_rendering_unresolved_cloud_resources(
        self,
        import_payload,
        run_pyjianying,
    ):
        with tempfile.TemporaryDirectory(prefix="unresolved-resource-test-") as temporary:
            root = Path(temporary)
            draft_root = root / "drafts"
            executable = root / "JianyingPro.exe"
            draft_root.mkdir()
            executable.write_bytes(b"exe")
            import_payload.return_value = {
                "draft_id": "DRAFT-ID",
                "draft_name": "DRAFT-ID",
                "draft_dir": str(draft_root / "DRAFT-ID"),
                "warnings": [],
                "unresolved_cloud_resources": ["font:不存在的字体"],
            }

            with self.assertRaises(DraftCoreBridgeError) as raised:
                _run_native_export(
                    {"job_id": "job-id", "draft_key": {"calls": []}},
                    str(draft_root),
                    str(executable),
                    root / "output",
                )

        self.assertIn("已停止导出", str(raised.exception))
        run_pyjianying.assert_not_called()

    @patch("desktop_bridge.device_agent._run_pyjianying_export")
    @patch("desktop_bridge.device_agent.import_draft_payload")
    def test_native_export_stops_before_rendering_failed_quality_checks(
        self,
        import_payload,
        run_pyjianying,
    ):
        with tempfile.TemporaryDirectory(prefix="quality-gate-test-") as temporary:
            root = Path(temporary)
            draft_root = root / "drafts"
            executable = root / "JianyingPro.exe"
            draft_root.mkdir()
            executable.write_bytes(b"exe")
            import_payload.return_value = {
                "draft_id": "DRAFT-ID",
                "draft_name": "DRAFT-ID",
                "draft_dir": str(draft_root / "DRAFT-ID"),
                "warnings": [],
                "quality_checks": {
                    "passed": False,
                    "issues": [
                        {
                            "code": "caption_voice_drift",
                            "message": "主字幕与人声结束时间相差 900ms",
                        }
                    ],
                },
            }

            with self.assertRaises(DraftCoreBridgeError) as raised:
                _run_native_export(
                    {"job_id": "job-id", "draft_key": {"calls": []}},
                    str(draft_root),
                    str(executable),
                    root / "output",
                )

        self.assertIn("主字幕与人声结束时间相差 900ms", str(raised.exception))
        run_pyjianying.assert_not_called()

    @patch(
        "desktop_bridge.device_agent._run_pyjianying_export",
        side_effect=BridgeError("primary failed"),
    )
    @patch("desktop_bridge.jianying_uia_export.export_draft_uia")
    @patch("desktop_bridge.device_agent.subprocess.run")
    @patch("desktop_bridge.device_agent.import_draft_payload")
    def test_hidden_qml_controls_fall_back_to_uia2(
        self,
        import_payload,
        run_legacy_export,
        export_uia2,
        run_pyjianying,
    ):
        with tempfile.TemporaryDirectory(prefix="uia2-fallback-test-") as temporary:
            root = Path(temporary)
            draft_root = root / "drafts"
            output_root = root / "output"
            executable = root / "JianyingPro.exe"
            draft_root.mkdir()
            executable.write_bytes(b"exe")
            import_payload.return_value = {
                "draft_id": "DRAFT-ID",
                "draft_name": "DRAFT-ID",
                "draft_dir": str(draft_root / "DRAFT-ID"),
                "track_count": 2,
                "segment_count": 3,
                "warnings": [],
            }
            run_legacy_export.side_effect = [
                MagicMock(
                    returncode=1,
                    stdout=(
                        "jianying_automation_stage "
                        "stage=ui_tree_unavailable action=restart_with_helper"
                    ),
                    stderr="",
                ),
                MagicMock(
                    returncode=1,
                    stdout=(
                        "jianying_automation_stage "
                        "stage=ui_tree_unavailable action=use_supported_jianying"
                    ),
                    stderr="",
                ),
            ]

            def write_uia2_result(_name, output_path, **_kwargs):
                target = Path(output_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"mp4")
                return target

            export_uia2.side_effect = write_uia2_result

            result = _run_native_export(
                {"job_id": "job-id", "draft_key": {"calls": []}},
                str(draft_root),
                str(executable),
                output_root,
            )

            self.assertEqual(result.read_bytes(), b"mp4")
            run_pyjianying.assert_called_once()
            self.assertEqual(run_legacy_export.call_count, 2)
            self.assertIn(
                "-RestartExisting",
                run_legacy_export.call_args_list[1].args[0],
            )
            export_uia2.assert_called_once()

    @patch(
        "desktop_bridge.device_agent.detect_jianying_version",
        return_value="11.2.5.12345",
    )
    @patch("desktop_bridge.device_agent._run_pyjianying_export")
    @patch("desktop_bridge.device_agent.subprocess.run")
    @patch("desktop_bridge.device_agent.import_draft_payload")
    def test_modern_jianying_uses_restarted_compatibility_driver(
        self,
        import_payload,
        run_compatibility_export,
        run_pyjianying,
        _detect_version,
    ):
        with tempfile.TemporaryDirectory(prefix="modern-jianying-test-") as temporary:
            root = Path(temporary)
            draft_root = root / "drafts"
            output_root = root / "output"
            executable = root / "JianyingPro.exe"
            draft_root.mkdir()
            executable.write_bytes(b"exe")
            import_payload.return_value = {
                "draft_id": "DRAFT-ID",
                "draft_name": "DRAFT-ID",
                "draft_dir": str(draft_root / "DRAFT-ID"),
                "track_count": 2,
                "segment_count": 3,
                "warnings": [],
            }

            def complete_export(command, **_kwargs):
                output_path = Path(command[command.index("-OutputPath") + 1])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"mp4")
                return MagicMock(returncode=0, stdout="", stderr="")

            run_compatibility_export.side_effect = complete_export

            result = _run_native_export(
                {"job_id": "job-id", "draft_key": {"calls": []}},
                str(draft_root),
                str(executable),
                output_root,
            )

            self.assertEqual(result.read_bytes(), b"mp4")
            run_pyjianying.assert_not_called()
            self.assertIn("-RestartExisting", run_compatibility_export.call_args.args[0])
            command = run_compatibility_export.call_args.args[0]
            self.assertEqual(command[command.index("-ResourceWaitSeconds") + 1], "0")

    def test_jianying_automation_uses_full_description_controls(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "run_jianying_export_automation.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn("LookupById(30159)", script)
        self.assertIn("HomePageDraftTitle:$DraftName", script)
        self.assertIn("MainWindowTitleBarExportBtn", script)
        self.assertIn("ExportOkBtn", script)
        self.assertIn("ui_snapshot_finished", script)
        self.assertIn("--force-renderer-accessibility", script)
        self.assertIn("ui_tree_unavailable", script)
        self.assertIn('Write-Stage "restarting_existing_jianying"', script)
        self.assertIn('Write-Stage "jianying_minimized"', script)
        self.assertIn('Write-Stage "cloud_resource_sync_wait_started"', script)
        self.assertIn('Minimize-JianyingWindow $process "cloud_resource_sync"', script)
        self.assertIn('Write-Stage "editor_export_coordinate_click"', script)
        self.assertIn('Write-Stage "editor_export_control_point_click"', script)
        self.assertIn('Write-Stage "editor_export_control_click_unverified"', script)
        self.assertIn("Test-RealExportDialog", script)
        self.assertIn("$rect.Width -lt 420", script)
        self.assertIn("SetProcessDpiAwarenessContext", script)
        self.assertIn('Write-Stage "physical_click_sent"', script)
        self.assertIn('Write-Stage "slow_physical_click_sent"', script)
        self.assertIn("Invoke-ExportConfirmationReliably", script)
        self.assertIn('Write-Stage "export_confirm_accepted"', script)
        self.assertIn('Write-Stage "export_confirm_not_accepted"', script)
        self.assertIn('Write-Stage "window_click_sent"', script)
        self.assertIn('Write-Stage "editor_export_calibration_loaded"', script)
        self.assertIn('Write-Stage "draft_search_applied"', script)
        self.assertIn("$height * 0.672", script)
        self.assertIn("$Query.Substring(0, 8)", script)
        self.assertIn('Write-Stage "export_confirm_calibration_loaded"', script)
        self.assertIn("$width * 0.105", script)
        self.assertIn("$height * 0.023", script)
        self.assertIn('Write-Stage "export_confirm_control_ready"', script)
        self.assertIn('Write-Stage "export_confirm_coordinate_click"', script)
        self.assertIn("$centerY -ge ($exportRect.Y + ($exportRect.Height * 0.55))", script)
        self.assertNotIn("$confirm = Get-VisibleElements $process.Id", script)
        self.assertIn("$width * 0.20", script)
        self.assertIn("$height * 0.038", script)
        uia_source = (
            Path(__file__).resolve().parents[1]
            / "desktop_bridge"
            / "jianying_uia_export.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn(".SetTopmost()", uia_source)
        self.assertIn('"uia2_export_coordinate_click"', uia_source)
        self.assertIn('"uia2_export_control_point_click"', uia_source)
        self.assertIn("is_real_export_window", uia_source)
        self.assertIn("(rect[2] - rect[0]) < 420", uia_source)
        self.assertIn("_enable_dpi_awareness()", uia_source)
        self.assertIn('"uia2_export_window_message_click"', uia_source)
        self.assertIn('"uia2_export_calibration_loaded"', uia_source)
        self.assertIn('"uia2_draft_search_applied"', uia_source)
        self.assertIn('"uia2_export_confirm_calibration_loaded"', uia_source)
        device_agent_source = (
            Path(__file__).resolve().parents[1]
            / "desktop_bridge"
            / "device_agent.py"
        ).read_text(encoding="utf-8")
        self.assertIn("剪映主自动化最后阶段", device_agent_source)
        self.assertIn("width * 0.105", uia_source)
        self.assertIn("height * 0.023", uia_source)

    def test_renamed_helper_uses_an_independent_single_instance_lock(self):
        self.assertEqual(windows_integration.MUTEX_NAME, r"Local\AIVideoCreator.UserAgent")

    def test_new_product_data_directory_migrates_existing_pairing_settings(self):
        with tempfile.TemporaryDirectory(prefix="helper-data-migration-") as temporary:
            root = Path(temporary)
            legacy = root / "DouyinDraftBridge"
            legacy.mkdir()
            (legacy / "settings.json").write_text(
                json.dumps({"device_id": "paired-device"}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"APPDATA": str(root)}):
                current = app_data_dir()
            self.assertEqual(current.name, "AIVideoCreator")
            self.assertEqual(
                json.loads((current / "settings.json").read_text(encoding="utf-8"))["device_id"],
                "paired-device",
            )

    def test_pairs_outbound_device_agent_without_local_server(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "device_id": "device-1",
            "device_token": "secret-token",
            "name": "办公室电脑",
        }
        with (
            patch("desktop_bridge.device_agent.requests.post", return_value=response) as post,
            patch(
                "desktop_bridge.device_agent.detect_jianying_version",
                return_value="5.9.0.11632",
            ),
        ):
            with tempfile.TemporaryDirectory(prefix="jianying-version-") as temporary:
                executable = Path(temporary) / "JianyingPro.exe"
                executable.write_bytes(b"MZ")
                result = pair_with_site(
                    "https://example.test/business/",
                    "ABCD2345",
                    "办公室电脑",
                    str(executable),
                )
        self.assertEqual(normalize_site_url("https://example.test/business"), "https://example.test")
        self.assertEqual(result["site_url"], "https://example.test")
        self.assertEqual(result["device_token"], "secret-token")
        self.assertEqual(post.call_args.args[0], "https://example.test/api/v1/render-agent/pair")
        self.assertFalse(post.call_args.kwargs["json"]["capabilities"]["ffmpeg"])
        self.assertTrue(post.call_args.kwargs["json"]["capabilities"]["jianying_found"])
        self.assertEqual(
            post.call_args.kwargs["json"]["capabilities"]["jianying_version"],
            "5.9.0.11632",
        )

    def test_detects_jianying_version_from_versioned_install_folder(self):
        with tempfile.TemporaryDirectory(prefix="jianying-install-") as temporary:
            executable = (
                Path(temporary)
                / "JianyingPro"
                / "Apps"
                / "6.8.0.12345"
                / "JianyingPro.exe"
            )
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"MZ")
            self.assertEqual(detect_jianying_version(executable), "6.8.0.12345")

    def test_prefers_newer_installed_jianying_over_persisted_old_executable(self):
        with tempfile.TemporaryDirectory(prefix="jianying-upgrade-") as temporary:
            apps = Path(temporary) / "JianyingPro" / "Apps"
            old_executable = apps / "5.9.0.11632" / "JianyingPro.exe"
            new_executable = apps / "11.2.5.12345" / "JianyingPro.exe"
            old_executable.parent.mkdir(parents=True)
            new_executable.parent.mkdir(parents=True)
            old_executable.write_bytes(b"MZ")
            new_executable.write_bytes(b"MZ")

            selected = prefer_newest_jianying_executable(
                old_executable,
                [old_executable, new_executable],
            )

            self.assertEqual(selected, new_executable.resolve())

    @patch(
        "desktop_bridge.app.detect_jianying_executables",
    )
    @patch("desktop_bridge.app.detect_draft_roots", return_value=[])
    def test_default_paths_upgrade_persisted_jianying_path(
        self,
        _detect_roots,
        detect_executables,
    ):
        with tempfile.TemporaryDirectory(prefix="jianying-default-upgrade-") as temporary:
            apps = Path(temporary) / "JianyingPro" / "Apps"
            old_executable = apps / "5.9.0.11632" / "JianyingPro.exe"
            new_executable = apps / "11.2.5.12345" / "JianyingPro.exe"
            old_executable.parent.mkdir(parents=True)
            new_executable.parent.mkdir(parents=True)
            old_executable.write_bytes(b"MZ")
            new_executable.write_bytes(b"MZ")
            detect_executables.return_value = [new_executable, old_executable]

            _, selected = bridge_app._detected_default_paths(
                {"jianying_exe": str(old_executable)}
            )

            self.assertEqual(Path(selected), new_executable.resolve())

    def test_parses_browser_wake_protocol_without_executing_shell_text(self):
        parsed = parse_protocol_url(
            "douyin-draft://wake?site=https%3A%2F%2Fvideo.example.test&code=ABCD2345"
        )
        self.assertEqual(parsed["action"], "wake")
        self.assertEqual(parsed["site_url"], "https://video.example.test")
        self.assertEqual(parsed["pairing_code"], "ABCD2345")
        update = parse_protocol_url("douyin-draft://update?site=https%3A%2F%2Fvideo.example.test")
        self.assertEqual(update["action"], "update")
        self.assertEqual(update["site_url"], "https://video.example.test")
        self.assertEqual(parse_protocol_url("https://example.test"), {})

    def test_helper_update_downloads_verifies_and_launches_latest_exe(self):
        with tempfile.TemporaryDirectory(prefix="helper-update-") as temporary:
            root = Path(temporary)
            payload = b"MZ-new-helper"
            response = MagicMock()
            response.headers = {"X-Content-SHA256": hashlib.sha256(payload).hexdigest()}
            response.iter_content.return_value = [payload[:4], payload[4:]]
            response.__enter__.return_value = response
            response.__exit__.return_value = None

            with (
                patch.object(updater, "app_data_dir", return_value=root),
                patch.object(updater.requests, "get", return_value=response) as get,
                patch.object(updater.subprocess, "Popen") as popen,
            ):
                downloaded = updater.download_and_launch_update("https://video.example.test/business")

            self.assertTrue(downloaded.is_file())
            self.assertEqual(downloaded.read_bytes(), payload)
            get.assert_called_once_with(
                "https://video.example.test/api/v1/downloads/draft-bridge",
                stream=True,
                timeout=(20, 180),
            )
            response.raise_for_status.assert_called_once()
            self.assertEqual(popen.call_args.args[0], [str(downloaded), "--background"])

    def test_frozen_helper_self_installs_and_relaunches_from_user_directory(self):
        with tempfile.TemporaryDirectory(prefix="bridge-self-install-") as temporary:
            root = Path(temporary)
            source = root / "downloaded.exe"
            source.write_bytes(b"MZ-test-helper")
            installed = root / "installed"
            installed.mkdir()
            process = MagicMock()
            with (
                patch.object(windows_integration.os, "name", "nt"),
                patch.object(windows_integration.sys, "frozen", True, create=True),
                patch.object(windows_integration.sys, "executable", str(source)),
                patch.object(windows_integration, "install_dir", return_value=installed),
                patch.object(windows_integration, "_register_windows_integration") as register,
                patch.object(windows_integration, "_stop_other_installed_helpers") as stop_old,
                patch.object(windows_integration.subprocess, "Popen", return_value=process) as popen,
            ):
                relaunched = windows_integration.install_for_current_user([])
            self.assertTrue(relaunched)
            target = register.call_args.args[0]
            self.assertTrue(target.is_file())
            self.assertEqual(target.read_bytes(), source.read_bytes())
            stop_old.assert_called_once_with(target)
            self.assertEqual(popen.call_args.args[0], [str(target), "--background"])

    def test_browser_wake_pairs_in_background_without_confirmation_window(self):
        bridge = object.__new__(DraftBridgeApp)
        bridge.settings = {}
        bridge.background_mode = False
        bridge.hide_after_pairing = False
        bridge.site_url_var = MagicMock()
        bridge.pairing_code_var = MagicMock()
        bridge.device_status_var = MagicMock()
        bridge.root = MagicMock()
        bridge.start_pairing = MagicMock()

        bridge._handle_protocol_url(
            "douyin-draft://wake?"
            "site=https%3A%2F%2Fvideo.example.test&code=ABCD2345"
        )

        self.assertTrue(bridge.background_mode)
        self.assertTrue(bridge.hide_after_pairing)
        bridge.root.withdraw.assert_called_once()
        bridge.root.deiconify.assert_not_called()
        bridge.start_pairing.assert_called_once()

    def test_background_render_failure_stays_hidden(self):
        bridge = object.__new__(DraftBridgeApp)
        bridge.background_mode = True
        bridge.device_status_var = MagicMock()
        bridge.root = MagicMock()

        bridge._apply_device_status("剪映导出失败：测试错误")

        bridge.device_status_var.set.assert_called_once()
        bridge.root.deiconify.assert_not_called()

    def test_helper_upgrade_stops_only_older_installed_helper_builds(self):
        with tempfile.TemporaryDirectory(prefix="bridge-upgrade-test-") as temporary:
            installed = Path(temporary).resolve()
            target = installed / "AIVideoCreator-current.exe"
            with (
                patch.object(windows_integration.os, "name", "nt"),
                patch.object(windows_integration, "install_dir", return_value=installed),
                patch.object(windows_integration.subprocess, "run") as run,
                patch.object(windows_integration.time, "sleep"),
            ):
                windows_integration._stop_other_installed_helpers(target)

            command = run.call_args.args[0]
            encoded = command[command.index("-EncodedCommand") + 1]
            script = base64.b64decode(encoded).decode("utf-16le")
            self.assertIn(str(installed), script)
            self.assertIn(str(target), script)
            self.assertIn("AIVideoCreator-*.exe", script)
            self.assertIn("Stop-Process", script)

    def test_exports_raw_mihe_json_and_navigable_structure(self):
        with tempfile.TemporaryDirectory(prefix="mihe-export-test-") as temporary:
            payload = {
                "canvas_config": {"width": 1080, "height": 1920},
                "duration": 2_000_000,
                "materials": {
                    "videos": [{"id": "video-1", "path": "https://example.invalid/1.png", "type": "photo"}],
                    "video_effects": [{"id": "effect-1", "name": "glow"}],
                },
                "tracks": [
                    {
                        "id": "track-1",
                        "type": "video",
                        "segments": [
                            {
                                "id": "segment-1",
                                "material_id": "video-1",
                                "target_timerange": {"start": 0, "duration": 2_000_000},
                                "common_keyframes": [
                                    {"property_type": "KFTypePositionX", "keyframe_list": []}
                                ],
                            }
                        ],
                    }
                ],
            }
            report = export_mihe_server_draft_json(
                "fdee55ea-0ba9-484d-8e6a-1abcbaaad15b",
                output_dir=Path(temporary),
                server_payload=payload,
            )
            raw = json.loads(Path(report["raw_json_path"]).read_text(encoding="utf-8"))
            structure = json.loads(Path(report["structure_path"]).read_text(encoding="utf-8"))
            self.assertEqual(raw, payload)
            self.assertEqual(structure["track_count"], 1)
            self.assertEqual(structure["segment_count"], 1)
            segment = structure["tracks"][0]["segments"][0]
            self.assertEqual(segment["json_path"], "$.tracks[0].segments[0]")
            self.assertEqual(segment["material_json_path"], "$.materials.videos[0]")
            self.assertEqual(segment["keyframe_property_types"], ["KFTypePositionX"])

    def test_extracts_nested_coze_draft_key_string(self):
        key = {
            "kind": "jianying_draft_key",
            "meta": {"run_id": "nested-test"},
            "calls": [{"call_id": "image", "tool": "add_images", "params": {"image_infos": [{}]}}],
        }
        wrapped = {"data": {"output": {"draft_key": json.dumps(key, ensure_ascii=False)}}}
        self.assertEqual(extract_draft_key(wrapped), key)

    def test_rejects_payload_without_draft_key(self):
        with self.assertRaises(BridgeError):
            extract_draft_key({"status": "success"})

    def test_extracts_nested_mihe_draft_id(self):
        draft_id = "c7f3042a-6741-1bad-02a0-0f2ac1527e5f/36788c0f-70d0-4c8a-b77f-613c4173ff42"
        wrapped = {"data": {"output": {"draft_id": draft_id}}}
        self.assertEqual(extract_mihe_draft_id(wrapped), draft_id)

    def test_downloads_and_pins_official_mihe_sync_payload(self):
        with tempfile.TemporaryDirectory(prefix="mihe-sync-test-") as temporary:
            root = Path(temporary)
            payload = b"MZ" + (b"\0" * (1024 * 1024))
            archive = root / "source.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
                output.writestr("米核剪映小助手.exe", payload)
            archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
            executable_hash = hashlib.sha256(payload).hexdigest()
            install_dir = root / "installed"

            executable = ensure_mihe_sync(
                base_dir=install_dir,
                download_url="https://example.invalid/mihe.zip",
                archive_sha256=archive_hash,
                executable_sha256=executable_hash,
                downloader=lambda _url, destination: shutil.copyfile(archive, destination),
            )

            self.assertEqual(executable.read_bytes(), payload)
            self.assertTrue((install_dir / "source.json").is_file())
            cached = ensure_mihe_sync(
                base_dir=install_dir,
                archive_sha256=archive_hash,
                executable_sha256=executable_hash,
                downloader=lambda _url, _destination: self.fail("cached executable should not download again"),
            )
            self.assertEqual(cached, executable)

    def test_directly_imports_mihe_server_draft_and_keeps_json_backup(self):
        with tempfile.TemporaryDirectory(prefix="mihe-direct-test-") as temporary:
            root = Path(temporary)
            draft_id = "fdee55ea-0ba9-484d-8e6a-1abcbaaad15b"
            payload = {
                "canvas_config": {"width": 1080, "height": 1920, "ratio": "9:16"},
                "duration": 0,
                "materials": {
                    "audios": [{"id": "audio-1", "path": "https://example.invalid/a.mp3"}],
                    "videos": [
                        {
                            "id": "video-1",
                            "path": "https://example.invalid/i.png",
                            "type": "photo",
                            "local_id": "",
                        }
                    ],
                },
                "tracks": [
                    {
                        "type": "video",
                        "segments": [
                            {
                                "target_timerange": {"start": 0, "duration": 2_000_000},
                                "common_keyframes": [
                                    {"property_type": "KFTypePositionX", "keyframe_list": [{"time_offset": 0}]},
                                    {
                                        "property_type": "KFTypePositionX",
                                        "keyframe_list": [{"time_offset": 2_000_000}],
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }

            def fake_asset_download(_url: str, destination: Path) -> None:
                destination.write_bytes(b"asset")

            report = import_mihe_server_draft(
                draft_id,
                draft_root=root / "drafts",
                server_payload=payload,
                asset_downloader=fake_asset_download,
            )

            draft_dir = Path(report["draft_dir"])
            content = json.loads((draft_dir / "draft_content.json").read_text(encoding="utf-8"))
            backup = json.loads((draft_dir / "mihe_server_draft.json").read_text(encoding="utf-8"))
            self.assertEqual(report["method"], "mihe_direct_http")
            self.assertEqual(report["asset_count"], 2)
            self.assertEqual(content["duration"], 2_000_000)
            self.assertEqual(len(content["tracks"][0]["segments"][0]["common_keyframes"]), 1)
            self.assertTrue(Path(content["materials"]["audios"][0]["path"]).is_file())
            self.assertTrue(Path(content["materials"]["videos"][0]["path"]).is_file())
            self.assertEqual(backup["materials"]["audios"][0]["path"], "https://example.invalid/a.mp3")
            self.assertTrue((root / "drafts" / "root_meta_info.json").is_file())

    def test_imports_and_verifies_local_draft(self):
        with tempfile.TemporaryDirectory(prefix="draft-bridge-test-") as temporary:
            root = Path(temporary)
            image_path = root / "image.png"
            Image.new("RGB", (320, 180), "#332211").save(image_path)
            key = {
                "kind": "jianying_draft_key",
                "meta": {"run_id": "bridge-unit-test", "title": "桥接测试"},
                "draft": {"width": 320, "height": 180, "name": "桥接测试"},
                "calls": [
                    {
                        "call_id": "image",
                        "tool": "add_images",
                        "params": {
                            "image_infos": [
                                {"image_url": str(image_path), "start": 0, "end": 1_000_000}
                            ]
                        },
                    }
                ],
            }
            report = import_draft_payload(key, draft_root=root / "drafts")
            self.assertTrue(report["verified"])
            self.assertEqual(report["track_count"], 1)
            self.assertEqual(report["segment_count"], 1)
            self.assertTrue((Path(report["draft_dir"]) / "draft_content.json").is_file())
            self.assertTrue((Path(report["draft_dir"]) / "draft_info.json").is_file())

    def test_overlapping_images_are_split_across_video_tracks(self):
        with tempfile.TemporaryDirectory(prefix="draft-bridge-overlap-test-") as temporary:
            root = Path(temporary)
            image_path = root / "image.png"
            Image.new("RGB", (320, 180), "#332211").save(image_path)
            key = {
                "kind": "jianying_draft_key",
                "meta": {"run_id": "bridge-overlap-test"},
                "draft": {"width": 320, "height": 180, "name": "重叠图片测试"},
                "calls": [
                    {
                        "call_id": "images",
                        "tool": "add_images",
                        "params": {
                            "image_infos": [
                                {"image_url": str(image_path), "start": 0, "end": 1_000_000},
                                {"image_url": str(image_path), "start": 0, "end": 1_000_000},
                                {
                                    "image_url": str(image_path),
                                    "start": 1_000_000,
                                    "end": 2_000_000,
                                },
                            ]
                        },
                    }
                ],
            }

            report = import_draft_payload(key, draft_root=root / "drafts")
            content = json.loads(
                (Path(report["draft_dir"]) / "draft_content.json").read_text(
                    encoding="utf-8"
                )
            )
            video_tracks = [
                track for track in content["tracks"] if track["type"] == "video"
            ]

            self.assertEqual(len(video_tracks), 2)
            self.assertEqual(
                sorted(len(track["segments"]) for track in video_tracks),
                [1, 2],
            )
            for track in video_tracks:
                ranges = sorted(
                    (
                        segment["target_timerange"]["start"],
                        segment["target_timerange"]["start"]
                        + segment["target_timerange"]["duration"],
                    )
                    for segment in track["segments"]
                )
                self.assertTrue(
                    all(
                        previous[1] <= current[0]
                        for previous, current in zip(ranges, ranges[1:])
                    )
                )


if __name__ == "__main__":
    unittest.main()
