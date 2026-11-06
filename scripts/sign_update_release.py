"""Build the signed EggieUpdate-v1.json from locally built release artifacts.

Run from the project root. The private key is a base64-encoded 32-byte Ed25519
seed supplied via stdin by a keychain/secret manager. Never place it in the
repository, in command arguments, or beside published files.
"""
import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eggie_update_feed import MANIFEST_FILENAME, asset_url, verify_manifest
from update_check import Release
from utils.file_helper import publish_new_file, temporary_output


class KeychainSigner:
    """Only public bytes and signatures cross the native helper boundary."""
    def __init__(self, helper, expected_public_key):
        self.helper = str(Path(helper).resolve(strict=True))
        result = subprocess.run([self.helper, "public"], capture_output=True, check=True, timeout=30)
        public = base64.b64decode(result.stdout.strip(), validate=True)
        if public != expected_public_key:
            raise ValueError("Keychain key does not correspond to the client public key")
        self.key = Ed25519PublicKey.from_public_bytes(public)

    def public_key(self):
        return self.key

    def sign(self, payload):
        result = subprocess.run([self.helper, "sign"], input=payload, capture_output=True, check=True, timeout=30)
        signature = base64.b64decode(result.stdout.strip(), validate=True)
        self.key.verify(signature, payload)
        return signature


def sign_release(spec, directory, signer):
    target = Release(**spec["target"])
    entries = []
    for item in spec["assets"]:
        if set(item) != {"platform", "kind", "base", "filename"}:
            raise ValueError("Expected platform, kind, base and filename in the asset list")
        name = item["filename"]
        if Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError("Assets must be files within the release directory")
        path = directory / name
        with path.open("rb") as source:
            digest = hashlib.sha256()
            size = 0
            while block := source.read(1024 * 1024):
                size += len(block)
                digest.update(block)
        entries.append(dict(item, size=size, sha256=digest.hexdigest(), url=asset_url(target, name)))
    payload = json.dumps({"schema": 1, "target": spec["target"], "assets": entries},
                         sort_keys=True, separators=(",", ":")).encode()
    envelope = json.dumps({"payload": base64.b64encode(payload).decode("ascii"),
                           "signature": base64.b64encode(signer.sign(payload)).decode("ascii")},
                          separators=(",", ":")).encode() + b"\n"
    verify_manifest(envelope, signer.public_key().public_bytes_raw(), target)
    return envelope


def publish_manifest(manifest, destination):
    temporary = Path(temporary_output(destination))
    try:
        with temporary.open("wb") as output:
            output.write(manifest)
            output.flush()
            os.fsync(output.fileno())
        publish_new_file(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", required=True, type=Path, help="Directory containing the completed packages")
    parser.add_argument("--spec", required=True, type=Path, help="JSON list of target version and asset definitions")
    parser.add_argument("--public-key", required=True, type=Path, help="The exact public key embedded in the base clients")
    parser.add_argument("--keychain-helper", type=Path, help="Native macOS helper; private key stays in Keychain/helper memory")
    args = parser.parse_args()
    if not args.keychain_helper and sys.stdin.isatty():
        parser.error("Supply the signing key directly from a secret manager on stdin")
    try:
        expected_public_key = base64.b64decode(args.public_key.read_bytes().strip(), validate=True)
        if args.keychain_helper:
            signer = KeychainSigner(args.keychain_helper, expected_public_key)
        else:
            encoded = sys.stdin.buffer.read(129).strip()
            signer = Ed25519PrivateKey.from_private_bytes(base64.b64decode(encoded, validate=True))
        if signer.public_key().public_bytes_raw() != expected_public_key:
            parser.error("Signing key does not correspond to the client public key")
        spec = json.loads(args.spec.read_bytes())
        manifest = sign_release(spec, args.assets, signer)
        destination = args.assets / MANIFEST_FILENAME
        publish_manifest(manifest, destination)
        print(f"Signed release manifest: {destination}")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(2, f"Cannot sign release: {error}\n")


if __name__ == "__main__":
    main()
