# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, copy_metadata
import sys
import os

block_cipher = None

# ---------- OS DETECTION ----------
if sys.platform == 'win32':
    ffmpeg_bin = 'ffmpeg.exe'
    ffprobe_bin = 'ffprobe.exe'
else:
    ffmpeg_bin = 'ffmpeg'
    ffprobe_bin = 'ffprobe'

bin_path = 'bin'

# ---------- DATA ----------
datas = [
    ('web', 'web'),
    ('logo', 'logo'),
]

binaries = [
    (os.path.join(bin_path, ffmpeg_bin), '.'),
    (os.path.join(bin_path, ffprobe_bin), '.'),
]

# ---------- HIDDEN IMPORTS ----------
hiddenimports = [
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.loops.asyncio',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',

    'fastapi',
    'starlette',
    'pydantic',

    'python_multipart',
    'dotenv',
    'fitz',
    'webview',

    # Windows
    'clr_loader',
    'pythonnet',
    'System',
    'System.Windows.Forms',

    # AI / Audio
    'faster_whisper',
]

# ---------- COLLECT PACKAGES ----------
for pkg in ['faster_whisper', 'pythonnet', 'clr_loader', 'pywebview', 'av']:
    tmp = collect_all(pkg)
    datas += tmp[0]
    binaries += tmp[1]
    hiddenimports += tmp[2]

# ---------- METADATA ----------
packages_to_copy = [
    'tqdm',
    'regex',
    'requests',
    'packaging',
    'filelock',
    'huggingface_hub',
    'google-genai',
    'numpy',
    'uvicorn',
    'fastapi',
    'av'
]

for pkg in packages_to_copy:
    try:
        datas += copy_metadata(pkg)
    except Exception:
        print(f"[WARNING] Metadata not found for {pkg}")

# ---------- ANALYSIS ----------
a = Analysis(
    ['gui_app.py'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        'torch',
        'noisereduce',
        'scipy',
        'matplotlib',
        'tkinter', 'tcl', 'tk'
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name='AudioTTo',
    console=True,
    icon='logo/logo_app.ico'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='AudioTTo'
)
