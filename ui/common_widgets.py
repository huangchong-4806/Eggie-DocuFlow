from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QSpinBox, QStyle, QStyleOptionSpinBox


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


__all__ = ["ClearSpinBox", "SelectionComboBox"]
