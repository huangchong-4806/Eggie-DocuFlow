"""Produce a new Sparkle delta and verify it reconstructs the expected signed app."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eggie_update_mac import _cdhash, _identity, _tool


def build_delta(base, target, output):
    base, target = base.resolve(strict=True), target.resolve(strict=True)
    output = output.absolute()
    if output.suffix != ".delta" or output.exists():
        raise ValueError("Choose a new .delta filename")
    old, new = _identity(base), _identity(target)
    if new.sort_key() <= old.sort_key():
        raise ValueError("Target version and build must be newer than the base")
    _cdhash(base)
    expected_hash = _cdhash(target)
    tool = _tool(base, "BinaryDelta")
    with tempfile.TemporaryDirectory(prefix=".eggie-delta-", dir=output.parent) as temporary:
        patch = Path(temporary) / "created.delta"
        restored = Path(temporary) / "check.app"
        subprocess.run([tool, "create", base, target, patch], check=True)
        subprocess.run([tool, "apply", base, restored, patch], check=True)
        if _identity(restored) != new or _cdhash(restored) != expected_hash:
            raise ValueError("Reconstructed app does not match the target")
        os.link(patch, output)
    return output.stat().st_size


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(f"Verified delta: {build_delta(args.base, args.target, args.output):,} bytes")
