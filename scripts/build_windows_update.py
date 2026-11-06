"""Stamp isolated PyInstaller outputs and generate a Windows Inno delta project."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat
import subprocess
import tempfile


STAMP = "eggie-runtime.json"
EXE = "Eggie DocuFlow.exe"
APP_ID = "{{7DA942BC-98E2-48DB-93C7-741D7FD9C1C3}"
TEMPLATE = Path(__file__).resolve().parents[1] / "packaging" / "windows" / "delta.iss.in"


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def version_key(version, build):
    if (not re.fullmatch(r"(?:0|[1-9][0-9]{0,8})(?:\.(?:0|[1-9][0-9]{0,8})){2}", version)
            or not re.fullmatch(r"[0-9]{10}", build)):
        raise ValueError("Invalid application version or build")
    return (*map(int, version.split(".")), int(build))


def check_component(name):
    if (not name or name in (".", "..") or name[-1] in ". " or PureWindowsPath(name).is_reserved()
            or any(ch in """'";{}:\\*?|<>/""" or ord(ch) < 32 for ch in name)):
        raise ValueError(f"Unsafe path in Windows installer: {name!r}")


def reparse(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _files(root):
    if reparse(root):
        raise ValueError("Runtime root cannot be a link")
    files = {}
    folded = set()
    def walk(folder):
        for child in sorted(folder.iterdir(), key=lambda p: p.name.casefold()):
            check_component(child.name)
            path = child.relative_to(root).as_posix()
            if path.casefold() in folded or reparse(child):
                raise ValueError(f"Ambiguous path or link in Windows runtime: {path}")
            folded.add(path.casefold())
            if folder == root and (path == STAMP or re.fullmatch(r"unins[0-9]+\.(?:exe|dat|msg)", path, re.I)):
                if not child.is_file():
                    raise ValueError(f"Unexpected runtime entry: {path}")
                continue
            if folder == root and path not in (EXE, "_internal"):
                raise ValueError(f"Expected a clean PyInstaller runtime, found {path}")
            if child.is_dir():
                walk(child)
            elif child.is_file():
                files[path] = digest(child)
            else:
                raise ValueError(f"Unsupported runtime entry: {path}")
    walk(root)
    if EXE not in files or not any(path.startswith("_internal/") for path in files):
        raise ValueError("Expected a complete Windows PyInstaller onedir output")
    return files


def write_stamp(root, version, build):
    version_key(version, build)
    record = {"schema": 1, "version": version, "build": build, "files": _files(root)}
    content = (json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    stamp = root / STAMP
    if stamp.exists():
        if stamp.read_bytes() != content:
            raise ValueError("Existing stamp differs; use a fresh isolated runtime")
        return
    # Reserve the exact destination; never replace an unrelated file.
    with stamp.open("xb") as f:
        try:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            f.close()
            stamp.unlink(missing_ok=True)
            raise


def read_stamp(root):
    files = _files(root)
    path = root / STAMP
    source = path.read_bytes()
    record = json.loads(source)
    if (set(record) != {"schema", "version", "build", "files"}
            or type(record["schema"]) is not int or record["schema"] != 1 or record["files"] != files):
        raise ValueError("Runtime contents differ from stamp; refusing to build an update")
    version_key(record["version"], record["build"])
    return record, hashlib.sha256(source).hexdigest()


def build_delta(old, new, out):
    old_record, old_stamp_hash = read_stamp(old)
    new_record, new_stamp_hash = read_stamp(new)
    if version_key(new_record["version"], new_record["build"]) <= version_key(old_record["version"], old_record["build"]):
        raise ValueError("Update target must be newer than its exact baseline")
    old_files, new_files = old_record["files"], new_record["files"]
    names = sorted(old_files.keys() | new_files.keys())
    seen = {}
    for name in names:
        for part in (PureWindowsPath(name), *PureWindowsPath(name).parents):
            actual = part.as_posix()
            previous = seen.setdefault(actual.casefold(), actual)
            if previous != actual:
                raise ValueError("Case-only renames are not supported; use a full package")
    # A file on one side that is a directory on the other cannot be patched safely.
    file_names = {name.casefold() for name in names}
    for name in names:
        if any(parent.as_posix().casefold() in file_names for parent in PureWindowsPath(name).parents):
            raise ValueError("File/directory path conflicts require a full package")

    changed = [n for n in names if n in new_files and old_files.get(n) != new_files[n]]
    removed = [n for n in names if n in old_files and n not in new_files]
    new_paths = [n for n in changed if n not in old_files]
    template = TEMPLATE.read_text(encoding="utf-8")
    out = out.absolute()
    if out.exists() or not out.parent.is_dir():
        raise ValueError("Choose an unused output directory with an existing parent")
    old_root, new_root = old.resolve(), new.resolve()
    if any(out.resolve().is_relative_to(p) for p in (old_root, new_root)):
        raise ValueError("Delta output must be outside both source runtimes")
    stage = Path(tempfile.mkdtemp(prefix=".eggie-delta-", dir=out.parent))
    try:
        payload = stage / "payload"
        install = []
        deletes = []
        checks = []
        verify_new = []
        for name, checksum in sorted(old_files.items()):
            windows_name = name.replace("/", "\\")
            checks.append(f"  if not Matches('{windows_name}', '{checksum}') then exit;")
            checks.append(f"  if not MatchesAt(Backup, '{windows_name}', '{checksum}') then exit;")
        for name in new_paths:
            windows_name = name.replace("/", "\\")
            checks.append(f"  if not AvailablePath('{windows_name}') then exit;")
        for name in [*changed, STAMP]:
            source, target = new / name, payload / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if digest(target) != (new_stamp_hash if name == STAMP else new_files[name]):
                raise ValueError("Runtime changed while delta files were copied")
            path = PureWindowsPath(name)
            subdir = "" if str(path.parent) == "." else "\\" + str(path.parent)
            install.append(f'Source: "payload\\{path}"; DestDir: "{{app}}{subdir}"; '
                           f"Flags: ignoreversion; BeforeInstall: RequireAbsent('{path}')")
        for name in [*removed, *(n for n in changed if n in old_files), STAMP]:
            path = str(PureWindowsPath(name))
            checksum = old_stamp_hash if name == STAMP else old_files[name]
            deletes.append(f'Type: files; Name: "{{app}}\\{path}"; Check: Matches(\'{path}\', \'{checksum}\')')
        for name, checksum in sorted(new_files.items()):
            windows_name = name.replace("/", "\\")
            verify_new.append(f"  if not Matches('{windows_name}', '{checksum}') then exit;")
        for name in removed:
            verify_new.append(f"  if not AvailablePath('{PureWindowsPath(name)}') then exit;")
        iss = template.replace("@APP_ID@", APP_ID).replace("@VERSION@", new_record["version"])
        for tag, value in {
            "BASE_STAMP": old_stamp_hash, "TARGET_STAMP": new_stamp_hash,
            "BASENAME": f'Eggie-{old_record["build"]}-to-{new_record["build"]}-Windows-x64',
            "VERIFY_BASE": "\n".join(checks), "VERIFY_NEW": "\n".join(verify_new),
            "DELETE": "\n".join(deletes), "FILES": "\n".join(install),
        }.items():
            iss = iss.replace("@" + tag + "@", value)
        (stage / "patch.iss").write_text(iss, encoding="utf-8-sig", newline="\n")
        stage.rename(out)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return len(changed), len(removed)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cmds = cli.add_subparsers(dest="operation", required=True)
    stamp = cmds.add_parser("stamp")
    stamp.add_argument("--root", required=True, type=Path)
    stamp.add_argument("--version", required=True)
    stamp.add_argument("--build", required=True)
    delta = cmds.add_parser("delta")
    for option in ("old", "new", "output"):
        delta.add_argument("--" + option, required=True, type=Path)
    delta.add_argument("--iscc", type=Path, help="Optionally compile the project on Windows")
    args = cli.parse_args()
    try:
        if args.operation == "stamp":
            write_stamp(args.root, args.version, args.build)
        else:
            changed, removed = build_delta(args.old, args.new, args.output)
            if args.iscc:
                subprocess.run([args.iscc, args.output / "patch.iss"], check=True)
            print(f"{changed} changed/new files, {removed} retired files")
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        cli.exit(2, f"Cannot prepare Windows update: {error}\n")


if __name__ == "__main__":
    main()
