"""Small startup gate: no Qt, settings, parsers, or downloaded code is loaded here."""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys


def windows_gate_name(root):
    location = os.path.normcase(os.path.abspath(root)).replace("/", "\\").casefold()
    return "Local\\Eggie-Updating-" + hashlib.sha256(location.encode("utf-8")).hexdigest()


def _windows_event(name, access=0x00100000):
    api = ctypes.windll.kernel32.OpenEventW
    api.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    api.restype = wintypes.HANDLE
    return api(access, False, name)


def windows_update_active(root, args):
    kernel = ctypes.windll.kernel32
    # Only the monitor holds this short-lived permission while opening the checked
    # target or restored app. This is a launch-coordination token, not a trust key.
    options = [a.removeprefix("--eggie-update-launch=") for a in args
               if a.startswith("--eggie-update-launch=")]
    if len(options) == 1 and re.fullmatch(r"[0-9a-f]{32}", options[0]):
        permit = _windows_event("Local\\Eggie-Update-" + options[0] + "-launch")
        if permit:
            kernel.CloseHandle(wintypes.HANDLE(permit))
            return False
    name = windows_gate_name(root)
    gate = _windows_event(name)
    if not gate:
        return False
    try:
        if kernel.WaitForSingleObject(wintypes.HANDLE(gate), 0) == 0:
            return False  # Installation has finished; the result window may remain.
        show = _windows_event(name + "-show", 0x0002)
        if show:
            try:
                kernel.SetEvent(wintypes.HANDLE(show))
            finally:
                kernel.CloseHandle(wintypes.HANDLE(show))
        return True
    finally:
        kernel.CloseHandle(wintypes.HANDLE(gate))


def startup_is_blocked():
    if not getattr(sys, "frozen", False):
        return False
    args = sys.argv[1:]
    if args in (["--check-install"], ["--version"]):
        return False
    executable = Path(sys.executable).resolve()
    if sys.platform == "win32":
        return windows_update_active(executable.parent, args)
    if sys.platform == "darwin":
        app = executable.parents[2]
        helper = app / "Contents/Frameworks/update-tools/EggieUpdateHelper"
        if not helper.is_file():
            return False  # Older or unsigned development bundles have no updater.
        permits = [a for a in args if a.startswith(("--eggie-update-health=", "--eggie-update-resume="))]
        permit = permits[0] if len(permits) == 1 else ""
        result = subprocess.run([helper, "--guard-launch", app, permit],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=15)
        return result.returncode != 0
    return False
