"""Include only an explicitly selected Ed25519 public key in a PyInstaller build."""
import base64
import os
from pathlib import Path


# Released before Eggie could install signed updates itself.
LEGACY_RELEASES = {("1.5.1", "2026110401"), ("1.5.1", "2026110402")}


def build_trust_data(version):
    selected = os.environ.get("EGGIE_UPDATE_PUBLIC_KEY_FILE")
    if not selected:
        if version["BUILD_TYPE"] == "development" or (version["APP_VERSION"], version["BUILD_NUMBER"]) in LEGACY_RELEASES:
            return []
        raise ValueError("Set EGGIE_UPDATE_PUBLIC_KEY_FILE to the release public key before packaging this build.")
    key = Path(selected).resolve(strict=True)
    if key.name != "eggie-update-ed25519.pub" or key.stat().st_size > 128:
        raise ValueError("Expected a public key file named eggie-update-ed25519.pub")
    raw = base64.b64decode(key.read_bytes().strip(), validate=True)
    if len(raw) != 32:
        raise ValueError("Expected exactly 32 public key bytes encoded in base64")
    return [(str(key), ".")]
