import unittest
from pathlib import Path

from version import APP_VERSION


ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    def test_v1_3_6_metadata_is_consistent(self):
        self.assertEqual(APP_VERSION, "1.3.6")

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("EggieDocuFlow_V1.3.6_mac.app", readme)
        self.assertIn("EggieDocuFlow_V1.3.6_mac.zip", readme)

        spec = (ROOT / "packaging" / "EggieDocuFlow.spec").read_text(
            encoding="utf-8"
        )
        self.assertIn('"CFBundleVersion": "10"', spec)


if __name__ == "__main__":
    unittest.main()
