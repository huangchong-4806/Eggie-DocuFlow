"""Guarded relocation of RC2's two build-only patches into a fresh source tree."""
import argparse
import hashlib
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

EXPECTED_PROJECT = 'bdf402755c7f90737c666ade7507779ee86a8637e7776cc7babba365c538606e'
EXPECTED_HELPER = 'a2807645dff808bee4e32ea426705355c82642165640542e32f2c96bc844f0a3'


def prepare(project, helper, python_path):
    if hashlib.sha256(project).hexdigest() != EXPECTED_PROJECT:
        raise ValueError('MuPDF project is not the unmodified recorded 1.28.5 source')
    # Installed pipcl may use Windows CRLF; compare its canonical source text.
    canonical = helper.replace(b'\r\n', b'\n')
    if hashlib.sha256(canonical).hexdigest() != EXPECTED_HELPER:
        raise ValueError('pipcl helper is not the unmodified recorded version 13')
    if any(c in python_path for c in '\r\n"') or not python_path.lower().endswith('.exe'):
        raise ValueError('Expected a single Windows Python executable path')
    old = b'python scripts\\mupdfwrap.py --venv -b 0'
    if project.count(old) != 7:
        raise ValueError('Expected exactly seven MuPDF prebuild commands')
    command = ('&quot;' + escape(python_path) + '&quot; scripts\\mupdfwrap.py -b 0').encode()
    revised_project = project.replace(old, command)
    ET.fromstring(revised_project)
    before = b"if platform.machine().startswith('ARM'):"
    after = b"if __import__('sysconfig').get_platform().lower().endswith(('arm64', 'arm32')):"
    if helper.count(before) != 1:
        raise ValueError('Expected exactly one target-CPU check')
    revised_helper = helper.replace(before, after)
    compile(revised_helper, 'wdev.py', 'exec')
    return revised_project, revised_helper


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mupdf-root', type=Path, required=True)
    parser.add_argument('--pipcl-helper', type=Path, required=True)
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    project = args.mupdf_root / 'platform/win32/mupdfcpp.vcxproj'
    helper = args.pipcl_helper
    for path in (project, helper, args.python):
        if path.is_symlink() or not path.is_file():
            raise ValueError('Expected an existing regular file: ' + str(path))
    originals = [project.read_bytes(), helper.read_bytes()]
    revised = prepare(*originals, str(args.python.resolve()))
    backups = [p.with_name(p.name + '.before-rc2-relocation') for p in (project, helper)]
    if any(p.exists() for p in backups):
        raise ValueError('Backup already exists; inspect prior work before applying again')
    print('Validated MuPDF 7-command patch and pipcl 1-condition patch.')
    if not args.apply:
        print('Check only: no files changed. Use --apply only in a fresh isolated build tree.')
        return
    for path, backup, original, new in zip((project, helper), backups, originals, revised):
        with backup.open('xb') as stream:
            stream.write(original)
        path.write_bytes(new)
        if path.read_bytes() != new:
            raise RuntimeError('Patch readback failed; original preserved at ' + str(backup))
    print('Applied both build patches; original files preserved beside each target.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Stopped: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
