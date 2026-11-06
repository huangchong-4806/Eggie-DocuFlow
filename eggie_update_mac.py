"""Stage a verified macOS update beside the running app, then hand off before exit."""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import plistlib
import posixpath
import re
import select
import shutil
import stat
import subprocess
import sys
import tempfile
from zipfile import ZipFile

from update_check import DeltaNotApplicable, Release, UpdateCheckError

BUNDLE_ID = "com.huang.eggiedocuflow"
EXECUTABLE = "Eggie DocuFlow"
STAGE_PREFIX = ".eggie-update-"


@dataclass(frozen=True)
class PreparedMacUpdate:
    installed: Path
    staging: Path
    old_cdhash: str
    new_cdhash: str


def installed_bundle():
    if sys.platform == "darwin" and getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        app = executable.parents[2]
        if app.suffix == ".app" and executable == app / "Contents" / "MacOS" / EXECUTABLE:
            return app
    return None


def _tool(app, name):
    return app / "Contents" / "Frameworks" / "update-tools" / name


def _checked(args, message, timeout=300):
    try:
        return subprocess.run(args, capture_output=True, check=True, timeout=timeout,
                              env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"})
    except (OSError, subprocess.SubprocessError) as error:
        raise UpdateCheckError(message) from error


def _identity(app):
    try:
        info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
        if info.get("CFBundleIdentifier") != BUNDLE_ID or info.get("CFBundleExecutable") != EXECUTABLE:
            raise ValueError("bundle")
        return Release(info["CFBundleShortVersionString"], info["CFBundleVersion"])
    except (KeyError, OSError, TypeError, ValueError, plistlib.InvalidFileException) as error:
        raise UpdateCheckError("无法核对 Mac 应用的身份和版本。") from error


def _cdhash(app):
    failure = "Mac 应用签名校验未通过，已停止更新。"
    _checked(["/usr/bin/codesign", "--verify", "--deep", "--strict", app], failure)
    info = _checked(["/usr/bin/codesign", "-d", "--verbose=4", app], failure)
    match = re.search(rb"^CDHash=([0-9a-f]{40})$", info.stderr, re.M)
    if not match:
        raise UpdateCheckError(failure)
    return match.group(1).decode("ascii")


def _archive_app(archive):
    """Allow a single app bundle and only internal relative symbolic links."""
    names = set()
    links = set()
    roots = set()
    with ZipFile(archive) as source:
        for entry in source.infolist():
            raw = entry.filename.rstrip("/")
            path = PurePosixPath(raw)
            if (not path.parts or path.is_absolute() or str(path) != raw or ".." in path.parts
                    or "\\" in raw or raw in names):
                raise UpdateCheckError("完整包包含无效路径。")
            roots.add(path.parts[0])
            names.add(raw)
            kind = stat.S_IFMT(entry.external_attr >> 16)
            if kind == stat.S_IFLNK:
                if entry.file_size > 4096:
                    raise UpdateCheckError("完整包包含无效链接。")
                target = source.read(entry).decode("utf-8")
                resolved = posixpath.normpath(posixpath.join(str(path.parent), target))
                if not target or target.startswith("/") or not resolved.startswith(path.parts[0] + "/"):
                    raise UpdateCheckError("完整包链接超出应用目录。")
                links.add(raw)
            elif kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise UpdateCheckError("完整包包含不支持的文件类型。")
    if len(roots) != 1 or not next(iter(roots)).endswith(".app"):
        raise UpdateCheckError("完整安装包应包含一份 Mac 应用。")
    if any(str(parent) in links for name in names for parent in PurePosixPath(name).parents):
        raise UpdateCheckError("完整包包含穿过链接的路径。")
    return next(iter(roots))


def _copy_verified(package, dest, asset):
    digest = hashlib.sha256()
    size = 0
    with Path(package).open("rb") as src, dest.open("xb") as out:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            size += len(chunk)
            if size > asset.size:
                raise UpdateCheckError("更新包大小不符，请重新下载。")
            digest.update(chunk)
            out.write(chunk)
    if size != asset.size or digest.hexdigest() != asset.sha256:
        raise UpdateCheckError("更新包校验未通过，请重新下载。")


def prepare_update(package, asset, target):
    from eggie_update_feed import read_update_public_key, verify_manifest

    app = installed_bundle()
    if not app:
        raise UpdateCheckError("请从已安装的 Mac 应用中启动更新。")
    key = read_update_public_key()
    if not key or asset not in verify_manifest(asset.signed_manifest, key, target):
        raise UpdateCheckError("无法验证 Mac 更新包的发布签名。")
    current = _identity(app)
    if (asset.platform != "macos-arm64" or asset.target != target
            or target.sort_key() <= current.sort_key()
            or asset.kind not in ("delta", "full")):
        raise UpdateCheckError("更新包与本机版本不匹配，请重新检查更新。")
    if asset.kind == "delta" and asset.base != current:
        raise DeltaNotApplicable("本机版本与增量包不匹配，当前版本可继续使用。")
    if not os.access(_tool(app, "EggieUpdateHelper"), os.X_OK):
        raise UpdateCheckError("本机缺少更新组件，请使用完整安装包。")
    if "/AppTranslocation/" in str(app):
        raise UpdateCheckError("请先将应用移到“应用程序”目录，再重新打开更新。")
    old_hash = _cdhash(app)
    try:
        stage = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=app.parent))
    except OSError as error:
        raise UpdateCheckError("没有权限在当前安装目录更新，或磁盘空间不足。可使用完整安装包。") from error
    try:
        archive = stage / "download"
        _copy_verified(package, archive, asset)
        new = stage / "Next.app"
        if asset.kind == "delta":
            try:
                _checked([_tool(app, "BinaryDelta"), "apply", app, new, archive],
                         "增量包不适用或可用空间不足。当前版本仍可使用。")
            except UpdateCheckError as error:
                cause = error.__cause__
                if isinstance(cause, subprocess.CalledProcessError) and b"Source doesn't have expected hash" in (cause.stderr or b""):
                    raise DeltaNotApplicable("本机文件与增量包的起始版本不一致。") from error
                raise
        else:
            root = _archive_app(archive)
            extracted = stage / "archive"
            extracted.mkdir()
            _checked(["/usr/bin/ditto", "-x", "-k", archive, extracted], "不能解压完整更新包，请检查磁盘空间。")
            (extracted / root).rename(new)
        new_hash = _cdhash(new)
        if _identity(new) != target:
            raise UpdateCheckError("更新包中的程序版本与发布信息不符。")
        _checked([new / "Contents/MacOS" / EXECUTABLE, "--check-install"],
                 "新程序未通过启动检查，当前版本仍可使用。", timeout=90)
        archive.unlink()
        return PreparedMacUpdate(app, stage, old_hash, new_hash)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def launch_update(prepared):
    _checked([_tool(prepared.installed, "EggieUpdateHelper"), "--check-running",
              prepared.installed, str(os.getpid())],
             "同一安装位置可能还有其他 Eggie 窗口或任务，请全部退出后再更新。", timeout=15)
    try:
        process = subprocess.Popen([_tool(prepared.installed, "EggieUpdateHelper"), str(os.getpid()),
                          prepared.installed, prepared.staging, prepared.old_cdhash, prepared.new_cdhash],
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
    except OSError as error:
        raise UpdateCheckError("无法启动 Mac 更新助手，当前应用仍可使用。") from error
    try:
        readable, _, _ = select.select([process.stdout], [], [], 15)
        if not readable or os.read(process.stdout.fileno(), 32) != b"ready\n" or process.poll() is not None:
            raise UpdateCheckError("更新提示窗口未能打开，当前应用保持运行。请稍后重试。")
    except Exception:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        raise
    finally:
        process.stdout.close()


def discard_update(prepared):
    if prepared.staging.parent == prepared.installed.parent and prepared.staging.name.startswith(STAGE_PREFIX):
        shutil.rmtree(prepared.staging, ignore_errors=True)


def confirm_healthy_startup():
    """Acknowledge only from the new frozen bundle after its main window is ready."""
    prefix = "--eggie-update-health="
    options = [arg[len(prefix):] for arg in sys.argv[1:] if arg.startswith(prefix)]
    app = installed_bundle()
    if len(options) != 1 or app is None:
        return
    match = re.fullmatch(r"([a-z0-9_]{8}):([0-9A-Fa-f]{8}-(?:[0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12})", options[0])
    if not match:
        return
    stage = app.parent / f"Eggie 更新恢复-{match.group(1)}.noindex"
    try:
        fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            status = os.fstat(fd)
            if status.st_uid != os.getuid() or status.st_mode & 0o077:
                return
            marker = os.open("ready", os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                             0o600, dir_fd=fd)
            with os.fdopen(marker, "w", encoding="ascii") as receipt:
                receipt.write(match.group(2))
        finally:
            os.close(fd)
    except OSError:
        # The helper will roll back if its private acknowledgment is unavailable.
        return
