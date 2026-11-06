import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from scripts.build_windows_update import APP_ID, EXE, STAMP, build_delta, read_stamp, write_stamp


class WindowsDeltaBuildTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.old = self.root / "old"
        self.new = self.root / "new"
        for folder in (self.old, self.new):
            (folder / "_internal").mkdir(parents=True)
            (folder / "_internal/stable.dll").write_bytes(b"fixed library")
            (folder / EXE).write_bytes(b"A" if folder == self.old else b"B")
        (self.old / "_internal/retired.dll").write_bytes(b"old lib")
        (self.new / "_internal/new.dll").write_bytes(b"new lib")
        self.out = self.root / "delta"
        self.stamp_both()

    def stamp_both(self):
        write_stamp(self.old, "1.5.1", "2026110402")
        write_stamp(self.new, "1.6.0", "2026110403")

    def test_exact_inventory_and_idempotent_stamp(self):
        write_stamp(self.old, "1.5.1", "2026110402")
        (self.old / "unins000.exe").write_bytes(b"uninstaller")
        record, digest = read_stamp(self.old)
        self.assertEqual(set(record["files"]), {EXE, "_internal/stable.dll", "_internal/retired.dll"})
        self.assertEqual(digest, hashlib.sha256((self.old / STAMP).read_bytes()).hexdigest())
        (self.old / EXE).write_bytes(b"user modification")
        with self.assertRaisesRegex(ValueError, "differs"):
            write_stamp(self.old, "1.5.1", "2026110402")
        with self.assertRaisesRegex(ValueError, "differ"):
            read_stamp(self.old)

    def test_only_changed_bytes_and_complete_result_can_be_reconstructed(self):
        self.assertEqual(build_delta(self.old, self.new, self.out), (2, 1))
        payload = self.out / "payload"
        files = {f.relative_to(payload).as_posix() for f in payload.rglob("*") if f.is_file()}
        self.assertEqual(files, {EXE, "_internal/new.dll", STAMP})
        self.assertFalse((payload / EXE).samefile(self.new / EXE))
        baseline = self.root / "applied"
        shutil.copytree(self.old, baseline)
        (baseline / "_internal/retired.dll").unlink()
        shutil.copytree(payload, baseline, dirs_exist_ok=True)
        self.assertEqual(read_stamp(baseline), read_stamp(self.new))
        with self.assertRaisesRegex(ValueError, "unused"):
            build_delta(self.old, self.new, self.out)
        self.assertFalse(any(self.root.glob(".eggie-delta-*")))

    def test_delta_gates_standalone_use_and_never_deletes_unmanaged_names(self):
        build_delta(self.old, self.new, self.out)
        script = (self.out / "patch.iss").read_text(encoding="utf-8-sig")
        self.assertIn("AppId=" + APP_ID, script)
        self.assertIn("PrivilegesRequired=admin", script)
        self.assertIn("function PrepareToInstall", script)
        self.assertIn("if Work = '' then exit", script)
        self.assertIn("ValidWorkFolder(ExtractFileName(Work))", script)
        self.assertIn("rollback.json", script)
        record, oldhash = read_stamp(self.old)
        self.assertIn(f"MatchesAt(Backup, 'eggie-runtime.json', '{oldhash}')", script)
        for name, checksum in record["files"].items():
            name = name.replace("/", "\\")
            self.assertIn(f"Matches('{name}', '{checksum}')", script)
            self.assertIn(f"MatchesAt(Backup, '{name}', '{checksum}')", script)
        self.assertIn("AvailablePath('_internal\\new.dll')", script)
        self.assertIn("BeforeInstall: RequireAbsent('Eggie DocuFlow.exe')", script)
        self.assertIn("if not AvailablePath('_internal\\retired.dll') then exit;", script)
        self.assertIn("Type: files;", script)
        self.assertNotIn("Type: filesandordirs", script)
        self.assertNotIn('Name: "{app}\\*"', script)
        self.assertNotIn("@VERIFY", script)

    def test_downgrade_file_directory_and_unsafe_links_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "newer"):
            build_delta(self.new, self.old, self.out)
        (self.new / STAMP).unlink()
        (self.new / "_internal/retired.dll").mkdir()
        (self.new / "_internal/retired.dll/file").write_bytes(b"data")
        write_stamp(self.new, "1.6.0", "2026110403")
        with self.assertRaisesRegex(ValueError, "conflict"):
            build_delta(self.old, self.new, self.out)
        self.assertFalse(self.out.exists())
        (self.new / "customer.xlsx").write_bytes(b"must never become a runtime file")
        with self.assertRaisesRegex(ValueError, "clean PyInstaller"):
            read_stamp(self.new)

    def test_does_not_follow_runtime_links(self):
        target = self.root / "user-data"
        target.write_bytes(b"preserve")
        try:
            (self.new / "_internal/link.dll").symlink_to(target)
        except OSError:
            self.skipTest("Creating symlinks requires permission on this Windows host")
        with self.assertRaisesRegex(ValueError, "link"):
            read_stamp(self.new)
        self.assertEqual(target.read_bytes(), b"preserve")

    def test_reject_tampered_or_missing_stamp(self):
        original = (self.new / STAMP).read_bytes()
        altered = json.loads(original)
        altered["files"]["_internal/stable.dll"] = "0" * 64
        (self.new / STAMP).write_text(json.dumps(altered))
        with self.assertRaisesRegex(ValueError, "differ"):
            build_delta(self.old, self.new, self.out)
        self.assertFalse(self.out.exists())
        (self.new / STAMP).unlink()
        with self.assertRaises(FileNotFoundError):
            build_delta(self.old, self.new, self.out)


if __name__ == "__main__":
    unittest.main()
