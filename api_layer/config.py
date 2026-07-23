import json
import os
import tempfile
from pathlib import Path


PROVIDER_LABELS = {
    "baidu": "百度智能云 OCR",
    "alibaba": "阿里云 OCR",
}
PROVIDER_ENV_KEYS = {
    "baidu": ("BAIDU_OCR_API_KEY", "BAIDU_OCR_SECRET_KEY"),
    "alibaba": (
        "ALIBABA_CLOUD_ACCESS_KEY_ID",
        "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
    ),
}
ALLOWED_ENV_KEYS = {"EGGIE_OCR_PROVIDER"} | {
    key for keys in PROVIDER_ENV_KEYS.values() for key in keys
}


def _default_config_dir(platform_name, home_directory, app_data=""):
    home_directory = Path(home_directory)
    if platform_name == "nt":
        if app_data:
            return Path(app_data) / "Eggie DocuFlow"
        return home_directory / "AppData" / "Roaming" / "Eggie DocuFlow"
    if platform_name == "posix" and (home_directory / "Library").is_dir():
        return home_directory / "Library" / "Application Support" / "Eggie DocuFlow"
    return home_directory / ".config" / "eggie-docuflow"


def get_config_dir():
    override = os.environ.get("EGGIE_OCR_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _default_config_dir(
        os.name,
        Path.home(),
        os.environ.get("APPDATA", "").strip(),
    )


def get_config_file():
    return get_config_dir() / ".env"


def _decode_value(value):
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
        return str(decoded)
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return value


def _read_env_file(config_file=None):
    config_file = Path(config_file or get_config_file())
    values = {}
    if not config_file.is_file():
        return values
    try:
        lines = config_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key in ALLOWED_ENV_KEYS:
            values[key] = _decode_value(value)
    return values


def _sync_process_environment(previous_values, values, managed_keys):
    for key in managed_keys:
        previous_value = str(previous_values.get(key, "")).strip()
        value = str(values.get(key, "")).strip()
        if value:
            os.environ[key] = value
        elif previous_value and os.environ.get(key) == previous_value:
            os.environ.pop(key, None)


def load_env_file(config_file=None):
    values = _read_env_file(config_file)
    for key, value in values.items():
        if value:
            os.environ.setdefault(key, value)
    return values


def _write_env_file(values, config_file=None, managed_keys=()):
    config_file = Path(config_file or get_config_file())
    previous_values = _read_env_file(config_file)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Eggie DocuFlow OCR 本机配置，禁止上传或分享",
        "# 密钥只供当前用户在本机调用 OCR 服务。",
    ]
    for key in ("EGGIE_OCR_PROVIDER", *PROVIDER_ENV_KEYS["baidu"], *PROVIDER_ENV_KEYS["alibaba"]):
        value = str(values.get(key, "")).strip()
        if value:
            lines.append(f"{key}={json.dumps(value, ensure_ascii=False)}")
    content = "\n".join(lines) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".env-",
        suffix=".tmp",
        dir=config_file.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, config_file)
        os.chmod(config_file, 0o600)
    finally:
        Path(temporary_name).unlink(missing_ok=True)
    _sync_process_environment(previous_values, values, managed_keys)
    return config_file


def load_credentials(provider):
    if provider not in PROVIDER_ENV_KEYS:
        raise ValueError("不支持的 OCR 服务平台。")
    values = load_env_file()
    result = {}
    for key in PROVIDER_ENV_KEYS[provider]:
        result[key] = os.environ.get(key) or values.get(key, "")
    return result


def save_credentials(provider, credentials):
    if provider not in PROVIDER_ENV_KEYS:
        raise ValueError("不支持的 OCR 服务平台。")
    allowed = PROVIDER_ENV_KEYS[provider]
    cleaned = {
        key: str(credentials.get(key, "")).strip().replace("\r", "").replace("\n", "")
        for key in allowed
    }
    if not all(cleaned.values()):
        raise ValueError("请填写完整的密钥信息。")
    values = _read_env_file()
    values.update(cleaned)
    values["EGGIE_OCR_PROVIDER"] = provider
    return _write_env_file(
        values,
        managed_keys={"EGGIE_OCR_PROVIDER", *allowed},
    )


def delete_credentials(provider):
    if provider not in PROVIDER_ENV_KEYS:
        raise ValueError("不支持的 OCR 服务平台。")
    values = _read_env_file()
    for key in PROVIDER_ENV_KEYS[provider]:
        values.pop(key, None)
    return _write_env_file(values, managed_keys=set(PROVIDER_ENV_KEYS[provider]))


def is_provider_configured(provider):
    try:
        return all(load_credentials(provider).values())
    except ValueError:
        return False


def selected_provider(default="baidu"):
    values = load_env_file()
    provider = os.environ.get("EGGIE_OCR_PROVIDER") or values.get("EGGIE_OCR_PROVIDER")
    return provider if provider in PROVIDER_ENV_KEYS else default


def select_provider(provider):
    if provider not in PROVIDER_ENV_KEYS:
        raise ValueError("不支持的 OCR 服务平台。")
    values = _read_env_file()
    values["EGGIE_OCR_PROVIDER"] = provider
    return _write_env_file(values, managed_keys={"EGGIE_OCR_PROVIDER"})
