# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all
import sys
import os

block_cipher = None
is_macos = sys.platform == "darwin"
is_windows = sys.platform == "win32"

APP_NAME = "AudioTTo"

# -------------------------
# Icone per OS
# -------------------------
if is_windows:
    APP_ICON = "logo/logo_app.ico"
elif is_macos:
    APP_ICON = "logo/logo_app.icns"
else:
    APP_ICON = "logo/logo_app.png"

# -------------------------
# Risorse
# -------------------------
datas = [
    ("web", "web"),
    ("logo", "logo"),
]

binaries = []
bin_path = "bin"

if is_macos:
    binaries += [
        (os.path.join(bin_path, "ffmpeg"), "bin"),
        (os.path.join(bin_path, "ffprobe"), "bin"),
    ]
elif is_windows:
    binaries += [
        (os.path.join(bin_path, "ffmpeg.exe"), "."),
        (os.path.join(bin_path, "ffprobe.exe"), "."),
    ]
else:  # Linux
    binaries += [
        (os.path.join(bin_path, "ffmpeg"), "."),
        (os.path.join(bin_path, "ffprobe"), "."),
    ]

# -------------------------
# Import nascosti
# -------------------------
hiddenimports = [
    "fastapi",
    "uvicorn",
    "starlette",
    "pydantic",
    "webview",
    "faster_whisper",
]

for pkg in ["faster_whisper", "pywebview", "av"]:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# -------------------------
# Analisi
# -------------------------
a = Analysis(
    ["gui_app.py"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "torch"],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, cipher=block_cipher)

# -------------------------
# EXE
# -------------------------
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name=APP_NAME,
    console=True,
    icon=None if is_macos else APP_ICON,
)

# -------------------------
# OUTPUT
# -------------------------
if is_macos:
    app = BUNDLE(
        exe,
        a.binaries,
        a.datas,
        name=f"{APP_NAME}.app",
        icon=APP_ICON,
        bundle_identifier="com.manumarzo.audiotto",
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "NSHighResolutionCapable": True,
        },
    )
else:
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        name=APP_NAME,
    )
