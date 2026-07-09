import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import (
    QLibraryInfo,
    QLocale,
    QMimeData,
    QSize,
    QSettings,
    Qt,
    QTranslator,
    QUrl,
)
from PySide6.QtGui import QDesktopServices, QDrag, QFont, QIcon, QPixmap, QTransform
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
    QInputDialog,
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
    is_supported_image_file,
    output_path,
    page_count,
    pdf_to_images,
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


def is_chinese_locale(locale):
    return locale.language() == QLocale.Chinese


def localized_app_name(locale):
    return APP_NAME_ZH if is_chinese_locale(locale) else APP_NAME_EN


def resource_path(relative_path):
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path / relative_path


class PdfPageCard(QWidget):
    def __init__(self, owner, data):
        super().__init__()
        self.owner = owner
        self.data = data
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
        pixmap = QPixmap(self.data.get("thumbnail", ""))
        if rotation and not pixmap.isNull():
            pixmap = pixmap.transformed(QTransform().rotate(rotation), Qt.SmoothTransformation)
        if not pixmap.isNull():
            pixmap = pixmap.scaled(
                PDF_PAGE_THUMBNAIL_SIZE,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.image_label.setPixmap(pixmap)
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
    def __init__(self, owner, image_file):
        super().__init__()
        self.owner = owner
        self.image_file = image_file
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
        pixmap = QPixmap(self.image_file)
        if not pixmap.isNull():
            pixmap = pixmap.scaled(
                PDF_PAGE_THUMBNAIL_SIZE,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.image_label.setPixmap(pixmap)
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

ACCENT_SOFT_COLORS = {
    "cyan": "#E8F4F4",
    "green": "#EEF7F1",
    "blue": "#EFF6FF",
    "purple": "#F3E8FF",
}

THEME_BASES = {
    "dark": {
        "window_bg": "#F4F7FA",
        "panel": "#FFFFFF",
        "panel_alt": "#F8FAFC",
        "panel_hover": "#F1F5F7",
        "text": "#4E5A67",
        "title": "#202832",
        "muted": "#7A8795",
        "placeholder": "#9AA6B2",
        "border": "#D9E2EA",
        "border_soft": "#E8EEF3",
        "table_header": "#F1F4F7",
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
    QWidget#homePage {{
        background: {colors["window_bg"]};
        color: {colors["title"]};
    }}
    QWidget#homeSidebar {{
        background: {colors["panel"]};
        border-right: 1px solid {colors["border"]};
    }}
    QWidget#homeMain {{
        background: {colors["window_bg"]};
    }}
    QWidget[homePanel="true"],
    QWidget[homeCard="true"] {{
        background: {colors["panel"]};
        border: 1px solid {colors["border"]};
        border-radius: 12px;
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
        background: {colors["accent_soft"]};
        color: {colors["primary"]};
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
        self.rename_source_files = []
        self.rename_previews = []
        self.rename_last_log_file = ""
        self.pdf_output_folder = ""
        self.pdf_page_cards = []
        self.pdf_compress_source_file = ""
        self.pdf_image_source_files = []
        self.pdf_image_cards = []
        self.pdf_export_source_file = ""
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

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

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
        page.setAttribute(Qt.WA_StyledBackground, True)
        root_layout = QHBoxLayout(page)
        self.home_layout = root_layout
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

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

        def nav_button(text, handler=None, active=False):
            button = QPushButton(text)
            button.setMinimumHeight(42)
            button.setProperty("variant", "homeNavActive" if active else "homeNav")
            if handler:
                button.clicked.connect(handler)
            return button

        sidebar = styled_widget("homeSidebar")
        sidebar.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(24, 22, 16, 22)
        sidebar_layout.setSpacing(10)

        brand_layout = QHBoxLayout()
        brand_layout.setSpacing(10)
        self.home_logo_pixmap = QPixmap(str(resource_path("assets/app_icon.png")))
        self.home_logo_label = QLabel()
        self.home_logo_label.setFixedSize(58, 58)
        self.home_logo_label.setScaledContents(True)
        brand_layout.addWidget(self.home_logo_label)
        brand_text_layout = QVBoxLayout()
        brand_text_layout.setSpacing(2)
        brand_text_layout.addWidget(home_label("Eggie", "cardTitle"))
        brand_text_layout.addWidget(home_label("文档处理系统", "muted"))
        brand_layout.addLayout(brand_text_layout, 1)
        sidebar_layout.addLayout(brand_layout)
        sidebar_layout.addSpacing(16)
        sidebar_layout.addWidget(nav_button("工作台", active=True))
        sidebar_layout.addWidget(nav_button("Excel 合并", self.show_excel_tool))
        sidebar_layout.addWidget(nav_button("Excel 拆分", self.show_split_tool))
        sidebar_layout.addWidget(nav_button("PDF 发票解析", self.show_invoice_tool))
        sidebar_layout.addWidget(nav_button("文档智能处理", self.show_document_tool))
        sidebar_layout.addWidget(nav_button("批量改名", self.show_rename_tool))
        sidebar_layout.addWidget(nav_button("PDF 工具箱", self.show_pdf_tool))
        sidebar_layout.addStretch(1)
        sidebar_layout.addWidget(nav_button("软件设置", self.show_settings))
        root_layout.addWidget(sidebar)

        main = styled_widget("homeMain")
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(28, 28, 28, 28)
        main_layout.setSpacing(16)
        root_layout.addWidget(main, 1)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)
        title_layout = QVBoxLayout()
        title_layout.setSpacing(3)
        self.home_title_label = home_label("工作台", "title")
        self.home_subtitle_label = home_label(
            "常用工具、最近结果和软件状态集中在一个页面", "muted"
        )
        title_layout.addWidget(self.home_title_label)
        title_layout.addWidget(self.home_subtitle_label)
        header_layout.addLayout(title_layout, 1)
        self.home_version_label = QLabel(f"版本 {APP_VERSION}")
        self.home_version_label.setProperty("homeRole", "muted")
        self.home_version_label.setAlignment(Qt.AlignCenter)
        self.home_version_label.setMinimumHeight(34)
        self.home_version_label.setMinimumWidth(96)
        self.home_settings_button = QPushButton("设置")
        self.home_settings_button.setMinimumHeight(34)
        self.home_settings_button.setProperty("variant", "homeGhost")
        self.home_settings_button.clicked.connect(self.show_settings)
        header_layout.addWidget(self.home_version_label)
        header_layout.addWidget(self.home_settings_button)
        main_layout.addLayout(header_layout)

        banner = styled_widget(prop_name="homePanel")
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(18, 12, 18, 12)
        banner_layout.setSpacing(12)
        banner_text_layout = QVBoxLayout()
        banner_text_layout.setSpacing(2)
        banner_text_layout.addWidget(
            home_label("选择对应工具即可开始处理 Excel、PDF、发票和文件名", "body")
        )
        banner_text_layout.addWidget(
            home_label("首页只保留真实可用入口，避免按钮过多和信息重叠。", "muted")
        )
        banner_layout.addLayout(banner_text_layout, 1)
        quick_button = QPushButton("打开 Excel 合并")
        quick_button.setProperty("variant", "homePrimary")
        quick_button.setMinimumHeight(38)
        quick_button.clicked.connect(self.show_excel_tool)
        banner_layout.addWidget(quick_button)
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

        def tool_card(tag, accent, title, desc, badge, handler):
            card = styled_widget(prop_name="homeCard")
            card.setMinimumHeight(124)
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
            badge_label = QLabel(badge)
            badge_label.setAlignment(Qt.AlignCenter)
            badge_label.setMinimumWidth(72)
            badge_label.setMinimumHeight(26)
            badge_label.setStyleSheet(
                "background: #EEF7F1; color: #2F7D57; "
                "border-radius: 8px; font-size: 12px;"
            )
            title_row.addWidget(badge_label)
            card_layout.addLayout(title_row)

            bottom_row = QHBoxLayout()
            bottom_row.setSpacing(12)
            desc_label = home_label(desc, "body", True)
            desc_label.setMinimumHeight(38)
            bottom_row.addWidget(desc_label, 1)

            open_button = QPushButton("打开")
            open_button.setProperty("variant", "homeOpen")
            open_button.setMinimumHeight(34)
            open_button.clicked.connect(handler)
            bottom_row.addWidget(open_button, 0, Qt.AlignBottom)
            card_layout.addLayout(bottom_row)
            self.home_tool_buttons.append(open_button)
            self.home_tool_cards.append(card)
            return card

        tool_specs = [
            ("XL", "#12857F", "Excel 合并工具", "多文件合并，合并前检查行数、列数、表头和合并单元格。", "预览检查", self.show_excel_tool),
            ("XL", "#4D83BD", "Excel 拆分工具", "按表头和数据行数拆分，开始前显示预计生成几个文件。", "预计数量", self.show_split_tool),
            ("PDF", "#C46C3B", "PDF 发票解析", "批量解析发票，自动生成单张结果和发票台账汇总。", "台账汇总", self.show_invoice_tool),
            ("DOC", "#8A6FB1", "文档智能处理", "自动判断发票、合同、表格类 PDF，并输出对应结果。", "自动识别", self.show_document_tool),
            ("REN", "#2E8B57", "批量改名工具", "先预览新文件名，确认无重名和异常后再执行。", "先预览", self.show_rename_tool),
            ("PDF", "#A85D70", "PDF 工具箱", "页面整理、压缩、图片转 PDF、PDF 转图片。", "多功能", self.show_pdf_tool),
        ]
        for index, spec in enumerate(tool_specs):
            self.home_grid.addWidget(tool_card(*spec), index // 2, index % 2)
        tools_layout.addLayout(self.home_grid)

        note = styled_widget(prop_name="homePanel")
        note_layout = QVBoxLayout(note)
        note_layout.setContentsMargins(18, 12, 18, 12)
        note_layout.setSpacing(4)
        note_layout.addWidget(home_label("使用提示", "body"))
        note_layout.addWidget(
            home_label("先添加文件并查看预览，确认无误后再开始处理；完成后可打开结果或日志。", "muted", True)
        )
        tools_layout.addWidget(note)
        content_layout.addLayout(tools_layout, 1)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(16)
        info_header = home_label("信息面板", "section")
        info_layout.addWidget(info_header)

        def info_panel(title, lines):
            panel = styled_widget(prop_name="homePanel")
            panel.setMinimumWidth(268)
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(16, 14, 16, 14)
            panel_layout.setSpacing(8)
            panel_layout.addWidget(home_label(title, "cardTitle"))
            for line in lines:
                panel_layout.addWidget(home_label(line, "body", True))
            return panel

        info_layout.addWidget(
            info_panel(
                "最近结果",
                ["处理完成后可直接打开结果文件", "批量工具会保留操作日志", "发票解析会生成台账汇总"],
            )
        )
        info_layout.addWidget(
            info_panel(
                "今日状态",
                [f"当前版本：{APP_VERSION}", "首页和工具页风格已统一", "打包版 logo 已恢复"],
            )
        )
        info_layout.addWidget(
            info_panel(
                "本版优化",
                ["Excel 增加合并前预览", "拆分前显示预计文件数", "发票解析生成台账汇总"],
            )
        )
        info_layout.addStretch(1)
        content_layout.addLayout(info_layout)
        main_layout.addLayout(content_layout, 1)
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
        self.split_header_rows_spinbox.valueChanged.connect(self.update_split_estimate)
        self.split_rows_per_file_spinbox.valueChanged.connect(self.update_split_estimate)
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

    def create_pdf_page(self):
        page = QWidget()
        page.setObjectName("pdfPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)

        tool_header_layout = QHBoxLayout()
        self.pdf_back_home_button = QPushButton("返回工具首页")
        self.pdf_back_home_button.setMinimumHeight(30)
        self.pdf_back_home_button.setProperty("variant", "ghost")
        self.pdf_settings_button = QPushButton("软件设置")
        self.pdf_settings_button.setMinimumHeight(30)
        self.pdf_settings_button.setProperty("variant", "ghost")
        tool_header_layout.addWidget(self.pdf_back_home_button)
        self.pdf_version_label = QLabel(f"版本 {APP_VERSION}")
        self.pdf_version_label.setProperty("role", "hint")
        tool_header_layout.addWidget(self.pdf_version_label)
        tool_header_layout.addStretch()
        tool_header_layout.addWidget(self.pdf_settings_button)
        layout.addLayout(tool_header_layout)

        title = QLabel("PDF 工具箱")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("PingFang SC", 20, QFont.Bold))
        title.setProperty("role", "title")
        layout.addWidget(title)

        subtitle = QLabel("整理页面、压缩文件，并支持图片和 PDF 互转")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setProperty("role", "subtitle")
        layout.addWidget(subtitle)

        self.pdf_tabs = QTabWidget()
        self.pdf_tabs.addTab(self.create_pdf_organizer_tab(), "页面整理")
        self.pdf_tabs.addTab(self.create_pdf_compress_tab(), "PDF 压缩")
        self.pdf_tabs.addTab(self.create_pdf_convert_tab(), "图片 / PDF 互转")
        layout.addWidget(self.pdf_tabs, 1)

        self.pdf_back_home_button.clicked.connect(self.show_home)
        self.pdf_settings_button.clicked.connect(self.show_settings)
        self.update_pdf_button_states()
        return page

    def create_pdf_organizer_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(10)

        button_layout = QHBoxLayout()
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
            button_layout.addWidget(button)
        layout.addLayout(button_layout)

        self.pdf_page_scroll = QScrollArea()
        self.pdf_page_scroll.setWidgetResizable(True)
        self.pdf_page_board = PdfPageBoard(self)
        self.pdf_page_scroll.setWidget(self.pdf_page_board)
        layout.addWidget(self.pdf_page_scroll, 1)

        save_group = QGroupBox("输出设置")
        save_layout = QHBoxLayout(save_group)
        save_layout.setContentsMargins(12, 14, 12, 10)
        self.pdf_output_folder_edit = QLineEdit()
        self.pdf_output_folder_edit.setReadOnly(True)
        self.pdf_output_folder_edit.setPlaceholderText("请选择结果保存文件夹")
        self.pdf_choose_output_folder_button = QPushButton("选择文件夹")
        self.pdf_output_name_edit = QLineEdit()
        self.pdf_output_name_edit.setPlaceholderText(default_output_name("PDF合并结果"))
        save_layout.addWidget(QLabel("文件夹："))
        save_layout.addWidget(self.pdf_output_folder_edit, 2)
        save_layout.addWidget(self.pdf_choose_output_folder_button)
        save_layout.addWidget(QLabel("文件名："))
        save_layout.addWidget(self.pdf_output_name_edit, 1)
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
        self.pdf_export_source_edit = QLineEdit()
        self.pdf_export_source_edit.setReadOnly(True)
        self.pdf_export_source_edit.setPlaceholderText("请选择需要导出图片的 PDF")
        self.pdf_choose_export_source_button = QPushButton("选择 PDF")
        self.pdf_choose_export_source_button.setProperty("variant", "accent")
        self.pdf_export_output_folder_edit = QLineEdit()
        self.pdf_export_output_folder_edit.setReadOnly(True)
        self.pdf_choose_export_output_button = QPushButton("选择文件夹")
        self.pdf_export_format_combo = QComboBox()
        self.pdf_export_format_combo.addItems(["JPG", "PNG"])
        self.pdf_export_button = QPushButton("导出图片")
        self.pdf_export_button.setMinimumHeight(44)
        self.pdf_export_button.setProperty("variant", "primary")
        export_layout.addWidget(self.pdf_export_source_edit)
        export_layout.addWidget(self.pdf_choose_export_source_button)
        export_layout.addWidget(QLabel("保存文件夹："))
        export_layout.addWidget(self.pdf_export_output_folder_edit)
        export_layout.addWidget(self.pdf_choose_export_output_button)
        export_layout.addWidget(QLabel("图片格式："))
        export_layout.addWidget(self.pdf_export_format_combo)
        export_layout.addWidget(self.pdf_export_button)
        self.pdf_export_status_label = QLabel("尚未选择 PDF")
        self.pdf_export_status_label.setProperty("role", "status")
        export_layout.addWidget(self.pdf_export_status_label)
        export_layout.addStretch(1)
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

    def show_pdf_tool(self):
        self.stack.setCurrentWidget(self.pdf_page)
        self.setWindowTitle(f"{self.app_name} - PDF 工具箱")

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
                bool(self.pdf_export_source_file)
                and bool(self.pdf_export_output_folder_edit.text())
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
        pdf_files = [os.path.abspath(path) for path in pdf_files if path]
        if not pdf_files:
            return
        self.set_pdf_output_defaults(pdf_files)
        progress = QProgressDialog("正在生成页面缩略图…", "", 0, len(pdf_files), self)
        progress.setWindowTitle("PDF 工具箱")
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for file_index, pdf_file in enumerate(pdf_files, 1):
                progress.setLabelText(f"正在读取：{Path(pdf_file).name}")
                QApplication.processEvents()
                for page_index in range(page_count(pdf_file)):
                    thumbnail = Path(self.pdf_thumbnail_tempdir.name) / (
                        f"thumb_{len(self.pdf_page_cards)}_{page_index}.png"
                    )
                    data = {
                        "source_file": pdf_file,
                        "page_index": page_index,
                        "rotation": 0,
                        "thumbnail": render_page_thumbnail(pdf_file, page_index, thumbnail),
                    }
                    card = PdfPageCard(self, data)
                    card.update_display(len(self.pdf_page_cards) + 1)
                    self.pdf_page_cards.append(card)
                progress.setValue(file_index)
        except Exception as error:
            QMessageBox.critical(self, "读取 PDF 失败", str(error))
        finally:
            QApplication.restoreOverrideCursor()
            progress.close()

        self.refresh_pdf_page_numbers()
        self.refresh_pdf_page_cards_layout()

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

    def save_pdf_result_message(self, title, result, extra_text=""):
        open_target = result.output_file or (
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
            result = save_pages(
                self.pdf_page_refs_from_items(self.all_pdf_page_items()),
                output_file,
                "PDF 页面整理",
            )
        except Exception as error:
            QMessageBox.critical(self, "保存失败", str(error))
            return
        self.pdf_status_label.setText(f"已保存：{Path(result.output_file).name}")
        self.save_pdf_result_message("PDF 保存完成", result)

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
            result = save_pages(
                self.pdf_page_refs_from_items(selected),
                output_file,
                "PDF 拆分选中页面",
            )
        except Exception as error:
            QMessageBox.critical(self, "拆分失败", str(error))
            return
        self.pdf_status_label.setText(f"已拆分：{Path(result.output_file).name}")
        self.save_pdf_result_message("PDF 拆分完成", result)

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
            result = compress_pdf(
                self.pdf_compress_source_file,
                output_file,
                self.current_pdf_compression_preset(),
            )
        except Exception as error:
            QMessageBox.critical(self, "压缩失败", str(error))
            return

        if result.saved_percent > 0:
            text = (
                f"压缩完成：{format_file_size(result.source_size)} → "
                f"{format_file_size(result.output_size)}，节省 {result.saved_percent}%"
            )
        else:
            text = "压缩完成，但这个 PDF 压缩效果不明显。"
        self.pdf_compress_status_label.setText(text)
        self.save_pdf_result_message("PDF 压缩完成", result, text)

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

    def add_pdf_image_paths(self, filenames):
        if not filenames:
            return 0, 0
        existing = {card.image_file for card in self.pdf_image_cards}
        added = 0
        skipped = 0
        for filename in filenames:
            normalized = os.path.abspath(filename)
            if not is_supported_image_file(normalized):
                skipped += 1
                continue
            if normalized not in existing:
                self.pdf_image_cards.append(PdfImageCard(self, normalized))
                existing.add(normalized)
                added += 1
        if self.pdf_image_cards and not self.pdf_image_output_folder_edit.text():
            folder = str(Path(self.pdf_image_cards[0].image_file).parent / "output")
            self.pdf_image_output_folder_edit.setText(folder)
            self.pdf_image_output_folder_edit.setToolTip(folder)
        if not self.pdf_image_output_name_edit.text():
            self.pdf_image_output_name_edit.setText(default_output_name("图片合成PDF"))
        self.refresh_pdf_image_cards_layout()
        self.refresh_pdf_image_cards()
        return added, skipped

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
        added, skipped = self.add_pdf_image_paths(filenames)
        if skipped:
            self.pdf_image_status_label.setText(
                f"已添加 {len(self.pdf_image_cards)} 张图片，跳过 {skipped} 个非图片或无法读取文件。"
            )

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
        added, skipped = self.add_pdf_image_paths(image_files)
        if not added:
            QMessageBox.information(self, "没有图片", "这个文件夹里没有可用图片。")
            return
        if skipped:
            self.pdf_image_status_label.setText(
                f"已添加 {len(self.pdf_image_cards)} 张图片，跳过 {skipped} 个非图片或无法读取文件。"
            )

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
            result = images_to_pdf(self.pdf_image_source_files, output_file)
        except Exception as error:
            QMessageBox.critical(self, "合成失败", str(error))
            return
        self.pdf_image_status_label.setText(f"已生成：{Path(result.output_file).name}")
        self.save_pdf_result_message("图片合成 PDF 完成", result)

    def choose_pdf_export_source(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择需要导出图片的 PDF",
            self.dialog_folder("open"),
            "PDF 文件 (*.pdf)",
        )
        if not filename:
            return
        self.remember_dialog_folder("open", filename)
        self.pdf_export_source_file = os.path.abspath(filename)
        self.pdf_export_source_edit.setText(self.pdf_export_source_file)
        self.pdf_export_source_edit.setToolTip(self.pdf_export_source_file)
        folder = str(Path(self.pdf_export_source_file).parent / f"{Path(filename).stem}_图片")
        self.pdf_export_output_folder_edit.setText(folder)
        self.pdf_export_output_folder_edit.setToolTip(folder)
        self.pdf_export_status_label.setText("已选择 PDF，可导出图片")
        self.update_pdf_button_states()

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
        try:
            result = pdf_to_images(
                self.pdf_export_source_file,
                self.pdf_export_output_folder_edit.text(),
                self.pdf_export_format_combo.currentText().lower(),
            )
        except Exception as error:
            QMessageBox.critical(self, "导出失败", str(error))
            return
        self.pdf_export_status_label.setText(f"已导出 {len(result.image_files)} 张图片")
        self.save_pdf_result_message("PDF 导出图片完成", result)

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
                        "columns": "无法读取",
                        "merged_cells": "无法读取",
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
        ledger_result = None
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

        if results:
            try:
                ledger_result = write_invoice_ledger(
                    results,
                    failures,
                    self.invoice_output_folder,
                )
            except Exception as error:
                QMessageBox.warning(
                    self,
                    "台账生成失败",
                    f"单张发票 Excel 已生成，但台账汇总失败：\n{error}",
                )

        if results or failures:
            self.show_invoice_complete_message(results, failures, ledger_result)

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

        try:
            info = get_file_info(self.split_source_file)
            self.split_source_info = info
            self.update_split_estimate()
        except Exception as error:
            self.split_source_info = {}
            self.split_source_status_label.setText("已选择文件，但暂时无法读取行数")
            QMessageBox.warning(
                self,
                "文件信息读取失败",
                f"{os.path.basename(self.split_source_file)}\n{error}",
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
