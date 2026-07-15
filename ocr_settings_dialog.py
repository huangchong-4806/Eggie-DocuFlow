from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from api_layer.config import (
    PROVIDER_ENV_KEYS,
    PROVIDER_LABELS,
    delete_credentials,
    is_provider_configured,
    load_credentials,
    save_credentials,
)
from api_layer.providers import create_provider


class ConnectionTestThread(QThread):
    completed = Signal(bool, str)

    def __init__(self, provider, parent=None):
        super().__init__(parent)
        self.provider = provider

    def run(self):
        try:
            _, message = create_provider(self.provider).test_connection()
        except Exception as error:
            self.completed.emit(False, str(error))
            return
        self.completed.emit(True, message)


class SoftwareSettingsDialog(QDialog):
    accent_changed = Signal(str)

    def __init__(
        self,
        selected_provider="baidu",
        accent_options=(),
        selected_accent="",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("软件设置")
        self.setMinimumWidth(680)
        self._test_thread = None
        self._fields = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        theme_group = QGroupBox("外观")
        theme_form = QFormLayout(theme_group)
        self.theme_combo = QComboBox()
        for key, label in accent_options:
            self.theme_combo.addItem(label, key)
        theme_index = self.theme_combo.findData(selected_accent)
        self.theme_combo.setCurrentIndex(max(0, theme_index))
        theme_form.addRow("主题色调：", self.theme_combo)
        layout.addWidget(theme_group)

        service_group = QGroupBox("第三方服务")
        service_layout = QVBoxLayout(service_group)
        service_layout.setSpacing(12)

        introduction = QLabel(
            "在这里统一管理您自己申请的 OCR 密钥。密钥保存在当前 Mac 用户的"
            "个人配置区，不写入项目、日志或处理结果。仅在您确认后，扫描页"
            "才会发送给所选平台。文档处理和未来的 PDF 比对共用这套设置。"
        )
        introduction.setWordWrap(True)
        introduction.setProperty("role", "hint")
        service_layout.addWidget(introduction)

        provider_row = QHBoxLayout()
        provider_row.addWidget(QLabel("默认 OCR 平台："))
        self.provider_combo = QComboBox()
        for key, label in PROVIDER_LABELS.items():
            self.provider_combo.addItem(label, key)
        provider_row.addWidget(self.provider_combo, 1)
        service_layout.addLayout(provider_row)

        credential_group = QGroupBox("密钥信息")
        credential_layout = QVBoxLayout(credential_group)
        self.credential_stack = QStackedWidget()
        for provider in PROVIDER_LABELS:
            page = QWidget()
            form = QFormLayout(page)
            keys = PROVIDER_ENV_KEYS[provider]
            labels = (
                ("API Key", "Secret Key")
                if provider == "baidu"
                else ("AccessKey ID", "AccessKey Secret")
            )
            provider_fields = []
            for label, key in zip(labels, keys):
                field = QLineEdit()
                field.setEchoMode(QLineEdit.Password)
                field.setPlaceholderText(f"请填写 {label}")
                form.addRow(f"{label}：", field)
                provider_fields.append(field)
            self._fields[provider] = tuple(provider_fields)
            self.credential_stack.addWidget(page)
        credential_layout.addWidget(self.credential_stack)
        self.show_secret_checkbox = QCheckBox("显示密钥")
        credential_layout.addWidget(self.show_secret_checkbox)
        service_layout.addWidget(credential_group)

        note = QLabel(
            "建议使用专门用于本软件的子账号或独立密钥，只授予 OCR 所需权限。"
            "如怀疑泄露，请立即到对应平台停用并更换密钥。"
        )
        note.setWordWrap(True)
        note.setProperty("role", "hint")
        service_layout.addWidget(note)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setProperty("role", "status")
        service_layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.delete_button = QPushButton("删除本机密钥")
        self.test_button = QPushButton("保存并测试连接")
        self.save_button = QPushButton("保存当前平台密钥")
        self.save_button.setProperty("variant", "primary")
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)
        buttons.addWidget(self.test_button)
        buttons.addWidget(self.save_button)
        service_layout.addLayout(buttons)
        layout.addWidget(service_group)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        self.close_button = QPushButton("完成")
        self.close_button.setMinimumWidth(110)
        close_row.addWidget(self.close_button)
        layout.addLayout(close_row)

        index = max(0, self.provider_combo.findData(selected_provider))
        self.provider_combo.setCurrentIndex(index)
        self.provider_combo.currentIndexChanged.connect(self._provider_changed)
        self.theme_combo.currentIndexChanged.connect(self._theme_changed)
        self.show_secret_checkbox.toggled.connect(self._toggle_secret_visibility)
        self.delete_button.clicked.connect(self._delete_current_credentials)
        self.test_button.clicked.connect(self._test_connection)
        self.save_button.clicked.connect(self._save_current_credentials)
        self.close_button.clicked.connect(self.accept)
        self._load_fields()
        self._provider_changed()

    @property
    def selected_provider(self):
        return self.provider_combo.currentData()

    @property
    def selected_accent(self):
        return self.theme_combo.currentData()

    def _theme_changed(self):
        accent = self.selected_accent
        if accent:
            self.accent_changed.emit(accent)

    def _load_fields(self):
        for provider, fields in self._fields.items():
            values = load_credentials(provider)
            for field, key in zip(fields, PROVIDER_ENV_KEYS[provider]):
                field.setText(values.get(key, ""))

    def _provider_changed(self):
        provider = self.selected_provider
        self.credential_stack.setCurrentIndex(
            list(PROVIDER_LABELS).index(provider)
        )
        configured = is_provider_configured(provider)
        self.status_label.setText(
            "当前平台密钥已保存在本机。"
            if configured
            else "当前平台尚未配置密钥。"
        )

    def _toggle_secret_visibility(self, visible):
        mode = QLineEdit.Normal if visible else QLineEdit.Password
        for fields in self._fields.values():
            for field in fields:
                field.setEchoMode(mode)

    def _credential_values(self):
        provider = self.selected_provider
        return {
            key: field.text()
            for key, field in zip(
                PROVIDER_ENV_KEYS[provider],
                self._fields[provider],
            )
        }

    def _save(self):
        return save_credentials(self.selected_provider, self._credential_values())

    def _save_current_credentials(self):
        try:
            self._save()
        except Exception as error:
            QMessageBox.warning(self, "无法保存", str(error))
            return
        self.status_label.setText("密钥已安全保存在本机个人配置区。")

    def _delete_current_credentials(self):
        provider = self.selected_provider
        answer = QMessageBox.question(
            self,
            "删除本机密钥",
            f"确定删除 {PROVIDER_LABELS[provider]} 在这台 Mac 上保存的密钥吗？\n"
            "这不会删除您在云平台上的账号或密钥。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        delete_credentials(provider)
        for field in self._fields[provider]:
            field.clear()
        self.status_label.setText("这台 Mac 上保存的密钥已删除。")

    def _test_connection(self):
        provider = self.selected_provider
        if provider == "alibaba":
            answer = QMessageBox.question(
                self,
                "连接测试提醒",
                "阿里云连接测试会发送一张由软件生成的 TEST 测试图，"
                "不包含您的文档，但可能占用 1 次 OCR 调用额度。\n\n"
                "是否继续？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        try:
            config_file = self._save()
        except Exception as error:
            QMessageBox.warning(self, "无法测试", str(error))
            return
        self.status_label.setText("正在测试连接，请稍候…")
        for button in (self.test_button, self.save_button, self.delete_button):
            button.setEnabled(False)
        self._test_thread = ConnectionTestThread(provider, self)
        self._test_thread.completed.connect(self._connection_test_finished)
        self._test_thread.start()

    def _connection_test_finished(self, success, message):
        for button in (self.test_button, self.save_button, self.delete_button):
            button.setEnabled(True)
        prefix = "连接测试通过：" if success else "连接测试失败："
        self.status_label.setText(prefix + message)
        if not success:
            QMessageBox.warning(self, "连接测试失败", message)
        self._test_thread.deleteLater()
        self._test_thread = None

    def closeEvent(self, event):
        if self._test_thread is not None and self._test_thread.isRunning():
            self.status_label.setText("连接测试还在进行，请稍候。")
            event.ignore()
            return
        super().closeEvent(event)
