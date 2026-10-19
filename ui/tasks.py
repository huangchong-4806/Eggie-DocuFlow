import multiprocessing
import time
from dataclasses import replace
from pathlib import Path
from queue import Empty

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from api_layer import extract_document_to_files, process_document_with_ocr
from pdf_invoice_tool import run_invoice_batch_task


class DocumentOCRThread(QThread):
    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, task_kind, source_file, output_folder, provider, parent=None):
        super().__init__(parent)
        self.task_kind = task_kind
        self.source_file = source_file
        self.output_folder = output_folder
        self.provider = provider

    def _progress(self, value, total, message):
        self.progress.emit(value, total, message)

    def run(self):
        try:
            if self.task_kind == "process":
                result = process_document_with_ocr(
                    self.source_file,
                    self.output_folder,
                    provider_name=self.provider,
                    progress_callback=self._progress,
                )
            else:
                result = extract_document_to_files(
                    self.source_file,
                    self.output_folder,
                    self.provider,
                    progress_callback=self._progress,
                )
        except Exception as error:
            self.failed.emit(f"{type(error).__name__}: {error}")
            return
        self.completed.emit(result)


class BackgroundTaskThread(QThread):
    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, worker, parent=None):
        super().__init__(parent)
        self.worker = worker

    def _progress(self, value, total, message):
        self.progress.emit(int(value), int(total), str(message))

    def run(self):
        try:
            result = self.worker(self._progress)
        except Exception as error:
            self.failed.emit(f"{type(error).__name__}: {error}")
            return
        self.completed.emit(result)


class InvoiceBatchProcessThread(QThread):
    """Keep invoice parsing outside the app process so it can always be stopped."""

    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        source_files,
        output_folder,
        parent=None,
    ):
        super().__init__(parent)
        self.source_files = tuple(str(path) for path in source_files)
        self.output_folder = str(output_folder)
        self._force_stop_requested = False

    def force_stop(self):
        self._force_stop_requested = True

    @staticmethod
    def _stop_process(process):
        if process.is_alive():
            process.terminate()
        process.join(timeout=3)
        if process.is_alive():
            process.kill()
            process.join(timeout=3)

    def _handle_message(self, message):
        kind, payload = message
        if kind == "progress":
            self.progress.emit(*payload)
            return False
        if kind == "completed":
            self.completed.emit(payload)
            return True
        if kind == "failed":
            self.failed.emit(str(payload))
            return True
        return False

    def run(self):
        process = None
        result_queue = None
        try:
            context = multiprocessing.get_context("spawn")
            result_queue = context.Queue()
            process = context.Process(
                target=run_invoice_batch_task,
                args=(self.source_files, self.output_folder, result_queue),
            )
            process.start()
            finished = False
            while process.is_alive() and not finished:
                if self._force_stop_requested:
                    self._stop_process(process)
                    self.cancelled.emit()
                    return
                try:
                    message = result_queue.get(timeout=0.1)
                except Empty:
                    continue
                finished = self._handle_message(message)

            if finished:
                process.join(timeout=3)
                return

            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                try:
                    if self._handle_message(result_queue.get(timeout=0.1)):
                        return
                except Empty:
                    continue
            self.failed.emit("发票处理意外结束，未生成不完整 Excel。")
        except Exception as error:
            self.failed.emit(f"{type(error).__name__}: {error}")
        finally:
            if process is not None and process.is_alive():
                self._stop_process(process)
            if result_queue is not None:
                result_queue.close()
                result_queue.join_thread()


class PdfWorkspaceProcess(QObject):
    completed = Signal(int, int, object)
    failed = Signal(int, int, str)
    discarded = Signal(int)
    progress = Signal(int, int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None
        self._pending = []
        self._active = None
        self._counter = 0
        self._temporary_path = None
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self._poll)

    def _start(self):
        if self._process is not None:
            if not self._process.is_alive():
                raise RuntimeError("PDF 后台已退出，请清空工作区后重新打开文件。")
            return
        from pdf_workspace import run_pdf_workspace_worker

        context = multiprocessing.get_context("spawn")
        self._requests, self._responses = context.Queue(), context.Queue()
        self._cancel = context.Event()
        self._process = context.Process(target=run_pdf_workspace_worker,
                                        args=(self._requests, self._responses, self._cancel), daemon=True)
        self._process.start()
        self._timer.start()

    def submit(self, operation, payload, revision):
        self._counter += 1
        request = (self._counter, revision, operation, payload)
        if operation == "render":
            for queued in self._pending[:]:
                if queued[2] == "render" and (queued[1] != revision or (
                        queued[3]["page_id"], queued[3].get("max_pixels")) == (
                            payload["page_id"], payload.get("max_pixels"))):
                    self._pending.remove(queued)
                    self.discarded.emit(queued[0])
            self._pending.append(request)
        else:
            self._pending.insert(0, request)
        # Let callers register callbacks before even a startup error is delivered.
        QTimer.singleShot(0, self._dispatch)
        return request[0]

    def _dispatch(self):
        if self._active or not self._pending:
            return
        self._active = self._pending.pop(0)
        try:
            self._start()
            self._cancel.clear()
            if self._active[2] == "export":
                from utils.file_helper import temporary_output
                # The parent owns this path so a crashed PDF worker cannot orphan it.
                self._temporary_path = temporary_output(self._active[3]["output_file"])
                self._active[3]["temporary_path"] = self._temporary_path
            self._requests.put(self._active)
        except Exception:
            request, self._active = self._active, None
            self.failed.emit(request[0], request[1], "PDF 后台或输出目录无法使用。请检查后重试；原文件未修改。" + self._clear_temporary())
            for queued in self._pending:
                self.discarded.emit(queued[0])
            self._pending.clear()

    def _clear_temporary(self):
        path, self._temporary_path = self._temporary_path, None
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                return f"\n临时文件未能清理，请手动检查：{path}"
        return ""

    def _poll(self):
        while True:
            try:
                request_id, revision, kind, result = self._responses.get_nowait()
            except Empty:
                break
            if not self._active or self._active[0] != request_id:
                continue
            if kind == "progress":
                self.progress.emit(request_id, revision, result)
                continue
            cleanup_warning = self._clear_temporary()
            if cleanup_warning:
                if kind == "completed":
                    result = replace(result, failures=tuple(result.failures) + (cleanup_warning,))
                else:
                    result += cleanup_warning
            self._active = None
            if kind == "completed":
                self.completed.emit(request_id, revision, result)
            else:
                self.failed.emit(request_id, revision, result)
            self._dispatch()
        if self._active and self._process is not None and not self._process.is_alive():
            request, self._active = self._active, None
            self.failed.emit(request[0], request[1], "PDF 后台意外退出，编辑状态已保留；请清空后重新打开文件。" + self._clear_temporary())
            for queued in self._pending:
                self.discarded.emit(queued[0])
            self._pending.clear()
            self._timer.stop()

    def cancel(self):
        cancelled = [request for request in self._pending if request[2] != "release"]
        self._pending = [request for request in self._pending if request[2] == "release"]
        if self._process is not None:
            self._cancel.set()
        for request_id, revision, operation, _ in cancelled:
            if operation == "render":
                self.discarded.emit(request_id)
            else:
                self.failed.emit(request_id, revision, "已取消操作，任务尚未开始。")

    def shutdown(self):
        self._timer.stop()
        for queued in self._pending:
            self.discarded.emit(queued[0])
        self._pending.clear()
        if self._process is not None:
            # Export cancellation is cooperative; the UI does not allow closing mid-export.
            self._cancel.set()
            if self._process.is_alive():
                self._requests.put((-1, 0, "close", {}))
                self._process.join(timeout=1)
                if self._process.is_alive():
                    self._process.terminate()
                    self._process.join(timeout=1)
            self._requests.cancel_join_thread()
            self._responses.cancel_join_thread()
            self._requests.close()
            self._responses.close()
            self._process = None
        self._clear_temporary()
        self._active = None


__all__ = ["BackgroundTaskThread", "DocumentOCRThread", "InvoiceBatchProcessThread", "PdfWorkspaceProcess"]
