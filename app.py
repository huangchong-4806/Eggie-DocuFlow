"""Assemble the existing tool pages and keep the application window entry point."""
import tempfile
from PySide6.QtCore import QFileSystemWatcher, QSettings
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QWidget,
)
# Preserve imports used by existing callers while implementations live with their pages.
from ui.merge_review import HeaderlessReviewDialog, SkipRowReviewDialog
from ui.common_widgets import ClearSpinBox, SelectionComboBox
from ui.pdf_widgets import PdfImageBoard, PdfImageCard, PdfPageBoard, PdfPageCard
from ui.theme import ACCENT_PALETTES, build_theme_colors, build_theme_stylesheet
from ui.tasks import BackgroundTaskThread, DocumentOCRThread, InvoiceBatchProcessThread
from ui.app_support import (
    APP_NAME_EN,
    APP_NAME_ZH,
    DOCUMENT_TYPE_LABELS,
    PDF_IMAGE_MAX_COUNT,
    PDF_IMAGE_WARNING_COUNT,
    RENAME_MAX_COUNT,
    RENAME_WARNING_COUNT,
    application_icon_path,
    default_output_filename,
    format_elapsed_seconds,
    install_qt_translations,
    is_chinese_locale,
    localized_app_name,
    preferred_system_locale,
    resource_path,
)
from ui.window_shell import WindowShellMixin
from ui.window_tasks import WindowTasksMixin
from ui.pages.merge_page import MergePageMixin
from ui.pages.split_page import SplitPageMixin
from ui.pages.cleanup_page import CleanupPageMixin
from ui.pages.invoice_page import InvoicePageMixin
from ui.pages.document_page import DocumentPageMixin
from ui.pages.batch_page import BatchPageMixin
from ui.pages.rename_page import RenamePageMixin
from ui.pages.pdf_page import PdfPageMixin
from ui.pages.pdf_conversion import PdfConversionMixin


class ExcelMergerWindow(
    WindowShellMixin,
    WindowTasksMixin,
    MergePageMixin,
    SplitPageMixin,
    CleanupPageMixin,
    InvoicePageMixin,
    DocumentPageMixin,
    BatchPageMixin,
    RenamePageMixin,
    PdfPageMixin,
    PdfConversionMixin,
    QMainWindow,
):
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

        self.setup_merge_page()
        self.apply_theme()
