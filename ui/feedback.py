"""Domestic in-app feedback channel. Never opens a GitHub issue."""
import re
from urllib.parse import urlsplit


DEFAULT_FEEDBACK_CHANNEL = "mailto:448223855@qq.com"
SETTINGS_KEY = "feedback/channel"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_feedback_channel(value):
    """Accept a mailto address or an http(s) questionnaire URL.

    An empty value keeps the default mailbox. GitHub links are rejected so the
    in-app entry stays usable on domestic networks.
    """
    text = str(value or "").strip()
    if not text:
        return DEFAULT_FEEDBACK_CHANNEL
    if text.lower().startswith("mailto:"):
        address = text[7:].split("?", 1)[0].strip()
        if not _EMAIL.fullmatch(address):
            raise ValueError("请填写有效的邮箱，或 http(s) 问卷链接。")
        return "mailto:" + address
    if _EMAIL.fullmatch(text):
        return "mailto:" + text
    if text.lower().startswith(("https://", "http://")):
        parts = urlsplit(text)
        host = (parts.hostname or "").lower()
        if not host or host == "github.com" or host.endswith(".github.com"):
            raise ValueError("反馈入口不使用 GitHub，请填写邮箱或国内问卷链接。")
        return text
    raise ValueError("请填写邮箱，或腾讯问卷 / 金数据的 http(s) 链接。")
