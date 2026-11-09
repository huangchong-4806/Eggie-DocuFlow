"""Document processing page.

Functions are bound onto ExcelMergerWindow and use app.py globals,
so tests can keep patching Qt and tool names on the app module.
"""

def create_document_page(self):
    page = QWidget()
    page.setObjectName("documentPage")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(22, 18, 22, 18)
    layout.setSpacing(14)

    title = QLabel("文档处理")
    title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    title.setFont(QFont("PingFang SC", 24, QFont.Bold))
    title.setProperty("role", "title")
    layout.addWidget(title)

    subtitle = QLabel("自动识别发票、合同和表格类 PDF，并生成对应结果")
    subtitle.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    subtitle.setProperty("role", "subtitle")
    layout.addWidget(subtitle)

    source_group = QGroupBox("待处理 PDF")
    source_layout = QHBoxLayout(source_group)
    self.document_source_path_edit = QLineEdit()
    self.document_source_path_edit.setReadOnly(True)
    self.document_source_path_edit.setPlaceholderText("请选择一个 PDF 文件")
    self.document_source_path_edit.setMinimumHeight(34)
    self.choose_document_source_button = QPushButton("选择 PDF")
    self.choose_document_source_button.setMinimumHeight(34)
    self.choose_document_source_button.setProperty("variant", "accent")
    source_layout.addWidget(self.document_source_path_edit, 1)
    source_layout.addWidget(self.choose_document_source_button)
    layout.addWidget(source_group)

    output_group = QGroupBox("结果保存文件夹")
    output_layout = QHBoxLayout(output_group)
    self.document_output_path_edit = QLineEdit()
    self.document_output_path_edit.setReadOnly(True)
    self.document_output_path_edit.setPlaceholderText("选择 PDF 后将自动设为同目录的 output 文件夹")
    self.document_output_path_edit.setMinimumHeight(34)
    self.choose_document_output_button = QPushButton("更改文件夹")
    self.choose_document_output_button.setMinimumHeight(34)
    output_layout.addWidget(self.document_output_path_edit, 1)
    output_layout.addWidget(self.choose_document_output_button)
    layout.addWidget(output_group)

    self.document_enhanced_layout_checkbox = QCheckBox("增强排版转换（适合合同和表格）")
    self.document_enhanced_layout_checkbox.setToolTip(
        "仍由系统自动识别 PDF 类型；合同会套正式样式，表格会尽量保留边框和版式。"
    )
    layout.addWidget(self.document_enhanced_layout_checkbox)

    ocr_group = QGroupBox("扫描件文字识别（在当前文档处理中使用）")
    ocr_layout = QVBoxLayout(ocr_group)
    ocr_top_row = QHBoxLayout()
    self.document_ocr_checkbox = QCheckBox("扫描页使用云端文字识别")
    self.document_ocr_provider_combo = SelectionComboBox()
    for provider_key, provider_label in PROVIDER_LABELS.items():
        self.document_ocr_provider_combo.addItem(provider_label, provider_key)
    configured_provider = selected_provider()
    provider_index = self.document_ocr_provider_combo.findData(configured_provider)
    self.document_ocr_provider_combo.setCurrentIndex(max(0, provider_index))
    self.document_ocr_settings_button = QPushButton("前往设置")
    self.document_ocr_manual_button = QPushButton("使用说明")
    ocr_top_row.addWidget(self.document_ocr_checkbox)
    ocr_top_row.addWidget(self.document_ocr_provider_combo, 1)
    ocr_top_row.addWidget(self.document_ocr_settings_button)
    ocr_top_row.addWidget(self.document_ocr_manual_button)
    ocr_layout.addLayout(ocr_top_row)

    self.document_ocr_privacy_label = QLabel(
        "有文字的页面只在本机读取；仅扫描图片页会在您确认后发送给所选平台。"
    )
    self.document_ocr_privacy_label.setWordWrap(True)
    self.document_ocr_privacy_label.setProperty("role", "hint")
    ocr_layout.addWidget(self.document_ocr_privacy_label)

    ocr_result_row = QHBoxLayout()
    self.document_ocr_status_label = QLabel("")
    self.document_ocr_status_label.setProperty("role", "status")
    self.document_ocr_result_path_edit = QLineEdit()
    self.document_ocr_result_path_edit.setReadOnly(True)
    self.document_ocr_result_path_edit.setPlaceholderText("可选：仅提取文字后在这里显示结果")
    self.document_ocr_extract_button = QPushButton("仅提取文字")
    self.document_ocr_open_button = QPushButton("打开文字结果")
    ocr_result_row.addWidget(self.document_ocr_status_label)
    ocr_result_row.addWidget(self.document_ocr_result_path_edit, 1)
    ocr_result_row.addWidget(self.document_ocr_extract_button)
    ocr_result_row.addWidget(self.document_ocr_open_button)
    ocr_layout.addLayout(ocr_result_row)
    self.document_ocr_disclosure = Disclosure("扫描件文字识别与仅提取文字", ocr_group)
    layout.addWidget(self.document_ocr_disclosure)

    result_group = QGroupBox("处理结果")
    self.document_result_group = result_group
    result_layout = QVBoxLayout(result_group)
    self.document_status_label = QLabel("等待选择 PDF 文件")
    self.document_status_label.setProperty("role", "status")
    self.document_result_path_edit = QLineEdit()
    self.document_result_path_edit.setReadOnly(True)
    self.document_result_path_edit.setPlaceholderText("处理完成后在这里显示结果路径")
    self.document_result_path_edit.setMinimumHeight(34)
    layout.addWidget(self.document_status_label)
    result_layout.addWidget(self.document_result_path_edit)
    layout.addWidget(result_group)
    result_group.hide()
    self.document_result_path_edit.textChanged.connect(lambda text: result_group.setVisible(bool(text)))

    hint = QLabel("默认在本机处理；云端文字识别需要另行确认。扫描页识别暂不与增强排版同时使用。")
    hint.setAlignment(Qt.AlignLeft)
    hint.setProperty("role", "hint")
    hint.setWordWrap(True)
    layout.addWidget(hint)
    layout.addStretch(1)

    button_layout = QHBoxLayout()
    self.document_process_button = QPushButton("开始处理")
    self.document_process_button.setMinimumHeight(38)
    self.document_process_button.setMinimumWidth(140)
    self.document_process_button.setFont(QFont("PingFang SC", 14, QFont.Bold))
    self.document_process_button.setProperty("variant", "primary")
    self.open_document_result_button = QPushButton("打开结果")
    self.open_document_result_button.setMinimumHeight(38)
    self.open_document_result_button.setMinimumWidth(140)
    button_layout.addStretch()
    button_layout.addWidget(self.document_process_button)
    button_layout.addWidget(self.open_document_result_button)
    layout.addLayout(button_layout)

    self.choose_document_source_button.clicked.connect(
        self.choose_document_source_file
    )
    self.choose_document_output_button.clicked.connect(
        self.choose_document_output_folder
    )
    self.document_process_button.clicked.connect(self.process_smart_document)
    self.open_document_result_button.clicked.connect(
        lambda: self.open_output_file(self.document_result_file)
    )
    self.document_ocr_provider_combo.currentIndexChanged.connect(
        self.document_ocr_provider_changed
    )
    self.document_ocr_checkbox.toggled.connect(
        self.document_ocr_mode_changed
    )
    self.document_ocr_settings_button.clicked.connect(
        self.show_ocr_settings
    )
    self.document_ocr_manual_button.clicked.connect(
        self.open_ocr_manual
    )
    self.document_ocr_extract_button.clicked.connect(
        self.extract_document_text_only
    )
    self.document_ocr_open_button.clicked.connect(
        lambda: self.open_output_file(self.document_ocr_result_file)
    )
    self.refresh_document_ocr_status()
    self.update_document_button_states()
    contain_page_form(page)
    return page


def current_document_ocr_provider(self):
    return self.document_ocr_provider_combo.currentData()


def refresh_document_ocr_status(self):
    provider = self.current_document_ocr_provider()
    if is_provider_configured(provider):
        self.document_ocr_status_label.setText("密钥已配置")
    else:
        self.document_ocr_status_label.setText("未配置（文本页仍可本机提取）")


def document_ocr_provider_changed(self):
    provider = self.current_document_ocr_provider()
    try:
        select_provider(provider)
    except OSError as error:
        QMessageBox.warning(self, "无法保存选择", str(error))
    self.refresh_document_ocr_status()


def document_ocr_mode_changed(self, _enabled):
    self.document_enhanced_layout_checkbox.setChecked(False)
    self.document_enhanced_layout_checkbox.setEnabled(not _enabled)
    self.refresh_document_ocr_status()


def show_ocr_settings(self):
    self.show_settings(self.current_document_ocr_provider())


def open_ocr_manual(self):
    manual_file = resource_path("docs/OCR使用说明.pdf")
    if not manual_file.is_file():
        QMessageBox.warning(self, "说明书缺失", "未找到 OCR 使用说明。")
        return
    self.open_output_file(str(manual_file))


def start_document_inspection(self, action):
    if not self.document_source_file or not self.document_output_folder:
        QMessageBox.warning(self, "尚未完成设置", "请先选择 PDF 文件。")
        return
    source_file = self.document_source_file
    self.start_background_task(
        "正在检查 PDF",
        f"正在检查页面内容：{Path(source_file).name}",
        lambda _progress: inspect_pdf(source_file),
        lambda inspection: self.document_inspection_completed(
            action, inspection
        ),
        lambda error: QMessageBox.critical(self, "无法读取 PDF", error),
        status_label=self.document_ocr_status_label,
    )


def document_inspection_completed(self, action, inspection):
    if not inspection.scanned_pages:
        if action == "extract":
            self.start_document_ocr_task("extract", inspection)
        else:
            self.start_document_local_processing()
        return

    provider = self.current_document_ocr_provider()
    if not is_provider_configured(provider):
        answer = QMessageBox.question(
            self,
            "需要先配置密钥",
            f"检测到 {len(inspection.scanned_pages)} 个扫描页，但 {PROVIDER_LABELS[provider]} "
            "尚未配置密钥。\n\n是否现在打开软件设置？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            self.show_ocr_settings()
        return

    pages = "、".join(str(page) for page in inspection.scanned_pages[:20])
    if len(inspection.scanned_pages) > 20:
        pages += "等"
    answer = QMessageBox.question(
        self,
        "发送扫描页前确认",
        f"文件共 {inspection.page_count} 页，检测到 {len(inspection.scanned_pages)} 个扫描页"
        f"（第 {pages} 页）。\n\n"
        f"继续后，软件会将这些页面的图片发送给 {PROVIDER_LABELS[provider]} "
        "识别文字；有文字的页面不会发送。请确认您有权处理文档内容，"
        "并已了解该平台的服务条款、隐私规则、额度和费用。\n\n"
        "Eggie DocuFlow 不代理或转售 OCR 服务，也不接收您的密钥或文档。\n\n"
        "是否继续并发送这些扫描页？",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if answer != QMessageBox.Yes:
        self.document_ocr_status_label.setText("已取消发送扫描页")
        return
    if action == "process":
        self.document_result_file = ""
        self.document_result_path_edit.clear()
        self.document_status_label.setText("正在识别扫描页并处理文档…")
    self.start_document_ocr_task(action, inspection)


def start_document_ocr_task(self, task_kind, inspection):
    if self.document_ocr_thread is not None or self.task_is_running():
        return
    self.document_ocr_task_kind = task_kind
    if task_kind == "extract":
        self.document_ocr_result_file = ""
        self.document_ocr_result_path_edit.clear()
    title = "文档处理中" if task_kind == "process" else "正在提取 PDF 文字"
    progress = QProgressDialog(title + "…", "", 0, inspection.page_count, self)
    progress.setWindowTitle(title)
    progress.setCancelButton(None)
    progress.setMinimumDuration(0)
    progress.setWindowModality(Qt.WindowModal)
    progress.setLabelText(
        f"任务正在执行，请勿关闭软件。\n\n{title}…"
    )
    progress.show()
    self.document_ocr_progress = progress
    self.document_ocr_thread = DocumentOCRThread(
        task_kind,
        self.document_source_file,
        self.document_output_folder,
        self.current_document_ocr_provider(),
        self,
    )
    self.document_ocr_thread.progress.connect(self.document_ocr_progress_changed)
    self.document_ocr_thread.completed.connect(self.document_ocr_completed)
    self.document_ocr_thread.failed.connect(self.document_ocr_failed)
    self.document_ocr_thread.finished.connect(self.document_ocr_thread_finished)
    self.update_document_button_states()
    self.set_global_task_active(True)
    self.document_ocr_thread.start()


def document_ocr_progress_changed(self, value, total, text):
    if self.document_ocr_progress is not None:
        self.document_ocr_progress.setMaximum(max(total, 1))
        self.document_ocr_progress.setValue(value)
        self.document_ocr_progress.setLabelText(
            "任务正在执行，请勿关闭软件。\n\n" + text
        )
    self.document_ocr_status_label.setText(text)


def document_ocr_completed(self, result):
    if self.document_ocr_progress is not None:
        self.document_ocr_progress.close()
    if self.document_ocr_task_kind == "process":
        self.finish_document_processing(result)
        return
    self.document_ocr_result_file = result.text_file
    self.document_ocr_result_path_edit.setText(result.text_file)
    self.document_ocr_result_path_edit.setToolTip(result.text_file)
    self.document_ocr_status_label.setText(
        f"文字提取完成：本机 {result.local_page_count} 页，云 OCR {result.cloud_page_count} 页"
    )
    message = QMessageBox(self)
    message.setWindowTitle("文字提取完成")
    message.setIcon(QMessageBox.Information)
    message.setText(
        f"已处理 {result.page_count} 页，其中云 OCR {result.cloud_page_count} 页"
    )
    message.setInformativeText(
        f"文字结果：\n{result.text_file}\n\n"
        f"保留位置的结果：\n{result.json_file}\n\n"
        f"处理日志：\n{result.log_file}"
    )
    open_button = message.addButton("打开文字结果", QMessageBox.ActionRole)
    ok_button = message.addButton("确定", QMessageBox.AcceptRole)
    message.setDefaultButton(ok_button)
    message.exec()
    if message.clickedButton() == open_button:
        self.open_output_file(result.text_file)


def document_ocr_failed(self, error_message):
    if self.document_ocr_progress is not None:
        self.document_ocr_progress.close()
    self.document_ocr_status_label.setText("处理失败，未修改原 PDF")
    QMessageBox.critical(
        self,
        "OCR 处理失败",
        "未生成结果，原 PDF 不会被修改。\n"
        f"本次未保留不完整结果。\n\n{error_message}",
    )


def document_ocr_thread_finished(self):
    if self.document_ocr_thread is not None:
        self.document_ocr_thread.deleteLater()
    self.document_ocr_thread = None
    self.document_ocr_progress = None
    self.document_ocr_task_kind = ""
    self.set_global_task_active(False)
    self.update_document_button_states()


def extract_document_text_only(self):
    self.start_document_inspection("extract")


def update_document_button_states(self):
    idle = self.document_ocr_thread is None
    self.document_process_button.setEnabled(
        bool(idle and self.document_source_file and self.document_output_folder)
    )
    self.open_document_result_button.setEnabled(
        bool(self.document_result_file and Path(self.document_result_file).exists())
    )
    self.document_ocr_extract_button.setEnabled(
        bool(idle and self.document_source_file and self.document_output_folder)
    )
    self.document_ocr_open_button.setEnabled(
        bool(
            self.document_ocr_result_file
            and Path(self.document_ocr_result_file).exists()
        )
    )


def dropped_pdf_path(self, event):
    for url in event.mimeData().urls():
        if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() == ".pdf":
            return url.toLocalFile()
    return ""


def dragEnterEvent(self, event):
    if self.dropped_pdf_path(event):
        event.acceptProposedAction()
        return
    super().dragEnterEvent(event)


def dropEvent(self, event):
    pdf_file = self.dropped_pdf_path(event)
    if not pdf_file:
        super().dropEvent(event)
        return
    self.set_document_source_file(pdf_file)
    self.show_document_tool()
    event.acceptProposedAction()


def set_document_source_file(self, filename):
    if not filename or Path(filename).suffix.lower() != ".pdf":
        return False
    self.document_source_file = os.path.abspath(filename)
    self.document_output_folder = str(Path(self.document_source_file).parent / "output")
    self.document_result_file = ""
    self.document_ocr_result_file = ""
    self.document_source_path_edit.setText(self.document_source_file)
    self.document_source_path_edit.setToolTip(self.document_source_file)
    self.document_output_path_edit.setText(self.document_output_folder)
    self.document_output_path_edit.setToolTip(self.document_output_folder)
    self.document_result_path_edit.clear()
    self.document_ocr_result_path_edit.clear()
    self.document_status_label.setText("已选择 PDF，可开始一键处理")
    self.update_document_button_states()
    return True


def choose_document_source_file(self):
    filename, _ = QFileDialog.getOpenFileName(
        self,
        "选择要智能处理的 PDF",
        self.dialog_folder("open"),
        "PDF 文件 (*.pdf)",
    )
    if not filename:
        return

    self.remember_dialog_folder("open", filename)
    self.set_document_source_file(filename)


def choose_document_output_folder(self):
    folder = QFileDialog.getExistingDirectory(
        self,
        "选择结果保存文件夹",
        self.dialog_folder("save", self.document_output_folder),
        QFileDialog.ShowDirsOnly,
    )
    if not folder:
        return

    self.document_output_folder = os.path.abspath(folder)
    self.remember_dialog_folder("save", self.document_output_folder)
    self.document_result_file = ""
    self.document_ocr_result_file = ""
    self.document_output_path_edit.setText(self.document_output_folder)
    self.document_output_path_edit.setToolTip(self.document_output_folder)
    self.document_result_path_edit.clear()
    self.document_ocr_result_path_edit.clear()
    self.document_status_label.setText("保存位置已更新，可开始处理")
    self.update_document_button_states()


def process_smart_document(self):
    if not self.document_source_file or not self.document_output_folder:
        QMessageBox.warning(self, "尚未完成设置", "请先选择 PDF 文件。")
        return

    if self.document_ocr_checkbox.isChecked():
        self.start_document_inspection("process")
        return
    self.start_document_local_processing()


def start_document_local_processing(self):
    source_file = self.document_source_file
    output_folder = self.document_output_folder
    enhanced_layout = self.document_enhanced_layout_checkbox.isChecked()
    self.document_result_file = ""
    self.document_result_path_edit.clear()
    self.document_status_label.setText("正在识别文档类型…")
    self.update_document_button_states()

    def process_local(progress_callback):
        if enhanced_layout:
            return process_layout_document(
                source_file,
                output_folder,
                progress_callback=progress_callback,
                style_template="formal_contract",
            )
        return process_document(
            source_file,
            output_folder,
            progress_callback=progress_callback,
        )

    def process_failed(error):
        self.finish_document_processing(
            {
                "doc_type": "UNKNOWN",
                "confidence": 0.0,
                "output_file": "",
                "status": "failed",
            },
            f"\n\n错误信息：{error}",
        )

    self.start_background_task(
        "文档智能处理",
        f"正在读取并识别：{Path(source_file).name}",
        process_local,
        self.finish_document_processing,
        process_failed,
        status_label=self.document_status_label,
    )


def finish_document_processing(self, result, error_detail=""):

    if result["status"] != "success" or not result["output_file"]:
        if not error_detail and result.get("error_message"):
            error_detail = f"\n\n错误信息：{result['error_message']}"
        self.document_status_label.setText(
            "处理失败，请检查 PDF 文件和日志记录"
        )
        QMessageBox.critical(
            self,
            "处理失败",
            "未生成结果文件。"
            f"{error_detail}\n\n日志位置：~/.eggie_excel_tool/logs",
        )
        self.update_document_button_states()
        return

    self.document_result_file = result["output_file"]
    self.document_result_path_edit.setText(self.document_result_file)
    self.document_result_path_edit.setToolTip(self.document_result_file)
    doc_type_label = DOCUMENT_TYPE_LABELS.get(
        result["doc_type"], result["doc_type"]
    )
    confidence = result.get("confidence")
    if confidence is None:
        confidence = result.get("data", {}).get("confidence")
    if confidence is None:
        self.document_status_label.setText(f"处理完成：{doc_type_label}")
    else:
        confidence_percent = round(confidence * 100)
        self.document_status_label.setText(
            f"处理完成：{doc_type_label}（置信度 {confidence_percent}%）"
        )
    self.update_document_button_states()

    message = QMessageBox(self)
    message.setWindowTitle("处理完成")
    message.setIcon(QMessageBox.Information)
    message.setText(f"已识别为：{doc_type_label}")
    message.setInformativeText(f"结果保存位置：\n{self.document_result_file}")
    open_button = message.addButton("打开结果", QMessageBox.ActionRole)
    ok_button = message.addButton("确定", QMessageBox.AcceptRole)
    for button in (ok_button, open_button):
        button.setFixedSize(112, 36)
    message.setDefaultButton(ok_button)
    message.exec()
    if message.clickedButton() == open_button:
        self.open_output_file(self.document_result_file)

