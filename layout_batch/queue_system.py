from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
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

    def run(self, tasks, progress_callback=None, stop_event=None):
        task_list = [
            task if isinstance(task, QueueTask) else QueueTask(str(task))
            for task in tasks
        ]
        total = len(task_list)
        results = [None] * total
        if not task_list:
            return []

        def stopping():
            return stop_event is not None and stop_event.is_set()

        def complete(index, result):
            results[index] = result
            if progress_callback:
                progress_callback(finished, total, f"已完成 {finished}/{total}：{Path(task_list[index].source_file).name}，{result['status']}")

        finished = 0
        if self.max_workers == 1 or total == 1:
            for index, task in enumerate(task_list):
                if stopping():break
                if progress_callback:
                    progress_callback(index,total,f"等待处理：{Path(task.source_file).name}")
                if stopping():break
                result = self._run_one(task,stop_event)
                finished += 1
                complete(index,result)
        else:
            workers = min(self.max_workers,total)
            if progress_callback:
                progress_callback(0,total,f"开始批量处理：{total} 个文件，同时处理 {workers} 个")
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {}
                next_index = 0
                while futures or next_index < total:
                    while len(futures) < workers and next_index < total and not stopping():
                        futures[executor.submit(self._run_one,task_list[next_index],stop_event)] = next_index
                        next_index += 1
                    if not futures:break
                    done,_ = wait(futures,return_when=FIRST_COMPLETED)
                    for future in done:
                        finished += 1
                        complete(futures.pop(future),future.result())
        for index, result in enumerate(results):
            if result is None:
                results[index] = self._normalize({"status":"unprocessed","data":{"stopped":True},
                                                  "error_message":"用户已停止后续处理。"}, task_list[index].source_file)
        return results

    def _run_one(self, task, stop_event=None):
        started = time.monotonic()
        warnings = []

        def record(logger, *args, **fields):
            try:
                logger(*args, **fields)
            except OSError as error:
                warning = f"队列日志未写入：{error}"
                if warning not in warnings:
                    warnings.append(warning)

        def with_warnings(result):
            if warnings:
                previous = result["data"].get("warning", "")
                result["data"]["warning"] = "；".join(filter(None, [previous, *warnings]))
            return result

        record(self._log_event, task, "start")
        last_error = ""
        for attempt in range(1, self.max_retries + 2):
            try:
                result = self._normalize(self.worker(task.source_file), task.source_file)
                if result["status"] == "failed" and result["output_file"] and Path(result["output_file"]).is_file():
                    result["data"]["retryable"] = False
                    result["data"].setdefault("error_message", "结果文件已存在，请核对后再处理。")
                if result["status"] in ("success", "unprocessed") or result["data"].get("retryable") is False:
                    record(
                        self._log_event, task,
                        result["status"],
                        attempt=attempt,
                        elapsed=f"{time.monotonic() - started:.2f}s",
                        output_file=result.get("output_file", ""),
                    )
                    return with_warnings(result)
                last_error = result["data"].get("error_message", "任务返回失败")
            except Exception as error:
                last_error = f"{type(error).__name__}: {error}"
            record(self._log_error, task, attempt, last_error)
            if stop_event is not None and stop_event.is_set():
                break
            if attempt <= self.max_retries and self.retry_delay:
                if stop_event is None:
                    time.sleep(self.retry_delay)
                elif stop_event.wait(self.retry_delay):
                    break
        failed = {
            "doc_type": "UNKNOWN",
            "data": {
                "source_file": task.source_file,
                "attempts": attempt,
                "error_message": last_error,
            },
            "output_file": "",
            "status": "failed",
        }
        record(
            self._log_event, task,
            "failed",
            attempts=attempt,
            elapsed=f"{time.monotonic() - started:.2f}s",
            error=last_error,
        )
        return with_warnings(failed)

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
