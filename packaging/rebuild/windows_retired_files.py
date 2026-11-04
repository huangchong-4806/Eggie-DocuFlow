"""Generate the Inno Setup upgrade list from two private application runtimes."""
import argparse
import hashlib
from pathlib import Path


def make_list(old_app: Path, new_app: Path) -> str:
    old = old_app / "_internal"
    new = new_app / "_internal"
    if not all((d / "Eggie DocuFlow.exe").is_file() and (d / "_internal").is_dir()
               for d in (old_app, new_app)):
        raise ValueError("Both applications must be complete PyInstaller outputs")
    lines = ["; Files retired after V1.5.1 build 2026110401. Only remove exact originals."]
    for file in sorted(old.rglob("*")):
        relative = file.relative_to(old)
        if not file.is_file() or (new / relative).exists():
            continue
        name = "_internal\\" + str(relative).replace("/", "\\")
        if any(c in name for c in "'\"{};\r\n"):
            raise ValueError(f"Unsafe installer filename: {name!r}")
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        lines.append(f'Type: files; Name: "{{app}}\\{name}"; Check: OriginalFile(\'{name}\', \'{digest}\')')
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("old_app", type=Path)
    cli.add_argument("new_app", type=Path)
    cli.add_argument("output", type=Path)
    args = cli.parse_args()
    args.output.write_text(make_list(args.old_app, args.new_app), encoding="utf-8")
