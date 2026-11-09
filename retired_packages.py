"""Remove the old v2 package after it was renamed to layout_batch.

Windows installs copy new files over the old tree and otherwise leave removed
directories behind. Mac in-app update replaces the whole .app, so the installed
bundle is already the new tree. These helpers only delete an install-relative
directory when it still looks like the old Python package.
"""
from pathlib import Path
import shutil


RETIRED_PACKAGE_DIRS = ("v2", "_internal/v2")


def _inside(root, path):
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def is_retired_package(directory):
    directory = Path(directory)
    try:
        if not directory.is_dir() or directory.is_symlink():
            return False
        names = [child.name for child in directory.iterdir()]
    except OSError:
        return False
    if "__init__.py" in names or "__init__.pyc" in names:
        return True
    return any(name.startswith("__init__.cpython-") and name.endswith(".pyc") for name in names)


def remove_retired_packages(install_root):
    """Delete leftover v2 packages. Return the relative paths that were removed."""
    root = Path(install_root)
    removed = []
    for relative in RETIRED_PACKAGE_DIRS:
        path = root.joinpath(*relative.split("/"))
        if not _inside(root, path) or not is_retired_package(path):
            continue
        shutil.rmtree(path)
        removed.append(relative)
    return tuple(removed)
