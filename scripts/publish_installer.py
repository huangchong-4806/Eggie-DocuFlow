"""Publish a verified installer without deleting the previous complete file."""
import os
from pathlib import Path
import sys
import time


def publish_installer(source, target, timeout_seconds=5):
    source, target = Path(source), Path(target)
    if source.parent.resolve() != target.parent.resolve():
        raise ValueError("Stage the installer in its destination directory")
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            os.replace(source, target)
            return
        except OSError as error:
            remaining = deadline - time.monotonic()
            # Windows can deny a rename while another process briefly opens the
            # executable without delete sharing. Never remove the old file first.
            if getattr(error, "winerror", None) not in (5, 32) or remaining <= 0:
                raise
            time.sleep(min(0.1, remaining))


if __name__ == "__main__":
    publish_installer(*sys.argv[1:])
