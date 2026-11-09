# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os
import subprocess
import sys
from importlib.metadata import version as distribution_version
from runpy import run_path
from PyInstaller.utils.hooks import copy_metadata


PROJECT_ROOT = Path(SPECPATH).parent
build_trust_data = run_path(str(PROJECT_ROOT / "packaging" / "update_trust.py"))["build_trust_data"]
cocoa_repair = run_path(str(PROJECT_ROOT / "packaging" / "mac_cocoa.py"))
APP_BASENAME = "Eggie DocuFlow"
version_scope = {}
exec((PROJECT_ROOT / "version.py").read_text(encoding="utf-8"), version_scope)
APP_VERSION = version_scope["APP_VERSION"]
LICENSE_METADATA = []
for package in ("openpyxl", "xlrd", "pdfplumber", "pypdf", "Pillow", "pypdfium2", "PyMuPDF",
                "PySide6-Essentials", "alibabacloud_ocr_api20210707"):
    LICENSE_METADATA += copy_metadata(package, recursive=True)

EXCLUDED_BINARY_PATHS = {
    "PySide6/QtNetwork.abi3.so",
    "PySide6/QtDBus.abi3.so",
}
EXCLUDED_BINARY_PREFIXES = (
    "PySide6/Qt/lib/QtNetwork.framework/",
    "PySide6/Qt/lib/QtSvg.framework/",
    "PySide6/Qt/plugins/generic/",
    "PySide6/Qt/plugins/iconengines/",
    "PySide6/Qt/plugins/imageformats/",
    "PySide6/Qt/plugins/networkinformation/",
    "PySide6/Qt/plugins/tls/",
)
EXCLUDED_PLATFORM_PLUGINS = {
    "PySide6/Qt/plugins/platforms/libqminimal.dylib",
    "PySide6/Qt/plugins/platforms/libqoffscreen.dylib",
}
EXCLUDED_DATA_PATHS = {
    "QtNetwork",
    "QtSvg",
}
EXCLUDED_DATA_PREFIXES = (
    "PySide6/Qt/lib/QtNetwork.framework/",
    "PySide6/Qt/lib/QtSvg.framework/",
)


def keep_binary(entry):
    destination = entry[0].replace("\\", "/")
    if destination in EXCLUDED_BINARY_PATHS:
        return False
    if destination in EXCLUDED_PLATFORM_PLUGINS:
        return False
    return not destination.startswith(EXCLUDED_BINARY_PREFIXES)


def keep_data(entry):
    destination = entry[0].replace("\\", "/")
    if destination in EXCLUDED_DATA_PATHS:
        return False
    if destination.startswith(EXCLUDED_DATA_PREFIXES):
        return False

    translations_prefix = "PySide6/Qt/translations/"
    if not destination.startswith(translations_prefix):
        return True

    filename = destination.rsplit("/", 1)[-1]
    return filename.startswith("qtbase_")


# CI smoke packages skip the local Cocoa repair, release signing key, and updater.
# They are not a substitute for the signed, notarized, or ad-hoc release build.
CI_UNSIGNED = os.environ.get("EGGIE_CI_UNSIGNED") == "1"
mac_update_binaries = []
mac_update_notices = []
if CI_UNSIGNED:
    cocoa_library = cocoa_report = None
    trust_data = []
elif os.environ.get("EGGIE_UPDATE_PUBLIC_KEY_FILE"):
    cocoa_library, cocoa_report = cocoa_repair["verified_component"](
        os.environ.get("EGGIE_QT_COCOA_REPAIR_DIR"), distribution_version("PySide6-Essentials"),
    )
    trust_data = build_trust_data(version_scope)
    tools_dir = Path(workpath) / "eggie-mac-update-tools"
    subprocess.run([sys.executable, PROJECT_ROOT / "scripts/prepare_mac_updater.py", tools_dir], check=True)
    mac_update_binaries = [(str(tools_dir / name), "update-tools")
                           for name in ("BinaryDelta", "EggieUpdateHelper")]
    mac_update_notices = [(str(tools_dir / "Sparkle-LICENSE.txt"), "licenses/sparkle")]
else:
    cocoa_library, cocoa_report = cocoa_repair["verified_component"](
        os.environ.get("EGGIE_QT_COCOA_REPAIR_DIR"), distribution_version("PySide6-Essentials"),
    )
    trust_data = build_trust_data(version_scope)


a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=mac_update_binaries,
    datas=[
        (str(PROJECT_ROOT / "LICENSE"), "."),
        (str(PROJECT_ROOT / "THIRD_PARTY_NOTICES.md"), "."),
        (str(PROJECT_ROOT / f"release_notes_v{APP_VERSION}.md"), "."),
        (str(PROJECT_ROOT / "BUILD_RELEASE.md"), "."),
        (str(PROJECT_ROOT / "licenses"), "licenses"),
        (str(PROJECT_ROOT / "packaging/macos/qt-cocoa"), "licenses/qt-cocoa"),
        (str(PROJECT_ROOT / "assets" / "software_logo.png"), "assets"),
        (str(PROJECT_ROOT / "assets" / "app_icon.png"), "assets"),
        (str(PROJECT_ROOT / "assets" / "app_icon.icns"), "assets"),
        (str(PROJECT_ROOT / "docs" / "OCR使用说明.pdf"), "docs"),
        (
            str(PROJECT_ROOT / "assets" / "en.lproj" / "InfoPlist.strings"),
            "en.lproj",
        ),
        (
            str(PROJECT_ROOT / "assets" / "zh-Hans.lproj" / "InfoPlist.strings"),
            "zh-Hans.lproj",
        ),
        (
            str(PROJECT_ROOT / "assets" / "zh-Hant.lproj" / "InfoPlist.strings"),
            "zh-Hant.lproj",
        ),
    ] + ([(str(cocoa_report), "licenses/qt-cocoa")] if cocoa_report else []) + mac_update_notices + LICENSE_METADATA + trust_data,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6.QtNetwork",
        "PySide6.QtDBus",
        "PySide6.QtSvg",
    ],
    noarchive=False,
    optimize=1,
)
a.binaries = [entry for entry in a.binaries if keep_binary(entry)]
if cocoa_library is not None:
    a.binaries = cocoa_repair["replace_cocoa_binary"](a.binaries, cocoa_library)
a.datas = [entry for entry in a.datas if keep_data(entry)]

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
    strip=True,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=True,
    upx=False,
    name=APP_BASENAME,
)

app = BUNDLE(
    coll,
    name=f"{APP_BASENAME}.app",
    icon=str(PROJECT_ROOT / "assets" / "app_icon.icns"),
    bundle_identifier="com.huang.eggiedocuflow",
    version=APP_VERSION,
    info_plist={
        "CFBundleDisplayName": APP_BASENAME,
        "CFBundleName": APP_BASENAME,
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": version_scope["BUILD_NUMBER"],
        "CFBundleAllowMixedLocalizations": True,
        "CFBundleDevelopmentRegion": "zh-Hans",
        "CFBundleLocalizations": ["en", "zh-Hans", "zh-Hant"],
        "LSHasLocalizedDisplayName": True,
        "LSMinimumSystemVersion": "15.0",
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "PDF Document",
                "CFBundleTypeExtensions": ["pdf"],
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
            }
        ],
    },
)
