import shutil
from pathlib import Path

from utils.file_helper import publish_output, temporary_output


def export_text(text_file, output_file):
    temporary_file = temporary_output(output_file)
    try:
        with open(temporary_file, "w", encoding="utf-8") as output:
            output.write("文档类型：UNKNOWN\n识别结果：无法分类\n\n")
            with open(text_file, encoding="utf-8") as source:
                shutil.copyfileobj(source, output, length=1024 * 1024)
        return publish_output(temporary_file, output_file)
    finally:
        Path(temporary_file).unlink(missing_ok=True)
