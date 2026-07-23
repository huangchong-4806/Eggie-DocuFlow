import errno
import os
import re
import shutil
import tempfile
from pathlib import Path


INVALID_XML_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def available_output_path(path):
    path = Path(path)
    if not path.exists():
        return path
    for number in range(1, 10000):
        candidate = path.with_name(f"{path.stem}_{number}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError("无法生成不重复的输出文件名。")


def temporary_output(output_file):
    descriptor, filename = tempfile.mkstemp(
        prefix=f".{Path(output_file).stem}-",
        suffix=Path(output_file).suffix,
        dir=Path(output_file).parent,
    )
    os.close(descriptor)
    return filename


_LINK_RESTRICTION_ERRORS = {
    errno.EINVAL,
    errno.EPERM,
    errno.EXDEV,
    getattr(errno, "EOPNOTSUPP", errno.EINVAL),
}


def publish_new_file(temporary_file, output_file):
    """Publish a completed file without replacing an existing result."""
    temporary_path = Path(temporary_file)
    output_path = Path(output_file)
    try:
        os.link(temporary_path, output_path)
        return str(output_path.resolve())
    except FileExistsError:
        raise
    except OSError as error:
        if error.errno not in _LINK_RESTRICTION_ERRORS:
            raise

    descriptor = None
    try:
        descriptor = os.open(
            output_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o644,
        )
        with temporary_path.open("rb") as source, os.fdopen(descriptor, "wb") as target:
            descriptor = None
            shutil.copyfileobj(source, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        output_path.unlink(missing_ok=True)
        raise
    return str(output_path.resolve())


def publish_output(temporary_file, output_file):
    os.chmod(temporary_file, 0o644)
    for _ in range(10000):
        final_file = available_output_path(output_file)
        try:
            return publish_new_file(temporary_file, final_file)
        except FileExistsError:
            continue
    raise FileExistsError("无法生成不重复的输出文件名。")
