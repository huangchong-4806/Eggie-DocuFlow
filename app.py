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
    QMimeData,
    QThread,
    QTimer,
    QSize,
    QSettings,
    Signal,
    Qt,
    QTranslator,
    QUrl,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QDrag,
    QFont,
    QIcon,
    QPainter,
    QPen,
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
    QSpinBox,
    QStackedWidget,
    QStyle,
    QStyleOptionSpinBox,
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
from batch_rename_tool import (
    RenameOptions,
    apply_renames,
    discover_rename_files,
    preview_renames,
)
from document_router import process_document
from api_layer import (
    PROVIDER_LABELS,
    extract_document_to_files,
    inspect_pdf,
    is_provider_configured,
    process_document_with_ocr,
)
from api_layer.config import select_provider, selected_provider
from ocr_settings_dialog import SoftwareSettingsDialog
from pdf_invoice_tool import (
    convert_invoice_pdfs,
    write_invoice_ledger,
)
from pdf_toolbox import (
    COMPRESSION_PRESETS,
    IMAGE_SUFFIXES,
    PdfPageRef,
    compress_pdf,
    default_output_name,
    estimate_compressed_size,
    images_to_pdf,
    output_path,
    page_count,
    pdfs_to_images,
    prepare_image_thumbnail,
    render_page_thumbnail,
    save_pages,
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
PDF_PAGE_DRAG_MIME = "application/x-eggie-pdf-page-card"
PDF_IMAGE_DRAG_MIME = "application/x-eggie-pdf-image-card"
PDF_PAGE_CARD_WIDTH = 176
PDF_PAGE_CARD_HEIGHT = 282
PDF_PAGE_CARD_H_SPACING = 18
PDF_PAGE_CARD_V_SPACING = 34
PDF_PAGE_THUMBNAIL_SIZE = QSize(132, 180)
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


class DocumentOCRThread(QThread):
    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, task_kind, source_file, output_folder, provider, parent=None):
        super().__init__(parent)
        self.task_kind = task_kind
        self.source_file = source_file
        self.output_folder = output_folder
        self.provider = provider

    def _progress(self, value, total, message):
        self.progress.emit(value, total, message)

    def run(self):
        try:
            if self.task_kind == "process":
                result = process_document_with_ocr(
                    self.source_file,
                    self.output_folder,
                    provider_name=self.provider,
                    progress_callback=self._progress,
                )
            else:
                result = extract_document_to_files(
                    self.source_file,
                    self.output_folder,
                    self.provider,
                    progress_callback=self._progress,
                )
        except Exception as error:
            self.failed.emit(f"{type(error).__name__}: {error}")
            return
        self.completed.emit(result)


class BackgroundTaskThread(QThread):
    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, worker, parent=None):
        super().__init__(parent)
        self.worker = worker

    def _progress(self, value, total, message):
        self.progress.emit(int(value), int(total), str(message))

    def run(self):
        try:
            result = self.worker(self._progress)
        except Exception as error:
            self.failed.emit(f"{type(error).__name__}: {error}")
            return
        self.completed.emit(result)


class PdfPageCard(QWidget):
    def __init__(self, owner, data):
        super().__init__()
        self.owner = owner
        self.data = data
        self.thumbnail_cache = QPixmap()
        self.display_rotation = None
        self.drag_start_position = None
        self.setAcceptDrops(True)
        self.setFixedSize(PDF_PAGE_CARD_WIDTH, PDF_PAGE_CARD_HEIGHT)
        self.setProperty("pdfCard", "true")
        self.setProperty("checked", "false")
        self.setProperty("dragging", "false")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.thumbnail_box = QWidget()
        self.thumbnail_box.setObjectName("pdfThumbnailBox")
        self.thumbnail_box.setFixedSize(148, 192)
        thumbnail_layout = QGridLayout(self.thumbnail_box)
        thumbnail_layout.setContentsMargins(6, 6, 6, 6)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.checkbox = QCheckBox()
        self.checkbox.setFixedSize(24, 24)
        thumbnail_layout.addWidget(self.image_label, 0, 0, Qt.AlignCenter)
        thumbnail_layout.addWidget(self.checkbox, 0, 0, Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(self.thumbnail_box, 0, Qt.AlignHCenter)

        self.page_label = QLabel()
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setFixedHeight(24)
        self.page_label.setProperty("pdfCardTitle", "true")
        self.file_label = QLabel()
        self.file_label.setAlignment(Qt.AlignCenter)
        self.file_label.setFixedHeight(22)
        self.file_label.setWordWrap(False)
        self.file_label.setProperty("pdfCardName", "true")
        layout.addWidget(self.page_label)
        layout.addWidget(self.file_label)
        layout.addStretch(1)

        self.checkbox.stateChanged.connect(self.handle_checked_changed)

    def polish(self):
        self.style().unpolish(self)
        self.style().polish(self)

    def is_checked(self):
        return self.checkbox.isChecked()

    def set_checked(self, checked):
        self.checkbox.setChecked(checked)

    def set_dragging(self, dragging):
        self.setProperty("dragging", "true" if dragging else "false")
        self.polish()

    def handle_checked_changed(self):
        self.setProperty("checked", "true" if self.is_checked() else "false")
        self.polish()
        self.owner.refresh_pdf_page_numbers()

    def update_display(self, index):
        rotation = self.data.get("rotation", 0) % 360
        if self.thumbnail_cache.isNull():
            pixmap = QPixmap(self.data.get("thumbnail", ""))
            if not pixmap.isNull():
                self.thumbnail_cache = pixmap.scaled(
                    PDF_PAGE_THUMBNAIL_SIZE,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
        if not self.thumbnail_cache.isNull() and self.display_rotation != rotation:
            display = self.thumbnail_cache
            if rotation:
                display = display.transformed(
                    QTransform().rotate(rotation),
                    Qt.SmoothTransformation,
                )
                display = display.scaled(
                    PDF_PAGE_THUMBNAIL_SIZE,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            self.image_label.setPixmap(display)
            self.display_rotation = rotation
        self.page_label.setText(f"第 {index:03d} 页")
        name = Path(self.data["source_file"]).name
        self.file_label.setText(
            self.file_label.fontMetrics().elidedText(name, Qt.ElideMiddle, PDF_PAGE_CARD_WIDTH - 18)
        )
        self.file_label.setToolTip(name)
        self.setToolTip(
            f"{Path(self.data['source_file']).name}\n"
            f"当前序号：{index}\n"
            f"原页码：{self.data['page_index'] + 1}\n"
            "双击可放大预览，拖拽可调整顺序"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_position = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton) or self.drag_start_position is None:
            super().mouseMoveEvent(event)
            return
        distance = (event.position().toPoint() - self.drag_start_position).manhattanLength()
        if distance < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return

        source_index = self.owner.pdf_page_cards.index(self)
        mime_data = QMimeData()
        mime_data.setData(PDF_PAGE_DRAG_MIME, str(source_index).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        pixmap = self.image_label.pixmap()
        if pixmap:
            drag.setPixmap(pixmap)
        self.set_dragging(True)
        try:
            drag.exec(Qt.MoveAction)
        finally:
            self.set_dragging(False)

    def mouseDoubleClickEvent(self, event):
        self.owner.preview_pdf_page(self)
        event.accept()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(PDF_PAGE_DRAG_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(PDF_PAGE_DRAG_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(PDF_PAGE_DRAG_MIME):
            return
        source_index = int(bytes(event.mimeData().data(PDF_PAGE_DRAG_MIME)).decode("utf-8"))
        target_index = self.owner.pdf_page_cards.index(self)
        if event.position().x() > self.width() / 2:
            target_index += 1
        self.owner.reorder_pdf_page(source_index, target_index)
        event.acceptProposedAction()


class PdfPageBoard(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setAcceptDrops(True)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(8, 8, 8, 8)
        self.grid.setHorizontalSpacing(PDF_PAGE_CARD_H_SPACING)
        self.grid.setVerticalSpacing(PDF_PAGE_CARD_V_SPACING)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.owner.refresh_pdf_page_cards_layout()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(PDF_PAGE_DRAG_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(PDF_PAGE_DRAG_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(PDF_PAGE_DRAG_MIME):
            return
        source_index = int(bytes(event.mimeData().data(PDF_PAGE_DRAG_MIME)).decode("utf-8"))
        self.owner.reorder_pdf_page(source_index, len(self.owner.pdf_page_cards))
        event.acceptProposedAction()


class PdfImageCard(QWidget):
    def __init__(self, owner, image_file, thumbnail_file=""):
        super().__init__()
        self.owner = owner
        self.image_file = image_file
        self.thumbnail_file = thumbnail_file or image_file
        self.thumbnail_cache = QPixmap()
        self.drag_start_position = None
        self.setAcceptDrops(True)
        self.setFixedSize(PDF_PAGE_CARD_WIDTH, PDF_PAGE_CARD_HEIGHT)
        self.setProperty("pdfCard", "true")
        self.setProperty("checked", "false")
        self.setProperty("dragging", "false")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.thumbnail_box = QWidget()
        self.thumbnail_box.setObjectName("pdfThumbnailBox")
        self.thumbnail_box.setFixedSize(148, 192)
        thumbnail_layout = QGridLayout(self.thumbnail_box)
        thumbnail_layout.setContentsMargins(6, 6, 6, 6)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.checkbox = QCheckBox()
        self.checkbox.setFixedSize(24, 24)
        thumbnail_layout.addWidget(self.image_label, 0, 0, Qt.AlignCenter)
        thumbnail_layout.addWidget(self.checkbox, 0, 0, Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(self.thumbnail_box, 0, Qt.AlignHCenter)

        self.page_label = QLabel()
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setFixedHeight(24)
        self.page_label.setProperty("pdfCardTitle", "true")
        self.file_label = QLabel()
        self.file_label.setAlignment(Qt.AlignCenter)
        self.file_label.setFixedHeight(22)
        self.file_label.setWordWrap(False)
        self.file_label.setProperty("pdfCardName", "true")
        layout.addWidget(self.page_label)
        layout.addWidget(self.file_label)
        layout.addStretch(1)

        self.checkbox.stateChanged.connect(self.handle_checked_changed)

    def polish(self):
        self.style().unpolish(self)
        self.style().polish(self)

    def is_checked(self):
        return self.checkbox.isChecked()

    def set_dragging(self, dragging):
        self.setProperty("dragging", "true" if dragging else "false")
        self.polish()

    def handle_checked_changed(self):
        self.setProperty("checked", "true" if self.is_checked() else "false")
        self.polish()
        self.owner.refresh_pdf_image_cards()

    def update_display(self, index):
        if self.thumbnail_cache.isNull():
            pixmap = QPixmap(self.thumbnail_file)
            if not pixmap.isNull():
                self.thumbnail_cache = pixmap.scaled(
                    PDF_PAGE_THUMBNAIL_SIZE,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
        if not self.thumbnail_cache.isNull():
            self.image_label.setPixmap(self.thumbnail_cache)
        else:
            self.image_label.setText("无法预览")
        name = Path(self.image_file).name
        self.page_label.setText(f"第 {index:03d} 张")
        self.file_label.setText(
            self.file_label.fontMetrics().elidedText(name, Qt.ElideMiddle, PDF_PAGE_CARD_WIDTH - 18)
        )
        self.file_label.setToolTip(self.image_file)
        self.setToolTip(f"{name}\n双击可放大预览，拖拽可调整顺序")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_position = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton) or self.drag_start_position is None:
            super().mouseMoveEvent(event)
            return
        distance = (event.position().toPoint() - self.drag_start_position).manhattanLength()
        if distance < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        source_index = self.owner.pdf_image_cards.index(self)
        mime_data = QMimeData()
        mime_data.setData(PDF_IMAGE_DRAG_MIME, str(source_index).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        pixmap = self.image_label.pixmap()
        if pixmap:
            drag.setPixmap(pixmap)
        self.set_dragging(True)
        try:
            drag.exec(Qt.MoveAction)
        finally:
            self.set_dragging(False)

    def mouseDoubleClickEvent(self, event):
        self.owner.preview_pdf_image(self)
        event.accept()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(PDF_IMAGE_DRAG_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(PDF_IMAGE_DRAG_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(PDF_IMAGE_DRAG_MIME):
            return
        source_index = int(bytes(event.mimeData().data(PDF_IMAGE_DRAG_MIME)).decode("utf-8"))
        target_index = self.owner.pdf_image_cards.index(self)
        if event.position().x() > self.width() / 2:
            target_index += 1
        self.owner.reorder_pdf_image(source_index, target_index)
        event.acceptProposedAction()


class PdfImageBoard(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setAcceptDrops(True)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(8, 8, 8, 8)
        self.grid.setHorizontalSpacing(PDF_PAGE_CARD_H_SPACING)
        self.grid.setVerticalSpacing(PDF_PAGE_CARD_V_SPACING)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.owner.refresh_pdf_image_cards_layout()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(PDF_IMAGE_DRAG_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(PDF_IMAGE_DRAG_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(PDF_IMAGE_DRAG_MIME):
            return
        source_index = int(bytes(event.mimeData().data(PDF_IMAGE_DRAG_MIME)).decode("utf-8"))
        self.owner.reorder_pdf_image(source_index, len(self.owner.pdf_image_cards))
        event.acceptProposedAction()


ACCENT_PALETTES = {
    "cyan": {
        "label": "科技蓝",
        "accent": "#3B9DFF",
        "accent_hover": "#2389F0",
        "accent_pressed": "#1675D1",
        "accent_soft_dark": "#0E2B36",
        "accent_border_dark": "#164E63",
        "primary": "#3198F5",
        "primary_hover": "#2389F0",
        "primary_pressed": "#1675D1",
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

ACCENT_SOFT_COLORS = {
    "cyan": "#E8F3FF",
    "green": "#EEF7F1",
    "blue": "#EFF6FF",
    "purple": "#F3E8FF",
}

THEME_BASES = {
    "dark": {
        "window_bg": "#FFFFFF",
        "panel": "#FFFFFF",
        "panel_alt": "#F5F5F6",
        "panel_hover": "#ECEFF2",
        "text": "#50555C",
        "title": "#202327",
        "muted": "#8A8F96",
        "placeholder": "#A1A6AD",
        "border": "#DFE2E6",
        "border_soft": "#EAECF0",
        "table_header": "#F3F4F6",
        "table_row": "#FFFFFF",
        "table_row_alt": "#FAFBFC",
        "input": "#FFFFFF",
        "disabled_bg": "#EEF2F5",
        "disabled_text": "#A0AAB6",
        "danger_bg": "#FFF1F2",
        "danger_text": "#BE123C",
        "danger_border": "#FDA4AF",
        "shadow": "rgba(15, 23, 42, 24)",
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
            "accent_soft": ACCENT_SOFT_COLORS.get(accent_name, "#E8F4F4"),
            "accent_border": accent["primary"],
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
    QWidget#appShell {{
        background: {colors["window_bg"]};
    }}
    QWidget#homePage,
    QWidget#excelPage,
    QWidget#splitPage,
    QWidget#invoicePage,
    QWidget#documentPage,
    QWidget#pdfPage,
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
    QScrollArea {{
        background: transparent;
        border: none;
    }}
    QScrollArea > QWidget > QWidget {{
        background: transparent;
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
        background: {colors["panel"]};
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
    QWidget[pdfCard="true"] {{
        background: {colors["table_row"]};
        border: 1px solid {colors["border_soft"]};
        border-radius: 8px;
    }}
    QWidget[pdfCard="true"][checked="true"] {{
        background: {colors["accent_soft"]};
        border: 1px solid {colors["accent"]};
    }}
    QWidget[pdfCard="true"][dragging="true"] {{
        border: 2px solid {colors["accent"]};
    }}
    QWidget#pdfThumbnailBox {{
        background: #FFFFFF;
        border: 1px solid {colors["border_soft"]};
        border-radius: 6px;
    }}
    QLabel[pdfCardTitle="true"] {{
        color: {colors["title"]};
        font-size: 13px;
        font-weight: 600;
    }}
    QLabel[pdfCardName="true"] {{
        color: {colors["text"]};
        font-size: 12px;
    }}
    QTabWidget::pane {{
        border: 1px solid {colors["border"]};
        border-radius: 10px;
        background: {colors["panel"]};
    }}
    QTabBar::tab {{
        background: {colors["panel_alt"]};
        color: {colors["text"]};
        padding: 8px 14px;
        border: 1px solid {colors["border"]};
        border-bottom: none;
    }}
    QTabBar::tab:selected {{
        background: {colors["accent_soft"]};
        color: {colors["title"]};
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
    QSpinBox {{
        padding-right: 34px;
    }}
    QSpinBox::up-button,
    QSpinBox::down-button {{
        subcontrol-origin: border;
        width: 30px;
        background: {colors["panel_alt"]};
        border-left: 1px solid {colors["border"]};
    }}
    QSpinBox::up-button {{
        subcontrol-position: top right;
        border-bottom: 1px solid {colors["border"]};
        border-top-right-radius: 8px;
    }}
    QSpinBox::down-button {{
        subcontrol-position: bottom right;
        border-bottom-right-radius: 8px;
    }}
    QSpinBox::up-button:hover,
    QSpinBox::down-button:hover {{
        background: {colors["accent_soft"]};
    }}
    QSpinBox::up-arrow,
    QSpinBox::down-arrow {{
        image: none;
        width: 0;
        height: 0;
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
    QPushButton[compactToolbar="true"] {{
        padding: 7px 9px;
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
    QWidget#homePage {{
        background: {colors["window_bg"]};
        color: {colors["title"]};
    }}
    QWidget#homeSidebar {{
        background: {colors["panel_alt"]};
        border-right: 1px solid {colors["border"]};
    }}
    QWidget#homeMain {{
        background: {colors["window_bg"]};
    }}
    QWidget[homePanel="true"],
    QWidget[homeCard="true"] {{
        background: {colors["panel_alt"]};
        border: 1px solid {colors["border"]};
        border-radius: 12px;
    }}
    QWidget[homeStatus="true"] {{
        background: {colors["accent_soft"]};
        border-left: 4px solid {colors["primary"]};
    }}
    QWidget[homeHero="true"] {{
        background: {colors["accent_soft"]};
        border-left: 4px solid {colors["primary"]};
    }}
    QWidget[homeCard="true"]:hover {{
        border: 1px solid {colors["primary"]};
    }}
    QLabel[homeRole="title"] {{
        color: {colors["title"]};
        font-size: 32px;
        font-weight: 700;
    }}
    QLabel[homeRole="section"] {{
        color: {colors["title"]};
        font-size: 22px;
        font-weight: 700;
    }}
    QLabel[homeRole="cardTitle"] {{
        color: {colors["title"]};
        font-size: 18px;
        font-weight: 700;
    }}
    QLabel[homeRole="brand"] {{
        color: {colors["title"]};
        font-size: 15px;
        font-weight: 700;
    }}
    QLabel[homeRole="body"] {{
        color: {colors["text"]};
        font-size: 14px;
    }}
    QLabel[homeRole="muted"] {{
        color: {colors["muted"]};
        font-size: 13px;
    }}
    QPushButton[variant="homeNav"] {{
        background: transparent;
        color: {colors["text"]};
        border: none;
        border-radius: 10px;
        padding: 10px 14px;
        text-align: left;
        font-size: 15px;
        font-weight: 500;
    }}
    QPushButton[variant="homeNav"]:hover {{
        background: {colors["panel_hover"]};
        color: {colors["primary"]};
    }}
    QPushButton[variant="homeNavActive"] {{
        background: {colors["primary"]};
        color: #FFFFFF;
        border: none;
        border-radius: 10px;
        padding: 10px 14px;
        text-align: left;
        font-size: 15px;
        font-weight: 700;
    }}
    QPushButton[variant="homeOpen"] {{
        background: {colors["panel_alt"]};
        color: {colors["title"]};
        border: 1px solid {colors["border"]};
        border-radius: 9px;
        padding: 7px 16px;
        font-weight: 600;
    }}
    QPushButton[variant="homeOpen"]:hover {{
        background: {colors["accent_soft"]};
        border-color: {colors["primary"]};
        color: {colors["primary"]};
    }}
    QPushButton[variant="homePrimary"] {{
        background: {colors["primary"]};
        color: #FFFFFF;
        border: 1px solid {colors["primary"]};
        border-radius: 9px;
        padding: 8px 18px;
        font-weight: 700;
    }}
    QPushButton[variant="homeGhost"] {{
        background: {colors["panel"]};
        color: {colors["title"]};
        border: 1px solid {colors["border"]};
        border-radius: 9px;
        padding: 8px 18px;
        font-weight: 600;
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


class ClearSpinBox(QSpinBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor("#46515D" if self.isEnabled() else "#AAB2BB"))
        pen.setWidthF(2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        for control, direction in (
            (QStyle.SubControl.SC_SpinBoxUp, -1),
            (QStyle.SubControl.SC_SpinBoxDown, 1),
        ):
            rect = self.style().subControlRect(
                QStyle.ComplexControl.CC_SpinBox,
                option,
                control,
                self,
            )
            center_x = rect.center().x()
            center_y = rect.center().y()
            half_width = max(4, min(6, rect.width() // 4))
            half_height = 3
            painter.drawLine(
                center_x - half_width,
                center_y - direction * half_height,
                center_x,
                center_y + direction * half_height,
            )
            painter.drawLine(
                center_x,
                center_y + direction * half_height,
                center_x + half_width,
                center_y - direction * half_height,
            )


class SelectionComboBox(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(self.palette().color(self.foregroundRole()))
        pen.setWidthF(1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        center_x = self.width() - 16
        center_y = self.height() // 2
        painter.drawLine(center_x - 4, center_y - 2, center_x, center_y + 2)
        painter.drawLine(center_x, center_y + 2, center_x + 4, center_y - 2)


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
        self.invoice_source_files = []
        self.invoice_output_folder = ""
        self.document_source_file = ""
        self.document_output_folder = ""
        self.document_result_file = ""
        self.document_ocr_result_file = ""
        self.document_ocr_thread = None
        self.document_ocr_progress = None
        self.document_ocr_task_kind = ""
        self.background_task_thread = None
        self.background_task_progress = None
        self.background_task_status_label = None
        self.background_task_title = ""
        self.rename_source_files = []
        self.rename_previews = []
        self.rename_preview_valid = False
        self.rename_last_log_file = ""
        self.pdf_output_folder = ""
        self.pdf_page_cards = []
        self.pdf_compress_source_file = ""
        self.pdf_image_source_files = []
        self.pdf_image_cards = []
        self.pdf_export_source_files = []
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
        self.app_icon = QIcon(str(resource_path("assets/app_icon.icns")))
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
        self.invoice_page = self.create_invoice_page()
        self.document_page = self.create_document_page()
        self.rename_page = self.create_rename_page()
        self.pdf_page = self.create_pdf_page()
        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.excel_page)
        self.stack.addWidget(self.split_page)
        self.stack.addWidget(self.invoice_page)
        self.stack.addWidget(self.document_page)
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
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(20, 22, 18, 20)
        layout.setSpacing(8)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        self.home_logo_pixmap = QPixmap(str(resource_path("assets/app_icon.png")))
        self.home_logo_label = QLabel()
        self.home_logo_label.setFixedSize(52, 52)
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
        add_nav("invoice", "发票解析", self.show_invoice_tool)
        add_nav("document", "文档处理", self.show_document_tool)
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
        main_layout.addLayout(header_layout)

        status = styled_widget(prop_name="homeStatus")
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(18, 12, 18, 12)
        status_layout.addWidget(home_label("✓ 软件已就绪，请从左侧菜单或下方卡片选择工具。", "body"))
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
            home_label("不展示虚假的处理数量或最近文件，只保留真实可用入口。", "muted")
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
            ("XL", "#3198F5", "Excel 合并", "按顺序合并多个表格，并保留主要格式。", self.show_excel_tool),
            ("XL", "#3198F5", "Excel 拆分", "按表头和数据行数拆分成多个文件。", self.show_split_tool),
            ("PDF", "#3198F5", "发票解析", "批量解析发票，并生成台账汇总。", self.show_invoice_tool),
            ("DOC", "#3198F5", "文档处理", "自动识别合同、表格和发票类 PDF。", self.show_document_tool),
            ("REN", "#3198F5", "批量改名", "先预览新文件名，确认后再执行。", self.show_rename_tool),
            ("PDF", "#3198F5", "PDF 工具箱", "页面整理、压缩和图片互转。", self.show_pdf_tool),
        ]
        for index, spec in enumerate(tool_specs):
            self.home_grid.addWidget(tool_card(*spec), index // 2, index % 2)
        tools_layout.addLayout(self.home_grid)
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

    def show_invoice_tool(self):
        self.stack.setCurrentWidget(self.invoice_page)
        self.set_active_navigation("invoice")
        self.setWindowTitle(f"{self.app_name} - PDF发票解析工具")

    def show_document_tool(self):
        self.stack.setCurrentWidget(self.document_page)
        self.set_active_navigation("document")
        self.setWindowTitle(f"{self.app_name} - 文档智能处理")

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
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setWindowModality(Qt.WindowModal)
        if total <= 0:
            progress.setRange(0, 0)
        progress.show()

        thread = BackgroundTaskThread(worker, self)
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
        thread.finished.connect(thread.deleteLater)
        self.set_global_task_active(True)
        thread.start()
        return True

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
        if self.background_task_progress is not None:
            self.background_task_progress.close()
        self.background_task_thread = None
        self.background_task_progress = None
        self.background_task_status_label = None
        self.background_task_title = ""
        self.set_global_task_active(False)
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
        self.rename_rule_primary_edit.clear()
        self.rename_rule_secondary_edit.clear()
        self.rename_rule_count_spinbox.setValue(1)
        self.update_rename_rule_inputs()
        self.schedule_rename_preview()

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

    def schedule_rename_preview(self):
        self.rename_preview_valid = False
        self.rename_preview_timer.start()
        self.update_rename_button_states()

    def refresh_rename_file_list(self, on_complete=None, force_sync=False):
        self.rename_preview_valid = False
        self.update_rename_button_states()
        files = tuple(self.rename_source_files)
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
        self.refresh_rename_file_list(on_complete=self.warn_blank_rename_preview)

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
                previews, progress_callback=progress
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
                f"\n\n台账文件：\n{ledger_result.output_file}"
                f"\n\n日志文件：\n{ledger_result.log_file}"
            )
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
                    len(source_files),
                    len(source_files),
                    "正在生成发票台账和处理日志…",
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

        def invoices_completed(result):
            results, failures, ledger_result, ledger_error = result
            if ledger_error:
                QMessageBox.warning(
                    self,
                    "台账生成失败",
                    f"单张发票 Excel 已生成，但台账汇总失败：\n{ledger_error}",
                )
            if results or failures:
                self.show_invoice_complete_message(results, failures, ledger_result)

        self.start_background_task(
            "正在批量解析发票",
            f"准备解析 {len(source_files)} 个 PDF 发票…",
            process_invoices,
            invoices_completed,
            lambda error: QMessageBox.critical(
                self,
                "发票识别失败",
                f"{error}\n\n未生成未结构化文本或不完整 Excel。",
            ),
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
