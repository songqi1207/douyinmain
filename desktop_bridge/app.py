#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tkinter UI and CLI entrypoint for AI Video Creator."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path

from desktop_bridge.draft_core import (
    BridgeError,
    detect_draft_roots,
    detect_jianying_executables,
    import_draft_payload,
    launch_jianying,
    load_payload_file,
    open_directory,
)
from desktop_bridge.device_agent import DeviceAgent, agent_log_path, pair_with_site
from desktop_bridge.helper_metadata import HELPER_PRODUCT_NAME, HELPER_VERSION
from desktop_bridge.paths import app_data_dir
from desktop_bridge.updater import download_and_launch_update
from desktop_bridge.windows_integration import (
    acquire_single_instance,
    consume_wake_signal,
    install_for_current_user,
    notify_primary,
    parse_protocol_url,
)


def _settings_path() -> Path:
    return app_data_dir() / "settings.json"


def _load_settings() -> dict:
    try:
        return json.loads(_settings_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_settings(payload: dict) -> None:
    path = _settings_path()
    temporary = path.with_suffix(".tmp")
    merged = _load_settings()
    merged.update(payload)
    temporary.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class DraftBridgeApp:
    def __init__(self, initial_file: str = "", start_hidden: bool = False, protocol_url: str = ""):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = tk.Tk()
        if start_hidden:
            # Hide before widgets are constructed so Windows startup/browser
            # wake does not flash a blank Tk window on the user's desktop.
            self.root.withdraw()
        self.root.title(f"{HELPER_PRODUCT_NAME} v{HELPER_VERSION}")
        self.root.geometry("940x900")
        self.root.minsize(800, 760)
        self.last_report: dict = {}
        self.settings = _load_settings()
        self.device_agent: DeviceAgent | None = None
        self.hide_after_pairing = False
        self.background_mode = bool(start_hidden)

        roots = detect_draft_roots()
        executables = detect_jianying_executables()
        default_root = self.settings.get("draft_root") or (str(roots[0]) if roots else "")
        default_exe = self.settings.get("jianying_exe") or (str(executables[0]) if executables else "")
        self.draft_root_var = tk.StringVar(value=default_root)
        self.jianying_exe_var = tk.StringVar(value=default_exe)
        self.site_url_var = tk.StringVar(value=str(self.settings.get("site_url") or ""))
        self.pairing_code_var = tk.StringVar(value="")
        self.device_name_var = tk.StringVar(
            value=str(self.settings.get("device_name") or os.getenv("COMPUTERNAME") or "我的电脑")
        )
        self.device_status_var = tk.StringVar(value="尚未连接网站")
        self.force_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="粘贴网站工作流生成的 draft_key JSON")
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        if self.settings.get("device_token") and self.settings.get("device_id"):
            self.root.after(400, self.start_device_agent)
        if protocol_url:
            self.root.after(250, self._handle_protocol_url, protocol_url)
        self.root.after(800, self._poll_wake_signal)
        if initial_file:
            self.load_file(initial_file)

    def _build_ui(self) -> None:
        from tkinter import scrolledtext

        frame = self.ttk.Frame(self.root, padding=14)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(5, weight=1)

        self.ttk.Label(frame, text="剪映草稿目录").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=5)
        self.ttk.Entry(frame, textvariable=self.draft_root_var).grid(row=0, column=1, sticky="ew", pady=5)
        self.ttk.Button(frame, text="选择目录", command=self.choose_draft_root).grid(row=0, column=2, padx=(8, 0), pady=5)

        self.ttk.Label(frame, text="剪映程序").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=5)
        self.ttk.Entry(frame, textvariable=self.jianying_exe_var).grid(row=1, column=1, sticky="ew", pady=5)
        self.ttk.Button(frame, text="选择 EXE", command=self.choose_jianying_exe).grid(row=1, column=2, padx=(8, 0), pady=5)

        device = self.ttk.LabelFrame(frame, text="网站一键生成视频（本机剪映原生导出，不使用 FFmpeg）", padding=10)
        device.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 8))
        device.columnconfigure(1, weight=1)
        self.ttk.Label(device, text="网站地址").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        self.ttk.Entry(device, textvariable=self.site_url_var).grid(row=0, column=1, columnspan=3, sticky="ew", pady=4)
        self.ttk.Label(device, text="配对码").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        self.ttk.Entry(device, textvariable=self.pairing_code_var, width=16).grid(row=1, column=1, sticky="w", pady=4)
        self.ttk.Label(device, text="电脑名称").grid(row=1, column=2, sticky="e", padx=(12, 8), pady=4)
        self.ttk.Entry(device, textvariable=self.device_name_var, width=22).grid(row=1, column=3, sticky="ew", pady=4)
        self.pair_button = self.ttk.Button(device, text="配对并保持在线", command=self.start_pairing)
        self.pair_button.grid(row=0, column=4, rowspan=2, padx=(10, 0), pady=4)
        self.ttk.Button(device, text="退出助手", command=self._exit_app).grid(
            row=2, column=4, padx=(10, 0), pady=(6, 0)
        )
        self.ttk.Button(device, text="查看日志", command=self.open_device_logs).grid(
            row=3, column=4, padx=(10, 0), pady=(6, 0)
        )
        self.ttk.Label(device, textvariable=self.device_status_var, foreground="#19714a").grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(6, 0)
        )

        toolbar = self.ttk.Frame(frame)
        toolbar.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(2, 8))
        self.ttk.Button(toolbar, text="选择 JSON 文件", command=self.choose_json).pack(side="left")
        self.ttk.Button(toolbar, text="粘贴剪贴板", command=self.paste_clipboard).pack(side="left", padx=8)
        self.ttk.Button(toolbar, text="清空", command=lambda: self.text.delete("1.0", "end")).pack(side="left")
        self.ttk.Checkbutton(toolbar, text="强制重新导入同一任务", variable=self.force_var).pack(side="right")

        self.ttk.Label(frame, text="工作流 draft_key JSON").grid(row=4, column=0, columnspan=3, sticky="w")
        self.text = scrolledtext.ScrolledText(frame, wrap="none", font=("Consolas", 10), undo=True)
        self.text.grid(row=5, column=0, columnspan=3, sticky="nsew", pady=(5, 10))

        action = self.ttk.Frame(frame)
        action.grid(row=6, column=0, columnspan=3, sticky="ew")
        self.import_button = self.ttk.Button(action, text="导入到本机剪映", command=self.start_import)
        self.import_button.pack(side="left")
        self.ttk.Button(action, text="打开草稿目录", command=self.open_last_draft).pack(side="left", padx=8)
        self.ttk.Button(action, text="启动剪映", command=self.start_jianying).pack(side="left")
        self.ttk.Button(action, text="打开运行日志", command=self.open_device_logs).pack(side="left", padx=8)
        self.progress = self.ttk.Progressbar(action, mode="indeterminate", length=180)
        self.progress.pack(side="right")

        self.ttk.Label(frame, textvariable=self.status_var, foreground="#285f8f").grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(10, 0)
        )

    def start_pairing(self) -> None:
        site_url = self.site_url_var.get().strip()
        pairing_code = self.pairing_code_var.get().strip()
        device_name = self.device_name_var.get().strip()
        if not site_url or not pairing_code:
            self.show_error("请先填写网站地址和网站生成的 8 位配对码")
            return
        self.pair_button.configure(state="disabled")
        self.device_status_var.set("正在与网站配对…")
        threading.Thread(
            target=self._pair_worker,
            args=(site_url, pairing_code, device_name),
            daemon=True,
        ).start()

    def _pair_worker(self, site_url: str, pairing_code: str, device_name: str) -> None:
        try:
            result = pair_with_site(site_url, pairing_code, device_name)
        except Exception as exc:
            self.root.after(0, self._finish_pair_error, str(exc))
            return
        self.root.after(0, self._finish_pairing, result)

    def _finish_pair_error(self, message: str) -> None:
        self.pair_button.configure(state="normal")
        self.device_status_var.set(f"配对失败：{message}")
        self.root.deiconify()
        self.root.lift()
        self.show_error(message)

    def _finish_pairing(self, result: dict) -> None:
        self.pair_button.configure(state="normal")
        self.pairing_code_var.set("")
        self.site_url_var.set(str(result["site_url"]))
        self.device_status_var.set("配对成功，正在启动本机剪映任务监听…")
        self.settings.update(
            {
                "site_url": result["site_url"],
                "device_id": result["device_id"],
                "device_token": result["device_token"],
                "device_name": result.get("name") or self.device_name_var.get().strip(),
            }
        )
        self._persist_paths()
        self.start_device_agent()
        if self.hide_after_pairing:
            self.hide_after_pairing = False
            self.root.after(700, self.root.withdraw)

    def _handle_protocol_url(self, protocol_url: str) -> None:
        options = parse_protocol_url(protocol_url)
        if not options:
            return
        action = str(options.get("action") or "")
        if action == "wake":
            self.background_mode = True
        site_url = str(options.get("site_url") or "")
        pairing_code = str(options.get("pairing_code") or "")
        if site_url:
            self.site_url_var.set(site_url)
        if action == "update":
            self.background_mode = True
            self.root.withdraw()
            self.start_update(site_url or str(self.settings.get("site_url") or ""))
            return
        current_site = str(self.settings.get("site_url") or "").rstrip("/")
        needs_pairing = pairing_code and (
            not self.settings.get("device_token") or (site_url and current_site != site_url.rstrip("/"))
        )
        if needs_pairing:
            self.pairing_code_var.set(pairing_code)
            self.hide_after_pairing = action == "wake"
            if action == "wake":
                self.device_status_var.set("网页已发起配对，正在后台连接…")
                self.root.withdraw()
                self.start_pairing()
                return
            self.device_status_var.set("网页已填入配对信息，请确认网站地址后点击“配对并保持在线”")
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            return
        if self.settings.get("device_token"):
            self.start_device_agent()
        if action == "open" or not self.settings.get("device_token"):
            self.background_mode = False
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()

    def _poll_wake_signal(self) -> None:
        protocol_url = consume_wake_signal()
        if protocol_url:
            self._handle_protocol_url(protocol_url)
        try:
            self.root.after(800, self._poll_wake_signal)
        except Exception:
            pass

    def _persist_paths(self) -> None:
        values = {
            **self.settings,
            "site_url": self.site_url_var.get().strip(),
            "device_name": self.device_name_var.get().strip(),
            "draft_root": self.draft_root_var.get().strip(),
            "jianying_exe": self.jianying_exe_var.get().strip(),
        }
        self.settings.update(values)
        _save_settings(values)

    def start_update(self, site_url: str) -> None:
        target_site = str(site_url or self.site_url_var.get() or self.settings.get("site_url") or "")
        self.device_status_var.set("正在下载并启动最新版助手...")
        threading.Thread(target=self._update_worker, args=(target_site,), daemon=True).start()

    def _update_worker(self, site_url: str) -> None:
        try:
            download_and_launch_update(site_url)
        except Exception as exc:
            self.root.after(0, self._finish_update_error, str(exc))
            return
        self.root.after(0, self._finish_update_launched)

    def _finish_update_error(self, message: str) -> None:
        self.device_status_var.set(f"助手更新失败：{message}")
        self.background_mode = False
        self.root.deiconify()
        self.root.lift()
        self.show_error(message)

    def _finish_update_launched(self) -> None:
        self.device_status_var.set("最新版助手已启动，正在退出旧助手...")
        self.root.after(500, self._exit_app)

    def _set_device_status(self, message: str) -> None:
        try:
            self.root.after(0, self._apply_device_status, message)
        except Exception:
            pass

    def _apply_device_status(self, message: str) -> None:
        self.device_status_var.set(message)
        if not message.startswith("剪映导出失败："):
            return
        if self.background_mode:
            return
        from tkinter import messagebox

        self.root.deiconify()
        self.root.lift()
        messagebox.showerror(
            "剪映导出失败",
            f"{message}\n\n详细运行日志：\n{agent_log_path()}",
        )

    def start_device_agent(self) -> None:
        if self.device_agent:
            self.device_agent.stop()
        site_url = self.site_url_var.get().strip() or str(self.settings.get("site_url") or "")
        device_id = str(self.settings.get("device_id") or "")
        device_token = str(self.settings.get("device_token") or "")
        draft_root = self.draft_root_var.get().strip()
        jianying_exe = self.jianying_exe_var.get().strip()
        if not site_url or not device_id or not device_token:
            self.device_status_var.set("请从网站获取配对码，然后在这里完成一次配对")
            return
        if not draft_root or not jianying_exe:
            self.device_status_var.set("已配对；选择剪映草稿目录和 JianyingPro.exe 后即可在线")
            return
        self._persist_paths()
        try:
            self.device_agent = DeviceAgent(
                site_url=site_url,
                device_id=device_id,
                device_token=device_token,
                draft_root=draft_root,
                jianying_exe=jianying_exe,
                status=self._set_device_status,
            )
            self.device_agent.start()
        except Exception as exc:
            self.device_status_var.set(f"本机助手启动失败：{exc}")

    def _on_close(self) -> None:
        if getattr(sys, "frozen", False) and self.settings.get("device_token"):
            self.root.withdraw()
            return
        self._exit_app()

    def _exit_app(self) -> None:
        if self.device_agent:
            self.device_agent.stop()
        self.root.destroy()

    def open_device_logs(self) -> None:
        path = agent_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        open_directory(path.parent)

    def choose_draft_root(self) -> None:
        from tkinter import filedialog

        selected = filedialog.askdirectory(title="选择 com.lveditor.draft 草稿目录")
        if selected:
            self.draft_root_var.set(selected)
            self._persist_paths()
            if not self.device_agent or not self.device_agent.running:
                self.start_device_agent()

    def choose_jianying_exe(self) -> None:
        from tkinter import filedialog

        selected = filedialog.askopenfilename(title="选择 JianyingPro.exe", filetypes=[("程序", "*.exe")])
        if selected:
            self.jianying_exe_var.set(selected)
            self._persist_paths()
            if not self.device_agent or not self.device_agent.running:
                self.start_device_agent()

    def choose_json(self) -> None:
        from tkinter import filedialog

        selected = filedialog.askopenfilename(title="选择 draft_key JSON", filetypes=[("JSON", "*.json"), ("全部", "*.*")])
        if selected:
            self.load_file(selected)

    def load_file(self, path: str) -> None:
        try:
            payload = load_payload_file(path)
        except BridgeError as exc:
            self.show_error(str(exc))
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", json.dumps(payload, ensure_ascii=False, indent=2))
        self.status_var.set(f"已加载：{path}")

    def paste_clipboard(self) -> None:
        try:
            value = self.root.clipboard_get()
        except Exception:
            self.show_error("剪贴板中没有文本")
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)
        self.status_var.set("已粘贴剪贴板内容")

    def start_import(self) -> None:
        raw = self.text.get("1.0", "end").strip()
        draft_root = self.draft_root_var.get().strip()
        if not draft_root:
            self.show_error("没有检测到剪映草稿目录，请先点击“选择目录”")
            return
        if not raw:
            self.show_error("请先粘贴 draft_key 或选择 JSON 文件")
            return
        self.import_button.configure(state="disabled")
        self.progress.start(10)
        self.status_var.set("准备导入……")
        force = self.force_var.get()
        thread = threading.Thread(target=self._import_worker, args=(raw, draft_root, force), daemon=True)
        thread.start()

    def _import_worker(self, raw: str, draft_root: str, force: bool) -> None:
        try:
            report = import_draft_payload(
                raw,
                draft_root=draft_root,
                force=force,
                progress=lambda message: self.root.after(0, self.status_var.set, message),
            )
        except Exception as exc:
            self.root.after(0, self._finish_error, str(exc))
            return
        self.root.after(0, self._finish_success, report)

    def _finish_success(self, report: dict) -> None:
        self.progress.stop()
        self.import_button.configure(state="normal")
        self.last_report = report
        _save_settings(
            {"draft_root": self.draft_root_var.get().strip(), "jianying_exe": self.jianying_exe_var.get().strip()}
        )
        warnings = report.get("warnings") or []
        status = (
            f"导入成功｜草稿 ID：{report.get('draft_id')}｜轨道：{report.get('track_count')}"
            f"｜片段：{report.get('segment_count')}"
        )
        if warnings:
            status += f"｜警告：{len(warnings)} 条"
        self.status_var.set(status)
        from tkinter import messagebox

        detail = status + f"\n\n草稿目录：\n{report.get('draft_dir')}"
        if warnings:
            detail += "\n\n" + "\n".join(str(item) for item in warnings[:12])
        messagebox.showinfo("草稿导入完成", detail)

    def _finish_error(self, message: str) -> None:
        self.progress.stop()
        self.import_button.configure(state="normal")
        self.show_error(message)

    def show_error(self, message: str) -> None:
        self.status_var.set(message)
        from tkinter import messagebox

        messagebox.showerror("草稿桥接器", message)

    def open_last_draft(self) -> None:
        target = self.last_report.get("draft_dir") or self.draft_root_var.get().strip()
        try:
            open_directory(target)
        except BridgeError as exc:
            self.show_error(str(exc))

    def start_jianying(self) -> None:
        target = self.jianying_exe_var.get().strip()
        if not target:
            self.show_error("没有检测到剪映程序，请先选择 JianyingPro.exe")
            return
        try:
            launch_jianying(target)
        except BridgeError as exc:
            self.show_error(str(exc))

    def run(self) -> None:
        self.root.mainloop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="draft_key → Windows 本地剪映草稿桥接器")
    parser.add_argument("--key", help="draft_key 或扣子运行结果 JSON 文件")
    parser.add_argument("--draft-root", help="剪映 com.lveditor.draft 目录")
    parser.add_argument("--force", action="store_true", help="强制重新导入相同 run_id")
    parser.add_argument("--launch", action="store_true", help="成功后启动剪映")
    parser.add_argument("--jianying-exe", help="JianyingPro.exe 路径")
    parser.add_argument("--background", action="store_true", help="后台启动网站剪映任务助手")
    parser.add_argument("--protocol", help="处理 douyin-draft:// 网页唤醒地址")
    parser.add_argument("--no-gui", action="store_true", help="命令行模式")
    args = parser.parse_args(argv)

    if not args.no_gui:
        relaunch_arguments = list(argv if argv is not None else sys.argv[1:])
        if install_for_current_user(relaunch_arguments):
            return 0
        protocol_url = str(args.protocol or "")
        if not acquire_single_instance():
            notify_primary(protocol_url or "douyin-draft://open")
            return 0
        protocol = parse_protocol_url(protocol_url)
        DraftBridgeApp(
            args.key or "",
            start_hidden=bool(args.background or protocol.get("action") in {"wake", "update"}),
            protocol_url=protocol_url,
        ).run()
        return 0
    if not args.key:
        parser.error("--no-gui 需要 --key")
    roots = detect_draft_roots()
    draft_root = args.draft_root or (str(roots[0]) if roots else "")
    if not draft_root:
        print("没有检测到剪映草稿目录，请传 --draft-root", file=sys.stderr)
        return 2
    try:
        report = import_draft_payload(
            load_payload_file(args.key),
            draft_root=draft_root,
            force=args.force,
            progress=lambda message: print(message, file=sys.stderr),
        )
        if args.launch:
            executables = detect_jianying_executables()
            executable = args.jianying_exe or (str(executables[0]) if executables else "")
            if not executable:
                raise BridgeError("没有检测到剪映程序，请传 --jianying-exe")
            launch_jianying(executable)
    except BridgeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
