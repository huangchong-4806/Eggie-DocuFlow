from pathlib import Path

from PySide6.QtCore import QMimeData, QSize, Qt
from PySide6.QtGui import QDrag, QPixmap, QTransform
from PySide6.QtWidgets import QApplication, QCheckBox, QGridLayout, QLabel, QVBoxLayout, QWidget


PDF_PAGE_DRAG_MIME = "application/x-eggie-pdf-page-card"
PDF_IMAGE_DRAG_MIME = "application/x-eggie-pdf-image-card"
PDF_PAGE_CARD_WIDTH = 176
PDF_PAGE_CARD_HEIGHT = 282
PDF_PAGE_CARD_H_SPACING = 18
PDF_PAGE_CARD_V_SPACING = 34
PDF_PAGE_THUMBNAIL_SIZE = QSize(132, 180)


class PdfThumbnailCard(QWidget):
    drag_mime = ""
    owner_cards_attribute = ""
    owner_reorder_method = ""
    owner_preview_method = ""
    owner_checked_method = ""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
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

    def _owner_cards(self):
        return getattr(self.owner, self.owner_cards_attribute)

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
        getattr(self.owner, self.owner_checked_method)()

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

        source_index = self._owner_cards().index(self)
        mime_data = QMimeData()
        mime_data.setData(self.drag_mime, str(source_index).encode("utf-8"))
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
        getattr(self.owner, self.owner_preview_method)(self)
        event.accept()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(self.drag_mime):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(self.drag_mime):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(self.drag_mime):
            return
        source_index = int(bytes(event.mimeData().data(self.drag_mime)).decode("utf-8"))
        target_index = self._owner_cards().index(self)
        if event.position().x() > self.width() / 2:
            target_index += 1
        getattr(self.owner, self.owner_reorder_method)(source_index, target_index)
        event.acceptProposedAction()


class PdfPageCard(PdfThumbnailCard):
    drag_mime = PDF_PAGE_DRAG_MIME
    owner_cards_attribute = "pdf_page_cards"
    owner_reorder_method = "reorder_pdf_page"
    owner_preview_method = "preview_pdf_page"
    owner_checked_method = "refresh_pdf_page_numbers"

    def __init__(self, owner, data):
        super().__init__(owner)
        self.data = data
        self.display_rotation = None

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


class PdfImageCard(PdfThumbnailCard):
    drag_mime = PDF_IMAGE_DRAG_MIME
    owner_cards_attribute = "pdf_image_cards"
    owner_reorder_method = "reorder_pdf_image"
    owner_preview_method = "preview_pdf_image"
    owner_checked_method = "refresh_pdf_image_cards"

    def __init__(self, owner, image_file, thumbnail_file=""):
        super().__init__(owner)
        self.image_file = image_file
        self.thumbnail_file = thumbnail_file or image_file

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


class DragDropBoard(QWidget):
    drag_mime = ""
    owner_cards_attribute = ""
    owner_reorder_method = ""
    owner_refresh_layout_method = ""

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
        getattr(self.owner, self.owner_refresh_layout_method)()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(self.drag_mime):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(self.drag_mime):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(self.drag_mime):
            return
        source_index = int(bytes(event.mimeData().data(self.drag_mime)).decode("utf-8"))
        target_index = len(getattr(self.owner, self.owner_cards_attribute))
        getattr(self.owner, self.owner_reorder_method)(source_index, target_index)
        event.acceptProposedAction()


class PdfPageBoard(DragDropBoard):
    drag_mime = PDF_PAGE_DRAG_MIME
    owner_cards_attribute = "pdf_page_cards"
    owner_reorder_method = "reorder_pdf_page"
    owner_refresh_layout_method = "refresh_pdf_page_cards_layout"


class PdfImageBoard(DragDropBoard):
    drag_mime = PDF_IMAGE_DRAG_MIME
    owner_cards_attribute = "pdf_image_cards"
    owner_reorder_method = "reorder_pdf_image"
    owner_refresh_layout_method = "refresh_pdf_image_cards_layout"


__all__ = [
    "DragDropBoard",
    "PdfImageBoard",
    "PdfImageCard",
    "PdfPageBoard",
    "PdfPageCard",
    "PdfThumbnailCard",
]
