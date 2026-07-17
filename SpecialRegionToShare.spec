# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Special Region to Share.

Build a single windowed .exe:

    pyinstaller SpecialRegionToShare.spec

Output: dist/SpecialRegionToShare.exe
"""

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

# Bundle native extensions and data for packages that need help.
for pkg in ("windows_capture", "cv2", "pystray", "pynput"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# win32 modules used at runtime
hiddenimports += [
    "win32gui",
    "win32con",
    "win32api",
    "win32process",
    "win32ui",
    "pystray._win32",
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
]


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SpecialRegionToShare",
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
    icon="assets/app.ico",
)
