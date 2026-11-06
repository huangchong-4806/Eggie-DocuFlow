"""Stage a verified release for the installed app without modifying user documents."""
import platform
import sys
import sysconfig
import tempfile
from dataclasses import dataclass
from pathlib import Path

from eggie_update_feed import UpdateAsset, download_asset, read_update_public_key, verify_manifest
from update_check import UpdateCheckError


def installed_platform():
    if not getattr(sys, "frozen", False):
        return None
    if sys.platform == "darwin" and platform.machine() == "arm64":
        import eggie_update_mac
        if eggie_update_mac.installed_bundle() is not None:
            return "macos-arm64"
    if sys.platform == "win32" and sysconfig.get_platform() == "win-amd64":
        import eggie_update_windows
        if eggie_update_windows.can_update_installation():
            return "windows-x64"
    return None


def _installer(platform_name):
    if platform_name == "macos-arm64":
        import eggie_update_mac
        return eggie_update_mac
    if platform_name == "windows-x64":
        import eggie_update_windows
        return eggie_update_windows
    raise UpdateCheckError("此系统没有可用的软件内更新方式。")


def full_alternative(asset):
    key = read_update_public_key()
    if key is None:
        raise UpdateCheckError("无法验证完整更新包。")
    entries = verify_manifest(asset.signed_manifest, key, asset.target)
    if asset not in entries:
        raise UpdateCheckError("无法验证所选增量包。")
    return next(entry for entry in entries if entry.platform == asset.platform and entry.kind == "full")


class DownloadCancelled(Exception):
    pass


@dataclass
class PreparedDownload:
    asset: UpdateAsset
    native: object

    def discard(self):
        _installer(self.asset.platform).discard_update(self.native)

    def launch(self):
        _installer(self.asset.platform).launch_update(self.native)


def stage_download(asset, cancelled, on_progress):
    installer = _installer(asset.platform)

    def progress(done, total):
        if cancelled.is_set():
            raise DownloadCancelled()
        on_progress(done, total)

    with tempfile.TemporaryDirectory(prefix="eggie-update-download-") as folder:
        package = download_asset(asset, Path(folder), progress)
        progress(asset.size, asset.size)
        native = installer.prepare_update(package, asset, asset.target)
    staged = PreparedDownload(asset, native)
    if cancelled.is_set():
        staged.discard()
        raise DownloadCancelled()
    return staged
