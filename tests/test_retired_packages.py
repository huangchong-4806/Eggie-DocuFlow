import unittest
from pathlib import Path

from retired_packages import is_retired_package, remove_retired_packages


class RetiredPackageTests(unittest.TestCase):
    def test_only_old_v2_packages_are_removed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            install = Path(folder)
            package = install / "v2"
            package.mkdir()
            (package / "__init__.py").write_text("old = True\n", encoding="utf-8")
            (package / "batch_engine.py").write_text("x = 1\n", encoding="utf-8")
            internal = install / "_internal" / "v2"
            internal.mkdir(parents=True)
            (internal / "__init__.cpython-312.pyc").write_bytes(b"pyc")
            personal = install / "v2-notes"
            personal.mkdir()
            (personal / "发票.xlsx").write_bytes(b"keep")
            loose = install / "_internal" / "customer"
            loose.mkdir()
            (loose / "notes.txt").write_text("keep", encoding="utf-8")
            self.assertTrue(is_retired_package(package))
            self.assertFalse(is_retired_package(personal))
            removed = remove_retired_packages(install)
            self.assertEqual(removed, ("v2", "_internal/v2"))
            self.assertFalse(package.exists())
            self.assertFalse(internal.exists())
            self.assertEqual((personal / "发票.xlsx").read_bytes(), b"keep")
            self.assertTrue((loose / "notes.txt").is_file())
            self.assertEqual(remove_retired_packages(install), ())

    def test_installer_and_update_worker_name_the_same_directories(self):
        root = Path(__file__).resolve().parents[1]
        installer = (root / "packaging/EggieDocuFlow_windows.iss").read_text(encoding="utf-8")
        worker = (root / "windows_update_worker.py").read_text(encoding="utf-8")
        self.assertIn('Name: "{app}\\v2"; Check: RetiredPackageDir(\'v2\')', installer)
        self.assertIn('Name: "{app}\\_internal\\v2"', installer)
        self.assertIn("__init__.py", installer)
        self.assertIn("Remove-RetiredPackage 'v2'", worker)
        self.assertIn("Remove-RetiredPackage '_internal\\v2'", worker)
        self.assertIn("__init__.cpython-", worker)

    def test_mac_ci_package_stays_unsigned(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "scripts/package_unsigned_mac.sh").read_text(encoding="utf-8")
        spec = (root / "packaging/EggieDocuFlow.spec").read_text(encoding="utf-8")
        self.assertIn("EGGIE_CI_UNSIGNED", script)
        self.assertNotIn("codesign", script)
        self.assertNotIn("notarytool", script)
        self.assertIn("EGGIE_CI_UNSIGNED", spec)
        self.assertIn("build_trust_data(", spec)
        self.assertFalse((root / "v2").exists())
        self.assertTrue((root / "layout_batch" / "__init__.py").is_file())
        workflow = (root / ".github/workflows/package.yml").read_text(encoding="utf-8")
        self.assertIn("SHA256SUMS.txt", workflow)
        self.assertNotIn("notarytool", workflow)
        self.assertNotIn("codesign", workflow)
