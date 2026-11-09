"""Excel cleanup page.

Functions are bound onto ExcelMergerWindow and use app.py globals,
so tests can keep patching Qt and tool names on the app module.
"""

def create_cleanup_page(self):
    page = QWidget()
    page.setObjectName("cleanupPage")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(22, 18, 22, 18)
    layout.setSpacing(12)

    title = QLabel("Excel 数据清理")
    title.setFont(QFont("PingFang SC", 24, QFont.Bold))
    title.setProperty("role", "title")
    layout.addWidget(title)
    subtitle = QLabel("先查看预计变化，再把选中的工作表清理后另存为新文件")
    subtitle.setProperty("role", "subtitle")
    layout.addWidget(subtitle)

    source_group = QGroupBox("源文件和工作表")
    source_layout = QVBoxLayout(source_group)
    source_row = QHBoxLayout()
    self.cleanup_source_path_edit = QLineEdit()
    self.cleanup_source_path_edit.setReadOnly(True)
    self.cleanup_source_path_edit.setPlaceholderText("请选择 .xlsx 或 .xlsm 文件")
    self.choose_cleanup_source_button = QPushButton("选择 Excel")
    self.choose_cleanup_source_button.setProperty("variant", "accent")
    source_row.addWidget(self.cleanup_source_path_edit, 1)
    source_row.addWidget(self.choose_cleanup_source_button)
    source_layout.addLayout(source_row)
    sheet_row = QHBoxLayout()
    self.cleanup_sheet_combo = SelectionComboBox()
    self.cleanup_header_row_spinbox = ClearSpinBox()
    self.cleanup_header_row_spinbox.setRange(1, 999)
    self.cleanup_header_row_spinbox.setValue(1)
    self.cleanup_header_row_spinbox.setSuffix(" 行")
    self.cleanup_preview_button = QPushButton("更新预览")
    sheet_row.addWidget(QLabel("工作表："))
    sheet_row.addWidget(self.cleanup_sheet_combo, 1)
    sheet_row.addWidget(QLabel("表头所在行："))
    sheet_row.addWidget(self.cleanup_header_row_spinbox)
    sheet_row.addWidget(self.cleanup_preview_button)
    source_layout.addLayout(sheet_row)
    layout.addWidget(source_group)

    options_group = QGroupBox("清理规则")
    options_layout = QGridLayout(options_group)
    options_layout.setHorizontalSpacing(28); options_layout.setVerticalSpacing(14)
    self.cleanup_empty_rows_checkbox = QCheckBox("删除空白行")
    self.cleanup_empty_rows_checkbox.setChecked(True)
    self.cleanup_spaces_checkbox = QCheckBox("清理文字多余空格")
    self.cleanup_spaces_checkbox.setChecked(True)
    self.cleanup_deduplicate_checkbox = QCheckBox("删除重复行")
    self.cleanup_dates_checkbox = QCheckBox("统一日期显示")
    self.cleanup_numbers_checkbox = QCheckBox("统一数字显示")
    for index, checkbox in enumerate((
        self.cleanup_empty_rows_checkbox,
        self.cleanup_spaces_checkbox,
        self.cleanup_deduplicate_checkbox,
        self.cleanup_dates_checkbox,
        self.cleanup_numbers_checkbox,
    )):
        options_layout.addWidget(checkbox, index // 2, index % 2)
    layout.addWidget(options_group)

    columns_group = QGroupBox("判断重复的列（不选时按整行判断）")
    columns_layout = QVBoxLayout(columns_group)
    self.cleanup_columns_tree = QTreeWidget()
    self.cleanup_columns_tree.setHeaderLabels(["判断重复的列"])
    self.cleanup_columns_tree.setRootIsDecorated(False)
    self.cleanup_columns_tree.setMaximumHeight(145)
    columns_layout.addWidget(self.cleanup_columns_tree)
    layout.addWidget(columns_group)
    columns_group.setVisible(False)
    self.cleanup_deduplicate_checkbox.toggled.connect(columns_group.setVisible)

    preview_group = QGroupBox("预计结果")
    preview_layout = QVBoxLayout(preview_group)
    preview_layout.setSizeConstraint(QVBoxLayout.SetMinimumSize)
    self.cleanup_preview_label = QLabel("等待选择 Excel 文件")
    self.cleanup_preview_label.setWordWrap(True)
    self.cleanup_preview_label.setProperty("role", "status")
    preview_layout.addWidget(self.cleanup_preview_label)
    layout.addWidget(preview_group)

    output_group = QGroupBox("保存位置")
    output_layout = QHBoxLayout(output_group)
    self.cleanup_output_path_edit = QLineEdit()
    self.cleanup_output_path_edit.setReadOnly(True)
    self.cleanup_output_path_edit.setPlaceholderText("请选择结果保存文件夹")
    self.choose_cleanup_output_button = QPushButton("选择文件夹")
    output_layout.addWidget(self.cleanup_output_path_edit, 1)
    output_layout.addWidget(self.choose_cleanup_output_button)
    layout.addWidget(output_group)

    action_layout = QHBoxLayout()
    self.cleanup_start_button = QPushButton("开始清理并另存")
    self.cleanup_start_button.setProperty("variant", "primary")
    self.cleanup_start_button.setMinimumHeight(38)
    self.cleanup_open_result_button = QPushButton("打开结果")
    self.cleanup_open_result_button.setMinimumHeight(38)
    action_layout.addStretch()
    action_layout.addWidget(self.cleanup_start_button)
    action_layout.addWidget(self.cleanup_open_result_button)
    layout.addLayout(action_layout)

    self.choose_cleanup_source_button.clicked.connect(self.choose_cleanup_source_file)
    self.choose_cleanup_output_button.clicked.connect(self.choose_cleanup_output_folder)
    self.cleanup_preview_button.clicked.connect(self.refresh_cleanup_preview)
    self.cleanup_start_button.clicked.connect(self.start_excel_cleanup)
    self.cleanup_open_result_button.clicked.connect(
        lambda: self.open_output_file(self.cleanup_result_file)
    )
    self.cleanup_sheet_combo.currentIndexChanged.connect(
        self.invalidate_cleanup_preview
    )
    self.cleanup_header_row_spinbox.valueChanged.connect(
        self.invalidate_cleanup_preview
    )
    self.cleanup_columns_tree.itemChanged.connect(self.invalidate_cleanup_preview)
    for checkbox in (
        self.cleanup_empty_rows_checkbox,
        self.cleanup_spaces_checkbox,
        self.cleanup_deduplicate_checkbox,
        self.cleanup_dates_checkbox,
        self.cleanup_numbers_checkbox,
    ):
        checkbox.toggled.connect(self.invalidate_cleanup_preview)
    self.update_cleanup_button_states()
    layout.addStretch(1)
    contain_page_form(page)
    return page


def choose_cleanup_source_file(self):
    filename, _ = QFileDialog.getOpenFileName(
        self,
        "选择需要清理的 Excel 文件",
        self.dialog_folder("cleanup_open"),
        "Excel 文件 (*.xlsx *.xlsm)",
    )
    if not filename:
        return
    self.cleanup_source_file = os.path.abspath(filename)
    self.cleanup_source_path_edit.setText(self.cleanup_source_file)
    self.cleanup_source_path_edit.setToolTip(self.cleanup_source_file)
    self.remember_dialog_folder("cleanup_open", Path(filename).parent)
    self.cleanup_output_folder = str(Path(filename).parent / "Eggie Excel 清理结果")
    self.cleanup_output_path_edit.setText(self.cleanup_output_folder)
    self.cleanup_result_file = ""
    self.cleanup_preview = None

    def worker(_progress_callback):
        return workbook_sheet_names(self.cleanup_source_file)

    self.start_background_task(
        "读取 Excel",
        "正在读取工作表名称…",
        worker,
        self.cleanup_source_loaded,
        status_label=self.cleanup_preview_label,
    )


def cleanup_source_loaded(self, sheet_names):
    self.cleanup_sheet_combo.blockSignals(True)
    self.cleanup_sheet_combo.clear()
    self.cleanup_sheet_combo.addItems(list(sheet_names))
    self.cleanup_sheet_combo.blockSignals(False)
    if not sheet_names:
        self.cleanup_preview_label.setText("这个 Excel 没有可处理的工作表")
        self.update_cleanup_button_states()
        return
    self.refresh_cleanup_preview()


def current_cleanup_options(self):
    columns = []
    for index in range(self.cleanup_columns_tree.topLevelItemCount()):
        item = self.cleanup_columns_tree.topLevelItem(index)
        if item.checkState(0) == Qt.Checked:
            columns.append(int(item.data(0, Qt.UserRole)))
    return CleanupOptions(
        sheet_name=self.cleanup_sheet_combo.currentText(),
        header_row=self.cleanup_header_row_spinbox.value(),
        remove_empty_rows=self.cleanup_empty_rows_checkbox.isChecked(),
        trim_whitespace=self.cleanup_spaces_checkbox.isChecked(),
        deduplicate=self.cleanup_deduplicate_checkbox.isChecked(),
        duplicate_columns=tuple(columns),
        normalize_dates=self.cleanup_dates_checkbox.isChecked(),
        normalize_numbers=self.cleanup_numbers_checkbox.isChecked(),
    )


def invalidate_cleanup_preview(self, *_args):
    if self.cleanup_populating_columns:
        return
    self.cleanup_preview = None
    if self.cleanup_source_file and self.cleanup_sheet_combo.currentText():
        self.cleanup_preview_label.setText("规则已变化，请点击“更新预览”")
    self.update_cleanup_button_states()


def refresh_cleanup_preview(self):
    if not self.cleanup_source_file or not self.cleanup_sheet_combo.currentText():
        return
    source = self.cleanup_source_file
    options = self.current_cleanup_options()
    self.invalidate_cleanup_preview()

    def worker(_progress_callback):
        return preview_cleanup(source, options)

    def completed(preview):
        if self.cleanup_source_file == source and self.current_cleanup_options() == options:
            self.display_cleanup_preview(preview)

    self.start_background_task(
        "检查 Excel",
        f"正在检查工作表：{options.sheet_name}",
        worker,
        completed,
        status_label=self.cleanup_preview_label,
    )


def display_cleanup_preview(self, preview):
    selected_columns = {
        int(self.cleanup_columns_tree.topLevelItem(index).data(0, Qt.UserRole))
        for index in range(self.cleanup_columns_tree.topLevelItemCount())
        if self.cleanup_columns_tree.topLevelItem(index).checkState(0) == Qt.Checked
    }
    self.cleanup_populating_columns = True
    self.cleanup_columns_tree.blockSignals(True)
    self.cleanup_columns_tree.clear()
    for index, header in enumerate(preview.headers, 1):
        item = QTreeWidgetItem([f"第 {index} 列：{header}"])
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0, Qt.Checked if index in selected_columns else Qt.Unchecked)
        item.setData(0, Qt.UserRole, index)
        self.cleanup_columns_tree.addTopLevelItem(item)
    self.cleanup_columns_tree.blockSignals(False)
    self.cleanup_populating_columns = False
    self.cleanup_preview = preview
    formula_note = (
        f"；公式 {preview.formula_cells} 个，请处理后检查公式结果"
        if preview.formula_cells
        else ""
    )
    self.cleanup_preview_label.setText(
        f"数据行 {preview.original_rows}，空白行 {preview.blank_rows}，"
        f"重复行 {preview.duplicate_rows}，空格问题 {preview.whitespace_cells}，"
        f"日期 {preview.date_cells}，数字 {preview.number_cells}{formula_note}"
        + (f"\n不能执行：{preview.blocked_reason}" if preview.blocked_reason else "")
    )
    self.update_cleanup_button_states()


def choose_cleanup_output_folder(self):
    folder = QFileDialog.getExistingDirectory(
        self,
        "选择 Excel 清理结果保存文件夹",
        self.dialog_folder("cleanup_output", self.cleanup_output_folder),
    )
    if not folder:
        return
    self.cleanup_output_folder = os.path.abspath(folder)
    self.remember_dialog_folder("cleanup_output", self.cleanup_output_folder)
    self.cleanup_output_path_edit.setText(self.cleanup_output_folder)
    self.update_cleanup_button_states()


def update_cleanup_button_states(self):
    ready = bool(
        self.cleanup_source_file
        and self.cleanup_sheet_combo.currentText()
        and self.cleanup_output_folder
        and self.cleanup_preview is not None
        and not self.cleanup_preview.blocked_reason
    )
    self.cleanup_preview_button.setEnabled(
        bool(self.cleanup_source_file and self.cleanup_sheet_combo.currentText())
    )
    self.cleanup_start_button.setEnabled(ready)
    self.cleanup_open_result_button.setEnabled(bool(self.cleanup_result_file))


def start_excel_cleanup(self):
    if self.cleanup_preview is None:
        QMessageBox.information(self, "请先更新预览", "规则变化后需要重新查看预计结果。")
        return
    if self.cleanup_preview.blocked_reason:
        QMessageBox.warning(self, "无法按所选规则清理", self.cleanup_preview.blocked_reason)
        return
    if self.cleanup_preview.formula_cells:
        answer = QMessageBox.question(
            self,
            "工作表包含公式",
            f"检测到 {self.cleanup_preview.formula_cells} 个公式。删除行可能影响公式引用，"
            "软件会另存新文件，不修改原文件。\n\n是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
    options = self.current_cleanup_options()

    def worker(progress_callback):
        return clean_workbook(
            self.cleanup_source_file,
            self.cleanup_output_folder,
            options,
            progress_callback,
        )

    self.start_background_task(
        "Excel 数据清理",
        "正在清理并生成新文件…",
        worker,
        self.excel_cleanup_completed,
        total=max(self.cleanup_preview.original_rows, 1),
        status_label=self.cleanup_preview_label,
    )


def excel_cleanup_completed(self, result):
    self.cleanup_result_file = result.output_file
    self.cleanup_preview_label.setText(
        f"清理完成：删除 {result.removed_rows} 行，剩余数据行 {result.final_rows}；"
        f"日志：{result.log_file}"
    )
    self.update_cleanup_button_states()
    message = QMessageBox(self)
    message.setWindowTitle("Excel 清理完成")
    message.setIcon(QMessageBox.Information)
    message.setText("已生成新的 Excel 文件，原文件没有修改")
    message.setInformativeText(
        f"结果文件：\n{result.output_file}\n\n处理日志：\n{result.log_file}"
    )
    open_button = message.addButton("打开结果", QMessageBox.ActionRole)
    ok_button = message.addButton("确定", QMessageBox.AcceptRole)
    message.setDefaultButton(ok_button)
    message.exec()
    if message.clickedButton() is open_button:
        self.open_output_file(result.output_file)

