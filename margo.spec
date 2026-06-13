# -*- mode: python ; coding: utf-8 -*-
"""
margo.spec — PyInstaller spec para Margo · Nelí
Genera: dist/Margo Neli/Margo Neli.exe  (sin terminal, doble clic)
Construir: pyinstaller margo.spec
"""

import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

# ── Recursos que van DENTRO del bundle (sys._MEIPASS) ─────────────────────────
datas = [
    # Plotly offline
    ('assets', 'assets'),
]

# ── Imports ocultos que PyInstaller no detecta solo ───────────────────────────
hiddenimports = [
    'PyQt6.QtWebEngineWidgets',
    'PyQt6.QtWebEngineCore',
    'PyQt6.QtWebChannel',
    'PyQt6.sip',
    'plotly',
    'plotly.graph_objects',
    'plotly.subplots',
    'pandas',
    'numpy',
    'xlrd',
    'openpyxl',
]

a = Analysis(
    ['app_qt.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'streamlit', 'tornado', 'altair', 'bokeh',
        'matplotlib', 'scipy', 'sklearn',
        'IPython', 'jupyter',
        'tkinter', 'wx',
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
    name='Margo Neli',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,        # <-- sin terminal
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Margo Neli',
)
