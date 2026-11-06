"""Build the native handoff tool and unpack only the pinned Sparkle delta utility."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
from urllib.request import urlopen

SPARKLE = "2.10.1"
ARCHIVE_SHA256 = "1a856d2a9edb8e628de88121d7be04cf0e2167f8641650b78fca00b14244cf27"
ARCHIVE_URL = f"https://github.com/sparkle-project/Sparkle/releases/download/{SPARKLE}/Sparkle-{SPARKLE}.tar.xz"


def prepare(directory):
    directory.mkdir(parents=True, exist_ok=True)
    cached = os.environ.get("EGGIE_SPARKLE_ARCHIVE")
    archive = Path(cached) if cached else directory / "Sparkle.tar.xz"
    if not cached and not archive.exists():
        part = directory / "Sparkle.download"
        try:
            with urlopen(ARCHIVE_URL, timeout=30) as response, part.open("wb") as dest:
                shutil.copyfileobj(response, dest)
            part.replace(archive)
        finally:
            part.unlink(missing_ok=True)
    with archive.open("rb") as src:
        digest = hashlib.file_digest(src, "sha256").hexdigest()
    if digest != ARCHIVE_SHA256:
        raise ValueError("Sparkle release SHA-256 mismatch")
    with tarfile.open(archive) as tar:
        for member, output in (("./bin/BinaryDelta", "BinaryDelta"), ("./LICENSE", "Sparkle-LICENSE.txt")):
            entry = tar.getmember(member)
            if not entry.isfile():
                raise ValueError("Unexpected Sparkle archive structure")
            with tar.extractfile(entry) as src, (directory / output).open("wb") as dest:
                shutil.copyfileobj(src, dest)
    (directory / "BinaryDelta").chmod(0o755)
    source = Path(__file__).resolve().parents[1] / "packaging/macos/EggieUpdateHelper.swift"
    subprocess.run(["/usr/bin/xcrun", "swiftc", "-O", "-target", "arm64-apple-macosx15.0",
                    source, "-o", directory / "EggieUpdateHelper"], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    prepare(parser.parse_args().directory)
