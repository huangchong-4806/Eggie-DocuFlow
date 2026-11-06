import base64
from contextlib import contextmanager
import hashlib
import json
import os
import subprocess
import socket
import struct
from pathlib import Path
import tempfile
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from eggie_update_feed import asset_url, verify_manifest
import eggie_update_windows as windows
from update_check import DeltaNotApplicable, Release, UpdateCheckError
from version import APP_VERSION, BUILD_NUMBER


@unittest.skipUnless(os.name == "nt", "Requires native Windows PowerShell")
class WindowsTransactionTests(unittest.TestCase):
    def test_recovered_result_releases_launch_and_old_window_cannot_release_next_update(self):
        from windows_update_worker import MONITOR
        from eggie_update_startup import windows_gate_name, windows_update_active
        import time
        with tempfile.TemporaryDirectory(prefix='Eggie-recovered-monitor-') as folder:
            root = Path(folder)
            job = root/'job'
            job.mkdir()
            token = uuid.uuid4().hex
            name = windows_gate_name(root)
            kernel = windows.ctypes.windll.kernel32
            kernel.CreateEventW.restype = windows.wintypes.HANDLE
            handles = [windows._claim_launch_gate(name)]
            for event in (name+'-show','Local\\Eggie-Update-'+token+'-shown','Local\\Eggie-Update-'+token+'-abort'):
                handles.append(windows.wintypes.HANDLE(kernel.CreateEventW(None,True,False,event)))
            handles.append(windows.wintypes.HANDLE(kernel.CreateEventW(None,False,True,'Local\\Eggie-Update-'+token+'-finish')))
            process = None
            try:
                script = ('$job='+windows._ps(job)+';$app='+windows._ps(root)
                          +';$token='+windows._ps(token)+';$gateName='+windows._ps(name)+';'+MONITOR)
                process = windows._powershell(script,cwd=windows._system_dir())
                self.assertEqual(kernel.WaitForSingleObject(handles[2],15000),0)
                self.assertTrue(windows_update_active(root,[]))
                # Missing progress metadata is not recovery confirmation.
                time.sleep(.5)
                self.assertTrue(windows_update_active(root,[]))
                (job/'result').write_text('recovered')
                end = time.monotonic()+10
                while windows_update_active(root,[]) and time.monotonic()<end:time.sleep(.1)
                self.assertFalse(windows_update_active(root,[]))
                self.assertIsNone(process.poll())  # Keep the completed result open.
                handles.append(windows._claim_launch_gate(name))
                self.assertTrue(windows_update_active(root,[]))
                self.assertEqual(kernel.WaitForSingleObject(handles[4],0),258)  # Old caller cannot finish twice.
                with self.assertRaisesRegex(UpdateCheckError,'正在进行'):
                    windows._claim_launch_gate(name)
                kernel.SetEvent(handles[3])  # Close only the OLD result.
                self.assertEqual(process.wait(timeout=10),0)
                self.assertTrue(windows_update_active(root,[]))
                kernel.SetEvent(handles[-1])
                self.assertFalse(windows_update_active(root,[]))
            finally:
                if process is not None and process.poll() is None:
                    kernel.SetEvent(handles[3]);process.wait(timeout=10)
                for handle in handles:kernel.CloseHandle(handle)

    def test_native_progress_is_visible_before_commit_and_abort_releases_it(self):
        from windows_update_worker import MONITOR
        from eggie_update_startup import windows_gate_name, windows_update_active
        with tempfile.TemporaryDirectory(prefix='Eggie-progress-test-') as folder:
            root = Path(folder)
            token = uuid.uuid4().hex
            gate_name = windows_gate_name(root)
            kernel = windows.ctypes.windll.kernel32
            create = kernel.CreateEventW
            create.restype = windows.wintypes.HANDLE
            names = ['Local\\Eggie-Update-'+token+s for s in ('-shown','-abort')]
            names += [gate_name,gate_name+'-show']
            handles = [windows.wintypes.HANDLE(create(None,True,False,n)) for n in names]
            handles.append(windows.wintypes.HANDLE(create(None,False,True,'Local\\Eggie-Update-'+token+'-finish')))
            process = None
            try:
                script = ('$job='+windows._ps(root/'job')+';$app='+windows._ps(root)
                          +';$token='+windows._ps(token)+';$gateName='+windows._ps(gate_name)+';'+MONITOR)
                real_launch = subprocess.Popen
                def launch(*args, **kwargs):
                    kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    return real_launch(*args, **kwargs)
                with patch.object(windows.subprocess,'Popen',side_effect=launch):
                    process = windows._powershell(script,cwd=windows._system_dir())
                shown = kernel.WaitForSingleObject(handles[0],15000)
                if shown != 0 and process.poll() is not None:
                    self.fail(process.communicate()[1].decode(errors='replace')[-1800:])
                self.assertEqual(shown,0)
                self.assertIsNone(process.poll())
                self.assertTrue(windows_update_active(root,[]))
                kernel.SetEvent(handles[1])
                self.assertEqual(process.wait(timeout=10),0)
                self.assertFalse((root/'job').exists())
            finally:
                if process is not None and process.poll() is None:
                    kernel.SetEvent(handles[1])
                    process.wait(timeout=10)
                for h in handles:kernel.CloseHandle(h)
            self.assertFalse(windows_update_active(root,[]))

    def test_private_worker_environment_can_run_system_executables_in_pipelines(self):
        with tempfile.TemporaryDirectory(prefix="Eggie-worker-environment-") as folder:
            root = Path(folder)
            script = r"""
$ErrorActionPreference='Stop'
& ([IO.Path]::Combine([Environment]::SystemDirectory,'reg.exe')) query 'HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion' /v CurrentBuild /reg:64 | Out-Null
if ($LASTEXITCODE -ne 0) {exit 91}
$copyCommand = Get-Command ([IO.Path]::Combine([Environment]::SystemDirectory,'robocopy.exe'))
if ($copyCommand.CommandType -ne 'Application') {exit 92}
[IO.File]::WriteAllText([IO.Path]::Combine((Get-Location).Path,'native-commands-ok'),'ok')
"""
            with patch.dict(os.environ, {"PATHEXT": ".UNTRUSTED"}):
                process = windows._powershell(script, cwd=root, inherited_handle=[])
            self.assertEqual(process.wait(timeout=30), 0)
            self.assertEqual((root / "native-commands-ok").read_text(), "ok")

    def test_invalid_base_preserves_install_and_records_exact_failure_stage(self):
        from windows_update_worker import TRANSACTION
        with tempfile.TemporaryDirectory(prefix="Eggie-transaction-test-") as folder:
            root = Path(folder)
            app = root / "app"
            job = root / "job"
            app.mkdir()
            job.mkdir()
            (app / windows.APP_EXE).write_bytes(b"original application")
            (app / windows.STAMP).write_text(json.dumps(dict(schema=1, version="1.0.0", build="2026010101", files={})))
            original = {p.name: p.read_bytes() for p in app.iterdir()}
            config = dict(install_dir=str(app), version="2.0.0", build="2026010102", kind="delta",
                          broker_pid=2147483646, gui_pid=2147483647, commit_handle=0)
            (job / "rollback.json").write_text(json.dumps(config))
            # Only a same-process test event is substituted. The actual worker must
            # reject the version before invoking any installer or registry command.
            prefix = """$testGate = [Threading.EventWaitHandle]::new($true,[Threading.EventResetMode]::ManualReset)
$testConfig = Get-Content -Raw rollback.json | ConvertFrom-Json
$testConfig.commit_handle = $testGate.SafeWaitHandle.DangerousGetHandle().ToInt64()
$testConfig | ConvertTo-Json | Set-Content -Encoding UTF8 rollback.json
"""
            encoded = base64.b64encode((prefix + TRANSACTION).encode("utf-16-le")).decode("ascii")
            result = subprocess.run([str(windows._system_dir() / "WindowsPowerShell/v1.0/powershell.exe"),
                                     "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                                    cwd=job, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            self.assertEqual((job / "result").read_text(), "not-started")
            failure = json.loads((job / "failure.json").read_bytes())
            self.assertEqual(failure["stage"], "verify-base")
            self.assertIn("does not match", failure["message"])
            self.assertIsNone(failure["installer_exit"])
            self.assertEqual({p.name: p.read_bytes() for p in app.iterdir()}, original)
            self.assertFalse((job / "installing").exists())


class WindowsUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.install = self.root / "installed"
        self.install.mkdir()
        self.exe = self.install / windows.APP_EXE
        self.exe.write_bytes(b"A")
        self.installed = Release(APP_VERSION, BUILD_NUMBER)
        self.target = Release("99.0.0", "2099123101")
        self.package = self.root / "patch.exe"
        self.package.write_bytes(b"MZ signed fixture")
        self.stamp({windows.APP_EXE: hashlib.sha256(b"A").hexdigest()})
        key = Ed25519PrivateKey.generate()
        self.key = key.public_key().public_bytes_raw()
        entries = []
        for kind, name in [("full", "full.exe"), ("delta", "patch.exe")]:
            entries.append(dict(platform="windows-x64", base=vars(self.installed) if kind == "delta" else None,
                                kind=kind, filename=name, size=self.package.stat().st_size,
                                sha256=hashlib.sha256(self.package.read_bytes()).hexdigest(),
                                url=asset_url(self.target, name)))
        data = json.dumps(dict(schema=1, target=vars(self.target), assets=entries)).encode()
        signed = json.dumps(dict(payload=base64.b64encode(data).decode(),
                                 signature=base64.b64encode(key.sign(data)).decode())).encode()
        self.full, self.delta = verify_manifest(signed, self.key, self.target)

    def stamp(self, files):
        record = dict(schema=1, version=APP_VERSION, build=BUILD_NUMBER, files=files)
        (self.install / windows.STAMP).write_text(json.dumps(record))

    def test_preparation_reauthenticates_preserves_private_file_and_discards(self):
        with patch.object(windows, "_installed", return_value=self.install), \
             patch.object(windows, "read_update_public_key", return_value=self.key):
            prepared = windows.prepare_update(self.package, self.delta, self.target)
            try:
                self.package.unlink()
                self.assertEqual((prepared.directory / prepared.filename).read_bytes(), b"MZ signed fixture")
                self.assertEqual((prepared.directory / "manifest.json").read_bytes(), self.delta.signed_manifest)
            finally:
                windows.discard_update(prepared)
            self.assertFalse(prepared.directory.exists())

    def test_broker_stream_exposes_only_the_authenticated_staged_payload(self):
        with patch.object(windows, "_installed", return_value=self.install), \
             patch.object(windows, "read_update_public_key", return_value=self.key):
            prepared = windows.prepare_update(self.package, self.delta, self.target)
            self.addCleanup(windows.discard_update, prepared)
            with windows._package_stream(prepared) as port, \
                 socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
                connection.sendall(prepared.token.encode("ascii"))
                with connection.makefile("rb") as stream:
                    size = struct.unpack("!I", stream.read(4))[0]
                    asset = windows._authenticate(stream.read(size), prepared.target, prepared.filename)
                    destination = self.root / "broker-copy.exe"
                    windows._write_verified(stream, destination, asset)
                self.assertEqual(destination.read_bytes(), self.package.read_bytes())

    def test_changed_download_and_unsigned_asset_are_rejected(self):
        with patch.object(windows, "_installed", return_value=self.install), \
             patch.object(windows, "read_update_public_key", return_value=self.key):
            self.package.write_bytes(b"X" * self.delta.size)
            with self.assertRaisesRegex(UpdateCheckError, "校验"):
                windows.prepare_update(self.package, self.delta, self.target)
            with self.assertRaises(UpdateCheckError):
                windows._authenticate(self.delta.signed_manifest.replace(b'"signature"', b'"x"'),
                                      self.target, self.delta.filename)
            with self.assertRaises(UpdateCheckError):
                windows._authenticate(self.delta.signed_manifest, self.target, "other.exe")

    def test_independent_recovery_is_checked_and_copied_before_installation(self):
        relative = "_internal/update-tools/EggieUpdateRestore.exe"
        helper = self.install / relative
        helper.parent.mkdir(parents=True)
        helper.write_bytes(b"MZ recovery fixture")
        self.stamp({windows.APP_EXE: hashlib.sha256(b"A").hexdigest(),
                    relative: hashlib.sha256(helper.read_bytes()).hexdigest()})
        job = self.root / "protected-job"
        job.mkdir()
        with patch.object(windows, "_check_acl"):
            windows._copy_recovery_helper(self.install, job)
            self.assertEqual((job / helper.name).read_bytes(), helper.read_bytes())
            (job / helper.name).unlink()
            helper.write_bytes(b"changed recovery fixture")
            with self.assertRaises(UpdateCheckError):
                windows._copy_recovery_helper(self.install, job)

    def test_drift_offers_full_repair_but_does_not_overwrite_unmanaged_files(self):
        self.exe.write_bytes(b"locally changed")
        with self.assertRaises(DeltaNotApplicable):
            windows.validate_installation(self.install, self.installed)
        windows.validate_installation(self.install, self.installed, full=True)
        (self.install / "unins000.dat").write_bytes(b"registered installer data")
        windows.validate_installation(self.install, self.installed, full=True)
        (self.install / "notes.txt").write_text("user content")
        with self.assertRaises(UpdateCheckError):
            windows.validate_installation(self.install, self.installed, full=True)

    def test_ambiguous_and_escaping_managed_paths_are_rejected(self):
        for unsafe in ["../bad", "bad:ads", "unrelated\\app", "/abs", "COM1", "a./file", "a//file"]:
            with self.subTest(unsafe=unsafe):
                self.stamp({windows.APP_EXE: "a"*64, unsafe: "f"*64})
                with self.assertRaises(UpdateCheckError):
                    windows.validate_installation(self.install, self.installed, full=True)
        if os.name != "nt":
            symlink = self.install / "link"
            symlink.symlink_to(self.root)
            self.stamp({windows.APP_EXE: hashlib.sha256(b"A").hexdigest()})
            with self.assertRaises(UpdateCheckError):
                windows.validate_installation(self.install, self.installed, full=True)

    def test_interrupted_update_keeps_backup_visible_instead_of_starting_again(self):
        job = self.root / (".eggie-update-" + "a" * 32)
        job.mkdir()
        (job / "rollback.json").write_text(json.dumps({"install_dir": str(self.install)}))
        (job / "installing").touch()
        with self.assertRaisesRegex(UpdateCheckError, "恢复目录"):
            windows._check_pending_recovery(self.install)
        (job / "installing").unlink()
        windows._check_pending_recovery(self.install)

    def test_elevated_powershell_starts_with_an_allowlisted_environment(self):
        injected = {"COR_ENABLE_PROFILING": "1", "COR_PROFILER_PATH": "untrusted.dll",
                    "COMPLUS_ReadyToRun": "0", "PSModulePath": "unsafe", "TMP": "unsafe", "PATHEXT": ".UNTRUSTED"}
        with patch.dict(os.environ, injected), patch.object(windows, "_system_dir", return_value=self.root / "System32"), \
             patch.object(windows.subprocess, "STARTUPINFO", SimpleNamespace, create=True), \
             patch.object(windows.subprocess, "CREATE_NO_WINDOW", 0, create=True), \
             patch.object(windows.subprocess, "Popen") as launch:
            windows._powershell("exit", cwd=self.root, inherited_handle=[3, 4, 5])
        env = launch.call_args.kwargs["env"]
        self.assertFalse(any(name.startswith(("COR_", "COMPLUS_", "_PYI_")) for name in env))
        self.assertEqual(env["TEMP"], str(self.root / "tmp"))
        self.assertNotIn("unsafe", env.values())
        self.assertEqual(env['PATHEXT'], '.EXE')
        self.assertEqual(launch.call_args.kwargs["startupinfo"].lpAttributeList["handle_list"], [3, 4, 5])

    def test_launch_never_commits_if_broker_or_unelevated_monitor_fails(self):
        prepared = windows.Prepared(self.root, "patch.exe", self.target, "8"*32)
        for failed_at in ("broker", "monitor"):
            with self.subTest(failed_at=failed_at):
                libs = MagicMock()
                libs.kernel32.CreateMutexW.return_value = 90
                libs.kernel32.CreateEventW.side_effect = range(71, 79)
                libs.kernel32.WaitForSingleObject.return_value = 0
                libs.shell32.IsUserAnAdmin.return_value = False
                monitor = MagicMock()
                monitor.poll.return_value = None
                with patch.object(windows.ctypes, "windll", libs, create=True), \
                     patch.object(windows, "_installed", return_value=self.install), \
                     patch.object(windows, "_check_acl"), \
                     patch.object(windows, "_system_dir", return_value=self.root), \
                     patch.object(windows, "_run_broker", side_effect=OSError() if failed_at=="broker" else None), \
                     patch.object(windows, "_powershell", return_value=monitor,
                                  side_effect=OSError() if failed_at=="monitor" else None), \
                     self.assertRaises(OSError):
                    windows.launch_update(prepared)
                self.assertEqual([c.args[0].value for c in libs.kernel32.SetEvent.call_args_list], [75,76])
                self.assertEqual(libs.kernel32.CloseHandle.call_count, 9)
                self.assertTrue(self.root.is_dir())

    def test_monitor_failure_can_retry_download_without_reusing_job_or_events(self):
        prepared = windows.Prepared(self.root, "patch.exe", self.target, "8" * 32)
        attempts = []
        jobs = []
        @contextmanager
        def stream(transaction):
            attempts.append(transaction)
            yield 12345
        def broker(args, root):
            # The real broker uses exclusive mkdir; a reused token must fail.
            self.assertEqual(args[5], attempts[-1].token)
            job = root.parent / (".eggie-update-" + args[5])
            job.mkdir()
            jobs.append(job)
        libs = MagicMock()
        libs.kernel32.CreateMutexW.return_value = 90
        libs.kernel32.CreateEventW.side_effect = range(71, 87)
        libs.kernel32.WaitForSingleObject.return_value = 0
        libs.shell32.IsUserAnAdmin.return_value = False
        monitor = MagicMock()
        monitor.poll.return_value = None
        with patch.object(windows.ctypes, "windll", libs, create=True), \
             patch.object(windows, "_installed", return_value=self.install), \
             patch.object(windows, "_check_acl"), \
             patch.object(windows, "_system_dir", return_value=self.root), \
             patch.object(windows, "_package_stream", stream), \
             patch.object(windows, "_run_broker", broker), \
             patch.object(windows, "_powershell", side_effect=[OSError("monitor unavailable"), monitor]), \
             patch.object(windows, "discard_update") as discard:
            with self.assertRaises(OSError):
                windows.launch_update(prepared)
            self.assertEqual([c.args[0].value for c in libs.kernel32.SetEvent.call_args_list], [75,76])
            discard.assert_not_called()
            windows.launch_update(prepared)
        self.assertEqual(len(attempts), 1)  # No broker/job exists before the window is ready.
        self.assertEqual(prepared.token, "8" * 32)
        self.assertEqual(len(jobs), 1)
        self.assertEqual([c.args[0].value for c in libs.kernel32.SetEvent.call_args_list], [75,76,79])
        self.assertEqual(libs.kernel32.CloseHandle.call_count, 18)
        names = [call.args[3] for call in libs.kernel32.CreateEventW.call_args_list]
        self.assertEqual(len(set(names)), 14)  # Two stable installation gates + twelve transaction events.
        discard.assert_called_once_with(attempts[0])

    def test_window_timeout_never_contacts_broker_or_commits(self):
        libs = MagicMock()
        libs.kernel32.CreateMutexW.return_value = 90
        libs.kernel32.CreateEventW.side_effect = range(71, 79)
        libs.kernel32.WaitForSingleObject.side_effect = [0,258,0]
        libs.shell32.IsUserAnAdmin.return_value = False
        monitor = MagicMock()
        monitor.poll.return_value = None
        prepared = windows.Prepared(self.root, "patch.exe", self.target, "8"*32)
        with patch.object(windows.ctypes, "windll", libs, create=True), \
             patch.object(windows, "_installed", return_value=self.install), \
             patch.object(windows, "_check_acl"), \
             patch.object(windows, "_system_dir", return_value=self.root), \
             patch.object(windows, "_run_broker") as broker, \
             patch.object(windows, "_powershell", return_value=monitor), \
             patch.object(windows, "discard_update") as discard:
            with self.assertRaisesRegex(UpdateCheckError, "提示窗口"):
                windows.launch_update(prepared)
        broker.assert_not_called()
        discard.assert_not_called()
        self.assertEqual([c.args[0].value for c in libs.kernel32.SetEvent.call_args_list], [75,76])

    def test_claim_reuses_completed_gate_but_rejects_active_or_competing_attempt(self):
        for mutex_state, event_state, allowed in [(0,0,True),(0x80,0,True),(0,258,False),(258,0,False)]:
            with self.subTest(mutex=mutex_state,event=event_state):
                libs = MagicMock()
                kernel = libs.kernel32
                kernel.CreateMutexW.return_value = 90
                kernel.CreateEventW.return_value = 91
                kernel.GetLastError.return_value = 183
                kernel.WaitForSingleObject.side_effect = [mutex_state,event_state]
                with patch.object(windows.ctypes,'windll',libs,create=True):
                    if allowed:
                        self.assertEqual(windows._claim_launch_gate('fixture').value,91)
                        kernel.ResetEvent.assert_called_once()
                    else:
                        with self.assertRaises(UpdateCheckError):windows._claim_launch_gate('fixture')
                        kernel.ResetEvent.assert_not_called()
                self.assertEqual(kernel.ReleaseMutex.call_count,int(mutex_state in (0,0x80)))
