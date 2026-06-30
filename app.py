import os
import re
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import (
    QLibraryInfo,
    QLocale,
    QSize,
    QSettings,
    Qt,
    QTranslator,
    QUrl,
)
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from excel_merge_tool import (
    build_merged_workbook,
    discover_excel_files,
    format_file_size,
    get_file_info,
    split_workbook_by_rows,
)
from batch_rename_tool import (
    RenameOptions,
    apply_renames,
    discover_rename_files,
    preview_renames,
)
from document_router import process_document
from pdf_invoice_tool import (
    convert_invoice_pdfs,
)
from v2.layout_engine import process_layout_document
from version import APP_VERSION


APP_NAME_ZH = "Eggie文档处理系统"
APP_NAME_EN = "Eggie DocuFlow"
DOCUMENT_TYPE_LABELS = {
    "INVOICE": "发票",
    "CONTRACT": "合同",
    "TABLE": "表格",
    "UNKNOWN": "未知文档",
}


def is_chinese_locale(locale):
    return locale.language() == QLocale.Chinese


def localized_app_name(locale):
    return APP_NAME_ZH if is_chinese_locale(locale) else APP_NAME_EN


def resource_path(relative_path):
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path / relative_path


ACCENT_PALETTES = {
    "cyan": {
        "label": "青蓝",
        "accent": "#22D3EE",
        "accent_hover": "#06B6D4",
        "accent_pressed": "#0891B2",
        "accent_soft_dark": "#0E2B36",
        "accent_border_dark": "#164E63",
        "primary": "#06B6D4",
        "primary_hover": "#0891B2",
        "primary_pressed": "#0E7490",
    },
    "green": {
        "label": "翡翠绿",
        "accent": "#34D399",
        "accent_hover": "#10B981",
        "accent_pressed": "#059669",
        "accent_soft_dark": "#0F2F26",
        "accent_border_dark": "#166534",
        "primary": "#10B981",
        "primary_hover": "#059669",
        "primary_pressed": "#047857",
    },
    "blue": {
        "label": "深蓝",
        "accent": "#60A5FA",
        "accent_hover": "#3B82F6",
        "accent_pressed": "#2563EB",
        "accent_soft_dark": "#172B4E",
        "accent_border_dark": "#1D4ED8",
        "primary": "#3B82F6",
        "primary_hover": "#2563EB",
        "primary_pressed": "#1D4ED8",
    },
    "purple": {
        "label": "紫色",
        "accent": "#A78BFA",
        "accent_hover": "#8B5CF6",
        "accent_pressed": "#7C3AED",
        "accent_soft_dark": "#2E2453",
        "accent_border_dark": "#6D28D9",
        "primary": "#8B5CF6",
        "primary_hover": "#7C3AED",
        "primary_pressed": "#6D28D9",
    },
}

THEME_BASES = {
    "dark": {
        "window_bg": "#091120",
        "panel": "#111C31",
        "panel_alt": "#0F172A",
        "panel_hover": "#15233A",
        "text": "#E5F0FF",
        "title": "#F8FAFC",
        "muted": "#9FB2CC",
        "placeholder": "#71839D",
        "border": "#26354D",
        "border_soft": "#1D2C42",
        "table_header": "#17263F",
        "table_row": "#0F1A2D",
        "table_row_alt": "#132139",
        "input": "#0B1324",
        "disabled_bg": "#1D2A3D",
        "disabled_text": "#738198",
        "danger_bg": "#3A1D26",
        "danger_text": "#FCA5A5",
        "danger_border": "#7F1D1D",
        "shadow": "rgba(0, 0, 0, 96)",
    },
}


def build_theme_colors(accent_name):
    base = THEME_BASES["dark"].copy()
    accent = ACCENT_PALETTES.get(accent_name, ACCENT_PALETTES["cyan"])
    base.update(
        {
            "accent": accent["accent"],
            "accent_hover": accent["accent_hover"],
            "accent_pressed": accent["accent_pressed"],
            "accent_soft": accent["accent_soft_dark"],
            "accent_border": accent["accent_border_dark"],
            "primary": accent["primary"],
            "primary_hover": accent["primary_hover"],
            "primary_pressed": accent["primary_pressed"],
        }
    )
    return base


def build_theme_stylesheet(colors):
    return f"""
    QMainWindow {{
        background: {colors["window_bg"]};
        color: {colors["text"]};
    }}
    QWidget#homePage,
    QWidget#excelPage,
    QWidget#splitPage,
    QWidget#invoicePage,
    QWidget#documentPage,
    QWidget#renamePage {{
        background: {colors["window_bg"]};
        color: {colors["text"]};
    }}
    QLabel {{
        color: {colors["text"]};
    }}
    QLabel[role="title"] {{
        color: {colors["title"]};
        font-size: 26px;
        font-weight: 700;
    }}
    QLabel[role="subtitle"],
    QLabel[role="hint"] {{
        color: {colors["muted"]};
        font-size: 13px;
    }}
    QLabel[role="status"] {{
        color: {colors["accent"]};
        font-size: 12px;
    }}
    QGroupBox {{
        background: {colors["panel"]};
        border: 1px solid {colors["border"]};
        border-radius: 12px;
        margin-top: 12px;
        padding-top: 12px;
        color: {colors["text"]};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 8px;
        color: {colors["title"]};
        font-weight: 600;
        background: {colors["window_bg"]};
    }}
    QTreeWidget {{
        background: {colors["table_row"]};
        alternate-background-color: {colors["table_row_alt"]};
        color: {colors["text"]};
        border: 1px solid {colors["border"]};
        border-radius: 10px;
        font-size: 13px;
        selection-background-color: {colors["accent"]};
        selection-color: #FFFFFF;
    }}
    QTreeWidget::item {{
        height: 34px;
        border-bottom: 1px solid {colors["border_soft"]};
    }}
    QTreeWidget::item:selected {{
        background: {colors["accent"]};
        color: #FFFFFF;
    }}
    QTreeWidget::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 5px;
        border: 1px solid {colors["border"]};
        background: {colors["input"]};
    }}
    QTreeWidget::indicator:checked {{
        background: {colors["accent"]};
        border: 1px solid {colors["accent"]};
    }}
    QTreeWidget::indicator:unchecked:selected {{
        background: {colors["input"]};
        border: 1px solid #FFFFFF;
    }}
    QTreeWidget::indicator:checked:selected {{
        background: #FFFFFF;
        border: 1px solid #FFFFFF;
    }}
    QHeaderView::section {{
        background: {colors["table_header"]};
        color: {colors["text"]};
        border: none;
        border-right: 1px solid {colors["border"]};
        border-bottom: 1px solid {colors["border"]};
        padding: 8px;
        font-weight: 600;
    }}
    QLineEdit,
    QComboBox,
    QSpinBox {{
        background: {colors["input"]};
        color: {colors["text"]};
        border: 1px solid {colors["border"]};
        border-radius: 8px;
        padding: 6px 10px;
        min-height: 24px;
    }}
    QLineEdit:focus,
    QComboBox:focus,
    QSpinBox:focus {{
        border: 1px solid {colors["accent"]};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 30px;
    }}
    QComboBox QAbstractItemView {{
        background: {colors["panel"]};
        color: {colors["text"]};
        border: 1px solid {colors["border"]};
        selection-background-color: {colors["accent"]};
        selection-color: white;
    }}
    QLineEdit:read-only {{
        color: {colors["muted"]};
    }}
    QCheckBox {{
        color: {colors["text"]};
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 5px;
        border: 1px solid {colors["border"]};
        background: {colors["input"]};
    }}
    QCheckBox::indicator:checked {{
        background: {colors["accent"]};
        border: 1px solid {colors["accent"]};
    }}
    QPushButton {{
        background: {colors["panel"]};
        color: {colors["text"]};
        border: 1px solid {colors["border"]};
        border-radius: 9px;
        padding: 7px 14px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background: {colors["panel_hover"]};
        border-color: {colors["accent_border"]};
    }}
    QPushButton:pressed {{
        background: {colors["accent_soft"]};
    }}
    QPushButton:disabled {{
        background: {colors["disabled_bg"]};
        color: {colors["disabled_text"]};
        border: 1px solid {colors["border_soft"]};
    }}
    QPushButton[variant="primary"] {{
        background: {colors["primary"]};
        color: #FFFFFF;
        border: 1px solid {colors["primary"]};
        border-radius: 12px;
        font-weight: 700;
        padding: 9px 30px;
    }}
    QPushButton[variant="primary"]:hover {{
        background: {colors["primary_hover"]};
        border-color: {colors["primary_hover"]};
    }}
    QPushButton[variant="primary"]:pressed {{
        background: {colors["primary_pressed"]};
        border-color: {colors["primary_pressed"]};
    }}
    QPushButton[variant="accent"] {{
        background: {colors["accent_soft"]};
        color: {colors["accent"]};
        border: 1px solid {colors["accent_border"]};
        font-weight: 600;
    }}
    QPushButton[variant="danger"] {{
        background: {colors["danger_bg"]};
        color: {colors["danger_text"]};
        border: 1px solid {colors["danger_border"]};
    }}
    QPushButton[variant="ghost"] {{
        background: transparent;
        color: {colors["text"]};
        border: 1px solid {colors["border"]};
    }}
    QPushButton[variant="toolCardPrimary"] {{
        background: {colors["primary"]};
        color: #FFFFFF;
        border: 1px solid {colors["primary"]};
        border-radius: 14px;
        font-weight: 700;
    }}
    QPushButton[variant="toolCardPrimary"]:hover {{
        background: {colors["primary_hover"]};
        border-color: {colors["primary_hover"]};
    }}
    QPushButton[variant="toolCardEmpty"] {{
        background: {colors["panel_alt"]};
        color: {colors["muted"]};
        border: 1px dashed {colors["border"]};
        border-radius: 14px;
    }}
    QPushButton[variant="primary"]:disabled,
    QPushButton[variant="accent"]:disabled,
    QPushButton[variant="danger"]:disabled,
    QPushButton[variant="ghost"]:disabled {{
        background: {colors["disabled_bg"]};
        color: {colors["disabled_text"]};
        border: 1px solid {colors["border_soft"]};
    }}
    QPushButton[variant="toolCardEmpty"]:disabled {{
        background: {colors["panel_alt"]};
        color: {colors["muted"]};
        border: 1px dashed {colors["border"]};
    }}
    QProgressDialog {{
        background: {colors["panel"]};
        color: {colors["text"]};
    }}
    QMessageBox {{
        background: {colors["panel"]};
        color: {colors["text"]};
    }}
    """


def preferred_system_locale():
    locale_name = QLocale.system().name()

    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["/usr/bin/defaults", "read", "-g", "AppleLanguages"],
                capture_output=True,
                check=False,
                text=True,
                timeout=2,
            )
            match = re.search(r'"([^"]+)"', result.stdout)
            if match:
                locale_name = match.group(1)
        except (OSError, subprocess.SubprocessError):
            pass

    return QLocale(locale_name)


def install_qt_translations(application, locale):
    translations_path = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    translator = QTranslator(application)

    if translator.load(locale, "qtbase", "_", translations_path):
        application.installTranslator(translator)
        application.qtbase_translator = translator


def default_output_filename(locale):
    if locale.language() != QLocale.Chinese:
        return "Merged result.xlsx"

    if locale.script() == QLocale.TraditionalHanScript:
        return "合併結果.xlsx"
    return "合并结果.xlsx"


def format_elapsed_seconds(seconds):
    if seconds < 60:
        return f"{seconds:.2f} 秒"

    minutes = int(seconds // 60)
    remaining_seconds = seconds - minutes * 60
    return f"{minutes} 分 {remaining_seconds:.2f} 秒"


class ExcelMergerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.files = []
        self.file_info = {}
        self.checked_files = set()
        self.output_file = ""
        self.split_source_file = ""
        self.split_output_folder = ""
        self.split_result_folder = ""
        self.invoice_source_files = []
        self.invoice_output_folder = ""
        self.document_source_file = ""
        self.document_output_folder = ""
        self.document_result_file = ""
        self.rename_source_files = []
        self.rename_previews = []
        self.rename_last_log_file = ""
        self.refreshing_list = False
        self.settings = QSettings("EggieDocuFlow", "EggieDocuFlow")
        old_settings = QSettings("ExcelMergeTool", "MacSimpleOfficeTools")
        self.accent_name = self.settings.value(
            "appearance/accent",
            old_settings.value("appearance/accent", "cyan"),
        )
        if self.accent_name not in ACCENT_PALETTES:
            self.accent_name = "cyan"
        application = QApplication.instance()
        self.system_locale = getattr(
            application,
            "preferred_locale",
            preferred_system_locale(),
        )
        self.app_name = localized_app_name(self.system_locale)
        self.app_icon = QIcon(str(resource_path("assets/app_icon.icns")))
        if not self.app_icon.isNull():
            self.setWindowIcon(self.app_icon)

        self.setWindowTitle(self.app_name)
        self.resize(1120, 740)
        self.setMinimumSize(900, 580)
        self.setAcceptDrops(True)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.home_page = self.create_home_page()
        self.excel_page = QWidget()
        self.excel_page.setObjectName("excelPage")
        self.split_page = self.create_split_page()
        self.invoice_page = self.create_invoice_page()
        self.document_page = self.create_document_page()
        self.rename_page = self.create_rename_page()
        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.excel_page)
        self.stack.addWidget(self.split_page)
        self.stack.addWidget(self.invoice_page)
        self.stack.addWidget(self.document_page)
        self.stack.addWidget(self.rename_page)
        self.update_home_responsive_layout()

        main_layout = QVBoxLayout(self.excel_page)
        main_layout.setContentsMargins(22, 18, 22, 18)
        main_layout.setSpacing(14)

        tool_header_layout = QHBoxLayout()
        self.back_home_button = QPushButton("返回工具首页")
        self.back_home_button.setMinimumHeight(30)
        self.back_home_button.setProperty("variant", "ghost")
        self.excel_settings_button = QPushButton("软件设置")
        self.excel_settings_button.setMinimumHeight(30)
        self.excel_settings_button.setProperty("variant", "ghost")
        tool_header_layout.addWidget(self.back_home_button)
        self.excel_version_label = QLabel(f"版本 {APP_VERSION}")
        self.excel_version_label.setProperty("role", "hint")
        tool_header_layout.addWidget(self.excel_version_label)
        tool_header_layout.addStretch()
        tool_header_layout.addWidget(self.excel_settings_button)
        main_layout.addLayout(tool_header_layout)

        title = QLabel("Excel 合并工具")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("PingFang SC", 20, QFont.Bold))
        title.setProperty("role", "title")
        main_layout.addWidget(title)

        subtitle = QLabel("选择 Excel 文件或文件夹，按列表顺序合并并保留单元格格式")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setProperty("role", "subtitle")
        main_layout.addWidget(subtitle)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        self.add_files_button = QPushButton("添加文件")
        self.add_folder_button = QPushButton("添加文件夹")
        self.move_up_button = QPushButton("上移")
        self.move_down_button = QPushButton("下移")
        self.delete_button = QPushButton("删除选中")
        self.clear_button = QPushButton("清空列表")
        self.add_files_button.setProperty("variant", "accent")
        self.add_folder_button.setProperty("variant", "accent")
        self.delete_button.setProperty("variant", "danger")

        for button in (
            self.add_files_button,
            self.add_folder_button,
            self.move_up_button,
            self.move_down_button,
            self.delete_button,
            self.clear_button,
        ):
            button.setMinimumHeight(34)
            button_layout.addWidget(button)

        main_layout.addLayout(button_layout)

        file_group = QGroupBox("待合并文件（请选择文件后使用“上移 / 下移”调整顺序）")
        file_group_layout = QVBoxLayout(file_group)
        file_group_layout.setContentsMargins(10, 14, 10, 10)
        file_group_layout.setSpacing(8)

        self.file_table = QTreeWidget()
        self.file_table.setColumnCount(5)
        self.file_table.setHeaderLabels(
            ["序号", "文件名", "文件大小", "行数（含表头）", "文件路径"]
        )
        self.file_table.headerItem().setTextAlignment(0, Qt.AlignCenter)
        self.file_table.setRootIsDecorated(False)
        self.file_table.setUniformRowHeights(True)
        self.file_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.file_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.file_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.file_table.setDragDropMode(QAbstractItemView.NoDragDrop)
        self.file_table.setDragEnabled(False)
        self.file_table.setAcceptDrops(False)
        self.file_table.setDropIndicatorShown(False)
        self.file_table.setAlternatingRowColors(True)
        self.file_table.itemChanged.connect(self.handle_file_item_changed)
        header = self.file_table.header()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Interactive)
        header.setStretchLastSection(False)
        self.file_table.setColumnWidth(0, 90)
        self.file_table.setColumnWidth(1, 250)
        self.file_table.setColumnWidth(2, 105)
        self.file_table.setColumnWidth(3, 120)
        self.file_table.setColumnWidth(4, 760)
        file_group_layout.addWidget(self.file_table)

        self.status_label = QLabel("尚未添加文件")
        self.status_label.setProperty("role", "status")
        file_group_layout.addWidget(self.status_label)
        main_layout.addWidget(file_group, 1)

        save_group = QGroupBox("保存位置")
        save_layout = QHBoxLayout(save_group)
        save_layout.setContentsMargins(12, 14, 12, 10)
        save_layout.setSpacing(10)

        self.output_path_edit = QLineEdit()
        self.output_path_edit.setReadOnly(True)
        self.output_path_edit.setPlaceholderText("请先选择合并结果的保存位置")
        self.output_path_edit.setMinimumHeight(34)

        self.choose_output_button = QPushButton("选择保存位置")
        self.choose_output_button.setMinimumHeight(34)
        save_layout.addWidget(self.output_path_edit, 1)
        save_layout.addWidget(self.choose_output_button)
        main_layout.addWidget(save_group)

        options_layout = QHBoxLayout()
        options_layout.setAlignment(Qt.AlignCenter)
        options_layout.setSpacing(28)

        skip_rows_label = QLabel("后续文件跳过行数：")
        self.skip_rows_spinbox = QSpinBox()
        self.skip_rows_spinbox.setRange(0, 99)
        self.skip_rows_spinbox.setValue(1)
        self.skip_rows_spinbox.setSuffix(" 行")
        self.skip_rows_spinbox.setMinimumWidth(90)
        self.skip_rows_spinbox.setToolTip(
            "仅对第二个及后续文件生效；0 表示不跳过，最多跳过 99 行。"
        )
        self.merged_cells_checkbox = QCheckBox("保留合并单元格")
        self.merged_cells_checkbox.setChecked(True)
        options_layout.addWidget(skip_rows_label)
        options_layout.addWidget(self.skip_rows_spinbox)
        options_layout.addWidget(self.merged_cells_checkbox)
        main_layout.addLayout(options_layout)

        self.merge_button = QPushButton("开始合并")
        self.merge_button.setMinimumHeight(48)
        self.merge_button.setMinimumWidth(230)
        self.merge_button.setFont(QFont("PingFang SC", 14, QFont.Bold))
        self.merge_button.setProperty("variant", "primary")
        merge_layout = QHBoxLayout()
        merge_layout.addStretch()
        merge_layout.addWidget(self.merge_button)
        merge_layout.addStretch()
        main_layout.addLayout(merge_layout)

        self.add_files_button.clicked.connect(self.add_files)
        self.add_folder_button.clicked.connect(self.add_folder)
        self.move_up_button.clicked.connect(self.move_up)
        self.move_down_button.clicked.connect(self.move_down)
        self.delete_button.clicked.connect(self.delete_selected)
        self.clear_button.clicked.connect(self.clear_files)
        self.choose_output_button.clicked.connect(self.choose_output_file)
        self.merge_button.clicked.connect(self.merge_files)
        self.back_home_button.clicked.connect(self.show_home)
        self.excel_settings_button.clicked.connect(self.show_settings)
        self.file_table.itemSelectionChanged.connect(self.update_button_states)

        self.refresh_file_list()
        self.apply_theme()

    def create_home_page(self):
        page = QWidget()
        page.setObjectName("homePage")
        layout = QVBoxLayout(page)
        self.home_layout = layout
        layout.setContentsMargins(40, 22, 40, 26)
        layout.setSpacing(10)

        top_layout = QHBoxLayout()
        top_layout.addStretch()
        self.home_settings_button = QPushButton("软件设置")
        self.home_settings_button.setMinimumHeight(32)
        self.home_settings_button.setProperty("variant", "ghost")
        self.home_settings_button.clicked.connect(self.show_settings)
        top_layout.addWidget(self.home_settings_button)
        layout.addLayout(top_layout)

        self.home_logo_pixmap = QPixmap(str(resource_path("assets/software_logo.png")))
        self.home_logo_label = QLabel()
        self.home_logo_label.setAlignment(Qt.AlignCenter)
        self.home_logo_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout.addWidget(self.home_logo_label)

        self.home_title_label = QLabel(self.app_name)
        self.home_title_label.setAlignment(Qt.AlignCenter)
        self.home_title_label.setFont(QFont("PingFang SC", 24, QFont.Bold))
        self.home_title_label.setProperty("role", "title")
        self.home_title_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout.addWidget(self.home_title_label)

        self.home_subtitle_label = QLabel("请选择需要使用的办公工具")
        self.home_subtitle_label.setAlignment(Qt.AlignCenter)
        self.home_subtitle_label.setProperty("role", "subtitle")
        self.home_subtitle_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout.addWidget(self.home_subtitle_label)

        self.home_grid = QGridLayout()
        self.home_grid.setSpacing(14)
        self.home_tool_buttons = []

        for index in range(12):
            button = QPushButton()
            button.setFont(QFont("PingFang SC", 13, QFont.Bold))

            if index == 0:
                button.setText("Excel 合并工具")
                button.setToolTip("按列表顺序合并多个 Excel 文件")
                button.setProperty("variant", "toolCardPrimary")
                button.clicked.connect(self.show_excel_tool)
            elif index == 1:
                button.setText("Excel 拆分工具")
                button.setToolTip("按表头和数据行数拆分一个 Excel 文件")
                button.setProperty("variant", "toolCardPrimary")
                button.clicked.connect(self.show_split_tool)
            elif index == 2:
                button.setText("PDF发票解析工具")
                button.setToolTip("解析 PDF 发票并输出财务结构化 Excel")
                button.setProperty("variant", "toolCardPrimary")
                button.clicked.connect(self.show_invoice_tool)
            elif index == 3:
                button.setText("文档智能处理")
                button.setToolTip("自动识别 PDF 类型并生成对应结果")
                button.setProperty("variant", "toolCardPrimary")
                button.clicked.connect(self.show_document_tool)
            elif index == 4:
                button.setText("批量改名工具")
                button.setToolTip("批量预览并重命名文件")
                button.setProperty("variant", "toolCardPrimary")
                button.clicked.connect(self.show_rename_tool)
            else:
                button.setText("敬请期待")
                button.setEnabled(False)
                button.setToolTip("预留功能入口")
                button.setProperty("variant", "toolCardEmpty")

            row = index // 3
            column = index % 3
            self.home_grid.addWidget(button, row, column)
            self.home_tool_buttons.append(button)

        layout.addLayout(self.home_grid)
        self.home_version_label = QLabel(f"版本 {APP_VERSION}")
        self.home_version_label.setAlignment(Qt.AlignCenter)
        self.home_version_label.setProperty("role", "hint")
        layout.addWidget(self.home_version_label)
        return page

    def create_split_page(self):
        page = QWidget()
        page.setObjectName("splitPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)

        tool_header_layout = QHBoxLayout()
        self.split_back_home_button = QPushButton("返回工具首页")
        self.split_back_home_button.setMinimumHeight(30)
        self.split_back_home_button.setProperty("variant", "ghost")
        self.split_settings_button = QPushButton("软件设置")
        self.split_settings_button.setMinimumHeight(30)
        self.split_settings_button.setProperty("variant", "ghost")
        tool_header_layout.addWidget(self.split_back_home_button)
        self.split_version_label = QLabel(f"版本 {APP_VERSION}")
        self.split_version_label.setProperty("role", "hint")
        tool_header_layout.addWidget(self.split_version_label)
        tool_header_layout.addStretch()
        tool_header_layout.addWidget(self.split_settings_button)
        layout.addLayout(tool_header_layout)

        title = QLabel("Excel 拆分工具")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("PingFang SC", 20, QFont.Bold))
        title.setProperty("role", "title")
        layout.addWidget(title)

        subtitle = QLabel("选择一个 Excel 文件，按表头和数据行数拆分成多个文件")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setProperty("role", "subtitle")
        layout.addWidget(subtitle)

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

        output_group = QGroupBox("输出文件夹")
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
        options_layout.setAlignment(Qt.AlignCenter)

        header_rows_label = QLabel("表头行数：")
        self.split_header_rows_spinbox = QSpinBox()
        self.split_header_rows_spinbox.setRange(0, 999)
        self.split_header_rows_spinbox.setValue(1)
        self.split_header_rows_spinbox.setSuffix(" 行")
        self.split_header_rows_spinbox.setMinimumWidth(105)
        self.split_header_rows_spinbox.setToolTip(
            "例如填 2，表示第 1 到第 2 行会作为表头复制到每个拆分文件。"
        )

        rows_per_file_label = QLabel("每个文件数据行数：")
        self.split_rows_per_file_spinbox = QSpinBox()
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
        layout.addWidget(options_group)
        layout.addStretch(1)

        self.split_button = QPushButton("开始拆分")
        self.split_button.setMinimumHeight(48)
        self.split_button.setMinimumWidth(230)
        self.split_button.setFont(QFont("PingFang SC", 14, QFont.Bold))
        self.split_button.setProperty("variant", "primary")
        split_button_layout = QHBoxLayout()
        split_button_layout.addStretch()
        split_button_layout.addWidget(self.split_button)
        split_button_layout.addStretch()
        layout.addLayout(split_button_layout)

        self.split_back_home_button.clicked.connect(self.show_home)
        self.split_settings_button.clicked.connect(self.show_settings)
        self.choose_split_source_button.clicked.connect(self.choose_split_source_file)
        self.choose_split_output_button.clicked.connect(self.choose_split_output_folder)
        self.split_button.clicked.connect(self.split_workbook)
        return page

    def create_invoice_page(self):
        page = QWidget()
        page.setObjectName("invoicePage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)

        tool_header_layout = QHBoxLayout()
        self.invoice_back_home_button = QPushButton("返回工具首页")
        self.invoice_back_home_button.setMinimumHeight(30)
        self.invoice_back_home_button.setProperty("variant", "ghost")
        self.invoice_settings_button = QPushButton("软件设置")
        self.invoice_settings_button.setMinimumHeight(30)
        self.invoice_settings_button.setProperty("variant", "ghost")
        tool_header_layout.addWidget(self.invoice_back_home_button)
        self.invoice_version_label = QLabel(f"版本 {APP_VERSION}")
        self.invoice_version_label.setProperty("role", "hint")
        tool_header_layout.addWidget(self.invoice_version_label)
        tool_header_layout.addStretch()
        tool_header_layout.addWidget(self.invoice_settings_button)
        layout.addLayout(tool_header_layout)

        title = QLabel("PDF发票解析工具")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("PingFang SC", 20, QFont.Bold))
        title.setProperty("role", "title")
        layout.addWidget(title)

        subtitle = QLabel("统一提取发票头信息和明细，自动校验金额与税额")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setProperty("role", "subtitle")
        layout.addWidget(subtitle)

        source_button_layout = QHBoxLayout()
        source_button_layout.setSpacing(10)
        self.choose_invoice_source_button = QPushButton("添加 PDF 发票")
        self.delete_invoice_source_button = QPushButton("删除选中")
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
            "每张 PDF 独立生成一个 Excel；单个失败不影响其他发票。扫描图片型 PDF 暂不支持。"
        )
        hint.setAlignment(Qt.AlignCenter)
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.invoice_convert_button = QPushButton("开始识别并生成 Excel")
        self.invoice_convert_button.setMinimumHeight(48)
        self.invoice_convert_button.setMinimumWidth(260)
        self.invoice_convert_button.setFont(QFont("PingFang SC", 14, QFont.Bold))
        self.invoice_convert_button.setProperty("variant", "primary")
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.invoice_convert_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        self.invoice_back_home_button.clicked.connect(self.show_home)
        self.invoice_settings_button.clicked.connect(self.show_settings)
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

    def create_document_page(self):
        page = QWidget()
        page.setObjectName("documentPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)

        tool_header_layout = QHBoxLayout()
        self.document_back_home_button = QPushButton("返回工具首页")
        self.document_back_home_button.setMinimumHeight(30)
        self.document_back_home_button.setProperty("variant", "ghost")
        self.document_settings_button = QPushButton("软件设置")
        self.document_settings_button.setMinimumHeight(30)
        self.document_settings_button.setProperty("variant", "ghost")
        tool_header_layout.addWidget(self.document_back_home_button)
        self.document_version_label = QLabel(f"版本 {APP_VERSION}")
        self.document_version_label.setProperty("role", "hint")
        tool_header_layout.addWidget(self.document_version_label)
        tool_header_layout.addStretch()
        tool_header_layout.addWidget(self.document_settings_button)
        layout.addLayout(tool_header_layout)

        title = QLabel("文档智能处理")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("PingFang SC", 20, QFont.Bold))
        title.setProperty("role", "title")
        layout.addWidget(title)

        subtitle = QLabel("自动识别发票、合同和表格类 PDF，并生成对应结果")
        subtitle.setAlignment(Qt.AlignCenter)
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

        result_group = QGroupBox("处理结果")
        result_layout = QVBoxLayout(result_group)
        self.document_status_label = QLabel("等待选择 PDF 文件")
        self.document_status_label.setProperty("role", "status")
        self.document_result_path_edit = QLineEdit()
        self.document_result_path_edit.setReadOnly(True)
        self.document_result_path_edit.setPlaceholderText("处理完成后在这里显示结果路径")
        self.document_result_path_edit.setMinimumHeight(34)
        result_layout.addWidget(self.document_status_label)
        result_layout.addWidget(self.document_result_path_edit)
        layout.addWidget(result_group)

        hint = QLabel(
            "处理顺序：PDF 分类 → 路由 → 输出。当前版本不含 OCR，"
            "扫描图片型 PDF 将输出 UNKNOWN 文本说明。"
        )
        hint.setAlignment(Qt.AlignCenter)
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)

        button_layout = QHBoxLayout()
        self.document_process_button = QPushButton("一键识别并处理")
        self.document_process_button.setMinimumHeight(48)
        self.document_process_button.setMinimumWidth(230)
        self.document_process_button.setFont(QFont("PingFang SC", 14, QFont.Bold))
        self.document_process_button.setProperty("variant", "primary")
        self.open_document_result_button = QPushButton("打开结果")
        self.open_document_result_button.setMinimumHeight(48)
        self.open_document_result_button.setMinimumWidth(140)
        button_layout.addStretch()
        button_layout.addWidget(self.document_process_button)
        button_layout.addWidget(self.open_document_result_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        self.document_back_home_button.clicked.connect(self.show_home)
        self.document_settings_button.clicked.connect(self.show_settings)
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
        self.update_document_button_states()
        return page

    def create_rename_page(self):
        page = QWidget()
        page.setObjectName("renamePage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)

        tool_header_layout = QHBoxLayout()
        self.rename_back_home_button = QPushButton("返回工具首页")
        self.rename_back_home_button.setMinimumHeight(30)
        self.rename_back_home_button.setProperty("variant", "ghost")
        self.rename_settings_button = QPushButton("软件设置")
        self.rename_settings_button.setMinimumHeight(30)
        self.rename_settings_button.setProperty("variant", "ghost")
        tool_header_layout.addWidget(self.rename_back_home_button)
        self.rename_version_label = QLabel(f"版本 {APP_VERSION}")
        self.rename_version_label.setProperty("role", "hint")
        tool_header_layout.addWidget(self.rename_version_label)
        tool_header_layout.addStretch()
        tool_header_layout.addWidget(self.rename_settings_button)
        layout.addLayout(tool_header_layout)

        title = QLabel("批量改名工具")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("PingFang SC", 20, QFont.Bold))
        title.setProperty("role", "title")
        layout.addWidget(title)

        subtitle = QLabel("先预览新文件名，确认无重名和异常后再执行")
        subtitle.setAlignment(Qt.AlignCenter)
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
        self.rename_delete_button = QPushButton("删除选中")
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

        self.rename_rule_combo = QComboBox()
        for label_text, rule_key in (
            ("替换文字", "replace"),
            ("删除指定文字", "delete_text"),
            ("删除开头几个字", "trim_start"),
            ("删除结尾几个字", "trim_end"),
            ("前面追加文字", "prefix"),
            ("后面追加文字", "suffix"),
            ("修改后缀", "extension"),
        ):
            self.rename_rule_combo.addItem(label_text, rule_key)
        self.rename_rule_primary_label = QLabel("查找文字：")
        self.rename_rule_primary_edit = QLineEdit()
        self.rename_rule_secondary_label = QLabel("替换为：")
        self.rename_rule_secondary_edit = QLineEdit()
        self.rename_rule_count_label = QLabel("删除数量：")
        self.rename_rule_count_spinbox = QSpinBox()
        self.rename_rule_count_spinbox.setRange(1, 999)
        self.rename_rule_count_spinbox.setValue(1)
        self.rename_numbering_checkbox = QCheckBox("添加编号")
        self.rename_number_start_spinbox = QSpinBox()
        self.rename_number_start_spinbox.setRange(0, 999999)
        self.rename_number_start_spinbox.setValue(1)
        self.rename_number_digits_spinbox = QSpinBox()
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

        number_layout = QHBoxLayout()
        number_layout.setSpacing(8)
        self.rename_number_start_spinbox.setMinimumWidth(90)
        self.rename_number_digits_spinbox.setMinimumWidth(78)
        number_layout.addWidget(self.rename_numbering_checkbox)
        number_layout.addWidget(QLabel("起始"))
        number_layout.addWidget(self.rename_number_start_spinbox)
        number_layout.addWidget(QLabel("位数"))
        number_layout.addWidget(self.rename_number_digits_spinbox)
        rules_layout.addLayout(number_layout)
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
        right_layout.addWidget(log_group)

        action_layout = QHBoxLayout()
        self.rename_preview_button = QPushButton("刷新预览")
        self.rename_execute_button = QPushButton("开始改名")
        self.rename_preview_button.setMinimumHeight(44)
        self.rename_execute_button.setMinimumHeight(48)
        self.rename_execute_button.setMinimumWidth(170)
        self.rename_execute_button.setFont(QFont("PingFang SC", 14, QFont.Bold))
        self.rename_execute_button.setProperty("variant", "primary")
        action_layout.addWidget(self.rename_preview_button)
        action_layout.addWidget(self.rename_execute_button, 1)
        right_layout.addLayout(action_layout)
        right_layout.addStretch(1)
        content_layout.addLayout(right_layout, 1)
        layout.addLayout(content_layout, 1)

        self.rename_back_home_button.clicked.connect(self.show_home)
        self.rename_settings_button.clicked.connect(self.show_settings)
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

        self.rename_rule_combo.currentIndexChanged.connect(
            self.handle_rename_rule_changed
        )
        self.rename_rule_primary_edit.textChanged.connect(
            lambda _text: self.refresh_rename_file_list()
        )
        self.rename_rule_secondary_edit.textChanged.connect(
            lambda _text: self.refresh_rename_file_list()
        )
        self.rename_rule_count_spinbox.valueChanged.connect(
            lambda _value: self.refresh_rename_file_list()
        )
        self.rename_numbering_checkbox.toggled.connect(
            lambda _checked: self.refresh_rename_file_list()
        )
        self.rename_number_start_spinbox.valueChanged.connect(
            lambda _value: self.refresh_rename_file_list()
        )
        self.rename_number_digits_spinbox.valueChanged.connect(
            lambda _value: self.refresh_rename_file_list()
        )
        self.update_rename_rule_inputs()
        self.refresh_rename_file_list()
        return page

    def update_home_responsive_layout(self):
        if not hasattr(self, "home_tool_buttons"):
            return

        width = max(self.home_page.width(), self.width())
        height = max(self.home_page.height(), self.height())
        side_margin = max(28, min(56, int(width * 0.04)))
        top_margin = max(14, min(28, int(height * 0.025)))
        bottom_margin = max(18, min(32, int(height * 0.03)))
        spacing = max(6, min(14, int(height * 0.014)))

        self.home_layout.setContentsMargins(
            side_margin,
            top_margin,
            side_margin,
            bottom_margin,
        )
        self.home_layout.setSpacing(spacing)

        logo_width = max(210, min(340, int(width * 0.22)))
        logo_height = max(58, min(96, int(height * 0.12)))
        if not self.home_logo_pixmap.isNull():
            self.home_logo_label.setPixmap(
                self.home_logo_pixmap.scaled(
                    QSize(logo_width, logo_height),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
        self.home_logo_label.setFixedHeight(logo_height)

        title_size = max(20, min(26, int(height * 0.035)))
        subtitle_size = max(11, min(14, int(height * 0.018)))
        self.home_title_label.setFont(QFont("PingFang SC", title_size, QFont.Bold))
        self.home_subtitle_label.setFont(QFont("PingFang SC", subtitle_size))
        self.home_title_label.setFixedHeight(title_size + 20)
        self.home_subtitle_label.setFixedHeight(subtitle_size + 14)

        grid_spacing = max(8, min(18, int(height * 0.018)))
        self.home_grid.setHorizontalSpacing(grid_spacing)
        self.home_grid.setVerticalSpacing(grid_spacing)

        available_width = max(540, width - side_margin * 2)
        reserved_height = (
            top_margin
            + bottom_margin
            + 34
            + logo_height
            + title_size * 2
            + subtitle_size * 2
            + spacing * 5
        )
        available_grid_height = max(260, height - reserved_height)

        card_width = max(150, int((available_width - grid_spacing * 2) / 3))
        card_height = max(
            54,
            min(132, int((available_grid_height - grid_spacing * 3) / 4)),
        )
        card_font_size = max(11, min(16, int(card_height * 0.17)))

        for button in self.home_tool_buttons:
            button.setFixedSize(card_width, card_height)
            button.setFont(QFont("PingFang SC", card_font_size, QFont.Bold))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_home_responsive_layout()

    def show_home(self):
        self.stack.setCurrentWidget(self.home_page)
        self.setWindowTitle(self.app_name)

    def show_excel_tool(self):
        self.stack.setCurrentWidget(self.excel_page)
        self.setWindowTitle(f"{self.app_name} - Excel 合并工具")

    def show_split_tool(self):
        self.stack.setCurrentWidget(self.split_page)
        self.setWindowTitle(f"{self.app_name} - Excel 拆分工具")

    def show_invoice_tool(self):
        self.stack.setCurrentWidget(self.invoice_page)
        self.setWindowTitle(f"{self.app_name} - PDF发票解析工具")

    def show_document_tool(self):
        self.stack.setCurrentWidget(self.document_page)
        self.setWindowTitle(f"{self.app_name} - 文档智能处理")

    def show_rename_tool(self):
        self.stack.setCurrentWidget(self.rename_page)
        self.setWindowTitle(f"{self.app_name} - 批量改名工具")

    def show_settings(self):
        accent_keys = list(ACCENT_PALETTES)
        labels = [ACCENT_PALETTES[key]["label"] for key in accent_keys]
        selected_label, accepted = QInputDialog.getItem(
            self,
            "软件设置",
            "主题色调：",
            labels,
            accent_keys.index(self.accent_name),
            False,
        )
        if accepted:
            self.save_accent_setting(accent_keys[labels.index(selected_label)])

    def save_accent_setting(self, accent_name):
        if accent_name not in ACCENT_PALETTES:
            return
        self.accent_name = accent_name
        self.settings.setValue("appearance/accent", self.accent_name)
        self.settings.sync()
        self.apply_theme()

    def apply_theme(self):
        colors = build_theme_colors(self.accent_name)
        self.setStyleSheet(build_theme_stylesheet(colors))

    def refresh_file_list(self, selected_row=None):
        self.refreshing_list = True
        self.checked_files.intersection_update(self.files)
        self.file_table.clear()

        if not self.files:
            empty_item = QTreeWidgetItem(
                ["", "暂无文件，请添加 Excel 文件", "", "", ""]
            )
            empty_item.setFlags(Qt.NoItemFlags)
            self.file_table.addTopLevelItem(empty_item)
            self.status_label.setText("尚未添加文件")
        else:
            for index, filename in enumerate(self.files, start=1):
                path = Path(filename)
                info = self.file_info.get(filename, {})
                item = QTreeWidgetItem(
                    [
                        f"{index:03d}",
                        path.name,
                        info.get("size", "读取中"),
                        str(info.get("rows", "读取中")),
                        filename,
                    ]
                )
                item.setData(0, Qt.UserRole, filename)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if filename in self.checked_files
                    else Qt.CheckState.Unchecked,
                )
                item.setTextAlignment(0, Qt.AlignCenter)
                item.setTextAlignment(2, Qt.AlignCenter)
                item.setTextAlignment(3, Qt.AlignCenter)
                item.setToolTip(1, filename)
                item.setToolTip(4, filename)
                self.file_table.addTopLevelItem(item)

            self.update_file_status()
            if selected_row is not None:
                selected_row = max(0, min(selected_row, len(self.files) - 1))
                self.file_table.setCurrentItem(
                    self.file_table.topLevelItem(selected_row)
                )

        self.refreshing_list = False
        self.update_button_states()

    def checked_file_paths(self):
        return [filename for filename in self.files if filename in self.checked_files]

    def update_file_status(self):
        checked_count = len(self.checked_file_paths())
        if checked_count:
            self.status_label.setText(
                f"已勾选 {checked_count} 个文件，列表共 {len(self.files)} 个"
            )
        else:
            self.status_label.setText(f"列表中共有 {len(self.files)} 个文件")

    def handle_file_item_changed(self, item, column):
        if self.refreshing_list or column != 0:
            return

        filename = item.data(0, Qt.UserRole)
        if not filename:
            return

        if item.checkState(0) == Qt.CheckState.Checked:
            self.checked_files.add(filename)
        else:
            self.checked_files.discard(filename)

        self.update_file_status()
        self.update_button_states()

    def update_button_states(self):
        has_files = bool(self.files)
        current_item = self.file_table.currentItem()
        has_selection = (
            has_files
            and current_item is not None
            and bool(current_item.data(0, Qt.UserRole))
        )
        has_checked_files = bool(self.checked_file_paths())
        self.move_up_button.setEnabled(has_selection)
        self.move_down_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_checked_files)
        self.clear_button.setEnabled(has_files)
        self.merge_button.setEnabled(has_files and bool(self.output_file))

    def add_paths(self, paths):
        existing = set(self.files)
        new_paths = []

        for path in paths:
            normalized_path = os.path.abspath(path)
            if normalized_path not in existing:
                self.files.append(normalized_path)
                existing.add(normalized_path)
                new_paths.append(normalized_path)

        if new_paths:
            progress = QProgressDialog(
                "正在读取文件信息...",
                "",
                0,
                len(new_paths),
                self,
            )
            progress.setWindowTitle("读取 Excel 文件")
            progress.setCancelButton(None)
            progress.setMinimumDuration(0)
            progress.setWindowModality(Qt.WindowModal)
            progress.show()

            for index, filename in enumerate(new_paths, start=1):
                progress.setLabelText(f"正在读取：{os.path.basename(filename)}")
                QApplication.processEvents()
                try:
                    self.file_info[filename] = get_file_info(filename)
                except Exception as error:
                    self.file_info[filename] = {
                        "size": format_file_size(os.path.getsize(filename)),
                        "rows": "无法读取",
                    }
                    QMessageBox.warning(
                        self,
                        "文件信息读取失败",
                        f"{os.path.basename(filename)}\n{error}",
                    )
                progress.setValue(index)

            progress.close()

        self.refresh_file_list(
            selected_row=len(self.files) - 1 if self.files else None
        )
        return len(new_paths)

    def add_files(self):
        downloads = str(Path.home() / "Downloads")
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "选择 Excel 文件",
            downloads,
            "Excel 文件 (*.xlsx *.xlsm)",
        )
        if not filenames:
            return

        added_count = self.add_paths(filenames)
        self.status_label.setText(
            f"已添加 {added_count} 个文件，列表共 {len(self.files)} 个"
        )

    def add_folder(self):
        downloads = str(Path.home() / "Downloads")
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择 Excel 文件夹",
            downloads,
            QFileDialog.ShowDirsOnly,
        )
        if folder:
            self.load_folder(folder)

    def load_folder(self, folder, show_messages=True):
        try:
            excel_files = discover_excel_files(folder)
        except OSError as error:
            if show_messages:
                QMessageBox.critical(self, "无法读取文件夹", str(error))
            return 0

        if not excel_files:
            if show_messages:
                QMessageBox.warning(
                    self,
                    "未找到 Excel 文件",
                    "所选文件夹及其子文件夹中没有找到 .xlsx 或 .xlsm 文件。",
                )
            return 0

        added_count = self.add_paths(excel_files)
        self.status_label.setText(
            f"已添加 {added_count} 个文件，列表共 {len(self.files)} 个"
        )
        return added_count

    def move_up(self):
        current_item = self.file_table.currentItem()
        if current_item is None:
            return

        row = self.file_table.indexOfTopLevelItem(current_item)
        if row <= 0 or not self.files:
            return

        self.files[row - 1], self.files[row] = self.files[row], self.files[row - 1]
        self.refresh_file_list(selected_row=row - 1)

    def move_down(self):
        current_item = self.file_table.currentItem()
        if current_item is None:
            return

        row = self.file_table.indexOfTopLevelItem(current_item)
        if row < 0 or row >= len(self.files) - 1:
            return

        self.files[row + 1], self.files[row] = self.files[row], self.files[row + 1]
        self.refresh_file_list(selected_row=row + 1)

    def confirm_list_change(self, text):
        return QMessageBox.question(
            self,
            "确认操作",
            text,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) == QMessageBox.Yes

    def delete_selected(self):
        checked_paths = self.checked_file_paths()
        if not checked_paths:
            return

        if not self.confirm_list_change("是否删除选中的文件"):
            return

        first_deleted_row = min(self.files.index(filename) for filename in checked_paths)
        checked_set = set(checked_paths)
        self.files = [filename for filename in self.files if filename not in checked_set]
        for filename in checked_paths:
            self.file_info.pop(filename, None)
        self.checked_files.difference_update(checked_set)

        selected_row = min(first_deleted_row, len(self.files) - 1) if self.files else None
        self.refresh_file_list(selected_row=selected_row)

    def clear_files(self):
        if not self.files:
            return
        if not self.confirm_list_change("是否清空列表"):
            return

        self.files = []
        self.file_info = {}
        self.checked_files.clear()
        self.refresh_file_list()

    def choose_output_file(self):
        default_path = Path.home() / "Downloads" / default_output_filename(
            self.system_locale
        )
        output_file, _ = QFileDialog.getSaveFileName(
            self,
            "保存合并结果",
            str(default_path),
            "Excel (*.xlsx)",
        )
        if not output_file:
            return
        if not output_file.lower().endswith(".xlsx"):
            output_file += ".xlsx"

        self.output_file = os.path.abspath(output_file)
        self.output_path_edit.setText(self.output_file)
        self.output_path_edit.setToolTip(self.output_file)
        self.update_button_states()

    def current_rename_rule(self):
        return self.rename_rule_combo.currentData() or "replace"

    def handle_rename_rule_changed(self, *_args):
        self.rename_rule_primary_edit.clear()
        self.rename_rule_secondary_edit.clear()
        self.rename_rule_count_spinbox.setValue(1)
        self.update_rename_rule_inputs()
        self.refresh_rename_file_list()

    def update_rename_rule_inputs(self):
        rule = self.current_rename_rule()
        count_rule = rule in ("trim_start", "trim_end")
        two_text_rule = rule == "replace"
        one_text_rule = rule in ("delete_text", "prefix", "suffix", "extension")

        labels = {
            "replace": ("查找文字：", "替换为："),
            "delete_text": ("删除文字：", ""),
            "prefix": ("前面追加：", ""),
            "suffix": ("后面追加：", ""),
            "extension": ("新后缀：", ""),
            "trim_start": ("删除数量：", ""),
            "trim_end": ("删除数量：", ""),
        }
        primary_label, secondary_label = labels.get(rule, labels["replace"])
        self.rename_rule_primary_label.setText(primary_label)
        self.rename_rule_secondary_label.setText(secondary_label)

        self.rename_rule_primary_label.setVisible(one_text_rule or two_text_rule)
        self.rename_rule_primary_edit.setVisible(one_text_rule or two_text_rule)
        self.rename_rule_secondary_label.setVisible(two_text_rule)
        self.rename_rule_secondary_edit.setVisible(two_text_rule)
        self.rename_rule_count_label.setVisible(count_rule)
        self.rename_rule_count_spinbox.setVisible(count_rule)

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
            numbering_enabled=self.rename_numbering_checkbox.isChecked(),
            number_start=self.rename_number_start_spinbox.value(),
            number_digits=self.rename_number_digits_spinbox.value(),
        )

    def refresh_rename_file_list(self):
        self.rename_file_table.clear()
        self.rename_previews = list(
            preview_renames(self.rename_source_files, self.rename_options())
        )
        if not self.rename_source_files:
            empty_item = QTreeWidgetItem(
                ["", "暂无文件，请添加需要改名的文件", "", "", ""]
            )
            empty_item.setFlags(Qt.NoItemFlags)
            self.rename_file_table.addTopLevelItem(empty_item)
            self.rename_status_label.setText("尚未添加文件")
        else:
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
                self.rename_file_table.addTopLevelItem(item)

            blocked_count = sum(1 for preview in self.rename_previews if preview.blocked)
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
        self.refresh_rename_file_list()
        self.warn_blank_rename_preview()

    def update_rename_button_states(self):
        has_files = bool(self.rename_source_files)
        has_selection = any(
            item.data(0, Qt.UserRole)
            for item in self.rename_file_table.selectedItems()
        )
        can_rename = (
            has_files
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
        for path in paths:
            normalized = os.path.abspath(path)
            if normalized not in existing and Path(normalized).is_file():
                self.rename_source_files.append(normalized)
                existing.add(normalized)
        self.refresh_rename_file_list()

    def add_rename_files(self):
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "选择需要改名的文件",
            str(Path.home() / "Downloads"),
            "所有文件 (*)",
        )
        if filenames:
            self.add_rename_paths(filenames)

    def add_rename_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择需要批量改名的文件夹",
            str(Path.home() / "Downloads"),
            QFileDialog.ShowDirsOnly,
        )
        if not folder:
            return
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
        ok_button = message.addButton("确 定", QMessageBox.AcceptRole)
        for button in (ok_button, open_button):
            button.setFixedSize(112, 36)
        message.setDefaultButton(ok_button)
        message.exec()
        if message.clickedButton() == open_button:
            self.open_output_file(result.log_file)

    def rename_files(self):
        self.refresh_rename_file_list()
        if not self.rename_source_files:
            QMessageBox.warning(self, "尚未添加文件", "请先添加需要改名的文件。")
            return
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

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = apply_renames(self.rename_previews)
        except Exception as error:
            QMessageBox.critical(self, "改名失败", str(error))
            return
        finally:
            QApplication.restoreOverrideCursor()

        self.rename_last_log_file = result.log_file
        self.rename_log_path_edit.setText(result.log_file)
        self.rename_log_path_edit.setToolTip(result.log_file)
        self.rename_source_files = [
            action.target_path if action.status == "成功" else action.source_path
            for action in result.actions
        ]
        self.refresh_rename_file_list()
        self.show_rename_complete_message(result)

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
            str(Path.home() / "Downloads"),
            "PDF 文件 (*.pdf)",
        )
        if not filenames:
            return
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
            self.invoice_output_folder or str(Path.home() / "Downloads"),
        )
        if not output_folder:
            return
        self.invoice_output_folder = os.path.abspath(output_folder)
        self.invoice_output_path_edit.setText(self.invoice_output_folder)
        self.invoice_output_path_edit.setToolTip(self.invoice_output_folder)
        self.update_invoice_button_states()

    def show_invoice_complete_message(self, results, failures):
        message = QMessageBox(self)
        message.setWindowTitle("批量发票解析完成")
        message.setIcon(QMessageBox.Warning if failures else QMessageBox.Information)
        message.setText(f"成功 {len(results)} 个，失败 {len(failures)} 个")
        item_count = sum(result.item_count for result in results)
        abnormal_count = sum(result.abnormal_count for result in results)
        message.setInformativeText(
            f"保存文件夹：\n{self.invoice_output_folder}\n\n"
            f"明细行数：{item_count}\n校验异常：{abnormal_count} 项"
        )
        if failures:
            message.setDetailedText(
                "\n".join(f"{Path(path).name}：{error}" for path, error in failures)
            )
        open_button = message.addButton("打开文件夹", QMessageBox.ActionRole)
        ok_button = message.addButton("确 定", QMessageBox.AcceptRole)
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

        progress = QProgressDialog("正在解析 PDF 发票…", "", 0, len(self.invoice_source_files), self)
        progress.setWindowTitle("正在批量解析发票")
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        def update_progress(value, total, text):
            progress.setMaximum(total)
            progress.setValue(value)
            progress.setLabelText(text)
            QApplication.processEvents()

        results = []
        failures = []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            results, failures = convert_invoice_pdfs(
                self.invoice_source_files,
                self.invoice_output_folder,
                progress_callback=update_progress,
            )
        except Exception as error:
            QMessageBox.critical(
                self,
                "发票识别失败",
                f"{error}\n\n未生成未结构化文本或不完整 Excel。",
            )
        finally:
            QApplication.restoreOverrideCursor()
            progress.close()

        if results or failures:
            self.show_invoice_complete_message(results, failures)

    def update_document_button_states(self):
        self.document_process_button.setEnabled(
            bool(self.document_source_file and self.document_output_folder)
        )
        self.open_document_result_button.setEnabled(
            bool(self.document_result_file and Path(self.document_result_file).exists())
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
        self.document_source_path_edit.setText(self.document_source_file)
        self.document_source_path_edit.setToolTip(self.document_source_file)
        self.document_output_path_edit.setText(self.document_output_folder)
        self.document_output_path_edit.setToolTip(self.document_output_folder)
        self.document_result_path_edit.clear()
        self.document_status_label.setText("已选择 PDF，可开始一键处理")
        self.update_document_button_states()
        return True

    def choose_document_source_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择要智能处理的 PDF",
            str(Path.home() / "Downloads"),
            "PDF 文件 (*.pdf)",
        )
        if not filename:
            return

        self.set_document_source_file(filename)

    def choose_document_output_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择结果保存文件夹",
            self.document_output_folder or str(Path.home() / "Downloads"),
            QFileDialog.ShowDirsOnly,
        )
        if not folder:
            return

        self.document_output_folder = os.path.abspath(folder)
        self.document_result_file = ""
        self.document_output_path_edit.setText(self.document_output_folder)
        self.document_output_path_edit.setToolTip(self.document_output_folder)
        self.document_result_path_edit.clear()
        self.document_status_label.setText("保存位置已更新，可开始处理")
        self.update_document_button_states()

    def process_smart_document(self):
        if not self.document_source_file or not self.document_output_folder:
            QMessageBox.warning(self, "尚未完成设置", "请先选择 PDF 文件。")
            return

        progress = QProgressDialog("正在读取 PDF…", "", 0, 0, self)
        progress.setWindowTitle("文档智能处理")
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        def update_progress(value, total, text):
            progress.setMaximum(max(total, 1))
            progress.setValue(value)
            progress.setLabelText(text)
            self.document_status_label.setText(text)
            QApplication.processEvents()

        self.document_result_file = ""
        self.document_result_path_edit.clear()
        self.document_status_label.setText("正在识别文档类型…")
        self.update_document_button_states()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        error_detail = ""
        try:
            if self.document_enhanced_layout_checkbox.isChecked():
                result = process_layout_document(
                    self.document_source_file,
                    self.document_output_folder,
                    progress_callback=update_progress,
                    style_template="formal_contract",
                )
            else:
                result = process_document(
                    self.document_source_file,
                    self.document_output_folder,
                    progress_callback=update_progress,
                )
        except Exception as error:
            result = {
                "doc_type": "UNKNOWN",
                "confidence": 0.0,
                "output_file": "",
                "status": "failed",
            }
            error_detail = f"\n\n错误信息：{error}"
        finally:
            QApplication.restoreOverrideCursor()
            progress.close()

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
        ok_button = message.addButton("确 定", QMessageBox.AcceptRole)
        for button in (ok_button, open_button):
            button.setFixedSize(112, 36)
        message.setDefaultButton(ok_button)
        message.exec()
        if message.clickedButton() == open_button:
            self.open_output_file(self.document_result_file)

    def choose_split_source_file(self):
        downloads = str(Path.home() / "Downloads")
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择要拆分的 Excel 文件",
            downloads,
            "Excel 文件 (*.xlsx)",
        )
        if not filename:
            return

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

        try:
            info = get_file_info(self.split_source_file)
            self.split_source_status_label.setText(
                f"已选择文件，大小 {info['size']}，共 {info['rows']} 行（含表头）"
            )
        except Exception as error:
            self.split_source_status_label.setText("已选择文件，但暂时无法读取行数")
            QMessageBox.warning(
                self,
                "文件信息读取失败",
                f"{os.path.basename(self.split_source_file)}\n{error}",
            )

    def choose_split_output_folder(self):
        downloads = str(Path.home() / "Downloads")
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择输出文件夹",
            downloads,
            QFileDialog.ShowDirsOnly,
        )
        if not folder:
            return

        self.split_output_folder = os.path.abspath(folder)
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
        ok_button = message.addButton("确 定", QMessageBox.AcceptRole)
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
                "尚未选择输出文件夹",
                "请先选择输出文件夹。",
            )
            return

        header_rows = self.split_header_rows_spinbox.value()
        rows_per_file = self.split_rows_per_file_spinbox.value()

        progress = QProgressDialog(
            "正在准备拆分...",
            "",
            0,
            0,
            self,
        )
        progress.setWindowTitle("正在拆分")
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        def update_progress(value, total, filename):
            progress.setMaximum(total)
            progress.setValue(value)
            progress.setLabelText(
                f"正在拆分：第 {value} / {total} 个文件\n正在生成：{filename}"
            )
            QApplication.processEvents()

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            split_result = split_workbook_by_rows(
                self.split_source_file,
                self.split_output_folder,
                rows_per_file=rows_per_file,
                header_rows=header_rows,
                progress_callback=update_progress,
            )
        except Exception as error:
            QMessageBox.critical(
                self,
                "拆分失败",
                "出现错误：\n"
                f"{error}\n\n"
                "建议检查文件是否正在被 Excel 打开、损坏、加密或包含特殊格式。",
            )
            return
        finally:
            QApplication.restoreOverrideCursor()
            progress.close()

        self.split_result_folder = split_result.output_folder
        self.show_split_complete_message(split_result)

    def open_output_file(self, output_file=None):
        output_file = output_file or self.output_file
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(output_file))
        if not opened:
            QMessageBox.warning(
                self,
                "无法打开文件",
                "合并已完成，但无法打开文件：\n"
                f"{output_file}",
            )
        return opened

    def show_merge_complete_message(self):
        message = QMessageBox(self)
        message.setWindowTitle("合并完成")
        message.setIcon(QMessageBox.Information)
        message.setText("合并完成")
        message.setInformativeText(f"保存位置：\n{self.output_file}")
        open_button = message.addButton("打 开 文 件", QMessageBox.ActionRole)
        ok_button = message.addButton("确 定", QMessageBox.AcceptRole)
        for button in (ok_button, open_button):
            button.setFixedSize(112, 36)
        message.setDefaultButton(ok_button)
        message.exec()
        if message.clickedButton() == open_button:
            self.open_output_file()

    def merge_files(self):
        if not self.files or not self.output_file:
            QMessageBox.warning(
                self,
                "尚未完成设置",
                "请先添加 Excel 文件并选择保存位置。",
            )
            return

        if os.path.realpath(self.output_file) in {
            os.path.realpath(filename) for filename in self.files
        }:
            QMessageBox.warning(
                self,
                "无法保存",
                "保存位置不能与待合并的源文件相同，请选择新的文件名。",
            )
            return

        progress = QProgressDialog(
            "正在准备合并...",
            "",
            0,
            len(self.files),
            self,
        )
        progress.setWindowTitle("正在合并")
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        def update_progress(value, filename):
            progress.setValue(value)
            progress.setLabelText(f"正在处理：{filename}")
            QApplication.processEvents()

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            build_merged_workbook(
                self.files,
                self.output_file,
                skip_rows=self.skip_rows_spinbox.value(),
                keep_merged_cells=self.merged_cells_checkbox.isChecked(),
                progress_callback=update_progress,
            )
        except Exception as error:
            QMessageBox.critical(
                self,
                "合并失败",
                "出现错误：\n"
                f"{error}\n\n"
                "建议检查文件是否正在被 Excel 打开、损坏、加密或包含特殊格式。",
            )
            return
        finally:
            QApplication.restoreOverrideCursor()
            progress.close()

        self.show_merge_complete_message()
