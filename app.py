import os
import re
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QLibraryInfo,
    QLocale,
    Qt,
    QTranslator,
)
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSpinBox,
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
)


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


class ExcelMergerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.files = []
        self.file_info = {}
        self.output_file = ""
        self.refreshing_list = False
        application = QApplication.instance()
        self.system_locale = getattr(
            application,
            "preferred_locale",
            preferred_system_locale(),
        )

        self.setWindowTitle("Excel 合并工具 V1.0.0 - 保留格式版")
        self.resize(1120, 700)
        self.setMinimumSize(900, 580)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(22, 18, 22, 18)
        main_layout.setSpacing(14)

        title = QLabel("Excel 合并工具")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Arial", 20, QFont.Bold))
        main_layout.addWidget(title)

        subtitle = QLabel("选择 Excel 文件或文件夹，按列表顺序合并并保留单元格格式")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #5F6368; font-size: 13px;")
        main_layout.addWidget(subtitle)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        self.add_files_button = QPushButton("添加文件")
        self.add_folder_button = QPushButton("添加文件夹")
        self.move_up_button = QPushButton("上移")
        self.move_down_button = QPushButton("下移")
        self.delete_button = QPushButton("删除选中")
        self.clear_button = QPushButton("清空列表")

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
        file_group.setStyleSheet(
            """
            QGroupBox {
                font-weight: 600;
                border: 1px solid #C7CCD1;
                border-radius: 7px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            """
        )
        file_group_layout = QVBoxLayout(file_group)
        file_group_layout.setContentsMargins(10, 14, 10, 10)
        file_group_layout.setSpacing(8)

        self.file_table = QTreeWidget()
        self.file_table.setColumnCount(5)
        self.file_table.setHeaderLabels(
            ["序号", "文件名", "文件大小", "行数（含表头）", "文件路径"]
        )
        self.file_table.setRootIsDecorated(False)
        self.file_table.setUniformRowHeights(True)
        self.file_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.file_table.setDragDropMode(QAbstractItemView.NoDragDrop)
        self.file_table.setDragEnabled(False)
        self.file_table.setAcceptDrops(False)
        self.file_table.setDropIndicatorShown(False)
        self.file_table.setAlternatingRowColors(True)
        self.file_table.setStyleSheet(
            """
            QTreeWidget {
                background: white;
                color: #202124;
                border: 1px solid #B8BEC5;
                border-radius: 5px;
                font-size: 13px;
            }
            QTreeWidget::item {
                height: 32px;
                border-bottom: 1px solid #ECEFF1;
            }
            QTreeWidget::item:selected {
                background: #0A84FF;
                color: white;
            }
            QHeaderView::section {
                background: #F2F4F6;
                color: #202124;
                border: none;
                border-right: 1px solid #D4D8DC;
                border-bottom: 1px solid #C7CCD1;
                padding: 7px;
                font-weight: 600;
            }
            """
        )
        header = self.file_table.header()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        self.file_table.setColumnWidth(0, 65)
        self.file_table.setColumnWidth(1, 250)
        self.file_table.setColumnWidth(2, 105)
        self.file_table.setColumnWidth(3, 120)
        file_group_layout.addWidget(self.file_table)

        self.status_label = QLabel("尚未添加文件")
        self.status_label.setStyleSheet("color: #245B8A; font-size: 12px;")
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
        self.merge_button.setFont(QFont("Arial", 14, QFont.Bold))
        self.merge_button.setStyleSheet(
            """
            QPushButton {
                background: #16833F;
                color: white;
                border: none;
                border-radius: 7px;
                padding: 8px 28px;
            }
            QPushButton:hover { background: #126D35; }
            QPushButton:pressed { background: #0F5D2D; }
            QPushButton:disabled {
                background: #AAB2B9;
                color: #E8EAED;
            }
            """
        )
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

    def refresh_file_list(self, selected_row=None):
        self.refreshing_list = True
        self.file_table.clear()

        if not self.files:
            empty_item = QTreeWidgetItem(
                ["", "暂无文件，请添加 Excel 文件", "", "", ""]
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
                        str(path.parent),
                    ]
                )
                item.setData(0, Qt.UserRole, filename)
                item.setTextAlignment(0, Qt.AlignCenter)
                item.setTextAlignment(2, Qt.AlignCenter)
                item.setTextAlignment(3, Qt.AlignCenter)
                item.setToolTip(1, filename)
                item.setToolTip(4, filename)
                self.file_table.addTopLevelItem(item)

            self.status_label.setText(f"列表中共有 {len(self.files)} 个文件")
            if selected_row is not None:
                selected_row = max(0, min(selected_row, len(self.files) - 1))
                self.file_table.setCurrentItem(
                    self.file_table.topLevelItem(selected_row)
                )

        self.refreshing_list = False
        self.update_button_states()

    def update_button_states(self):
        has_files = bool(self.files)
        current_item = self.file_table.currentItem()
        has_selection = (
            has_files
            and current_item is not None
            and bool(current_item.data(0, Qt.UserRole))
        )
        self.move_up_button.setEnabled(has_selection)
        self.move_down_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)
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
        downloads = str(Path.home() / "Downloads")
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "选择 Excel 文件",
            downloads,
            "Excel 文件 (*.xlsx *.xlsm)",
        )
        if not filenames:
            return

        added_count = self.add_paths(filenames)
        self.status_label.setText(
            f"已添加 {added_count} 个文件，列表共 {len(self.files)} 个"
        )

    def add_folder(self):
        downloads = str(Path.home() / "Downloads")
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择 Excel 文件夹",
            downloads,
            QFileDialog.ShowDirsOnly,
        )
        if folder:
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

    def delete_selected(self):
        current_item = self.file_table.currentItem()
        if current_item is None:
            return

        row = self.file_table.indexOfTopLevelItem(current_item)
        if row < 0 or row >= len(self.files):
            return

        filename = self.files.pop(row)
        self.file_info.pop(filename, None)
        self.refresh_file_list(selected_row=min(row, len(self.files) - 1))

    def clear_files(self):
        self.files = []
        self.file_info = {}
        self.refresh_file_list()

    def create_output_dialog(self):
        downloads = str(Path.home() / "Downloads")
        dialog = QFileDialog(
            self,
            QCoreApplication.translate("QFileDialog", "Save As"),
            downloads,
            "Excel (*.xlsx)",
        )
        dialog.setAcceptMode(QFileDialog.AcceptSave)
        dialog.setFileMode(QFileDialog.AnyFile)
        dialog.setDefaultSuffix("xlsx")
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setOption(QFileDialog.DontConfirmOverwrite, False)
        dialog.selectFile(default_output_filename(self.system_locale))
        return dialog

    def choose_output_file(self):
        dialog = self.create_output_dialog()
        if dialog.exec() != QFileDialog.Accepted:
            return
        output_file = dialog.selectedFiles()[0]
        if not output_file.lower().endswith(".xlsx"):
            output_file += ".xlsx"

        self.output_file = os.path.abspath(output_file)
        self.output_path_edit.setText(self.output_file)
        self.output_path_edit.setToolTip(self.output_file)
        self.update_button_states()

    def merge_files(self):
        if not self.files or not self.output_file:
            QMessageBox.warning(
                self,
                "尚未完成设置",
                "请先添加 Excel 文件并选择保存位置。",
            )
            return

        if self.output_file in self.files:
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

        QMessageBox.information(
            self,
            "完成",
            f"合并完成！\n\n保存位置：\n{self.output_file}",
        )
