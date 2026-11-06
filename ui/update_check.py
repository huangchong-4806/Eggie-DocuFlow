from concurrent.futures import Future
from threading import Event, Thread

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox,
    QProgressDialog, QPushButton, QStyle, QVBoxLayout,
)

from eggie_update_feed import fetch_update_asset
from eggie_update_runtime import DownloadCancelled, full_alternative, installed_platform, stage_download
from excel_merge_tool import format_file_size
from update_check import DeltaNotApplicable, Release, UpdateCheckError, fetch_latest_release
from version import APP_VERSION, BUILD_NUMBER


def _background_future(function, *args):
    future = Future()

    def run():
        try:
            future.set_result(function(*args))
        except Exception as error:
            future.set_exception(error)

    Thread(target=run, daemon=True).start()
    return future


def _check_for_update(installed):
    latest = fetch_latest_release()
    asset = None
    if latest.sort_key() > installed.sort_key():
        platform_name = installed_platform()
        if platform_name:
            asset = fetch_update_asset(installed, latest, platform_name)
    return latest, asset


class UpdateResultDialog(QDialog):
    def __init__(self, parent, title, lines, icon_type, close_text="关闭"):
        super().__init__(parent)
        self.setWindowTitle("检查更新")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(376, 164)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 14)
        layout.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(self.style().standardIcon(icon_type).pixmap(32, 32))
        row.addWidget(icon, 0, Qt.AlignTop)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(3 if len(lines) > 2 else 5)
        self.heading = QLabel(title)
        self.heading.setProperty("homeRole", "cardTitle")
        text_layout.addWidget(self.heading)
        text_layout.addSpacing(1)
        self.detail_labels = []
        for line in lines:
            label = QLabel(line)
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(True)
            text_layout.addWidget(label)
            self.detail_labels.append(label)
        row.addLayout(text_layout, 1)
        layout.addLayout(row)
        layout.addStretch(1)

        self.buttons = QDialogButtonBox()
        close = self.buttons.addButton(close_text, QDialogButtonBox.RejectRole)
        close.setDefault(True)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def add_action(self, text, callback):
        button = self.buttons.addButton(text, QDialogButtonBox.ActionRole)
        button.clicked.connect(self.accept)
        self.accepted.connect(callback)


class UpdateCheckButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__("检查更新", parent)
        self.setToolTip("查看是否有新版本可下载")
        self._future = None
        self._handoff_callback = None
        self._download_dialog = None
        self._download_asset = None
        self._percent = 0
        self._cancelled = Event()
        self._staged = None
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._finish_if_ready)
        self.clicked.connect(self.start_check)

    def start_check(self):
        if self._future is not None:
            return
        if self._staged is not None:
            self._show_ready()
            return
        self.setEnabled(False)
        self.setText("正在检查更新…")
        self._future = _background_future(_check_for_update, Release(APP_VERSION, BUILD_NUMBER))
        self._timer.start()

    def is_downloading(self):
        return self._download_dialog is not None

    def _finish_if_ready(self):
        if self.is_downloading() and not self._cancelled.is_set():
            self._download_dialog.setValue(min(99, self._percent))
            if self._percent == 100:
                self._download_dialog.setLabelText("正在校验并准备更新…")
        if self._future is None or not self._future.done():
            return
        future, self._future = self._future, None
        self._timer.stop()
        if self._handoff_callback is not None:
            callback, self._handoff_callback = self._handoff_callback, None
            error = future.exception()
            if error is None:
                self._staged = None
            callback(error)
            return
        self.setText("检查更新")
        self.setEnabled(True)
        if self.is_downloading():
            self._download_dialog.blockSignals(True)
            self._download_dialog.close()
            self._download_dialog.deleteLater()
            self._download_dialog = None
            self._finish_download(future)
            return
        if not self.window().isVisible():
            return
        installed = Release(APP_VERSION, BUILD_NUMBER)
        current = f"当前版本　{installed.label()}"
        try:
            latest, asset = future.result()
        except Exception as error:
            reason = str(error) if isinstance(error, UpdateCheckError) else "暂时无法读取官方发布记录。"
            box = UpdateResultDialog(
                self.window(), "本次未能确认是否有更新", (current, reason), QStyle.SP_MessageBoxWarning,
            )
            box.add_action("重试", self.start_check)
        else:
            has_update = latest.sort_key() > installed.sort_key()
            if has_update:
                title = "有可用更新"
            elif latest == installed:
                title = "当前已是最新版"
            else:
                title = "当前版本高于已发布的最新正式版"
            lines = [current, f"最新版本　{latest.label()}"]
            if asset is not None:
                kind = "增量更新" if asset.kind == "delta" else "完整更新包"
                lines.append(f"{kind}　需下载 {format_file_size(asset.size)}")
            box = UpdateResultDialog(self.window(), title, lines, QStyle.SP_MessageBoxInformation)
            if asset is not None:
                box.add_action("下载更新", lambda: self._download(asset))
            elif has_update:
                box.add_action("打开官方下载页", lambda: self._open_download(latest.page))
        box.open()

    def _download(self, asset):
        if self._future is not None or self._staged is not None:
            return
        self._download_asset = asset
        self._percent = 0
        self._cancelled = Event()
        dialog = QProgressDialog("正在下载更新…", "取消", 0, 100, self.window())
        dialog.setWindowTitle("下载更新")
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.canceled.connect(self._cancelled.set)
        self._download_dialog = dialog
        self.setText("正在下载更新…")
        self.setEnabled(False)
        dialog.show()
        self._future = _background_future(stage_download, asset, self._cancelled, self._record_progress)
        self._timer.start()

    def _record_progress(self, done, total):
        # No Qt objects in the worker. Reserve the last step for local preparation.
        self._percent = min(100, 100 * done // max(1, total))

    def _finish_download(self, future):
        asset, self._download_asset = self._download_asset, None
        try:
            staged = future.result()
        except DownloadCancelled:
            return
        except Exception as error:
            if self._cancelled.is_set():
                return
            if isinstance(error, DeltaNotApplicable) and asset.kind == "delta":
                try:
                    full = full_alternative(asset)
                except UpdateCheckError as verification_error:
                    error = verification_error
                else:
                    box = UpdateResultDialog(
                        self.window(), "此安装需要完整更新包",
                        ("增量包无法用于当前安装。", f"完整更新包　需下载 {format_file_size(full.size)}"),
                        QStyle.SP_MessageBoxInformation,
                    )
                    box.add_action("下载完整包", lambda: self._download(full))
                    box.open()
                    return
            box = UpdateResultDialog(self.window(), "更新没有准备好",
                                     (str(error) or "请重新检查更新。", "当前版本可继续使用。"),
                                     QStyle.SP_MessageBoxWarning)
            box.add_action("重新检查", self.start_check)
            box.open()
            return
        if self._cancelled.is_set() or not self.window().isVisible():
            staged.discard()
            return
        self._staged = staged
        self.setText("重启并更新")
        self._show_ready()

    def _show_ready(self):
        box = UpdateResultDialog(
            self.window(), "更新已准备好",
            (f"最新版本　{self._staged.asset.target.label()}", "稍后可从侧栏继续，直接退出会清除下载。"),
            QStyle.SP_MessageBoxInformation, close_text="稍后",
        )
        box.add_action("重启并更新", self.window().restart_for_update)
        box.open()

    def needs_windows_handoff(self):
        return self._staged is not None and self._staged.asset.platform == "windows-x64"

    def start_windows_handoff(self, callback):
        self._handoff_callback = callback
        self._future = _background_future(self._staged.launch)
        self._timer.start()

    def launch_prepared(self):
        if not self._staged:
            raise UpdateCheckError("请重新检查并下载更新。")
        self._staged.launch()
        self._staged = None

    def discard_prepared(self):
        if self._staged:
            self._staged.discard()
            self._staged = None

    def _open_download(self, page):
        if not QDesktopServices.openUrl(QUrl(page)):
            QMessageBox.information(self, "未能打开浏览器", f"请在浏览器中打开官方下载页：\n{page}")
