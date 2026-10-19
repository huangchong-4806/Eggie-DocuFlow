# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata


PROJECT_ROOT = Path(SPECPATH).parent
APP_BASENAME = "Eggie DocuFlow"
LICENSE_METADATA = []
for package in ("openpyxl", "pdfplumber", "pypdf", "Pillow", "pypdfium2", "PyMuPDF",
                "PySide6-Essentials", "alibabacloud_ocr_api20210707"):
    LICENSE_METADATA += copy_metadata(package, recursive=True)

a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        (str(PROJECT_ROOT / "LICENSE"), "."),
        (str(PROJECT_ROOT / "THIRD_PARTY_NOTICES.md"), "."),
        (str(PROJECT_ROOT / "release_notes_v1.5.0.md"), "."),
        (str(PROJECT_ROOT / "BUILD_RELEASE.md"), "."),
        (str(PROJECT_ROOT / "licenses"), "licenses"),
        (str(PROJECT_ROOT / "assets" / "software_logo.png"), "assets"),
        (str(PROJECT_ROOT / "assets" / "app_icon.png"), "assets"),
        (str(PROJECT_ROOT / "assets" / "app_icon.ico"), "assets"),
        (str(PROJECT_ROOT / "docs" / "OCR使用说明.pdf"), "docs"),
    ] + LICENSE_METADATA,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_BASENAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(PROJECT_ROOT / "assets" / "app_icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_BASENAME,
)
