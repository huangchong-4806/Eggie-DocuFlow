import os
import subprocess
import sys
from pathlib import Path

from document_router import process_document


def runtime_base():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parents[3]
    return Path(__file__).resolve().parents[1]


def _apple_script_text(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def choose_pdf(folder):
    script = (
        'POSIX path of (choose file with prompt "请选择需要处理的 PDF 文件" '
        'of type {"com.adobe.pdf"} default location '
        f'(POSIX file "{_apple_script_text(folder)}"))'
    )
    selected = subprocess.run(
        ["/usr/bin/osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    return selected.stdout.strip() if selected.returncode == 0 else ""


def show_result(result, log_folder):
    if result["status"] == "success":
        title = "文档处理完成"
        message = (
            f"类型：{result['doc_type']}\n"
            f"输出：{result['output_file']}"
        )
    else:
        title = "文档处理失败"
        message = f"请查看日志：{log_folder}"
    script = (
        f'display alert "{_apple_script_text(title)}" '
        f'message "{_apple_script_text(message)}" '
        'buttons {"确定"} default button "确定"'
    )
    subprocess.run(
        ["/usr/bin/osascript", "-e", script],
        capture_output=True,
        text=True,
    )


def main():
    base = runtime_base()
    output_folder = base / "output"
    log_folder = base / "logs"
    test_folder = base / "test_files"
    output_folder.mkdir(parents=True, exist_ok=True)
    log_folder.mkdir(parents=True, exist_ok=True)
    test_folder.mkdir(parents=True, exist_ok=True)

    command_line_pdf = next(
        (
            Path(value).expanduser()
            for value in sys.argv[1:]
            if not value.startswith("-") and Path(value).suffix.lower() == ".pdf"
        ),
        None,
    )
    pdf_file = command_line_pdf or choose_pdf(test_folder)
    if not pdf_file:
        return 0

    result = process_document(
        os.fspath(pdf_file),
        output_dir=output_folder,
        log_root=log_folder,
    )
    print(f"doc_type: {result['doc_type']}")
    print(f"output_file: {result['output_file']}")
    print(f"status: {result['status']}")

    if command_line_pdf is None:
        show_result(result, log_folder)
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
