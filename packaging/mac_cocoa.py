"""Select a locally rebuilt, pinned Qt Cocoa accessibility repair for packaging."""
import hashlib
import json
from pathlib import Path

QT_VERSION = "6.10.3"
FIX_COMMIT = "8148c48deb8e4345bacb797cb75c011df6f797fa"
INPUT_HASHES = {
    "qtbase-source.tar.xz": "383dc907816338f0cba72088a524c07458dfc69ce684ca9132fcc4fe91c24b0b",
    "qtbase-sdk.7z": "998227b59cfa2c59b063bbfddeefff312d74fa99da1647544df87a14ffa4bb77",
    "QTBUG-149612.patch": "965901a92183c9dc1834717587725b1c375a7965ad7e6adc56633543d2c464ca",
}
PLUGIN_DESTINATION = "PySide6/Qt/plugins/platforms/libqcocoa.dylib"


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verified_component(directory, pyside_version):
    if pyside_version != QT_VERSION:
        raise ValueError("The Cocoa repair must be reviewed again when changing PySide6/Qt versions")
    if not directory:
        raise ValueError("Set EGGIE_QT_COCOA_REPAIR_DIR to the output of scripts/build_mac_cocoa.py")
    directory = Path(directory).resolve()
    report = directory / "cocoa-repair.json"
    metadata = json.loads(report.read_text(encoding="utf-8"))
    if (metadata.get("qt_version") != QT_VERSION or metadata.get("fix_commit") != FIX_COMMIT
            or metadata.get("architecture") != "arm64" or metadata.get("inputs") != INPUT_HASHES):
        raise ValueError("Cocoa repair provenance does not match the approved Qt backport")
    recipe = Path(__file__).parent / "macos/qt-cocoa/CMakeLists.txt"
    if metadata.get("cmake_recipe_sha256") != sha256(recipe):
        raise ValueError("Cocoa repair must be rebuilt after changing its CMake recipe")
    library = directory / "libqcocoa.dylib"
    if library.is_symlink() or sha256(library) != metadata.get("library_sha256"):
        raise ValueError("Cocoa repair library is missing or has changed since its build")
    return library, report


def replace_cocoa_binary(entries, library):
    matches = [e for e in entries if e[0].replace("\\", "/") == PLUGIN_DESTINATION]
    if len(matches) != 1 or matches[0][2] != "BINARY":
        raise ValueError("Expected exactly one Qt Cocoa platform plugin in the Mac bundle")
    return [(e[0], str(library), e[2]) if e[0].replace("\\", "/") == PLUGIN_DESTINATION
            else e for e in entries]
