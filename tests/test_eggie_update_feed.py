import base64
import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from runpy import run_path
from unittest.mock import patch
from urllib.error import HTTPError

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import eggie_update_feed as feed
from scripts.sign_update_release import publish_manifest, sign_release
from update_check import Release, UpdateCheckError


class SignedUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes_raw()
        self.base = Release("1.5.1", "2026110401")
        self.target = Release("1.5.1", "2026110402")
        self.payloads = {"patch.exe": b"delta", "full.exe": b"full" * 100,
                         "mac.delta": b"delta-mac", "mac.zip": b"full-mac" * 100}
        for name, data in self.payloads.items():
            (self.root / name).write_bytes(data)
        entries = []
        for platform, items in [("windows-x64", ("patch.exe", "full.exe")),
                                ("macos-arm64", ("mac.delta", "mac.zip"))]:
            entries += [{"platform": platform, "kind": "delta", "base": vars(self.base), "filename": items[0]},
                        {"platform": platform, "kind": "full", "base": None, "filename": items[1]}]
        self.spec = {"target": vars(self.target), "assets": entries}
        self.envelope = sign_release(self.spec, self.root, self.key)
        self.assets = feed.verify_manifest(self.envelope, self.public, self.target)

    def replace_payload(self, change, *, sign=True):
        envelope = json.loads(self.envelope)
        manifest = json.loads(base64.b64decode(envelope["payload"]))
        change(manifest)
        data = json.dumps(manifest).encode()
        envelope["payload"] = base64.b64encode(data).decode()
        if sign:
            envelope["signature"] = base64.b64encode(self.key.sign(data)).decode()
        return json.dumps(envelope).encode()

    def test_selects_each_platform_exact_build_and_correct_full_size(self):
        for platform, delta, full in [("macos-arm64", "mac.delta", "mac.zip"),
                                      ("windows-x64", "patch.exe", "full.exe")]:
            selected = feed.select_asset(self.assets, self.base, platform)
            self.assertEqual((selected.kind, selected.filename, selected.size),
                             ("delta", delta, len(self.payloads[delta])))
            fallback = feed.select_asset(self.assets, Release("1.5.0", "2026110401"), platform)
            self.assertEqual((fallback.kind, fallback.filename, fallback.size),
                             ("full", full, len(self.payloads[full])))
        with self.assertRaises(UpdateCheckError):
            feed.select_asset(self.assets, self.target, "windows-x64")

    def test_mismatched_key_target_tampering_and_oversize_rejected(self):
        forged = self.replace_payload(lambda m: m["assets"][0].update(size=1), sign=False)
        for envelope, key, target in [
                (forged, self.public, self.target),
                (self.envelope, Ed25519PrivateKey.generate().public_key().public_bytes_raw(), self.target),
                (self.envelope, self.public, self.base),
                (b" " * (feed.MAX_MANIFEST_SIZE + 1), self.public, self.target),
                (b'{"payload":"a","payload":"b","signature":"c"}', self.public, self.target)]:
            with self.assertRaises(UpdateCheckError):
                feed.verify_manifest(envelope, key, target)

    def test_even_signed_invalid_fields_and_ambiguous_assets_are_rejected(self):
        changes = [
            lambda m: m["assets"][0].update(url="https://evil.example/patch.exe"),
            lambda m: m["assets"][0].update(kind="full"),
            lambda m: m["assets"][0].update(base=m["target"]),
            lambda m: m["assets"][0].update(sha256="x" * 64),
            lambda m: m["assets"][0].update(size=True),
            lambda m: m["assets"][0].update(filename="../outside.exe"),
            lambda m: m["assets"][0].update(filename="CON.exe"),
            lambda m: m["assets"][0].update(platform="windows-arm64"),
            lambda m: m["assets"].append(m["assets"][0]),
            lambda m: m["assets"].pop(1),
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(UpdateCheckError):
                feed.verify_manifest(self.replace_payload(change), self.public, self.target)

    def test_download_verifies_manifest_and_preserves_files(self):
        data = self.payloads["patch.exe"]
        selected = feed.select_asset(self.assets, self.base, "windows-x64")
        existing = self.root / "patch.exe"
        progress = []
        with patch.object(feed, "read_update_public_key", return_value=self.public), \
             patch.object(feed, "_open", return_value=BytesIO(data)) as request:
            path = feed.download_asset(selected, self.root, lambda n, t: progress.append((n, t)))
            self.assertEqual(request.call_args.args, (selected.url,))
        self.assertEqual(path.name, "patch.exe")
        self.assertNotEqual(path, existing)
        self.assertEqual(path.read_bytes(), existing.read_bytes())
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), selected.sha256)
        self.assertEqual(progress[-1], (len(data), len(data)))
        with patch.object(feed, "read_update_public_key", return_value=self.public), \
             patch.object(feed, "_open") as request, self.assertRaises(UpdateCheckError):
            feed.download_asset(replace(selected, filename="../fake.exe"), self.root)
        request.assert_not_called()

    def test_failed_download_preserves_existing_files_and_cleans_partial(self):
        selected = self.assets[0]
        expected = sorted(self.root.iterdir())
        for content in [b"", b"other", b"toolong"]:
            with patch.object(feed, "read_update_public_key", return_value=self.public), \
                 patch.object(feed, "_open", return_value=BytesIO(content)), self.assertRaises(UpdateCheckError):
                feed.download_asset(selected, self.root)
            self.assertEqual(sorted(self.root.iterdir()), expected)
        with patch.object(feed, "read_update_public_key", return_value=self.public), \
             patch.object(feed, "_open", side_effect=TimeoutError()), self.assertRaises(UpdateCheckError):
            feed.download_asset(selected, self.root)
        self.assertEqual(sorted(self.root.iterdir()), expected)

    def test_local_key_never_taken_from_runtime_environment(self):
        pub = self.root / feed.PUBLIC_KEY_FILENAME
        pub.write_bytes(base64.b64encode(self.public))
        bundle = self.root / "app"
        bundle.mkdir()
        with patch.object(feed.sys, "_MEIPASS", str(bundle), create=True), \
             patch.dict(os.environ, {"EGGIE_UPDATE_PUBLIC_KEY_FILE": str(pub)}):
            self.assertIsNone(feed.read_update_public_key())
            (bundle / pub.name).write_bytes(pub.read_bytes())
            self.assertEqual(feed.read_update_public_key(), self.public)
            (bundle / pub.name).write_text("malformed")
            with self.assertRaises(UpdateCheckError):
                feed.read_update_public_key()
        package = run_path(str(Path(__file__).resolve().parents[1] / "packaging/update_trust.py"))
        with patch.dict(os.environ, {"EGGIE_UPDATE_PUBLIC_KEY_FILE": str(pub)}):
            self.assertEqual(package["build_trust_data"]({"BUILD_TYPE": "release", "APP_VERSION": "1.6.0",
                                                          "BUILD_NUMBER": "2026110501"}),
                             [(str(pub.resolve()), ".")])

    def test_new_release_or_candidate_needs_pinned_key_on_both_platforms(self):
        root = Path(__file__).resolve().parents[1]
        build_trust_data = run_path(str(root / "packaging/update_trust.py"))["build_trust_data"]
        with patch.dict(os.environ, {"EGGIE_UPDATE_PUBLIC_KEY_FILE": ""}):
            historical = dict(BUILD_TYPE="release", APP_VERSION="1.5.1", BUILD_NUMBER="2026110402")
            self.assertEqual(build_trust_data(historical), [])
            self.assertEqual(build_trust_data(dict(historical, BUILD_NUMBER="2026110401")), [])
            for kind in ("release", "release_candidate", "unrecognised"):
                with self.assertRaisesRegex(ValueError, "EGGIE_UPDATE_PUBLIC_KEY_FILE"):
                    build_trust_data(dict(historical, BUILD_TYPE=kind, BUILD_NUMBER="2026110501"))
            self.assertEqual(build_trust_data(dict(historical, BUILD_TYPE="development", APP_VERSION="1.6.0")), [])
        for name in ("EggieDocuFlow.spec", "EggieDocuFlow_windows.spec"):
            spec = (root / "packaging" / name).read_text()
            self.assertIn("build_trust_data(", spec)
            self.assertIn("version.py", spec)
            self.assertNotIn("build_trust_data(),", spec)

    def test_manifest_write_failure_leaves_no_partial_or_overwritten_record(self):
        folder = self.root / "publication"
        folder.mkdir()
        destination = folder / feed.MANIFEST_FILENAME
        with patch("scripts.sign_update_release.os.fsync", side_effect=OSError("disk full")), self.assertRaises(OSError):
            publish_manifest(self.envelope, destination)
        self.assertEqual(list(folder.iterdir()), [])
        publish_manifest(self.envelope, destination)
        with self.assertRaises(FileExistsError):
            publish_manifest(b"another record", destination)
        self.assertEqual(list(folder.iterdir()), [destination])
        self.assertEqual(destination.read_bytes(), self.envelope)

    def test_signed_download_route_and_legacy_only_fallback(self):
        with patch.object(feed, "read_update_public_key", return_value=self.public), \
             patch.object(feed, "_open", return_value=BytesIO(self.envelope)) as read:
            selected = feed.fetch_update_asset(self.base, self.target, "windows-x64")
            self.assertEqual(selected, self.assets[0])
            self.assertEqual(read.call_args.args, (feed.asset_url(self.target, feed.MANIFEST_FILENAME),))
        with patch.object(feed, "read_update_public_key", return_value=self.public), \
             patch.object(feed, "_open", side_effect=HTTPError("https://example.com", 404, "Not Found", {}, None)):
            self.assertIsNone(feed.fetch_update_asset(self.base, self.target, "macos-arm64"))
            with self.assertRaises(UpdateCheckError):
                feed.fetch_update_asset(self.base, Release("1.5.2", "2026110501"), "macos-arm64")
        with patch.object(feed, "read_update_public_key", return_value=None), patch.object(feed, "_open") as read:
            self.assertIsNone(feed.fetch_update_asset(self.base, self.target, "windows-x64"))
            read.assert_not_called()

    def test_redirects_reject_other_urls_before_requesting_them(self):
        origin = self.assets[0].url
        self.assertTrue(feed._allowed_response(origin, origin))
        self.assertTrue(feed._allowed_response("https://release-assets.githubusercontent.com/github-production/x?sig=a", origin))
        guard = feed._ReleaseRedirects(origin)
        for url in ["http://release-assets.githubusercontent.com/x",
                    "https://evil.com/x", "https://github.com/other/repository/x",
                    "https://release-assets.githubusercontent.com@evil.test/a",
                    "https://release-assets.githubusercontent.com:8080/a"]:
            with self.assertRaises(UpdateCheckError):
                guard.redirect_request(None, None, 302, None, {}, url)


if __name__ == "__main__":
    unittest.main()
