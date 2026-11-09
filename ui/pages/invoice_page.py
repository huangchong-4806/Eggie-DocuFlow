"""Invoice batch page.

Functions are bound onto ExcelMergerWindow and use app.py globals,
so tests can keep patching Qt and tool names on the app module.
"""

def create_invoice_page(self):
    page = QWidget()
    page.setObjectName("invoicePage")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(22, 18, 22, 18)
    layout.setSpacing(14)

    title = QLabel("发票解析")
    title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    title.setFont(QFont("PingFang SC", 24, QFont.Bold))
    title.setProperty("role", "title")
    layout.addWidget(title)

    subtitle = QLabel("统一提取发票基本信息和明细，自动校验金额与税额")
    subtitle.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    subtitle.setProperty("role", "subtitle")
    layout.addWidget(subtitle)

    source_button_layout = QHBoxLayout()
    source_button_layout.setSpacing(10)
    self.choose_invoice_source_button = QPushButton("添加 PDF 发票")
    self.delete_invoice_source_button = QPushButton("移出列表")
    self.delete_invoice_source_button.setToolTip("从待处理列表移除，不删除原文件")
    self.clear_invoice_source_button = QPushButton("清空列表")
    self.choose_invoice_source_button.setProperty("variant", "accent")
    self.delete_invoice_source_button.setProperty("variant", "danger")
    for button in (
        self.choose_invoice_source_button,
        self.delete_invoice_source_button,
        self.clear_invoice_source_button,
    ):
        button.setMinimumHeight(34)
        source_button_layout.addWidget(button)
    source_button_layout.addStretch()
    layout.addLayout(source_button_layout)

    source_group = QGroupBox("待解析 PDF 发票")
    source_layout = QVBoxLayout(source_group)
    source_layout.setContentsMargins(10, 14, 10, 10)
    source_layout.setSpacing(8)
    self.invoice_file_table = QTreeWidget()
    self.invoice_file_table.setColumnCount(4)
    self.invoice_file_table.setHeaderLabels(
        ["序号", "文件名", "文件大小", "文件路径"]
    )
    self.invoice_file_table.headerItem().setTextAlignment(0, Qt.AlignCenter)
    self.invoice_file_table.setRootIsDecorated(False)
    self.invoice_file_table.setUniformRowHeights(True)
    self.invoice_file_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
    self.invoice_file_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    self.invoice_file_table.setTextElideMode(Qt.TextElideMode.ElideNone)
    self.invoice_file_table.setAlternatingRowColors(True)
    header = self.invoice_file_table.header()
    header.setSectionResizeMode(0, QHeaderView.Fixed)
    header.setSectionResizeMode(1, QHeaderView.Interactive)
    header.setSectionResizeMode(2, QHeaderView.Fixed)
    header.setSectionResizeMode(3, QHeaderView.Stretch)
    self.invoice_file_table.setColumnWidth(0, 80)
    self.invoice_file_table.setColumnWidth(1, 300)
    self.invoice_file_table.setColumnWidth(2, 110)
    source_layout.addWidget(self.invoice_file_table)
    self.invoice_file_status_label = QLabel("尚未添加文件")
    self.invoice_file_status_label.setProperty("role", "status")
    source_layout.addWidget(self.invoice_file_status_label)
    layout.addWidget(source_group, 1)

    output_group = QGroupBox("Excel 保存文件夹")
    output_layout = QHBoxLayout(output_group)
    output_layout.setContentsMargins(12, 14, 12, 10)
    output_layout.setSpacing(10)
    self.invoice_output_path_edit = QLineEdit()
    self.invoice_output_path_edit.setReadOnly(True)
    self.invoice_output_path_edit.setPlaceholderText("请选择批量结果保存文件夹")
    self.invoice_output_path_edit.setMinimumHeight(34)
    self.choose_invoice_output_button = QPushButton("选择文件夹")
    self.choose_invoice_output_button.setMinimumHeight(34)
    output_layout.addWidget(self.invoice_output_path_edit, 1)
    output_layout.addWidget(self.choose_invoice_output_button)
    layout.addWidget(output_group)

    hint = QLabel(
        "每张 PDF 独立生成一个 Excel；单个失败不影响其他发票。"
        "汇总时按发票号标出重复项，空白发票号不算重复。扫描图片型 PDF 暂不支持。"
    )
    hint.setAlignment(Qt.AlignLeft)
    hint.setProperty("role", "hint")
    hint.setWordWrap(True)
    layout.insertWidget(3, hint)
    self.invoice_convert_button = QPushButton("开始识别并生成 Excel")
    self.invoice_convert_button.setMinimumHeight(38)
    self.invoice_convert_button.setMinimumWidth(190)
    self.invoice_convert_button.setFont(QFont("PingFang SC", 14, QFont.Bold))
    self.invoice_convert_button.setProperty("variant", "primary")
    button_layout = QHBoxLayout()
    button_layout.addStretch()
    button_layout.addWidget(self.invoice_convert_button)
    layout.addLayout(button_layout)

    self.choose_invoice_source_button.clicked.connect(self.add_invoice_files)
    self.delete_invoice_source_button.clicked.connect(self.delete_selected_invoice_files)
    self.clear_invoice_source_button.clicked.connect(self.clear_invoice_files)
    self.choose_invoice_output_button.clicked.connect(self.choose_invoice_output_folder)
    self.invoice_convert_button.clicked.connect(self.convert_invoice)
    self.invoice_file_table.itemSelectionChanged.connect(
        self.update_invoice_button_states
    )
    self.refresh_invoice_file_list()
    return page


def refresh_invoice_file_list(self):
    self.invoice_file_table.clear()
    if not self.invoice_source_files:
        empty_item = QTreeWidgetItem(
            ["", "暂无文件，请添加 PDF 发票", "", ""]
        )
        empty_item.setFlags(Qt.NoItemFlags)
        self.invoice_file_table.addTopLevelItem(empty_item)
        self.invoice_file_status_label.setText("尚未添加文件")
    else:
        for index, filename in enumerate(self.invoice_source_files, 1):
            path = Path(filename)
            try:
                size = format_file_size(path.stat().st_size)
            except OSError:
                size = "无法读取"
            item = QTreeWidgetItem(
                [f"{index:03d}", path.name, size, filename]
            )
            item.setData(0, Qt.UserRole, filename)
            item.setTextAlignment(0, Qt.AlignCenter)
            item.setTextAlignment(2, Qt.AlignCenter)
            item.setToolTip(1, filename)
            item.setToolTip(3, filename)
            self.invoice_file_table.addTopLevelItem(item)
        self.invoice_file_status_label.setText(
            f"已添加 {len(self.invoice_source_files)} 个 PDF 发票"
        )
    self.update_invoice_button_states()


def update_invoice_button_states(self):
    has_files = bool(self.invoice_source_files)
    has_selection = any(
        item.data(0, Qt.UserRole)
        for item in self.invoice_file_table.selectedItems()
    )
    self.delete_invoice_source_button.setEnabled(has_selection)
    self.clear_invoice_source_button.setEnabled(has_files)
    self.invoice_convert_button.setEnabled(
        has_files and bool(self.invoice_output_folder)
    )


def add_invoice_files(self):
    filenames, _ = QFileDialog.getOpenFileNames(
        self,
        "选择一个或多个 PDF 发票",
        self.dialog_folder("open"),
        "PDF 文件 (*.pdf)",
    )
    if not filenames:
        return
    self.remember_dialog_folder("open", filenames[0])
    existing = set(self.invoice_source_files)
    for filename in filenames:
        normalized = os.path.abspath(filename)
        if normalized not in existing:
            self.invoice_source_files.append(normalized)
            existing.add(normalized)
    self.refresh_invoice_file_list()


def delete_selected_invoice_files(self):
    selected = {
        item.data(0, Qt.UserRole)
        for item in self.invoice_file_table.selectedItems()
        if item.data(0, Qt.UserRole)
    }
    if selected:
        self.invoice_source_files = [
            filename
            for filename in self.invoice_source_files
            if filename not in selected
        ]
        self.refresh_invoice_file_list()


def clear_invoice_files(self):
    self.invoice_source_files = []
    self.refresh_invoice_file_list()


def choose_invoice_output_folder(self):
    output_folder = QFileDialog.getExistingDirectory(
        self,
        "选择批量结果保存文件夹",
        self.dialog_folder("save", self.invoice_output_folder),
    )
    if not output_folder:
        return
    self.invoice_output_folder = os.path.abspath(output_folder)
    self.remember_dialog_folder("save", self.invoice_output_folder)
    self.invoice_output_path_edit.setText(self.invoice_output_folder)
    self.invoice_output_path_edit.setToolTip(self.invoice_output_folder)
    self.update_invoice_button_states()


def show_invoice_complete_message(self, results, failures, ledger_result=None):
    message = QMessageBox(self)
    message.setWindowTitle("批量发票解析完成")
    message.setIcon(QMessageBox.Warning if failures else QMessageBox.Information)
    message.setText(f"成功 {len(results)} 个，失败 {len(failures)} 个")
    item_count = sum(result.item_count for result in results)
    abnormal_count = sum(result.abnormal_count for result in results)
    detail = (
        f"保存文件夹：\n{self.invoice_output_folder}\n\n"
        f"明细行数：{item_count}\n校验异常：{abnormal_count} 项"
    )
    if ledger_result:
        detail += (
            f"\n\n汇总结果：\n{ledger_result.output_file}"
        )
        if ledger_result.duplicate_rows:
            detail += (
                f"\n\n发现重复发票号：{ledger_result.duplicate_rows} 行已在汇总表标红。"
                "空白发票号不参与查重。"
            )
        if ledger_result.log_file:
            detail += f"\n\n日志文件：\n{ledger_result.log_file}"
        elif ledger_result.log_error:
            detail += f"\n\n处理日志未生成：\n{ledger_result.log_error}"
    message.setInformativeText(detail)
    if failures:
        message.setDetailedText(
            "\n".join(f"{Path(path).name}：{error}" for path, error in failures)
        )
    open_button = message.addButton("打开文件夹", QMessageBox.ActionRole)
    ok_button = message.addButton("确定", QMessageBox.AcceptRole)
    for button in (ok_button, open_button):
        button.setFixedSize(112, 36)
    message.setDefaultButton(ok_button)
    message.exec()
    if message.clickedButton() == open_button:
        self.open_output_file(self.invoice_output_folder)


def convert_invoice(self):
    if not self.invoice_source_files or not self.invoice_output_folder:
        QMessageBox.warning(self, "尚未完成设置", "请先选择 PDF 发票和 Excel 保存文件夹。")
        return
    source_files = tuple(self.invoice_source_files)
    output_folder = self.invoice_output_folder

    def invoices_completed(result):
        results, failures, ledger_result, ledger_error = result
        if ledger_error:
            QMessageBox.warning(
                self,
                "汇总结果生成失败",
                f"单张发票 Excel 已生成，但批量汇总结果失败：\n{ledger_error}",
            )
        elif ledger_result and ledger_result.log_error:
            QMessageBox.warning(
                self,
                "处理日志未生成",
                "单张发票 Excel 和汇总结果均已生成，"
                f"但处理日志未生成：\n{ledger_result.log_error}",
            )
        if results or failures:
            self.show_invoice_complete_message(results, failures, ledger_result)

    failure_message = lambda error: QMessageBox.critical(
        self,
        "发票识别失败",
        f"{error}\n\n未完成的发票不会生成不完整 Excel。",
    )
    if os.name == "nt":
        self.start_background_task(
            "正在批量解析发票",
            f"准备解析 {len(source_files)} 个 PDF 发票…",
            None,
            invoices_completed,
            failure_message,
            total=len(source_files),
            status_label=self.invoice_file_status_label,
            task_thread=InvoiceBatchProcessThread(
                source_files,
                output_folder,
                parent=self,
            ),
            allow_force_stop=True,
            on_cancel=lambda: QMessageBox.information(
                self,
                "任务已结束",
                "已强制结束当前发票任务。未完成的发票没有生成不完整 Excel；"
                "已经完成的结果会保留。",
            ),
        )
        return

    def process_invoices(progress_callback):
        results, failures = convert_invoice_pdfs(
            source_files,
            output_folder,
            progress_callback=progress_callback,
        )
        ledger_result = None
        ledger_error = ""
        if results:
            progress_callback(
                len(source_files) * 100,
                max(len(source_files) * 100, 1),
                "正在生成发票汇总结果和处理日志…",
            )
            try:
                ledger_result = write_invoice_ledger(
                    results,
                    failures,
                    output_folder,
                )
            except Exception as error:
                ledger_error = str(error)
        return results, failures, ledger_result, ledger_error

    self.start_background_task(
        "正在批量解析发票",
        f"准备解析 {len(source_files)} 个 PDF 发票…",
        process_invoices,
        invoices_completed,
        failure_message,
        total=len(source_files),
        status_label=self.invoice_file_status_label,
    )

