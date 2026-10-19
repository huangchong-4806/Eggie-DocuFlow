import unittest
from pathlib import Path

from version import APP_VERSION, BUILD_TYPE, BUILD_DATE


ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    def test_open_source_notices_and_bundled_licenses_are_present(self):
        self.assertIn("Copyright (c) 2026 qq448223855-rgb", (ROOT / "LICENSE").read_text(encoding="utf-8"))
        self.assertIn("GNU AFFERO GENERAL PUBLIC LICENSE", (ROOT / "licenses/AGPL-3.0.txt").read_text(encoding="utf-8"))
        self.assertIn("PyMuPDF", (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8"))
        for spec_name in ("EggieDocuFlow.spec", "EggieDocuFlow_windows.spec"):
            spec = (ROOT / "packaging" / spec_name).read_text(encoding="utf-8")
            self.assertIn("THIRD_PARTY_NOTICES.md", spec)
            self.assertIn("copy_metadata", spec)

    def test_release_version_is_consistent(self):
        self.assertEqual(APP_VERSION, "1.5.0")
        self.assertEqual(BUILD_TYPE, "release")
        self.assertEqual(BUILD_DATE, "2026-10-16")
        spec = (ROOT / "packaging" / "EggieDocuFlow.spec").read_text(encoding="utf-8")
        self.assertIn('"CFBundleVersion": version_scope["BUILD_NUMBER"]', spec)

    def test_release_declares_supported_macos_minimum(self):
        spec = (ROOT / "packaging" / "EggieDocuFlow.spec").read_text(encoding="utf-8")
        self.assertIn('"LSMinimumSystemVersion": "15.0"', spec)

    def test_v1_4_0_historical_downloads_are_preserved(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("EggieDocuFlow_V1.4.0_mac.app", readme)
        self.assertIn("EggieDocuFlow_V1.4.0_mac.zip", readme)
        self.assertIn("EggieDocuFlow_V1.4.0_Windows_x64_Setup.exe", readme)
        self.assertTrue((ROOT / "release_notes_v1.4.0.md").is_file())

        windows_spec = (ROOT / "packaging" / "EggieDocuFlow_windows.spec").read_text(
            encoding="utf-8"
        )
        self.assertIn('APP_BASENAME = "Eggie DocuFlow"', windows_spec)
        self.assertTrue((ROOT / "assets" / "app_icon.ico").is_file())
        installer = (ROOT / "packaging" / "EggieDocuFlow_windows.iss").read_text(
            encoding="utf-8"
        )
        self.assertIn("DefaultDirName={autopf}\\{#MyAppName}", installer)
        self.assertIn("PrivilegesRequired=admin", installer)


if __name__ == "__main__":
    unittest.main()
