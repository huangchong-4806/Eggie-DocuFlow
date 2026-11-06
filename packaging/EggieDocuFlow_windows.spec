# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from runpy import run_path
from PyInstaller.utils.hooks import copy_metadata


PROJECT_ROOT = Path(SPECPATH).parent
build_trust_data = run_path(str(PROJECT_ROOT / "packaging" / "update_trust.py"))["build_trust_data"]
version_scope = run_path(str(PROJECT_ROOT / "version.py"))
trust_data = build_trust_data(version_scope)
recovery_data = []
if trust_data:
    prepare_recovery = run_path(str(PROJECT_ROOT / "scripts" / "prepare_windows_updater.py"))["prepare"]
    recovery_helper = prepare_recovery(Path(workpath) / "eggie-windows-update-tools")
    recovery_data = [(str(recovery_helper), "update-tools")]
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
        (str(PROJECT_ROOT / f"release_notes_v{version_scope['APP_VERSION']}.md"), "."),
        (str(PROJECT_ROOT / "BUILD_RELEASE.md"), "."),
        (str(PROJECT_ROOT / "licenses"), "licenses"),
        (str(PROJECT_ROOT / "assets" / "software_logo.png"), "assets"),
        (str(PROJECT_ROOT / "assets" / "app_icon.png"), "assets"),
        (str(PROJECT_ROOT / "assets" / "app_icon.ico"), "assets"),
        (str(PROJECT_ROOT / "docs" / "OCR使用说明.pdf"), "docs"),
    ] + LICENSE_METADATA + trust_data + recovery_data,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)

# Build-machine paths in installer metadata do not belong in a distributed app.
a.datas = [entry for entry in a.datas if not (
    ".dist-info/" in entry[0].replace("\\", "/")
    and Path(entry[0].replace("\\", "/")).name in {"direct_url.json", "uv_cache.json"}
)]

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


# Direct PyInstaller + ISCC and the PowerShell wrapper must carry the same stamp.
if trust_data:
    write_stamp = run_path(str(PROJECT_ROOT / "scripts" / "build_windows_update.py"))["write_stamp"]
    write_stamp(Path(DISTPATH) / APP_BASENAME, version_scope["APP_VERSION"], version_scope["BUILD_NUMBER"])
