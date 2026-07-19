#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tkinter UI and CLI entrypoint for DouyinDraftBridge."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path

from desktop_bridge.core import (
    BridgeError,
    detect_draft_roots,
    detect_jianying_executables,
    ensure_mihe_sync,
    extract_mihe_draft_id,
    import_draft_payload,
    import_mihe_server_draft,
    launch_mihe_sync_automated,
    launch_jianying,
    load_payload_file,
    mihe_sync_executable_path,
    open_directory,
)


def _settings_path() -> Path:
    base = Path(os.getenv("APPDATA") or Path.home()) / "DouyinDraftBridge"
    base.mkdir(parents=True, exist_ok=True)
    return base / "settings.json"


def _load_settings() -> dict:
    try:
        return json.loads(_settings_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_settings(payload: dict) -> None:
    path = _settings_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class DraftBridgeApp:
    def __init__(self, initial_file: str = ""):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = tk.Tk()
        self.root.title("抖音工作流 · 剪映草稿桥接器")
        self.root.geometry("900x790")
        self.root.minsize(760, 690)
        self.last_report: dict = {}
        self.settings = _load_settings()

        roots = detect_draft_roots()
        executables = detect_jianying_executables()
        default_root = self.settings.get("draft_root") or (str(roots[0]) if roots else "")
        default_exe = self.settings.get("jianying_exe") or (str(executables[0]) if executables else "")
        self.draft_root_var = tk.StringVar(value=default_root)
        self.jianying_exe_var = tk.StringVar(value=default_exe)
        self.mihe_draft_id_var = tk.StringVar(value="")
        self.force_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="旧工作流填 draft_id；本地草稿工作流粘贴 draft_key JSON")
        self._build_ui()
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

        legacy = self.ttk.LabelFrame(frame, text="兼容现有扣子工作流（米核服务器 draft_id）", padding=10)
        legacy.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 8))
        legacy.columnconfigure(0, weight=1)
        self.ttk.Entry(legacy, textvariable=self.mihe_draft_id_var).grid(row=0, column=0, sticky="ew")
        self.ttk.Button(legacy, text="粘贴 ID", command=self.paste_mihe_id).grid(row=0, column=1, padx=8)
        self.mihe_direct_button = self.ttk.Button(legacy, text="直接下载到剪映", command=self.start_mihe_direct)
        self.mihe_direct_button.grid(row=0, column=2)
        self.mihe_button = self.ttk.Button(legacy, text="原同步器兜底", command=self.start_mihe_sync)
        self.mihe_button.grid(row=0, column=3, padx=(8, 0))
        self.ttk.Label(
            legacy,
            text="优先直接读取米核服务器 JSON；失败时再使用原同步器。",
            foreground="#725b18",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(7, 0))

        toolbar = self.ttk.Frame(frame)
        toolbar.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(2, 8))
        self.ttk.Button(toolbar, text="选择 JSON 文件", command=self.choose_json).pack(side="left")
        self.ttk.Button(toolbar, text="粘贴剪贴板", command=self.paste_clipboard).pack(side="left", padx=8)
        self.ttk.Button(toolbar, text="清空", command=lambda: self.text.delete("1.0", "end")).pack(side="left")
        self.ttk.Checkbutton(toolbar, text="强制重新导入同一任务", variable=self.force_var).pack(side="right")

        self.ttk.Label(frame, text="新本地草稿工作流 / draft_key JSON").grid(row=4, column=0, columnspan=3, sticky="w")
        self.text = scrolledtext.ScrolledText(frame, wrap="none", font=("Consolas", 10), undo=True)
        self.text.grid(row=5, column=0, columnspan=3, sticky="nsew", pady=(5, 10))

        action = self.ttk.Frame(frame)
        action.grid(row=6, column=0, columnspan=3, sticky="ew")
        self.import_button = self.ttk.Button(action, text="导入到本机剪映", command=self.start_import)
        self.import_button.pack(side="left")
        self.ttk.Button(action, text="打开草稿目录", command=self.open_last_draft).pack(side="left", padx=8)
        self.ttk.Button(action, text="启动剪映", command=self.start_jianying).pack(side="left")
        self.progress = self.ttk.Progressbar(action, mode="indeterminate", length=180)
        self.progress.pack(side="right")

        self.ttk.Label(frame, textvariable=self.status_var, foreground="#285f8f").grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(10, 0)
        )

    def choose_draft_root(self) -> None:
        from tkinter import filedialog

        selected = filedialog.askdirectory(title="选择 com.lveditor.draft 草稿目录")
        if selected:
            self.draft_root_var.set(selected)

    def choose_jianying_exe(self) -> None:
        from tkinter import filedialog

        selected = filedialog.askopenfilename(title="选择 JianyingPro.exe", filetypes=[("程序", "*.exe")])
        if selected:
            self.jianying_exe_var.set(selected)

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

    def paste_mihe_id(self) -> None:
        try:
            value = self.root.clipboard_get()
            draft_id = extract_mihe_draft_id(value)
        except Exception as exc:
            self.show_error(f"剪贴板中没有有效的米核草稿 ID：{exc}")
            return
        self.mihe_draft_id_var.set(draft_id)
        self.status_var.set("已粘贴米核 draft_id")

    def start_mihe_sync(self) -> None:
        raw = self.mihe_draft_id_var.get().strip()
        if not raw:
            try:
                raw = self.root.clipboard_get()
            except Exception:
                raw = ""
        try:
            draft_id = extract_mihe_draft_id(raw)
        except BridgeError as exc:
            self.show_error(str(exc))
            return
        if not mihe_sync_executable_path().is_file():
            from tkinter import messagebox

            confirmed = messagebox.askyesno(
                "首次安装米核同步器",
                "将从米核官方地址 https://cdn.miheai.com/tool/miheai.zip 下载便携版。\n\n"
                "该第三方程序目前没有数字签名；桥接器会使用固定 SHA256 校验后才启动。是否继续？",
            )
            if not confirmed:
                return
        self.mihe_draft_id_var.set(draft_id)
        self.root.clipboard_clear()
        self.root.clipboard_append(draft_id)
        self.root.update_idletasks()
        self.mihe_button.configure(state="disabled")
        self.progress.start(10)
        self.status_var.set("准备米核同步器……")
        threading.Thread(target=self._mihe_worker, args=(draft_id,), daemon=True).start()

    def start_mihe_direct(self) -> None:
        raw = self.mihe_draft_id_var.get().strip()
        draft_root = self.draft_root_var.get().strip()
        if not draft_root:
            self.show_error("没有检测到剪映草稿目录，请先点击“选择目录”")
            return
        if not raw:
            try:
                raw = self.root.clipboard_get()
            except Exception:
                raw = ""
        try:
            draft_id = extract_mihe_draft_id(raw)
        except BridgeError as exc:
            self.show_error(str(exc))
            return
        self.mihe_draft_id_var.set(draft_id)
        self.mihe_direct_button.configure(state="disabled")
        self.progress.start(10)
        self.status_var.set("准备直接读取米核服务器草稿……")
        threading.Thread(
            target=self._mihe_direct_worker,
            args=(draft_id, draft_root),
            daemon=True,
        ).start()

    def _mihe_direct_worker(self, draft_id: str, draft_root: str) -> None:
        try:
            report = import_mihe_server_draft(
                draft_id,
                draft_root=draft_root,
                progress=lambda message: self.root.after(0, self.status_var.set, message),
            )
        except Exception as exc:
            self.root.after(0, self._finish_error, str(exc))
            return
        self.root.after(0, self._finish_success, report)

    def _mihe_worker(self, draft_id: str) -> None:
        try:
            result = launch_mihe_sync_automated(
                draft_id,
                progress=lambda message: self.root.after(0, self.status_var.set, message)
            )
        except Exception as exc:
            self.root.after(0, self._finish_error, str(exc))
            return
        self.root.after(0, self._finish_mihe_success, result)

    def _finish_mihe_success(self, result: dict) -> None:
        self.progress.stop()
        self.mihe_button.configure(state="normal")
        status = str(result.get("status") or "started")
        automated = status == "submitted"
        self.status_var.set("米核同步器已自动提交 draft_id" if automated else "米核同步器已启动，请检查界面")
        from tkinter import messagebox

        messagebox.showinfo(
            "米核同步器已启动",
            ("已经自动填写 draft_id 并点击创建按钮。" if automated else
             "自动点击未完全完成，草稿 ID 已复制到剪贴板；请在米核同步器中按 Ctrl+V 后手动点击创建。")
            + f"\n\n同步器位置：\n{result.get('executable')}",
        )

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
        self.mihe_direct_button.configure(state="normal")
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
        self.mihe_button.configure(state="normal")
        self.mihe_direct_button.configure(state="normal")
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
    parser.add_argument("--mihe-draft-id", help="直接从米核服务器下载的旧工作流 draft_id")
    parser.add_argument("--install-mihe-sync", action="store_true", help="下载并校验米核官方同步器")
    parser.add_argument("--no-gui", action="store_true", help="命令行模式")
    args = parser.parse_args(argv)

    if not args.no_gui:
        DraftBridgeApp(args.key or "").run()
        return 0
    if args.mihe_draft_id:
        roots = detect_draft_roots()
        draft_root = args.draft_root or (str(roots[0]) if roots else "")
        if not draft_root:
            print("没有检测到剪映草稿目录，请传 --draft-root", file=sys.stderr)
            return 2
        try:
            report = import_mihe_server_draft(
                extract_mihe_draft_id(args.mihe_draft_id),
                draft_root=draft_root,
                progress=lambda message: print(message, file=sys.stderr),
            )
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.install_mihe_sync:
        try:
            executable = ensure_mihe_sync(progress=lambda message: print(message, file=sys.stderr))
        except BridgeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(str(executable))
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
