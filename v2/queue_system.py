from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class QueueTask:
    source_file: str


class TaskQueue:
    def __init__(self, worker, max_retries=1, log_file=None):
        if max_retries < 0:
            raise ValueError("max_retries 不能小于 0")
        self.worker = worker
        self.max_retries = max_retries
        self.log_file = Path(log_file).expanduser().resolve() if log_file else None

    def run(self, tasks, progress_callback=None):
        task_list = [
            task if isinstance(task, QueueTask) else QueueTask(str(task))
            for task in tasks
        ]
        total = len(task_list)
        results = []
        for index, task in enumerate(task_list, 1):
            if progress_callback:
                progress_callback(index - 1, total, f"等待处理：{Path(task.source_file).name}")
            result = self._run_one(task)
            results.append(result)
            if progress_callback:
                progress_callback(index, total, f"完成：{Path(task.source_file).name}，{result['status']}")
        return results

    def _run_one(self, task):
        last_error = ""
        for attempt in range(1, self.max_retries + 2):
            try:
                result = self._normalize(self.worker(task.source_file), task.source_file)
                if result["status"] == "success":
                    return result
                last_error = result["data"].get("error_message", "任务返回失败")
            except Exception as error:
                last_error = f"{type(error).__name__}: {error}"
            self._log_error(task, attempt, last_error)
        return {
            "doc_type": "UNKNOWN",
            "data": {
                "source_file": task.source_file,
                "attempts": self.max_retries + 1,
                "error_message": last_error,
            },
            "output_file": "",
            "status": "failed",
        }

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
        if not self.log_file:
            return
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with self.log_file.open("a", encoding="utf-8") as log:
            log.write(
                f"source_file={task.source_file} attempt={attempt} "
                f"error={error_message}\n"
            )
