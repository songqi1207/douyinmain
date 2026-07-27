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
    _run_native_export,
    normalize_site_url,
    pair_with_site,
)
from desktop_bridge.paths import app_data_dir
from desktop_bridge.app import DraftBridgeApp
import desktop_bridge.windows_integration as windows_integration
from desktop_bridge.windows_integration import parse_protocol_url


class DesktopBridgeTests(unittest.TestCase):
    def test_background_start_hides_window_before_building_widgets(self):
        source = inspect.getsource(DraftBridgeApp.__init__)

        self.assertLess(source.index("self.root.withdraw()"), source.index("self._build_ui()"))

    @patch("desktop_bridge.jianying_uia_export.export_draft_uia")
    @patch("desktop_bridge.device_agent.subprocess.run")
    @patch("desktop_bridge.device_agent.import_draft_payload")
    def test_hidden_qml_controls_fall_back_to_uia2(
        self,
        import_payload,
        run_legacy_export,
        export_uia2,
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
            run_legacy_export.return_value = MagicMock(
                returncode=1,
                stdout=(
                    "jianying_automation_stage "
                    "stage=ui_tree_unavailable action=use_supported_jianying"
                ),
                stderr="",
            )

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
            export_uia2.assert_called_once()

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
        self.assertIn('Write-Stage "jianying_minimized"', script)

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
        with patch("desktop_bridge.device_agent.requests.post", return_value=response) as post:
            result = pair_with_site("https://example.test/business/", "ABCD2345", "办公室电脑")
        self.assertEqual(normalize_site_url("https://example.test/business"), "https://example.test")
        self.assertEqual(result["site_url"], "https://example.test")
        self.assertEqual(result["device_token"], "secret-token")
        self.assertEqual(post.call_args.args[0], "https://example.test/api/v1/render-agent/pair")
        self.assertFalse(post.call_args.kwargs["json"]["capabilities"]["ffmpeg"])

    def test_parses_browser_wake_protocol_without_executing_shell_text(self):
        parsed = parse_protocol_url(
            "douyin-draft://wake?site=https%3A%2F%2Fvideo.example.test&code=ABCD2345"
        )
        self.assertEqual(parsed["action"], "wake")
        self.assertEqual(parsed["site_url"], "https://video.example.test")
        self.assertEqual(parsed["pairing_code"], "ABCD2345")
        self.assertEqual(parse_protocol_url("https://example.test"), {})

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
