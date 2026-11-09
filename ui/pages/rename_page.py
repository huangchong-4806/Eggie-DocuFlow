"""Batch rename page.

Functions are bound onto ExcelMergerWindow and use app.py globals,
so tests can keep patching Qt and tool names on the app module.
"""

def create_rename_page(self):
    page = QWidget()
    page.setObjectName("renamePage")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(22, 18, 22, 18)
    layout.setSpacing(14)

    title = QLabel("批量改名")
    title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    title.setFont(QFont("PingFang SC", 24, QFont.Bold))
    title.setProperty("role", "title")
    layout.addWidget(title)

    subtitle = QLabel("先预览新文件名，确认无重名和异常后再执行")
    subtitle.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    subtitle.setProperty("role", "subtitle")
    layout.addWidget(subtitle)

    content_layout = QHBoxLayout()
    content_layout.setSpacing(14)

    left_group = QGroupBox("文件预览")
    left_layout = QVBoxLayout(left_group)
    left_layout.setContentsMargins(10, 14, 10, 10)
    left_layout.setSpacing(8)

    source_button_layout = QHBoxLayout()
    source_button_layout.setSpacing(10)
    self.rename_add_files_button = QPushButton("添加文件")
    self.rename_add_folder_button = QPushButton("添加文件夹")
    for button in (self.rename_add_files_button, self.rename_add_folder_button): button.setProperty("compactToolbar", "true")
    self.rename_delete_button = QPushButton("移出列表")
    self.rename_delete_button.setToolTip("从待处理列表移除，不删除原文件")
    self.rename_clear_button = QPushButton("清空列表")
    self.rename_add_files_button.setProperty("variant", "accent")
    self.rename_add_folder_button.setProperty("variant", "accent")
    self.rename_delete_button.setProperty("variant", "danger")
    for button in (
        self.rename_add_files_button,
        self.rename_add_folder_button,
        self.rename_delete_button,
        self.rename_clear_button,
    ):
        button.setMinimumHeight(34)
        source_button_layout.addWidget(button)
    source_button_layout.addStretch()
    left_layout.addLayout(source_button_layout)

    self.rename_limit_label = QLabel(
        "当前 0 / 20,000 个文件；处理数量越多，处理速度越慢，"
        "请酌情拆分任务"
    )
    self.rename_limit_label.setProperty("role", "hint")
    self.rename_limit_label.setWordWrap(True)
    left_layout.addWidget(self.rename_limit_label)

    self.rename_file_table = QTreeWidget()
    self.rename_file_table.setColumnCount(5)
    self.rename_file_table.setHeaderLabels(
        ["序号", "原文件名", "新文件名", "状态", "文件路径"]
    )
    self.rename_file_table.headerItem().setTextAlignment(0, Qt.AlignCenter)
    self.rename_file_table.setRootIsDecorated(False)
    self.rename_file_table.setUniformRowHeights(True)
    self.rename_file_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
    self.rename_file_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    self.rename_file_table.setTextElideMode(Qt.TextElideMode.ElideNone)
    self.rename_file_table.setAlternatingRowColors(True)
    rename_header = self.rename_file_table.header()
    rename_header.setSectionResizeMode(0, QHeaderView.Fixed)
    rename_header.setSectionResizeMode(1, QHeaderView.Interactive)
    rename_header.setSectionResizeMode(2, QHeaderView.Stretch)
    rename_header.setSectionResizeMode(3, QHeaderView.Fixed)
    rename_header.setSectionResizeMode(4, QHeaderView.Fixed)
    self.rename_file_table.setColumnHidden(4, True)
    self.rename_file_table.setColumnWidth(0, 70)
    self.rename_file_table.setColumnWidth(1, 245)
    self.rename_file_table.setColumnWidth(2, 285)
    self.rename_file_table.setColumnWidth(3, 105)
    left_layout.addWidget(self.rename_file_table, 1)
    self.rename_status_label = QLabel("尚未添加文件")
    self.rename_status_label.setProperty("role", "status")
    left_layout.addWidget(self.rename_status_label)
    content_layout.addWidget(left_group, 2)

    right_layout = QVBoxLayout()
    right_layout.setSpacing(12)

    rules_group = QGroupBox("改名规则")
    rules_layout = QVBoxLayout(rules_group)
    rules_layout.setContentsMargins(12, 18, 12, 12)
    rules_layout.setSpacing(7)

    self.rename_rule_combo = SelectionComboBox()
    for label_text, rule_key in (
        ("替换文字", "replace"),
        ("删除指定文字", "delete_text"),
        ("删除开头几个字", "trim_start"),
        ("删除结尾几个字", "trim_end"),
        ("开头添加文字", "prefix"),
        ("末尾添加文字", "suffix"),
        ("修改扩展名", "extension"),
        ("智能识别命名", "smart"),
    ):
        self.rename_rule_combo.addItem(label_text, rule_key)
    self.rename_rule_primary_label = QLabel("查找文字：")
    self.rename_rule_primary_edit = QLineEdit()
    self.rename_rule_secondary_label = QLabel("替换为：")
    self.rename_rule_secondary_edit = QLineEdit()
    self.rename_rule_count_label = QLabel("删除数量：")
    self.rename_rule_count_spinbox = ClearSpinBox()
    self.rename_rule_count_spinbox.setRange(1, 999)
    self.rename_rule_count_spinbox.setValue(1)
    self.rename_numbering_checkbox = QCheckBox("添加编号")
    self.rename_number_start_spinbox = ClearSpinBox()
    self.rename_number_start_spinbox.setRange(0, 999999)
    self.rename_number_start_spinbox.setValue(1)
    self.rename_number_digits_spinbox = ClearSpinBox()
    self.rename_number_digits_spinbox.setRange(1, 9)
    self.rename_number_digits_spinbox.setValue(3)

    rules_layout.addWidget(QLabel("改名方式："))
    rules_layout.addWidget(self.rename_rule_combo)
    rules_layout.addWidget(self.rename_rule_primary_label)
    rules_layout.addWidget(self.rename_rule_primary_edit)
    rules_layout.addWidget(self.rename_rule_secondary_label)
    rules_layout.addWidget(self.rename_rule_secondary_edit)
    rules_layout.addWidget(self.rename_rule_count_label)
    rules_layout.addWidget(self.rename_rule_count_spinbox)

    self.rename_number_widget = QWidget()
    number_layout = QGridLayout(self.rename_number_widget)
    number_layout.setContentsMargins(0, 0, 0, 0)
    number_layout.setSpacing(8)
    self.rename_number_start_spinbox.setMinimumWidth(90)
    self.rename_number_digits_spinbox.setMinimumWidth(78)
    number_layout.addWidget(self.rename_numbering_checkbox, 0, 0, 1, 4)
    number_layout.addWidget(QLabel("起始"), 1, 0)
    number_layout.addWidget(self.rename_number_start_spinbox, 1, 1)
    number_layout.addWidget(QLabel("位数"), 1, 2)
    number_layout.addWidget(self.rename_number_digits_spinbox, 1, 3)
    rules_layout.addWidget(self.rename_number_widget)

    self.rename_smart_options_widget = QWidget()
    smart_layout = QVBoxLayout(self.rename_smart_options_widget)
    smart_layout.setContentsMargins(0, 0, 0, 0)
    smart_layout.setSpacing(7)
    smart_ocr_row = QHBoxLayout()
    self.rename_smart_ocr_checkbox = QCheckBox("扫描页使用云端文字识别")
    self.rename_smart_provider_combo = SelectionComboBox()
    for provider_key, provider_label in PROVIDER_LABELS.items():
        self.rename_smart_provider_combo.addItem(provider_label, provider_key)
    smart_provider_index = self.rename_smart_provider_combo.findData(selected_provider())
    self.rename_smart_provider_combo.setCurrentIndex(max(0, smart_provider_index))
    self.rename_smart_settings_button = QPushButton("设置")
    smart_ocr_row.addWidget(self.rename_smart_ocr_checkbox)
    smart_ocr_row.addWidget(self.rename_smart_provider_combo, 1)
    smart_ocr_row.addWidget(self.rename_smart_settings_button)
    smart_layout.addLayout(smart_ocr_row)
    smart_hint = QLabel("仅支持 PDF；发票按日期、销售方和金额命名，合同按日期和标题命名。重复内容只标记。")
    smart_hint.setWordWrap(True)
    smart_hint.setProperty("role", "hint")
    smart_layout.addWidget(smart_hint)
    rules_layout.addWidget(self.rename_smart_options_widget)
    right_layout.addWidget(rules_group)

    log_group = QGroupBox("操作日志")
    log_layout = QVBoxLayout(log_group)
    log_layout.setContentsMargins(12, 14, 12, 10)
    log_layout.setSpacing(8)
    self.rename_log_path_edit = QLineEdit()
    self.rename_log_path_edit.setReadOnly(True)
    self.rename_log_path_edit.setPlaceholderText("暂无日志")
    self.rename_log_path_edit.setMinimumHeight(34)
    self.rename_open_log_button = QPushButton("打开日志")
    self.rename_open_log_button.setMinimumHeight(34)
    log_layout.addWidget(self.rename_log_path_edit)
    log_layout.addWidget(self.rename_open_log_button)
    self.rename_log_disclosure = Disclosure("操作日志", log_group)
    right_layout.addWidget(self.rename_log_disclosure)

    action_layout = QHBoxLayout()
    self.rename_preview_button = QPushButton("刷新预览")
    self.rename_execute_button = QPushButton("开始改名")
    self.rename_preview_button.setMinimumHeight(44)
    self.rename_execute_button.setMinimumHeight(38)
    self.rename_execute_button.setMinimumWidth(170)
    self.rename_execute_button.setFont(QFont("PingFang SC", 14, QFont.Bold))
    self.rename_execute_button.setProperty("variant", "primary")
    action_layout.addWidget(self.rename_preview_button)
    action_layout.addWidget(self.rename_execute_button, 1)
    right_layout.addLayout(action_layout)
    right_layout.addStretch(1)
    rules_panel = QWidget(); rules_panel.setLayout(right_layout)
    rules_panel.setMinimumWidth(320); rules_panel.setMaximumWidth(380)
    rules_scroll = QScrollArea(); rules_scroll.setWidgetResizable(True); rules_scroll.setWidget(rules_panel)
    rules_scroll.setMinimumWidth(330); rules_scroll.setMaximumWidth(390)
    content_layout.addWidget(rules_scroll, 1)
    layout.addLayout(content_layout, 1)

    self.rename_add_files_button.clicked.connect(self.add_rename_files)
    self.rename_add_folder_button.clicked.connect(self.add_rename_folder)
    self.rename_delete_button.clicked.connect(self.delete_selected_rename_files)
    self.rename_clear_button.clicked.connect(self.clear_rename_files)
    self.rename_preview_button.clicked.connect(
        self.refresh_rename_preview_with_warning
    )
    self.rename_execute_button.clicked.connect(self.rename_files)
    self.rename_open_log_button.clicked.connect(
        lambda: self.open_output_file(self.rename_last_log_file)
    )
    self.rename_file_table.itemSelectionChanged.connect(
        self.update_rename_button_states
    )

    self.rename_preview_timer = QTimer(self)
    self.rename_preview_timer.setSingleShot(True)
    self.rename_preview_timer.setInterval(250)
    self.rename_preview_timer.timeout.connect(
        lambda: self.refresh_rename_file_list()
    )

    self.rename_rule_combo.currentIndexChanged.connect(
        self.handle_rename_rule_changed
    )
    self.rename_rule_primary_edit.textChanged.connect(
        lambda _text: self.schedule_rename_preview()
    )
    self.rename_rule_secondary_edit.textChanged.connect(
        lambda _text: self.schedule_rename_preview()
    )
    self.rename_rule_count_spinbox.valueChanged.connect(
        lambda _value: self.schedule_rename_preview()
    )
    self.rename_numbering_checkbox.toggled.connect(
        lambda _checked: self.schedule_rename_preview()
    )
    self.rename_number_start_spinbox.valueChanged.connect(
        lambda _value: self.schedule_rename_preview()
    )
    self.rename_number_digits_spinbox.valueChanged.connect(
        lambda _value: self.schedule_rename_preview()
    )
    self.rename_smart_ocr_checkbox.toggled.connect(
        lambda _checked: self.schedule_rename_preview()
    )
    self.rename_smart_provider_combo.currentIndexChanged.connect(
        self.rename_smart_provider_changed
    )
    self.rename_smart_settings_button.clicked.connect(
        lambda: self.show_settings(self.rename_smart_provider_combo.currentData())
    )
    self.update_rename_rule_inputs()
    self.refresh_rename_file_list()
    return page


def current_rename_rule(self):
    return self.rename_rule_combo.currentData() or "replace"


def handle_rename_rule_changed(self, *_args):
    self.rename_smart_result = None
    self.rename_rule_primary_edit.clear()
    self.rename_rule_secondary_edit.clear()
    self.rename_rule_count_spinbox.setValue(1)
    self.update_rename_rule_inputs()
    if self.current_rename_rule() == "smart":
        self.refresh_rename_file_list()
    else:
        self.schedule_rename_preview()


def update_rename_rule_inputs(self):
    rule = self.current_rename_rule()
    count_rule = rule in ("trim_start", "trim_end")
    two_text_rule = rule == "replace"
    one_text_rule = rule in ("delete_text", "prefix", "suffix", "extension")
    smart_rule = rule == "smart"

    labels = {
        "replace": ("查找文字：", "替换为："),
        "delete_text": ("删除文字：", ""),
        "prefix": ("开头添加：", ""),
        "suffix": ("末尾添加：", ""),
        "extension": ("新扩展名：", ""),
        "trim_start": ("删除数量：", ""),
        "trim_end": ("删除数量：", ""),
    }
    primary_label, secondary_label = labels.get(rule, labels["replace"])
    self.rename_rule_primary_edit.setPlaceholderText("例如 pdf；仅修改扩展名，不转换文件格式" if rule == "extension" else "")
    self.rename_rule_primary_edit.setToolTip("仅修改文件名中的扩展名，不会转换文件内容或格式。" if rule == "extension" else "")
    self.rename_rule_primary_label.setText(primary_label)
    self.rename_rule_secondary_label.setText(secondary_label)

    self.rename_rule_primary_label.setVisible(one_text_rule or two_text_rule)
    self.rename_rule_primary_edit.setVisible(one_text_rule or two_text_rule)
    self.rename_rule_secondary_label.setVisible(two_text_rule)
    self.rename_rule_secondary_edit.setVisible(two_text_rule)
    self.rename_rule_count_label.setVisible(count_rule)
    self.rename_rule_count_spinbox.setVisible(count_rule)
    self.rename_number_widget.setVisible(not smart_rule)
    self.rename_smart_options_widget.setVisible(smart_rule)


def rename_options(self):
    rule = self.current_rename_rule()
    primary_text = self.rename_rule_primary_edit.text()
    return RenameOptions(
        find_text=primary_text if rule == "replace" else "",
        replace_text=(
            self.rename_rule_secondary_edit.text() if rule == "replace" else ""
        ),
        delete_text=primary_text if rule == "delete_text" else "",
        trim_start_count=(
            self.rename_rule_count_spinbox.value() if rule == "trim_start" else 0
        ),
        trim_end_count=(
            self.rename_rule_count_spinbox.value() if rule == "trim_end" else 0
        ),
        prefix=primary_text if rule == "prefix" else "",
        suffix=primary_text if rule == "suffix" else "",
        extension=primary_text if rule == "extension" else "",
        numbering_enabled=(
            self.rename_numbering_checkbox.isChecked() and rule != "smart"
        ),
        number_start=self.rename_number_start_spinbox.value(),
        number_digits=self.rename_number_digits_spinbox.value(),
    )


def schedule_rename_preview(self):
    self.rename_preview_valid = False
    self.rename_smart_result = None
    if self.current_rename_rule() == "smart":
        self.rename_preview_timer.stop()
        if self.rename_source_files:
            self.rename_status_label.setText("请点击“刷新预览”开始智能识别")
        self.update_rename_button_states()
        return
    self.rename_preview_timer.start()
    self.update_rename_button_states()


def refresh_rename_file_list(self, on_complete=None, force_sync=False):
    self.rename_preview_valid = False
    self.update_rename_button_states()
    files = tuple(self.rename_source_files)
    if self.current_rename_rule() == "smart":
        self.rename_smart_result = None
        self.display_rename_previews(preview_renames(files, RenameOptions()))
        self.rename_preview_valid = False
        if files:
            self.rename_status_label.setText("请点击“刷新预览”开始智能识别")
        self.update_rename_button_states()
        return True
    options = self.rename_options()
    if len(files) > RENAME_WARNING_COUNT and not force_sync:
        self.rename_status_label.setText(
            f"正在生成 {len(files):,} 个文件的改名预览…"
        )
        self.rename_execute_button.setEnabled(False)

        def preview_ready(previews):
            self.display_rename_previews(previews)
            if on_complete is not None:
                on_complete()

        return self.start_background_task(
            "正在生成改名预览",
            f"正在检查 {len(files):,} 个文件…",
            lambda _progress: preview_renames(files, options),
            preview_ready,
            lambda error: QMessageBox.critical(self, "预览失败", error),
            status_label=self.rename_status_label,
        )

    previews = preview_renames(files, options)
    self.display_rename_previews(previews)
    if on_complete is not None:
        on_complete()
    return True


def display_rename_previews(self, previews):
    self.rename_file_table.setUpdatesEnabled(False)
    self.rename_file_table.clear()
    self.rename_previews = list(previews)
    count = len(self.rename_source_files)
    self.rename_limit_label.setText(
        f"当前 {count:,} / {RENAME_MAX_COUNT:,} 个文件；"
        "处理数量越多，处理速度越慢，请酌情拆分任务"
    )
    try:
        if not self.rename_source_files:
            empty_item = QTreeWidgetItem(
                ["", "暂无文件，请添加需要改名的文件", "", "", ""]
            )
            empty_item.setFlags(Qt.NoItemFlags)
            self.rename_file_table.addTopLevelItem(empty_item)
            self.rename_status_label.setText("尚未添加文件")
        else:
            items = []
            for index, preview in enumerate(self.rename_previews, start=1):
                blank_preview = (
                    preview.blocked and "新文件名不能为空" in preview.message
                )
                target_name = (
                    preview.message
                    if blank_preview
                    else Path(preview.target_path).name
                )
                item = QTreeWidgetItem(
                    [
                        f"{index:03d}",
                        Path(preview.source_path).name,
                        target_name,
                        preview.status,
                        preview.source_path,
                    ]
                )
                item.setData(0, Qt.UserRole, preview.source_path)
                item.setTextAlignment(0, Qt.AlignCenter)
                item.setTextAlignment(3, Qt.AlignCenter)
                item.setToolTip(1, preview.source_path)
                item.setToolTip(2, preview.message or preview.target_path)
                item.setToolTip(4, preview.source_path)
                items.append(item)
            self.rename_file_table.addTopLevelItems(items)

            blocked_count = sum(
                1 for preview in self.rename_previews if preview.blocked
            )
            rename_count = sum(
                1 for preview in self.rename_previews if preview.will_rename
            )
            if blocked_count:
                self.rename_status_label.setText(
                    f"共 {len(self.rename_previews)} 个文件，{blocked_count} 个需要处理"
                )
            elif rename_count:
                self.rename_status_label.setText(
                    f"共 {len(self.rename_previews)} 个文件，{rename_count} 个将被改名"
                )
            else:
                self.rename_status_label.setText("当前规则不会改变文件名")
    finally:
        self.rename_file_table.setUpdatesEnabled(True)
    self.rename_preview_valid = True
    self.update_rename_button_states()


def blank_rename_previews(self):
    return [
        preview
        for preview in self.rename_previews
        if preview.blocked and "新文件名不能为空" in preview.message
    ]


def warn_blank_rename_preview(self):
    blank_previews = self.blank_rename_previews()
    if not blank_previews:
        return False

    preview_names = "\n".join(
        Path(preview.source_path).name for preview in blank_previews[:5]
    )
    more_text = ""
    if len(blank_previews) > 5:
        more_text = f"\n等 {len(blank_previews)} 个文件"
    QMessageBox.warning(
        self,
        "预览结果为空",
        "部分文件改名后会变成空白文件名，已阻止执行。\n\n"
        f"{preview_names}{more_text}\n\n"
        "请减少删除数量，或改用其他规则。",
    )
    return True


def refresh_rename_preview_with_warning(self):
    self.rename_preview_timer.stop()
    if self.current_rename_rule() == "smart":
        self.refresh_smart_rename_preview()
        return
    self.refresh_rename_file_list(on_complete=self.warn_blank_rename_preview)


def rename_smart_provider_changed(self):
    provider = self.rename_smart_provider_combo.currentData()
    try:
        select_provider(provider)
    except OSError as error:
        QMessageBox.warning(self, "无法保存选择", str(error))
    for combo in (
        self.document_ocr_provider_combo,
        self.batch_ocr_provider_combo,
    ):
        index = combo.findData(provider)
        if index >= 0 and combo.currentIndex() != index:
            combo.setCurrentIndex(index)
    self.schedule_rename_preview()


def refresh_smart_rename_preview(self):
    if not self.rename_source_files:
        QMessageBox.warning(self, "尚未添加文件", "请先添加需要改名的 PDF。")
        return
    use_ocr = self.rename_smart_ocr_checkbox.isChecked()
    provider = self.rename_smart_provider_combo.currentData()
    if use_ocr and not is_provider_configured(provider):
        QMessageBox.warning(
            self,
            "OCR 密钥未配置",
            "请先在软件设置中填写所选文字识别平台的密钥。",
        )
        return
    pdf_files = tuple(
        path for path in self.rename_source_files
        if Path(path).suffix.lower() == ".pdf"
    )
    if use_ocr and pdf_files:
        self.start_background_task(
            "检查扫描页",
            f"正在检查 {len(pdf_files)} 个 PDF 是否包含扫描页…",
            lambda progress: inspect_pdf_files(pdf_files, progress),
            lambda inspections: self.confirm_smart_ocr_and_start(
                inspections,
                provider,
            ),
            total=len(pdf_files),
            status_label=self.rename_status_label,
        )
        return
    self.run_smart_rename_preview(False, provider)


def confirm_smart_ocr_and_start(self, inspections, provider):
    scanned = [preview for preview in inspections if preview.scanned_pages]
    if scanned:
        page_count = sum(len(preview.scanned_pages) for preview in scanned)
        details = "\n".join(
            f"{Path(preview.source_file).name}：第 "
            f"{', '.join(map(str, preview.scanned_pages))} 页"
            for preview in scanned[:8]
        )
        if len(scanned) > 8:
            details += f"\n另有 {len(scanned) - 8} 个文件"
        answer = QMessageBox.question(
            self,
            "确认使用云 OCR",
            f"共 {page_count} 个扫描页会发送给 {PROVIDER_LABELS.get(provider, provider)}：\n\n"
            f"{details}\n\n有文字的页面仍在本机读取。是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self.rename_status_label.setText("已取消云 OCR 智能命名")
            return
    self.run_smart_rename_preview(True, provider)


def run_smart_rename_preview(self, use_ocr, provider):
    files = tuple(self.rename_source_files)
    self.rename_status_label.setText(f"正在智能识别 {len(files)} 个文件…")
    self.start_background_task(
        "智能识别命名",
        f"正在识别 {len(files)} 个文件并检查重复内容…",
        lambda progress: suggest_smart_renames(
            files,
            use_ocr=use_ocr,
            provider_name=provider,
            progress_callback=progress,
        ),
        self.smart_rename_preview_completed,
        total=len(files),
        status_label=self.rename_status_label,
    )


def smart_rename_preview_completed(self, result):
    self.rename_smart_result = result
    self.display_rename_previews(result.previews)
    duplicate_count = sum(bool(item.duplicate_of) for item in result.suggestions)
    unchanged_count = sum(not preview.will_rename for preview in result.previews)
    rename_count = sum(preview.will_rename for preview in result.previews)
    blocked_count = sum(preview.blocked for preview in result.previews)
    self.rename_status_label.setText(
        f"智能预览完成：将改名 {rename_count} 个，保持原名 {unchanged_count} 个，"
        f"重复内容 {duplicate_count} 个，冲突 {blocked_count} 个"
    )
    self.rename_preview_valid = True
    self.update_rename_button_states()


def update_rename_button_states(self):
    has_files = bool(self.rename_source_files)
    has_selection = any(
        item.data(0, Qt.UserRole)
        for item in self.rename_file_table.selectedItems()
    )
    can_rename = (
        has_files
        and self.rename_preview_valid
        and not any(preview.blocked for preview in self.rename_previews)
        and any(preview.will_rename for preview in self.rename_previews)
    )
    self.rename_delete_button.setEnabled(has_selection)
    self.rename_clear_button.setEnabled(has_files)
    self.rename_preview_button.setEnabled(has_files)
    self.rename_execute_button.setEnabled(can_rename)
    self.rename_open_log_button.setEnabled(
        bool(self.rename_last_log_file and Path(self.rename_last_log_file).exists())
    )


def add_rename_paths(self, paths):
    existing = set(self.rename_source_files)
    candidates = []
    for path in paths:
        normalized = os.path.abspath(path)
        if normalized not in existing and Path(normalized).is_file():
            candidates.append(normalized)
            existing.add(normalized)
    if not candidates:
        return False
    if not self.confirm_large_addition(
        "文件",
        len(self.rename_source_files),
        len(candidates),
        RENAME_WARNING_COUNT,
        RENAME_MAX_COUNT,
    ):
        return False
    self.rename_source_files.extend(candidates)
    self.refresh_rename_file_list()
    return True


def add_rename_files(self):
    filenames, _ = QFileDialog.getOpenFileNames(
        self,
        "选择需要改名的文件",
        self.dialog_folder("open"),
        "所有文件 (*)",
    )
    if filenames:
        self.remember_dialog_folder("open", filenames[0])
        self.add_rename_paths(filenames)


def add_rename_folder(self):
    folder = QFileDialog.getExistingDirectory(
        self,
        "选择需要批量改名的文件夹",
        self.dialog_folder("open"),
        QFileDialog.ShowDirsOnly,
    )
    if not folder:
        return
    self.remember_dialog_folder("open", folder)
    try:
        files = discover_rename_files(folder)
    except OSError as error:
        QMessageBox.critical(self, "无法读取文件夹", str(error))
        return
    if not files:
        QMessageBox.warning(self, "未找到文件", "所选文件夹中没有找到可改名文件。")
        return
    self.add_rename_paths(files)


def delete_selected_rename_files(self):
    selected = {
        item.data(0, Qt.UserRole)
        for item in self.rename_file_table.selectedItems()
        if item.data(0, Qt.UserRole)
    }
    if not selected:
        return
    self.rename_source_files = [
        filename for filename in self.rename_source_files if filename not in selected
    ]
    self.refresh_rename_file_list()


def clear_rename_files(self):
    if not self.rename_source_files:
        return
    if not self.confirm_list_change("是否清空待改名文件列表"):
        return
    self.rename_source_files = []
    self.rename_previews = []
    self.refresh_rename_file_list()


def show_rename_complete_message(self, result):
    message = QMessageBox(self)
    message.setWindowTitle("批量改名完成")
    message.setIcon(
        QMessageBox.Warning if result.failed_count else QMessageBox.Information
    )
    message.setText(
        f"成功 {result.success_count} 个，跳过 {result.skipped_count} 个，"
        f"失败 {result.failed_count} 个"
    )
    message.setInformativeText(f"日志文件：\n{result.log_file}")
    failures = [
        f"{Path(action.source_path).name}：{action.error}"
        for action in result.actions
        if action.status == "失败"
    ]
    if failures:
        message.setDetailedText("\n".join(failures))
    open_button = message.addButton("打开日志", QMessageBox.ActionRole)
    ok_button = message.addButton("确定", QMessageBox.AcceptRole)
    for button in (ok_button, open_button):
        button.setFixedSize(112, 36)
    message.setDefaultButton(ok_button)
    message.exec()
    if message.clickedButton() == open_button:
        self.open_output_file(result.log_file)


def rename_files(self):
    if not self.rename_source_files:
        QMessageBox.warning(self, "尚未添加文件", "请先添加需要改名的文件。")
        return
    if self.rename_preview_timer.isActive() or not self.rename_preview_valid:
        QMessageBox.information(
            self,
            "预览正在更新",
            "改名预览正在更新，请稍后再开始改名。",
        )
        return
    self.rename_preview_timer.stop()
    if self.warn_blank_rename_preview():
        return
    blocked = [preview for preview in self.rename_previews if preview.blocked]
    if blocked:
        QMessageBox.warning(
            self,
            "预览中有问题",
            "请先处理重名、目标已存在或文件名不合法的问题。",
        )
        return
    rename_count = sum(1 for preview in self.rename_previews if preview.will_rename)
    if not rename_count:
        QMessageBox.information(self, "无需改名", "当前规则不会改变文件名。")
        return
    if not self.confirm_list_change(f"即将改名 {rename_count} 个文件，是否继续"):
        return

    previews = tuple(self.rename_previews)
    smart_metadata = (
        self.rename_smart_result.metadata_by_source
        if self.current_rename_rule() == "smart" and self.rename_smart_result
        else None
    )

    def rename_completed(result):
        self.rename_last_log_file = result.log_file
        self.rename_log_path_edit.setText(result.log_file)
        self.rename_log_path_edit.setToolTip(result.log_file)
        self.rename_source_files = [
            action.target_path if action.status == "成功" else action.source_path
            for action in result.actions
        ]
        self.show_rename_complete_message(result)
        self.refresh_rename_file_list()

    self.start_background_task(
        "正在批量改名",
        f"准备处理 {rename_count} 个文件…",
        lambda progress: apply_renames(
            previews,
            progress_callback=progress,
            metadata_by_source=smart_metadata,
        ),
        rename_completed,
        lambda error: QMessageBox.critical(self, "改名失败", error),
        total=len(previews),
        status_label=self.rename_status_label,
    )

