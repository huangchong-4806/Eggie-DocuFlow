import json
from pathlib import Path
from runpy import run_path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
repair = run_path(str(ROOT / "packaging/mac_cocoa.py"))


class MacCocoaBuildTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.library = self.folder / "libqcocoa.dylib"
        self.library.write_bytes(b"test-only build component")
        self.report = {
            "qt_version": repair["QT_VERSION"], "fix_commit": repair["FIX_COMMIT"],
            "architecture": "arm64", "inputs": repair["INPUT_HASHES"],
            "library_sha256": repair["sha256"](self.library),
            "cmake_recipe_sha256": repair["sha256"](ROOT / "packaging/macos/qt-cocoa/CMakeLists.txt"),
        }
        self.write_report()

    def write_report(self):
        (self.folder / "cocoa-repair.json").write_text(json.dumps(self.report))

    def test_only_platform_plugin_replaced_and_other_entries_untouched(self):
        library, _ = repair["verified_component"](self.folder, "6.10.3")
        entries = [(repair["PLUGIN_DESTINATION"], "/original/plugin", "BINARY"),
                   ("QtCore", "/original/core", "BINARY")]
        replaced = repair["replace_cocoa_binary"](entries, library)
        self.assertEqual(Path(replaced[0][1]), self.library.resolve())
        self.assertEqual(replaced[1], entries[1])
        self.assertEqual(entries[0][1], "/original/plugin")

    def test_missing_duplicate_or_wrong_kind_platform_plugin_rejected(self):
        item = (repair["PLUGIN_DESTINATION"], "/original/plugin", "BINARY")
        for entries in ([], [item, item], [(item[0], item[1], "DATA")]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                repair["replace_cocoa_binary"](entries, self.library)

    def test_modified_library_and_incompatible_version_rejected(self):
        with self.assertRaises(ValueError):
            repair["verified_component"](self.folder, "6.12.0")
        self.library.write_bytes(b"changed after build")
        with self.assertRaises(ValueError):
            repair["verified_component"](self.folder, "6.10.3")

    def test_wrong_source_patch_or_recipe_rejected(self):
        for key, value in (("fix_commit", "unknown"), ("inputs", {}), ("cmake_recipe_sha256", "changed")):
            original = self.report[key]
            self.report[key] = value
            self.write_report()
            with self.subTest(key=key), self.assertRaises(ValueError):
                repair["verified_component"](self.folder, "6.10.3")
            self.report[key] = original
