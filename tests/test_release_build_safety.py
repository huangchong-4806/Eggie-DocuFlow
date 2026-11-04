import gzip
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch



ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("assemble_sources", ROOT / "packaging/rebuild/assemble_sources.py")
sources = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sources)


def zipped_tar(entries, mtime):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as tar:
        for name, content in entries:
            member = tarfile.TarInfo(name)
            member.mtime = mtime
            member.size = len(content)
            tar.addfile(member, io.BytesIO(content))
    result = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=result, compresslevel=6, mtime=0) as gz:
        gz.write(data.getvalue())
    return result.getvalue()


class SourceArchiveTests(unittest.TestCase):
    def test_gitiles_repack_checks_the_whole_tree_before_caching(self):
        entries = [("src/a", b"abc"), ("src/b", b"x")]
        original = zipped_tar(entries, 1)
        digest = hashlib.sha256(original).hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            template = root / "headers.gz"
            template.write_bytes(zipped_tar([(n, bytes(len(v))) for n, v in entries], 1))
            cache = root / "cache"
            cache.mkdir()
            spec = {"sha256": digest, "url": "https://example.invalid/fixed-commit"}
            with patch.object(sources, "LIBYUV_HEADERS", template), patch.object(sources, "LIBYUV_SHA", digest):
                for candidate in [entries + [entries[0]], entries[:1], entries + [("extra", b"")],
                                  [("src/a", b"bad"), entries[1]], list(reversed(entries))]:
                    data = zipped_tar(candidate, 2)
                    def download(cmd, **kwargs):
                        Path(cmd[cmd.index("--output") + 1]).write_bytes(data)
                    with self.subTest(entries=candidate), patch.object(sources.subprocess, "run", download):
                        if candidate == list(reversed(entries)):
                            self.assertEqual(sources.verified_input(cache, spec).read_bytes(), original)
                        else:
                            with self.assertRaises(ValueError):
                                sources.verified_input(cache, spec)
                            self.assertEqual(list(cache.iterdir()), [])


@unittest.skipUnless(sys.platform == "win32", "Requires native Windows PowerShell")
class WindowsBuildTests(unittest.TestCase):
    def test_concurrent_builds_and_corrupt_copy(self):
        compiler = shutil.which("ISCC.exe")
        if not compiler:
            for base in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
                candidate = Path(os.environ.get(base, "")) / "Inno Setup 6/ISCC.exe"
                if candidate.is_file():
                    compiler = str(candidate)
                    break
        if not compiler:
            if os.environ.get("GITHUB_ACTIONS"):
                self.fail("Inno Setup missing from Windows CI")
            self.skipTest("Inno Setup not installed")
        with tempfile.TemporaryDirectory(prefix="Eggie build test ") as folder:
            root = Path(folder)
            script = root / "scripts/build_windows.ps1"
            script.parent.mkdir()
            shutil.copyfile(ROOT / "scripts/build_windows.ps1", script)
            package = root / "packaging"
            package.mkdir()
            (package / "ChineseSimplified.isl").touch()
            (root / "version.py").write_text('APP_VERSION = "1.5.1"\n')
            (package / "EggieDocuFlow_windows.iss").write_text(
                '[Setup]\nAppName=Test\nAppVersion=1\nDefaultDirName={tmp}\\EggieTest\n'
                'OutputDir={#GetEnv("EGGIE_APP_OUTPUT_DIR")}\nOutputBaseFilename=EggieDocuFlow_V1.5.1_Windows_x64_Setup\n'
                '[Files]\nSource: "{#GetEnv("EGGIE_APP_SOURCE_DIR")}\\*"; DestDir: "{app}"\n')
            # A small PyInstaller stand-in lets both builders rendezvous reliably.
            (root / "PyInstaller.py").write_text(
                'import os, sys, time\nfrom pathlib import Path\n'
                'dist = Path(sys.argv[sys.argv.index("--distpath") + 1])\n'
                'assert Path(os.environ["PYINSTALLER_CONFIG_DIR"]).parent == dist.parent\n'
                'Path(dist.parent.name + ".ready").touch()\n'
                'for _ in range(200):\n'
                '    if len(list(Path.cwd().glob("*.ready"))) >= 2: break\n'
                '    time.sleep(.05)\n'
                'else: raise RuntimeError("Builds did not get separate directories")\n'
                'app = dist / "Eggie DocuFlow"\napp.mkdir(parents=True)\n'
                '(app / "Eggie DocuFlow.exe").write_bytes(b"fixture")\n')
            stage = root / "local/EggieDocuFlowBuild"
            stage.mkdir(parents=True)
            sentinel = stage / "keep"
            sentinel.write_text("existing")
            env = dict(os.environ, PYTHON=sys.executable, LOCALAPPDATA=str(stage.parent),
                       PATH=str(Path(compiler).parent) + os.pathsep + os.environ["PATH"])
            shell = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]
            jobs = [subprocess.Popen(shell + ["-File", str(script)], cwd=root, env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT) for _ in range(2)]
            outputs = [job.communicate(timeout=90)[0] for job in jobs]
            for job, output in zip(jobs, outputs):
                self.assertEqual(job.returncode, 0, output[-1600:])
            installer = next((root / "release").glob("*.exe"))
            good = installer.read_bytes()
            self.assertEqual(good[:2], b"MZ")
            # Simulate a shared drive that returns success after copying the wrong bytes.
            cmd = ("function Copy-Item { param($LiteralPath,$Destination) "
                   "[IO.File]::WriteAllText($Destination,'damaged') }; & './scripts/build_windows.ps1'")
            failed = subprocess.run(shell + ["-Command", cmd], cwd=root, env=env, capture_output=True, timeout=90)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn(b"SHA-256", failed.stderr)
            self.assertEqual(installer.read_bytes(), good)
            self.assertEqual(list(installer.parent.iterdir()), [installer])
            self.assertEqual(list(stage.iterdir()), [sentinel])
