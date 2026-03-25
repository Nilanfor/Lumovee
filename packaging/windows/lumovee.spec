# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Lumovee
# Run from the repo root:  pyinstaller packaging/windows/lumovee.spec

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent.parent   # repo root
SRC  = str(ROOT / "src")

a = Analysis(
    [str(ROOT / "src" / "ui.py")],
    pathex=[SRC],
    binaries=[],
    datas=[],
    hiddenimports=[
        # PySide6 platform plugins are loaded at runtime — make sure they are bundled
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim heavy Qt modules we don't use
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.QtMultimedia",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Lumovee",
    debug=False,
    strip=False,
    upx=True,
    console=False,        # no console window
    icon=None,            # replace with .ico path when available
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="Lumovee",
)
