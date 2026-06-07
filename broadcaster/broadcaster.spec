# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

a = Analysis(
    ['tray.py'],
    pathex=[],
    binaries=collect_dynamic_libs('mediapipe'),
    datas=collect_data_files('livekit.rtc') + collect_data_files('mediapipe') + [('hand_landmarker.task', 'broadcaster')],
    hiddenimports=[
        'livekit.rtc.resources',
        'mediapipe.tasks.c',
        'pystray._win32',
        'pystray._darwin',
        'pystray._xorg',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Broadcaster',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
