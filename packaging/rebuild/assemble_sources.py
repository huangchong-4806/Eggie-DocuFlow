"""Rebuild the V1.5.1/2026110402 third-party archive from verified inputs."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import zipfile

BASE_SHA = "667a1b328f8d8442dd2cca8e266da62b871d4471e173b30627d3255747e14633"
LIBYUV_SHA = "9d10677793af0bb47bf9cc1c5f270adc87398a7572db4bb668e794a99905eb4b"
LIBYUV_HEADERS = Path(__file__).with_name("libyuv-644251f2.headers.gz")
README = """# Eggie DocuFlow V1.5.1 · build 2026110402

Start with project-support/BUILD_RELEASE.md and packaging/rebuild/BUILD_2026110402.md
in the accompanying project source. Verify the release download with SHA256SUMS.txt.

sources/2026110402 contains the updated Python dependency source distributions and
native source inputs for the Pillow 13 wheels. records/2026110402 contains the two
upstream Pillow wheel SBOMs, pinned build recipes and license files. Source locations
and hashes are recorded in project-support/packaging/rebuild/sources_2026110402.json.
Native sources common to both builds remain under the original sources/ paths.
The upstream wheel SBOMs can include optional components; the tagged recipes
indicate which optional libraries are enabled for each platform.

The other sources/ and records/ paths retain the acquisition records and original
archives from the verified earlier build, including the full custom MuPDF engine
source and unchanged libraries. Historical Pillow 12 records apply only to the
previous build. Use the current portable requirement lists to choose the matching
versions. The original limitations on reconstructing historical PDFium and
cryptography build infrastructure still apply. This archive does not claim to be a
full offline copy of compilers, development SDKs and external tooling.

MANIFEST.json and the archive's SHA256SUMS.txt cover the individual inputs. The
separate checksum file on the download page covers each published archive.
"""


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def restore_libyuv_archive(download, restored):
    """Restore the release tar metadata; preserve and verify all upstream source bytes."""
    # Gitiles generates fresh mtimes even for a fixed commit. The template is
    # the published tar with every regular-file payload zeroed (17 KiB gzipped).
    tar_bytes = bytearray(gzip.decompress(LIBYUV_HEADERS.read_bytes()))
    with gzip.open(download, "rb") as compressed:
        fetched = compressed.read(8 * 1024 * 1024 + 1)
    if len(fetched) > 8 * 1024 * 1024:
        raise ValueError("Unexpected libyuv archive size")
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as template:
        remaining = {m.name: m for m in template}
    with tarfile.open(fileobj=io.BytesIO(fetched), mode="r:") as upstream:
        for member in upstream:
            expected = remaining.pop(member.name, None)
            if (expected is None or expected.type != member.type
                    or expected.size != member.size or expected.mode & 0o777 != member.mode & 0o777):
                raise ValueError(f"Unexpected libyuv entry: {member.name!r}")
            if member.isreg():
                start = expected.offset_data
                tar_bytes[start:start + member.size] = upstream.extractfile(member).read()
            elif not member.isdir():
                raise ValueError(f"Unsupported libyuv entry: {member.name!r}")
    if remaining:
        raise ValueError("Incomplete libyuv source tree")
    with restored.open("xb") as out:
        with gzip.GzipFile(filename="", mode="wb", fileobj=out, compresslevel=6, mtime=0) as gz:
            gz.write(tar_bytes)
    if sha(restored) != LIBYUV_SHA:
        raise ValueError("libyuv source does not reproduce the verified archive checksum")


def verified_input(cache, spec):
    dest = cache / spec["sha256"]
    if dest.exists() and sha(dest) == spec["sha256"]:
        return dest
    with tempfile.TemporaryDirectory(dir=cache) as temp:
        download = Path(temp) / "download"
        subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location",
                        "--retry", "3", "--output", str(download), spec["url"]], check=True)
        if sha(download) != spec.get("download_sha256", spec["sha256"]):
            if spec["sha256"] != LIBYUV_SHA:
                raise ValueError("Download checksum mismatch: " + spec["url"])
            restored = Path(temp) / "restored"
            restore_libyuv_archive(download, restored)
            download = restored
        if "member" in spec:
            with zipfile.ZipFile(download) as z:
                content = z.read(spec["member"])
            if hashlib.sha256(content).hexdigest() != spec["sha256"]:
                raise ValueError("SBOM checksum mismatch")
            dest.write_bytes(content)
        else:
            download.replace(dest)
    return dest


def assemble(baseline, output, cache, project=None):
    if sha(baseline) != BASE_SHA:
        raise ValueError("Unexpected baseline source archive")
    project = Path(__file__).resolve().parents[2] if project is None else project.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    index = json.loads((project / "packaging/rebuild/sources_2026110402.json").read_text(encoding="utf-8"))
    added = {name: verified_input(cache, spec) for name, spec in index.items()}
    for name in ("BUILD_RELEASE.md", "THIRD_PARTY_NOTICES.md", "LICENSE"):
        added["project-support/" + name] = project / name
    for f in sorted((project / "packaging/rebuild").iterdir()):
        if f.is_file() and not f.name.startswith("."):
            added["project-support/packaging/rebuild/" + f.name] = f
    for name in ("packaging/retired_2026110401.iss", "packaging/EggieDocuFlow_windows.iss"):
        added["project-support/" + name] = project / name
    records = {}
    # STORE keeps digests independent of the host zlib. Upstream archives are already compressed.
    with zipfile.ZipFile(baseline) as old, zipfile.ZipFile(output, "x", allowZip64=True) as out:
        previous = {item["path"]: item for item in json.loads(old.read("MANIFEST.json"))["files"]}
        def put(name, source):
            entry = zipfile.ZipInfo(name, date_time=(2026,11,4,0,0,0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            h = hashlib.sha256()
            size = 0
            with source, out.open(entry, "w") as dst:
                while chunk := source.read(1024 * 1024):
                    dst.write(chunk)
                    h.update(chunk)
                    size += len(chunk)
            return {"path": name, "bytes": size, "sha256": h.hexdigest()}
        for name in sorted(previous.keys() | added.keys()):
            if name in added:
                record = put(name, added[name].open("rb"))
                if name in index and index[name]["sha256"] != record["sha256"]:
                    raise ValueError("Source changed: " + name)
            else:
                record = put(name, old.open(name))
                if previous[name]["sha256"] != record["sha256"]:
                    raise ValueError("Baseline entry changed: " + name)
            records[name] = record
        records["README.md"] = put("README.md", io.BytesIO(README.encode()))
        manifest = {"version":"1.5.1", "build":"2026110402", "baseline_sha256":BASE_SHA,
                    "files":[records[n] for n in sorted(records)]}
        data = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
        records["MANIFEST.json"] = put("MANIFEST.json", io.BytesIO(data))
        sums = "".join(f"{records[n]['sha256']}  {n}\n" for n in sorted(records))
        put("SHA256SUMS.txt", io.BytesIO(sums.encode()))
    print(sha(output), output.name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("baseline", "output", "cache"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--project-root", type=Path, help="Project sources to embed; use the released tag for an exact rebuild")
    args = parser.parse_args()
    assemble(args.baseline, args.output, args.cache, args.project_root)
