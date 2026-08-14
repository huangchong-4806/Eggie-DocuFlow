import unittest
from pathlib import Path

from version import APP_VERSION


ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    def test_v1_4_0_metadata_is_consistent(self):
        self.assertEqual(APP_VERSION, "1.4.0")

        version_text = (ROOT / "version.py").read_text(encoding="utf-8")
        self.assertIn('BUILD_DATE = "2026-08-14"', version_text)

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("EggieDocuFlow_V1.4.0_mac.app", readme)
        self.assertIn("EggieDocuFlow_V1.4.0_mac.zip", readme)
        self.assertIn("EggieDocuFlow_V1.4.0_Windows_x64_Setup.exe", readme)
        self.assertTrue((ROOT / "release_notes_v1.4.0.md").is_file())

        spec = (ROOT / "packaging" / "EggieDocuFlow.spec").read_text(
            encoding="utf-8"
        )
        self.assertIn('"CFBundleVersion": "11"', spec)

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
