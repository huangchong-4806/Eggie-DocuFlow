"""Signed Eggie release assets. Public keys are selected at build time only."""
import base64
import hashlib
import http.client
import json
import os
import re
import ssl
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener

import certifi
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from update_check import RELEASES_URL, VERSION_PATTERN, Release, UpdateCheckError


MANIFEST_FILENAME = "EggieUpdate-v1.json"
PUBLIC_KEY_FILENAME = "eggie-update-ed25519.pub"
MAX_MANIFEST_SIZE = 256 * 1024
MAX_PACKAGE_SIZE = 4 * 1024**3
PLATFORMS = {"macos-arm64": {"delta": ".delta", "full": ".zip"},
             "windows-x64": {"delta": ".exe", "full": ".exe"}}
CDN_HOSTS = {"release-assets.githubusercontent.com", "objects.githubusercontent.com",
             "github-releases.githubusercontent.com"}
LAST_LEGACY_RELEASE = Release("1.5.1", "2026110402")


@dataclass(frozen=True)
class UpdateAsset:
    platform: str
    kind: str
    base: Release | None
    target: Release
    filename: str
    size: int
    sha256: str
    url: str
    signed_manifest: bytes = field(repr=False, compare=False, default=b"")


def read_update_public_key() -> bytes | None:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    try:
        with (root / PUBLIC_KEY_FILENAME).open("rb") as source:
            encoded = source.read(129)
        key = base64.b64decode(encoded.strip(), validate=True)
        if len(encoded) > 128 or len(key) != 32:
            raise ValueError()
        return key
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        raise UpdateCheckError("本机更新验证公钥无法读取，请重新安装官方完整包。") from error


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate key")
        result[name] = value
    return result


def _json(data):
    return json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)


def _release(value):
    if (not isinstance(value, dict) or set(value) != {"version", "build"}
            or not re.fullmatch(VERSION_PATTERN, value["version"])
            or not re.fullmatch(r"[0-9]{10}", value["build"])):
        raise ValueError("invalid version record")
    return Release(value["version"], value["build"])


def asset_url(target, filename):
    return f"{RELEASES_URL}/download/v{target.version}/{filename}"


def verify_manifest(envelope: bytes, public_key: bytes, expected: Release) -> tuple[UpdateAsset, ...]:
    """Authenticate the exact signed payload before trusting its release or filenames."""
    try:
        if len(envelope) > MAX_MANIFEST_SIZE or len(public_key) != 32:
            raise ValueError("size")
        outer = _json(envelope)
        if not isinstance(outer, dict) or set(outer) != {"payload", "signature"}:
            raise ValueError("envelope")
        data = base64.b64decode(outer["payload"], validate=True)
        signature = base64.b64decode(outer["signature"], validate=True)
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, data)
        manifest = _json(data)
        if (not isinstance(manifest, dict) or set(manifest) != {"schema", "target", "assets"}
                or type(manifest["schema"]) is not int or manifest["schema"] != 1
                or _release(manifest["target"]) != expected):
            raise ValueError("wrong release")
        entries = manifest["assets"]
        if not isinstance(entries, list) or not 1 <= len(entries) <= 128:
            raise ValueError("asset count")
        assets = []
        keys = set()
        names = set()
        for entry in entries:
            if set(entry) != {"platform", "kind", "base", "filename", "size", "sha256", "url"}:
                raise ValueError("asset fields")
            platform, kind = entry["platform"], entry["kind"]
            suffix = PLATFORMS[platform][kind]
            base = None if entry["base"] is None else _release(entry["base"])
            name, size, digest = entry["filename"], entry["size"], entry["sha256"]
            if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", name)
                    or not name.lower().endswith(suffix)
                    or name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL",
                        *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
                    or type(size) is not int or not 0 < size <= MAX_PACKAGE_SIZE
                    or not re.fullmatch(r"[a-f0-9]{64}", digest)
                    or entry["url"] != asset_url(expected, name)
                    or (base is None) != (kind == "full")
                    or (base is not None and base.sort_key() >= expected.sort_key())
                    or (platform, base) in keys or name.lower() in names):
                raise ValueError("invalid or ambiguous asset")
            keys.add((platform, base))
            names.add(name.lower())
            assets.append(UpdateAsset(platform, kind, base, expected, name, size, digest,
                                      entry["url"], envelope))
        if any((asset.platform, None) not in keys for asset in assets):
            raise ValueError("missing full package")
        return tuple(assets)
    except InvalidSignature as error:
        raise UpdateCheckError("更新清单的签名无法验证，已停止更新。") from error
    except (ValueError, KeyError, TypeError, RecursionError) as error:
        raise UpdateCheckError("更新清单不完整、格式异常或与目标版本不一致，已停止更新。") from error


def select_asset(assets, installed, platform):
    candidates = [asset for asset in assets if asset.platform == platform
                  and asset.target.sort_key() > installed.sort_key()
                  and asset.base in (None, installed)]
    if not candidates:
        raise UpdateCheckError("官方更新清单没有本系统可用的安装包。")
    return min(candidates, key=lambda asset: (asset.size, asset.kind != "delta"))


def _allowed_response(url, original):
    if url == original:
        return True
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.netloc in CDN_HOSTS and
            not parsed.fragment and parsed.path.startswith("/"))


class _ReleaseRedirects(HTTPRedirectHandler):
    def __init__(self, original):
        super().__init__()
        self.original = original

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allowed_response(newurl, self.original):
            raise UpdateCheckError("下载地址发生异常跳转，已停止更新。")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url):
    context = ssl.create_default_context()
    if not context.cert_store_stats()["x509_ca"]:
        context.load_verify_locations(cafile=certifi.where())
    opener = build_opener(HTTPSHandler(context=context), _ReleaseRedirects(url))
    request = Request(url, headers={"User-Agent": "Eggie-DocuFlow-Updater",
                                    "Accept-Encoding": "identity", "Cache-Control": "no-cache"})
    response = opener.open(request, timeout=20)
    if response.status != 200 or not _allowed_response(response.geturl(), url):
        response.close()
        raise UpdateCheckError("更新服务器的响应或来源异常，已停止更新。")
    return response


def fetch_update_asset(installed: Release, latest: Release, platform: str) -> UpdateAsset | None:
    key = read_update_public_key()
    if key is None or installed.sort_key() >= latest.sort_key():
        return None
    try:
        with _open(asset_url(latest, MANIFEST_FILENAME)) as response:
            envelope = response.read(MAX_MANIFEST_SIZE + 1)
    except HTTPError as error:
        if error.code == 404 and latest.sort_key() <= LAST_LEGACY_RELEASE.sort_key():
            return None
        raise UpdateCheckError("无法取得此版本的已签名更新清单，请稍后重试。") from error
    except (OSError, http.client.HTTPException) as error:
        raise UpdateCheckError("读取更新清单失败，请检查网络后重试。") from error
    return select_asset(verify_manifest(envelope, key, latest), installed, platform)


def download_asset(asset: UpdateAsset, directory: Path, progress=None) -> Path:
    """Return a verified file in a new private subdirectory owned by the caller."""
    key = read_update_public_key()
    if key is None or asset not in verify_manifest(asset.signed_manifest, key, asset.target):
        raise UpdateCheckError("所选安装包与已签名的更新清单不符。")
    work = Path(tempfile.mkdtemp(prefix="eggie-update-", dir=directory))
    output = work / asset.filename
    received = 0
    digest = hashlib.sha256()
    try:
        with _open(asset.url) as response, output.open("xb") as handle:
            while chunk := response.read(256 * 1024):
                received += len(chunk)
                if received > asset.size:
                    raise UpdateCheckError("下载大小超过更新清单，文件已丢弃。")
                handle.write(chunk)
                digest.update(chunk)
                if progress is not None:
                    progress(received, asset.size)
            handle.flush()
            os.fsync(handle.fileno())
        if received != asset.size or digest.hexdigest() != asset.sha256:
            raise UpdateCheckError("下载不完整或文件校验失败，请重新下载。")
        return output
    except BaseException as error:
        output.unlink(missing_ok=True)
        work.rmdir()
        if isinstance(error, (OSError, http.client.HTTPException)):
            raise UpdateCheckError("更新包下载或保存失败，请检查网络和可用空间后重试。") from error
        raise
