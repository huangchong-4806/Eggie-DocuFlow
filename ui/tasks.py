import multiprocessing
import time
from queue import Empty

from PySide6.QtCore import QThread, Signal

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


__all__ = ["BackgroundTaskThread", "DocumentOCRThread", "InvoiceBatchProcessThread"]
