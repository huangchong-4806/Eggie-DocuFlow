from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import QMessageBox, QProgressDialog
from ui.tasks import BackgroundTaskThread


class WindowTasksMixin:
    """Existing window methods; initialization remains in the window."""

    def task_is_running(self):
        return bool(
            (self.background_task_thread and self.background_task_thread.isRunning())
            or (self.document_ocr_thread and self.document_ocr_thread.isRunning())
        )

    def set_global_task_active(self, active):
        self.stack.setEnabled(not active)
        self.sidebar.setEnabled(not active)

    def start_background_task(
        self,
        title,
        message,
        worker,
        on_success,
        on_failure=None,
        total=0,
        status_label=None,
        task_thread=None,
        allow_force_stop=False,
        on_cancel=None,
    ):
        if self.task_is_running():
            QMessageBox.information(
                self,
                "任务正在进行",
                "当前任务尚未完成，请等待完成后再开始新的任务。",
            )
            return False

        progress = QProgressDialog(
            f"任务正在执行，请勿关闭软件。\n\n{message}",
            "",
            0,
            max(int(total), 0),
            self,
        )
        progress.setWindowTitle(title)
        if allow_force_stop:
            progress.setCancelButtonText("强制结束当前任务")
        else:
            progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setWindowModality(Qt.WindowModal)
        if total <= 0:
            progress.setRange(0, 0)
        progress.show()

        thread = task_thread or BackgroundTaskThread(worker, self)
        self.background_task_thread = thread
        self.background_task_progress = progress
        self.background_task_status_label = status_label
        self.background_task_title = title
        thread.progress.connect(
            lambda value, maximum, text, task=thread: self.background_task_progress_changed(
                task, value, maximum, text
            )
        )
        thread.completed.connect(
            lambda result, task=thread: self.background_task_completed(
                task, result, on_success
            )
        )
        thread.failed.connect(
            lambda error, task=thread: self.background_task_failed(
                task, error, on_failure
            )
        )
        if allow_force_stop and hasattr(thread, "force_stop"):
            progress.canceled.connect(
                lambda task=thread: self.request_force_stop_background_task(
                    task,
                    on_cancel,
                )
            )
        if hasattr(thread, "cancelled"):
            thread.cancelled.connect(
                lambda task=thread: self.background_task_cancelled(task, on_cancel)
            )
        thread.finished.connect(thread.deleteLater)
        self.set_global_task_active(True)
        thread.start()
        return True

    def request_force_stop_background_task(self, thread, on_cancel):
        if self.background_task_thread is not thread:
            return
        answer = QMessageBox.question(
            self,
            "强制结束当前任务",
            "即将停止当前正在处理的发票。未完成的发票不会生成不完整 Excel；"
            "已经完成的结果会保留。\n\n是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        if self.background_task_progress is not None:
            self.background_task_progress.setCancelButton(None)
            self.background_task_progress.setLabelText("正在停止当前任务，请稍候…")
        if self.background_task_status_label is not None:
            self.background_task_status_label.setText("正在停止当前任务，请稍候…")
        thread.force_stop()

    def background_task_progress_changed(self, thread, value, total, text):
        if self.background_task_thread is not thread:
            return
        progress = self.background_task_progress
        if progress is not None:
            if total > 0:
                progress.setRange(0, total)
                progress.setValue(max(0, min(value, total)))
            else:
                progress.setRange(0, 0)
            progress.setLabelText(
                "任务正在执行，请勿关闭软件。\n\n" + text
            )
        if self.background_task_status_label is not None:
            self.background_task_status_label.setText(text)

    def clear_background_task(self, thread):
        if self.background_task_thread is not thread:
            return False
        progress = self.background_task_progress
        self.background_task_thread = None
        self.background_task_progress = None
        self.background_task_status_label = None
        self.background_task_title = ""
        self.set_global_task_active(False)
        if progress is not None:
            progress.close()
        return True

    def background_task_completed(self, thread, result, on_success):
        if not self.clear_background_task(thread):
            return
        on_success(result)

    def background_task_failed(self, thread, error_message, on_failure):
        title = self.background_task_title
        if not self.clear_background_task(thread):
            return
        if on_failure is not None:
            on_failure(error_message)
            return
        QMessageBox.critical(
            self,
            f"{title or '任务'}失败",
            error_message,
        )

    def background_task_cancelled(self, thread, on_cancel):
        if not self.clear_background_task(thread):
            return
        if on_cancel is not None:
            on_cancel()
            return
        QMessageBox.information(self, "任务已结束", "当前任务已强制结束。")

    def restart_for_update(self):
        if self.pdf_workspace.has_unsaved_changes():
            QMessageBox.information(self, "请先处理当前 PDF",
                                    "当前 PDF 还有未保存的修改。处理完成后，可再次点击“重启并更新”。")
            return
        self._restarting_for_update = True
        try:
            self.close()
        finally:
            self._restarting_for_update = False

    def _start_windows_handoff(self):
        dialog = QProgressDialog("正在等待 Windows 授权并核对更新包…", "", 0, 0, self)
        dialog.setWindowTitle("重启并更新")
        dialog.setCancelButton(None)
        dialog.setWindowModality(Qt.WindowModal)
        self._windows_handoff_dialog = dialog
        self.set_global_task_active(True)
        dialog.show()
        self.update_check_button.start_windows_handoff(self._finish_windows_handoff)

    def _finish_windows_handoff(self, error):
        dialog, self._windows_handoff_dialog = self._windows_handoff_dialog, None
        dialog.close()
        dialog.deleteLater()
        if error is not None:
            self.set_global_task_active(False)
            QMessageBox.warning(self, "暂时无法安装更新", str(error))
            return
        self._windows_update_committed = True
        self.close()

    def closeEvent(self, event):
        if self._windows_handoff_dialog is not None:
            self._windows_handoff_dialog.show()
            event.ignore()
            return
        if self._windows_update_committed:
            self.pdf_workspace.shutdown()
            super().closeEvent(event)
            return
        if self.update_check_button.is_downloading():
            QMessageBox.information(self, "正在准备更新", "请先取消下载或等待更新准备完成，再关闭软件。")
            event.ignore()
            return
        running_threads = [
            thread for thread in self.findChildren(QThread) if thread.isRunning()
        ]
        if running_threads:
            QMessageBox.warning(
                self,
                "任务正在进行",
                "文件处理或连接检查尚未完成，请等待完成后再关闭软件。",
            )
            event.ignore()
            return
        if not self.pdf_workspace.request_close():
            event.ignore()
            return
        if self._restarting_for_update:
            if self.update_check_button.needs_windows_handoff():
                self._start_windows_handoff()
                event.ignore()
                return
            try:
                self.update_check_button.launch_prepared()
            except Exception as error:
                QMessageBox.warning(self, "暂时无法安装更新", str(error))
                event.ignore()
                return
        else:
            self.update_check_button.discard_prepared()
        self.pdf_workspace.shutdown()
        super().closeEvent(event)
