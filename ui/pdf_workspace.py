"""One local, undoable PDF session shared by page and content editing."""

from collections import OrderedDict
from dataclasses import replace
import os
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QSize, QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSplitter, QStackedWidget,
    QTabBar, QTabWidget, QToolBar, QVBoxLayout, QWidget,
)

from pdf_workspace import (NumberOptions, PageScope, RedactionMark, WatermarkOptions,
                           WorkspaceState, marks_with_state, pending_count, resolve_pages)
from ui.pdf_widgets import PdfPageBoard, PdfPageCanvas, PdfPageCard
from ui.tasks import PdfWorkspaceProcess
from ui.common_widgets import ClearSpinBox, SelectionComboBox


class _WorkspaceEdit(QUndoCommand):
    def __init__(self, owner, state, label):
        super().__init__(label)
        self.owner, self.before, self.after = owner, owner.state, state

    def redo(self):
        self.owner._set_state(self.after)

    def undo(self):
        self.owner._set_state(self.before)


class PdfWorkspaceWidget(QWidget):
    close_ready = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = WorkspaceState()
        self.revision = 0
        self.current_page_id = None
        self._preview_revision = None
        self.source_names = {}
        self.source_paths = {}
        self._last_export_directory = None
        self.image_names = {}
        self.pdf_page_cards = []
        self._jobs = {}
        self._cache = OrderedDict()
        self._cache_bytes = 0
        self._busy = False
        self._cancel_requested = False
        self._cleanup_approved = False
        self._after_save = None
        self._mark_list_page = 0
        self._syncing = False
        self._closed = False
        self.worker = PdfWorkspaceProcess(self)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.progress.connect(self._progress)
        self.worker.discarded.connect(lambda request_id: self._jobs.pop(request_id, None))
        self.undo_stack = QUndoStack(self)
        self.undo_stack.cleanChanged.connect(self._refresh_controls)
        self.setAcceptDrops(True)
        self.setObjectName("pdfWorkspace")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(8)
        header = QHBoxLayout()
        self.open_button = self._button("打开 PDF", self.choose_open)
        self.add_button = self._button("插入 PDF", self.choose_add)
        self.clear_button = self._button("清空", self.clear_workspace)
        for button in (self.open_button, self.add_button, self.clear_button):
            header.addWidget(button)
        self.document_label = QLabel("本地处理 · 原文件始终保留")
        self.document_label.setTextFormat(Qt.PlainText)
        self.document_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.document_label.setProperty("role", "hint")
        header.addWidget(self.document_label, 1)
        self.export_button = self._button("另存 PDF", self.export_current, "primary")
        header.addWidget(self.export_button)
        self.document_header = QWidget(); self.document_header.setLayout(header)
        header_policy = self.document_header.sizePolicy()
        header_policy.setVerticalPolicy(QSizePolicy.Fixed)
        self.document_header.setSizePolicy(header_policy)
        header.setContentsMargins(0, 0, 0, 0)

        self.module_tabs = QTabWidget()
        self.module_tabs.addTab(self._create_pages(), "页面编辑")
        self.module_tabs.addTab(self._create_content(), "内容编辑")
        layout.addWidget(self.module_tabs, 1)
        footer = QHBoxLayout()
        self.status_label = QLabel("打开或拖入 PDF 开始；无需联网，不会自动识别扫描文字。")
        self.status_label.setWordWrap(True)
        self.status_label.setProperty("role", "status")
        footer.addWidget(self.status_label, 1)
        self.cancel_button = self._button("取消处理", self.cancel_operation)
        self.cancel_button.hide()
        footer.addWidget(self.cancel_button)
        self.license_button = self._button("开源说明", self.show_licenses)
        footer.addWidget(self.license_button)
        layout.addLayout(footer)
        self.undo_action = self.undo_stack.createUndoAction(self, "撤销")
        self.redo_action = self.undo_stack.createRedoAction(self, "重做")
        self.undo_action.setShortcuts(QKeySequence.Undo)
        self.redo_action.setShortcuts(QKeySequence.Redo)
        self.addActions([self.undo_action, self.redo_action])
        for toolbar in (self.page_toolbar, self.content_toolbar):
            toolbar.addSeparator()
            toolbar.addAction(self.undo_action)
            toolbar.addAction(self.redo_action)
        self.module_tabs.currentChanged.connect(lambda _: self.request_visible_previews())
        self.module_tabs.currentChanged.connect(self._place_document_header)
        self._place_document_header(self.module_tabs.currentIndex())
        self.tool_tabs.currentChanged.connect(self._tool_changed)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self.request_visible_previews)
        self.refresh_workspace()

    def _place_document_header(self, index):
        # The mode navigation stays above its actions. Reuse the same controls
        # so both editors continue to operate on the same PDF session.
        if index < 2:
            self.module_tabs.widget(index).layout().insertWidget(0, self.document_header)
            self.document_header.show()
        else:
            self.document_header.hide()

    @staticmethod
    def _button(text, callback, variant=None):
        button = QPushButton(text)
        button.setMinimumHeight(34)
        if variant:
            button.setProperty("variant", variant)
        button.clicked.connect(callback)
        return button

    def _action(self, toolbar, text, callback):
        action = QAction(text, self)
        action.triggered.connect(callback)
        toolbar.addAction(action)
        return action

    def _create_pages(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.page_toolbar = QToolBar()
        self.page_toolbar.setAccessibleName("页面编辑工具栏")
        self._page_actions = []
        for label, callback in (("全选", lambda: self.set_all_pdf_page_checks(True)),
                                ("取消全选", lambda: self.set_all_pdf_page_checks(False)),
                                ("前移", lambda: self.move_checked_pdf_pages(-1)),
                                ("后移", lambda: self.move_checked_pdf_pages(1)),
                                ("左转", lambda: self.rotate_selected_pdf_pages(-90)),
                                ("右转", lambda: self.rotate_selected_pdf_pages(90)),
                                ("转 180°", lambda: self.rotate_selected_pdf_pages(180)),
                                ("删除", self.delete_selected_pdf_pages),
                                ("提取", self.extract_selected)):
            self._page_actions.append(self._action(self.page_toolbar, label, callback))
        layout.addWidget(self.page_toolbar)
        row = QHBoxLayout()
        self.page_limit_label = QLabel("当前 0 / 1,000 页；完整页面预览，不裁切内容")
        self.page_limit_label.setWordWrap(True)
        row.addWidget(self.page_limit_label, 1)
        self.thumbnail_size_combo = SelectionComboBox()
        self.thumbnail_size_combo.addItems(["标准缩略图", "大缩略图"])
        self.thumbnail_size_combo.currentIndexChanged.connect(lambda _: self.refresh_workspace())
        row.addWidget(self.thumbnail_size_combo)
        layout.addLayout(row)
        self.empty_label = QLabel("打开或拖入 PDF，开始整理页面\n支持移动、旋转、提取和删除页面；保留原文件")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setProperty("role", "hint")
        layout.addWidget(self.empty_label, 1)
        self.pdf_page_scroll = QScrollArea()
        self.pdf_page_scroll.setWidgetResizable(True)
        self.pdf_page_board = PdfPageBoard(self)
        self.pdf_page_scroll.setWidget(self.pdf_page_board)
        self.pdf_page_scroll.verticalScrollBar().valueChanged.connect(lambda _: self._schedule_previews())
        layout.addWidget(self.pdf_page_scroll, 1)
        return page

    def _create_content(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.tool_tabs = QTabBar()
        for title in ("涂黑脱敏", "水印", "页码"):
            self.tool_tabs.addTab(title)
        self.tool_tabs.setExpanding(False)
        layout.addWidget(self.tool_tabs)
        self.content_toolbar = QToolBar()
        self.content_toolbar.setAccessibleName("选区与预览工具栏")
        self._mode_actions = []
        for label, mode in (("框选区域", "area"), ("选取文字", "text"), ("选择 / 移动", "select"), ("拖动页面", "hand")):
            action = self._action(self.content_toolbar, label, lambda checked=False, value=mode: self.set_selection_mode(value))
            action.setCheckable(True)
            self._mode_actions.append((action, mode))
        self.content_toolbar.addSeparator()
        for text, callback in (("−", lambda: self.canvas.zoom(0.8)), ("＋", lambda: self.canvas.zoom(1.25)),
                               ("整页", lambda: self.canvas.fit_page()), ("适合宽度", lambda: self.canvas.fit_width())):
            self._action(self.content_toolbar, text, callback)
        layout.addWidget(self.content_toolbar)
        splitter = QSplitter()
        self.page_list = QListWidget()
        self.page_list.setAccessibleName("页面缩略图导航")
        self.page_list.setViewMode(QListWidget.IconMode)
        self.page_list.setFlow(QListWidget.TopToBottom)
        self.page_list.setWrapping(False)
        self.page_list.setMovement(QListWidget.Static)
        self.page_list.setGridSize(QSize(104, 132))
        self.page_list.setIconSize(QSize(72, 100))
        self.page_list.setMinimumWidth(120)
        self.page_list.setMaximumWidth(160)
        self.page_list.currentRowChanged.connect(self._page_selected)
        self.page_list.verticalScrollBar().valueChanged.connect(lambda _: self._schedule_previews())
        splitter.addWidget(self.page_list)
        viewer = QWidget()
        viewer_layout = QVBoxLayout(viewer)
        viewer_layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = PdfPageCanvas()
        self.canvas.area_selected.connect(lambda rects: self.add_mark(rects, "area"))
        self.canvas.text_selected.connect(lambda rects: self.add_mark(rects, "text"))
        self.canvas.mark_changed.connect(self.change_mark)
        self.canvas.mark_deleted.connect(self.delete_mark)
        viewer_layout.addWidget(self.canvas, 1)
        navigation = QHBoxLayout()
        navigation.addStretch()
        navigation.addWidget(self._button("上一页", lambda: self.page_jump.setValue(self.page_jump.value() - 1)))
        self.page_jump = ClearSpinBox()
        self.page_jump.setRange(1, 1)
        self.page_jump.setPrefix("第 ")
        self.page_jump.setSuffix(" 页")
        self.page_jump.valueChanged.connect(lambda value: self.page_list.setCurrentRow(value - 1))
        navigation.addWidget(self.page_jump)
        navigation.addWidget(self._button("下一页", lambda: self.page_jump.setValue(self.page_jump.value() + 1)))
        navigation.addStretch()
        viewer_layout.addLayout(navigation)
        splitter.addWidget(viewer)
        inspector_scroll = QScrollArea()
        inspector_scroll.setWidgetResizable(True)
        inspector_scroll.setMinimumWidth(250)
        inspector_scroll.setMaximumWidth(320)
        self.inspector = QStackedWidget()
        self.inspector.addWidget(self._create_redaction_settings())
        self.inspector.addWidget(self._create_watermark_settings())
        self.inspector.addWidget(self._create_number_settings())
        inspector_scroll.setWidget(self.inspector)
        splitter.addWidget(inspector_scroll)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([110, 620, 270])
        layout.addWidget(splitter, 1)
        self.set_selection_mode("area")
        return page

    def _create_redaction_settings(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        hint = QLabel("框选区域或直接选取文字。\n应用后可继续新增；关闭前可返回修改。\n导出后，被涂黑的原内容无法恢复，请保留原件。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.mark_count_label = QLabel()
        layout.addWidget(self.mark_count_label)
        self.mark_list = QListWidget()
        self.mark_list.setAccessibleName("涂黑标记列表，每页显示 50 条")
        self.mark_list.setMinimumHeight(160)
        self.mark_list.currentItemChanged.connect(self._mark_selected)
        layout.addWidget(self.mark_list, 1)
        row = QHBoxLayout()
        row.addWidget(self._button("前 50 条", lambda: self._move_mark_list(-1)))
        row.addWidget(self._button("后 50 条", lambda: self._move_mark_list(1)))
        layout.addLayout(row)
        self.delete_mark_button = self._button("删除选中标记", lambda: self.delete_mark(self.canvas.selected_mark))
        layout.addWidget(self.delete_mark_button)
        self.apply_button = self._button("应用新增标记", self.apply_pending, "primary")
        self.return_button = self._button("返回修改已应用标记", self.return_to_editing)
        layout.addWidget(self.apply_button)
        layout.addWidget(self.return_button)
        return panel

    @staticmethod
    def _combo(choices):
        combo = SelectionComboBox()
        for label, value in choices:
            combo.addItem(label, value)
        return combo

    @staticmethod
    def _spin(minimum, maximum, value, suffix=""):
        spin = ClearSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setSuffix(suffix)
        return spin

    def _scope_fields(self, layout, prefix):
        ranges = QLineEdit()
        ranges.setPlaceholderText("留空为全部，如 1-3,5")
        skip = QCheckBox("跳过当前首页")
        layout.addRow("页面范围", ranges)
        layout.addRow(skip)
        setattr(self, prefix + "_ranges", ranges)
        setattr(self, prefix + "_skip", skip)
        label = QLabel()
        label.setWordWrap(True)
        layout.addRow(label)
        setattr(self, prefix + "_scope_label", label)
        ranges.textEdited.connect(self._settings_changed)
        ranges.editingFinished.connect(self._settings_changed)
        skip.toggled.connect(self._settings_changed)

    def _create_watermark_settings(self):
        panel = QWidget()
        form = QFormLayout(panel)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setVerticalSpacing(10)
        self.watermark_form = form
        self.watermark_kind = self._combo([("不添加", "none"), ("文字水印", "text"), ("图片水印", "image")])
        self.watermark_text = QLineEdit("内部资料")
        self.watermark_image_button = self._button("选择 PNG / JPG", self.choose_watermark_image)
        self.watermark_image_label = QLabel("尚未选择图片")
        self.watermark_image_label.setWordWrap(True)
        self.watermark_direction = self._combo([("倾斜", -32), ("水平", 0)])
        self.watermark_layout = self._combo([("单个居中", False), ("整页平铺", True)])
        self.watermark_size = self._spin(40, 170, 100, "%")
        self.watermark_opacity = self._spin(5, 80, 18, "%")
        self.watermark_spacing = self._spin(70, 180, 120)
        for label, widget in (("类型", self.watermark_kind), ("文字", self.watermark_text),
                               ("图片", self.watermark_image_button), ("", self.watermark_image_label),
                               ("方向", self.watermark_direction), ("布局", self.watermark_layout),
                               ("大小", self.watermark_size), ("透明度", self.watermark_opacity), ("平铺间距", self.watermark_spacing)):
            form.addRow(label, widget)
        self._scope_fields(form, "watermark")
        hint = QLabel("设置即时预览；提取页面时，范围按提取结果重新计算。")
        hint.setWordWrap(True)
        form.addRow(hint)
        self.watermark_text.textEdited.connect(self._settings_changed)
        self.watermark_text.editingFinished.connect(self._settings_changed)
        for combo in (self.watermark_kind, self.watermark_direction, self.watermark_layout):
            combo.currentIndexChanged.connect(self._settings_changed)
        for spin in (self.watermark_size, self.watermark_opacity, self.watermark_spacing):
            spin.valueChanged.connect(self._settings_changed)
        self.watermark_kind.currentIndexChanged.connect(self._update_watermark_fields)
        self.watermark_layout.currentIndexChanged.connect(self._update_watermark_fields)
        self._update_watermark_fields()
        return panel

    def _update_watermark_fields(self, *_):
        kind = self.watermark_kind.currentData()
        self.watermark_form.setRowVisible(self.watermark_text, kind == "text")
        self.watermark_form.setRowVisible(self.watermark_image_button, kind == "image")
        self.watermark_form.setRowVisible(self.watermark_image_label, kind == "image")
        for widget in (self.watermark_direction, self.watermark_layout, self.watermark_size,
                       self.watermark_opacity, self.watermark_ranges, self.watermark_skip,
                       self.watermark_scope_label):
            self.watermark_form.setRowVisible(widget, kind != "none")
        self.watermark_form.setRowVisible(self.watermark_spacing,
                                         kind != "none" and self.watermark_layout.currentData())

    def _create_number_settings(self):
        panel = QWidget()
        form = QFormLayout(panel)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setVerticalSpacing(10)
        self.number_enabled = QCheckBox("添加页码")
        self.number_style = self._combo([("1", "plain"), ("— 1 —", "dash"), ("第 1 页", "chinese"),
                                         ("1 / 4", "fraction"), ("第 1 页，共 4 页", "chinese_total")])
        self.number_start = self._spin(0, 999999, 1)
        self.number_position = self._combo([(label, key) for label, key in (
            ("底部居中", "bottom_center"), ("底部左侧", "bottom_left"), ("底部右侧", "bottom_right"),
            ("顶部居中", "top_center"), ("顶部左侧", "top_left"), ("顶部右侧", "top_right"))])
        form.addRow(self.number_enabled)
        form.addRow("样式", self.number_style)
        form.addRow("起始数字", self.number_start)
        form.addRow("位置", self.number_position)
        self._scope_fields(form, "number")
        hint = QLabel("跳过的页面不占用数字序号；总页数始终等于实际输出页数。")
        hint.setWordWrap(True)
        form.addRow(hint)
        self.number_enabled.toggled.connect(self._settings_changed)
        self.number_style.currentIndexChanged.connect(self._settings_changed)
        self.number_start.valueChanged.connect(self._settings_changed)
        self.number_position.currentIndexChanged.connect(self._settings_changed)
        return panel

    def _settings_changed(self, *_):
        if self._syncing or self._busy:
            return
        watermark = WatermarkOptions(self.watermark_kind.currentData(), self.watermark_text.text(),
            self.state.watermark.image_id, self.watermark_direction.currentData(), self.watermark_layout.currentData(),
            self.watermark_size.value(), self.watermark_opacity.value() / 100, self.watermark_spacing.value(),
            PageScope(self.watermark_ranges.text(), self.watermark_skip.isChecked()))
        numbers = NumberOptions(self.number_enabled.isChecked(), self.number_style.currentData(), self.number_start.value(),
            self.number_position.currentData(), PageScope(self.number_ranges.text(), self.number_skip.isChecked()))
        self._record(replace(self.state, watermark=watermark, numbers=numbers), "调整水印或页码")

    def _sync_settings(self):
        self._syncing = True
        watermark, numbers = self.state.watermark, self.state.numbers
        for combo, value in ((self.watermark_kind, watermark.kind), (self.watermark_direction, watermark.angle),
                              (self.watermark_layout, watermark.tiled), (self.number_style, numbers.style),
                              (self.number_position, numbers.position)):
            combo.setCurrentIndex(combo.findData(value))
        for edit, value in ((self.watermark_text, watermark.text),
                            (self.watermark_ranges, watermark.scope.ranges),
                            (self.number_ranges, numbers.scope.ranges)):
            if edit.text() != value:
                edit.setText(value)
        self.watermark_image_label.setText(self.image_names.get(watermark.image_id, "尚未选择图片"))
        self.watermark_size.setValue(int(watermark.size))
        self.watermark_opacity.setValue(round(watermark.opacity * 100))
        self.watermark_spacing.setValue(int(watermark.spacing))
        self.watermark_skip.setChecked(watermark.scope.skip_first)
        self.number_enabled.setChecked(numbers.enabled)
        self.number_start.setValue(numbers.start)
        self.number_skip.setChecked(numbers.scope.skip_first)
        self.watermark_scope_label.setText(self._scope_summary(self.state, "watermark"))
        self.number_scope_label.setText(self._scope_summary(self.state, "numbers"))
        self._syncing = False

    @staticmethod
    def _scope_summary(state, field):
        options = getattr(state, field)
        name = "水印" if field == "watermark" else "页码"
        enabled = options.kind != "none" if field == "watermark" else options.enabled
        if not enabled:
            return name + "：未启用"
        try:
            count = len(resolve_pages(options.scope, len(state.pages)))
            return f"{name}实际作用：{count} / {len(state.pages)} 页"
        except ValueError:
            return name + "范围无效，请调整后再导出。"

    def _record(self, state, label):
        if state != self.state and not self._busy:
            self.undo_stack.push(_WorkspaceEdit(self, state, label))

    def _set_state(self, state):
        same_render = (self.state.pages == state.pages and self.state.watermark == state.watermark
                       and self.state.numbers == state.numbers
                       and [mark for mark in self.state.marks if mark.applied] == [mark for mark in state.marks if mark.applied])
        self.state = state
        previous_revision = self.revision
        self.revision += 1
        if same_render:
            if self._preview_revision == previous_revision:
                self._preview_revision = self.revision
            self._cache = OrderedDict(((self.revision, key[1], key[2]), value) for key, value in self._cache.items())
            self._refresh_marks()
            self._refresh_controls()
            if not self.canvas.preview:
                self._schedule_previews()
            return
        self._cache.clear()
        self._cache_bytes = 0
        self._preview_revision = None
        self.canvas.setEnabled(False)
        self.refresh_workspace()

    def refresh_workspace(self):
        self.empty_label.setVisible(not self.state.pages)
        self.pdf_page_scroll.setVisible(bool(self.state.pages))
        checked = {card.data["page_id"] for card in self.pdf_page_cards if card.is_checked()}
        for card in self.pdf_page_cards:
            card.setParent(None)
            card.deleteLater()
        self.pdf_page_cards = []
        self._syncing = True
        self.page_list.clear()
        large = self.thumbnail_size_combo.currentIndex() == 1
        for index, ref in enumerate(self.state.pages):
            card = PdfPageCard(self, {"page_id": ref.page_id, "source_file": self.source_names.get(ref.source_id, "PDF"),
                                      "page_index": ref.source_index, "rotation": 0})
            if large:
                card.setFixedSize(246, 360)
                card.thumbnail_box.setFixedSize(222, 276)
            card.update_display(index + 1)
            card.set_checked(ref.page_id in checked)
            self.pdf_page_cards.append(card)
            item = QListWidgetItem(f"第 {index + 1} 页")
            item.setSizeHint(QSize(104, 132))
            item.setTextAlignment(Qt.AlignHCenter)
            self.page_list.addItem(item)
        ids = [ref.page_id for ref in self.state.pages]
        if self.current_page_id not in ids:
            self.current_page_id = ids[0] if ids else None
        self.page_jump.setMaximum(max(1, len(ids)))
        if self.current_page_id:
            index = ids.index(self.current_page_id)
            self.page_list.setCurrentRow(index)
            self.page_jump.setValue(index + 1)
        else:
            self.canvas.set_page(None)
        self._syncing = False
        self._sync_settings()
        self.refresh_pdf_page_cards_layout()
        self._refresh_marks()
        self._refresh_controls()
        self._schedule_previews()

    def refresh_pdf_page_cards_layout(self):
        if not hasattr(self, "pdf_page_scroll"):
            return
        grid = self.pdf_page_board.grid
        while grid.count():
            grid.takeAt(0)
        width = 246 if self.thumbnail_size_combo.currentIndex() else 176
        columns = max(1, (self.pdf_page_scroll.viewport().width() - 16) // (width + 18))
        for i, card in enumerate(self.pdf_page_cards):
            grid.addWidget(card, i // columns, i % columns)
        self._schedule_previews()

    def refresh_pdf_page_numbers(self):
        if hasattr(self, "status_label"):
            self._refresh_controls()

    def _refresh_controls(self, *_):
        if self._closed or not hasattr(self, "status_label"):
            return
        count, pending = len(self.state.pages), pending_count(self.state)
        self.page_limit_label.setText(f"当前 {count} / 1,000 页；已选 {len(self.selected_page_ids())} 页 · 双击查看完整页面")
        names = list(dict.fromkeys(self.source_names.get(ref.source_id, "PDF") for ref in self.state.pages))
        title = (names[0][:27] + ("…" if len(names[0]) > 27 else "")) if names else "未打开文档"
        if len(names) > 1:
            title += f" 等 {len(names)} 个来源"
        self.document_label.setText(f"{title} · {count} 页 · {'有未保存修改' if self.has_unsaved_changes() else '保留原件'}")
        self.document_label.setToolTip("\n".join(names))
        for button in (self.open_button, self.add_button):
            button.setEnabled(not self._busy)
        self.clear_button.setEnabled(not self._busy and bool(count))
        self.export_button.setEnabled(not self._busy and bool(count) and not pending)
        self.apply_button.setEnabled(not self._busy and bool(pending))
        self.apply_button.setText(f"应用新增标记（{pending}）")
        self.return_button.setEnabled(not self._busy and any(mark.applied for mark in self.state.marks))
        self.delete_mark_button.setEnabled(not self._busy and bool(self.state.marks))
        self.inspector.setEnabled(not self._busy)
        self.page_toolbar.setEnabled(not self._busy and bool(count))
        self.pdf_page_board.setEnabled(not self._busy)
        if hasattr(self, "undo_action"):
            self.undo_action.setEnabled(not self._busy and self.undo_stack.canUndo())
            self.redo_action.setEnabled(not self._busy and self.undo_stack.canRedo())

    def selected_page_ids(self):
        return {card.data["page_id"] for card in self.pdf_page_cards if card.is_checked()}

    def set_all_pdf_page_checks(self, checked):
        for card in self.pdf_page_cards:
            card.set_checked(checked)

    def rotate_selected_pdf_pages(self, degrees):
        selected = self.selected_page_ids()
        self._record(replace(self.state, pages=[replace(ref, rotation=(ref.rotation + degrees) % 360)
            if ref.page_id in selected else ref for ref in self.state.pages]), "旋转页面")

    def reorder_pdf_page(self, source_index, target_index):
        pages = self.state.pages
        if not 0 <= source_index < len(pages) or not 0 <= target_index <= len(pages):
            return
        selected = self.selected_page_ids()
        if pages[source_index].page_id not in selected:
            selected = {pages[source_index].page_id}
        moving = [ref for ref in pages if ref.page_id in selected]
        target = sum(ref.page_id not in selected for ref in pages[:target_index])
        remaining = [ref for ref in pages if ref.page_id not in selected]
        self._record(replace(self.state, pages=remaining[:target] + moving + remaining[target:]), "调整页面顺序")

    def move_checked_pdf_pages(self, direction):
        selected, pages = self.selected_page_ids(), list(self.state.pages)
        indices = range(1, len(pages)) if direction < 0 else range(len(pages) - 2, -1, -1)
        for index in indices:
            other = index + direction
            if pages[index].page_id in selected and pages[other].page_id not in selected:
                pages[index], pages[other] = pages[other], pages[index]
        self._record(replace(self.state, pages=pages), "移动页面")

    def delete_selected_pdf_pages(self):
        selected = self.selected_page_ids()
        self._record(replace(self.state, pages=[ref for ref in self.state.pages if ref.page_id not in selected],
                             marks=[mark for mark in self.state.marks if mark.page_id not in selected]), "删除页面")

    def preview_pdf_page(self, card):
        self.current_page_id = card.data["page_id"]
        self.module_tabs.setCurrentIndex(1)
        self.page_list.setCurrentRow(next(i for i, ref in enumerate(self.state.pages) if ref.page_id == self.current_page_id))
        self.request_visible_previews()

    def _page_selected(self, index):
        if self._syncing or not 0 <= index < len(self.state.pages):
            return
        self.current_page_id = self.state.pages[index].page_id
        self.page_jump.setValue(index + 1)
        self.canvas.setEnabled(False)
        self._schedule_previews()

    def set_selection_mode(self, mode):
        self.canvas.set_mode(mode)
        for action, value in self._mode_actions:
            action.setChecked(value == mode)
        if mode == "text" and self.canvas.preview and not self.canvas.preview["chars"] and hasattr(self, "status_label"):
            self.status_label.setText("此页没有可选文字，请使用框选区域；不会自动识别扫描文字。")

    def _tool_changed(self, index):
        self.inspector.setCurrentIndex(index)
        self.set_selection_mode("area" if index == 0 else "hand")
        for action, _ in self._mode_actions:
            action.setEnabled(index == 0)

    def add_mark(self, rects, mode):
        if self._valid_preview() and not self._busy:
            mark = RedactionMark(uuid4().hex, self.current_page_id, tuple(rects), mode)
            self._record(replace(self.state, marks=self.state.marks + [mark]), "新增涂黑标记")

    def change_mark(self, mark_id, rects):
        if not self._valid_preview() or self._busy:
            return
        self._record(replace(self.state, marks=[replace(mark, rects=tuple(rects)) if mark.mark_id == mark_id
            and not mark.applied and mark.mode == "area" else mark for mark in self.state.marks]), "移动或调整涂黑区域")

    def delete_mark(self, mark_id):
        mark = next((mark for mark in self.state.marks if mark.mark_id == mark_id), None)
        if mark and mark.applied:
            self.show_error("请先返回修改，再删除已应用的标记。")
        elif mark:
            self._record(replace(self.state, marks=[item for item in self.state.marks if item.mark_id != mark_id]), "删除涂黑标记")

    def _refresh_marks(self):
        self.canvas.set_marks(self.state.marks)
        self.mark_count_label.setText(f"共 {len(self.state.marks)} 条 · 待应用 {pending_count(self.state)} 条")
        self.mark_list.blockSignals(True)
        self.mark_list.clear()
        self._mark_list_page = min(self._mark_list_page, max(0, (len(self.state.marks) - 1) // 50))
        numbers = {ref.page_id: i + 1 for i, ref in enumerate(self.state.pages)}
        start = self._mark_list_page * 50
        for index, mark in enumerate(self.state.marks[start:start + 50], start + 1):
            item = QListWidgetItem(f"{index}. 第 {numbers.get(mark.page_id, '?')} 页 · {'文字' if mark.mode == 'text' else '区域'} · {'已应用' if mark.applied else '待应用'}")
            item.setData(Qt.UserRole, mark.mark_id)
            self.mark_list.addItem(item)
        self.mark_list.blockSignals(False)

    def _move_mark_list(self, direction):
        self._mark_list_page = max(0, self._mark_list_page + direction)
        self._refresh_marks()

    def _mark_selected(self, item, previous):
        if not item:
            return
        mark = next(mark for mark in self.state.marks if mark.mark_id == item.data(Qt.UserRole))
        self.canvas.selected_mark = mark.mark_id
        self.set_selection_mode("select")
        self.page_list.setCurrentRow(next(i for i, ref in enumerate(self.state.pages) if ref.page_id == mark.page_id))
        self.canvas.set_marks(self.state.marks)

    def apply_pending(self):
        if pending_count(self.state) and not self._busy:
            self._set_busy(True, "检查文档结构与待应用区域…")
            self._submit("inspect", {"state": self.state}, ("inspect", "apply"))

    def return_to_editing(self):
        self._record(replace(self.state, marks=marks_with_state(self.state.marks, False)), "返回修改涂黑")

    def _set_busy(self, busy, message=""):
        self._busy = busy
        if busy:
            self._cancel_requested = False
        self.cancel_button.setVisible(busy)
        self.canvas.setEnabled(not busy and self._valid_preview())
        if message:
            self.status_label.setText(message)
        self._refresh_controls()
        if not busy:
            self._schedule_previews()

    def _valid_preview(self):
        return bool(self.canvas.preview and self.canvas.preview["page_id"] == self.current_page_id
                    and self._preview_revision == self.revision)

    def _submit(self, operation, payload, context):
        request_id = self.worker.submit(operation, payload, self.revision)
        self._jobs[request_id] = (operation, context)
        return request_id

    def _release_resources(self, source_ids=(), image_ids=()):
        source_ids, image_ids = tuple(set(source_ids)), tuple(set(image_ids))
        for key in source_ids:
            self.source_names.pop(key, None)
            self.source_paths.pop(key, None)
        for key in image_ids:
            self.image_names.pop(key, None)
        if source_ids or image_ids:
            self._submit("release", {"source_ids": source_ids, "image_ids": image_ids}, None)

    def _schedule_previews(self):
        if hasattr(self, "_preview_timer") and not self._closed:
            self._preview_timer.start()

    def request_visible_previews(self):
        if not self.state.pages or self._busy or self._closed or not self.isVisible() or self.module_tabs.currentIndex() not in (0, 1):
            return
        requests = []
        if self.module_tabs.currentIndex() == 1 and self.current_page_id:
            requests.append((self.current_page_id, 1600))
            viewport = self.page_list.viewport().rect()
            for i, ref in enumerate(self.state.pages):
                if self.page_list.visualItemRect(self.page_list.item(i)).intersects(viewport):
                    requests.append((ref.page_id, 360))
        else:
            viewport = self.pdf_page_scroll.viewport().rect()
            size = 700 if self.thumbnail_size_combo.currentIndex() else 480
            for card in self.pdf_page_cards:
                rect = card.rect().translated(card.mapTo(self.pdf_page_scroll.viewport(), card.rect().topLeft()))
                if rect.intersects(viewport):
                    requests.append((card.data["page_id"], size))
        for page_id, size in requests:
            key = (self.revision, page_id, size)
            if key in self._cache:
                preview, cost = self._cache[key]
                self._cache.move_to_end(key)
                self._display_preview(preview, size)
            elif not any(operation == "render" and context == key for operation, context in self._jobs.values()):
                self._submit("render", {"state": self.state, "page_id": page_id, "max_pixels": size}, key)

    def _display_preview(self, preview, size):
        if size == 1600:
            if preview["page_id"] == self.current_page_id:
                self.canvas.set_page(preview)
                self._preview_revision = self.revision
                self.canvas.set_marks(self.state.marks)
                self.canvas.setEnabled(not self._busy)
                self.status_label.setText("页面预览已更新 · 原文件未修改")
                if self.canvas.mode == "text" and not preview["chars"]:
                    self.status_label.setText("此页没有可选文字，请使用框选区域；不会自动识别扫描文字。")
            return
        pixmap = QPixmap()
        pixmap.loadFromData(preview["png"], "PNG")
        for index, card in enumerate(self.pdf_page_cards):
            if card.data["page_id"] != preview["page_id"]:
                continue
            available = card.thumbnail_box.size() - QSize(16, 16)
            card.image_label.setPixmap(pixmap.scaled(available, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.page_list.item(index).setIcon(QIcon(pixmap.scaled(72, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            break

    def _completed(self, request_id, revision, result):
        job = self._jobs.pop(request_id, None)
        if not job:
            return
        operation, context = job
        if operation == "release":
            return
        if operation not in ("render", "export") and self._cancel_requested:
            if operation == "open":
                self._release_resources(ref.source_id for ref in context[1] + list(result))
            elif operation == "image":
                self._release_resources(image_ids=(result,))
            self._cancel_requested = False
            self._set_busy(False, "已取消操作，当前编辑状态未改变。")
            return
        if operation == "render":
            if revision != self.revision:
                return
            if context[0] == "extract_preview":
                dialog, canvas, button = context[1:]
                if dialog.isVisible() and canvas.property("requestedPage") == result["page_id"]:
                    canvas.set_page(result)
                    button.setEnabled(True)
                return
            size = context[2]
            cost = len(result["png"]) + size * size * 4 + len(result["chars"]) * 200
            self._cache[context] = (result, cost)
            self._cache_bytes += cost
            while self._cache_bytes > 48 * 1024 * 1024 and len(self._cache) > 1:
                key, (_, removed) = self._cache.popitem(last=False)
                self._cache_bytes -= removed
                for i, card in enumerate(self.pdf_page_cards):
                    if card.data["page_id"] == key[1] and key[2] != 1600:
                        card.image_label.clear()
                        self.page_list.item(i).setIcon(QIcon())
            self._display_preview(result, size)
        elif operation == "open":
            paths, imported, replace_current = context
            imported.extend(result)
            if len(imported) + (0 if replace_current else len(self.state.pages)) > 1000:
                self._release_resources(ref.source_id for ref in imported)
                self._set_busy(False)
                self.show_error("单次最多 1,000 页，本次没有添加。请先拆分文件。")
                return
            for ref in result:
                self.source_names[ref.source_id] = Path(paths[0]).name
                self.source_paths[ref.source_id] = str(Path(paths[0]).expanduser().resolve())
            if len(paths) > 1:
                self._submit("open", {"path": paths[1]}, (paths[1:], imported, replace_current))
            else:
                self._set_busy(False)
                self._cleanup_approved = False
                if replace_current or not self.state.pages:
                    old_sources = set(self.source_names) | {ref.source_id for ref in self.state.pages}
                    self._release_resources(old_sources - {ref.source_id for ref in imported}, tuple(self.image_names))
                    self.undo_stack.clear()
                    self._set_state(WorkspaceState(pages=imported))
                    self.undo_stack.setClean()
                else:
                    self._record(replace(self.state, pages=self.state.pages + imported), "插入 PDF 页面")
                self._set_busy(True, "正在检查签名与附加内容…")
                self._submit("inspect", {"state": self.state}, "opened")
        elif operation == "inspect":
            self._set_busy(False)
            if context == "opened":
                self.status_label.setText(f"已载入 {len(self.state.pages)} 页，原文件未修改。")
                if result["signatures"]:
                    QMessageBox.information(self, "数字签名提醒", "此文档包含签名字段。编辑并另存会影响已有签名的有效性。\n请保留原件；本工具不验证或重新签署文件。")
                return
            if result["blocking_reasons"]:
                self.show_error("\n".join(result["blocking_reasons"]))
                return
            details = "应用后仍可新增标记，也可在本次会话中返回修改。导出后，被涂黑的原内容无法恢复。"
            if any(result[key] for key in ("attachments", "annotations", "forms", "signatures")):
                details += (f"\n\n检测到附件 {result['attachments']} 个、批注 {result['annotations']} 个、表单 {result['forms']} 项。"
                            "\n将清除附件、批注备注、表单值和原文元数据；保留可见外观。数字签名将失效。")
            if QMessageBox.question(self, "确认应用涂黑", details, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
            self._cleanup_approved = True
            self._set_busy(True, "正在验证并应用涂黑…")
            self._submit("apply", {"state": self.state, "allow_cleanup": True}, ("apply",))
        elif operation == "apply":
            self._set_busy(False)
            if revision == self.revision:
                self._record(replace(self.state, marks=marks_with_state(self.state.marks, True)), "应用涂黑")
                self.status_label.setText("已应用，可继续新增标记；导出前可返回修改。")
                self.request_visible_previews()
        elif operation == "image":
            self._set_busy(False)
            self.image_names[result] = Path(context).name
            self._record(replace(self.state, watermark=replace(self.state.watermark, image_id=result, kind="image")), "选择图片水印")
        elif operation == "export":
            self._set_busy(False)
            self._last_export_directory = str(Path(result.output_file).expanduser().resolve().parent)
            if not context and revision == self.revision:
                self.undo_stack.setClean()
            self.status_label.setText(f"已保存：{result.output_file}" + ("；附加处理有提醒，请查看详情" if result.failures else ""))
            message = f"已保存并重新读取核验：\n{result.output_file}\n\n原文件未修改。"
            if result.failures:
                message += "\n" + "\n".join(result.failures)
            QMessageBox.information(self, "PDF 保存完成", message)
            if self._after_save and not context:
                action, self._after_save = self._after_save, None
                action()

    def _progress(self, request_id, revision, message):
        if request_id in self._jobs and revision == self.revision and not self._cancel_requested:
            self.status_label.setText(message)

    def _failed(self, request_id, revision, message):
        job = self._jobs.pop(request_id, None)
        if not job:
            return
        operation, context = job
        if operation == "release":
            self.status_label.setText("旧文档资源未能释放，请清空工作区后重试。")
            return
        if operation == "render":
            if revision == self.revision:
                self.status_label.setText("预览未更新：" + message)
                if context[0] != "extract_preview" and context[1] == self.current_page_id:
                    self.canvas.setEnabled(False)
            return
        if operation == "open":
            self._release_resources(ref.source_id for ref in context[1])
        self._after_save = None
        self._set_busy(False)
        if self._cancel_requested and message.startswith("已取消"):
            self._cancel_requested = False
            self.status_label.setText(message)
            return
        self.show_error(message)

    def cancel_operation(self):
        self._cancel_requested = True
        self.status_label.setText("已请求取消，正在完成当前安全检查；请稍候。")
        self.worker.cancel()

    def show_error(self, message):
        self.status_label.setText(message)
        QMessageBox.warning(self, "PDF 工作区", message)

    def choose_open(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "打开 PDF", "", "PDF 文件 (*.pdf)")
        if paths:
            self._maybe_discard(lambda: self.open_paths(tuple(paths), replace_current=True))

    def choose_add(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "插入 PDF 页面", "", "PDF 文件 (*.pdf)")
        if paths:
            self.open_paths(tuple(paths))

    def open_paths(self, paths, replace_current=False):
        if paths and not self._busy:
            self._set_busy(True, "正在读取 PDF，现有文档会保留到读取成功…")
            self._submit("open", {"path": str(paths[0])}, (tuple(paths), [], replace_current))

    def choose_watermark_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择本地图片水印", "", "图片 (*.png *.jpg *.jpeg)")
        if path:
            self._set_busy(True, "正在读取图片水印…")
            self._submit("image", {"path": path}, path)

    def _export_allowed(self):
        return self.can_export() and bool(self.state.pages)

    def can_export(self):
        if self._busy:
            self.show_error("当前 PDF 正在处理，请等待或取消后再导出。")
            return False
        if pending_count(self.state):
            self.module_tabs.setCurrentIndex(1)
            self.tool_tabs.setCurrentIndex(0)
            self.show_error(f"还有 {pending_count(self.state)} 条待应用的涂黑标记，请先应用或删除后再导出。")
            return False
        return True

    def export_current(self):
        if self._export_allowed():
            self._save_state(self.state, False)
        else:
            self._after_save = None

    def _save_state(self, state, partial):
        if not self._export_allowed():
            self._after_save = None
            return
        try:
            default_path = self._default_export_path(state, partial)
        except ValueError as error:
            self._after_save = None
            self.show_error(str(error))
            return
        path, _ = QFileDialog.getSaveFileName(self, "另存 PDF 副本", str(default_path), "PDF 文件 (*.pdf)")
        if not path:
            self._after_save = None
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self._set_busy(True, "正在生成并核验 PDF…")
        self._submit("export", {"state": state, "output_file": path, "allow_cleanup": self._cleanup_approved}, partial)

    def _default_export_path(self, state, partial):
        candidates = [self._last_export_directory]
        pages = sorted(state.pages, key=lambda page: page.page_id != self.current_page_id)
        candidates.extend(Path(self.source_paths[page.source_id]).parent
                          for page in pages if page.source_id in self.source_paths)
        candidates.extend((QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation), Path.home()))
        for candidate in candidates:
            if not candidate:
                continue
            try:
                directory = Path(candidate).expanduser().resolve()
                if directory.is_dir() and os.access(directory, os.W_OK | os.X_OK):
                    return directory / ("提取结果.pdf" if partial else "PDF编辑结果.pdf")
            except (OSError, RuntimeError):
                continue
        raise ValueError("找不到可写的保存目录，请检查文稿文件夹或源文件所在目录的权限。")

    def extract_selected(self):
        if not self._export_allowed():
            return
        selected = self.selected_page_ids()
        if not selected:
            self.show_error("请先勾选需要提取的页面。")
            return
        state = replace(self.state, pages=[ref for ref in self.state.pages if ref.page_id in selected],
                        marks=[mark for mark in self.state.marks if mark.page_id in selected])
        dialog = QDialog(self)
        dialog.setWindowTitle(f"提取预览 · 共 {len(state.pages)} 页")
        dialog.resize(800, 720)
        layout = QVBoxLayout(dialog)
        hint = QLabel(f"仅提取勾选页面，水印与页码范围按这 {len(state.pages)} 页重新计算。\n主文档的未保存状态不会改变。\n"
                      + self._scope_summary(state, "watermark") + "；" + self._scope_summary(state, "numbers"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        canvas = PdfPageCanvas()
        canvas.set_mode("hand")
        layout.addWidget(canvas, 1)
        jump = self._spin(1, len(state.pages), 1, " 页")
        layout.addWidget(jump)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        save = buttons.button(QDialogButtonBox.Save)
        save.setText("确认并另存")
        save.setEnabled(False)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        def preview(value):
            save.setEnabled(False)
            canvas.setProperty("requestedPage", state.pages[value - 1].page_id)
            self._submit("render", {"state": state, "page_id": state.pages[value - 1].page_id, "max_pixels": 1400},
                         ("extract_preview", dialog, canvas, save))
        jump.valueChanged.connect(preview)
        QTimer.singleShot(0, lambda: preview(1))
        accepted = dialog.exec() == QDialog.Accepted
        for request_id, (operation, context) in list(self._jobs.items()):
            if operation == "render" and context[0] == "extract_preview" and context[1] is dialog:
                self._jobs.pop(request_id)
        if accepted:
            self._save_state(state, True)
        dialog.deleteLater()

    def has_unsaved_changes(self):
        return not self.undo_stack.isClean()

    def confirm_discard(self):
        answer = QMessageBox.question(self, "有未保存的修改", "是否先另存当前 PDF？\n放弃后，本次涂黑标记与撤销记录将清除；原文件不受影响。",
                                      QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel)
        return {QMessageBox.Save: "save", QMessageBox.Discard: "discard"}.get(answer, "cancel")

    def _maybe_discard(self, action):
        self._after_save = None
        if self._busy:
            self.show_error("当前正在处理 PDF，请先取消或等待完成。")
            return False
        if self.has_unsaved_changes():
            choice = self.confirm_discard()
            if choice == "cancel":
                return False
            if choice == "save":
                self._after_save = action
                self.export_current()
                return False
        action()
        return True

    def request_close(self):
        self._after_save = None
        if self._busy:
            self.show_error("当前正在处理 PDF，请先取消或等待完成。")
            return False
        if self.has_unsaved_changes():
            choice = self.confirm_discard()
            if choice == "cancel":
                return False
            if choice == "save":
                self._after_save = self.close_ready.emit
                self.export_current()
                return False
        return True

    def clear_workspace(self):
        def clear():
            self.worker.shutdown()
            self._jobs.clear()
            self.undo_stack.clear()
            self.source_names.clear()
            self.source_paths.clear()
            self.image_names.clear()
            self._cleanup_approved = False
            self._set_state(WorkspaceState())
            self.status_label.setText("工作区已清空，原文件未修改。")
        self._maybe_discard(clear)

    def shutdown(self):
        self._closed = True
        self._preview_timer.stop()
        self.worker.shutdown()
        self._jobs.clear()
        self._cache.clear()

    def show_licenses(self):
        import sys
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        path = root / "THIRD_PARTY_NOTICES.md"
        if path.exists():
            dialog = QDialog(self)
            dialog.setWindowTitle("开源说明与许可证")
            dialog.resize(700, 560)
            from PySide6.QtWidgets import QTextBrowser
            browser = QTextBrowser()
            browser.setMarkdown(path.read_text(encoding="utf-8"))
            browser.setSearchPaths([str(root)])
            browser.setOpenExternalLinks(True)
            layout = QVBoxLayout(dialog)
            layout.addWidget(browser)
            dialog.exec()
        else:
            self.show_error("开源说明文件尚未就绪。")

    def dragEnterEvent(self, event):
        if not self._busy and event.mimeData().hasUrls() and all(url.isLocalFile() and url.toLocalFile().lower().endswith(".pdf") for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = tuple(url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile())
        if paths and all(path.lower().endswith(".pdf") for path in paths):
            self.open_paths(paths)
            event.acceptProposedAction()

    def showEvent(self, event):
        super().showEvent(event)
        self._schedule_previews()
