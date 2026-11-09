import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from PySide6.QtCore import (
    QFileSystemWatcher,
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
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QFormLayout,
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
    QStyle,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from excel_merge_tool import (
    build_merged_workbook,
    compare_merge_sources,
    inspect_merge_file,
    source_fingerprint,
    discover_excel_files,
    format_file_size,
    get_file_info,
    split_workbook_by_rows,
)
from ui.merge_review import (
    HeaderlessReviewDialog, MergeReviewDialog, SkipRowReviewDialog, skip_row_warnings,
)
from ui.excel_category_split import CategorySplitPage
from ui.presentation import ToolEntry, Disclosure, tool_icon, contain_page_form
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
    compress_pdf,
    compression_io_message,
    compare_pdf_text,
    default_output_name,
    estimate_compressed_size,
    images_to_pdf,
    make_searchable_pdf,
    output_path,
    page_count,
    pdfs_to_images,
    prepare_image_thumbnail,
    secure_pdf,
)
from ui.common_widgets import ClearSpinBox, SelectionComboBox
from ui.feedback import DEFAULT_FEEDBACK_CHANNEL, SETTINGS_KEY, normalize_feedback_channel
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
    load_image_pixmap,
)
from ui.update_check import UpdateCheckButton
from ui.theme import ACCENT_PALETTES, build_theme_colors, build_theme_stylesheet
from ui.tasks import BackgroundTaskThread, DocumentOCRThread, InvoiceBatchProcessThread
from ui.pdf_workspace import PdfWorkspaceWidget
from layout_batch.layout_engine import process_layout_document
from version import APP_VERSION, BUILD_NUMBER, BUILD_TYPE


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
        self._restarting_for_update = False
        self._windows_handoff_dialog = None
        self._windows_update_committed = False
        self.files = []
        self.merge_sources = {}
        self.merge_choices = {}
        self.merge_errors = {}
        self.merge_reads = {}
        self.merge_checks = {}
        self.merge_excluded = set()
        self.merge_watcher = QFileSystemWatcher(self)
        self.merge_watcher.fileChanged.connect(self.merge_source_changed)
        self.header_mode_skip_rows = 1
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
        self.pdf_compress_source_file = ""
        self.pdf_image_source_files = []
        self.pdf_image_cards = []
        self.pdf_export_source_files = []
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
        # Keep the earlier theme preference intact; the approved warm design has its own preference.
        self.accent_name = self.settings.value("appearance/warm-accent", "green")
        if self.accent_name not in ACCENT_PALETTES:
            self.accent_name = "green"
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

        subtitle = QLabel("先核对工作表和表头，再按文件顺序合并。第一份参与文件用作对照表。")
        subtitle.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        subtitle.setProperty("role", "subtitle")
        main_layout.addWidget(subtitle)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        self.add_files_button = QPushButton("添加文件")
        self.add_folder_button = QPushButton("添加文件夹")
        self.move_up_button = QPushButton("上移")
        self.move_down_button = QPushButton("下移")
        self.delete_button = QPushButton("移出列表")
        self.delete_button.setToolTip("从待处理列表移除，不删除原文件")
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

        button_layout.addStretch(1)
        main_layout.addLayout(button_layout)

        file_group = QGroupBox("待合并文件")
        file_group_layout = QVBoxLayout(file_group)
        file_group_layout.setContentsMargins(10, 14, 10, 10)
        file_group_layout.setSpacing(8)

        self.file_table = QTreeWidget()
        self.file_table.setHeaderLabels(
            ["顺序", "文件名", "工作表", "核对表头", "核对结果", "读取范围", "文件信息"]
        )
        self.file_table.setRootIsDecorated(False)
        self.file_table.setUniformRowHeights(True)
        self.file_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_table.setAlternatingRowColors(True)
        self.file_table.setTextElideMode(Qt.ElideRight)
        header = self.file_table.header()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        for column, width in enumerate((72, 175, 152, 86, 185, 145, 245)):
            self.file_table.setColumnWidth(column, width)
        file_group_layout.addWidget(self.file_table, 1)

        actions = QHBoxLayout()
        self.merge_review_button = QPushButton("查看差异 / 选表头")
        self.merge_replace_button = QPushButton("替换这份文件")
        self.merge_exclude_button = QPushButton("本次排除")
        self.merge_refresh_button = QPushButton("重新核对")
        for button in (self.merge_review_button, self.merge_replace_button,
                       self.merge_exclude_button, self.merge_refresh_button):
            actions.addWidget(button)
        actions.addStretch()
        file_group_layout.addLayout(actions)

        self.merge_detail = QLabel()
        self.merge_detail.setTextFormat(Qt.PlainText)
        self.merge_detail.setWordWrap(True)
        file_group_layout.addWidget(self.merge_detail)
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
        options_layout.setAlignment(Qt.AlignLeft)
        options_layout.setSpacing(16)

        skip_rows_label = QLabel("跳过开头行数：")
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
        self.merge_headerless = QCheckBox("无表头，按列位置合并")
        options_layout.addWidget(self.merge_headerless)
        options_layout.addWidget(skip_rows_label)
        options_layout.addWidget(self.skip_rows_spinbox)
        options_layout.addWidget(self.merged_cells_checkbox)
        options_layout.addStretch(1)
        main_layout.addLayout(options_layout)

        self.merge_button = QPushButton("开始合并")
        self.merge_button.setMinimumHeight(38)
        self.merge_button.setMinimumWidth(140)
        self.merge_button.setFont(QFont("PingFang SC", 14, QFont.Bold))
        self.merge_button.setProperty("variant", "primary")
        merge_layout = QHBoxLayout()
        merge_layout.addStretch()
        merge_layout.addWidget(self.merge_button)
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
        self.file_table.itemDoubleClicked.connect(lambda *_: self.review_merge_file())
        self.merge_review_button.clicked.connect(self.review_merge_file)
        self.merge_replace_button.clicked.connect(self.replace_merge_file)
        self.merge_exclude_button.clicked.connect(self.toggle_merge_exclusion)
        self.merge_refresh_button.clicked.connect(self.refresh_merge_sources)
        self.merge_headerless.toggled.connect(self.change_merge_mode)
        self.skip_rows_spinbox.valueChanged.connect(lambda _: self.refresh_file_list())

        self.refresh_file_list()
        self.apply_theme()

    def create_sidebar(self):
        sidebar = QWidget()
        sidebar.setObjectName("homeSidebar")
        sidebar.setAttribute(Qt.WA_StyledBackground, True)
        sidebar.setFixedWidth(200)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 20, 12, 16)
        layout.setSpacing(8)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        self.home_logo_pixmap = QPixmap(str(resource_path("assets/app_icon.png")))
        self.home_logo_label = QLabel()
        self.home_logo_label.setFixedSize(32, 32)
        self.home_logo_label.setAlignment(Qt.AlignCenter)
        if not self.home_logo_pixmap.isNull():
            self.home_logo_label.setPixmap(
                self.home_logo_pixmap.scaled(
                    QSize(32, 32),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
        else:
            self.home_logo_label.setText("Eggie")
        brand.addWidget(self.home_logo_label)

        brand_text = QVBoxLayout()
        brand_text.setSpacing(2)
        name = QLabel("Eggie")
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
            button.setMinimumHeight(38)
            button.setIcon(tool_icon(key))
            button.setIconSize(QSize(18, 18))
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

        version_suffix = {"development": "开发版", "release_candidate": "发布候选版"}.get(BUILD_TYPE, "")
        version = QLabel(f"版本 {APP_VERSION}（{BUILD_NUMBER}）")
        version.setProperty("homeRole", "muted")
        layout.addWidget(version)
        if version_suffix:
            release_type = QLabel(version_suffix)
            release_type.setProperty("homeRole", "muted")
            layout.addWidget(release_type)
        self.update_check_button = UpdateCheckButton(self)
        layout.addWidget(self.update_check_button)
        feedback_button = QPushButton("反馈")
        feedback_button.setMinimumHeight(38)
        feedback_button.setIcon(tool_icon("settings"))
        feedback_button.setProperty("variant", "homeNav")
        feedback_button.setToolTip("打开国内反馈入口，不会跳转到 GitHub")
        feedback_button.clicked.connect(self.open_feedback)
        layout.addWidget(feedback_button)
        settings_button = QPushButton("设置")
        settings_button.setMinimumHeight(38)
        settings_button.setIcon(tool_icon("settings"))
        settings_button.setProperty("variant", "homeNav")
        settings_button.clicked.connect(self.show_settings)
        layout.addWidget(settings_button)
        return sidebar

    def create_home_page(self):
        page = QWidget(); page.setObjectName("homePage")
        root = QVBoxLayout(page); self.home_layout = root
        root.setContentsMargins(28, 24, 28, 24); root.setSpacing(12)
        self.home_title_label = QLabel("工作台"); self.home_title_label.setProperty("role", "title")
        self.home_subtitle_label = QLabel("选择工具，开始处理文件"); self.home_subtitle_label.setProperty("role", "subtitle")
        root.addWidget(self.home_title_label); root.addWidget(self.home_subtitle_label); root.addSpacing(12)
        panel = QWidget(); panel.setProperty("homePanel", "true")
        panel.setAttribute(Qt.WA_StyledBackground, True)
        self.home_grid = QGridLayout(panel); self.home_grid.setContentsMargins(16, 8, 16, 8)
        self.home_grid.setHorizontalSpacing(24); self.home_grid.setVerticalSpacing(0)
        self.home_tool_buttons = []; self.home_tool_cards = []
        specs = [
            ("excel", "Excel 合并", "按顺序合并多个表格", self.show_excel_tool),
            ("split", "Excel 拆分", "按固定行数或指定列分类拆分", self.show_split_tool),
            ("cleanup", "数据清理", "先预览变化，再清理并另存", self.show_cleanup_tool),
            ("invoice", "发票解析", "提取发票信息，每份另存为 Excel", self.show_invoice_tool),
            ("document", "文档处理", "识别 PDF 并生成对应结果", self.show_document_tool),
            ("batch", "批量处理", "逐个处理文件夹中的 PDF", self.show_batch_tool),
            ("rename", "批量改名", "先核对新名称，再执行改名", self.show_rename_tool),
            ("pdf", "PDF 工具箱", "整理页面、脱敏、水印与转换", self.show_pdf_tool),
        ]
        for index, spec in enumerate(specs):
            entry = ToolEntry(*spec)
            self.home_grid.addWidget(entry, index // 2, index % 2)
            self.home_tool_buttons.append(entry); self.home_tool_cards.append(entry)
        root.addWidget(panel); root.addStretch(1)
        return page

    def update_home_responsive_layout(self):
        if not hasattr(self, "home_logo_label"):
            return

        height = max(self.home_page.height(), self.height())
        logo_size = 32
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
            feedback_channel=self.feedback_channel(),
        )
        dialog.setStyleSheet(self.styleSheet())
        dialog.accent_changed.connect(self.save_accent_setting)
        if dialog.exec() == QDialog.Accepted:
            self.save_feedback_channel(dialog.feedback_channel)
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

    def feedback_channel(self):
        try:
            return normalize_feedback_channel(self.settings.value(SETTINGS_KEY, ""))
        except ValueError:
            return DEFAULT_FEEDBACK_CHANNEL

    def save_feedback_channel(self, channel):
        self.settings.setValue(SETTINGS_KEY, normalize_feedback_channel(channel))
        self.settings.sync()

    def open_feedback(self):
        QDesktopServices.openUrl(QUrl(self.feedback_channel()))

    def save_accent_setting(self, accent_name):
        if accent_name not in ACCENT_PALETTES:
            return
        self.accent_name = accent_name
        self.settings.setValue("appearance/warm-accent", self.accent_name)
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

    def restart_for_update(self):
        if self.pdf_workspace.has_unsaved_changes():
            QMessageBox.information(self, "请先处理当前 PDF",
                                    "当前 PDF 还有未保存的修改。处理完成后，可再次点击“重启并更新”。")
            return
        self._restarting_for_update = True
        try:
            self.close()
        finally:
            self._restarting_for_update = False

    def _start_windows_handoff(self):
        dialog = QProgressDialog("正在等待 Windows 授权并核对更新包…", "", 0, 0, self)
        dialog.setWindowTitle("重启并更新")
        dialog.setCancelButton(None)
        dialog.setWindowModality(Qt.WindowModal)
        self._windows_handoff_dialog = dialog
        self.set_global_task_active(True)
        dialog.show()
        self.update_check_button.start_windows_handoff(self._finish_windows_handoff)

    def _finish_windows_handoff(self, error):
        dialog, self._windows_handoff_dialog = self._windows_handoff_dialog, None
        dialog.close()
        dialog.deleteLater()
        if error is not None:
            self.set_global_task_active(False)
            QMessageBox.warning(self, "暂时无法安装更新", str(error))
            return
        self._windows_update_committed = True
        self.close()

    def closeEvent(self, event):
        if self._windows_handoff_dialog is not None:
            self._windows_handoff_dialog.show()
            event.ignore()
            return
        if self._windows_update_committed:
            self.pdf_workspace.shutdown()
            super().closeEvent(event)
            return
        if self.update_check_button.is_downloading():
            QMessageBox.information(self, "正在准备更新", "请先取消下载或等待更新准备完成，再关闭软件。")
            event.ignore()
            return
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
        if not self.pdf_workspace.request_close():
            event.ignore()
            return
        if self._restarting_for_update:
            if self.update_check_button.needs_windows_handoff():
                self._start_windows_handoff()
                event.ignore()
                return
            try:
                self.update_check_button.launch_prepared()
            except Exception as error:
                QMessageBox.warning(self, "暂时无法安装更新", str(error))
                event.ignore()
                return
        else:
            self.update_check_button.discard_prepared()
        self.pdf_workspace.shutdown()
        super().closeEvent(event)

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

import types

from ui.pages import (
    batch_page,
    cleanup_page,
    document_page,
    invoice_page,
    merge_page,
    pdf_page,
    rename_page,
    split_page,
)


def _bind_page_methods(cls, module):
    """Attach page functions with this module's globals so patches stay on app."""
    for name, value in vars(module).items():
        if isinstance(value, types.FunctionType) and value.__module__ == module.__name__:
            rebound = types.FunctionType(
                value.__code__,
                globals(),
                name,
                value.__defaults__,
                value.__closure__,
            )
            rebound.__qualname__ = f"{cls.__name__}.{name}"
            rebound.__doc__ = value.__doc__
            setattr(cls, name, rebound)


for _page in (
    merge_page,
    split_page,
    cleanup_page,
    invoice_page,
    document_page,
    batch_page,
    rename_page,
    pdf_page,
):
    _bind_page_methods(ExcelMergerWindow, _page)
