import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from PySide6.QtCore import (
    QLibraryInfo,
    QLocale,
    QThread,
    QTimer,
    QSize,
    QSettings,
    Qt,
    QTranslator,
    QUrl,
)
from PySide6.QtGui import (
    QDesktopServices,
    QFont,
    QIcon,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
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
from excel_cleanup_tool import (
    CleanupOptions,
    clean_workbook,
    preview_cleanup,
    workbook_sheet_names,
)
from batch_rename_tool import (
    RenameOptions,
    apply_renames,
    discover_rename_files,
    preview_renames,
)
from smart_rename_tool import suggest_smart_renames
from batch_processing_tool import (
    discover_pdf_files,
    inspect_pdf_files,
    process_pdf_files,
)
from document_router import process_document
from api_layer import (
    PROVIDER_LABELS,
    inspect_pdf,
    is_provider_configured,
)
from api_layer.config import select_provider, selected_provider
from ocr_settings_dialog import SoftwareSettingsDialog
from pdf_invoice_tool import convert_invoice_pdfs, write_invoice_ledger
from pdf_toolbox import (
    COMPRESSION_PRESETS,
    IMAGE_SUFFIXES,
    PdfPageRef,
    add_pdf_marks,
    compress_pdf,
    compare_pdf_text,
    default_output_name,
    estimate_compressed_size,
    images_to_pdf,
    make_searchable_pdf,
    output_path,
    page_count,
    pdfs_to_images,
    prepare_image_thumbnail,
    render_page_thumbnail,
    save_pages,
    secure_pdf,
)
from ui.common_widgets import ClearSpinBox, SelectionComboBox
from ui.pdf_widgets import (
    PDF_PAGE_CARD_HEIGHT,
    PDF_PAGE_CARD_H_SPACING,
    PDF_PAGE_CARD_V_SPACING,
    PDF_PAGE_CARD_WIDTH,
    PDF_PAGE_THUMBNAIL_SIZE,
    PdfImageBoard,
    PdfImageCard,
    PdfPageBoard,
    PdfPageCard,
)
from ui.theme import ACCENT_PALETTES, build_theme_colors, build_theme_stylesheet
from ui.tasks import BackgroundTaskThread, DocumentOCRThread, InvoiceBatchProcessThread
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
PDF_IMAGE_WARNING_COUNT = 100
PDF_IMAGE_MAX_COUNT = 300
PDF_PAGE_WARNING_COUNT = 500
PDF_PAGE_MAX_COUNT = 1000
RENAME_WARNING_COUNT = 5000
RENAME_MAX_COUNT = 20000


def is_chinese_locale(locale):
    return locale.language() == QLocale.Chinese


def localized_app_name(locale):
    return APP_NAME_ZH if is_chinese_locale(locale) else APP_NAME_EN


def resource_path(relative_path):
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path / relative_path


def application_icon_path():
    icon_name = "app_icon.ico" if sys.platform == "win32" else "app_icon.icns"
    return resource_path(f"assets/{icon_name}")


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
        self.split_source_info = {}
        self.split_output_folder = ""
        self.split_result_folder = ""
        self.cleanup_source_file = ""
        self.cleanup_output_folder = ""
        self.cleanup_result_file = ""
        self.cleanup_preview = None
        self.cleanup_populating_columns = False
        self.invoice_source_files = []
        self.invoice_output_folder = ""
        self.document_source_file = ""
        self.document_output_folder = ""
        self.document_result_file = ""
        self.document_ocr_result_file = ""
        self.document_ocr_thread = None
        self.document_ocr_progress = None
        self.document_ocr_task_kind = ""
        self.batch_source_folder = ""
        self.batch_output_folder = ""
        self.batch_previews = []
        self.batch_failed_files = []
        self.batch_last_log_file = ""
        self.background_task_thread = None
        self.background_task_progress = None
        self.background_task_status_label = None
        self.background_task_title = ""
        self.rename_source_files = []
        self.rename_previews = []
        self.rename_preview_valid = False
        self.rename_last_log_file = ""
        self.rename_smart_result = None
        self.pdf_output_folder = ""
        self.pdf_page_cards = []
        self.pdf_compress_source_file = ""
        self.pdf_image_source_files = []
        self.pdf_image_cards = []
        self.pdf_export_source_files = []
        self.pdf_marks_source_file = ""
        self.pdf_marks_output_folder = ""
        self.pdf_marks_result_file = ""
        self.pdf_security_source_file = ""
        self.pdf_security_output_folder = ""
        self.pdf_security_result_file = ""
        self.pdf_searchable_source_file = ""
        self.pdf_searchable_output_folder = ""
        self.pdf_searchable_result_file = ""
        self.pdf_searchable_inspection = None
        self.pdf_compare_left_file = ""
        self.pdf_compare_right_file = ""
        self.pdf_compare_output_folder = ""
        self.pdf_compare_result_file = ""
        self.pdf_thumbnail_tempdir = tempfile.TemporaryDirectory(
            prefix="eggie-pdf-thumbs-"
        )
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
        self.app_icon = QIcon(str(application_icon_path()))
        if not self.app_icon.isNull():
            self.setWindowIcon(self.app_icon)

        self.setWindowTitle(self.app_name)
        self.resize(1280, 820)
        self.setMinimumSize(1180, 720)
        self.setAcceptDrops(True)

        self.app_shell = QWidget()
        self.app_shell.setObjectName("appShell")
        shell_layout = QHBoxLayout(self.app_shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        self.sidebar = self.create_sidebar()
        self.stack = QStackedWidget()
        shell_layout.addWidget(self.sidebar)
        shell_layout.addWidget(self.stack, 1)
        self.setCentralWidget(self.app_shell)

        self.home_page = self.create_home_page()
        self.excel_page = QWidget()
        self.excel_page.setObjectName("excelPage")
        self.split_page = self.create_split_page()
        self.cleanup_page = self.create_cleanup_page()
        self.invoice_page = self.create_invoice_page()
        self.document_page = self.create_document_page()
        self.batch_page = self.create_batch_page()
        self.rename_page = self.create_rename_page()
        self.pdf_page = self.create_pdf_page()
        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.excel_page)
        self.stack.addWidget(self.split_page)
        self.stack.addWidget(self.cleanup_page)
        self.stack.addWidget(self.invoice_page)
        self.stack.addWidget(self.document_page)
        self.stack.addWidget(self.batch_page)
        self.stack.addWidget(self.rename_page)
        self.stack.addWidget(self.pdf_page)
        self.set_active_navigation("home")
        self.update_home_responsive_layout()

        main_layout = QVBoxLayout(self.excel_page)
        main_layout.setContentsMargins(22, 18, 22, 18)
        main_layout.setSpacing(14)

        title = QLabel("Excel 合并")
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title.setFont(QFont("PingFang SC", 24, QFont.Bold))
        title.setProperty("role", "title")
        main_layout.addWidget(title)

        subtitle = QLabel("按顺序合并多个表格，并保留主要格式")
        subtitle.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
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
        self.file_table.setColumnCount(7)
        self.file_table.setHeaderLabels(
            ["序号", "文件名", "文件大小", "行数", "列数", "合并单元格", "文件路径"]
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
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        header.setSectionResizeMode(5, QHeaderView.Fixed)
        header.setSectionResizeMode(6, QHeaderView.Interactive)
        header.setStretchLastSection(False)
        self.file_table.setColumnWidth(0, 90)
        self.file_table.setColumnWidth(1, 250)
        self.file_table.setColumnWidth(2, 105)
        self.file_table.setColumnWidth(3, 90)
        self.file_table.setColumnWidth(4, 90)
        self.file_table.setColumnWidth(5, 110)
        self.file_table.setColumnWidth(6, 700)
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
        self.skip_rows_spinbox = ClearSpinBox()
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
        self.file_table.itemSelectionChanged.connect(self.update_button_states)

        self.refresh_file_list()
        self.apply_theme()

    def create_sidebar(self):
        sidebar = QWidget()
        sidebar.setObjectName("homeSidebar")
        sidebar.setAttribute(Qt.WA_StyledBackground, True)
        sidebar.setFixedWidth(250)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(20, 22, 18, 20)
        layout.setSpacing(8)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        self.home_logo_pixmap = QPixmap(str(resource_path("assets/app_icon.png")))
        self.home_logo_label = QLabel()
        self.home_logo_label.setFixedSize(52, 52)
        self.home_logo_label.setAlignment(Qt.AlignCenter)
        if not self.home_logo_pixmap.isNull():
            self.home_logo_label.setPixmap(
                self.home_logo_pixmap.scaled(
                    QSize(52, 52),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
        else:
            self.home_logo_label.setText("Eggie")
        brand.addWidget(self.home_logo_label)

        brand_text = QVBoxLayout()
        brand_text.setSpacing(2)
        name = QLabel("Eggie DocuFlow")
        name.setProperty("homeRole", "brand")
        subtitle = QLabel("文档处理系统")
        subtitle.setProperty("homeRole", "muted")
        brand_text.addWidget(name)
        brand_text.addWidget(subtitle)
        brand.addLayout(brand_text, 1)
        layout.addLayout(brand)
        layout.addSpacing(16)

        self.nav_buttons = {}

        def add_nav(key, text, handler):
            button = QPushButton(text)
            button.setMinimumHeight(44)
            button.setProperty("variant", "homeNav")
            button.clicked.connect(handler)
            layout.addWidget(button)
            self.nav_buttons[key] = button

        add_nav("home", "工作台", self.show_home)
        add_nav("excel", "Excel 合并", self.show_excel_tool)
        add_nav("split", "Excel 拆分", self.show_split_tool)
        add_nav("cleanup", "Excel 数据清理", self.show_cleanup_tool)
        add_nav("invoice", "发票解析", self.show_invoice_tool)
        add_nav("document", "文档处理", self.show_document_tool)
        add_nav("batch", "批量处理", self.show_batch_tool)
        add_nav("rename", "批量改名", self.show_rename_tool)
        add_nav("pdf", "PDF 工具箱", self.show_pdf_tool)
        layout.addStretch(1)

        version = QLabel(f"版本 {APP_VERSION}")
        version.setProperty("homeRole", "muted")
        layout.addWidget(version)
        settings_button = QPushButton("设置")
        settings_button.setMinimumHeight(42)
        settings_button.setProperty("variant", "homeNav")
        settings_button.clicked.connect(self.show_settings)
        layout.addWidget(settings_button)
        return sidebar

    def create_home_page(self):
        page = QWidget()
        page.setObjectName("homePage")
        page.setAttribute(Qt.WA_StyledBackground, True)
        root_layout = QVBoxLayout(page)
        self.home_layout = root_layout
        root_layout.setContentsMargins(28, 26, 28, 26)
        root_layout.setSpacing(16)

        def styled_widget(object_name=None, prop_name=None):
            widget = QWidget()
            widget.setAttribute(Qt.WA_StyledBackground, True)
            if object_name:
                widget.setObjectName(object_name)
            if prop_name:
                widget.setProperty(prop_name, "true")
            return widget

        def home_label(text, role, word_wrap=False):
            label = QLabel(text)
            label.setProperty("homeRole", role)
            label.setWordWrap(word_wrap)
            return label

        main_layout = root_layout

        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)
        title_layout = QVBoxLayout()
        title_layout.setSpacing(3)
        self.home_title_label = home_label("工作台", "title")
        self.home_subtitle_label = home_label("浅色、克制、清晰的科技感工作台", "muted")
        title_layout.addWidget(self.home_title_label)
        title_layout.addWidget(self.home_subtitle_label)
        header_layout.addLayout(title_layout, 1)
        header_right = QHBoxLayout()
        header_right.setSpacing(10)
        settings_button = QPushButton("设置")
        settings_button.setProperty("variant", "homeOpen")
        settings_button.setMinimumSize(96, 38)
        settings_button.clicked.connect(self.show_settings)
        header_right.addWidget(settings_button)
        header_layout.addLayout(header_right)
        main_layout.addLayout(header_layout)

        status = styled_widget(prop_name="homeStatus")
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(18, 12, 18, 12)
        status_layout.addWidget(home_label("软件已就绪，请从左侧菜单或下方卡片选择工具。", "body"))
        main_layout.addWidget(status)

        banner = styled_widget(prop_name="homeHero")
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(20, 16, 20, 16)
        banner_layout.setSpacing(12)
        banner_text_layout = QVBoxLayout()
        banner_text_layout.setSpacing(2)
        banner_text_layout.addWidget(
            home_label("选择工具，添加文件，确认后处理", "cardTitle")
        )
        banner_text_layout.addWidget(
            home_label("首页只保留真实可用入口，处理结果仍在各工具完成后直接打开。", "muted")
        )
        banner_layout.addLayout(banner_text_layout, 1)
        main_layout.addWidget(banner)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(20)
        tools_layout = QVBoxLayout()
        tools_layout.setSpacing(14)
        tools_layout.addWidget(home_label("常用工具", "section"))
        self.home_grid = QGridLayout()
        self.home_grid.setHorizontalSpacing(18)
        self.home_grid.setVerticalSpacing(18)
        self.home_tool_buttons = []
        self.home_tool_cards = []

        def tool_card(tag, accent, title, desc, handler):
            card = styled_widget(prop_name="homeCard")
            card.setMinimumHeight(116)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 16, 18, 16)
            card_layout.setSpacing(8)

            title_row = QHBoxLayout()
            title_row.setSpacing(12)
            tag_label = QLabel(tag)
            tag_label.setAlignment(Qt.AlignCenter)
            tag_label.setFixedSize(46, 46)
            tag_label.setStyleSheet(
                f"background: {accent}; color: #FFFFFF; border-radius: 10px; "
                "font-weight: 700;"
            )
            title_row.addWidget(tag_label)

            title_label = home_label(title, "cardTitle")
            title_row.addWidget(title_label, 1)
            card_layout.addLayout(title_row)

            bottom_row = QHBoxLayout()
            bottom_row.setSpacing(12)
            desc_label = home_label(desc, "body", True)
            desc_label.setMinimumHeight(38)
            bottom_row.addWidget(desc_label, 1)

            open_button = QPushButton("打开")
            open_button.setProperty("variant", "homeOpen")
            open_button.setMinimumSize(112, 44)
            open_button.clicked.connect(handler)
            bottom_row.addWidget(open_button, 0, Qt.AlignBottom)
            card_layout.addLayout(bottom_row)
            self.home_tool_buttons.append(open_button)
            self.home_tool_cards.append(card)
            return card

        tool_specs = [
            ("XL", "#34C759", "Excel 合并", "按顺序合并多个表格，并保留主要格式。", self.show_excel_tool),
            ("XL", "#0A84FF", "Excel 拆分", "按表头和数据行数拆分成多个文件。", self.show_split_tool),
            ("XL", "#30B0C7", "Excel 数据清理", "先预览空行、重复行和格式问题，再另存新文件。", self.show_cleanup_tool),
            ("PDF", "#FF9F0A", "发票解析", "批量解析发票，并生成汇总结果。", self.show_invoice_tool),
            ("DOC", "#AF52DE", "文档处理", "自动识别合同、表格和发票类 PDF。", self.show_document_tool),
            ("BAT", "#007AFF", "批量处理", "选择文件夹，自动识别并逐个生成结果。", self.show_batch_tool),
            ("REN", "#30B0C7", "批量改名", "先预览新文件名，确认后再执行。", self.show_rename_tool),
            ("PDF", "#FF453A", "PDF 工具箱", "页面整理、压缩和图片互转。", self.show_pdf_tool),
        ]
        for index, spec in enumerate(tool_specs):
            self.home_grid.addWidget(tool_card(*spec), index // 2, index % 2)
        tools_layout.addLayout(self.home_grid)
        tools_layout.addStretch(1)
        content_layout.addLayout(tools_layout, 1)
        main_layout.addLayout(content_layout, 1)
        return page

    def create_split_page(self):
        page = QWidget()
        page.setObjectName("splitPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)

        title = QLabel("Excel 拆分")
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title.setFont(QFont("PingFang SC", 24, QFont.Bold))
        title.setProperty("role", "title")
        layout.addWidget(title)

        subtitle = QLabel("选择一个 Excel 文件，按表头和数据行数拆分成多个文件")
        subtitle.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
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

        self.choose_split_source_button.clicked.connect(self.choose_split_source_file)
        self.choose_split_output_button.clicked.connect(self.choose_split_output_folder)
        self.split_button.clicked.connect(self.split_workbook)
        self.split_header_rows_spinbox.valueChanged.connect(self.update_split_estimate)
        self.split_rows_per_file_spinbox.valueChanged.connect(self.update_split_estimate)
        return page

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
        options_layout = QHBoxLayout(options_group)
        self.cleanup_empty_rows_checkbox = QCheckBox("删除整行空白")
        self.cleanup_empty_rows_checkbox.setChecked(True)
        self.cleanup_spaces_checkbox = QCheckBox("清理文字多余空格")
        self.cleanup_spaces_checkbox.setChecked(True)
        self.cleanup_deduplicate_checkbox = QCheckBox("删除重复行")
        self.cleanup_dates_checkbox = QCheckBox("统一日期显示")
        self.cleanup_numbers_checkbox = QCheckBox("统一数字显示")
        for checkbox in (
            self.cleanup_empty_rows_checkbox,
            self.cleanup_spaces_checkbox,
            self.cleanup_deduplicate_checkbox,
            self.cleanup_dates_checkbox,
            self.cleanup_numbers_checkbox,
        ):
            options_layout.addWidget(checkbox)
        options_layout.addStretch(1)
        layout.addWidget(options_group)

        columns_group = QGroupBox("排重列（不勾选任何列时按整行排重）")
        columns_layout = QVBoxLayout(columns_group)
        self.cleanup_columns_tree = QTreeWidget()
        self.cleanup_columns_tree.setHeaderLabels(["可作为排重依据的列"])
        self.cleanup_columns_tree.setRootIsDecorated(False)
        self.cleanup_columns_tree.setMaximumHeight(145)
        columns_layout.addWidget(self.cleanup_columns_tree)
        layout.addWidget(columns_group)

        preview_group = QGroupBox("预计结果")
        preview_layout = QVBoxLayout(preview_group)
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
        self.cleanup_start_button.setMinimumHeight(46)
        self.cleanup_open_result_button = QPushButton("打开结果")
        self.cleanup_open_result_button.setMinimumHeight(46)
        action_layout.addStretch()
        action_layout.addWidget(self.cleanup_start_button)
        action_layout.addWidget(self.cleanup_open_result_button)
        action_layout.addStretch()
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
        return page

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

        subtitle = QLabel("统一提取发票头信息和明细，自动校验金额与税额")
        subtitle.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
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
        self.document_ocr_checkbox = QCheckBox("扫描页使用云 OCR")
        self.document_ocr_provider_combo = QComboBox()
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
        layout.addWidget(ocr_group)

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
            "处理顺序：PDF 分类 → 路由 → 输出。不勾选云 OCR 时，原有处理方式完全不变；"
            "勾选后，扫描页识别文字会继续进入同一文档处理流程。"
            "扫描页识别暂不与增强排版同时使用。"
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
        return page

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
        self.batch_ocr_checkbox = QCheckBox("扫描页使用云 OCR")
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
        self.batch_start_button.setMinimumHeight(46)
        self.batch_retry_button = QPushButton("只重试失败文件")
        self.batch_retry_button.setMinimumHeight(46)
        self.batch_open_folder_button = QPushButton("打开结果文件夹")
        self.batch_open_folder_button.setMinimumHeight(46)
        action_layout.addStretch()
        action_layout.addWidget(self.batch_start_button)
        action_layout.addWidget(self.batch_retry_button)
        action_layout.addWidget(self.batch_open_folder_button)
        action_layout.addStretch()
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

        self.rename_limit_label = QLabel(
            "当前 0 / 20,000 个文件；处理数量越多，处理速度越慢，"
            "请酌情拆分任务"
        )
        self.rename_limit_label.setProperty("role", "hint")
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

        self.rename_rule_combo = QComboBox()
        for label_text, rule_key in (
            ("替换文字", "replace"),
            ("删除指定文字", "delete_text"),
            ("删除开头几个字", "trim_start"),
            ("删除结尾几个字", "trim_end"),
            ("前面追加文字", "prefix"),
            ("后面追加文字", "suffix"),
            ("修改后缀", "extension"),
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
        number_layout = QHBoxLayout(self.rename_number_widget)
        number_layout.setContentsMargins(0, 0, 0, 0)
        number_layout.setSpacing(8)
        self.rename_number_start_spinbox.setMinimumWidth(90)
        self.rename_number_digits_spinbox.setMinimumWidth(78)
        number_layout.addWidget(self.rename_numbering_checkbox)
        number_layout.addWidget(QLabel("起始"))
        number_layout.addWidget(self.rename_number_start_spinbox)
        number_layout.addWidget(QLabel("位数"))
        number_layout.addWidget(self.rename_number_digits_spinbox)
        rules_layout.addWidget(self.rename_number_widget)

        self.rename_smart_options_widget = QWidget()
        smart_layout = QVBoxLayout(self.rename_smart_options_widget)
        smart_layout.setContentsMargins(0, 0, 0, 0)
        smart_layout.setSpacing(7)
        smart_ocr_row = QHBoxLayout()
        self.rename_smart_ocr_checkbox = QCheckBox("扫描页使用云 OCR")
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

        subtitle = QLabel("整理页面、压缩文件，并支持图片和 PDF 互转")
        subtitle.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        subtitle.setProperty("role", "subtitle")
        layout.addWidget(subtitle)

        self.pdf_tabs = QTabWidget()
        self.pdf_tabs.addTab(self.create_pdf_organizer_tab(), "页面整理")
        self.pdf_tabs.addTab(self.create_pdf_compress_tab(), "PDF 压缩")
        self.pdf_tabs.addTab(self.create_pdf_convert_tab(), "图片 / PDF 互转")
        self.pdf_tabs.addTab(self.create_pdf_marks_tab(), "水印与页码")
        self.pdf_tabs.addTab(self.create_pdf_security_tab(), "PDF 密码")
        self.pdf_tabs.addTab(self.create_searchable_pdf_tab(), "可搜索 PDF")
        self.pdf_tabs.addTab(self.create_pdf_compare_tab(), "文字对比")
        layout.addWidget(self.pdf_tabs, 1)

        self.update_pdf_button_states()
        return page

    def create_pdf_organizer_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(10)

        self.pdf_organizer_button_layout = QHBoxLayout()
        self.pdf_organizer_button_layout.setSpacing(6)
        self.pdf_add_button = QPushButton("添加 PDF")
        self.pdf_clear_button = QPushButton("清空页面")
        self.pdf_check_all_button = QPushButton("全选")
        self.pdf_uncheck_all_button = QPushButton("取消全选")
        self.pdf_move_previous_button = QPushButton("前移")
        self.pdf_move_next_button = QPushButton("后移")
        self.pdf_rotate_left_button = QPushButton("左转")
        self.pdf_rotate_right_button = QPushButton("右转")
        self.pdf_rotate_180_button = QPushButton("旋转 180 度")
        self.pdf_delete_pages_button = QPushButton("删除勾选")
        self.pdf_split_selected_button = QPushButton("拆分勾选")
        self.pdf_save_pages_button = QPushButton("保存当前顺序")
        self.pdf_add_button.setProperty("variant", "accent")
        self.pdf_delete_pages_button.setProperty("variant", "danger")
        self.pdf_save_pages_button.setProperty("variant", "primary")
        for button in (
            self.pdf_add_button,
            self.pdf_clear_button,
            self.pdf_check_all_button,
            self.pdf_uncheck_all_button,
            self.pdf_move_previous_button,
            self.pdf_move_next_button,
            self.pdf_rotate_left_button,
            self.pdf_rotate_right_button,
            self.pdf_rotate_180_button,
            self.pdf_delete_pages_button,
            self.pdf_split_selected_button,
            self.pdf_save_pages_button,
        ):
            button.setMinimumHeight(34)
        for button in (
            self.pdf_add_button,
            self.pdf_clear_button,
            self.pdf_check_all_button,
            self.pdf_uncheck_all_button,
            self.pdf_move_previous_button,
            self.pdf_move_next_button,
            self.pdf_rotate_left_button,
            self.pdf_rotate_right_button,
            self.pdf_rotate_180_button,
            self.pdf_delete_pages_button,
            self.pdf_split_selected_button,
        ):
            button.setProperty("compactToolbar", "true")
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            self.pdf_organizer_button_layout.addWidget(button)
        self.pdf_organizer_button_layout.addStretch(1)
        layout.addLayout(self.pdf_organizer_button_layout)

        self.pdf_page_limit_label = QLabel(
            "当前 0 / 1,000 页；处理数量越多，处理速度越慢，"
            "请酌情拆分任务"
        )
        self.pdf_page_limit_label.setProperty("role", "hint")
        layout.addWidget(self.pdf_page_limit_label)

        self.pdf_page_scroll = QScrollArea()
        self.pdf_page_scroll.setWidgetResizable(True)
        self.pdf_page_board = PdfPageBoard(self)
        self.pdf_page_scroll.setWidget(self.pdf_page_board)
        layout.addWidget(self.pdf_page_scroll, 1)

        save_group = QGroupBox("输出设置")
        save_layout = QVBoxLayout(save_group)
        save_layout.setContentsMargins(12, 14, 12, 10)
        save_fields_layout = QHBoxLayout()
        self.pdf_output_folder_edit = QLineEdit()
        self.pdf_output_folder_edit.setReadOnly(True)
        self.pdf_output_folder_edit.setPlaceholderText("请选择结果保存文件夹")
        self.pdf_choose_output_folder_button = QPushButton("选择文件夹")
        self.pdf_output_name_edit = QLineEdit()
        self.pdf_output_name_edit.setPlaceholderText(default_output_name("PDF合并结果"))
        self.pdf_save_pages_button.setText("保存结果")
        self.pdf_save_pages_button.setMinimumHeight(44)
        save_fields_layout.addWidget(QLabel("文件夹："))
        save_fields_layout.addWidget(self.pdf_output_folder_edit, 2)
        save_fields_layout.addWidget(self.pdf_choose_output_folder_button)
        save_fields_layout.addWidget(QLabel("文件名："))
        save_fields_layout.addWidget(self.pdf_output_name_edit, 1)
        save_layout.addLayout(save_fields_layout)
        save_layout.addWidget(self.pdf_save_pages_button)
        layout.addWidget(save_group)

        self.pdf_status_label = QLabel("尚未添加 PDF")
        self.pdf_status_label.setProperty("role", "status")
        layout.addWidget(self.pdf_status_label)

        self.pdf_add_button.clicked.connect(self.add_pdf_files)
        self.pdf_clear_button.clicked.connect(self.clear_pdf_pages)
        self.pdf_check_all_button.clicked.connect(lambda: self.set_all_pdf_page_checks(True))
        self.pdf_uncheck_all_button.clicked.connect(lambda: self.set_all_pdf_page_checks(False))
        self.pdf_move_previous_button.clicked.connect(lambda: self.move_checked_pdf_pages(-1))
        self.pdf_move_next_button.clicked.connect(lambda: self.move_checked_pdf_pages(1))
        self.pdf_rotate_left_button.clicked.connect(lambda: self.rotate_selected_pdf_pages(-90))
        self.pdf_rotate_right_button.clicked.connect(lambda: self.rotate_selected_pdf_pages(90))
        self.pdf_rotate_180_button.clicked.connect(lambda: self.rotate_selected_pdf_pages(180))
        self.pdf_delete_pages_button.clicked.connect(self.delete_selected_pdf_pages)
        self.pdf_split_selected_button.clicked.connect(self.split_selected_pdf_pages)
        self.pdf_save_pages_button.clicked.connect(self.save_pdf_pages)
        self.pdf_choose_output_folder_button.clicked.connect(self.choose_pdf_output_folder)
        return tab

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

        preset_group = QGroupBox("压缩档位")
        preset_layout = QHBoxLayout(preset_group)
        preset_layout.setContentsMargins(12, 14, 12, 10)
        self.pdf_compress_preset_combo = QComboBox()
        for key in ("clear", "standard", "small"):
            self.pdf_compress_preset_combo.addItem(COMPRESSION_PRESETS[key]["label"], key)
        self.pdf_compress_preset_combo.setCurrentIndex(1)
        self.pdf_compress_size_label = QLabel("原始大小：-    预计压缩后：-    预计缩小：-")
        self.pdf_compress_size_label.setProperty("role", "hint")
        preset_layout.addWidget(QLabel("档位："))
        preset_layout.addWidget(self.pdf_compress_preset_combo)
        preset_layout.addWidget(self.pdf_compress_size_label, 1)
        layout.addWidget(preset_group)

        output_group = QGroupBox("输出设置")
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
        self.pdf_compress_button.setMinimumHeight(48)
        self.pdf_compress_button.setProperty("variant", "primary")
        layout.addWidget(self.pdf_compress_button)
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
        self.pdf_delete_checked_images_button = QPushButton("删除勾选")
        self.pdf_clear_images_button = QPushButton("清空图片")
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
        image_layout.addWidget(self.pdf_image_output_folder_edit)
        image_layout.addWidget(self.pdf_choose_image_output_button)
        image_layout.addWidget(QLabel("输出文件名："))
        image_layout.addWidget(self.pdf_image_output_name_edit)
        self.pdf_images_to_pdf_button = QPushButton("合成 PDF")
        self.pdf_images_to_pdf_button.setMinimumHeight(44)
        self.pdf_images_to_pdf_button.setProperty("variant", "primary")
        image_layout.addWidget(self.pdf_images_to_pdf_button)
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
        self.pdf_delete_export_source_button = QPushButton("删除选中")
        self.pdf_delete_export_source_button.setProperty("variant", "danger")
        self.pdf_clear_export_sources_button = QPushButton("清空全部")
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
        export_layout.addWidget(self.pdf_export_button)
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

    def create_pdf_marks_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(11)

        source_group = QGroupBox("选择 PDF")
        source_layout = QHBoxLayout(source_group)
        self.pdf_marks_source_edit = QLineEdit()
        self.pdf_marks_source_edit.setReadOnly(True)
        self.pdf_marks_source_edit.setPlaceholderText("请选择需要添加水印或页码的 PDF")
        self.pdf_choose_marks_source_button = QPushButton("选择 PDF")
        self.pdf_choose_marks_source_button.setProperty("variant", "accent")
        source_layout.addWidget(self.pdf_marks_source_edit, 1)
        source_layout.addWidget(self.pdf_choose_marks_source_button)
        layout.addWidget(source_group)

        watermark_group = QGroupBox("文字水印")
        watermark_layout = QHBoxLayout(watermark_group)
        self.pdf_watermark_checkbox = QCheckBox("添加水印")
        self.pdf_watermark_checkbox.setChecked(True)
        self.pdf_watermark_text_edit = QLineEdit("内部资料")
        self.pdf_watermark_text_edit.setPlaceholderText("水印文字")
        self.pdf_watermark_opacity_spinbox = ClearSpinBox()
        self.pdf_watermark_opacity_spinbox.setRange(5, 80)
        self.pdf_watermark_opacity_spinbox.setValue(18)
        self.pdf_watermark_opacity_spinbox.setSuffix(" %")
        self.pdf_watermark_angle_spinbox = ClearSpinBox()
        self.pdf_watermark_angle_spinbox.setRange(-180, 180)
        self.pdf_watermark_angle_spinbox.setValue(-30)
        self.pdf_watermark_angle_spinbox.setSuffix("°")
        self.pdf_watermark_size_spinbox = ClearSpinBox()
        self.pdf_watermark_size_spinbox.setRange(12, 120)
        self.pdf_watermark_size_spinbox.setValue(40)
        self.pdf_watermark_size_spinbox.setSuffix(" 号")
        self.pdf_watermark_position_combo = SelectionComboBox()
        for label_text, value in (
            ("页面中央", "center"),
            ("左上", "top_left"),
            ("右上", "top_right"),
            ("左下", "bottom_left"),
            ("右下", "bottom_right"),
        ):
            self.pdf_watermark_position_combo.addItem(label_text, value)
        watermark_layout.addWidget(self.pdf_watermark_checkbox)
        watermark_layout.addWidget(self.pdf_watermark_text_edit, 1)
        watermark_layout.addWidget(QLabel("透明度"))
        watermark_layout.addWidget(self.pdf_watermark_opacity_spinbox)
        watermark_layout.addWidget(QLabel("角度"))
        watermark_layout.addWidget(self.pdf_watermark_angle_spinbox)
        watermark_layout.addWidget(QLabel("字号"))
        watermark_layout.addWidget(self.pdf_watermark_size_spinbox)
        watermark_layout.addWidget(self.pdf_watermark_position_combo)
        layout.addWidget(watermark_group)

        number_group = QGroupBox("页码")
        number_layout = QHBoxLayout(number_group)
        self.pdf_page_number_checkbox = QCheckBox("添加页码")
        self.pdf_page_number_start_spinbox = ClearSpinBox()
        self.pdf_page_number_start_spinbox.setRange(0, 999999)
        self.pdf_page_number_start_spinbox.setValue(1)
        self.pdf_page_number_position_combo = SelectionComboBox()
        for label_text, value in (
            ("底部居中", "bottom_center"),
            ("底部左侧", "bottom_left"),
            ("底部右侧", "bottom_right"),
            ("顶部居中", "top_center"),
            ("顶部左侧", "top_left"),
            ("顶部右侧", "top_right"),
        ):
            self.pdf_page_number_position_combo.addItem(label_text, value)
        number_layout.addWidget(self.pdf_page_number_checkbox)
        number_layout.addWidget(QLabel("起始页码"))
        number_layout.addWidget(self.pdf_page_number_start_spinbox)
        number_layout.addWidget(QLabel("位置"))
        number_layout.addWidget(self.pdf_page_number_position_combo)
        number_layout.addStretch(1)
        layout.addWidget(number_group)

        output_group = QGroupBox("输出设置")
        output_layout = QHBoxLayout(output_group)
        self.pdf_marks_output_folder_edit = QLineEdit()
        self.pdf_marks_output_folder_edit.setReadOnly(True)
        self.pdf_choose_marks_output_button = QPushButton("选择文件夹")
        self.pdf_marks_output_name_edit = QLineEdit()
        self.pdf_marks_output_name_edit.setPlaceholderText(default_output_name("水印页码结果"))
        output_layout.addWidget(QLabel("文件夹："))
        output_layout.addWidget(self.pdf_marks_output_folder_edit, 2)
        output_layout.addWidget(self.pdf_choose_marks_output_button)
        output_layout.addWidget(QLabel("文件名："))
        output_layout.addWidget(self.pdf_marks_output_name_edit, 1)
        layout.addWidget(output_group)

        self.pdf_marks_start_button = QPushButton("生成新 PDF")
        self.pdf_marks_start_button.setMinimumHeight(46)
        self.pdf_marks_start_button.setProperty("variant", "primary")
        self.pdf_marks_status_label = QLabel("尚未选择 PDF")
        self.pdf_marks_status_label.setProperty("role", "status")
        layout.addWidget(self.pdf_marks_start_button)
        layout.addWidget(self.pdf_marks_status_label)
        layout.addStretch(1)

        self.pdf_choose_marks_source_button.clicked.connect(self.choose_pdf_marks_source)
        self.pdf_choose_marks_output_button.clicked.connect(self.choose_pdf_marks_output_folder)
        self.pdf_marks_start_button.clicked.connect(self.create_marked_pdf)
        self.pdf_watermark_checkbox.toggled.connect(self.update_pdf_marks_controls)
        self.pdf_page_number_checkbox.toggled.connect(self.update_pdf_marks_controls)
        self.update_pdf_marks_controls()
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
        password_layout = QVBoxLayout(password_group)
        mode_row = QHBoxLayout()
        self.pdf_security_mode_combo = SelectionComboBox()
        self.pdf_security_mode_combo.addItem("设置打开密码", "set")
        self.pdf_security_mode_combo.addItem("移除已有密码", "remove")
        mode_row.addWidget(QLabel("操作："))
        mode_row.addWidget(self.pdf_security_mode_combo)
        mode_row.addStretch(1)
        password_layout.addLayout(mode_row)
        self.pdf_source_password_edit = QLineEdit()
        self.pdf_source_password_edit.setEchoMode(QLineEdit.Password)
        self.pdf_source_password_edit.setPlaceholderText("原密码；未加密 PDF 可留空")
        self.pdf_new_password_edit = QLineEdit()
        self.pdf_new_password_edit.setEchoMode(QLineEdit.Password)
        self.pdf_new_password_edit.setPlaceholderText("新密码，至少 6 个字符")
        self.pdf_confirm_password_edit = QLineEdit()
        self.pdf_confirm_password_edit.setEchoMode(QLineEdit.Password)
        self.pdf_confirm_password_edit.setPlaceholderText("再次输入新密码")
        password_layout.addWidget(QLabel("原密码："))
        password_layout.addWidget(self.pdf_source_password_edit)
        self.pdf_new_password_label = QLabel("新密码：")
        self.pdf_confirm_password_label = QLabel("确认新密码：")
        password_layout.addWidget(self.pdf_new_password_label)
        password_layout.addWidget(self.pdf_new_password_edit)
        password_layout.addWidget(self.pdf_confirm_password_label)
        password_layout.addWidget(self.pdf_confirm_password_edit)
        privacy = QLabel("密码只在当前操作中使用，不会保存，也不会写入日志。")
        privacy.setProperty("role", "hint")
        password_layout.addWidget(privacy)
        layout.addWidget(password_group)

        output_group = QGroupBox("输出设置")
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
        self.pdf_security_start_button.setMinimumHeight(46)
        self.pdf_security_start_button.setProperty("variant", "primary")
        self.pdf_security_status_label = QLabel("尚未选择 PDF")
        self.pdf_security_status_label.setProperty("role", "status")
        layout.addWidget(self.pdf_security_start_button)
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
        ocr_layout.addWidget(QLabel("OCR 平台："))
        ocr_layout.addWidget(self.pdf_searchable_provider_combo)
        ocr_layout.addWidget(self.pdf_searchable_settings_button)
        ocr_layout.addWidget(self.pdf_searchable_inspection_label, 1)
        layout.addWidget(ocr_group)

        output_group = QGroupBox("输出设置")
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
        self.pdf_searchable_start_button.setMinimumHeight(46)
        self.pdf_searchable_start_button.setProperty("variant", "primary")
        self.pdf_searchable_status_label = QLabel("尚未选择 PDF")
        self.pdf_searchable_status_label.setProperty("role", "status")
        layout.addWidget(self.pdf_searchable_start_button)
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
        self.pdf_compare_start_button.setMinimumHeight(46)
        self.pdf_compare_start_button.setProperty("variant", "primary")
        self.pdf_compare_open_button = QPushButton("打开报告")
        self.pdf_compare_open_button.setMinimumHeight(46)
        action_layout.addWidget(self.pdf_compare_start_button, 1)
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

    def update_home_responsive_layout(self):
        if not hasattr(self, "home_logo_label"):
            return

        height = max(self.home_page.height(), self.height())
        logo_size = max(48, min(64, int(height * 0.07)))
        if not self.home_logo_pixmap.isNull():
            self.home_logo_label.setPixmap(
                self.home_logo_pixmap.scaled(
                    QSize(logo_size, logo_size),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
        self.home_logo_label.setFixedSize(logo_size, logo_size)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_home_responsive_layout()

    def set_active_navigation(self, active_key):
        for key, button in self.nav_buttons.items():
            button.setProperty(
                "variant",
                "homeNavActive" if key == active_key else "homeNav",
            )
            button.style().unpolish(button)
            button.style().polish(button)

    def show_home(self):
        self.stack.setCurrentWidget(self.home_page)
        self.set_active_navigation("home")
        self.setWindowTitle(self.app_name)

    def show_excel_tool(self):
        self.stack.setCurrentWidget(self.excel_page)
        self.set_active_navigation("excel")
        self.setWindowTitle(f"{self.app_name} - Excel 合并工具")

    def show_split_tool(self):
        self.stack.setCurrentWidget(self.split_page)
        self.set_active_navigation("split")
        self.setWindowTitle(f"{self.app_name} - Excel 拆分工具")

    def show_cleanup_tool(self):
        self.stack.setCurrentWidget(self.cleanup_page)
        self.set_active_navigation("cleanup")
        self.setWindowTitle(f"{self.app_name} - Excel 数据清理")

    def show_invoice_tool(self):
        self.stack.setCurrentWidget(self.invoice_page)
        self.set_active_navigation("invoice")
        self.setWindowTitle(f"{self.app_name} - PDF发票解析工具")

    def show_document_tool(self):
        self.stack.setCurrentWidget(self.document_page)
        self.set_active_navigation("document")
        self.setWindowTitle(f"{self.app_name} - 文档智能处理")

    def show_batch_tool(self):
        self.stack.setCurrentWidget(self.batch_page)
        self.set_active_navigation("batch")
        self.setWindowTitle(f"{self.app_name} - 批量处理中心")

    def show_rename_tool(self):
        self.stack.setCurrentWidget(self.rename_page)
        self.set_active_navigation("rename")
        self.setWindowTitle(f"{self.app_name} - 批量改名工具")

    def show_pdf_tool(self):
        self.stack.setCurrentWidget(self.pdf_page)
        self.set_active_navigation("pdf")
        self.setWindowTitle(f"{self.app_name} - PDF 工具箱")

    def show_settings(self, initial_provider=None):
        if initial_provider not in PROVIDER_LABELS:
            initial_provider = selected_provider()
        accent_options = [
            (key, palette["label"])
            for key, palette in ACCENT_PALETTES.items()
        ]
        dialog = SoftwareSettingsDialog(
            initial_provider,
            accent_options,
            self.accent_name,
            self,
        )
        dialog.setStyleSheet(self.styleSheet())
        dialog.accent_changed.connect(self.save_accent_setting)
        if dialog.exec() == QDialog.Accepted:
            try:
                select_provider(dialog.selected_provider)
            except OSError as error:
                QMessageBox.warning(self, "无法保存选择", str(error))
        provider = selected_provider()
        index = self.document_ocr_provider_combo.findData(provider)
        if index >= 0:
            self.document_ocr_provider_combo.setCurrentIndex(index)
        batch_index = self.batch_ocr_provider_combo.findData(provider)
        if batch_index >= 0:
            self.batch_ocr_provider_combo.setCurrentIndex(batch_index)
        smart_index = self.rename_smart_provider_combo.findData(provider)
        if smart_index >= 0:
            self.rename_smart_provider_combo.setCurrentIndex(smart_index)
        searchable_index = self.pdf_searchable_provider_combo.findData(provider)
        if searchable_index >= 0:
            self.pdf_searchable_provider_combo.setCurrentIndex(searchable_index)
        self.refresh_document_ocr_status()

    def save_accent_setting(self, accent_name):
        if accent_name not in ACCENT_PALETTES:
            return
        self.accent_name = accent_name
        self.settings.setValue("appearance/accent", self.accent_name)
        self.settings.sync()
        self.apply_theme()

    def dialog_folder(self, key, fallback=""):
        downloads = str(Path.home() / "Downloads")
        for candidate in (self.settings.value(f"dialogs/{key}", ""), fallback, downloads):
            if not candidate:
                continue
            path = Path(str(candidate)).expanduser()
            if path.exists() and path.is_file():
                path = path.parent
            elif not path.exists() and path.parent.exists():
                path = path.parent
            if path.exists() and path.is_dir():
                return str(path)
        return downloads

    def remember_dialog_folder(self, key, selected_path):
        if not selected_path:
            return
        path = Path(str(selected_path)).expanduser()
        if path.exists() and path.is_file():
            path = path.parent
        elif not path.exists() and path.parent.exists():
            path = path.parent
        if path.exists() and path.is_dir():
            self.settings.setValue(f"dialogs/{key}", str(path.resolve()))
            self.settings.sync()

    def apply_theme(self):
        colors = build_theme_colors(self.accent_name)
        self.setStyleSheet(build_theme_stylesheet(colors))

    def task_is_running(self):
        return bool(
            (self.background_task_thread and self.background_task_thread.isRunning())
            or (self.document_ocr_thread and self.document_ocr_thread.isRunning())
        )

    def set_global_task_active(self, active):
        self.stack.setEnabled(not active)
        self.sidebar.setEnabled(not active)

    def start_background_task(
        self,
        title,
        message,
        worker,
        on_success,
        on_failure=None,
        total=0,
        status_label=None,
        task_thread=None,
        allow_force_stop=False,
        on_cancel=None,
    ):
        if self.task_is_running():
            QMessageBox.information(
                self,
                "任务正在进行",
                "当前任务尚未完成，请等待完成后再开始新的任务。",
            )
            return False

        progress = QProgressDialog(
            f"任务正在执行，请勿关闭软件。\n\n{message}",
            "",
            0,
            max(int(total), 0),
            self,
        )
        progress.setWindowTitle(title)
        if allow_force_stop:
            progress.setCancelButtonText("强制结束当前任务")
        else:
            progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setWindowModality(Qt.WindowModal)
        if total <= 0:
            progress.setRange(0, 0)
        progress.show()

        thread = task_thread or BackgroundTaskThread(worker, self)
        self.background_task_thread = thread
        self.background_task_progress = progress
        self.background_task_status_label = status_label
        self.background_task_title = title
        thread.progress.connect(
            lambda value, maximum, text, task=thread: self.background_task_progress_changed(
                task, value, maximum, text
            )
        )
        thread.completed.connect(
            lambda result, task=thread: self.background_task_completed(
                task, result, on_success
            )
        )
        thread.failed.connect(
            lambda error, task=thread: self.background_task_failed(
                task, error, on_failure
            )
        )
        if allow_force_stop and hasattr(thread, "force_stop"):
            progress.canceled.connect(
                lambda task=thread: self.request_force_stop_background_task(
                    task,
                    on_cancel,
                )
            )
        if hasattr(thread, "cancelled"):
            thread.cancelled.connect(
                lambda task=thread: self.background_task_cancelled(task, on_cancel)
            )
        thread.finished.connect(thread.deleteLater)
        self.set_global_task_active(True)
        thread.start()
        return True

    def request_force_stop_background_task(self, thread, on_cancel):
        if self.background_task_thread is not thread:
            return
        answer = QMessageBox.question(
            self,
            "强制结束当前任务",
            "即将停止当前正在处理的发票。未完成的发票不会生成不完整 Excel；"
            "已经完成的结果会保留。\n\n是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        if self.background_task_progress is not None:
            self.background_task_progress.setCancelButton(None)
            self.background_task_progress.setLabelText("正在停止当前任务，请稍候…")
        if self.background_task_status_label is not None:
            self.background_task_status_label.setText("正在停止当前任务，请稍候…")
        thread.force_stop()

    def background_task_progress_changed(self, thread, value, total, text):
        if self.background_task_thread is not thread:
            return
        progress = self.background_task_progress
        if progress is not None:
            if total > 0:
                progress.setRange(0, total)
                progress.setValue(max(0, min(value, total)))
            else:
                progress.setRange(0, 0)
            progress.setLabelText(
                "任务正在执行，请勿关闭软件。\n\n" + text
            )
        if self.background_task_status_label is not None:
            self.background_task_status_label.setText(text)

    def clear_background_task(self, thread):
        if self.background_task_thread is not thread:
            return False
        progress = self.background_task_progress
        self.background_task_thread = None
        self.background_task_progress = None
        self.background_task_status_label = None
        self.background_task_title = ""
        self.set_global_task_active(False)
        if progress is not None:
            progress.close()
        return True

    def background_task_completed(self, thread, result, on_success):
        if not self.clear_background_task(thread):
            return
        on_success(result)

    def background_task_failed(self, thread, error_message, on_failure):
        title = self.background_task_title
        if not self.clear_background_task(thread):
            return
        if on_failure is not None:
            on_failure(error_message)
            return
        QMessageBox.critical(
            self,
            f"{title or '任务'}失败",
            error_message,
        )

    def background_task_cancelled(self, thread, on_cancel):
        if not self.clear_background_task(thread):
            return
        if on_cancel is not None:
            on_cancel()
            return
        QMessageBox.information(self, "任务已结束", "当前任务已强制结束。")

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
                "请先在软件设置中填写所选 OCR 平台的密钥。",
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

    def selected_pdf_page_items(self):
        return [card for card in self.pdf_page_cards if card.is_checked()]

    def pdf_page_refs_from_items(self, items):
        refs = []
        for card in items:
            data = card.data
            refs.append(
                PdfPageRef(
                    data["source_file"],
                    data["page_index"],
                    data.get("rotation", 0),
                )
            )
        return refs

    def all_pdf_page_items(self):
        return list(self.pdf_page_cards)

    def set_pdf_output_defaults(self, source_files):
        if not source_files:
            return
        if not self.pdf_output_folder:
            self.pdf_output_folder = str(Path(source_files[0]).parent / "output")
            self.pdf_output_folder_edit.setText(self.pdf_output_folder)
            self.pdf_output_folder_edit.setToolTip(self.pdf_output_folder)
        if not self.pdf_page_cards:
            label = (
                "PDF合并结果"
                if len(source_files) > 1
                else f"{Path(source_files[0]).stem}_页面整理"
            )
            self.pdf_output_name_edit.setText(default_output_name(label))

    def update_pdf_button_states(self):
        if not hasattr(self, "pdf_page_cards"):
            return
        has_pages = len(self.pdf_page_cards) > 0
        has_selection = bool(self.selected_pdf_page_items())
        self.pdf_clear_button.setEnabled(has_pages)
        self.pdf_check_all_button.setEnabled(has_pages)
        self.pdf_uncheck_all_button.setEnabled(has_pages)
        self.pdf_move_previous_button.setEnabled(has_selection)
        self.pdf_move_next_button.setEnabled(has_selection)
        self.pdf_rotate_left_button.setEnabled(has_selection)
        self.pdf_rotate_right_button.setEnabled(has_selection)
        self.pdf_rotate_180_button.setEnabled(has_selection)
        self.pdf_delete_pages_button.setEnabled(has_selection)
        self.pdf_split_selected_button.setEnabled(has_selection)
        self.pdf_save_pages_button.setEnabled(has_pages and bool(self.pdf_output_folder))
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

    def refresh_pdf_page_cards_layout(self):
        if not hasattr(self, "pdf_page_board"):
            return
        if getattr(self, "refreshing_pdf_card_layout", False):
            return
        self.refreshing_pdf_card_layout = True
        while self.pdf_page_board.grid.count():
            item = self.pdf_page_board.grid.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        try:
            viewport_width = max(self.pdf_page_scroll.viewport().width(), PDF_PAGE_CARD_WIDTH)
            columns = max(
                1,
                (viewport_width - 28) // (PDF_PAGE_CARD_WIDTH + PDF_PAGE_CARD_H_SPACING),
            )
            row_count = (len(self.pdf_page_cards) + columns - 1) // columns
            content_height = (
                16
                + row_count * PDF_PAGE_CARD_HEIGHT
                + max(0, row_count - 1) * PDF_PAGE_CARD_V_SPACING
            )
            self.pdf_page_board.setMinimumHeight(content_height)
            for index, card in enumerate(self.pdf_page_cards):
                row = index // columns
                column = index % columns
                self.pdf_page_board.grid.addWidget(card, row, column)
        finally:
            self.refreshing_pdf_card_layout = False

    def reorder_pdf_page(self, source_index, insert_index):
        if source_index < 0 or source_index >= len(self.pdf_page_cards):
            return
        insert_index = max(0, min(insert_index, len(self.pdf_page_cards)))
        card = self.pdf_page_cards.pop(source_index)
        if source_index < insert_index:
            insert_index -= 1
        self.pdf_page_cards.insert(insert_index, card)
        self.refresh_pdf_page_cards_layout()
        self.refresh_pdf_page_numbers()

    def refresh_pdf_page_numbers(self):
        if getattr(self, "updating_pdf_page_numbers", False):
            return
        self.updating_pdf_page_numbers = True
        try:
            for index, card in enumerate(self.pdf_page_cards, 1):
                card.update_display(index)
        finally:
            self.updating_pdf_page_numbers = False
        total = len(self.pdf_page_cards)
        self.pdf_page_limit_label.setText(
            f"当前 {total:,} / {PDF_PAGE_MAX_COUNT:,} 页；"
            "处理数量越多，处理速度越慢，请酌情拆分任务"
        )
        checked = len(self.selected_pdf_page_items())
        if total:
            self.pdf_status_label.setText(
                f"当前共有 {total} 页，已勾选 {checked} 页。双击页面可放大预览。"
            )
        else:
            self.pdf_status_label.setText("尚未添加 PDF")
        self.update_pdf_button_states()

    def set_all_pdf_page_checks(self, checked):
        for card in self.pdf_page_cards:
            old_state = card.checkbox.blockSignals(True)
            card.checkbox.setChecked(checked)
            card.checkbox.blockSignals(old_state)
            card.setProperty("checked", "true" if checked else "false")
            card.polish()
        self.refresh_pdf_page_numbers()

    def move_checked_pdf_pages(self, delta):
        rows = [
            self.pdf_page_cards.index(card)
            for card in self.selected_pdf_page_items()
        ]
        if not rows:
            return
        row_set = set(rows)
        if delta < 0:
            for row in rows:
                if row <= 0 or row - 1 in row_set:
                    continue
                self.pdf_page_cards[row - 1], self.pdf_page_cards[row] = (
                    self.pdf_page_cards[row],
                    self.pdf_page_cards[row - 1],
                )
                row_set.remove(row)
                row_set.add(row - 1)
        else:
            for row in reversed(rows):
                if row >= len(self.pdf_page_cards) - 1 or row + 1 in row_set:
                    continue
                self.pdf_page_cards[row + 1], self.pdf_page_cards[row] = (
                    self.pdf_page_cards[row],
                    self.pdf_page_cards[row + 1],
                )
                row_set.remove(row)
                row_set.add(row + 1)
        self.refresh_pdf_page_cards_layout()
        self.refresh_pdf_page_numbers()

    def preview_pdf_page(self, card):
        data = card.data
        if not data:
            return
        preview_file = Path(self.pdf_thumbnail_tempdir.name) / (
            f"preview_{id(card)}_{data.get('rotation', 0)}.png"
        )
        render_page_thumbnail(
            data["source_file"],
            data["page_index"],
            preview_file,
            max_width=900,
        )
        pixmap = QPixmap(str(preview_file))
        rotation = data.get("rotation", 0) % 360
        if rotation and not pixmap.isNull():
            pixmap = pixmap.transformed(QTransform().rotate(rotation), Qt.SmoothTransformation)

        dialog = QDialog(self)
        dialog.setWindowTitle(
            f"{Path(data['source_file']).name} - 第 {data['page_index'] + 1} 页"
        )
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

    def add_pdf_paths(self, pdf_files):
        pdf_files = tuple(os.path.abspath(path) for path in pdf_files if path)
        if not pdf_files:
            return False

        def count_pages(progress_callback):
            counts = []
            total = len(pdf_files)
            for index, pdf_file in enumerate(pdf_files, 1):
                progress_callback(
                    index - 1,
                    total,
                    f"正在统计第 {index} / {total} 个 PDF：{Path(pdf_file).name}",
                )
                counts.append((pdf_file, page_count(pdf_file)))
                progress_callback(index, total, f"已统计 {index} / {total} 个 PDF")
            return tuple(counts)

        return self.start_background_task(
            "PDF 工具箱",
            "正在统计 PDF 页数…",
            count_pages,
            lambda counts: self.pdf_page_count_checked(pdf_files, counts),
            lambda error: QMessageBox.critical(self, "读取 PDF 失败", error),
            total=len(pdf_files),
            status_label=self.pdf_status_label,
        )

    def pdf_page_count_checked(self, pdf_files, counts):
        added_pages = sum(count for _pdf_file, count in counts)
        if not self.confirm_large_addition(
            "PDF 页面",
            len(self.pdf_page_cards),
            added_pages,
            PDF_PAGE_WARNING_COUNT,
            PDF_PAGE_MAX_COUNT,
        ):
            return False
        self.set_pdf_output_defaults(pdf_files)
        return self.start_rendering_pdf_pages(counts)

    def start_rendering_pdf_pages(self, counts):
        start_index = len(self.pdf_page_cards)
        jobs = [
            (pdf_file, page_index)
            for pdf_file, count in counts
            for page_index in range(count)
        ]

        def load_pages(progress_callback):
            total = len(jobs)
            pages = []
            for index, (pdf_file, page_index) in enumerate(jobs, 1):
                progress_callback(
                    index - 1,
                    total,
                    f"正在生成第 {index} / {total} 页缩略图：{Path(pdf_file).name}",
                )
                thumbnail = Path(self.pdf_thumbnail_tempdir.name) / (
                    f"thumb_{start_index + index}_{uuid.uuid4().hex}.png"
                )
                pages.append(
                    {
                        "source_file": pdf_file,
                        "page_index": page_index,
                        "rotation": 0,
                        "thumbnail": render_page_thumbnail(
                            pdf_file, page_index, thumbnail
                        ),
                    }
                )
                progress_callback(index, total, f"已读取 {index} / {total} 页")
            return pages

        def pages_loaded(pages):
            for data in pages:
                card = PdfPageCard(self, data)
                card.update_display(len(self.pdf_page_cards) + 1)
                self.pdf_page_cards.append(card)
            self.refresh_pdf_page_numbers()
            self.refresh_pdf_page_cards_layout()

        return self.start_background_task(
            "PDF 工具箱",
            "正在读取 PDF 并生成页面缩略图…",
            load_pages,
            pages_loaded,
            lambda error: QMessageBox.critical(self, "读取 PDF 失败", error),
            total=len(jobs),
            status_label=self.pdf_status_label,
        )

    def add_pdf_files(self):
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "选择一个或多个 PDF",
            self.dialog_folder("open"),
            "PDF 文件 (*.pdf)",
        )
        if filenames:
            self.remember_dialog_folder("open", filenames[0])
        self.add_pdf_paths(filenames)

    def choose_pdf_output_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择 PDF 结果保存文件夹",
            self.dialog_folder("save", self.pdf_output_folder),
            QFileDialog.ShowDirsOnly,
        )
        if not folder:
            return
        self.pdf_output_folder = os.path.abspath(folder)
        self.remember_dialog_folder("save", self.pdf_output_folder)
        self.pdf_output_folder_edit.setText(self.pdf_output_folder)
        self.pdf_output_folder_edit.setToolTip(self.pdf_output_folder)
        self.update_pdf_button_states()

    def clear_pdf_pages(self):
        if self.pdf_page_cards and not self.confirm_list_change("是否清空所有 PDF 页面"):
            return
        for card in self.pdf_page_cards:
            card.setParent(None)
            card.deleteLater()
        self.pdf_page_cards = []
        self.refresh_pdf_page_cards_layout()
        self.refresh_pdf_page_numbers()

    def rotate_selected_pdf_pages(self, degrees):
        for card in self.selected_pdf_page_items():
            data = dict(card.data)
            data["rotation"] = (data.get("rotation", 0) + degrees) % 360
            card.data = data
        self.refresh_pdf_page_numbers()

    def delete_selected_pdf_pages(self):
        selected = self.selected_pdf_page_items()
        if not selected:
            return
        if not self.confirm_list_change(f"是否删除勾选的 {len(selected)} 页"):
            return
        for card in selected:
            self.pdf_page_cards.remove(card)
            card.setParent(None)
            card.deleteLater()
        self.refresh_pdf_page_cards_layout()
        self.refresh_pdf_page_numbers()

    def choose_pdf_marks_source(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择需要添加水印或页码的 PDF",
            self.dialog_folder("open"),
            "PDF 文件 (*.pdf)",
        )
        if not filename:
            return
        self.remember_dialog_folder("open", filename)
        self.pdf_marks_source_file = os.path.abspath(filename)
        self.pdf_marks_source_edit.setText(self.pdf_marks_source_file)
        self.pdf_marks_source_edit.setToolTip(self.pdf_marks_source_file)
        self.pdf_marks_output_folder = str(Path(filename).parent / "output")
        self.pdf_marks_output_folder_edit.setText(self.pdf_marks_output_folder)
        self.pdf_marks_output_name_edit.setText(
            default_output_name(f"{Path(filename).stem}_水印页码")
        )
        self.pdf_marks_status_label.setText("已选择 PDF，确认设置后可生成新文件")
        self.update_pdf_marks_controls()

    def choose_pdf_marks_output_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择水印和页码结果保存文件夹",
            self.dialog_folder("save", self.pdf_marks_output_folder),
            QFileDialog.ShowDirsOnly,
        )
        if not folder:
            return
        self.pdf_marks_output_folder = os.path.abspath(folder)
        self.remember_dialog_folder("save", folder)
        self.pdf_marks_output_folder_edit.setText(self.pdf_marks_output_folder)
        self.update_pdf_marks_controls()

    def update_pdf_marks_controls(self):
        watermark_enabled = self.pdf_watermark_checkbox.isChecked()
        for widget in (
            self.pdf_watermark_text_edit,
            self.pdf_watermark_opacity_spinbox,
            self.pdf_watermark_angle_spinbox,
            self.pdf_watermark_size_spinbox,
            self.pdf_watermark_position_combo,
        ):
            widget.setEnabled(watermark_enabled)
        self.pdf_page_number_start_spinbox.setEnabled(
            self.pdf_page_number_checkbox.isChecked()
        )
        self.pdf_page_number_position_combo.setEnabled(
            self.pdf_page_number_checkbox.isChecked()
        )
        self.pdf_marks_start_button.setEnabled(
            bool(self.pdf_marks_source_file and self.pdf_marks_output_folder)
            and (watermark_enabled or self.pdf_page_number_checkbox.isChecked())
        )

    def create_marked_pdf(self):
        watermark_text = (
            self.pdf_watermark_text_edit.text().strip()
            if self.pdf_watermark_checkbox.isChecked()
            else ""
        )
        add_page_numbers = self.pdf_page_number_checkbox.isChecked()
        if not watermark_text and not add_page_numbers:
            QMessageBox.warning(self, "尚未完成设置", "请填写水印文字或启用页码。")
            return
        try:
            output_file = output_path(
                self.pdf_marks_output_folder,
                self.pdf_marks_output_name_edit.text(),
                default_output_name("水印页码结果"),
            )
        except Exception as error:
            QMessageBox.critical(self, "无法生成", str(error))
            return

        source_file = self.pdf_marks_source_file
        watermark_opacity = self.pdf_watermark_opacity_spinbox.value() / 100
        watermark_angle = self.pdf_watermark_angle_spinbox.value()
        watermark_size = self.pdf_watermark_size_spinbox.value()
        watermark_position = self.pdf_watermark_position_combo.currentData()
        page_number_start = self.pdf_page_number_start_spinbox.value()
        page_number_position = self.pdf_page_number_position_combo.currentData()

        def completed(result):
            self.pdf_marks_result_file = result.output_file
            self.pdf_marks_status_label.setText(
                f"已生成：{Path(result.output_file).name}"
            )
            self.save_pdf_result_message("PDF 水印与页码完成", result)

        self.start_background_task(
            "正在生成 PDF",
            f"正在处理：{Path(source_file).name}",
            lambda progress: add_pdf_marks(
                source_file,
                output_file,
                watermark_text=watermark_text,
                watermark_opacity=watermark_opacity,
                watermark_angle=watermark_angle,
                watermark_font_size=watermark_size,
                watermark_position=watermark_position,
                add_page_numbers=add_page_numbers,
                page_number_start=page_number_start,
                page_number_position=page_number_position,
                progress_callback=progress,
            ),
            completed,
            lambda error: QMessageBox.critical(self, "生成失败", error),
            status_label=self.pdf_marks_status_label,
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
                    "检测到扫描页，请先在设置中填写所选 OCR 平台的密钥。",
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
        detail += f"\n\n日志文件：\n{result.log_file}"
        message.setInformativeText(detail.strip())
        open_button = message.addButton("打开结果", QMessageBox.ActionRole)
        ok_button = message.addButton("确 定", QMessageBox.AcceptRole)
        for button in (ok_button, open_button):
            button.setFixedSize(112, 36)
        message.setDefaultButton(ok_button)
        message.exec()
        if message.clickedButton() == open_button and open_target:
            self.open_output_file(open_target)

    def save_pdf_pages(self):
        if not self.pdf_page_cards:
            QMessageBox.warning(self, "没有页面", "请先添加 PDF 页面。")
            return
        try:
            output_file = output_path(
                self.pdf_output_folder,
                self.pdf_output_name_edit.text(),
                default_output_name("PDF合并结果"),
            )
            page_refs = self.pdf_page_refs_from_items(self.all_pdf_page_items())
        except Exception as error:
            QMessageBox.critical(self, "保存失败", str(error))
            return

        def saved(result):
            self.pdf_status_label.setText(f"已保存：{Path(result.output_file).name}")
            self.save_pdf_result_message("PDF 保存完成", result)

        self.start_background_task(
            "正在保存 PDF",
            "正在按当前顺序生成 PDF…",
            lambda _progress: save_pages(page_refs, output_file, "PDF 页面整理"),
            saved,
            lambda error: QMessageBox.critical(self, "保存失败", error),
            status_label=self.pdf_status_label,
        )

    def split_selected_pdf_pages(self):
        selected = self.selected_pdf_page_items()
        if not selected:
            return
        try:
            output_file = output_path(
                self.pdf_output_folder,
                default_output_name("PDF拆分结果"),
                default_output_name("PDF拆分结果"),
            )
            page_refs = self.pdf_page_refs_from_items(selected)
        except Exception as error:
            QMessageBox.critical(self, "拆分失败", str(error))
            return

        def split_saved(result):
            self.pdf_status_label.setText(f"已拆分：{Path(result.output_file).name}")
            self.save_pdf_result_message("PDF 拆分完成", result)

        self.start_background_task(
            "正在拆分 PDF",
            "正在保存勾选的页面…",
            lambda _progress: save_pages(
                page_refs, output_file, "PDF 拆分选中页面"
            ),
            split_saved,
            lambda error: QMessageBox.critical(self, "拆分失败", error),
            status_label=self.pdf_status_label,
        )

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
        try:
            output_file = output_path(
                self.pdf_compress_output_folder_edit.text(),
                self.pdf_compress_output_name_edit.text(),
                default_output_name("PDF压缩结果"),
            )
        except Exception as error:
            QMessageBox.critical(self, "压缩失败", str(error))
            return
        source_file = self.pdf_compress_source_file
        preset = self.current_pdf_compression_preset()

        def compressed(result):
            if result.saved_percent > 0:
                text = (
                    f"压缩完成：{format_file_size(result.source_size)} → "
                    f"{format_file_size(result.output_size)}，节省 {result.saved_percent}%"
                )
            else:
                text = "压缩完成，但这个 PDF 压缩效果不明显。"
            self.pdf_compress_status_label.setText(text)
            self.save_pdf_result_message("PDF 压缩完成", result, text)

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
        self.pdf_image_mode_button.setProperty("variant", "primary" if index == 0 else "ghost")
        self.pdf_export_mode_button.setProperty("variant", "primary" if index == 1 else "ghost")
        self.pdf_image_mode_button.style().unpolish(self.pdf_image_mode_button)
        self.pdf_image_mode_button.style().polish(self.pdf_image_mode_button)
        self.pdf_export_mode_button.style().unpolish(self.pdf_export_mode_button)
        self.pdf_export_mode_button.style().polish(self.pdf_export_mode_button)

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
        pixmap = QPixmap(card.image_file)
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
        skipped_before_check = 0
        for filename in filenames:
            normalized = os.path.abspath(filename)
            if normalized in seen:
                continue
            seen.add(normalized)
            path = Path(normalized)
            if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
                skipped_before_check += 1
                continue
            candidates.append(normalized)
        if not candidates:
            QMessageBox.information(self, "没有图片", "没有找到可用图片。")
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
                    f"image_{uuid.uuid4().hex}.jpg"
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
            if not prepared:
                QMessageBox.information(self, "没有图片", "没有找到可用图片。")
            elif skipped:
                self.pdf_image_status_label.setText(
                    f"已添加 {len(self.pdf_image_cards)} 张图片，"
                    f"跳过 {skipped} 个非图片或无法读取文件。"
                )

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
        if not self.confirm_list_change(f"是否删除勾选的 {len(selected)} 张图片"):
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
            output_file = output_path(
                self.pdf_image_output_folder_edit.text(),
                self.pdf_image_output_name_edit.text(),
                default_output_name("图片合成PDF"),
            )
            self.sync_pdf_image_source_files()
            image_files = tuple(self.pdf_image_source_files)
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
                f"失败 PDF：{failure_count} 个\n"
                f"生成图片：{image_count} 张"
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

    def refresh_file_list(self, selected_row=None):
        self.refreshing_list = True
        self.checked_files.intersection_update(self.files)
        self.file_table.clear()

        if not self.files:
            empty_item = QTreeWidgetItem(
                ["", "暂无文件，请添加 Excel 文件", "", "", "", "", ""]
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
                        str(info.get("columns", "读取中")),
                        str(info.get("merged_cells", "读取中")),
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
                item.setTextAlignment(4, Qt.AlignCenter)
                item.setTextAlignment(5, Qt.AlignCenter)
                item.setToolTip(1, filename)
                item.setToolTip(6, filename)
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
            def read_file_info(progress_callback):
                info_by_file = {}
                failures = []
                total = len(new_paths)
                for index, filename in enumerate(new_paths, start=1):
                    progress_callback(
                        index - 1,
                        total,
                        f"正在读取第 {index} / {total} 个：{os.path.basename(filename)}",
                    )
                    try:
                        info_by_file[filename] = get_file_info(filename)
                    except Exception as error:
                        try:
                            size = format_file_size(os.path.getsize(filename))
                        except OSError:
                            size = "无法读取"
                        info_by_file[filename] = {
                            "size": size,
                            "rows": "无法读取",
                            "columns": "无法读取",
                            "merged_cells": "无法读取",
                        }
                        failures.append((filename, str(error)))
                    progress_callback(index, total, f"已读取 {index} / {total} 个文件")
                return info_by_file, failures

            def file_info_loaded(result):
                info_by_file, failures = result
                self.file_info.update(info_by_file)
                self.refresh_file_list(
                    selected_row=len(self.files) - 1 if self.files else None
                )
                if failures:
                    detail = "\n".join(
                        f"{Path(filename).name}：{error}"
                        for filename, error in failures[:10]
                    )
                    QMessageBox.warning(
                        self,
                        "部分文件信息读取失败",
                        f"有 {len(failures)} 个文件暂时无法读取：\n\n{detail}",
                    )

            self.start_background_task(
                "读取 Excel 文件",
                f"准备读取 {len(new_paths)} 个文件…",
                read_file_info,
                file_info_loaded,
                lambda error: QMessageBox.critical(
                    self, "文件信息读取失败", error
                ),
                total=len(new_paths),
                status_label=self.status_label,
            )

        self.refresh_file_list(selected_row=len(self.files) - 1 if self.files else None)
        return len(new_paths)

    def add_files(self):
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "选择 Excel 文件",
            self.dialog_folder("open"),
            "Excel 文件 (*.xlsx *.xlsm)",
        )
        if not filenames:
            return
        self.remember_dialog_folder("open", filenames[0])

        added_count = self.add_paths(filenames)
        self.status_label.setText(
            f"已添加 {added_count} 个文件，列表共 {len(self.files)} 个"
        )

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择 Excel 文件夹",
            self.dialog_folder("open"),
            QFileDialog.ShowDirsOnly,
        )
        if folder:
            self.remember_dialog_folder("open", folder)
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

    def confirm_large_addition(self, label, current, added, warning, maximum):
        total = current + added
        if total > maximum:
            QMessageBox.warning(
                self,
                "超过数量限制",
                f"{label}数量最多为 {maximum:,}，本次没有添加。",
            )
            return False
        if current <= warning < total:
            return QMessageBox.question(
                self,
                "数量较多",
                f"添加后共有 {total:,} 个{label}，处理可能较慢。\n\n"
                "是否继续？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            ) == QMessageBox.Yes
        return True

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
        default_path = Path(self.dialog_folder("save")) / default_output_filename(self.system_locale)
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
        self.remember_dialog_folder("save", self.output_file)
        self.output_path_edit.setText(self.output_file)
        self.output_path_edit.setToolTip(self.output_file)
        self.update_button_states()

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
                "请先在软件设置中填写所选 OCR 平台的密钥。",
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
        ok_button = message.addButton("确 定", QMessageBox.AcceptRole)
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
        ok_button = message.addButton("确 定", QMessageBox.AcceptRole)
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

    def closeEvent(self, event):
        running_threads = [
            thread for thread in self.findChildren(QThread) if thread.isRunning()
        ]
        if running_threads:
            QMessageBox.warning(
                self,
                "任务正在进行",
                "文件处理或连接检查尚未完成，请等待完成后再关闭软件。",
            )
            event.ignore()
            return
        super().closeEvent(event)

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
        ok_button = message.addButton("确 定", QMessageBox.AcceptRole)
        for button in (ok_button, open_button):
            button.setFixedSize(112, 36)
        message.setDefaultButton(ok_button)
        message.exec()
        if message.clickedButton() == open_button:
            self.open_output_file(self.document_result_file)

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
        options = self.current_cleanup_options()

        def worker(_progress_callback):
            return preview_cleanup(self.cleanup_source_file, options)

        self.start_background_task(
            "检查 Excel",
            f"正在检查工作表：{options.sheet_name}",
            worker,
            self.display_cleanup_preview,
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
            "选择输出文件夹",
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

        files = tuple(self.files)
        output_file = self.output_file
        skip_rows = self.skip_rows_spinbox.value()
        keep_merged_cells = self.merged_cells_checkbox.isChecked()

        def merge_task(progress_callback):
            build_merged_workbook(
                files,
                output_file,
                skip_rows=skip_rows,
                keep_merged_cells=keep_merged_cells,
                progress_callback=lambda value, filename: progress_callback(
                    value,
                    len(files),
                    f"正在合并第 {value} / {len(files)} 个：{filename}",
                ),
            )
            return output_file

        def merge_completed(_result):
            self.status_label.setText(f"合并完成，共处理 {len(files)} 个文件")
            self.show_merge_complete_message()

        self.start_background_task(
            "正在合并 Excel",
            f"准备合并 {len(files)} 个文件…",
            merge_task,
            merge_completed,
            lambda error: QMessageBox.critical(
                self,
                "合并失败",
                "出现错误：\n"
                f"{error}\n\n"
                "建议检查文件是否正在被 Excel 打开、损坏、加密或包含特殊格式。",
            ),
            total=len(files),
            status_label=self.status_label,
        )
