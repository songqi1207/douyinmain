# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

from desktop_bridge.helper_metadata import HELPER_BINARY_NAME


root = Path(SPECPATH)
python_root = Path(sys.base_prefix)
python_dlls = python_root / "DLLs"
tcl_root = python_root / "tcl"
tcl_data = tcl_root / "tcl8.6"
tk_data = tcl_root / "tk8.6"
tkinter_binary = python_dlls / "_tkinter.pyd"
tcl_binary = python_dlls / "tcl86t.dll"
tk_binary = python_dlls / "tk86t.dll"

required_tk_paths = (
    tkinter_binary,
    tcl_binary,
    tk_binary,
    tcl_data / "init.tcl",
    tk_data / "tk.tcl",
)
missing_tk_paths = [str(path) for path in required_tk_paths if not path.exists()]
if missing_tk_paths:
    raise SystemExit(
        "Cannot build the GUI helper because Tcl/Tk files are missing: "
        + ", ".join(missing_tk_paths)
    )

a = Analysis(
    [str(root / "desktop_bridge_main.py")],
    pathex=[str(root)],
    binaries=[
        (str(tkinter_binary), "."),
        (str(tcl_binary), "."),
        (str(tk_binary), "."),
    ],
    datas=[
        (str(root / "utils" / "data" / "jianying_meta.json"), "utils/data"),
        (str(root / "scripts" / "run_jianying_export_automation.ps1"), "scripts"),
        (str(tcl_data), "_tcl_data"),
        (str(tk_data), "_tk_data"),
    ],
    hiddenimports=[
        "PIL.Image",
        "requests",
        "_tkinter",
        "tkinter",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "tkinter.scrolledtext",
        "tkinter.ttk",
    ],
    hookspath=[str(root / "pyinstaller_hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["desktop_bridge.core", "desktop_bridge.mihe_direct"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=Path(HELPER_BINARY_NAME).stem,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
