# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, copy_metadata
import sys
import os

block_cipher = None

# --- OS Detection for Binaries ---
# Define binary names based on the system
if sys.platform == 'win32':
    ffmpeg_bin = 'ffmpeg.exe'
    ffprobe_bin = 'ffprobe.exe'
else:
    # Linux and macOS do not have the .exe extension
    ffmpeg_bin = 'ffmpeg'
    ffprobe_bin = 'ffprobe'

# local path where GitHub Action will download the files
bin_path = 'bin'

# --- Data Configuration ---
datas = [
    ('web', 'web'),        # web UI directory
    ('logo', 'logo'),      # logo directory
]

# Binaries configuration dynamic
binaries = [
    (os.path.join(bin_path, ffmpeg_bin), '.'), 
    (os.path.join(bin_path, ffprobe_bin), '.')
]

# --- Imports Configuration ---
hiddenimports = [
    # Server & API
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
    
    # Utilities
    'python_multipart',
    'dotenv',          # Per python-dotenv
    'fitz',            # Per PyMuPDF
    'webview',         # Per pywebview
    
    # AI & Audio
    'faster_whisper'
]

# --- Packets ---
# collects faster_whisper
tmp_ret = collect_all('faster_whisper')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# --- secure blocks for metadata ---
# this block try to copy metadata, but don't crash if not found
packages_to_copy = [
    'tqdm', 
    'regex', 
    'requests', 
    'packaging', 
    'filelock', 
    'huggingface_hub', 
    'google.genai',
    'numpy',
    'uvicorn',
    'fastapi'
]

for package in packages_to_copy:
    try:
        datas += copy_metadata(package)
    except Exception:
        print(f"[WARNING] Could not copy metadata for '{package}'. Skipping (this is usually fine).")

# --- Analysis ---
a = Analysis(
    ['gui_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch', 
        'noisereduce', 
        'scipy', 
        'matplotlib', 
        'tkinter', 'tcl', 'tk'
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AudioTTo',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='logo/logo_app.ico'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AudioTTo',
)