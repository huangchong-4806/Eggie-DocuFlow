"""Excel row-split page.

Functions are bound onto ExcelMergerWindow and use app.py globals,
so tests can keep patching Qt and tool names on the app module.
"""

def create_split_page(self):
    page = QWidget()
    page.setObjectName("splitPage")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(22, 18, 22, 18)
    layout.setSpacing(14)
    title = QLabel("Excel 拆分")
    title.setProperty("role", "title")
    layout.addWidget(title)
    subtitle = QLabel("将一张表拆成清晰有序的多个结果，原文件保持不变。")
    subtitle.setProperty("role", "subtitle")
    layout.addWidget(subtitle)
    self.split_mode_tabs = QTabWidget()
    self.split_mode_tabs.setObjectName("splitModeTabs")
    self.split_mode_tabs.addTab(self.create_row_split_page(), "按固定行数拆分")
    self.category_split_page = CategorySplitPage()
    self.split_mode_tabs.addTab(self.category_split_page, "按分类拆分")
    layout.addWidget(self.split_mode_tabs)
    return page


def create_row_split_page(self):
    page = QWidget()
    page.setObjectName("splitPage")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(22, 18, 22, 18)
    layout.setSpacing(14)

    source_group = QGroupBox("源文件")
    source_layout = QVBoxLayout(source_group)
    source_layout.setContentsMargins(12, 14, 12, 10)
    source_layout.setSpacing(8)

    source_picker_layout = QHBoxLayout()
    source_picker_layout.setSpacing(10)
    self.split_source_path_edit = QLineEdit()
    self.split_source_path_edit.setReadOnly(True)
    self.split_source_path_edit.setPlaceholderText("请选择需要拆分的 Excel 文件")
    self.split_source_path_edit.setMinimumHeight(34)
    self.choose_split_source_button = QPushButton("选择文件")
    self.choose_split_source_button.setMinimumHeight(34)
    self.choose_split_source_button.setProperty("variant", "accent")
    source_picker_layout.addWidget(self.split_source_path_edit, 1)
    source_picker_layout.addWidget(self.choose_split_source_button)
    source_layout.addLayout(source_picker_layout)

    self.split_source_status_label = QLabel("尚未选择文件")
    self.split_source_status_label.setProperty("role", "status")
    source_layout.addWidget(self.split_source_status_label)
    layout.addWidget(source_group)

    output_group = QGroupBox("保存文件夹")
    output_layout = QHBoxLayout(output_group)
    output_layout.setContentsMargins(12, 14, 12, 10)
    output_layout.setSpacing(10)

    self.split_output_folder_edit = QLineEdit()
    self.split_output_folder_edit.setReadOnly(True)
    self.split_output_folder_edit.setPlaceholderText("请选择拆分后文件的保存文件夹")
    self.split_output_folder_edit.setMinimumHeight(34)
    self.choose_split_output_button = QPushButton("选择文件夹")
    self.choose_split_output_button.setMinimumHeight(34)
    output_layout.addWidget(self.split_output_folder_edit, 1)
    output_layout.addWidget(self.choose_split_output_button)
    layout.addWidget(output_group)

    options_group = QGroupBox("拆分设置")
    options_layout = QHBoxLayout(options_group)
    options_layout.setContentsMargins(12, 18, 12, 14)
    options_layout.setSpacing(18)
    options_layout.setAlignment(Qt.AlignLeft)

    header_rows_label = QLabel("表头行数：")
    self.split_header_rows_spinbox = ClearSpinBox()
    self.split_header_rows_spinbox.setRange(0, 999)
    self.split_header_rows_spinbox.setValue(1)
    self.split_header_rows_spinbox.setSuffix(" 行")
    self.split_header_rows_spinbox.setMinimumWidth(105)
    self.split_header_rows_spinbox.setToolTip(
        "例如填 2，表示第 1 到第 2 行会作为表头复制到每个拆分文件。"
    )

    rows_per_file_label = QLabel("每个文件数据行数：")
    self.split_rows_per_file_spinbox = ClearSpinBox()
    self.split_rows_per_file_spinbox.setRange(1, 1000000)
    self.split_rows_per_file_spinbox.setValue(1000)
    self.split_rows_per_file_spinbox.setSuffix(" 行")
    self.split_rows_per_file_spinbox.setMinimumWidth(130)
    self.split_rows_per_file_spinbox.setToolTip(
        "这里填写的是数据行数，不包含每个文件都会复制的表头。"
    )

    options_layout.addWidget(header_rows_label)
    options_layout.addWidget(self.split_header_rows_spinbox)
    options_layout.addWidget(rows_per_file_label)
    options_layout.addWidget(self.split_rows_per_file_spinbox)
    layout.removeWidget(output_group)
    layout.addWidget(options_group)
    layout.addWidget(output_group)

    self.split_button = QPushButton("开始拆分")
    self.split_button.setMinimumHeight(38)
    self.split_button.setMinimumWidth(140)
    self.split_button.setFont(QFont("PingFang SC", 14, QFont.Bold))
    self.split_button.setProperty("variant", "primary")
    split_button_layout = QHBoxLayout()
    split_button_layout.addStretch()
    split_button_layout.addWidget(self.split_button)
    layout.addLayout(split_button_layout)

    self.choose_split_source_button.clicked.connect(self.choose_split_source_file)
    self.choose_split_output_button.clicked.connect(self.choose_split_output_folder)
    self.split_button.clicked.connect(self.split_workbook)
    self.split_header_rows_spinbox.valueChanged.connect(self.update_split_estimate)
    self.split_rows_per_file_spinbox.valueChanged.connect(self.update_split_estimate)
    layout.addStretch(1)
    contain_page_form(page, 0, 860)
    return page


def choose_split_source_file(self):
    filename, _ = QFileDialog.getOpenFileName(
        self,
        "选择要拆分的 Excel 文件",
        self.dialog_folder("open"),
        "Excel 文件 (*.xlsx)",
    )
    if not filename:
        return
    self.remember_dialog_folder("open", filename)

    if Path(filename).suffix.lower() != ".xlsx":
        QMessageBox.warning(
            self,
            "文件格式不支持",
            "拆分工具只支持 .xlsx 格式的 Excel 文件。",
        )
        return

    self.split_source_file = os.path.abspath(filename)
    self.split_result_folder = ""
    self.split_source_path_edit.setText(self.split_source_file)
    self.split_source_path_edit.setToolTip(self.split_source_file)
    source_file = self.split_source_file

    def info_loaded(info):
        self.split_source_info = info
        self.update_split_estimate()

    def info_failed(error):
        self.split_source_info = {}
        self.split_source_status_label.setText("已选择文件，但暂时无法读取行数")
        QMessageBox.warning(
            self,
            "文件信息读取失败",
            f"{os.path.basename(source_file)}\n{error}",
        )

    self.start_background_task(
        "读取 Excel 文件",
        f"正在读取：{Path(source_file).name}",
        lambda _progress: get_file_info(source_file),
        info_loaded,
        info_failed,
        status_label=self.split_source_status_label,
    )


def update_split_estimate(self):
    if not self.split_source_file:
        return
    total_rows = self.split_source_info.get("rows")
    if not isinstance(total_rows, int):
        return
    header_rows = self.split_header_rows_spinbox.value()
    rows_per_file = self.split_rows_per_file_spinbox.value()
    if header_rows >= total_rows:
        estimate = "表头行数不能大于或等于总行数"
    else:
        data_rows = total_rows - header_rows
        file_count = (data_rows + rows_per_file - 1) // rows_per_file
        estimate = f"预计生成 {file_count} 个文件，数据行 {data_rows} 行"
    self.split_source_status_label.setText(
        f"已选择文件，大小 {self.split_source_info.get('size', '-')}，"
        f"共 {total_rows} 行（含表头），{estimate}"
    )


def choose_split_output_folder(self):
    folder = QFileDialog.getExistingDirectory(
        self,
        "选择保存文件夹",
        self.dialog_folder("save", self.split_output_folder),
        QFileDialog.ShowDirsOnly,
    )
    if not folder:
        return

    self.split_output_folder = os.path.abspath(folder)
    self.remember_dialog_folder("save", self.split_output_folder)
    self.split_result_folder = ""
    self.split_output_folder_edit.setText(self.split_output_folder)
    self.split_output_folder_edit.setToolTip(self.split_output_folder)


def open_split_output_folder(self):
    folder = self.split_result_folder or self.split_output_folder
    opened = QDesktopServices.openUrl(
        QUrl.fromLocalFile(folder)
    )
    if not opened:
        QMessageBox.warning(
            self,
            "无法打开文件夹",
            "拆分已完成，但无法打开文件夹：\n"
            f"{folder}",
        )
    return opened


def show_split_complete_message(self, split_result):
    message = QMessageBox(self)
    message.setWindowTitle("拆分完成")
    message.setIcon(QMessageBox.Information)
    message.setText("拆分完成")
    message.setInformativeText(
        f"最终保存文件夹：\n{split_result.output_folder}\n\n"
        f"总行数：{split_result.total_rows}\n"
        f"表头行数：{split_result.header_rows}\n"
        f"数据行数：{split_result.data_rows}\n"
        f"生成文件数量：{split_result.file_count}\n"
        f"总耗时：{format_elapsed_seconds(split_result.elapsed_seconds)}\n"
        "平均每个文件耗时："
        f"{format_elapsed_seconds(split_result.average_seconds_per_file)}"
    )
    open_button = message.addButton("打开文件夹", QMessageBox.ActionRole)
    ok_button = message.addButton("确定", QMessageBox.AcceptRole)
    for button in (ok_button, open_button):
        button.setFixedSize(112, 36)
    message.setDefaultButton(ok_button)
    message.exec()
    if message.clickedButton() == open_button:
        self.open_split_output_folder()


def split_workbook(self):
    if not self.split_source_file:
        QMessageBox.warning(
            self,
            "尚未选择文件",
            "请先选择 Excel 文件。",
        )
        return

    if Path(self.split_source_file).suffix.lower() != ".xlsx":
        QMessageBox.warning(
            self,
            "文件格式不支持",
            "拆分工具只支持 .xlsx 格式的 Excel 文件。",
        )
        return

    if not self.split_output_folder:
        QMessageBox.warning(
            self,
            "尚未选择保存文件夹",
            "请先选择保存文件夹。",
        )
        return

    header_rows = self.split_header_rows_spinbox.value()
    rows_per_file = self.split_rows_per_file_spinbox.value()
    source_file = self.split_source_file
    output_folder = self.split_output_folder

    def split_task(progress_callback):
        return split_workbook_by_rows(
            source_file,
            output_folder,
            rows_per_file=rows_per_file,
            header_rows=header_rows,
            progress_callback=lambda value, total, filename: progress_callback(
                value,
                total,
                f"正在拆分第 {value} / {total} 个文件：{filename}",
            ),
        )

    def split_completed(split_result):
        self.split_result_folder = split_result.output_folder
        self.split_source_status_label.setText(
            f"拆分完成，共生成 {split_result.file_count} 个文件"
        )
        self.show_split_complete_message(split_result)

    self.start_background_task(
        "正在拆分 Excel",
        f"正在准备拆分：{Path(source_file).name}",
        split_task,
        split_completed,
        lambda error: QMessageBox.critical(
            self,
            "拆分失败",
            "出现错误：\n"
            f"{error}\n\n"
            "建议检查文件是否正在被 Excel 打开、损坏、加密或包含特殊格式。",
        ),
        status_label=self.split_source_status_label,
    )

