# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, copy_metadata

block_cipher = None

# --- Data Configuration ---
datas = [
    ('web', 'web'),        # web UI directory
    ('logo', 'logo'),      # logo directory
]
binaries = [
    ('bin/ffmpeg.exe', '.'), # need exe downloaded and placed in bin/
    ('bin/ffprobe.exe', '.')
]

# Import necessari
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
    'engineio.async_drivers.threading',
    'python_multipart',
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
    'google.generativeai',
    'numpy'
]

for package in packages_to_copy:
    try:
        datas += copy_metadata(package)
    except Exception:
        print(f"⚠️ Warning: Could not copy metadata for '{package}'. Skipping (this is usually fine).")

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