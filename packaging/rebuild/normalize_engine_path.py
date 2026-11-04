"""Drop a build-host path from the installed custom binding before freezing."""
from base64 import urlsafe_b64encode
import csv
import hashlib
from importlib.metadata import distribution
import re
import sys


def normalize():
    if sys.prefix == sys.base_prefix:
        raise RuntimeError("Use a dedicated build virtual environment")
    dist = distribution("PyMuPDF")
    if dist.version != "1.28.2":
        raise RuntimeError("Unexpected PyMuPDF version")
    name = "pymupdf/_build.py"
    path = dist.locate_file(name)
    data, n = re.subn(br"^mupdf_location = [^\r\n]+", b"mupdf_location = 'mupdf-1.28.5-source'",
                      path.read_bytes(), flags=re.MULTILINE)
    if n != 1:
        raise RuntimeError("Unexpected binding metadata layout")
    record = next(dist.locate_file(p) for p in dist.files if p.name == "RECORD")
    with record.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    row = next(row for row in rows if row[0] == name)
    row[1:] = ["sha256=" + urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("="), str(len(data))]
    path.write_bytes(data)
    with record.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, lineterminator="\n").writerows(rows)


if __name__ == "__main__":
    normalize()
