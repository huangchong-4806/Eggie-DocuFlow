"""Public download instructions and local links must survive a release update."""
import re
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

from version import APP_VERSION


ROOT = Path(__file__).resolve().parents[1]


class PublicDocumentationTests(unittest.TestCase):
    def test_public_documents_do_not_link_to_missing_files(self):
        docs = [ROOT / name for name in ("README.md", "BUILD_RELEASE.md", "SECURITY.md", "THIRD_PARTY_NOTICES.md")]
        docs.extend((ROOT / "licenses/pdfium").glob("*/libjpeg_turbo.md"))
        for doc in docs:
            for target in re.findall(r"\[[^\]\n]*\]\(([^)\n]+)\)", doc.read_text(encoding="utf-8")):
                url = urlsplit(target)
                if url.scheme or url.netloc or not url.path:
                    continue
                with self.subTest(document=doc.name, target=target):
                    self.assertTrue((doc.parent / unquote(url.path)).is_file())

    def test_download_buttons_and_checksum_examples_name_the_current_packages(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        for suffix in ("mac_arm64.zip", "Windows_x64_Setup.exe"):
            name = f"EggieDocuFlow_V{APP_VERSION}_{suffix}"
            self.assertIn(f"/releases/download/v{APP_VERSION}/{name}", readme)
            self.assertIn(name, security)
