# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller yapılandırması (PyInstaller 6.x).

Kullanım:
    pyinstaller MakineArizaTakip.spec --noconfirm --clean

Çıktı: dist/MakineArizaTakip.exe  (tek dosya, taşınabilir)
"""

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    # Şema dosyası koda gömülü değil, veri olarak paketlenmeli.
    datas=[("app/db/schema.sql", "app/db")],
    hiddenimports=["openpyxl"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Paket boyutunu küçültmek için kullanılmayan Qt/matplotlib parçaları dışlanır.
    excludes=[
        "tkinter",
        "PyQt6.QtQml",
        "PyQt6.QtQuick",
        "PyQt6.QtQuick3D",
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtMultimedia",
        "PyQt6.QtBluetooth",
        "PyQt6.QtNfc",
        "PyQt6.QtDesigner",
        "PyQt6.QtHelp",
        "PyQt6.QtTest",
        "matplotlib.backends.backend_webagg",
        "matplotlib.backends.backend_tkagg",
        "IPython",
        "jupyter",
        "pytest",
    ],
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
    name="MakineArizaTakip",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # Konsol penceresi açılmaz
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,              # Kendi .ico dosyanızı buraya verebilirsiniz
)
