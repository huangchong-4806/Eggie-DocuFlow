"""Verify an Inno update twice across the Windows elevation boundary."""
import base64
import ctypes
from contextlib import contextmanager
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import socket
import struct
import stat
import subprocess
import sys
import tempfile
from threading import Event, Thread
import uuid
from dataclasses import dataclass, replace

from eggie_update_feed import MAX_MANIFEST_SIZE, read_update_public_key, verify_manifest
from update_check import DeltaNotApplicable, Release, UpdateCheckError
from version import APP_VERSION, BUILD_NUMBER

APP_EXE = "Eggie DocuFlow.exe"
STAMP = "eggie-runtime.json"
REGISTRY_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{7DA942BC-98E2-48DB-93C7-741D7FD9C1C3}_is1"
JOB_RE = re.compile(r"[0-9a-f]{32}")


def _no_links(path):
    for component in (path, *path.parents):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise UpdateCheckError("安装或更新路径包含链接，请改用官方安装包。")


_TRUSTED_OWNERS = {
    "S-1-5-18", "S-1-5-32-544",
    "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464",  # TrustedInstaller
}


def _check_acl(path):
    """Reject user-owned or user-writable installation files before UAC loads any DLL."""
    api, kernel = ctypes.windll.advapi32, ctypes.windll.kernel32
    owner, acl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    def trusted_sid(address):
        sid_string = wintypes.LPWSTR()
        if not api.ConvertSidToStringSidW(ctypes.c_void_p(address), ctypes.byref(sid_string)):
            return False
        try:
            return sid_string.value in _TRUSTED_OWNERS
        finally:
            kernel.LocalFree(ctypes.cast(sid_string, ctypes.c_void_p))
    status = api.GetNamedSecurityInfoW(str(path), 1, 5, ctypes.byref(owner), None,
                                       ctypes.byref(acl), None, ctypes.byref(descriptor))
    try:
        if status or not acl.value or not owner.value or not trusted_sid(owner.value):
            raise UpdateCheckError("安装目录的权限不适合自动更新，请联系管理员。")
        count = ctypes.c_ushort.from_address(acl.value + 4).value
        for index in range(count):
            ace = ctypes.c_void_p()
            if not api.GetAce(acl, index, ctypes.byref(ace)):
                raise UpdateCheckError("无法验证安装目录权限。")
            kind = ctypes.c_ubyte.from_address(ace.value).value
            flags = ctypes.c_ubyte.from_address(ace.value + 1).value
            mask = ctypes.c_uint32.from_address(ace.value + 4).value
            if flags & 0x08 or kind not in (0, 4, 5, 9, 11) or not mask & 0x500D0156:
                continue
            if kind != 0 or not trusted_sid(ace.value + 8):
                raise UpdateCheckError("普通账户可以修改软件安装文件，请联系管理员。")
    finally:
        if descriptor.value:
            kernel.LocalFree(descriptor)


def _program_files():
    buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x26, None, 0, buffer) != 0:
        raise UpdateCheckError("无法读取 Windows 程序目录。")
    return Path(buffer.value)


def _installed():
    import winreg
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise UpdateCheckError("请从已安装的 Windows 版 Eggie 检查更新。")
    exe = Path(sys.executable)
    root = exe.parent
    _no_links(root)
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            registered = Path(winreg.QueryValueEx(key, "InstallLocation")[0])
    except OSError as exc:
        raise UpdateCheckError("没有找到这份软件的安装记录，请使用官方完整安装包。") from exc
    if (exe.name.casefold() != APP_EXE.casefold() or root != registered
            or root.parent != _program_files()):
        raise UpdateCheckError("安装位置与系统记录或受保护程序目录不符，请使用官方完整安装包。")
    _check_acl(root.parent)
    _check_acl(root)
    return root


def can_update_installation():
    try:
        _installed()
        if ctypes.windll.shell32.IsUserAnAdmin():
            return False
    except (OSError, ImportError, UpdateCheckError):
        return False
    return True


def _relative(name):
    if not isinstance(name, str) or not name or "\\" in name:
        raise ValueError("invalid path")
    parts = name.split("/")
    if any(not part or part in (".", "..") or part.endswith((" ", ".")) or
           re.search(r'[\x00-\x1f:<>|"?*]', part) or PureWindowsPath(part).is_reserved()
           for part in parts):
        raise ValueError("invalid path")
    return Path(*parts)


def _check_pending_recovery(root):
    for job in root.parent.glob(".eggie-update-*"):
        if not JOB_RE.fullmatch(job.name.removeprefix(".eggie-update-")) or not (job / "installing").is_file():
            continue
        _no_links(job / "rollback.json")
        try:
            saved = json.loads((job / "rollback.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise UpdateCheckError("检测到未完成的 Windows 更新，请联系维护者核对备份。")
        if Path(saved.get("install_dir", "")) == root:
            raise UpdateCheckError(f"上次更新尚未结束，请先确认原版本。恢复目录：{job}")


def validate_installation(root, base, *, full=False):
    """Check the trusted installation record before asking for elevation."""
    problem = UpdateCheckError if full else DeltaNotApplicable
    try:
        _no_links(root / STAMP)
        with (root / STAMP).open("rb") as stream:
            data = stream.read(4 * 1024**2 + 1)
        if len(data) > 4 * 1024**2:
            raise ValueError("oversized record")
        record = json.loads(data)
        files = record["files"]
        if (record["schema"] != 1 or record["version"] != base.version
                or record["build"] != base.build or not isinstance(files, dict) or APP_EXE not in files):
            raise ValueError("wrong base")
        managed = set()
        for name, digest in files.items():
            path = root / _relative(name)
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or name.casefold() in managed:
                raise ValueError("invalid file record")
            managed.add(name.casefold())
            # A full installer may repair missing/damaged managed files.
            if not full:
                _no_links(path)
                with path.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                        raise ValueError("wrong digest")
        # Never follow directory junctions, even in unmanaged or skipped directories.
        for directory, dirs, names in os.walk(root, onerror=_raise_walk_error):
            for name in (*dirs, *names):
                p = Path(directory) / name
                _no_links(p)
            if full:
                for name in names:
                    rel = (Path(directory) / name).relative_to(root).as_posix().casefold()
                    if rel not in managed and rel != STAMP and not re.fullmatch(r"unins[0-9]{3}\.(exe|dat|msg)", rel):
                        raise ValueError("unexpected local file")
    except (OSError, ValueError, KeyError, TypeError, UpdateCheckError) as error:
        detail = ("完整更新无法安全处理此安装目录，请使用官方下载页。" if full else
                  "此安装的文件与增量更新要求的旧版本不一致。")
        raise problem(detail) from error


def _raise_walk_error(error):
    raise error


def _write_verified(src, output, asset):
    total = 0
    digest = hashlib.sha256()
    with output.open("xb") as dst:
        while block := src.read(min(1024 * 1024, asset.size + 1 - total)):
            total += len(block)
            if total > asset.size:
                raise UpdateCheckError("Windows 更新包大小异常。")
            dst.write(block)
            digest.update(block)
        dst.flush()
        os.fsync(dst.fileno())
    if total != asset.size or digest.hexdigest() != asset.sha256:
        raise UpdateCheckError("Windows 更新包校验失败，未执行安装。")


def _authenticate(manifest, target, filename):
    key = read_update_public_key()
    if not key:
        raise UpdateCheckError("缺少用于检查更新来源的公钥。")
    installed = Release(APP_VERSION, BUILD_NUMBER)
    for item in verify_manifest(manifest, key, target):
        if (item.filename == filename and item.platform == "windows-x64"
                and target.sort_key() > installed.sort_key()
                and (item.kind == "full" or item.base == installed)):
            return item
    raise UpdateCheckError("Windows 更新文件、版本或基础版本不匹配。")


def _copy_recovery_helper(root, job):
    """Even full repair requires an intact standalone recovery tool before mutation."""
    relative = "_internal/update-tools/EggieUpdateRestore.exe"
    source = root / relative
    _no_links(source)
    _check_acl(source)
    record = json.loads((root / STAMP).read_bytes())
    expected = record.get("files", {}).get(relative, "")
    size = source.stat().st_size
    if not re.fullmatch(r"[a-f0-9]{64}", expected) or not 0 < size <= 4 * 1024**2:
        raise UpdateCheckError("缺少有效的独立恢复工具，请改用官方完整安装包。")
    from types import SimpleNamespace
    with source.open("rb") as stream:
        _write_verified(stream, job / "EggieUpdateRestore.exe", SimpleNamespace(size=size, sha256=expected))


@dataclass(frozen=True)
class Prepared:
    directory: Path
    filename: str
    target: Release
    token: str


def prepare_update(package, asset, target):
    root = _installed()
    _check_pending_recovery(root)
    verified = _authenticate(asset.signed_manifest, target, asset.filename)
    if asset != verified:
        raise UpdateCheckError("更新信息不匹配。")
    validate_installation(root, Release(APP_VERSION, BUILD_NUMBER), full=asset.kind == "full")
    work = Path(tempfile.mkdtemp(prefix="eggie-win-download-"))
    try:
        with Path(package).open("rb") as source:
            _write_verified(source, work / asset.filename, asset)
        (work / "manifest.json").write_bytes(asset.signed_manifest)
        return Prepared(work, asset.filename, target, uuid.uuid4().hex)
    except BaseException:
        shutil.rmtree(work)
        raise


def discard_update(prepared):
    if prepared.directory.exists():
        shutil.rmtree(prepared.directory)


def _system_dir():
    buf = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetSystemDirectoryW(buf, len(buf)):
        raise ctypes.WinError()
    return Path(buf.value)


def _powershell(script, *, cwd, inherited_handle=None):
    system = _system_dir()
    exe = system / "WindowsPowerShell/v1.0/powershell.exe"
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    if inherited_handle is not None:
        private_temp = cwd / "tmp"
        private_temp.mkdir()
        env = {"TEMP": str(private_temp), "TMP": str(private_temp),
               "COMSPEC": str(system / "cmd.exe"), "SystemDrive": system.drive,
               "PSModulePath": str(exe.parent / "Modules"), "PATH": str(system),
               # PowerShell 5.1 uses PATHEXT even for fully qualified EXE paths.
               # Keep this fixed rather than inheriting file associations from the caller.
               "PATHEXT": ".EXE"}
    else:
        # Restore the launching user's regular environment for the new GUI.
        env = os.environ.copy()
    env["SystemRoot"] = str(system.parent)
    env["WINDIR"] = str(system.parent)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    for name in tuple(env):
        if name.startswith("_PYI_"):
            del env[name]
    startup = None
    if inherited_handle is not None:
        startup = subprocess.STARTUPINFO()
        startup.lpAttributeList = {"handle_list": list(inherited_handle)}
    return subprocess.Popen([str(exe), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                            cwd=cwd, env=env, startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
    ]


def _run_broker(arguments, root):
    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x100  # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    info.lpVerb, info.lpFile = "runas", str(root / APP_EXE)
    info.lpParameters, info.lpDirectory = subprocess.list2cmdline(arguments), str(root)
    info.nShow = 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        raise UpdateCheckError("Windows 未批准安装权限，当前版本仍可使用。")
    kernel = ctypes.windll.kernel32
    handle = wintypes.HANDLE(info.hProcess)
    try:
        # The broker only authenticates and hands off; it never waits for this app to exit.
        if kernel.WaitForSingleObject(handle, 300000) != 0:
            raise UpdateCheckError("Windows 更新准备超时，请保留当前窗口。")
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 0:
            raise UpdateCheckError("Windows 拒绝更新准备，请检查安装文件和磁盘空间。")
    finally:
        kernel.CloseHandle(handle)


def _ps(value):
    return "'" + str(value).replace("'", "''") + "'"


@contextmanager
def _package_stream(prepared):
    # The elevated broker accepts only bytes. It never follows a standard
    # user's path, junction, UNC share or substituted file with administrator rights.
    stopped = Event()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(0.3)

        def serve():
            while not stopped.is_set():
                try:
                    peer, _ = listener.accept()
                except TimeoutError:
                    continue
                except OSError:
                    return
                try:
                    with peer, peer.makefile("rb") as reader:
                        peer.settimeout(5)
                        if reader.read(32) != prepared.token.encode("ascii"):
                            continue
                        manifest = (prepared.directory / "manifest.json").read_bytes()
                        peer.sendall(struct.pack("!I", len(manifest)) + manifest)
                        peer.settimeout(120)
                        with (prepared.directory / prepared.filename).open("rb") as source:
                            while data := source.read(1024 * 1024):
                                peer.sendall(data)
                        return
                except OSError:
                    return

        thread = Thread(target=serve, daemon=True)
        thread.start()
        try:
            yield listener.getsockname()[1]
        finally:
            stopped.set()


def _claim_launch_gate(name):
    """Atomically reuse a completed gate, even while its old result is visible."""
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW.restype = wintypes.HANDLE
    mutex = kernel.CreateMutexW(None, False, name + "-claim")
    if not mutex:
        raise ctypes.WinError()
    mutex = wintypes.HANDLE(mutex)
    acquired = False
    gate = None
    try:
        acquired = kernel.WaitForSingleObject(mutex, 0) in (0, 0x80)
        if not acquired:
            raise UpdateCheckError("另一次更新正在准备，请稍后重试。")
        kernel.CreateEventW.restype = wintypes.HANDLE
        handle = kernel.CreateEventW(None, True, False, name)
        existed = kernel.GetLastError() == 183
        if not handle:
            raise ctypes.WinError()
        gate = wintypes.HANDLE(handle)
        if existed:
            if kernel.WaitForSingleObject(gate, 0) != 0:
                raise UpdateCheckError("另一次更新正在进行，请等待完成。")
            if not kernel.ResetEvent(gate):
                raise ctypes.WinError()
        result, gate = gate, None
        return result
    finally:
        if gate is not None:
            kernel.CloseHandle(gate)
        if acquired:
            kernel.ReleaseMutex(mutex)
        kernel.CloseHandle(mutex)


def launch_update(prepared):
    # A download can survive a failed handoff. Each attempt needs its own job
    # and events; the previous worker may still be cancelling its uncommitted job.
    prepared = replace(prepared, token=uuid.uuid4().hex)
    root = _installed()
    if ctypes.windll.shell32.IsUserAnAdmin():
        raise UpdateCheckError("请以普通用户启动 Eggie 后安装更新。")
    for directory, dirs, names in os.walk(root, onerror=_raise_walk_error):
        for name in (*dirs, *names):
            path = Path(directory) / name
            _no_links(path)
            _check_acl(path)
    job = root.parent / (".eggie-update-" + prepared.token)
    # The monitor runs as the launching user, not as the elevated installer.
    # It restarts only the trusted, fixed, registered executable and never opens a document.
    from windows_update_worker import MONITOR
    from eggie_update_startup import windows_gate_name
    gate_name = windows_gate_name(root)
    monitor = ("$job=" + _ps(job) + ";$app=" + _ps(root) + ";$token=" + _ps(prepared.token)
               + ";$gateName=" + _ps(gate_name) + ";" + MONITOR)
    kernel = ctypes.windll.kernel32
    create_event = kernel.CreateEventW
    create_event.restype = wintypes.HANDLE
    events = []
    gate = None
    finish = None
    monitor_process = None
    committed = False
    try:
        names = ["Local\\Eggie-Update-" + prepared.token + purpose
                 for purpose in ("", "-ready", "-bad", "-shown", "-abort")]
        for name in names:
            handle = create_event(None, True, False, name)
            if not handle:
                raise ctypes.WinError()
            events.append(wintypes.HANDLE(handle))
        gate = _claim_launch_gate(gate_name)
        events.append(gate)
        show = create_event(None, True, False, gate_name + "-show")
        if not show:
            raise ctypes.WinError()
        events.append(wintypes.HANDLE(show))
        if not kernel.ResetEvent(events[-1]):
            raise ctypes.WinError()
        # A transaction can finish from either the monitor or a failed caller.
        # Exactly one may release the shared gate; a late cleanup must not
        # release a subsequent transaction that has already reused it.
        handle = create_event(None, False, True, "Local\\Eggie-Update-" + prepared.token + "-finish")
        if not handle:
            raise ctypes.WinError()
        finish = wintypes.HANDLE(handle)
        events.append(finish)
        monitor_process = _powershell(monitor, cwd=_system_dir())
        if kernel.WaitForSingleObject(events[3], 15000) != 0 or monitor_process.poll() is not None:
            raise UpdateCheckError("更新提示窗口未能打开，当前应用保持运行。请稍后重试。")
        with _package_stream(prepared) as port:
            args = ["--eggie-install-update", str(port), prepared.filename, prepared.target.version,
                    prepared.target.build, prepared.token, str(os.getpid())]
            _run_broker(args, root)
        if monitor_process.poll() is not None:
            raise UpdateCheckError("更新提示窗口已关闭，当前应用保持运行。请稍后重试。")
        if not kernel.SetEvent(events[0]):
            raise ctypes.WinError()
        committed = True
    finally:
        if not committed and len(events) >= 5:
            # An uncommitted worker cannot install. Do not leave a reused gate
            # active just because an older result window still owns a handle.
            kernel.SetEvent(events[4])
            if monitor_process is not None:
                try:
                    monitor_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    monitor_process.terminate()
                    monitor_process.wait(timeout=3)
            if gate is not None and (finish is None or kernel.WaitForSingleObject(finish, 0) == 0):
                kernel.SetEvent(gate)
        for event in events:
            kernel.CloseHandle(event)
    try:
        discard_update(prepared)
    except OSError:
        pass  # The handoff has committed; cache deletion cannot undo it.


def elevated_entry(args):
    """No user-supplied install destination, command line, key, executable or output path."""
    if sys.platform != "win32" or not ctypes.windll.shell32.IsUserAnAdmin() or len(args) != 6:
        return 2
    job = None
    created = False
    worker = None
    events = []
    try:
        root = _installed()
        _check_pending_recovery(root)
        port, filename, version, build, token, pid_text = args
        if (not JOB_RE.fullmatch(token) or not re.fullmatch(r"[1-9][0-9]{0,9}", pid_text)
                or not port.isascii() or not port.isdigit() or not 1024 <= int(port) <= 65535):
            raise ValueError("invalid transaction")
        open_event = ctypes.windll.kernel32.OpenEventW
        open_event.restype = wintypes.HANDLE
        for purpose in ("", "-ready", "-bad"):
            event = open_event(0x00100000, True, "Local\\Eggie-Update-" + token + purpose)
            if not event:
                raise UpdateCheckError("没有找到有效的本次更新确认。")
            events.append(event)
        from eggie_update_startup import windows_gate_name
        active = open_event(0x00100000, True, windows_gate_name(root))
        if not active:
            raise UpdateCheckError("更新提示已关闭，请重新开始更新。")
        events.append(active)
        with socket.create_connection(("127.0.0.1", int(port)), timeout=15) as channel:
            channel.settimeout(120)
            channel.sendall(token.encode("ascii"))
            with channel.makefile("rb") as stream:
                length = struct.unpack("!I", stream.read(4))[0]
                if not 0 < length <= MAX_MANIFEST_SIZE:
                    raise ValueError("invalid release header")
                manifest = stream.read(length)
                target = Release(version, build)
                asset = _authenticate(manifest, target, filename)
                installed = Release(APP_VERSION, BUILD_NUMBER)
                validate_installation(root, installed, full=asset.kind == "full")
                job = root.parent / (".eggie-update-" + token)
                job.mkdir()
                created = True
                _write_verified(stream, job / "update.exe", asset)
        (job / "rollback.json").write_text(json.dumps({
            "install_dir": str(root), "version": APP_VERSION, "build": BUILD_NUMBER,
            "target_version": version, "target_build": build, "gui_pid": int(pid_text),
            "sha256": asset.sha256, "kind": asset.kind, "commit_handle": events[0],
            "ready_handle": events[1], "bad_handle": events[2],
            "broker_pid": os.getpid(), "registry_key": "HKLM\\" + REGISTRY_KEY,
        }), encoding="utf-8")
        from windows_update_worker import TRANSACTION
        _copy_recovery_helper(root, job)
        worker = _powershell(TRANSACTION, cwd=job, inherited_handle=events)
        return 0
    except Exception:
        return 3
    finally:
        for event in events:
            ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(event))
        if created and worker is None:
            shutil.rmtree(job, ignore_errors=True)
