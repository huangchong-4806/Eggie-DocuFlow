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


APP_NAME_ZH = "Excel 合并拆分工具"
APP_NAME_EN = "Eggie Excel Tool"


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
    QWidget#splitPage {{
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
    QSpinBox {{
        background: {colors["input"]};
        color: {colors["text"]};
        border: 1px solid {colors["border"]};
        border-radius: 8px;
        padding: 6px 10px;
        min-height: 24px;
    }}
    QLineEdit:focus,
    QSpinBox:focus {{
        border: 1px solid {colors["accent"]};
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
        self.refreshing_list = False
        self.settings = QSettings("ExcelMergeTool", "MacSimpleOfficeTools")
        self.accent_name = self.settings.value("appearance/accent", "cyan")
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

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.home_page = self.create_home_page()
        self.excel_page = QWidget()
        self.excel_page.setObjectName("excelPage")
        self.split_page = self.create_split_page()
        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.excel_page)
        self.stack.addWidget(self.split_page)
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
