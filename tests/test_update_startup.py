import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import eggie_update_startup as startup


class StartupGateTests(unittest.TestCase):
    def test_development_and_component_checks_do_not_open_progress(self):
        with patch.object(sys, 'frozen', False, create=True):
            self.assertFalse(startup.startup_is_blocked())
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'argv', ['app', '--check-install']):
            self.assertFalse(startup.startup_is_blocked())

    def test_windows_repeat_signals_current_progress_and_releases_handles(self):
        libs = MagicMock()
        libs.kernel32.WaitForSingleObject.return_value = 258
        with patch.object(startup.ctypes, 'windll', libs, create=True), \
             patch.object(startup, '_windows_event', side_effect=[81, 82]) as opened:
            self.assertTrue(startup.windows_update_active('/one/Eggie', []))
        self.assertEqual(opened.call_args_list[1].args[0], startup.windows_gate_name('/one/Eggie')+'-show')
        self.assertEqual(libs.kernel32.SetEvent.call_args.args[0].value, 82)
        self.assertEqual([c.args[0].value for c in libs.kernel32.CloseHandle.call_args_list], [82, 81])
        self.assertNotEqual(startup.windows_gate_name('/one/Eggie'), startup.windows_gate_name('/two/Eggie'))

    def test_windows_internal_restart_requires_live_permit_event(self):
        option = '--eggie-update-launch='+'a'*32
        libs = MagicMock()
        libs.kernel32.WaitForSingleObject.return_value = 258
        with patch.object(startup.ctypes, 'windll', libs, create=True):
            with patch.object(startup, '_windows_event', return_value=81):
                self.assertFalse(startup.windows_update_active('/one/Eggie', [option]))
            with patch.object(startup, '_windows_event', side_effect=[None,81,82]):
                self.assertTrue(startup.windows_update_active('/one/Eggie', [option]))
            with patch.object(startup, '_windows_event', return_value=None):
                self.assertFalse(startup.windows_update_active('/other/Eggie', []))
            libs.kernel32.WaitForSingleObject.return_value = 0
            with patch.object(startup, '_windows_event', return_value=81):
                self.assertFalse(startup.windows_update_active('/one/Eggie', []))

    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('swiftc'), 'Requires Mac file locking and native helper')
    def test_mac_guard_live_stale_permit_other_install_and_symlink(self):
        import fcntl
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            helper = root/'helper'
            source = Path(__file__).resolve().parents[1]/'packaging/macos/EggieUpdateHelper.swift'
            subprocess.run(['xcrun','swiftc',source,'-o',helper], check=True, capture_output=True)
            app = root/'Eggie.app'
            digest = hashlib.sha256(str(app).encode()).hexdigest()
            lock = root/('.eggie-progress-'+digest+'.lock')
            def probe(target=app, permit=''):
                return subprocess.run([helper,'--guard-launch',target,permit], timeout=10,
                                      capture_output=True).returncode
            self.assertEqual(probe(), 0)
            with lock.open('w+') as stream:
                os.chmod(lock,0o600)
                stream.write(json.dumps({'permit':'--eggie-update-health=test'}));stream.flush()
                fcntl.flock(stream, fcntl.LOCK_EX)
                self.assertEqual(probe(),75)
                self.assertEqual(probe(permit='--eggie-update-health=wrong'),75)
                self.assertEqual(probe(permit='--eggie-update-health=test'),0)
                self.assertEqual(probe(root/'Other.app'),0)
            self.assertEqual(probe(),0)  # Stale record cannot trap future launches.
            # EACCES is also what a second account sees for the former owner's
            # private 0600 record. Exercise the real helper without changing users.
            os.chmod(lock,0)
            try:
                directory = os.open(root, os.O_RDONLY)
                try:
                    fcntl.flock(directory, fcntl.LOCK_EX)
                    self.assertEqual(probe(),75)  # Still updating: never bypass.
                    fcntl.flock(directory, fcntl.LOCK_UN)
                    self.assertEqual(probe(),0)  # Killed helper: kernel released it.
                    self.assertEqual(lock.stat().st_mode & 0o777,0)
                finally:
                    os.close(directory)
            finally:
                os.chmod(lock,0o600)
            lock.unlink()
            lock.symlink_to(root/'outside')
            self.assertEqual(probe(),75)
            self.assertFalse((root/'outside').exists())

    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('swiftc'), 'Requires native Mac updater')
    def test_mac_unreadable_gate_is_live_during_handoff_and_stale_after_helper_exit(self):
        import select
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            helper = root/'helper'
            source = Path(__file__).resolve().parents[1]/'packaging/macos/EggieUpdateHelper.swift'
            subprocess.run(['xcrun','swiftc',source,'-o',helper],check=True,capture_output=True)
            app = root/'Eggie.app'
            app.mkdir()
            stage = root/'.eggie-update-12345678'
            stage.mkdir()
            lock = root/('.eggie-progress-'+hashlib.sha256(str(app).encode()).hexdigest()+'.lock')
            process = subprocess.Popen([helper,str(os.getpid()),app,stage,'unused','unused'],
                                       stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            def probe():
                return subprocess.run([helper,'--guard-launch',app,''],capture_output=True,timeout=10).returncode
            try:
                self.assertTrue(select.select([process.stdout],[],[],10)[0])
                self.assertEqual(process.stdout.readline(),b'ready\n')
                # Foundation may normalize /private/var aliases differently for
                # an existing app directory. Probe the actual native lock.
                lock = next(root.glob('.eggie-progress-*.lock'))
                os.chmod(lock,0)
                self.assertEqual(probe(),75)
                process.terminate();process.wait(timeout=10)
                self.assertTrue(lock.exists())
                self.assertEqual(probe(),0)
                self.assertEqual(list(app.iterdir()),[])  # No installation ever started.
            finally:
                if process.poll() is None:process.terminate();process.wait(timeout=10)
                process.stdout.close();process.stderr.close()
                if lock.exists():os.chmod(lock,0o600)
