import unittest
from pathlib import Path

from version import APP_VERSION


ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    def test_v1_3_12_metadata_is_consistent(self):
        self.assertEqual(APP_VERSION, "1.3.12")

        version_text = (ROOT / "version.py").read_text(encoding="utf-8")
        self.assertIn('BUILD_DATE = "2026-07-23"', version_text)

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("EggieDocuFlow_V1.3.12_mac.app", readme)
        self.assertIn("EggieDocuFlow_V1.3.12_mac.zip", readme)
        self.assertIn("EggieDocuFlow_V1.3.12_Windows_x64_Setup.exe", readme)

        spec = (ROOT / "packaging" / "EggieDocuFlow.spec").read_text(
            encoding="utf-8"
        )
        self.assertIn('"CFBundleVersion": "10"', spec)

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
