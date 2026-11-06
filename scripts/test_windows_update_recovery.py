"""Explicit elevated acceptance for an isolated, interrupted full-repair transaction.

Never uses the real product registry key, application, shortcuts or user files.
Run on Windows through normal UAC; pass an existing output directory for evidence.
"""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main(output):
    assert os.name == 'nt' and ctypes.windll.shell32.IsUserAnAdmin(), 'Use normal Windows administrator consent'
    import winreg
    from eggie_update_windows import _powershell, _system_dir, _ps, _claim_launch_gate
    from eggie_update_startup import windows_gate_name, windows_update_active
    from windows_update_worker import TRANSACTION, MONITOR
    output = Path(output).resolve(strict=True)
    report_path = output / 'full-repair-interruption.json'
    assert not report_path.exists(), 'Do not replay an existing acceptance run'
    token = uuid.uuid4().hex
    product = str(uuid.uuid4()).upper()
    program_files = Path(os.environ['ProgramW6432'])
    app = program_files / ('Eggie QA Recovery ' + token)
    job = program_files / ('.eggie-update-' + token)
    registry = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{' + product + '}_is1'
    report = {'status': 'running', 'isolated_app': str(app), 'job': str(job)}
    worker = None
    monitor = None
    monitor_handles = []
    installer_pid = None
    handles = []
    success = False
    system = _system_dir()
    compiler = next(p for p in [system.parent / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe',
                               system.parent / 'Microsoft.NET/Framework/v4.0.30319/csc.exe'] if p.is_file())
    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    def terminate_fixture(pid):
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.restype = wintypes.HANDLE
        handle = kernel.OpenProcess(0x00100001, False, pid)
        if handle:
            handle = wintypes.HANDLE(handle)
            try:
                assert kernel.TerminateProcess(handle, 0)
                assert kernel.WaitForSingleObject(handle, 10000) == 0
            finally:
                kernel.CloseHandle(handle)
    try:
        app.mkdir()
        job.mkdir()
        save()
        original = {'Eggie DocuFlow.exe': b'original program', 'component/INSTALLER': b'locally changed metadata',
                    'unins000.dat': b'original uninstall data'}
        stamp = dict(schema=1, version='1.5.2', build='2026110501', files={
            'Eggie DocuFlow.exe': digest(original['Eggie DocuFlow.exe']),
            'component/INSTALLER': digest(b'original factory metadata'),
            'component/missing.txt': digest(b'a missing managed file'),
        })
        original['eggie-runtime.json'] = json.dumps(stamp).encode()
        for name, data in original.items():
            path = app / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, registry, 0, winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as key:
            winreg.SetValueEx(key, 'DisplayVersion', 0, winreg.REG_SZ, 'original')
        with tempfile.TemporaryDirectory(prefix='Eggie-recovery-fixture-') as temporary:
            source = Path(temporary)
            recovery_source = source / 'restore.cs'
            production = (ROOT / 'packaging/windows/EggieUpdateRestore.cs').read_text(encoding='utf-8')
            assert production.count('7DA942BC-98E2-48DB-93C7-741D7FD9C1C3') == 1
            recovery_source.write_text(production.replace('7DA942BC-98E2-48DB-93C7-741D7FD9C1C3', product), encoding='utf-8-sig')
            helper = job / 'EggieUpdateRestore.exe'
            subprocess.run([str(compiler), '/nologo', '/optimize+', '/codepage:65001', '/reference:System.Web.Extensions.dll',
                            '/win32manifest:' + str(ROOT / 'packaging/windows/recovery.manifest'),
                            '/out:' + str(helper), str(recovery_source)], check=True)
            installer_source = source / 'fixture.cs'
            installer_source.write_text(r'''
using System; using System.IO; using System.Threading; using System.Diagnostics;
using System.Collections.Generic; using System.Web.Script.Serialization; using Microsoft.Win32;
class Fixture { static void Main() {
  var config = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText("rollback.json"));
  string app = (string)config["install_dir"];
  File.WriteAllText(Path.Combine(app,"Eggie DocuFlow.exe"), "new application");
  File.WriteAllText(Path.Combine(app,"component/INSTALLER"), "repaired metadata");
  File.WriteAllText(Path.Combine(app,"component/missing.txt"), "repaired missing file");
  using(var key=Registry.LocalMachine.OpenSubKey(((string)config["registry_key"]).Substring(5),true))
    key.SetValue("DisplayVersion","new");
  File.WriteAllText("fixture-target-written", Process.GetCurrentProcess().Id.ToString());
  Thread.Sleep(600000);
} }
''', encoding='utf-8-sig')
            setup = job / 'update.exe'
            subprocess.run([str(compiler), '/nologo', '/reference:System.Web.Extensions.dll',
                            '/out:' + str(setup), str(installer_source)], check=True)
            kernel = ctypes.windll.kernel32
            kernel.CreateEventW.restype = wintypes.HANDLE
            gate_name = windows_gate_name(app)
            monitor_handles.append(_claim_launch_gate(gate_name))
            for name in (gate_name+'-show','Local\\Eggie-Update-'+token+'-shown','Local\\Eggie-Update-'+token+'-abort'):
                monitor_handles.append(wintypes.HANDLE(kernel.CreateEventW(None,True,False,name)))
            monitor_handles.append(wintypes.HANDLE(kernel.CreateEventW(None,False,True,'Local\\Eggie-Update-'+token+'-finish')))
            script = ('$job='+_ps(job)+';$app='+_ps(app)+';$token='+_ps(token)
                      +';$gateName='+_ps(gate_name)+';'+MONITOR)
            monitor = _powershell(script,cwd=system)
            assert kernel.WaitForSingleObject(monitor_handles[2],15000) == 0
            assert windows_update_active(app,[])
            for _ in range(3):
                handle = kernel.CreateEventW(None, True, True, None)
                assert handle
                os.set_handle_inheritable(handle, True)
                handles.append(handle)
            config = dict(install_dir=str(app), version='1.5.2', build='2026110501',
                          target_version='1.5.2', target_build='2026110502', kind='full',
                          broker_pid=2147483646, gui_pid=2147483647, registry_key='HKLM\\' + registry,
                          sha256=digest(setup.read_bytes()), commit_handle=handles[0], ready_handle=handles[1], bad_handle=handles[2])
            (job / 'rollback.json').write_text(json.dumps(config), encoding='utf-8')
            worker = _powershell(TRANSACTION, cwd=job, inherited_handle=handles)
            deadline = time.monotonic() + 60
            while not (job / 'fixture-target-written').exists():
                if worker.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Worker did not reach the controlled interruption point; see retained job')
                time.sleep(.1)
            installer_pid = int((job / 'fixture-target-written').read_text())
            worker.kill()
            worker.wait(timeout=10)
            worker = None
            terminate_fixture(installer_pid)
            installer_pid = None
            assert (job / 'installing').exists() and not (job / 'result').exists()
            snapshot = json.loads((job / 'backup-tree.json').read_bytes())
            assert snapshot['files'] == {name: digest(data) for name, data in original.items()}
            backup = job / 'backup'
            checks = []
            def recover():
                result = subprocess.run([str(helper)], input='RESTORE\n', capture_output=True,
                                        text=True, encoding='utf-8', errors='replace', timeout=40)
                with (output / 'recovery-native.log').open('a', encoding='utf-8') as log:
                    log.write(result.stdout + result.stderr + '\n')
                return result
            altered = backup / 'component/INSTALLER'
            altered.write_bytes(b'tampered after backup')
            assert recover().returncode == 2 and (job / 'installing').exists()
            assert not (job / 'result').exists() and windows_update_active(app,[])
            checks.append('reject_changed_backup')
            altered.write_bytes(original['component/INSTALLER'])
            extra = backup / 'unexpected.txt'
            extra.write_bytes(b'extra')
            assert recover().returncode == 2
            checks.append('reject_added_backup_file')
            extra.unlink()
            altered.unlink()
            assert recover().returncode == 2
            checks.append('reject_missing_backup_file')
            altered.write_bytes(original['component/INSTALLER'])
            # Also cover recovery after the monitor already displayed failure.
            (job / 'result').write_text('recovery-failed')
            time.sleep(1)
            assert monitor.poll() is None and windows_update_active(app,[])
            result = recover()
            assert result.returncode == 0 and 'Recovery complete.' in result.stdout
            assert not (job / 'installing').exists()
            assert (job / 'result').read_text() == 'recovered'
            deadline = time.monotonic()+10
            while windows_update_active(app,[]) and time.monotonic()<deadline:time.sleep(.1)
            assert not windows_update_active(app,[]) and monitor.poll() is None
            actual = {p.relative_to(app).as_posix(): p.read_bytes() for p in app.rglob('*') if p.is_file()}
            assert actual == original
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                assert winreg.QueryValueEx(key, 'DisplayVersion')[0] == 'original'
            checks += ['restore_original_drift', 'restore_original_missing_file_state', 'restore_registry',
                       'surviving_monitor_blocks_until_verified_recovery', 'recovery_releases_startup_with_result_still_visible']
            report.update(status='success', checks=checks, snapshot_files=len(snapshot['files']),
                          worker= 'production full-repair transaction', recovery='production helper with isolated product identifier')
            success = True
    except BaseException as error:
        report.update(status='failed', error=repr(error))
        raise
    finally:
        if monitor is not None and monitor.poll() is None:
            ctypes.windll.kernel32.SetEvent(monitor_handles[3]);monitor.wait(timeout=10)
        for handle in monitor_handles:ctypes.windll.kernel32.CloseHandle(handle)
        if worker is not None and worker.poll() is None:
            worker.kill(); worker.wait(timeout=10)
        if installer_pid:
            terminate_fixture(installer_pid)
        for handle in handles:
            ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(handle))
        if success:
            shutil.rmtree(app)
            shutil.rmtree(job)
            winreg.DeleteKeyEx(winreg.HKEY_LOCAL_MACHINE, registry, winreg.KEY_WOW64_64KEY)
            report['isolated_files_and_registry_removed'] = True
        save()


if __name__ == '__main__':
    main(sys.argv[1])
