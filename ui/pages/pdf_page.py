import os
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from excel_merge_tool import format_file_size
from ui.presentation import contain_page_form
from api_layer import PROVIDER_LABELS, inspect_pdf, is_provider_configured
from api_layer.config import select_provider, selected_provider
from pdf_toolbox import (
    COMPRESSION_PRESETS,
    compress_pdf,
    compression_io_message,
    compare_pdf_text,
    default_output_name,
    estimate_compressed_size,
    make_searchable_pdf,
    output_path,
    secure_pdf,
)
from ui.common_widgets import SelectionComboBox
from ui.pdf_workspace import PdfWorkspaceWidget


class PdfPageMixin:
    """Existing window methods; initialization remains in the window."""

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
