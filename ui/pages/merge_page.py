import os
from pathlib import Path
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)
from excel_merge_tool import (
    build_merged_workbook,
    compare_merge_sources,
    inspect_merge_file,
    source_fingerprint,
    discover_excel_files,
    format_file_size,
)
from ui.merge_review import (
    HeaderlessReviewDialog,
    MergeReviewDialog,
    SkipRowReviewDialog,
    skip_row_warnings,
)
from ui.common_widgets import ClearSpinBox, SelectionComboBox
from ui.app_support import (
    default_output_filename,
)


class MergePageMixin:
    """Existing window methods; initialization remains in the window."""

    def setup_merge_page(self):
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

    def selected_merge_file(self):
        items = self.file_table.selectedItems()
        return items[0].data(0, Qt.UserRole) if len(items) == 1 else None

    def participating_merge_files(self):
        return [path for path in self.files if path not in self.merge_excluded]

    def refresh_file_list(self, selected_row=None):
        if self.refreshing_list:
            return
        if selected_row is None:
            current = self.file_table.currentItem()
            selected_row = self.file_table.indexOfTopLevelItem(current) if current else 0
        self.refreshing_list = True
        self.file_table.clear()
        included = self.participating_merge_files()
        reference_path = included[0] if included else None
        headerless = self.merge_headerless.isChecked()
        ready = [self.merge_sources[path] for path in included if path in self.merge_sources]
        self.merge_checks = {}
        if reference_path in self.merge_sources:
            self.merge_checks = dict(zip(
                (source.path for source in ready),
                compare_merge_sources(ready, headerless=headerless),
            ))
        for index, path in enumerate(self.files):
            source = self.merge_sources.get(path)
            check = self.merge_checks.get(path)
            excluded = path in self.merge_excluded
            is_reference = path == reference_path
            if excluded:
                state = "本次已排除"
            elif path in self.merge_errors:
                state = self.merge_errors[path]
            elif source is None:
                state = "等待读取"
            elif check is None:
                state = "等待对照表核对"
            else:
                state = check.summary
            name, row = self.merge_choices.get(path, (None, 1))
            start_row = 1 if is_reference else self.skip_rows_spinbox.value() + 1
            scope = "—" if excluded else ("全部保留" if is_reference else f"从第 {start_row} 行追加")
            info = ""
            if source:
                info = (f"{source.row_count} 行 × {source.column_count} 列 · "
                        f"{source.merged_cells} 处合并 · {format_file_size(source.fingerprint[2])}")
            item = QTreeWidgetItem([
                f"{index + 1} 对照" if is_reference else str(index + 1),
                Path(path).name, source.sheet_name if source else (name or "待读取"),
                "无表头" if headerless else f"第 {row} 行", state, scope, info,
            ])
            item.setData(0, Qt.UserRole, path)
            item.setToolTip(1, path)
            if not excluded and ((check and not check.ok) or path in self.merge_errors):
                item.setIcon(4, self.style().standardIcon(QStyle.SP_MessageBoxWarning))
            item.setToolTip(4, "\n".join(check.details) if check and check.details else state)
            self.file_table.addTopLevelItem(item)
            if source and len(source.sheet_names) > 1:
                selector = SelectionComboBox()
                selector.addItems(source.sheet_names)
                selector.setCurrentText(source.sheet_name)
                selector.setAccessibleName(f"{Path(path).name} 使用的工作表")
                selector.activated.connect(
                    lambda _, p=path, box=selector: self.set_merge_choice(p, box.currentText(), 1)
                )
                self.file_table.setItemWidget(item, 2, selector)
        if self.files:
            row = max(0, min(selected_row, len(self.files) - 1))
            self.file_table.setCurrentItem(self.file_table.topLevelItem(row))
        else:
            empty = QTreeWidgetItem(["", "暂无文件，请添加 Excel 文件"])
            empty.setFlags(Qt.NoItemFlags)
            self.file_table.addTopLevelItem(empty)
        self.refreshing_list = False
        self.status_label.setText(
            f"参与 {len(included)} 份，已排除 {len(self.merge_excluded)} 份" if self.files else "尚未添加文件"
        )
        self.update_button_states()

    def update_button_states(self):
        if self.refreshing_list:
            return
        included = self.participating_merge_files()
        path = self.selected_merge_file()
        check = self.merge_checks.get(path)
        self.move_up_button.setEnabled(bool(path and path != self.files[0]))
        self.move_down_button.setEnabled(bool(path and path != self.files[-1]))
        self.delete_button.setEnabled(bool(self.files and self.file_table.selectedItems()))
        self.clear_button.setEnabled(bool(self.files))
        self.merge_replace_button.setEnabled(bool(path))
        self.merge_exclude_button.setEnabled(bool(path))
        self.merge_exclude_button.setText("恢复参与" if path in self.merge_excluded else "本次排除")
        self.merge_refresh_button.setEnabled(bool(self.files))
        self.merge_review_button.setEnabled(bool(path))
        self.merge_button.setEnabled(bool(
            included and self.output_file and
            all(p in self.merge_checks and self.merge_checks[p].ok for p in included)
        ))
        if path in self.merge_errors:
            detail = self.merge_errors[path]
        elif path in self.merge_excluded:
            detail = "这份文件不参与本次合并，可点击“恢复参与”。"
        elif check and not check.ok:
            detail = (check.details or (check.summary,))[0]
        elif path and path in self.merge_sources:
            source = self.merge_sources[path]
            detail = f"按第 {source.header_row} 行核对表头。" if not self.merge_headerless.isChecked() else "无表头模式，合并前需确认数据预览。"
            if included and path != included[0]:
                start = self.skip_rows_spinbox.value() + 1
                detail += f"这份文件从第 {start} 行开始追加。"
                if not self.merge_headerless.isChecked():
                    if start <= source.header_row:
                        detail += "当前设置会把表头也写入结果。"
                    elif start > source.header_row + 1 and source.row_count > source.header_row:
                        detail += "当前设置还会跳过表头后的行。"
        else:
            detail = ""
        self.merge_detail.setText(detail[:220] + ("…" if len(detail) > 220 else ""))
        self.merge_detail.setVisible(bool(detail))

    def merge_source_changed(self, path):
        if path not in self.files:
            return
        self.merge_sources.pop(path, None)
        self.merge_reads.pop(path, None)
        self.merge_errors[path] = "来源已更改，请重新核对"
        self.refresh_file_list()

    def read_merge_sources(self, paths, selected_path=None):
        if not paths or self.task_is_running():
            return
        token = object()
        requests = []
        for path in paths:
            self.merge_reads[path] = token
            self.merge_sources.pop(path, None)
            self.merge_errors.pop(path, None)
            sheet, row = self.merge_choices.get(path, (None, 1))
            requests.append((path, sheet, row))
        self.refresh_file_list()

        def inspect(progress):
            outcomes = []
            for i, (path, sheet, row) in enumerate(requests):
                progress(i, len(requests), f"正在核对 {Path(path).name}")
                try:
                    outcomes.append((path, inspect_merge_file(path, sheet, row), ""))
                except Exception as error:
                    outcomes.append((path, None, str(error)))
            return outcomes

        def loaded(outcomes):
            watching = set(self.merge_watcher.files())
            for path, source, error in outcomes:
                if self.merge_reads.get(path) is not token or path not in self.files:
                    continue
                self.merge_reads.pop(path, None)
                if source:
                    self.merge_sources[path] = source
                    self.merge_choices[path] = (source.sheet_name, source.header_row)
                else:
                    self.merge_errors[path] = f"无法核对：{error}"
                if path not in watching and os.path.isfile(path):
                    self.merge_watcher.addPath(path)
            self.refresh_file_list(self.files.index(selected_path) if selected_path in self.files else None)

        def failed(error):
            loaded([(path, None, error) for path, _, _ in requests])

        self.start_background_task(
            "核对 Excel 工作表和表头", f"正在读取 {len(requests)} 份文件…",
            inspect, loaded, failed, total=len(requests), status_label=self.status_label,
        )

    def refresh_merge_sources(self):
        self.read_merge_sources(tuple(self.files), self.selected_merge_file())

    def set_merge_choice(self, path, sheet, row):
        if path not in self.files or self.task_is_running():
            return
        self.merge_choices[path] = (sheet, row)
        self.read_merge_sources([path], path)

    def review_merge_file(self):
        path = self.selected_merge_file()
        if not path:
            return
        source = self.merge_sources.get(path)
        if not source:
            if self.confirm_list_change("按该文件默认工作表、第 1 行重新读取？"):
                self.set_merge_choice(path, None, 1)
            return
        included = self.participating_merge_files()
        ref = self.merge_sources.get(included[0]) if included else None
        dialog = MergeReviewDialog(source, ref, self.merge_checks.get(path), self)
        accepted = dialog.exec() == QDialog.Accepted
        sheet, row = dialog.sheet.currentText(), dialog.header_row.value()
        dialog.deleteLater()
        if accepted:
            self.set_merge_choice(path, sheet, row)

    def toggle_merge_exclusion(self):
        path = self.selected_merge_file()
        if path:
            self.merge_excluded.symmetric_difference_update((path,))
            self.refresh_file_list()

    def change_merge_mode(self, headerless):
        if headerless:
            self.header_mode_skip_rows = self.skip_rows_spinbox.value()
        self.skip_rows_spinbox.setValue(0 if headerless else self.header_mode_skip_rows)
        self.refresh_file_list()

    def forget_merge_file(self, path):
        if path in self.merge_watcher.files():
            self.merge_watcher.removePath(path)
        self.merge_sources.pop(path, None)
        self.merge_errors.pop(path, None)
        self.merge_choices.pop(path, None)
        self.merge_reads.pop(path, None)
        self.merge_excluded.discard(path)

    def replace_merge_file(self):
        old = self.selected_merge_file()
        if not old:
            return
        new, _ = QFileDialog.getOpenFileName(
            self, "替换这份 Excel 文件", str(Path(old).parent), "Excel 文件 (*.xlsx *.xlsm)"
        )
        if not new:
            return
        new = os.path.abspath(new)
        key = os.path.normcase(os.path.realpath(new))
        if any(p != old and os.path.normcase(os.path.realpath(p)) == key for p in self.files):
            QMessageBox.warning(self, "无法替换", "所选文件已在本批列表中。")
            return
        if key == os.path.normcase(os.path.realpath(old)):
            new = old
        if new != old:
            excluded = old in self.merge_excluded
            self.files[self.files.index(old)] = new
            self.forget_merge_file(old)
            if excluded:
                self.merge_excluded.add(new)
        self.read_merge_sources([new], new)

    def add_paths(self, paths):
        if self.task_is_running():
            return 0
        existing = {os.path.normcase(os.path.realpath(path)) for path in self.files}
        new_paths = []
        for path in paths:
            path = os.path.abspath(path)
            key = os.path.normcase(os.path.realpath(path))
            if key not in existing:
                self.files.append(path)
                new_paths.append(path)
                existing.add(key)
        if new_paths:
            self.read_merge_sources(new_paths, new_paths[-1])
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

        self.add_paths(filenames)

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

        return self.add_paths(excel_files)

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
        selected = {item.data(0, Qt.UserRole) for item in self.file_table.selectedItems()}
        selected.discard(None)
        if not selected or not self.confirm_list_change("是否从列表移除选中的文件？原文件会保留。"):
            return
        first = min(self.files.index(path) for path in selected)
        self.files = [path for path in self.files if path not in selected]
        for path in selected:
            self.forget_merge_file(path)
        self.refresh_file_list(first)

    def clear_files(self):
        if not self.files or not self.confirm_list_change("是否清空列表？"):
            return
        for path in self.files:
            self.forget_merge_file(path)
        self.files = []
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
        open_button = message.addButton("打开文件", QMessageBox.ActionRole)
        ok_button = message.addButton("确定", QMessageBox.AcceptRole)
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

        if self.task_is_running():
            return
        output_file = self.output_file
        try:
            for path in self.files:
                if (os.path.realpath(output_file) == os.path.realpath(path)
                        or os.path.exists(output_file) and os.path.exists(path)
                        and os.path.samefile(output_file, path)):
                    QMessageBox.warning(self, "无法保存", "保存位置与列表中的源文件相同，请选择新的文件名。")
                    return
        except OSError as error:
            QMessageBox.warning(self, "无法核对保存位置", str(error))
            return

        files = tuple(self.participating_merge_files())
        if not files or any(p not in self.merge_checks or not self.merge_checks[p].ok for p in files):
            QMessageBox.warning(self, "尚不能合并", "请先处理列表中的核对问题，或排除相应文件。")
            return
        reviewed = tuple(self.merge_sources[p] for p in files)
        changed = []
        for source in reviewed:
            try:
                if source_fingerprint(source.path) == source.fingerprint:
                    continue
            except OSError:
                pass
            changed.append(source.path)
        if changed:
            for path in changed:
                self.merge_source_changed(path)
            QMessageBox.warning(self, "来源已更改", "请点击“重新核对”查看最新数据后再合并。")
            return
        skip_rows = self.skip_rows_spinbox.value()
        keep_merged_cells = self.merged_cells_checkbox.isChecked()
        headerless = self.merge_headerless.isChecked()
        if headerless:
            dialog = HeaderlessReviewDialog(reviewed, skip_rows, self)
        else:
            warnings = skip_row_warnings(reviewed, skip_rows)
            dialog = SkipRowReviewDialog(warnings, skip_rows, self) if warnings else None
        if dialog is not None:
            accepted = dialog.exec() == QDialog.Accepted
            dialog.deleteLater()
            if not accepted:
                self.skip_rows_spinbox.setFocus()
                return

        def merge_task(progress_callback):
            build_merged_workbook(
                files,
                output_file,
                skip_rows=skip_rows,
                keep_merged_cells=keep_merged_cells,
                reviewed_sources=reviewed,
                headerless=headerless,
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
