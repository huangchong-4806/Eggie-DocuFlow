from pathlib import Path

from PySide6.QtCore import QMimeData, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QDrag, QImage, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (QApplication, QCheckBox, QGraphicsScene, QGraphicsView,
                               QGridLayout, QLabel, QVBoxLayout, QWidget)


PDF_PAGE_DRAG_MIME = "application/x-eggie-pdf-page-card"
PDF_IMAGE_DRAG_MIME = "application/x-eggie-pdf-image-card"
PDF_PAGE_CARD_WIDTH = 176
PDF_PAGE_CARD_HEIGHT = 282
PDF_PAGE_CARD_H_SPACING = 18
PDF_PAGE_CARD_V_SPACING = 34
PDF_PAGE_THUMBNAIL_SIZE = QSize(132, 180)


def load_image_pixmap(filename):
    """Decode locally supported images even when optional Qt codecs are absent."""
    pixmap = QPixmap(str(filename))
    if not pixmap.isNull():
        return pixmap
    from PIL import Image, ImageOps
    from contextlib import closing
    try:
        with Image.open(filename) as source, closing(ImageOps.exif_transpose(source)) as oriented:
            with closing(oriented.convert("RGBA")) as rgba:
                data = rgba.tobytes()
                image = QImage(data, rgba.width, rgba.height, rgba.width * 4,
                               QImage.Format_RGBA8888).copy()
                return QPixmap.fromImage(image)
    except (OSError, ValueError):
        return QPixmap()


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


class PdfPageCanvas(QGraphicsView):
    area_selected = Signal(object)
    text_selected = Signal(object)
    mark_changed = Signal(str, object)
    mark_deleted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setObjectName("pdfPageCanvas")
        self.setAccessibleName("PDF 页面预览与涂黑选区")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setBackgroundBrush(QColor("#E7E8E2"))
        self.setAlignment(Qt.AlignCenter)
        self.preview = None
        self.source_transform = QTransform()
        self.marks = ()
        self.mode = "area"
        self.selected_mark = None
        self._overlays = []
        self._drag = None
        self._fit = "page"

    def set_page(self, preview):
        self.scene().clear()
        self._overlays = []
        self._drag = None
        self.preview = preview
        if not preview:
            return
        pixmap = QPixmap()
        pixmap.loadFromData(preview["png"], "PNG")
        item = self.scene().addPixmap(pixmap)
        item.setTransform(QTransform.fromScale(preview["width_pt"] / pixmap.width(), preview["height_pt"] / pixmap.height()))
        self.source_transform = QTransform(*preview["source_to_view"])
        self.page_rect = QRectF(0, 0, preview["width_pt"], preview["height_pt"])
        self.source_rect = self.source_transform.inverted()[0].mapRect(self.page_rect)
        self.scene().setSceneRect(self.page_rect)
        self.set_marks(self.marks)
        self._apply_fit()

    def set_mode(self, mode):
        self.mode = mode
        self._drag = None
        self.setDragMode(QGraphicsView.ScrollHandDrag if mode == "hand" else QGraphicsView.NoDrag)
        self.viewport().setCursor(Qt.OpenHandCursor if mode == "hand" else Qt.CrossCursor if mode in ("area", "text") else Qt.ArrowCursor)

    def set_marks(self, marks):
        self.marks = tuple(marks)
        self._paint_marks()

    def _paint_marks(self, temporary=()):
        for item in self._overlays:
            self.scene().removeItem(item)
        self._overlays.clear()
        if not self.preview:
            return
        for mark in self.marks:
            if mark.page_id != self.preview["page_id"] or (self._drag and self._drag.get("mark") == mark.mark_id):
                continue
            for rect in mark.rects:
                if not mark.applied or mark.mark_id == self.selected_mark:
                    self._add_overlay(rect, selected=mark.mark_id == self.selected_mark, applied=mark.applied)
        for rect in temporary:
            self._add_overlay(rect, selected=True)

    def _add_overlay(self, rect, selected=False, applied=False):
        view_rect = self.source_transform.mapRect(QRectF(rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]))
        color = QColor("#2563eb" if selected else "#db4444")
        pen = QPen(color, 1.4, Qt.SolidLine if selected else Qt.DashLine)
        pen.setCosmetic(True)
        fill = QColor(37, 99, 235, 35) if selected else QColor(239, 68, 68, 35)
        self._overlays.append(self.scene().addRect(view_rect, pen, QBrush(Qt.NoBrush) if applied else QBrush(fill)))
        if selected and not applied:
            size = 6 / max(self.transform().m11(), 0.1)
            for corner in (view_rect.topLeft(), view_rect.topRight(), view_rect.bottomLeft(), view_rect.bottomRight()):
                self._overlays.append(self.scene().addRect(QRectF(corner.x() - size / 2, corner.y() - size / 2, size, size), pen, QBrush(Qt.white)))

    def _source_point(self, position):
        point = self.source_transform.inverted()[0].map(self.mapToScene(position))
        return QPointF(max(self.source_rect.left(), min(self.source_rect.right(), point.x())),
                       max(self.source_rect.top(), min(self.source_rect.bottom(), point.y())))

    def _text_rects(self, start, end):
        chars = self.preview["chars"]
        def box(char):
            x0, y0, x1, y1 = char["bbox"]
            return QRectF(x0, y0, x1 - x0, y1 - y0)
        first = next((i for i, char in enumerate(chars) if box(char).contains(start)), None)
        if first is None:
            return ()
        last = min(range(len(chars)), key=lambda i: (box(chars[i]).center() - end).manhattanLength())
        lines = {}
        for char in chars[min(first, last):max(first, last) + 1]:
            rect = box(char)
            key = char["line_id"]
            lines[key] = lines[key].united(rect) if key in lines else rect
        return tuple((r.left(), r.top(), r.right(), r.bottom()) for r in lines.values())

    def mousePressEvent(self, event):
        if not self.preview or event.button() != Qt.LeftButton or self.mode == "hand":
            return super().mousePressEvent(event)
        if not self.page_rect.contains(self.mapToScene(event.position().toPoint())):
            return
        point = self._source_point(event.position().toPoint())
        self._drag = {"start": point, "rects": ()}
        if self.mode == "select":
            self.selected_mark = None
            for mark in reversed(self.marks):
                if mark.page_id != self.preview["page_id"]:
                    continue
                for coords in mark.rects:
                    rect = QRectF(coords[0], coords[1], coords[2] - coords[0], coords[3] - coords[1])
                    tolerance = 8 / max(self.transform().m11(), 0.1)
                    if rect.adjusted(-tolerance, -tolerance, tolerance, tolerance).contains(point):
                        self.selected_mark = mark.mark_id
                        if not mark.applied and mark.mode == "area":
                            corners = (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight())
                            corner = next((i for i, p in enumerate(corners) if (p - point).manhattanLength() < tolerance * 2), None)
                            self._drag.update(mark=mark.mark_id, original=rect, corner=corner, rects=(coords,))
                        break
                if self.selected_mark:
                    break
            if "mark" not in self._drag:
                self._drag = None
        self._paint_marks(self._drag["rects"] if self._drag else ())
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._drag:
            return super().mouseMoveEvent(event)
        point = self._source_point(event.position().toPoint())
        start = self._drag["start"]
        if "mark" in self._drag:
            rect = QRectF(self._drag["original"])
            corner = self._drag["corner"]
            if corner is None:
                rect.translate(point - start)
                rect.translate(max(self.source_rect.left() - rect.left(), min(0, self.source_rect.right() - rect.right())),
                               max(self.source_rect.top() - rect.top(), min(0, self.source_rect.bottom() - rect.bottom())))
            else:
                (rect.setTopLeft, rect.setTopRight, rect.setBottomLeft, rect.setBottomRight)[corner](point)
                rect = rect.normalized()
            self._drag["rects"] = ((rect.left(), rect.top(), rect.right(), rect.bottom()),)
        elif self.mode == "text":
            self._drag["rects"] = self._text_rects(start, point)
        else:
            rect = QRectF(start, point).normalized()
            self._drag["rects"] = ((rect.left(), rect.top(), rect.right(), rect.bottom()),)
        self._paint_marks(self._drag["rects"])
        event.accept()

    def mouseReleaseEvent(self, event):
        if not self._drag or event.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(event)
        self.mouseMoveEvent(event)
        drag, self._drag = self._drag, None
        rects = tuple(r for r in drag["rects"] if r[2] - r[0] >= 1 and r[3] - r[1] >= 1)
        if rects:
            if "mark" in drag:
                self.mark_changed.emit(drag["mark"], rects)
            elif self.mode == "text":
                self.text_selected.emit(rects)
            elif self.mode == "area":
                self.area_selected.emit(rects)
        self._paint_marks()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._drag = None
            self._paint_marks()
        elif event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selected_mark:
            self.mark_deleted.emit(self.selected_mark)
        else:
            super().keyPressEvent(event)

    def fit_page(self):
        self._fit = "page"
        self._apply_fit()

    def fit_width(self):
        self._fit = "width"
        self._apply_fit()

    def zoom(self, factor):
        if self.preview:
            self._fit = None
            current = self.transform().m11()
            self.scale(max(0.1, min(8, current * factor)) / current, max(0.1, min(8, current * factor)) / current)

    def _apply_fit(self):
        if not self.preview or not self._fit:
            return
        if self._fit == "page":
            self.fitInView(self.page_rect.adjusted(-12, -12, 12, 12), Qt.KeepAspectRatio)
        else:
            scale = max(0.1, (self.viewport().width() - 28) / self.page_rect.width())
            self.setTransform(QTransform.fromScale(scale, scale))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_fit()


__all__ = [
    "DragDropBoard",
    "PdfImageBoard",
    "PdfImageCard",
    "PdfPageBoard",
    "PdfPageCard",
    "PdfThumbnailCard",
    "PdfPageCanvas",
]
