from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
import time


@dataclass(frozen=True)
class QueueTask:
    source_file: str


class TaskQueue:
    def __init__(self, worker, max_retries=1, log_file=None, max_workers=1, retry_delay=0):
        if max_retries < 0:
            raise ValueError("max_retries 不能小于 0")
        if max_workers < 1:
            raise ValueError("max_workers 不能小于 1")
        if retry_delay < 0:
            raise ValueError("retry_delay 不能小于 0")
        self.worker = worker
        self.max_retries = max_retries
        self.max_workers = max_workers
        self.retry_delay = retry_delay
        self.log_file = Path(log_file).expanduser().resolve() if log_file else None
        self._log_lock = Lock()

    def run(self, tasks, progress_callback=None):
        task_list = [
            task if isinstance(task, QueueTask) else QueueTask(str(task))
            for task in tasks
        ]
        total = len(task_list)
        results = [None] * total
        if not task_list:
            return []

        if self.max_workers == 1 or total == 1:
            for index, task in enumerate(task_list, 1):
                if progress_callback:
                    progress_callback(index - 1, total, f"等待处理：{Path(task.source_file).name}")
                result = self._run_one(task)
                results[index - 1] = result
                if progress_callback:
                    progress_callback(index, total, f"完成：{Path(task.source_file).name}，{result['status']}")
            return results

        if progress_callback:
            workers = min(self.max_workers, total)
            progress_callback(0, total, f"开始批量处理：{total} 个文件，同时处理 {workers} 个")
        with ThreadPoolExecutor(max_workers=min(self.max_workers, total)) as executor:
            futures = {
                executor.submit(self._run_one, task): (index, task)
                for index, task in enumerate(task_list)
            }
            finished = 0
            for future in as_completed(futures):
                index, task = futures[future]
                result = future.result()
                results[index] = result
                finished += 1
                if progress_callback:
                    progress_callback(finished, total, f"已完成 {finished}/{total}：{Path(task.source_file).name}，{result['status']}")
        return results

    def _run_one(self, task):
        started = time.monotonic()
        self._log_event(task, "start")
        last_error = ""
        for attempt in range(1, self.max_retries + 2):
            try:
                result = self._normalize(self.worker(task.source_file), task.source_file)
                if result["status"] == "success":
                    self._log_event(
                        task,
                        "success",
                        attempt=attempt,
                        elapsed=f"{time.monotonic() - started:.2f}s",
                        output_file=result.get("output_file", ""),
                    )
                    return result
                last_error = result["data"].get("error_message", "任务返回失败")
            except Exception as error:
                last_error = f"{type(error).__name__}: {error}"
            self._log_error(task, attempt, last_error)
            if attempt <= self.max_retries and self.retry_delay:
                time.sleep(self.retry_delay)
        failed = {
            "doc_type": "UNKNOWN",
            "data": {
                "source_file": task.source_file,
                "attempts": self.max_retries + 1,
                "error_message": last_error,
            },
            "output_file": "",
            "status": "failed",
        }
        self._log_event(
            task,
            "failed",
            attempts=self.max_retries + 1,
            elapsed=f"{time.monotonic() - started:.2f}s",
            error=last_error,
        )
        return failed

    def _normalize(self, result, source_file):
        if not isinstance(result, dict):
            return {
                "doc_type": "UNKNOWN",
                "data": {"source_file": source_file, "error_message": "任务返回结果格式错误"},
                "output_file": "",
                "status": "failed",
            }
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        data.setdefault("source_file", source_file)
        if "error_message" in result:
            data.setdefault("error_message", result["error_message"])
        return {
            "doc_type": result.get("doc_type", "UNKNOWN"),
            "data": data,
            "output_file": result.get("output_file", ""),
            "status": result.get("status", "failed"),
        }

    def _log_error(self, task, attempt, error_message):
        self._write_log(
            f"source_file={self._clean(task.source_file)} attempt={attempt} "
            f"error={self._clean(error_message)}\n"
        )

    def _log_event(self, task, event, **fields):
        parts = [f"event={event}", f"source_file={self._clean(task.source_file)}"]
        parts.extend(f"{key}={self._clean(value)}" for key, value in fields.items())
        self._write_log(" ".join(parts) + "\n")

    def _write_log(self, text):
        if not self.log_file:
            return
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with self._log_lock:
            with self.log_file.open("a", encoding="utf-8") as log:
                log.write(text)

    def _clean(self, value):
        return str(value).replace("\n", " ").replace("\r", " ")
