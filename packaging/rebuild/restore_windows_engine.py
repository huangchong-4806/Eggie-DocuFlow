"""Restore the verified 1.28.5 runtime in a disposable Windows build environment."""
from base64 import urlsafe_b64encode
import csv
import hashlib
import json
from importlib.metadata import distribution
from pathlib import Path
import sys


def restore(old_app):
    plan = json.loads(Path(__file__).with_name("windows-engine-1.28.5.json").read_text())
    dist = distribution("PyMuPDF")
    if sys.prefix == sys.base_prefix or sys.platform != "win32" or dist.version != "1.28.2":
        raise ValueError("Use a dedicated Windows virtual environment with PyMuPDF 1.28.2")
    changes = {}
    for name, spec in plan["wrappers"].items():
        raw = dist.locate_file(name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != spec["before"]:
            raise ValueError(f"Unexpected upstream wrapper: {name}")
        lines = raw.decode().splitlines(keepends=True)
        for start, end, replacement in reversed(spec["changes"]):
            lines[start:end] = replacement
        data = "".join(lines).encode()
        if hashlib.sha256(data).hexdigest() != spec["after"]:
            raise ValueError(f"Invalid wrapper patch: {name}")
        changes[name] = data
    for name, wanted in plan["native"].items():
        data = (old_app / "_internal" / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != wanted:
            raise ValueError(f"Unexpected released binary: {name}")
        changes[name] = data
    record = next(dist.locate_file(f) for f in dist.files if f.name == "RECORD")
    with record.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    for row in rows:
        if row[0] in changes:
            data = changes.pop(row[0])
            row[1] = "sha256=" + urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
            row[2] = str(len(data))
            dist.locate_file(row[0]).write_bytes(data)
    if changes:
        raise ValueError("Missing upstream package records")
    with record.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, lineterminator="\n").writerows(rows)
    print("Restored and verified release engine from authenticated sources")


if __name__ == "__main__":
    restore(Path(sys.argv[1]))
