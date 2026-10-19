"""Shared presentation pieces; no document-processing or persistence logic."""
from PySide6.QtCore import Qt, QSize, QPointF
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QScrollArea,
    QFrame, QSizePolicy,
)


def tool_icon(kind, color="#3C4942", size=24):
    """Small consistent line icons, painted locally without new dependencies."""
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 24, size / 24)
    pen = QPen(QColor(color), 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    if kind in ('excel', 'split', 'cleanup'):
        p.drawRoundedRect(3, 3, 18, 18, 2, 2)
        for y in (9, 15): p.drawLine(3, y, 21, y)
        p.drawLine(9, 3, 9, 21)
        if kind == 'split': p.drawLine(15, 3, 15, 21)
    elif kind == 'home':
        p.drawPolyline([QPointF(3, 11), QPointF(12, 3), QPointF(21, 11)])
        p.drawLine(5, 10, 5, 21); p.drawLine(19, 10, 19, 21)
        p.drawLine(5, 21, 19, 21); p.drawRect(10, 14, 4, 7)
    elif kind == 'settings':
        for y, x in ((6, 8), (12, 16), (18, 10)):
            p.drawLine(3, y, 21, y); p.drawEllipse(QPointF(x, y), 2, 2)
    elif kind == 'rename':
        p.drawPolyline([QPointF(3, 9), QPointF(10, 3), QPointF(21, 14), QPointF(14, 21), QPointF(3, 10)])
        p.drawEllipse(QPointF(8, 9), 1, 1)
    else:
        p.drawRoundedRect(5, 3, 14, 18, 2, 2)
        if kind == 'batch': p.drawLine(2, 7, 2, 23); p.drawLine(2, 23, 16, 23)
        for y in (9, 13, 17): p.drawLine(9, y, 15, y)
    p.end()
    return QIcon(pixmap)


class ToolEntry(QPushButton):
    def __init__(self, key, title, description, callback, parent=None):
        super().__init__(parent)
        self.setProperty('variant', 'toolEntry')
        self.setAccessibleName(title)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(104)
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 16, 20, 16); row.setSpacing(18)
        icon = QLabel(); icon.setPixmap(tool_icon(key, size=28).pixmap(QSize(28, 28)))
        row.addWidget(icon)
        text = QVBoxLayout(); text.setSpacing(5)
        name = QLabel(title); name.setProperty('homeRole', 'cardTitle')
        desc = QLabel(description); desc.setProperty('role', 'hint'); desc.setWordWrap(True)
        text.addWidget(name); text.addWidget(desc); row.addLayout(text, 1)
        arrow = QLabel('›'); arrow.setProperty('role', 'hint'); row.addWidget(arrow)
        for label in self.findChildren(QLabel):
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.clicked.connect(callback)


class Disclosure(QWidget):
    def __init__(self, title, content, expanded=False, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(8)
        self.toggle = QPushButton(); self.toggle.setCheckable(True)
        self.toggle.setProperty('variant', 'disclosure')
        self.content = content
        layout.addWidget(self.toggle); layout.addWidget(content)
        def update(checked):
            self.toggle.setText(('▾  ' if checked else '▸  ') + title)
            self.content.setVisible(checked)
        self.toggle.toggled.connect(update)
        self.toggle.setChecked(expanded); update(expanded)


def scroll_form(content, maximum_width=900):
    """Keep form controls at their natural height; scroll instead of crushing."""
    content.setMaximumWidth(maximum_width)
    content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    wrapper = QWidget(); row = QHBoxLayout(wrapper)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(content, 1, Qt.AlignTop); row.addStretch(0)
    scroll = QScrollArea(); scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame); scroll.setWidget(wrapper)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    return scroll


def contain_page_form(page, start_index=2, maximum_width=900):
    """Put an existing page's body into a scrollable form, retaining widgets/signals."""
    root = page.layout()
    body = QWidget(); layout = QVBoxLayout(body)
    layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(14)
    while root.count() > start_index:
        item = root.takeAt(start_index)
        if item.widget() is not None:
            layout.addWidget(item.widget(), 0, item.alignment())
        elif item.layout() is not None:
            child = item.layout()
            child.setParent(None)
            layout.addLayout(child)
        else:
            layout.addItem(item)
    layout.setSizeConstraint(QVBoxLayout.SetMinimumSize)
    root.addWidget(scroll_form(body, maximum_width), 1)
    return body
