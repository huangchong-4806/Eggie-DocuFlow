import argparse
import json
import sys
from pathlib import Path

import document_router

from v2.queue_system import TaskQueue


def _v2_result(router_result, source_file):
    source_file = str(Path(source_file).expanduser().resolve())
    if not isinstance(router_result, dict):
        return {
            "doc_type": "UNKNOWN",
            "data": {"source_file": source_file, "error_message": "router 返回结果格式错误"},
            "output_file": "",
            "status": "failed",
        }

    data = {"source_file": source_file}
    if "confidence" in router_result:
        data["confidence"] = router_result["confidence"]
    if "error_message" in router_result:
        data["error_message"] = router_result["error_message"]

    return {
        "doc_type": router_result.get("doc_type", "UNKNOWN"),
        "data": data,
        "output_file": router_result.get("output_file", ""),
        "status": router_result.get("status", "failed"),
    }


class BatchEngine:
    def __init__(self, router=None, max_retries=0, log_file=None):
        self.router = router or document_router.process_document
        self.max_retries = max_retries
        self.log_file = log_file

    def scan(self, input_folder, recursive=False):
        folder = Path(input_folder).expanduser().resolve()
        if not folder.is_dir():
            raise NotADirectoryError(f"输入文件夹不存在：{folder}")
        pattern = "**/*.pdf" if recursive else "*.pdf"
        return sorted(path for path in folder.glob(pattern) if path.is_file())

    def process_folder(
        self,
        input_folder,
        output_dir=None,
        recursive=False,
        progress_callback=None,
        log_root=None,
    ):
        input_folder = Path(input_folder).expanduser().resolve()
        output_dir = (
            Path(output_dir).expanduser().resolve()
            if output_dir
            else input_folder / "output"
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        pdf_files = self.scan(input_folder, recursive)
        if progress_callback:
            progress_callback(0, len(pdf_files), f"发现 {len(pdf_files)} 个 PDF")

        def worker(pdf_file):
            result = self.router(
                pdf_file,
                output_dir,
                progress_callback=progress_callback,
                log_root=log_root,
            )
            return _v2_result(result, pdf_file)

        queue = TaskQueue(
            worker,
            max_retries=self.max_retries,
            log_file=self.log_file or output_dir / "queue_errors.log",
        )
        return queue.run(pdf_files, progress_callback=progress_callback)


def process_batch(input_folder, output_dir=None, progress_callback=None):
    return BatchEngine().process_folder(input_folder, output_dir, progress_callback=progress_callback)


def _cli_progress(value, total, message):
    print(f"[{value}/{total}] {message}", file=sys.stderr, flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="DocuFlow v2 批量处理")
    parser.add_argument("input_folder", help="待扫描文件夹")
    parser.add_argument("-o", "--output-dir", help="输出文件夹，默认 input/output")
    parser.add_argument("--recursive", action="store_true", help="扫描子文件夹")
    parser.add_argument("--retries", type=int, default=0, help="失败重试次数")
    parser.add_argument("--log-dir", help="沿用 v1 日志目录")
    parser.add_argument("--queue-log", help="队列错误日志文件")
    args = parser.parse_args(argv)

    results = BatchEngine(max_retries=args.retries, log_file=args.queue_log).process_folder(
        args.input_folder,
        args.output_dir,
        recursive=args.recursive,
        progress_callback=_cli_progress,
        log_root=args.log_dir,
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(result["status"] == "success" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
