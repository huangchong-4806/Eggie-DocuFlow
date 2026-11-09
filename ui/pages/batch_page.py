"""PDF batch page.

Functions are bound onto ExcelMergerWindow and use app.py globals,
so tests can keep patching Qt and tool names on the app module.
"""

def create_batch_page(self):
    page = QWidget()
    page.setObjectName("batchPage")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(22, 18, 22, 18)
    layout.setSpacing(14)

    title = QLabel("批量处理")
    title.setFont(QFont("PingFang SC", 24, QFont.Bold))
    title.setProperty("role", "title")
    layout.addWidget(title)
    subtitle = QLabel("选择一个文件夹，逐个识别其中的 PDF 并生成对应结果")
    subtitle.setProperty("role", "subtitle")
    layout.addWidget(subtitle)

    source_group = QGroupBox("来源文件夹")
    source_layout = QVBoxLayout(source_group)
    source_row = QHBoxLayout()
    self.batch_source_path_edit = QLineEdit()
    self.batch_source_path_edit.setReadOnly(True)
    self.batch_source_path_edit.setPlaceholderText("请选择包含 PDF 的文件夹")
    self.choose_batch_source_button = QPushButton("选择文件夹")
    self.choose_batch_source_button.setProperty("variant", "accent")
    self.batch_recursive_checkbox = QCheckBox("包含子文件夹")
    self.batch_preview_button = QPushButton("重新检查")
    source_row.addWidget(self.batch_source_path_edit, 1)
    source_row.addWidget(self.choose_batch_source_button)
    source_row.addWidget(self.batch_recursive_checkbox)
    source_row.addWidget(self.batch_preview_button)
    source_layout.addLayout(source_row)
    self.batch_source_status_label = QLabel("尚未选择文件夹")
    self.batch_source_status_label.setProperty("role", "status")
    source_layout.addWidget(self.batch_source_status_label)
    layout.addWidget(source_group)

    preview_group = QGroupBox("处理预览")
    preview_layout = QVBoxLayout(preview_group)
    self.batch_file_table = QTreeWidget()
    self.batch_file_table.setColumnCount(6)
    self.batch_file_table.setHeaderLabels(
        ["序号", "PDF 文件", "页数", "扫描页", "预计处理方式", "状态"]
    )
    self.batch_file_table.setRootIsDecorated(False)
    self.batch_file_table.setAlternatingRowColors(True)
    self.batch_file_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
    batch_header = self.batch_file_table.header()
    batch_header.setSectionResizeMode(0, QHeaderView.Fixed)
    batch_header.setSectionResizeMode(1, QHeaderView.Stretch)
    batch_header.setSectionResizeMode(2, QHeaderView.Fixed)
    batch_header.setSectionResizeMode(3, QHeaderView.Fixed)
    batch_header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
    batch_header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
    self.batch_file_table.setColumnWidth(0, 65)
    self.batch_file_table.setColumnWidth(2, 70)
    self.batch_file_table.setColumnWidth(3, 80)
    preview_layout.addWidget(self.batch_file_table)
    layout.addWidget(preview_group, 1)

    output_group = QGroupBox("结果保存文件夹")
    output_layout = QHBoxLayout(output_group)
    self.batch_output_path_edit = QLineEdit()
    self.batch_output_path_edit.setReadOnly(True)
    self.batch_output_path_edit.setPlaceholderText("默认保存在来源文件夹的 Eggie批量处理结果 中")
    self.choose_batch_output_button = QPushButton("更改文件夹")
    output_layout.addWidget(self.batch_output_path_edit, 1)
    output_layout.addWidget(self.choose_batch_output_button)
    layout.addWidget(output_group)

    options_group = QGroupBox("扫描页识别")
    options_layout = QHBoxLayout(options_group)
    self.batch_ocr_checkbox = QCheckBox("扫描页使用云端文字识别")
    self.batch_ocr_provider_combo = SelectionComboBox()
    for provider_key, provider_label in PROVIDER_LABELS.items():
        self.batch_ocr_provider_combo.addItem(provider_label, provider_key)
    provider_index = self.batch_ocr_provider_combo.findData(selected_provider())
    self.batch_ocr_provider_combo.setCurrentIndex(max(0, provider_index))
    self.batch_ocr_status_label = QLabel("默认只在本机处理；勾选后仅上传扫描页")
    self.batch_ocr_status_label.setProperty("role", "hint")
    options_layout.addWidget(self.batch_ocr_checkbox)
    options_layout.addWidget(self.batch_ocr_provider_combo)
    options_layout.addWidget(self.batch_ocr_status_label, 1)
    layout.addWidget(options_group)

    action_layout = QHBoxLayout()
    self.batch_start_button = QPushButton("开始批量处理")
    self.batch_start_button.setProperty("variant", "primary")
    self.batch_start_button.setMinimumHeight(38)
    self.batch_retry_button = QPushButton("重试失败文件")
    self.batch_retry_button.setMinimumHeight(38)
    self.batch_open_folder_button = QPushButton("打开结果文件夹")
    self.batch_open_folder_button.setMinimumHeight(38)
    action_layout.addStretch()
    action_layout.addWidget(self.batch_start_button)
    action_layout.addWidget(self.batch_retry_button)
    action_layout.addWidget(self.batch_open_folder_button)
    layout.addLayout(action_layout)
    self.batch_status_label = QLabel("等待选择文件夹")
    self.batch_status_label.setProperty("role", "status")
    layout.addWidget(self.batch_status_label)

    self.choose_batch_source_button.clicked.connect(self.choose_batch_source_folder)
    self.choose_batch_output_button.clicked.connect(self.choose_batch_output_folder)
    self.batch_preview_button.clicked.connect(self.refresh_batch_preview)
    self.batch_recursive_checkbox.toggled.connect(self.refresh_batch_preview)
    self.batch_ocr_provider_combo.currentIndexChanged.connect(
        self.batch_ocr_provider_changed
    )
    self.batch_start_button.clicked.connect(self.start_batch_processing)
    self.batch_retry_button.clicked.connect(self.retry_failed_batch_files)
    self.batch_open_folder_button.clicked.connect(self.open_batch_output_folder)
    self.batch_ocr_status_label.setText(
        "密钥已配置；仅扫描页会上传"
        if is_provider_configured(self.batch_ocr_provider_combo.currentData())
        else "密钥未配置；默认仍可本机处理文字 PDF"
    )
    self.update_batch_button_states()
    return page


def choose_batch_source_folder(self):
    folder = QFileDialog.getExistingDirectory(
        self,
        "选择包含 PDF 的文件夹",
        self.dialog_folder("batch_source", self.batch_source_folder),
    )
    if not folder:
        return
    self.batch_source_folder = os.path.abspath(folder)
    self.remember_dialog_folder("batch_source", self.batch_source_folder)
    self.batch_source_path_edit.setText(self.batch_source_folder)
    self.batch_output_folder = str(
        Path(self.batch_source_folder) / "Eggie批量处理结果"
    )
    self.batch_output_path_edit.setText(self.batch_output_folder)
    self.refresh_batch_preview()


def choose_batch_output_folder(self):
    folder = QFileDialog.getExistingDirectory(
        self,
        "选择批量结果保存文件夹",
        self.dialog_folder("batch_output", self.batch_output_folder),
    )
    if not folder:
        return
    self.batch_output_folder = os.path.abspath(folder)
    self.remember_dialog_folder("batch_output", self.batch_output_folder)
    self.batch_output_path_edit.setText(self.batch_output_folder)
    self.update_batch_button_states()


def refresh_batch_preview(self, *_args):
    if not self.batch_source_folder:
        return
    try:
        files = discover_pdf_files(
            self.batch_source_folder,
            recursive=self.batch_recursive_checkbox.isChecked(),
        )
    except Exception as error:
        QMessageBox.warning(self, "无法读取文件夹", str(error))
        return
    self.batch_file_table.clear()
    self.batch_previews = []
    self.batch_failed_files = []
    if not files:
        self.batch_source_status_label.setText("没有发现 PDF 文件")
        self.update_batch_button_states()
        return

    def worker(progress_callback):
        return inspect_pdf_files(files, progress_callback)

    self.batch_source_status_label.setText(f"正在检查 {len(files)} 个 PDF…")
    self.start_background_task(
        "检查批量文件",
        f"正在检查 {len(files)} 个 PDF…",
        worker,
        self.display_batch_previews,
        total=len(files),
        status_label=self.batch_source_status_label,
    )


def display_batch_previews(self, previews):
    self.batch_previews = list(previews)
    self.batch_file_table.clear()
    invalid_count = 0
    scanned_pages = 0
    for index, preview in enumerate(self.batch_previews, 1):
        status = "可处理"
        if preview.error_message:
            status = "检查失败"
            invalid_count += 1
        scanned_pages += preview.scanned_page_count
        item = QTreeWidgetItem(
            [
                str(index),
                Path(preview.source_file).name,
                str(preview.page_count or "-"),
                str(preview.scanned_page_count or 0),
                preview.suggested_action,
                status,
            ]
        )
        item.setData(0, Qt.UserRole, preview.source_file)
        item.setToolTip(1, preview.source_file)
        if preview.error_message:
            item.setToolTip(5, preview.error_message)
        self.batch_file_table.addTopLevelItem(item)
    self.batch_source_status_label.setText(
        f"发现 {len(previews)} 个 PDF，扫描页 {scanned_pages} 个，"
        f"检查失败 {invalid_count} 个"
    )
    self.batch_status_label.setText("预览完成，确认设置后可以开始处理")
    self.update_batch_button_states()


def batch_ocr_provider_changed(self):
    provider = self.batch_ocr_provider_combo.currentData()
    try:
        select_provider(provider)
    except OSError as error:
        QMessageBox.warning(self, "无法保存选择", str(error))
    index = self.document_ocr_provider_combo.findData(provider)
    if index >= 0 and self.document_ocr_provider_combo.currentIndex() != index:
        self.document_ocr_provider_combo.setCurrentIndex(index)
    self.batch_ocr_status_label.setText(
        "密钥已配置；仅扫描页会上传"
        if is_provider_configured(provider)
        else "密钥未配置；请先到设置中填写"
    )


def update_batch_button_states(self):
    has_output = bool(self.batch_output_folder)
    self.batch_preview_button.setEnabled(bool(self.batch_source_folder))
    self.batch_start_button.setEnabled(bool(self.batch_previews) and has_output)
    self.batch_retry_button.setEnabled(bool(self.batch_failed_files) and has_output)
    self.batch_retry_button.setVisible(bool(self.batch_failed_files))
    self.batch_open_folder_button.setEnabled(
        has_output and Path(self.batch_output_folder).is_dir()
    )


def _set_batch_rows_waiting(self, files):
    targets = {str(Path(path).resolve()) for path in files}
    for index in range(self.batch_file_table.topLevelItemCount()):
        item = self.batch_file_table.topLevelItem(index)
        source = str(Path(item.data(0, Qt.UserRole)).resolve())
        if source in targets:
            item.setText(5, "等待处理")
            item.setToolTip(5, "")


def _confirm_batch_ocr(self, files):
    if not self.batch_ocr_checkbox.isChecked():
        return True
    provider = self.batch_ocr_provider_combo.currentData()
    if not is_provider_configured(provider):
        QMessageBox.warning(
            self,
            "OCR 密钥未配置",
            "请先在软件设置中填写所选文字识别平台的密钥。",
        )
        return False
    selected = {str(Path(path).resolve()) for path in files}
    scanned = [
        preview
        for preview in self.batch_previews
        if str(Path(preview.source_file).resolve()) in selected
        and preview.scanned_pages
    ]
    if not scanned:
        return True
    scanned_count = sum(len(preview.scanned_pages) for preview in scanned)
    details = "\n".join(
        f"{Path(preview.source_file).name}：第 "
        f"{'、'.join(map(str, preview.scanned_pages))} 页"
        for preview in scanned[:8]
    )
    if len(scanned) > 8:
        details += f"\n另有 {len(scanned) - 8} 个文件"
    provider_label = PROVIDER_LABELS.get(provider, provider)
    answer = QMessageBox.question(
        self,
        "确认使用云 OCR",
        f"共 {scanned_count} 个扫描页会发送给 {provider_label}：\n\n"
        f"{details}\n\n有文字的页面仍在本机读取。是否继续？",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    return answer == QMessageBox.Yes


def start_batch_processing(self, files=None):
    files = tuple(files or (preview.source_file for preview in self.batch_previews))
    if not files or not self.batch_output_folder:
        QMessageBox.information(self, "信息不完整", "请先选择文件夹并完成预览。")
        return
    if not self._confirm_batch_ocr(files):
        return
    use_ocr = self.batch_ocr_checkbox.isChecked()
    provider = self.batch_ocr_provider_combo.currentData()
    self._set_batch_rows_waiting(files)

    def worker(progress_callback):
        return process_pdf_files(
            files,
            self.batch_output_folder,
            use_ocr=use_ocr,
            provider_name=provider,
            progress_callback=progress_callback,
        )

    self.start_background_task(
        "批量处理 PDF",
        f"准备处理 {len(files)} 个 PDF…",
        worker,
        self.batch_processing_completed,
        total=len(files),
        status_label=self.batch_status_label,
    )


def batch_processing_completed(self, result):
    rows = {}
    for index in range(self.batch_file_table.topLevelItemCount()):
        item = self.batch_file_table.topLevelItem(index)
        rows[str(Path(item.data(0, Qt.UserRole)).resolve())] = item
    self.batch_failed_files = []
    for item_result in result.results:
        data = item_result.get("data") if isinstance(item_result.get("data"), dict) else {}
        source = str(Path(data.get("source_file", "")).resolve())
        row = rows.get(source)
        if item_result.get("status") == "success":
            status = f"成功：{DOCUMENT_TYPE_LABELS.get(item_result.get('doc_type'), '普通文档')}"
            tooltip = item_result.get("output_file", "")
        else:
            status = "失败"
            tooltip = data.get("error_message", "处理失败")
            if source:
                self.batch_failed_files.append(source)
        if row is not None:
            row.setText(5, status)
            row.setToolTip(5, tooltip)
    self.batch_last_log_file = result.log_file
    self.batch_status_label.setText(
        f"处理完成：成功 {len(result.successful)} 个，失败 {len(result.failed)} 个；"
        f"日志：{result.log_file}"
    )
    self.update_batch_button_states()
    message = QMessageBox(self)
    message.setWindowTitle("批量处理完成")
    message.setIcon(QMessageBox.Warning if result.failed else QMessageBox.Information)
    message.setText(
        f"成功 {len(result.successful)} 个，失败 {len(result.failed)} 个"
    )
    message.setInformativeText(
        f"结果文件夹：\n{self.batch_output_folder}\n\n处理日志：\n{result.log_file}"
    )
    open_button = message.addButton("打开文件夹", QMessageBox.ActionRole)
    ok_button = message.addButton("确定", QMessageBox.AcceptRole)
    message.setDefaultButton(ok_button)
    message.exec()
    if message.clickedButton() is open_button:
        self.open_batch_output_folder()


def retry_failed_batch_files(self):
    if self.batch_failed_files:
        self.start_batch_processing(tuple(self.batch_failed_files))


def open_batch_output_folder(self):
    if self.batch_output_folder and Path(self.batch_output_folder).is_dir():
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.batch_output_folder))

