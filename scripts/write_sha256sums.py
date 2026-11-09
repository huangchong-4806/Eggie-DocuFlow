"""Write a SHA256SUMS.txt for one or more package files."""
import hashlib
import sys
from pathlib import Path


def main(argv):
    if len(argv) < 3:
        raise SystemExit("usage: write_sha256sums.py <file> [<file> ...] <SHA256SUMS.txt>")
    output = Path(argv[-1])
    lines = []
    for name in argv[1:-1]:
        path = Path(name)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}\n")
    output.write_text("".join(lines), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main(sys.argv)
