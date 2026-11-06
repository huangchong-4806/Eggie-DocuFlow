import json
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zipfile import ZipFile, ZipInfo

from eggie_update_mac import (
    BUNDLE_ID, EXECUTABLE, _archive_app, _cdhash, _copy_verified, confirm_healthy_startup,
    discard_update, installed_bundle, prepare_update, launch_update,
)
from update_check import DeltaNotApplicable, Release, UpdateCheckError


class MacUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / "Eggie DocuFlow.app"
        (self.app / "Contents").mkdir(parents=True)
        (self.app / "Contents/Info.plist").write_bytes(plistlib.dumps({
            "CFBundleIdentifier": BUNDLE_ID, "CFBundleExecutable": EXECUTABLE,
            "CFBundleShortVersionString": "1.5.2", "CFBundleVersion": "2026110491",
        }))
        self.old = Release("1.5.2", "2026110491")
        self.target = Release("1.5.2", "2026110492")
        self.asset = SimpleNamespace(platform="macos-arm64", kind="delta", target=self.target,
                                     base=self.old, signed_manifest=b"signed")

    def test_source_mode_cannot_target_an_application(self):
        with patch.object(sys, "frozen", False, create=True):
            self.assertIsNone(installed_bundle())

    def test_source_mismatch_can_offer_full_package_only_after_authentication(self):
        self.asset.base = Release("1.5.1", "2026110402")
        with patch("eggie_update_mac.installed_bundle", return_value=self.app), \
             patch("eggie_update_feed.read_update_public_key", return_value=b"key"):
            with patch("eggie_update_feed.verify_manifest", return_value=()):
                with self.assertRaisesRegex(UpdateCheckError, "发布签名"):
                    prepare_update("unused", self.asset, self.target)
            with patch("eggie_update_feed.verify_manifest", return_value=(self.asset,)):
                with self.assertRaises(DeltaNotApplicable):
                    prepare_update("unused", self.asset, self.target)
        self.assertFalse(list(self.root.glob(".eggie-update-*")))

    def test_full_archive_rejects_outside_paths_and_escaping_links(self):
        archive = self.root / "test.zip"
        for filename in ("Foo.app/../../escape", "/absolute", "Foo.app//wrong"):
            with self.subTest(filename=filename):
                with ZipFile(archive, "w") as output:
                    output.writestr(filename, b"bad")
                with self.assertRaises(UpdateCheckError):
                    _archive_app(archive)
        link = ZipInfo("Foo.app/Contents/link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with ZipFile(archive, "w") as output:
            output.writestr(link, "../../outside")
        with self.assertRaises(UpdateCheckError):
            _archive_app(archive)
        with ZipFile(archive, "w") as output:
            output.writestr("Foo.app/Contents/Resources/valid", b"x")
            output.writestr(link, "Resources/valid")
        self.assertEqual(_archive_app(archive), "Foo.app")

    def test_tampered_payload_is_not_used(self):
        src = self.root / "delta"
        src.write_bytes(b"changed")
        with self.assertRaisesRegex(UpdateCheckError, "校验"):
            _copy_verified(src, self.root / "staged", SimpleNamespace(size=7, sha256="0"*64))

    @unittest.skipUnless(sys.platform == "darwin", "Mac acknowledgment uses a private POSIX directory")
    def test_acknowledgment_only_in_a_private_sibling_without_symlinks(self):
        stage = self.app.parent / "Eggie 更新恢复-abcdefgh.noindex"
        stage.mkdir(mode=0o700)
        nonce = "abcabcab-0000-1111-2222-123456789abc"
        option = "--eggie-update-health=abcdefgh:" + nonce
        with patch("eggie_update_mac.installed_bundle", return_value=self.app), patch.object(sys, "argv", ["app", option]):
            (stage/"ready").symlink_to(self.root/"outside")
            confirm_healthy_startup()
            self.assertFalse((self.root/"outside").exists())
            (stage/"ready").unlink()
            confirm_healthy_startup()
            self.assertEqual((stage/"ready").read_text(), nonce)
            os.chmod(stage, 0o755)
            (stage/"ready").unlink()
            confirm_healthy_startup()
            self.assertFalse((stage/"ready").exists())

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("swiftc"), "Needs native Mac signing and Swift")
    def test_independent_recovery_after_interrupted_swap(self):
        # This is the on-disk state after an atomic exchange and loss of the helper.
        directory = self.root / "Eggie 更新恢复-abcdefgh.noindex"
        directory.mkdir(mode=0o700)
        backup = directory / "保留版本.app"
        compiler_output = self.root / "helper"
        swift = Path(__file__).resolve().parents[1] / "packaging/macos/EggieUpdateHelper.swift"
        subprocess.run(["xcrun", "swiftc", swift, "-o", compiler_output], check=True)
        executable = self.app / "Contents/MacOS" / EXECUTABLE
        executable.parent.mkdir()
        shutil.copy(compiler_output, executable)
        bundled_helper = Path("Contents/Frameworks/update-tools/EggieUpdateHelper")
        (self.app / bundled_helper).parent.mkdir(parents=True)
        shutil.copy(compiler_output, self.app / bundled_helper)
        shutil.copytree(self.app, backup)
        info_file = self.app / "Contents/Info.plist"
        info = plistlib.loads(info_file.read_bytes())
        info["CFBundleVersion"] = "2026110492"
        info_file.write_bytes(plistlib.dumps(info))
        for app in (self.app, backup):
            subprocess.run(["codesign", "--force", "--deep", "--sign", "-", app],
                           check=True, capture_output=True)
        before, after = _cdhash(backup), _cdhash(self.app)
        self.assertNotEqual(before, after)
        (directory / "recovery.json").write_text(json.dumps({
            "name": self.app.name, "previousHash": before, "targetHash": after,
        }))
        extra = directory / "用户自存内容"
        extra.write_bytes(b"keep")
        subprocess.run([backup / bundled_helper, "--recover-no-launch"], check=True)
        self.assertEqual(_cdhash(self.app), before)
        self.assertEqual(list(directory.iterdir()), [extra])
        self.assertEqual(extra.read_bytes(), b"keep")

    def test_discard_keeps_unrelated_siblings(self):
        unrelated = self.root / "other"
        unrelated.mkdir()
        discard_update(SimpleNamespace(installed=self.app, staging=unrelated))
        self.assertTrue(unrelated.is_dir())

    def test_running_instance_check_failure_keeps_window_and_prepared_download(self):
        prepared = SimpleNamespace(installed=self.app, staging=self.root / '.eggie-update-abcdefgh')
        prepared.staging.mkdir()
        with patch('eggie_update_mac._checked', side_effect=UpdateCheckError('other instance')), \
             patch('eggie_update_mac.subprocess.Popen') as launch:
            with self.assertRaisesRegex(UpdateCheckError, 'other instance'):
                launch_update(prepared)
        launch.assert_not_called()
        self.assertTrue(prepared.staging.exists())

    def test_handoff_requires_visible_window_acknowledgment(self):
        prepared = SimpleNamespace(installed=self.app, staging=self.root/'.eggie-update-abcdefgh',
                                   old_cdhash='old', new_cdhash='new')
        for ready in (False, True):
            with self.subTest(ready=ready):
                process = MagicMock()
                process.poll.return_value = None
                with patch('eggie_update_mac._checked'), \
                     patch('eggie_update_mac.subprocess.Popen', return_value=process), \
                     patch('eggie_update_mac.select.select', return_value=([process.stdout] if ready else [],[],[])), \
                     patch('eggie_update_mac.os.read', return_value=b'ready\n'):
                    if ready:
                        launch_update(prepared)
                        process.terminate.assert_not_called()
                    else:
                        with self.assertRaisesRegex(UpdateCheckError,'提示窗口'):
                            launch_update(prepared)
                        process.terminate.assert_called_once()
                    process.stdout.close.assert_called_once()

    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('swiftc'), 'Needs native Mac process enumeration')
    def test_native_check_blocks_second_process_but_allows_other_installation(self):
        helper = self.root / 'helper'
        source = Path(__file__).resolve().parents[1] / 'packaging/macos/EggieUpdateHelper.swift'
        subprocess.run(['xcrun', 'swiftc', source, '-o', helper], check=True, capture_output=True)
        executable = self.app / 'Contents/MacOS' / EXECUTABLE
        executable.parent.mkdir()
        subprocess.run(['xcrun', 'clang', '-x', 'c', '-', '-o', executable],
                       input=b'#include <unistd.h>\nint main(){sleep(120);return 0;}\n', check=True, capture_output=True)
        other = self.root / 'Other.app/Contents/MacOS' / EXECUTABLE
        other.parent.mkdir(parents=True)
        shutil.copy2(executable, other)
        processes = [subprocess.Popen([executable]), subprocess.Popen([executable]), subprocess.Popen([other])]
        try:
            args = [helper, '--check-running', self.app, str(processes[0].pid)]
            blocked = subprocess.run(args, capture_output=True, timeout=15)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn('其他 Eggie', blocked.stderr.decode())
            self.assertTrue(all(p.poll() is None for p in processes))
            processes[1].terminate()
            processes[1].wait(timeout=10)
            permitted = subprocess.run(args, capture_output=True, timeout=15)
            self.assertEqual(permitted.returncode, 0, permitted.stderr.decode())
            self.assertIsNone(processes[0].poll())
            self.assertIsNone(processes[2].poll())
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
