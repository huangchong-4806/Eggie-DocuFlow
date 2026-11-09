"""PDF toolbox page.

Functions are bound onto ExcelMergerWindow and use app.py globals,
so tests can keep patching Qt and tool names on the app module.
"""

def create_pdf_page(self):
    page = QWidget()
    page.setObjectName("pdfPage")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(22, 18, 22, 18)
    layout.setSpacing(14)

    title = QLabel("PDF 工具箱")
    title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    title.setFont(QFont("PingFang SC", 24, QFont.Bold))
    title.setProperty("role", "title")
    layout.addWidget(title)

    subtitle = QLabel("页面编辑与内容编辑共用文档 · 涂黑脱敏、水印、页码均在本机完成")
    subtitle.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    subtitle.setProperty("role", "subtitle")
    layout.addWidget(subtitle)

    self.pdf_workspace = PdfWorkspaceWidget(self)
    self.pdf_workspace.close_ready.connect(self.close)
    self.pdf_tabs = self.pdf_workspace.module_tabs
    more = QWidget()
    more_layout = QVBoxLayout(more)
    more_hint = QLabel("这里独立选择文件；如需处理编辑后的文档，请先另存 PDF，再选择该副本。")
    more_hint.setWordWrap(True)
    more_hint.setProperty("role", "hint")
    more_layout.addWidget(more_hint)
    self.pdf_more_tabs = QTabWidget()
    self.pdf_more_tabs.addTab(self.create_pdf_compress_tab(), "PDF 压缩")
    self.pdf_more_tabs.addTab(self.create_pdf_convert_tab(), "图片 / PDF 互转")
    self.pdf_more_tabs.addTab(self.create_pdf_security_tab(), "PDF 密码")
    self.pdf_more_tabs.addTab(self.create_searchable_pdf_tab(), "可搜索 PDF")
    self.pdf_more_tabs.addTab(self.create_pdf_compare_tab(), "文字对比")
    for index in (0, 2, 3, 4):
        contain_page_form(self.pdf_more_tabs.widget(index), 0, 920)
    more_layout.addWidget(self.pdf_more_tabs, 1)
    self.pdf_tabs.addTab(more, "独立工具")
    layout.addWidget(self.pdf_workspace, 1)

    self.update_pdf_button_states()
    return page


def create_pdf_compress_tab(self):
    tab = QWidget()
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(12, 14, 12, 12)
    layout.setSpacing(12)

    source_group = QGroupBox("选择 PDF")
    source_layout = QHBoxLayout(source_group)
    source_layout.setContentsMargins(12, 14, 12, 10)
    self.pdf_compress_source_edit = QLineEdit()
    self.pdf_compress_source_edit.setReadOnly(True)
    self.pdf_compress_source_edit.setPlaceholderText("请选择需要压缩的 PDF")
    self.pdf_choose_compress_button = QPushButton("选择 PDF")
    self.pdf_choose_compress_button.setProperty("variant", "accent")
    source_layout.addWidget(self.pdf_compress_source_edit, 1)
    source_layout.addWidget(self.pdf_choose_compress_button)
    layout.addWidget(source_group)

    preset_group = QGroupBox("压缩程度")
    preset_layout = QHBoxLayout(preset_group)
    preset_layout.setContentsMargins(12, 14, 12, 10)
    self.pdf_compress_preset_combo = SelectionComboBox()
    for key in ("clear", "standard", "small"):
        self.pdf_compress_preset_combo.addItem(COMPRESSION_PRESETS[key]["label"], key)
    self.pdf_compress_preset_combo.setCurrentIndex(1)
    self.pdf_compress_size_label = QLabel("原始大小：-    预计压缩后：-    预计缩小：-")
    self.pdf_compress_size_label.setProperty("role", "hint")
    preset_layout.addWidget(QLabel("压缩程度："))
    preset_layout.addWidget(self.pdf_compress_preset_combo)
    preset_layout.addWidget(self.pdf_compress_size_label, 1)
    layout.addWidget(preset_group)

    output_group = QGroupBox("保存设置")
    output_layout = QHBoxLayout(output_group)
    output_layout.setContentsMargins(12, 14, 12, 10)
    self.pdf_compress_output_folder_edit = QLineEdit()
    self.pdf_compress_output_folder_edit.setReadOnly(True)
    self.pdf_choose_compress_output_button = QPushButton("选择文件夹")
    self.pdf_compress_output_name_edit = QLineEdit()
    self.pdf_compress_output_name_edit.setPlaceholderText(default_output_name("PDF压缩结果"))
    output_layout.addWidget(QLabel("文件夹："))
    output_layout.addWidget(self.pdf_compress_output_folder_edit, 2)
    output_layout.addWidget(self.pdf_choose_compress_output_button)
    output_layout.addWidget(QLabel("文件名："))
    output_layout.addWidget(self.pdf_compress_output_name_edit, 1)
    layout.addWidget(output_group)

    self.pdf_compress_button = QPushButton("开始压缩")
    self.pdf_compress_button.setMinimumHeight(38)
    self.pdf_compress_button.setProperty("variant", "primary")
    layout.addWidget(self.pdf_compress_button, 0, Qt.AlignRight)
    self.pdf_compress_status_label = QLabel("尚未选择 PDF")
    self.pdf_compress_status_label.setProperty("role", "status")
    layout.addWidget(self.pdf_compress_status_label)
    layout.addStretch(1)

    self.pdf_choose_compress_button.clicked.connect(self.choose_pdf_compress_source)
    self.pdf_choose_compress_output_button.clicked.connect(
        self.choose_pdf_compress_output_folder
    )
    self.pdf_compress_preset_combo.currentIndexChanged.connect(
        self.update_pdf_compress_estimate
    )
    self.pdf_compress_button.clicked.connect(self.compress_selected_pdf)
    return tab


def create_pdf_convert_tab(self):
    tab = QWidget()
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(12, 14, 12, 12)
    layout.setSpacing(10)

    mode_layout = QHBoxLayout()
    self.pdf_image_mode_button = QPushButton("图片转 PDF")
    self.pdf_export_mode_button = QPushButton("PDF 转图片")
    for button in (self.pdf_image_mode_button, self.pdf_export_mode_button):
        button.setProperty("variant", "mode")
        button.setCheckable(True)
        button.setMinimumHeight(34)
        mode_layout.addWidget(button)
    mode_layout.addStretch()
    layout.addLayout(mode_layout)

    self.pdf_convert_stack = QStackedWidget()
    layout.addWidget(self.pdf_convert_stack, 1)

    image_group = QGroupBox("图片转 PDF")
    image_layout = QVBoxLayout(image_group)
    image_layout.setContentsMargins(12, 14, 12, 10)
    image_button_layout = QHBoxLayout()
    self.pdf_add_images_button = QPushButton("添加图片")
    self.pdf_add_image_folder_button = QPushButton("添加文件夹")
    self.pdf_delete_checked_images_button = QPushButton("移出列表")
    self.pdf_delete_checked_images_button.setToolTip("从待处理列表移除，不删除原文件")
    self.pdf_clear_images_button = QPushButton("清空列表")
    self.pdf_add_images_button.setProperty("variant", "accent")
    self.pdf_add_image_folder_button.setProperty("variant", "accent")
    self.pdf_delete_checked_images_button.setProperty("variant", "danger")
    image_button_layout.addWidget(self.pdf_add_images_button)
    image_button_layout.addWidget(self.pdf_add_image_folder_button)
    image_button_layout.addWidget(self.pdf_delete_checked_images_button)
    image_button_layout.addWidget(self.pdf_clear_images_button)
    image_button_layout.addStretch()
    image_layout.addLayout(image_button_layout)
    self.pdf_image_limit_label = QLabel(
        "当前 0 / 300 张；处理数量越多，处理速度越慢，"
        "请酌情拆分任务"
    )
    self.pdf_image_limit_label.setProperty("role", "hint")
    image_layout.addWidget(self.pdf_image_limit_label)
    self.pdf_image_scroll = QScrollArea()
    self.pdf_image_scroll.setWidgetResizable(True)
    self.pdf_image_board = PdfImageBoard(self)
    self.pdf_image_scroll.setWidget(self.pdf_image_board)
    image_layout.addWidget(self.pdf_image_scroll, 1)
    self.pdf_image_output_folder_edit = QLineEdit()
    self.pdf_image_output_folder_edit.setReadOnly(True)
    self.pdf_image_output_name_edit = QLineEdit()
    self.pdf_image_output_name_edit.setPlaceholderText(default_output_name("图片合成PDF"))
    self.pdf_choose_image_output_button = QPushButton("选择文件夹")
    image_layout.addWidget(QLabel("保存文件夹："))
    image_output_row = QHBoxLayout()
    image_output_row.addWidget(self.pdf_image_output_folder_edit, 1)
    image_output_row.addWidget(self.pdf_choose_image_output_button)
    image_layout.addLayout(image_output_row)
    image_layout.addWidget(QLabel("保存文件名："))
    image_layout.addWidget(self.pdf_image_output_name_edit)
    self.pdf_images_to_pdf_button = QPushButton("合成 PDF")
    self.pdf_images_to_pdf_button.setMinimumHeight(44)
    self.pdf_images_to_pdf_button.setProperty("variant", "primary")
    image_layout.addWidget(self.pdf_images_to_pdf_button, 0, Qt.AlignRight)
    self.pdf_image_status_label = QLabel("尚未添加图片")
    self.pdf_image_status_label.setProperty("role", "status")
    image_layout.addWidget(self.pdf_image_status_label)
    self.pdf_convert_stack.addWidget(image_group)

    export_group = QGroupBox("PDF 转图片")
    export_layout = QVBoxLayout(export_group)
    export_layout.setContentsMargins(12, 14, 12, 10)
    export_source_button_layout = QHBoxLayout()
    self.pdf_choose_export_source_button = QPushButton("添加 PDF")
    self.pdf_choose_export_source_button.setProperty("variant", "accent")
    self.pdf_add_export_folder_button = QPushButton("添加文件夹")
    self.pdf_add_export_folder_button.setProperty("variant", "accent")
    self.pdf_delete_export_source_button = QPushButton("移出列表")
    self.pdf_delete_export_source_button.setToolTip("从待处理列表移除，不删除原文件")
    self.pdf_delete_export_source_button.setProperty("variant", "danger")
    self.pdf_clear_export_sources_button = QPushButton("清空列表")
    export_source_button_layout.addWidget(self.pdf_choose_export_source_button)
    export_source_button_layout.addWidget(self.pdf_add_export_folder_button)
    export_source_button_layout.addWidget(self.pdf_delete_export_source_button)
    export_source_button_layout.addWidget(self.pdf_clear_export_sources_button)
    export_source_button_layout.addStretch(1)
    self.pdf_export_source_tree = QTreeWidget()
    self.pdf_export_source_tree.setHeaderLabels(["PDF 文件", "所在位置"])
    self.pdf_export_source_tree.setRootIsDecorated(False)
    self.pdf_export_source_tree.setAlternatingRowColors(True)
    self.pdf_export_source_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
    self.pdf_export_source_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
    self.pdf_export_source_tree.setMinimumHeight(150)
    self.pdf_export_source_tree.header().setSectionResizeMode(
        0, QHeaderView.ResizeToContents
    )
    self.pdf_export_source_tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
    self.pdf_export_output_folder_edit = QLineEdit()
    self.pdf_export_output_folder_edit.setReadOnly(True)
    self.pdf_choose_export_output_button = QPushButton("选择文件夹")
    self.pdf_export_format_combo = SelectionComboBox()
    self.pdf_export_format_combo.addItems(["JPG", "PNG"])
    self.pdf_export_quality_combo = SelectionComboBox()
    self.pdf_export_quality_combo.addItem("普通（150 DPI）", 150)
    self.pdf_export_quality_combo.addItem("高清（300 DPI，推荐）", 300)
    self.pdf_export_quality_combo.addItem("超清（450 DPI，处理较慢）", 450)
    self.pdf_export_quality_combo.setCurrentIndex(1)
    self.pdf_export_button = QPushButton("开始转换")
    self.pdf_export_button.setMinimumHeight(44)
    self.pdf_export_button.setProperty("variant", "primary")
    export_layout.addLayout(export_source_button_layout)
    export_layout.addWidget(self.pdf_export_source_tree, 1)
    export_output_layout = QHBoxLayout()
    export_output_layout.addWidget(QLabel("保存文件夹："))
    export_output_layout.addWidget(self.pdf_export_output_folder_edit, 1)
    export_output_layout.addWidget(self.pdf_choose_export_output_button)
    export_layout.addLayout(export_output_layout)
    export_option_layout = QHBoxLayout()
    export_option_layout.addWidget(QLabel("图片格式："))
    export_option_layout.addWidget(self.pdf_export_format_combo)
    export_option_layout.addSpacing(18)
    export_option_layout.addWidget(QLabel("图片清晰度："))
    export_option_layout.addWidget(self.pdf_export_quality_combo)
    export_option_layout.addStretch(1)
    export_layout.addLayout(export_option_layout)
    export_layout.addWidget(self.pdf_export_button, 0, Qt.AlignRight)
    self.pdf_export_status_label = QLabel("尚未选择 PDF")
    self.pdf_export_status_label.setProperty("role", "status")
    export_layout.addWidget(self.pdf_export_status_label)
    self.pdf_convert_stack.addWidget(export_group)

    self.pdf_image_mode_button.clicked.connect(lambda: self.show_pdf_convert_mode(0))
    self.pdf_export_mode_button.clicked.connect(lambda: self.show_pdf_convert_mode(1))
    self.pdf_add_images_button.clicked.connect(self.add_pdf_images)
    self.pdf_add_image_folder_button.clicked.connect(self.add_pdf_image_folder)
    self.pdf_delete_checked_images_button.clicked.connect(self.delete_checked_pdf_images)
    self.pdf_clear_images_button.clicked.connect(self.clear_pdf_images)
    self.pdf_choose_image_output_button.clicked.connect(self.choose_pdf_image_output_folder)
    self.pdf_images_to_pdf_button.clicked.connect(self.convert_images_to_pdf)
    self.pdf_choose_export_source_button.clicked.connect(self.choose_pdf_export_source)
    self.pdf_add_export_folder_button.clicked.connect(
        self.choose_pdf_export_source_folder
    )
    self.pdf_delete_export_source_button.clicked.connect(
        self.delete_selected_pdf_export_sources
    )
    self.pdf_clear_export_sources_button.clicked.connect(self.clear_pdf_export_sources)
    self.pdf_export_source_tree.itemSelectionChanged.connect(
        self.update_pdf_button_states
    )
    self.pdf_choose_export_output_button.clicked.connect(self.choose_pdf_export_output_folder)
    self.pdf_export_button.clicked.connect(self.export_pdf_to_images)
    self.show_pdf_convert_mode(0)
    return tab


def create_pdf_security_tab(self):
    tab = QWidget()
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(12, 14, 12, 12)
    layout.setSpacing(12)

    source_group = QGroupBox("选择 PDF")
    source_layout = QHBoxLayout(source_group)
    self.pdf_security_source_edit = QLineEdit()
    self.pdf_security_source_edit.setReadOnly(True)
    self.pdf_security_source_edit.setPlaceholderText("请选择需要设置或移除密码的 PDF")
    self.pdf_choose_security_source_button = QPushButton("选择 PDF")
    self.pdf_choose_security_source_button.setProperty("variant", "accent")
    source_layout.addWidget(self.pdf_security_source_edit, 1)
    source_layout.addWidget(self.pdf_choose_security_source_button)
    layout.addWidget(source_group)

    password_group = QGroupBox("密码设置")
    password_layout = QFormLayout(password_group)
    password_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    password_layout.setVerticalSpacing(12)
    mode_row = QHBoxLayout()
    self.pdf_security_mode_combo = SelectionComboBox()
    self.pdf_security_mode_combo.addItem("设置打开密码", "set")
    self.pdf_security_mode_combo.addItem("移除已有密码", "remove")
    mode_row.addWidget(QLabel("操作："))
    mode_row.addWidget(self.pdf_security_mode_combo)
    mode_row.addStretch(1)
    password_layout.addRow(mode_row)
    self.pdf_source_password_edit = QLineEdit()
    self.pdf_source_password_edit.setEchoMode(QLineEdit.Password)
    self.pdf_source_password_edit.setPlaceholderText("原密码；未加密 PDF 可留空")
    self.pdf_new_password_edit = QLineEdit()
    self.pdf_new_password_edit.setEchoMode(QLineEdit.Password)
    self.pdf_new_password_edit.setPlaceholderText("新密码，至少 6 个字符")
    self.pdf_confirm_password_edit = QLineEdit()
    self.pdf_confirm_password_edit.setEchoMode(QLineEdit.Password)
    self.pdf_confirm_password_edit.setPlaceholderText("再次输入新密码")
    password_layout.addRow("原密码：", self.pdf_source_password_edit)
    self.pdf_new_password_label = QLabel("新密码：")
    self.pdf_confirm_password_label = QLabel("确认新密码：")
    password_layout.addRow(self.pdf_new_password_label, self.pdf_new_password_edit)
    password_layout.addRow(self.pdf_confirm_password_label, self.pdf_confirm_password_edit)
    privacy = QLabel("密码只在当前操作中使用，不会保存，也不会写入日志。")
    privacy.setProperty("role", "hint")
    privacy.setWordWrap(True)
    password_layout.addRow(privacy)
    layout.addWidget(password_group)

    output_group = QGroupBox("保存设置")
    output_layout = QHBoxLayout(output_group)
    self.pdf_security_output_folder_edit = QLineEdit()
    self.pdf_security_output_folder_edit.setReadOnly(True)
    self.pdf_choose_security_output_button = QPushButton("选择文件夹")
    self.pdf_security_output_name_edit = QLineEdit()
    output_layout.addWidget(QLabel("文件夹："))
    output_layout.addWidget(self.pdf_security_output_folder_edit, 2)
    output_layout.addWidget(self.pdf_choose_security_output_button)
    output_layout.addWidget(QLabel("文件名："))
    output_layout.addWidget(self.pdf_security_output_name_edit, 1)
    layout.addWidget(output_group)

    self.pdf_security_start_button = QPushButton("生成新 PDF")
    self.pdf_security_start_button.setMinimumHeight(38)
    self.pdf_security_start_button.setProperty("variant", "primary")
    self.pdf_security_status_label = QLabel("尚未选择 PDF")
    self.pdf_security_status_label.setProperty("role", "status")
    layout.addWidget(self.pdf_security_start_button, 0, Qt.AlignRight)
    layout.addWidget(self.pdf_security_status_label)
    layout.addStretch(1)

    self.pdf_choose_security_source_button.clicked.connect(self.choose_pdf_security_source)
    self.pdf_choose_security_output_button.clicked.connect(self.choose_pdf_security_output_folder)
    self.pdf_security_mode_combo.currentIndexChanged.connect(self.update_pdf_security_mode)
    self.pdf_security_start_button.clicked.connect(self.process_pdf_security)
    self.update_pdf_security_mode()
    return tab


def create_searchable_pdf_tab(self):
    tab = QWidget()
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(12, 14, 12, 12)
    layout.setSpacing(12)

    source_group = QGroupBox("选择 PDF")
    source_layout = QHBoxLayout(source_group)
    self.pdf_searchable_source_edit = QLineEdit()
    self.pdf_searchable_source_edit.setReadOnly(True)
    self.pdf_searchable_source_edit.setPlaceholderText("请选择需要生成可搜索副本的 PDF")
    self.pdf_choose_searchable_source_button = QPushButton("选择 PDF")
    self.pdf_choose_searchable_source_button.setProperty("variant", "accent")
    source_layout.addWidget(self.pdf_searchable_source_edit, 1)
    source_layout.addWidget(self.pdf_choose_searchable_source_button)
    layout.addWidget(source_group)

    ocr_group = QGroupBox("扫描页识别")
    ocr_layout = QHBoxLayout(ocr_group)
    self.pdf_searchable_provider_combo = SelectionComboBox()
    for provider_key, provider_label in PROVIDER_LABELS.items():
        self.pdf_searchable_provider_combo.addItem(provider_label, provider_key)
    searchable_provider_index = self.pdf_searchable_provider_combo.findData(selected_provider())
    self.pdf_searchable_provider_combo.setCurrentIndex(max(0, searchable_provider_index))
    self.pdf_searchable_settings_button = QPushButton("设置")
    self.pdf_searchable_inspection_label = QLabel("选择 PDF 后显示需要 OCR 的页面")
    self.pdf_searchable_inspection_label.setProperty("role", "hint")
    ocr_layout.addWidget(QLabel("文字识别平台："))
    ocr_layout.addWidget(self.pdf_searchable_provider_combo)
    ocr_layout.addWidget(self.pdf_searchable_settings_button)
    ocr_layout.addWidget(self.pdf_searchable_inspection_label, 1)
    layout.addWidget(ocr_group)

    output_group = QGroupBox("保存设置")
    output_layout = QHBoxLayout(output_group)
    self.pdf_searchable_output_folder_edit = QLineEdit()
    self.pdf_searchable_output_folder_edit.setReadOnly(True)
    self.pdf_choose_searchable_output_button = QPushButton("选择文件夹")
    self.pdf_searchable_output_name_edit = QLineEdit()
    output_layout.addWidget(QLabel("文件夹："))
    output_layout.addWidget(self.pdf_searchable_output_folder_edit, 2)
    output_layout.addWidget(self.pdf_choose_searchable_output_button)
    output_layout.addWidget(QLabel("文件名："))
    output_layout.addWidget(self.pdf_searchable_output_name_edit, 1)
    layout.addWidget(output_group)

    hint = QLabel("原页面图像会保留；仅扫描页在确认后调用云 OCR，并加入可搜索文字层。")
    hint.setProperty("role", "hint")
    hint.setWordWrap(True)
    layout.addWidget(hint)
    self.pdf_searchable_start_button = QPushButton("生成可搜索 PDF")
    self.pdf_searchable_start_button.setMinimumHeight(38)
    self.pdf_searchable_start_button.setProperty("variant", "primary")
    self.pdf_searchable_status_label = QLabel("尚未选择 PDF")
    self.pdf_searchable_status_label.setProperty("role", "status")
    layout.addWidget(self.pdf_searchable_start_button, 0, Qt.AlignRight)
    layout.addWidget(self.pdf_searchable_status_label)
    layout.addStretch(1)

    self.pdf_choose_searchable_source_button.clicked.connect(self.choose_searchable_pdf_source)
    self.pdf_choose_searchable_output_button.clicked.connect(self.choose_searchable_pdf_output_folder)
    self.pdf_searchable_settings_button.clicked.connect(
        lambda: self.show_settings(self.pdf_searchable_provider_combo.currentData())
    )
    self.pdf_searchable_provider_combo.currentIndexChanged.connect(
        self.pdf_searchable_provider_changed
    )
    self.pdf_searchable_start_button.clicked.connect(self.create_searchable_pdf)
    self.update_searchable_pdf_button()
    return tab


def create_pdf_compare_tab(self):
    tab = QWidget()
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(12, 14, 12, 12)
    layout.setSpacing(12)

    source_group = QGroupBox("选择两份 PDF")
    source_layout = QVBoxLayout(source_group)
    left_row = QHBoxLayout()
    self.pdf_compare_left_edit = QLineEdit()
    self.pdf_compare_left_edit.setReadOnly(True)
    self.pdf_compare_left_edit.setPlaceholderText("第一份 PDF")
    self.pdf_choose_compare_left_button = QPushButton("选择第一份")
    left_row.addWidget(self.pdf_compare_left_edit, 1)
    left_row.addWidget(self.pdf_choose_compare_left_button)
    right_row = QHBoxLayout()
    self.pdf_compare_right_edit = QLineEdit()
    self.pdf_compare_right_edit.setReadOnly(True)
    self.pdf_compare_right_edit.setPlaceholderText("第二份 PDF")
    self.pdf_choose_compare_right_button = QPushButton("选择第二份")
    right_row.addWidget(self.pdf_compare_right_edit, 1)
    right_row.addWidget(self.pdf_choose_compare_right_button)
    source_layout.addLayout(left_row)
    source_layout.addLayout(right_row)
    layout.addWidget(source_group)

    output_group = QGroupBox("报告保存位置")
    output_layout = QHBoxLayout(output_group)
    self.pdf_compare_output_folder_edit = QLineEdit()
    self.pdf_compare_output_folder_edit.setReadOnly(True)
    self.pdf_choose_compare_output_button = QPushButton("选择文件夹")
    self.pdf_compare_output_name_edit = QLineEdit(default_output_name("PDF文字对比", ".html"))
    output_layout.addWidget(QLabel("文件夹："))
    output_layout.addWidget(self.pdf_compare_output_folder_edit, 2)
    output_layout.addWidget(self.pdf_choose_compare_output_button)
    output_layout.addWidget(QLabel("文件名："))
    output_layout.addWidget(self.pdf_compare_output_name_edit, 1)
    layout.addWidget(output_group)

    hint = QLabel("对比只在本机完成；扫描 PDF 请先转换成可搜索 PDF。")
    hint.setProperty("role", "hint")
    layout.addWidget(hint)
    action_layout = QHBoxLayout()
    self.pdf_compare_start_button = QPushButton("生成文字对比报告")
    self.pdf_compare_start_button.setMinimumHeight(38)
    self.pdf_compare_start_button.setProperty("variant", "primary")
    self.pdf_compare_open_button = QPushButton("打开报告")
    self.pdf_compare_open_button.setMinimumHeight(38)
    action_layout.addStretch(1)
    action_layout.addWidget(self.pdf_compare_start_button)
    action_layout.addWidget(self.pdf_compare_open_button)
    layout.addLayout(action_layout)
    self.pdf_compare_status_label = QLabel("尚未选择两份 PDF")
    self.pdf_compare_status_label.setProperty("role", "status")
    layout.addWidget(self.pdf_compare_status_label)
    layout.addStretch(1)

    self.pdf_choose_compare_left_button.clicked.connect(lambda: self.choose_pdf_compare_source("left"))
    self.pdf_choose_compare_right_button.clicked.connect(lambda: self.choose_pdf_compare_source("right"))
    self.pdf_choose_compare_output_button.clicked.connect(self.choose_pdf_compare_output_folder)
    self.pdf_compare_start_button.clicked.connect(self.create_pdf_compare_report)
    self.pdf_compare_open_button.clicked.connect(
        lambda: self.open_output_file(self.pdf_compare_result_file)
    )
    self.update_pdf_compare_buttons()
    return tab


def update_pdf_button_states(self):
    if hasattr(self, "pdf_compress_button"):
        self.pdf_compress_button.setEnabled(
            bool(self.pdf_compress_source_file)
            and bool(self.pdf_compress_output_folder_edit.text())
        )
    if hasattr(self, "pdf_images_to_pdf_button"):
        self.pdf_images_to_pdf_button.setEnabled(
            bool(self.pdf_image_source_files)
            and bool(self.pdf_image_output_folder_edit.text())
        )
    if hasattr(self, "pdf_delete_checked_images_button"):
        self.pdf_delete_checked_images_button.setEnabled(
            bool(self.selected_pdf_image_cards())
        )
    if hasattr(self, "pdf_export_button"):
        self.pdf_export_button.setEnabled(
            bool(self.pdf_export_source_files)
            and bool(self.pdf_export_output_folder_edit.text())
        )
        self.pdf_delete_export_source_button.setEnabled(
            bool(self.pdf_export_source_tree.selectedItems())
        )
        self.pdf_clear_export_sources_button.setEnabled(
            bool(self.pdf_export_source_files)
        )


def choose_pdf_security_source(self):
    filename, _ = QFileDialog.getOpenFileName(
        self,
        "选择需要设置或移除密码的 PDF",
        self.dialog_folder("open"),
        "PDF 文件 (*.pdf)",
    )
    if not filename:
        return
    self.remember_dialog_folder("open", filename)
    self.pdf_security_source_file = os.path.abspath(filename)
    self.pdf_security_source_edit.setText(self.pdf_security_source_file)
    self.pdf_security_source_edit.setToolTip(self.pdf_security_source_file)
    self.pdf_security_output_folder = str(Path(filename).parent / "output")
    self.pdf_security_output_folder_edit.setText(self.pdf_security_output_folder)
    self.pdf_security_status_label.setText("已选择 PDF，密码不会被保存")
    self.update_pdf_security_mode()


def choose_pdf_security_output_folder(self):
    folder = QFileDialog.getExistingDirectory(
        self,
        "选择 PDF 密码处理结果保存文件夹",
        self.dialog_folder("save", self.pdf_security_output_folder),
        QFileDialog.ShowDirsOnly,
    )
    if not folder:
        return
    self.pdf_security_output_folder = os.path.abspath(folder)
    self.remember_dialog_folder("save", folder)
    self.pdf_security_output_folder_edit.setText(self.pdf_security_output_folder)
    self.update_pdf_security_mode()


def update_pdf_security_mode(self):
    setting_password = self.pdf_security_mode_combo.currentData() == "set"
    for widget in (
        self.pdf_new_password_label,
        self.pdf_new_password_edit,
        self.pdf_confirm_password_label,
        self.pdf_confirm_password_edit,
    ):
        widget.setVisible(setting_password)
    if self.pdf_security_source_file:
        suffix = "已加密" if setting_password else "无密码"
        self.pdf_security_output_name_edit.setText(
            default_output_name(f"{Path(self.pdf_security_source_file).stem}_{suffix}")
        )
    self.pdf_security_start_button.setEnabled(
        bool(self.pdf_security_source_file and self.pdf_security_output_folder)
    )


def process_pdf_security(self):
    if not self.pdf_workspace.can_process_files((self.pdf_security_source_file,)):
        return
    setting_password = self.pdf_security_mode_combo.currentData() == "set"
    source_password = self.pdf_source_password_edit.text()
    new_password = self.pdf_new_password_edit.text() if setting_password else ""
    if setting_password:
        if len(new_password) < 6:
            QMessageBox.warning(self, "密码太短", "新密码至少需要 6 个字符。")
            return
        if new_password != self.pdf_confirm_password_edit.text():
            QMessageBox.warning(self, "密码不一致", "两次输入的新密码不一致。")
            return
    try:
        output_file = output_path(
            self.pdf_security_output_folder,
            self.pdf_security_output_name_edit.text(),
            default_output_name("PDF密码处理结果"),
        )
    except Exception as error:
        QMessageBox.critical(self, "无法生成", str(error))
        return

    source_file = self.pdf_security_source_file
    action_text = "设置密码" if setting_password else "移除密码"

    def completed(result):
        self.pdf_security_result_file = result.output_file
        self.pdf_security_status_label.setText(
            f"{action_text}完成：{Path(result.output_file).name}"
        )
        self.save_pdf_result_message(f"PDF {action_text}完成", result)

    started = self.start_background_task(
        f"正在{action_text}",
        f"正在处理：{Path(source_file).name}",
        lambda _progress: secure_pdf(
            source_file,
            output_file,
            new_password=new_password,
            source_password=source_password,
        ),
        completed,
        lambda error: QMessageBox.critical(self, f"{action_text}失败", error),
        status_label=self.pdf_security_status_label,
    )
    if started:
        self.pdf_source_password_edit.clear()
        self.pdf_new_password_edit.clear()
        self.pdf_confirm_password_edit.clear()


def choose_searchable_pdf_source(self):
    filename, _ = QFileDialog.getOpenFileName(
        self,
        "选择需要生成可搜索副本的 PDF",
        self.dialog_folder("open"),
        "PDF 文件 (*.pdf)",
    )
    if not filename:
        return
    self.remember_dialog_folder("open", filename)
    self.pdf_searchable_source_file = os.path.abspath(filename)
    self.pdf_searchable_source_edit.setText(self.pdf_searchable_source_file)
    self.pdf_searchable_source_edit.setToolTip(self.pdf_searchable_source_file)
    self.pdf_searchable_output_folder = str(Path(filename).parent / "output")
    self.pdf_searchable_output_folder_edit.setText(self.pdf_searchable_output_folder)
    self.pdf_searchable_output_name_edit.setText(
        default_output_name(f"{Path(filename).stem}_可搜索")
    )
    self.pdf_searchable_inspection = None
    self.pdf_searchable_inspection_label.setText("正在检查 PDF 页面…")
    self.pdf_searchable_status_label.setText("正在检查 PDF…")
    self.update_searchable_pdf_button()
    self.start_background_task(
        "正在检查 PDF",
        f"正在检查页面：{Path(filename).name}",
        lambda _progress: inspect_pdf(filename),
        self.searchable_pdf_inspection_completed,
        lambda error: QMessageBox.critical(self, "无法读取 PDF", error),
        status_label=self.pdf_searchable_status_label,
    )


def searchable_pdf_inspection_completed(self, inspection):
    self.pdf_searchable_inspection = inspection
    if inspection.scanned_pages:
        pages = "、".join(map(str, inspection.scanned_pages))
        self.pdf_searchable_inspection_label.setText(
            f"共 {inspection.page_count} 页，需要 OCR：第 {pages} 页"
        )
        self.pdf_searchable_status_label.setText(
            f"检查完成，{len(inspection.scanned_pages)} 个扫描页需要 OCR"
        )
    else:
        self.pdf_searchable_inspection_label.setText(
            f"共 {inspection.page_count} 页，均已包含可搜索文字"
        )
        self.pdf_searchable_status_label.setText("检查完成，可在本机生成副本")
    self.update_searchable_pdf_button()


def choose_searchable_pdf_output_folder(self):
    folder = QFileDialog.getExistingDirectory(
        self,
        "选择可搜索 PDF 保存文件夹",
        self.dialog_folder("save", self.pdf_searchable_output_folder),
        QFileDialog.ShowDirsOnly,
    )
    if not folder:
        return
    self.pdf_searchable_output_folder = os.path.abspath(folder)
    self.remember_dialog_folder("save", folder)
    self.pdf_searchable_output_folder_edit.setText(self.pdf_searchable_output_folder)
    self.update_searchable_pdf_button()


def pdf_searchable_provider_changed(self):
    provider = self.pdf_searchable_provider_combo.currentData()
    try:
        select_provider(provider)
    except OSError as error:
        QMessageBox.warning(self, "无法保存选择", str(error))
    for combo in (
        self.document_ocr_provider_combo,
        self.batch_ocr_provider_combo,
        self.rename_smart_provider_combo,
    ):
        index = combo.findData(provider)
        if index >= 0 and combo.currentIndex() != index:
            combo.setCurrentIndex(index)
    self.update_searchable_pdf_button()


def update_searchable_pdf_button(self):
    self.pdf_searchable_start_button.setEnabled(
        bool(
            self.pdf_searchable_source_file
            and self.pdf_searchable_output_folder
            and self.pdf_searchable_inspection is not None
        )
    )


def create_searchable_pdf(self):
    if not self.pdf_workspace.can_process_files((self.pdf_searchable_source_file,)):
        return
    inspection = self.pdf_searchable_inspection
    if inspection is None:
        QMessageBox.warning(self, "尚未完成检查", "请先选择 PDF 并等待检查完成。")
        return
    provider = self.pdf_searchable_provider_combo.currentData()
    if inspection.scanned_pages:
        if not is_provider_configured(provider):
            QMessageBox.warning(
                self,
                "OCR 密钥未配置",
                "检测到扫描页，请先在设置中填写所选文字识别平台的密钥。",
            )
            return
        pages = "、".join(map(str, inspection.scanned_pages))
        answer = QMessageBox.question(
            self,
            "发送扫描页前确认",
            f"第 {pages} 页会发送给 "
            f"{PROVIDER_LABELS.get(provider, provider)} 识别文字；"
            "其他页面仍在本机处理。\n\n是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
    try:
        output_file = output_path(
            self.pdf_searchable_output_folder,
            self.pdf_searchable_output_name_edit.text(),
            default_output_name("可搜索PDF"),
        )
    except Exception as error:
        QMessageBox.critical(self, "无法生成", str(error))
        return

    source_file = self.pdf_searchable_source_file

    def completed(result):
        self.pdf_searchable_result_file = result.output_file
        self.pdf_searchable_status_label.setText(
            f"已生成：{Path(result.output_file).name}"
        )
        self.save_pdf_result_message("可搜索 PDF 生成完成", result)

    self.start_background_task(
        "正在生成可搜索 PDF",
        f"正在处理：{Path(source_file).name}",
        lambda progress: make_searchable_pdf(
            source_file,
            output_file,
            provider,
            progress_callback=progress,
        ),
        completed,
        lambda error: QMessageBox.critical(self, "生成失败", error),
        status_label=self.pdf_searchable_status_label,
    )


def choose_pdf_compare_source(self, side):
    filename, _ = QFileDialog.getOpenFileName(
        self,
        "选择需要对比的 PDF",
        self.dialog_folder("open"),
        "PDF 文件 (*.pdf)",
    )
    if not filename:
        return
    filename = os.path.abspath(filename)
    self.remember_dialog_folder("open", filename)
    if side == "left":
        self.pdf_compare_left_file = filename
        self.pdf_compare_left_edit.setText(filename)
        self.pdf_compare_left_edit.setToolTip(filename)
    else:
        self.pdf_compare_right_file = filename
        self.pdf_compare_right_edit.setText(filename)
        self.pdf_compare_right_edit.setToolTip(filename)
    if not self.pdf_compare_output_folder:
        self.pdf_compare_output_folder = str(Path(filename).parent / "output")
        self.pdf_compare_output_folder_edit.setText(self.pdf_compare_output_folder)
    self.update_pdf_compare_buttons()


def choose_pdf_compare_output_folder(self):
    folder = QFileDialog.getExistingDirectory(
        self,
        "选择对比报告保存文件夹",
        self.dialog_folder("save", self.pdf_compare_output_folder),
        QFileDialog.ShowDirsOnly,
    )
    if not folder:
        return
    self.pdf_compare_output_folder = os.path.abspath(folder)
    self.remember_dialog_folder("save", folder)
    self.pdf_compare_output_folder_edit.setText(self.pdf_compare_output_folder)
    self.update_pdf_compare_buttons()


def update_pdf_compare_buttons(self):
    self.pdf_compare_start_button.setEnabled(
        bool(
            self.pdf_compare_left_file
            and self.pdf_compare_right_file
            and self.pdf_compare_output_folder
        )
    )
    self.pdf_compare_open_button.setEnabled(
        bool(self.pdf_compare_result_file and Path(self.pdf_compare_result_file).is_file())
    )


def create_pdf_compare_report(self):
    if not self.pdf_workspace.can_process_files((self.pdf_compare_left_file, self.pdf_compare_right_file)):
        return
    name = self.pdf_compare_output_name_edit.text().strip() or default_output_name(
        "PDF文字对比", ".html"
    )
    if not name.lower().endswith(".html"):
        name += ".html"
    if Path(name).name != name or any(character in name for character in ("\0", ":")):
        QMessageBox.warning(self, "文件名不正确", "报告文件名包含不允许的字符。")
        return
    output_file = str(Path(self.pdf_compare_output_folder).expanduser().resolve() / name)
    left_file = self.pdf_compare_left_file
    right_file = self.pdf_compare_right_file

    def completed(result):
        self.pdf_compare_result_file = result.output_file
        self.pdf_compare_status_label.setText(
            f"已生成：{Path(result.output_file).name}"
        )
        self.update_pdf_compare_buttons()
        self.save_pdf_result_message(
            "PDF 文字对比完成",
            result,
            "报告已在本机生成。",
        )

    self.start_background_task(
        "正在对比 PDF 文字",
        "正在读取两份 PDF…",
        lambda progress: compare_pdf_text(
            left_file,
            right_file,
            output_file,
            progress_callback=progress,
        ),
        completed,
        lambda error: QMessageBox.critical(self, "对比失败", error),
        total=2,
        status_label=self.pdf_compare_status_label,
    )


def save_pdf_result_message(self, title, result, extra_text="", open_target=""):
    open_target = open_target or result.output_file or (
        str(Path(result.image_files[0]).parent) if result.image_files else ""
    )
    message = QMessageBox(self)
    message.setWindowTitle(title)
    message.setIcon(QMessageBox.Information)
    message.setText(title)
    detail = extra_text
    if result.output_file:
        detail += f"\n\n结果文件：\n{result.output_file}"
    if result.image_files:
        detail += f"\n\n生成图片：{len(result.image_files)} 张"
    if result.log_file:
        detail += f"\n\n日志文件：\n{result.log_file}"
    message.setInformativeText(detail.strip())
    open_button = message.addButton("打开结果", QMessageBox.ActionRole)
    ok_button = message.addButton("确定", QMessageBox.AcceptRole)
    for button in (ok_button, open_button):
        button.setFixedSize(112, 36)
    message.setDefaultButton(ok_button)
    message.exec()
    if message.clickedButton() == open_button and open_target:
        self.open_output_file(open_target)


def choose_pdf_compress_source(self):
    filename, _ = QFileDialog.getOpenFileName(
        self,
        "选择需要压缩的 PDF",
        self.dialog_folder("open"),
        "PDF 文件 (*.pdf)",
    )
    if not filename:
        return
    self.remember_dialog_folder("open", filename)
    self.pdf_compress_source_file = os.path.abspath(filename)
    self.pdf_compress_source_edit.setText(self.pdf_compress_source_file)
    self.pdf_compress_source_edit.setToolTip(self.pdf_compress_source_file)
    folder = str(Path(self.pdf_compress_source_file).parent / "output")
    self.pdf_compress_output_folder_edit.setText(folder)
    self.pdf_compress_output_folder_edit.setToolTip(folder)
    self.pdf_compress_output_name_edit.setText(
        default_output_name(f"{Path(filename).stem}_压缩")
    )
    self.pdf_compress_status_label.setText("已选择 PDF，可开始压缩")
    self.update_pdf_compress_estimate()
    self.update_pdf_button_states()


def choose_pdf_compress_output_folder(self):
    folder = QFileDialog.getExistingDirectory(
        self,
        "选择压缩结果保存文件夹",
        self.dialog_folder("save", self.pdf_compress_output_folder_edit.text()),
        QFileDialog.ShowDirsOnly,
    )
    if folder:
        self.remember_dialog_folder("save", folder)
        self.pdf_compress_output_folder_edit.setText(os.path.abspath(folder))
        self.update_pdf_button_states()


def current_pdf_compression_preset(self):
    if not hasattr(self, "pdf_compress_preset_combo"):
        return "standard"
    return self.pdf_compress_preset_combo.currentData() or "standard"


def update_pdf_compress_estimate(self):
    if not getattr(self, "pdf_compress_source_file", ""):
        self.pdf_compress_size_label.setText("原始大小：-    预计压缩后：-    预计缩小：-")
        return
    source = Path(self.pdf_compress_source_file)
    if not source.exists():
        self.pdf_compress_size_label.setText(
            "原始大小：文件不存在    预计压缩后：-    预计缩小：-"
        )
        return
    source_size = source.stat().st_size
    low, high = estimate_compressed_size(
        source_size,
        self.current_pdf_compression_preset(),
    )
    saved_low = max(0, round((source_size - high) / source_size * 100))
    saved_high = max(0, round((source_size - low) / source_size * 100))
    self.pdf_compress_size_label.setText(
        f"原始大小：{format_file_size(source_size)}    "
        f"预计压缩后：{format_file_size(low)} - {format_file_size(high)}    "
        f"预计缩小：{saved_low}% - {saved_high}%"
    )


def compress_selected_pdf(self):
    if not self.pdf_workspace.can_process_files((self.pdf_compress_source_file,)):
        return
    try:
        output_file = output_path(
            self.pdf_compress_output_folder_edit.text(),
            self.pdf_compress_output_name_edit.text(),
            default_output_name("PDF压缩结果"),
        )
    except (ValueError, OSError) as error:
        message = compression_io_message(error) if isinstance(error, OSError) else str(error)
        QMessageBox.critical(self, "压缩失败", message)
        return
    source_file = self.pdf_compress_source_file
    preset = self.current_pdf_compression_preset()

    def compressed(result):
        change = f"节省 {result.saved_percent}%" if result.output_size < result.source_size else "体积未减小"
        text = (f"{result.compression_method}：{format_file_size(result.source_size)} → "
                f"{format_file_size(result.output_size)}，{change}。")
        self.pdf_compress_status_label.setText(text)
        detail = f"{text}\n{result.compression_note}" if result.compression_note else text
        self.save_pdf_result_message("PDF 压缩完成", result, detail)

    self.start_background_task(
        "正在压缩 PDF",
        f"正在处理：{Path(source_file).name}",
        lambda _progress: compress_pdf(source_file, output_file, preset),
        compressed,
        lambda error: QMessageBox.critical(self, "压缩失败", error),
        status_label=self.pdf_compress_status_label,
    )


def show_pdf_convert_mode(self, index):
    self.pdf_convert_stack.setCurrentIndex(index)
    self.pdf_image_mode_button.setChecked(index == 0)
    self.pdf_export_mode_button.setChecked(index == 1)


def sync_pdf_image_source_files(self):
    self.pdf_image_source_files = [card.image_file for card in self.pdf_image_cards]


def selected_pdf_image_cards(self):
    return [card for card in self.pdf_image_cards if card.is_checked()]


def refresh_pdf_image_cards_layout(self):
    if not hasattr(self, "pdf_image_board"):
        return
    if getattr(self, "refreshing_pdf_image_layout", False):
        return
    self.refreshing_pdf_image_layout = True
    while self.pdf_image_board.grid.count():
        item = self.pdf_image_board.grid.takeAt(0)
        if item.widget():
            item.widget().setParent(None)
    try:
        viewport_width = max(self.pdf_image_scroll.viewport().width(), PDF_PAGE_CARD_WIDTH)
        columns = max(
            1,
            (viewport_width - 28) // (PDF_PAGE_CARD_WIDTH + PDF_PAGE_CARD_H_SPACING),
        )
        row_count = (len(self.pdf_image_cards) + columns - 1) // columns
        content_height = (
            16
            + row_count * PDF_PAGE_CARD_HEIGHT
            + max(0, row_count - 1) * PDF_PAGE_CARD_V_SPACING
        )
        self.pdf_image_board.setMinimumHeight(content_height)
        for index, card in enumerate(self.pdf_image_cards):
            row = index // columns
            column = index % columns
            self.pdf_image_board.grid.addWidget(card, row, column)
    finally:
        self.refreshing_pdf_image_layout = False


def refresh_pdf_image_cards(self):
    self.sync_pdf_image_source_files()
    for index, card in enumerate(self.pdf_image_cards, 1):
        card.update_display(index)
    count = len(self.pdf_image_cards)
    self.pdf_image_limit_label.setText(
        f"当前 {count:,} / {PDF_IMAGE_MAX_COUNT:,} 张；"
        "处理数量越多，处理速度越慢，请酌情拆分任务"
    )
    checked = len(self.selected_pdf_image_cards())
    if count:
        self.pdf_image_status_label.setText(
            f"已添加 {count} 张图片，已勾选 {checked} 张。双击图片可放大预览。"
        )
    else:
        self.pdf_image_status_label.setText("尚未添加图片")
    self.update_pdf_button_states()


def reorder_pdf_image(self, source_index, insert_index):
    if source_index < 0 or source_index >= len(self.pdf_image_cards):
        return
    insert_index = max(0, min(insert_index, len(self.pdf_image_cards)))
    card = self.pdf_image_cards.pop(source_index)
    if source_index < insert_index:
        insert_index -= 1
    self.pdf_image_cards.insert(insert_index, card)
    self.refresh_pdf_image_cards_layout()
    self.refresh_pdf_image_cards()


def preview_pdf_image(self, card):
    pixmap = load_image_pixmap(card.image_file)
    if pixmap.isNull():
        QMessageBox.warning(self, "无法预览", "这张图片无法预览。")
        return
    dialog = QDialog(self)
    dialog.setWindowTitle(Path(card.image_file).name)
    dialog_layout = QVBoxLayout(dialog)
    image_label = QLabel()
    image_label.setAlignment(Qt.AlignCenter)
    image_label.setPixmap(pixmap)
    scroll_area = QScrollArea()
    scroll_area.setWidget(image_label)
    scroll_area.setWidgetResizable(True)
    dialog_layout.addWidget(scroll_area, 1)
    close_button = QPushButton("关闭")
    close_button.clicked.connect(dialog.accept)
    dialog_layout.addWidget(close_button)
    dialog.resize(960, 760)
    dialog.exec()


def start_adding_pdf_images(self, filenames):
    if not filenames:
        return False
    existing = {card.image_file for card in self.pdf_image_cards}
    candidates = []
    seen = set(existing)
    repeated = 0
    skipped_before_check = 0
    for filename in filenames:
        normalized = os.path.abspath(filename)
        if normalized in seen:
            repeated += 1
            continue
        seen.add(normalized)
        path = Path(normalized)
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            skipped_before_check += 1
            continue
        candidates.append(normalized)

    def report_addition(added, skipped):
        detail = f"本次新增 {added} 张图片，列表共 {len(self.pdf_image_cards)} 张。"
        if repeated:
            detail += f"忽略 {repeated} 个重复项。"
        if skipped:
            detail += f"跳过 {skipped} 个非图片或无法读取文件。"
        self.pdf_image_status_label.setText(detail)
        if not added:
            QMessageBox.information(self, "没有新增图片", detail)

    if not candidates:
        report_addition(0, skipped_before_check)
        return False
    if not self.confirm_large_addition(
        "图片",
        len(self.pdf_image_cards),
        len(candidates),
        PDF_IMAGE_WARNING_COUNT,
        PDF_IMAGE_MAX_COUNT,
    ):
        return False

    def prepare_images(progress_callback):
        prepared = []
        skipped = skipped_before_check
        total = len(candidates)
        for index, filename in enumerate(candidates, 1):
            progress_callback(
                index - 1,
                total,
                f"正在准备第 {index} / {total} 张图片：{Path(filename).name}",
            )
            thumbnail_file = Path(self.pdf_thumbnail_tempdir.name) / (
                f"image_{uuid.uuid4().hex}.png"
            )
            try:
                preview = prepare_image_thumbnail(
                    filename,
                    thumbnail_file,
                    (PDF_PAGE_THUMBNAIL_SIZE.width(), PDF_PAGE_THUMBNAIL_SIZE.height()),
                )
            except Exception:
                skipped += 1
            else:
                prepared.append((filename, preview))
            progress_callback(index, total, f"已准备 {index} / {total} 张图片")
        return tuple(prepared), skipped

    def images_prepared(result):
        prepared, skipped = result
        for filename, thumbnail_file in prepared:
            self.pdf_image_cards.append(
                PdfImageCard(self, filename, thumbnail_file)
            )
        if self.pdf_image_cards and not self.pdf_image_output_folder_edit.text():
            folder = str(Path(self.pdf_image_cards[0].image_file).parent / "output")
            self.pdf_image_output_folder_edit.setText(folder)
            self.pdf_image_output_folder_edit.setToolTip(folder)
        if not self.pdf_image_output_name_edit.text():
            self.pdf_image_output_name_edit.setText(default_output_name("图片合成PDF"))
        self.refresh_pdf_image_cards_layout()
        self.refresh_pdf_image_cards()
        report_addition(len(prepared), skipped)

    return self.start_background_task(
        "正在添加图片",
        f"准备检查 {len(candidates)} 张图片…",
        prepare_images,
        images_prepared,
        lambda error: QMessageBox.critical(self, "添加图片失败", error),
        total=len(candidates),
        status_label=self.pdf_image_status_label,
    )


def add_pdf_image_paths(self, filenames):
    return self.start_adding_pdf_images(filenames)


def add_pdf_images(self):
    suffixes = " ".join(f"*{suffix}" for suffix in sorted(IMAGE_SUFFIXES))
    filenames, _ = QFileDialog.getOpenFileNames(
        self,
        "选择图片",
        self.dialog_folder("open"),
        f"图片文件 ({suffixes})",
    )
    if filenames:
        self.remember_dialog_folder("open", filenames[0])
    self.start_adding_pdf_images(filenames)


def add_pdf_image_folder(self):
    folder = QFileDialog.getExistingDirectory(
        self,
        "选择图片文件夹",
        self.dialog_folder("open"),
        QFileDialog.ShowDirsOnly,
    )
    if not folder:
        return
    self.remember_dialog_folder("open", folder)
    image_files = [
        str(path)
        for path in sorted(Path(folder).iterdir(), key=lambda item: item.name.lower())
        if path.is_file()
    ]
    self.start_adding_pdf_images(image_files)


def clear_pdf_images(self):
    for card in self.pdf_image_cards:
        card.setParent(None)
        card.deleteLater()
    self.pdf_image_cards = []
    self.refresh_pdf_image_cards_layout()
    self.refresh_pdf_image_cards()


def delete_checked_pdf_images(self):
    selected = self.selected_pdf_image_cards()
    if not selected:
        return
    if not self.confirm_list_change(f"是否从列表移除勾选的 {len(selected)} 张图片？\n不删除原文件。"):
        return
    for card in selected:
        self.pdf_image_cards.remove(card)
        card.setParent(None)
        card.deleteLater()
    self.refresh_pdf_image_cards_layout()
    self.refresh_pdf_image_cards()


def choose_pdf_image_output_folder(self):
    folder = QFileDialog.getExistingDirectory(
        self,
        "选择图片合成 PDF 保存文件夹",
        self.dialog_folder("save", self.pdf_image_output_folder_edit.text()),
        QFileDialog.ShowDirsOnly,
    )
    if folder:
        self.remember_dialog_folder("save", folder)
        self.pdf_image_output_folder_edit.setText(os.path.abspath(folder))
        self.update_pdf_button_states()


def convert_images_to_pdf(self):
    try:
        self.sync_pdf_image_source_files()
        image_files = tuple(self.pdf_image_source_files)
        if not self.pdf_workspace.can_process_files(image_files):
            return
        output_file = output_path(
            self.pdf_image_output_folder_edit.text(),
            self.pdf_image_output_name_edit.text(),
            default_output_name("图片合成PDF"),
        )
    except Exception as error:
        QMessageBox.critical(self, "合成失败", str(error))
        return

    def converted(result):
        self.pdf_image_status_label.setText(
            f"已生成：{Path(result.output_file).name}"
        )
        self.save_pdf_result_message("图片合成 PDF 完成", result)

    self.start_background_task(
        "正在合成 PDF",
        f"正在处理 {len(image_files)} 张图片…",
        lambda _progress: images_to_pdf(image_files, output_file),
        converted,
        lambda error: QMessageBox.critical(self, "合成失败", error),
        status_label=self.pdf_image_status_label,
    )


def choose_pdf_export_source(self):
    filenames, _ = QFileDialog.getOpenFileNames(
        self,
        "选择一个或多个需要导出图片的 PDF",
        self.dialog_folder("open"),
        "PDF 文件 (*.pdf)",
    )
    if not filenames:
        return
    self.remember_dialog_folder("open", filenames[0])
    added, repeated = self.add_pdf_export_sources(filenames)
    self.ensure_pdf_export_output_folder()
    status = f"已添加 {len(self.pdf_export_source_files)} 个 PDF"
    if repeated:
        status += f"，忽略 {repeated} 个重复文件"
    elif not added:
        status += "，没有新增文件"
    self.pdf_export_status_label.setText(status)


def choose_pdf_export_source_folder(self):
    folder = QFileDialog.getExistingDirectory(
        self,
        "选择包含 PDF 的文件夹",
        self.dialog_folder("open"),
        QFileDialog.ShowDirsOnly,
    )
    if not folder:
        return
    self.remember_dialog_folder("open", folder)
    found, added, repeated = self.add_pdf_export_source_folder(folder)
    if not found:
        QMessageBox.information(
            self,
            "没有 PDF",
            "这个文件夹当前层级中没有 PDF 文件。",
        )
        return
    self.ensure_pdf_export_output_folder()
    status = f"文件夹中找到 {found} 个 PDF，新增 {added} 个"
    if repeated:
        status += f"，忽略 {repeated} 个重复文件"
    self.pdf_export_status_label.setText(status)


def add_pdf_export_source_folder(self, folder):
    folder = Path(folder).expanduser().resolve()
    pdf_files = [
        str(path)
        for path in sorted(folder.iterdir(), key=lambda item: item.name.lower())
        if path.is_file() and path.suffix.lower() == ".pdf"
    ]
    added, repeated = self.add_pdf_export_sources(pdf_files)
    return len(pdf_files), added, repeated


def ensure_pdf_export_output_folder(self):
    if self.pdf_export_output_folder_edit.text() or not self.pdf_export_source_files:
        return
    folder = str(Path(self.pdf_export_source_files[0]).parent / "PDF转图片结果")
    self.pdf_export_output_folder_edit.setText(folder)
    self.pdf_export_output_folder_edit.setToolTip(folder)
    self.update_pdf_button_states()


def add_pdf_export_sources(self, filenames):
    known = set(self.pdf_export_source_files)
    added = 0
    repeated = 0
    for filename in filenames:
        source = str(Path(filename).expanduser().resolve())
        if Path(source).suffix.lower() != ".pdf" or not Path(source).is_file():
            continue
        if source in known:
            repeated += 1
            continue
        self.pdf_export_source_files.append(source)
        known.add(source)
        added += 1
    self.refresh_pdf_export_source_tree()
    return added, repeated


def refresh_pdf_export_source_tree(self):
    self.pdf_export_source_tree.clear()
    for source_file in self.pdf_export_source_files:
        source = Path(source_file)
        item = QTreeWidgetItem([source.name, str(source.parent)])
        item.setData(0, Qt.UserRole, source_file)
        item.setToolTip(0, source_file)
        item.setToolTip(1, source_file)
        self.pdf_export_source_tree.addTopLevelItem(item)
    if self.pdf_export_source_files:
        self.pdf_export_status_label.setText(
            f"已添加 {len(self.pdf_export_source_files)} 个 PDF，可开始导出图片"
        )
    else:
        self.pdf_export_status_label.setText("尚未选择 PDF")
    self.update_pdf_button_states()


def delete_selected_pdf_export_sources(self):
    selected = {
        item.data(0, Qt.UserRole)
        for item in self.pdf_export_source_tree.selectedItems()
    }
    if not selected:
        return
    self.pdf_export_source_files = [
        source for source in self.pdf_export_source_files if source not in selected
    ]
    self.refresh_pdf_export_source_tree()


def clear_pdf_export_sources(self):
    if not self.pdf_export_source_files:
        return
    if not self.confirm_list_change(
        f"是否清空已添加的 {len(self.pdf_export_source_files)} 个 PDF"
    ):
        return
    self.pdf_export_source_files = []
    self.refresh_pdf_export_source_tree()


def choose_pdf_export_output_folder(self):
    folder = QFileDialog.getExistingDirectory(
        self,
        "选择图片保存文件夹",
        self.dialog_folder("save", self.pdf_export_output_folder_edit.text()),
        QFileDialog.ShowDirsOnly,
    )
    if folder:
        self.remember_dialog_folder("save", folder)
        self.pdf_export_output_folder_edit.setText(os.path.abspath(folder))
        self.update_pdf_button_states()


def export_pdf_to_images(self):
    if not self.pdf_workspace.can_process_files(self.pdf_export_source_files):
        return
    source_files = tuple(self.pdf_export_source_files)
    output_folder = self.pdf_export_output_folder_edit.text()
    image_format = self.pdf_export_format_combo.currentText().lower()
    dpi = self.pdf_export_quality_combo.currentData()

    def export_completed(result):
        success_count = len(result.source_files)
        failure_count = len(result.failures)
        image_count = len(result.image_files)
        if success_count == 0 and failure_count:
            self.pdf_export_status_label.setText(
                f"转换失败：0 个成功，{failure_count} 个失败"
            )
            QMessageBox.critical(
                self,
                "PDF 转换失败",
                f"所有 PDF 都转换失败，未生成图片。\n\n"
                f"详细原因已记录在日志中：\n{result.log_file}",
            )
            return
        self.pdf_export_status_label.setText(
            f"处理完成：成功 {success_count} 个，失败 {failure_count} 个，"
            f"共生成 {image_count} 张图片"
        )
        detail = (
            f"成功 PDF：{success_count} 个\n"
            f"失败 PDF：{failure_count} 个"
        )
        if result.failures:
            failure_names = "、".join(
                Path(source).name for source, _ in result.failures
            )
            detail += f"\n失败文件：{failure_names}\n详细原因已记录在日志中。"
        self.save_pdf_result_message(
            "PDF 导出图片完成",
            result,
            detail,
            output_folder,
        )

    self.start_background_task(
        "正在转换 PDF",
        f"准备转换 {len(source_files)} 个 PDF…",
        lambda progress: pdfs_to_images(
            source_files,
            output_folder,
            image_format,
            dpi,
            progress_callback=progress,
        ),
        export_completed,
        lambda error: QMessageBox.critical(self, "导出失败", error),
        total=len(source_files),
        status_label=self.pdf_export_status_label,
    )

