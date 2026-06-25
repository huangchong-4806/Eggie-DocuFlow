import os
import re
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


def publish_output(temporary_file, output_file):
    output_file = available_output_path(output_file)
    os.chmod(temporary_file, 0o644)
    os.link(temporary_file, output_file)
    return str(Path(output_file).resolve())
