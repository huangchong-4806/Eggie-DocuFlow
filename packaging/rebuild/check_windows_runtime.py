"""Check a disposable Windows PyInstaller build against the V1.5.0 native runtime."""
import argparse
import hashlib
import re
import tempfile
from pathlib import Path

REFERENCE_SHA256 = "9d84426cc91d0d7bdda6ad3cdab42cf8138061911665e6c812ad76b84d433ce7"
HOST_ONLY = re.compile(r"_internal/(?:api-ms-win-[\w-]+|ucrtbase|lib(?:crypto|ssl)-3-x64)\.dll", re.I)


def inventory(root):
    files = {}
    for path in root.rglob("*"):
        if path.suffix.lower() not in (".dll", ".pyd") or not path.is_file():
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Runtime file is outside the build or is a link: " + str(path))
        name = path.relative_to(root).as_posix()
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def check(reference, candidate, apply):
    reference, candidate = reference.resolve(), candidate.resolve()
    if reference.is_relative_to(candidate) or candidate.is_relative_to(reference):
        raise ValueError("Use two separate directories.")
    if not all((p / "Eggie DocuFlow.exe").is_file() for p in (reference, candidate)):
        raise ValueError("Both directories must contain Eggie DocuFlow.exe.")
    baseline = inventory(reference)
    manifest = "".join(f"{name}\t{baseline[name]}\n" for name in sorted(baseline))
    if hashlib.sha256(manifest.encode()).hexdigest() != REFERENCE_SHA256:
        raise ValueError("Reference DLL/PYD inventory is not the verified V1.5.0 runtime.")
    current = inventory(candidate)
    mismatches = [name for name in baseline if current.get(name) != baseline[name]]
    extras = sorted(current.keys() - baseline.keys())
    if mismatches or any(not HOST_ONLY.fullmatch(name) for name in extras):
        raise ValueError(f"Runtime mismatch. Missing or changed: {mismatches!r}. Extra files: {extras!r}.")
    print(f"{len(baseline)} reference files matched. Build-host extras: {len(extras)}.")
    for name in extras:
        print(name)
    if not apply or not extras:
        return
    if candidate.name != "Eggie DocuFlow" or candidate.parent.name != "dist":
        raise ValueError("--apply requires a disposable dist/Eggie DocuFlow directory.")
    with tempfile.TemporaryDirectory(dir=candidate.parent) as staging:
        moved = []
        try:
            for name in extras:
                path = candidate / name
                saved = Path(staging) / path.name
                path.rename(saved)
                moved.append((saved, path))
            if inventory(candidate) != baseline:
                raise ValueError("Final inventory failed to match the verified reference.")
        except BaseException:
            for saved, path in reversed(moved):
                saved.rename(path)
            raise
    print("Final runtime inventory verified.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="Remove only listed host extras from disposable build output.")
    args = parser.parse_args()
    try:
        check(args.reference, args.candidate, args.apply)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Stopped: {error}\n")
