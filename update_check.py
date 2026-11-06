"""Read the published release's version record, using GitHub's official latest link."""

import ast
import http.client
import re
import ssl
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import certifi


REPOSITORY = "huangchong-4806/Eggie-DocuFlow"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
LATEST_RELEASE_URL = f"{RELEASES_URL}/latest"
VERSION_PATTERN = r"(?:0|[1-9][0-9]{0,8})(?:\.(?:0|[1-9][0-9]{0,8})){2}"
RECORD_LIMIT = 4096


class UpdateCheckError(ValueError):
    """A safe, user-facing reason that the check could not be completed."""


class DeltaNotApplicable(UpdateCheckError):
    """A verified delta cannot be applied to this installation."""


@dataclass(frozen=True)
class Release:
    version: str
    build: str

    def sort_key(self):
        return (*map(int, self.version.split(".")), int(self.build))

    @property
    def page(self):
        return f"{RELEASES_URL}/tag/v{self.version}"

    def label(self):
        return f"V{self.version}（{self.build}）"


def parse_version_record(tag_version, data):
    # A release tag already contains version.py for the application and both
    # installers. Only inspect literal assignments; never run downloaded code.
    invalid = "官方发布记录不完整，或与发布标签不一致。"
    try:
        tree = ast.parse(data.decode("utf-8"))
    except (UnicodeError, ValueError, SyntaxError, RecursionError) as error:
        raise UpdateCheckError(invalid) from error
    fields = {}
    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            raise UpdateCheckError(invalid)
        target = statement.targets[0]
        value = statement.value
        if (not isinstance(target, ast.Name) or target.id in fields
                or not isinstance(value, ast.Constant) or not isinstance(value.value, str)):
            raise UpdateCheckError(invalid)
        fields[target.id] = value.value
    build = fields.get("BUILD_NUMBER", "")
    if (not re.fullmatch(VERSION_PATTERN, tag_version)
            or fields.get("APP_VERSION") != tag_version or fields.get("BUILD_TYPE") != "release"
            or not re.fullmatch(r"[0-9]{10}", build)):
        raise UpdateCheckError(invalid)
    return Release(tag_version, build)


def fetch_latest_release():
    headers = {"User-Agent": "Eggie-DocuFlow-Update-Check", "Cache-Control": "no-cache"}
    try:
        context = ssl.create_default_context()
        # A portable Python can lack a default CA file on the target machine.
        # Retain system trust (including corporate proxies) when available.
        if not context.cert_store_stats()["x509_ca"]:
            context.load_verify_locations(cafile=certifi.where())
        # GitHub resolves this URL to the official latest release. No API
        # token, local version, or document data is needed for this check.
        request = Request(LATEST_RELEASE_URL, headers=headers, method="HEAD")
        with urlopen(request, timeout=8, context=context) as response:
            tag = re.fullmatch(re.escape(RELEASES_URL) + rf"/tag/v({VERSION_PATTERN})", response.geturl())
        if not tag:
            raise UpdateCheckError("未找到可核对的官方正式版本。")
        version = tag.group(1)
        record_url = f"https://raw.githubusercontent.com/{REPOSITORY}/v{version}/version.py"
        with urlopen(Request(record_url, headers=headers), timeout=8, context=context) as response:
            if response.geturl() != record_url:
                raise UpdateCheckError("无法核对官方版本记录的来源。")
            data = response.read(RECORD_LIMIT + 1)
        if len(data) > RECORD_LIMIT:
            raise UpdateCheckError("官方版本记录超出可读取范围。")
        return parse_version_record(version, data)
    except HTTPError as error:
        raise UpdateCheckError(f"官方发布记录暂时不可用（HTTP {error.code}）。") from error
    except (OSError, http.client.HTTPException) as error:
        raise UpdateCheckError("暂时无法连接官方发布页，请检查网络后重试。") from error
