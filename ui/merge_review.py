from itertools import zip_longest
from pathlib import Path

from openpyxl.utils import get_column_letter
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout, QHeaderView,
    QHBoxLayout, QLabel, QPlainTextEdit, QSizePolicy, QStackedWidget, QTableView,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ui.common_widgets import ClearSpinBox, SelectionComboBox


class PreviewModel(QAbstractTableModel):
    """Show any column without creating a widget item for every cell in a wide sheet."""

    def __init__(self, source, parent):
        super().__init__(parent)
        self.rows = source.preview
        self.width = source.full_width

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.width

    def data(self, index, role=Qt.DisplayRole):
        if index.isValid() and role in (Qt.DisplayRole, Qt.ToolTipRole):
            values = self.rows[index.row()][1]
            return values[index.column()] if index.column() < len(values) else ""
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                return get_column_letter(section + 1)
            return str(self.rows[section][0])
        return None


def preview_table(source):
    table = QTableView()
    table.setModel(PreviewModel(source, table))
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    for row, (number, _) in enumerate(source.preview):
        if number == source.header_row:
            table.selectRow(row)
            break
    return table


def plain_label(text):
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    return label


class MergeReviewDialog(QDialog):
    """Display exact differences and let the user choose a physical header row."""

    def __init__(self, source, reference, check, parent=None):
        super().__init__(parent)
        self.setWindowTitle("核对工作表和表头")
        self.setObjectName("mergeReviewDialog")
        self.resize(760, 560 if check and check.details else 500)
        self.setMinimumSize(620, 440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        # The header and controls keep their natural height. Only the preview
        # stretches, including when a different worksheet has not been read yet.
        header = QVBoxLayout()
        header.setSpacing(5)
        title_row = QHBoxLayout()
        title_row.setSpacing(16)
        filename = plain_label(Path(source.path).name)
        filename.setProperty("homeRole", "cardTitle")
        filename.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
        filename.setToolTip(source.path)
        title_row.addWidget(filename, 1)
        self.status = plain_label(check.summary if check else "待核对")
        self.status.setObjectName("mergeReviewStatus")
        self.status.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        title_row.addWidget(self.status, 0, Qt.AlignTop)
        header.addLayout(title_row)
        if reference and reference.path != source.path:
            reference_label = plain_label(
                f"对照：{Path(reference.path).name} · {reference.sheet_name} · 第 {reference.header_row} 行"
            )
            reference_label.setProperty("role", "hint")
            reference_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
            header.addWidget(reference_label)
        layout.addLayout(header)

        selectors = QGridLayout()
        selectors.setHorizontalSpacing(10)
        selectors.setVerticalSpacing(8)
        selectors.addWidget(QLabel("工作表"), 0, 0)
        self.sheet = SelectionComboBox()
        self.sheet.addItems(source.sheet_names)
        self.sheet.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.sheet.setMinimumContentsLength(12)
        self.sheet.setFixedWidth(240)
        self.sheet.setCurrentText(source.sheet_name)
        selectors.addWidget(self.sheet, 0, 1, Qt.AlignLeft)
        selectors.addWidget(QLabel("表头行"), 1, 0)
        self.header_row = ClearSpinBox()
        self.header_row.setAccessibleName("表头行")
        self.header_row.setRange(1, max(1, source.row_count))
        self.header_row.setValue(source.header_row)
        self.header_row.setFixedWidth(118)
        selectors.addWidget(self.header_row, 1, 1, Qt.AlignLeft)
        selectors.setColumnStretch(2, 1)
        layout.addLayout(selectors)

        self.preview_stack = QStackedWidget()
        self.preview_stack.setMinimumHeight(170)
        preview = QWidget()
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(8)
        if reference and reference.path != source.path:
            if check and not check.ok and not (reference.issues or source.issues):
                columns = [(get_column_letter(i), left or "（空）", right or "（空）")
                           for i, (left, right) in enumerate(
                               zip_longest(reference.headers, source.headers, fillvalue=""), 1
                           ) if left != right]
                if columns:
                    grid = QTableWidget(len(columns), 3)
                    grid.setHorizontalHeaderLabels(["列位置", "对照表字段", "这份文件的字段"])
                    grid.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
                    grid.verticalHeader().hide()
                    grid.setEditTriggers(QAbstractItemView.NoEditTriggers)
                    grid.setSelectionMode(QAbstractItemView.NoSelection)
                    grid.setFixedHeight(112)
                    grid.verticalHeader().setDefaultSectionSize(28)
                    for r, difference in enumerate(columns):
                        for c, text in enumerate(difference):
                            grid.setItem(r, c, QTableWidgetItem(text))
                    preview_layout.addWidget(grid)
        if check and check.details:
            details = QPlainTextEdit()
            details.setReadOnly(True)
            details.setPlainText("\n".join(check.details))
            details.setObjectName("mergeReviewDetails")
            details.setFixedHeight(74)
            preview_layout.addWidget(details)
        hint = plain_label("点击一行设为表头；宽表可横向滚动。")
        hint.setProperty("role", "hint")
        hint.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        preview_layout.addWidget(hint)
        table = preview_table(source)
        table.setObjectName("mergeReviewPreview")
        table.setAlternatingRowColors(True)
        table.verticalHeader().setDefaultSectionSize(28)
        table.setMinimumHeight(96)
        preview_layout.addWidget(table, 1)
        self.preview_stack.addWidget(preview)

        pending = QWidget()
        pending.setObjectName("mergeReviewPending")
        pending_layout = QVBoxLayout(pending)
        pending_layout.setContentsMargins(24, 24, 24, 24)
        pending_layout.setSpacing(8)
        pending_layout.addStretch()
        pending_title = plain_label("工作表已更改")
        pending_title.setProperty("homeRole", "cardTitle")
        pending_title.setAlignment(Qt.AlignCenter)
        pending_layout.addWidget(pending_title)
        tip = plain_label("点击“按此设置核对”读取新工作表，\n再打开此窗口查看预览和核对结果。")
        tip.setProperty("role", "hint")
        tip.setAlignment(Qt.AlignCenter)
        pending_layout.addWidget(tip)
        pending_layout.addStretch()
        self.preview_stack.addWidget(pending)
        layout.addWidget(self.preview_stack, 1)

        table.clicked.connect(lambda cell: self.header_row.setValue(source.preview[cell.row()][0]))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("按此设置核对")
        buttons.button(QDialogButtonBox.Ok).setProperty("variant", "primary")
        buttons.button(QDialogButtonBox.Cancel).setText("关闭")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        def show_status():
            changed = (self.sheet.currentText() != source.sheet_name
                       or self.header_row.value() != source.header_row)
            self.status.setText("待重新核对" if changed else check.summary if check else "待核对")
            self.status.setProperty("reviewState", "pending" if changed or not check
                                    else "ok" if check.ok else "error")
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)

        # Keep old results out of view while the newly selected sheet is pending.
        def change_sheet(name):
            changed = name != source.sheet_name
            self.preview_stack.setCurrentIndex(1 if changed else 0)
            self.header_row.setMaximum(1048576 if changed else max(1, source.row_count))
            self.header_row.setValue(1 if changed else source.header_row)
            self.sheet.setToolTip(name)
            show_status()

        self.sheet.setToolTip(source.sheet_name)
        show_status()
        self.sheet.currentTextChanged.connect(change_sheet)
        self.header_row.valueChanged.connect(show_status)


def skip_row_warnings(sources, skipped):
    warnings = []
    for source in sources[1:]:
        header = source.header_row
        first = skipped + 1
        if first <= header:
            detail = (f"从第 {first} 行追加，第 {first} 至 {header} 行（含表头）也会写入结果。"
                      if first < header else f"从第 {first} 行追加，表头行也会写入结果。")
        elif skipped > header and source.row_count > header:
            last = min(skipped, source.row_count)
            interval = f"第 {last} 行" if last == header + 1 else f"第 {header + 1} 至 {last} 行"
            detail = f"表头后的{interval}也会跳过。"
            if first > source.row_count:
                detail += "这份文件没有剩余行可追加。"
            else:
                detail += f"实际从第 {first} 行追加。"
        else:
            continue
        warnings.append(f"{Path(source.path).name} · {source.sheet_name}（表头第 {header} 行）\n{detail}")
    return warnings


class SkipRowReviewDialog(QDialog):
    def __init__(self, warnings, skip_rows, parent=None):
        super().__init__(parent)
        self.setWindowTitle("请核对追加数据的起始行")
        self.resize(620, 350)
        layout = QVBoxLayout(self)
        layout.addWidget(plain_label(
            f"已设置后续文件跳过开头 {skip_rows} 行。下列 {len(warnings)} 份文件的追加起点"
            "与表头位置不同，请确认这些行应当保留或跳过。"
        ))
        details = QPlainTextEdit()
        details.setReadOnly(True)
        details.setPlainText("\n\n".join(warnings))
        layout.addWidget(details, 1)
        buttons = QDialogButtonBox()
        back = buttons.addButton("返回设置", QDialogButtonBox.RejectRole)
        proceed = buttons.addButton("按当前起始行继续", QDialogButtonBox.AcceptRole)
        proceed.setAutoDefault(False)
        back.setDefault(True)
        back.setFocus()
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class HeaderlessReviewDialog(QDialog):
    def __init__(self, sources, skip_rows, parent=None):
        super().__init__(parent)
        self.setWindowTitle("确认按列位置合并")
        self.resize(900, 450)
        layout = QVBoxLayout(self)
        layout.addWidget(plain_label(
            "无表头模式按 A 对 A、B 对 B 追加数据。请对照下面的样例，确认每个位置的含义相同。"
            f"第一份保留全部行，后续文件从第 {skip_rows + 1} 行开始追加。"
        ))
        chooser = QComboBox()
        chooser.addItems([f"{i + 1}. {Path(s.path).name} · {s.sheet_name}" for i, s in enumerate(sources)])
        chooser.setCurrentIndex(min(1, len(sources) - 1))
        layout.addWidget(chooser)
        previews = QHBoxLayout()
        panels = []
        for title in ("第一份文件（对照）", "当前查看的文件"):
            panel = QVBoxLayout()
            panel.addWidget(plain_label(title))
            panels.append(panel)
            previews.addLayout(panel, 1)
        panels[0].addWidget(plain_label(f"{Path(sources[0].path).name} · {sources[0].sheet_name}"))
        panels[0].addWidget(preview_table(sources[0]))
        selected_title = plain_label("")
        panels[1].addWidget(selected_title)
        self.current_preview = None

        def show_preview(index):
            if self.current_preview:
                panels[1].removeWidget(self.current_preview)
                self.current_preview.deleteLater()
            source = sources[index]
            selected_title.setText(f"{Path(source.path).name} · {source.sheet_name}")
            self.current_preview = preview_table(source)
            panels[1].addWidget(self.current_preview)

        show_preview(chooser.currentIndex())
        chooser.currentIndexChanged.connect(show_preview)
        layout.addLayout(previews, 1)
        confirm = QCheckBox("我已核对列位置，按上述起始行合并")
        layout.addWidget(confirm)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        commit = buttons.button(QDialogButtonBox.Ok)
        commit.setText("按列位置合并")
        commit.setEnabled(False)
        buttons.button(QDialogButtonBox.Cancel).setText("返回")
        confirm.toggled.connect(commit.setEnabled)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
