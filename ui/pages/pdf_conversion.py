import os
import uuid
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from pdf_toolbox import (
    IMAGE_SUFFIXES,
    default_output_name,
    images_to_pdf,
    output_path,
    pdfs_to_images,
    prepare_image_thumbnail,
)
from ui.common_widgets import SelectionComboBox
from ui.pdf_widgets import (
    PDF_PAGE_CARD_HEIGHT,
    PDF_PAGE_CARD_H_SPACING,
    PDF_PAGE_CARD_V_SPACING,
    PDF_PAGE_CARD_WIDTH,
    PDF_PAGE_THUMBNAIL_SIZE,
    PdfImageBoard,
    PdfImageCard,
    load_image_pixmap,
)
from ui.app_support import (
    PDF_IMAGE_MAX_COUNT,
    PDF_IMAGE_WARNING_COUNT,
)


class PdfConversionMixin:
    """Existing window methods; initialization remains in the window."""

    def create_pdf_convert_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(10)

        mode_layout = QHBoxLayout()
        self.pdf_image_mode_button = QPushButton("图片转 PDF")
        self.pdf_export_mode_button = QPushButton("PDF 转图片")
        for button in (self.pdf_image_mode_button, self.pdf_export_mode_button):
            button.setProperty("variant", "mode")
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
        self.pdf_delete_checked_images_button = QPushButton("移出列表")
        self.pdf_delete_checked_images_button.setToolTip("从待处理列表移除，不删除原文件")
        self.pdf_clear_images_button = QPushButton("清空列表")
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
        image_output_row = QHBoxLayout()
        image_output_row.addWidget(self.pdf_image_output_folder_edit, 1)
        image_output_row.addWidget(self.pdf_choose_image_output_button)
        image_layout.addLayout(image_output_row)
        image_layout.addWidget(QLabel("保存文件名："))
        image_layout.addWidget(self.pdf_image_output_name_edit)
        self.pdf_images_to_pdf_button = QPushButton("合成 PDF")
        self.pdf_images_to_pdf_button.setMinimumHeight(44)
        self.pdf_images_to_pdf_button.setProperty("variant", "primary")
        image_layout.addWidget(self.pdf_images_to_pdf_button, 0, Qt.AlignRight)
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
        self.pdf_delete_export_source_button = QPushButton("移出列表")
        self.pdf_delete_export_source_button.setToolTip("从待处理列表移除，不删除原文件")
        self.pdf_delete_export_source_button.setProperty("variant", "danger")
        self.pdf_clear_export_sources_button = QPushButton("清空列表")
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
        export_layout.addWidget(self.pdf_export_button, 0, Qt.AlignRight)
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

    def show_pdf_convert_mode(self, index):
        self.pdf_convert_stack.setCurrentIndex(index)
        self.pdf_image_mode_button.setChecked(index == 0)
        self.pdf_export_mode_button.setChecked(index == 1)

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
        pixmap = load_image_pixmap(card.image_file)
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
        repeated = 0
        skipped_before_check = 0
        for filename in filenames:
            normalized = os.path.abspath(filename)
            if normalized in seen:
                repeated += 1
                continue
            seen.add(normalized)
            path = Path(normalized)
            if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
                skipped_before_check += 1
                continue
            candidates.append(normalized)

        def report_addition(added, skipped):
            detail = f"本次新增 {added} 张图片，列表共 {len(self.pdf_image_cards)} 张。"
            if repeated:
                detail += f"忽略 {repeated} 个重复项。"
            if skipped:
                detail += f"跳过 {skipped} 个非图片或无法读取文件。"
            self.pdf_image_status_label.setText(detail)
            if not added:
                QMessageBox.information(self, "没有新增图片", detail)

        if not candidates:
            report_addition(0, skipped_before_check)
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
                    f"image_{uuid.uuid4().hex}.png"
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
            report_addition(len(prepared), skipped)

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
        if not self.confirm_list_change(f"是否从列表移除勾选的 {len(selected)} 张图片？\n不删除原文件。"):
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
            self.sync_pdf_image_source_files()
            image_files = tuple(self.pdf_image_source_files)
            if not self.pdf_workspace.can_process_files(image_files):
                return
            output_file = output_path(
                self.pdf_image_output_folder_edit.text(),
                self.pdf_image_output_name_edit.text(),
                default_output_name("图片合成PDF"),
            )
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
        self.update_pdf_button_states()

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
        if not self.pdf_workspace.can_process_files(self.pdf_export_source_files):
            return
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
                f"失败 PDF：{failure_count} 个"
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
