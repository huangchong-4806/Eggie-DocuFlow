"""Rebuild only Qt 6.10.3's Cocoa plugin with the pinned upstream accessibility fix.

No Python environment or installed Qt files are modified. Pass downloaded source
and SDK archives in --inputs; checksums are verified before extraction. Build tools
must already be available (or supplied with --cmake and --ninja).
"""
import argparse
import json
import platform
from pathlib import Path
from runpy import run_path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
component = run_path(str(ROOT / "packaging/mac_cocoa.py"))


def build(inputs, output, cmake, ninja):
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("This component build requires an Apple Silicon Mac")
    inputs, output = inputs.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError(f"Preserve the existing component output: {output}")
    recipe = ROOT / "packaging/macos/qt-cocoa"
    sources = {name: recipe / name if name.endswith(".patch") else inputs / name
               for name in component["INPUT_HASHES"]}
    for name, source in sources.items():
        if component["sha256"](source) != component["INPUT_HASHES"][name]:
            raise ValueError(f"Unexpected SHA-256 for {name}")
    cmake, ninja = shutil.which(cmake), shutil.which(ninja)
    if not cmake or not ninja:
        raise ValueError("CMake and Ninja must be available; no tools are installed automatically")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cocoa-build-", dir=output.parent) as temporary:
        work = Path(temporary)
        source_dir, sdk, build_dir = work / "source", work / "sdk", work / "build"
        source_dir.mkdir(); sdk.mkdir()
        subprocess.run(["/usr/bin/tar", "-xf", sources["qtbase-source.tar.xz"], "-C", source_dir], check=True)
        subprocess.run(["/usr/bin/tar", "-xf", sources["qtbase-sdk.7z"], "-C", sdk], check=True)
        qtbase = source_dir / "qtbase-everywhere-src-6.10.3"
        subprocess.run(["/usr/bin/patch", "--batch", "-p1", "-i", sources["QTBUG-149612.patch"]],
                       cwd=qtbase, check=True)
        for tool in (sdk / "libexec/moc", sdk / "libexec/rcc"):
            tool.chmod(tool.stat().st_mode | 0o111)
        subprocess.run([cmake, "-S", recipe, "-B", build_dir, "-G", "Ninja",
                        f"-DCMAKE_MAKE_PROGRAM={ninja}", f"-DCMAKE_PREFIX_PATH={sdk}",
                        f"-DEGGIE_QTBASE_SOURCE={qtbase}", "-DCMAKE_BUILD_TYPE=Release",
                        "-DCMAKE_OSX_ARCHITECTURES=arm64", "-DCMAKE_OSX_DEPLOYMENT_TARGET=14.0"], check=True)
        subprocess.run([cmake, "--build", build_dir, "--parallel", "6"], check=True)
        library = build_dir / "platforms/libqcocoa.dylib"
        subprocess.run(["/usr/bin/lipo", "-verify_arch", "arm64", library], check=True)
        # PyInstaller rewrites framework dependencies and removes this SDK rpath
        # in its binary collection step; only the built app is runnable.
        metadata = {
            "qt_version": component["QT_VERSION"], "fix_commit": component["FIX_COMMIT"],
            "architecture": "arm64", "inputs": component["INPUT_HASHES"],
            "library_sha256": component["sha256"](library),
            "cmake_recipe_sha256": component["sha256"](recipe / "CMakeLists.txt"),
            "compiler": subprocess.check_output(["/usr/bin/clang", "--version"], text=True).splitlines()[0],
        }
        staged = work / "component"; staged.mkdir()
        shutil.copy2(library, staged / library.name)
        (staged / "cocoa-repair.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        staged.rename(output)
    print(f"Verified Cocoa repair component: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cmake", default="cmake")
    parser.add_argument("--ninja", default="ninja")
    args = parser.parse_args()
    build(args.inputs, args.output, args.cmake, args.ninja)
