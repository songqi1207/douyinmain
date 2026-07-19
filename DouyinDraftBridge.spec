# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


root = Path(SPECPATH)

a = Analysis(
    [str(root / "desktop_bridge_main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "utils" / "data" / "jianying_meta.json"), "utils/data"),
        (str(root / "scripts" / "run_mihe_sync_automation.ps1"), "scripts"),
    ],
    hiddenimports=["PIL.Image", "requests"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name="DouyinDraftBridge",
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
