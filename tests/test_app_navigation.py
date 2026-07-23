import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pypdf import PdfWriter
from PySide6.QtCore import QThread, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGroupBox, QLabel, QPushButton

from app import ClearSpinBox, ExcelMergerWindow, PdfImageCard, PdfPageCard
from ocr_settings_dialog import SoftwareSettingsDialog
from pdf_toolbox import PdfToolResult


class AppNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = ExcelMergerWindow()

    def tearDown(self):
        self.window.close()
        self.window.pdf_thumbnail_tempdir.cleanup()

    def test_theme_module_is_the_canonical_source(self):
        import app
        from ui.theme import (
            ACCENT_PALETTES as UI_ACCENT_PALETTES,
            build_theme_colors as ui_build_theme_colors,
            build_theme_stylesheet as ui_build_theme_stylesheet,
        )

        self.assertIs(app.ACCENT_PALETTES, UI_ACCENT_PALETTES)
        self.assertIs(app.build_theme_colors, ui_build_theme_colors)
        self.assertIs(app.build_theme_stylesheet, ui_build_theme_stylesheet)
        stylesheet = ui_build_theme_stylesheet(ui_build_theme_colors("cyan"))
        self.assertIn("QMainWindow", stylesheet)
        self.assertIn("QWidget#pdfThumbnailBox", stylesheet)

    def test_task_threads_use_ui_module_and_report_results(self):
        import app
        from ui.tasks import BackgroundTaskThread, DocumentOCRThread, InvoiceBatchProcessThread

        self.assertIs(app.BackgroundTaskThread, BackgroundTaskThread)
        self.assertIs(app.DocumentOCRThread, DocumentOCRThread)
        self.assertIs(app.InvoiceBatchProcessThread, InvoiceBatchProcessThread)

        progress = []
        completed = []
        succeeded = BackgroundTaskThread(
            lambda callback: (callback(1, 1, "完成"), "result")[1]
        )
        succeeded.progress.connect(
            lambda value, total, text: progress.append((value, total, text))
        )
        succeeded.completed.connect(completed.append)
        succeeded.run()

        failures = []

        def fail(_callback):
            raise OSError("disk full")

        failed = BackgroundTaskThread(fail)
        failed.failed.connect(failures.append)
        failed.run()

        self.assertEqual(progress, [(1, 1, "完成")])
        self.assertEqual(completed, ["result"])
        self.assertEqual(failures, ["OSError: disk full"])

    def test_invoice_task_can_be_marked_for_forced_stop(self):
        from ui.tasks import InvoiceBatchProcessThread

        task = InvoiceBatchProcessThread(("sample.pdf",), "output")
        task.force_stop()

        self.assertTrue(task._force_stop_requested)

    def test_invoice_task_stops_the_separate_process_when_forced(self):
        from ui.tasks import InvoiceBatchProcessThread

        cancelled = []
        task = InvoiceBatchProcessThread(("missing.pdf",), tempfile.gettempdir())
        task.cancelled.connect(lambda: cancelled.append(True))
        task.force_stop()
        task.run()

        self.assertEqual(cancelled, [True])

    def test_invoice_task_reports_a_batch_result_from_the_separate_process(self):
        from ui.tasks import InvoiceBatchProcessThread

        completed = []
        failures = []
        task = InvoiceBatchProcessThread(("missing.pdf",), tempfile.gettempdir())
        task.completed.connect(completed.append)
        task.failed.connect(failures.append)
        task.run()

        self.assertFalse(failures)
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0][0], [])
        self.assertIn("PDF 文件不存在", completed[0][1][0][1])

    def test_invoice_task_reports_when_process_cannot_start(self):
        from ui.tasks import InvoiceBatchProcessThread

        class Process:
            def start(self):
                raise OSError("无法启动")

            def is_alive(self):
                return False

        class Context:
            def Queue(self):
                return MagicMock()

            def Process(self, **_kwargs):
                return Process()

        failures = []
        task = InvoiceBatchProcessThread(("sample.pdf",), tempfile.gettempdir())
        task.failed.connect(failures.append)
        with patch("ui.tasks.multiprocessing.get_context", return_value=Context()):
            task.run()

        self.assertEqual(failures, ["OSError: 无法启动"])

    def test_common_widgets_use_ui_module(self):
        import app
        from ui.common_widgets import ClearSpinBox, SelectionComboBox

        self.assertIs(app.ClearSpinBox, ClearSpinBox)
        self.assertIs(app.SelectionComboBox, SelectionComboBox)
        self.assertEqual(len(self.window.findChildren(ClearSpinBox)), 6)
        self.assertIsInstance(self.window.pdf_export_format_combo, SelectionComboBox)
        self.assertIsInstance(self.window.pdf_export_quality_combo, SelectionComboBox)

    def test_pdf_widgets_use_ui_module(self):
        import app
        from ui.pdf_widgets import PdfImageBoard, PdfImageCard, PdfPageBoard, PdfPageCard

        self.assertIs(app.PdfPageCard, PdfPageCard)
        self.assertIs(app.PdfImageCard, PdfImageCard)
        self.assertIs(app.PdfPageBoard, PdfPageBoard)
        self.assertIs(app.PdfImageBoard, PdfImageBoard)
        self.assertIsInstance(self.window.pdf_page_board, PdfPageBoard)
        self.assertIsInstance(self.window.pdf_image_board, PdfImageBoard)

    def test_pdf_widgets_share_only_common_base_behavior(self):
        from ui.pdf_widgets import (
            DragDropBoard,
            PdfImageBoard,
            PdfImageCard,
            PdfPageBoard,
            PdfPageCard,
            PdfThumbnailCard,
        )

        self.assertTrue(issubclass(PdfPageCard, PdfThumbnailCard))
        self.assertTrue(issubclass(PdfImageCard, PdfThumbnailCard))
        self.assertTrue(issubclass(PdfPageBoard, DragDropBoard))
        self.assertTrue(issubclass(PdfImageBoard, DragDropBoard))
        self.assertIsNot(PdfPageCard.update_display, PdfImageCard.update_display)
        self.assertNotEqual(PdfPageCard.drag_mime, PdfImageCard.drag_mime)

    def test_sidebar_controls_every_page_and_marks_the_active_menu(self):
        pages = [
            ("home", self.window.show_home, self.window.home_page),
            ("excel", self.window.show_excel_tool, self.window.excel_page),
            ("split", self.window.show_split_tool, self.window.split_page),
            ("invoice", self.window.show_invoice_tool, self.window.invoice_page),
            ("document", self.window.show_document_tool, self.window.document_page),
            ("rename", self.window.show_rename_tool, self.window.rename_page),
            ("pdf", self.window.show_pdf_tool, self.window.pdf_page),
        ]

        for active_key, show_page, expected_page in pages:
            show_page()
            self.assertIs(self.window.stack.currentWidget(), expected_page)
            self.assertEqual(
                self.window.nav_buttons[active_key].property("variant"),
                "homeNavActive",
            )
            self.assertTrue(
                all(
                    button.property("variant") == "homeNav"
                    for key, button in self.window.nav_buttons.items()
                    if key != active_key
                )
            )

        button_texts = {
            button.text()
            for button in self.window.findChildren(QPushButton)
        }
        self.assertNotIn("返回工具首页", button_texts)
        self.assertNotIn("打开 Excel 合并", button_texts)
        self.assertEqual(len(self.window.findChildren(ClearSpinBox)), 6)
        self.assertEqual(self.window.stack.count(), 7)
        self.assertIn("仅提取文字", button_texts)
        self.assertIn("前往设置", button_texts)
        self.assertNotIn("配置密钥", button_texts)
        self.assertFalse(self.window.document_ocr_checkbox.isChecked())
        self.assertNotIn("ocr", self.window.nav_buttons)

    def test_home_cards_remove_badges_and_enlarge_open_buttons(self):
        home_labels = {
            label.text() for label in self.window.home_page.findChildren(QLabel)
        }
        open_buttons = [
            button
            for button in self.window.home_page.findChildren(QPushButton)
            if button.text() == "打开"
        ]

        self.assertTrue(
            {"常用", "清晰", "台账", "识别", "安全", "多功能"}.isdisjoint(home_labels)
        )
        self.assertEqual(len(open_buttons), 6)
        self.assertTrue(
            all(
                button.minimumWidth() >= 112 and button.minimumHeight() >= 44
                for button in open_buttons
            )
        )

    def test_pdf_organizer_actions_share_one_toolbar(self):
        toolbar_buttons = (
            self.window.pdf_add_button,
            self.window.pdf_clear_button,
            self.window.pdf_check_all_button,
            self.window.pdf_uncheck_all_button,
            self.window.pdf_move_previous_button,
            self.window.pdf_move_next_button,
            self.window.pdf_rotate_left_button,
            self.window.pdf_rotate_right_button,
            self.window.pdf_rotate_180_button,
            self.window.pdf_delete_pages_button,
            self.window.pdf_split_selected_button,
        )

        self.assertTrue(
            all(
                self.window.pdf_organizer_button_layout.indexOf(button) >= 0
                for button in toolbar_buttons
            )
        )
        self.assertEqual(
            self.window.pdf_organizer_button_layout.indexOf(
                self.window.pdf_save_pages_button
            ),
            -1,
        )

    def test_batch_limits_are_visible_before_adding_files(self):
        self.assertEqual(
            self.window.pdf_image_limit_label.text(),
            "当前 0 / 300 张；处理数量越多，处理速度越慢，"
            "请酌情拆分任务",
        )
        self.assertEqual(
            self.window.pdf_page_limit_label.text(),
            "当前 0 / 1,000 页；处理数量越多，处理速度越慢，"
            "请酌情拆分任务",
        )
        self.assertEqual(
            self.window.rename_limit_label.text(),
            "当前 0 / 20,000 个文件；处理数量越多，处理速度越慢，"
            "请酌情拆分任务",
        )

    def test_hard_limit_rejects_whole_addition(self):
        with patch("app.QMessageBox.warning") as warning:
            accepted = self.window.confirm_large_addition(
                "图片",
                current=299,
                added=2,
                warning=100,
                maximum=300,
            )

        self.assertFalse(accepted)
        warning.assert_called_once()
        self.assertIn("本次没有添加", warning.call_args.args[2])

    def test_soft_warning_is_only_shown_when_crossing_the_threshold(self):
        with patch("app.QMessageBox.question") as question:
            accepted_after_threshold = self.window.confirm_large_addition(
                "图片",
                current=101,
                added=1,
                warning=100,
                maximum=300,
            )

        self.assertTrue(accepted_after_threshold)
        question.assert_not_called()

    def test_cancelling_image_warning_keeps_existing_list(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "extra.png"
            from PIL import Image

            Image.new("RGB", (20, 20), "blue").save(source)
            existing = [
                SimpleNamespace(image_file=f"/tmp/existing-{index}.png")
                for index in range(100)
            ]
            self.window.pdf_image_cards = existing.copy()

            with patch("app.QMessageBox.question", return_value=0):
                started = self.window.start_adding_pdf_images([source])

            self.assertFalse(started)
            self.assertEqual(self.window.pdf_image_cards, existing)
            self.assertIsNone(self.window.background_task_thread)

    def test_pdf_image_card_reuses_cached_preview(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.png"
            preview = root / "preview.jpg"
            from PIL import Image

            Image.new("RGB", (800, 600), "blue").save(source)
            Image.new("RGB", (120, 90), "blue").save(preview)
            card = PdfImageCard(self.window, str(source), str(preview))

            card.update_display(1)
            first_key = card.thumbnail_cache.cacheKey()
            card.update_display(2)

            self.assertFalse(card.thumbnail_cache.isNull())
            self.assertEqual(card.thumbnail_cache.cacheKey(), first_key)
            card.deleteLater()

    def test_pdf_image_addition_runs_in_background_and_updates_visible_count(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "source.png"
            from PIL import Image

            Image.new("RGB", (1600, 900), "blue").save(source)

            started = self.window.start_adding_pdf_images([source])
            for _ in range(100):
                self.application.processEvents()
                if self.window.background_task_thread is None:
                    break
                QTest.qWait(10)

            self.assertTrue(started)
            self.assertEqual(len(self.window.pdf_image_cards), 1)
            self.assertNotEqual(
                self.window.pdf_image_cards[0].thumbnail_file,
                str(source),
            )
            self.assertTrue(
                self.window.pdf_image_limit_label.text().startswith("当前 1 / 300 张")
            )

    def test_pdf_image_hard_limit_keeps_existing_cards(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "extra.png"
            from PIL import Image

            Image.new("RGB", (20, 20), "blue").save(source)
            existing = [
                SimpleNamespace(image_file=f"/tmp/existing-{index}.png")
                for index in range(300)
            ]
            self.window.pdf_image_cards = existing.copy()

            with patch("app.QMessageBox.warning"):
                started = self.window.start_adding_pdf_images([source])

            self.assertFalse(started)
            self.assertEqual(self.window.pdf_image_cards, existing)
            self.assertIsNone(self.window.background_task_thread)

    def test_pdf_page_card_reuses_cached_thumbnail(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            thumbnail = Path(temporary_directory) / "thumbnail.png"
            from PIL import Image

            Image.new("RGB", (120, 160), "white").save(thumbnail)
            card = PdfPageCard(
                self.window,
                {
                    "source_file": str(Path(temporary_directory) / "source.pdf"),
                    "page_index": 0,
                    "rotation": 0,
                    "thumbnail": str(thumbnail),
                },
            )

            card.update_display(1)
            first_key = card.thumbnail_cache.cacheKey()
            card.update_display(2)

            self.assertFalse(card.thumbnail_cache.isNull())
            self.assertEqual(card.thumbnail_cache.cacheKey(), first_key)
            card.deleteLater()

    def test_pdf_page_rotation_keeps_cached_preview_inside_card(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            thumbnail = Path(temporary_directory) / "portrait.png"
            from PIL import Image

            Image.new("RGB", (120, 160), "white").save(thumbnail)
            data = {
                "source_file": str(Path(temporary_directory) / "source.pdf"),
                "page_index": 0,
                "rotation": 0,
                "thumbnail": str(thumbnail),
            }
            card = PdfPageCard(self.window, data)
            card.update_display(1)
            first_key = card.thumbnail_cache.cacheKey()

            data["rotation"] = 90
            card.update_display(1)
            displayed = card.image_label.pixmap()

            self.assertEqual(card.thumbnail_cache.cacheKey(), first_key)
            self.assertLessEqual(displayed.width(), 132)
            self.assertLessEqual(displayed.height(), 180)
            card.deleteLater()

    def test_pdf_page_hard_limit_rejects_before_rendering(self):
        with patch("app.QMessageBox.warning"), patch.object(
            self.window, "start_rendering_pdf_pages"
        ) as render:
            accepted = self.window.pdf_page_count_checked(
                ("/tmp/large.pdf",),
                (("/tmp/large.pdf", 1001),),
            )

        self.assertFalse(accepted)
        render.assert_not_called()
        self.assertEqual(self.window.pdf_page_cards, [])

    def test_rename_rule_changes_are_debounced(self):
        with patch.object(self.window, "refresh_rename_file_list") as refresh:
            self.window.rename_rule_primary_edit.setText("A")
            self.window.rename_rule_primary_edit.setText("AB")
            QTest.qWait(320)

        refresh.assert_called_once()

    def test_stale_rename_preview_cannot_be_reenabled_by_selecting_a_row(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "old-name.txt"
            source.touch()
            self.window.add_rename_paths([source])
            self.window.rename_rule_primary_edit.setText("old")
            self.window.rename_rule_secondary_edit.setText("new")
            self.window.rename_preview_timer.stop()
            self.window.refresh_rename_file_list(force_sync=True)
            self.assertTrue(self.window.rename_execute_button.isEnabled())

            self.window.rename_rule_secondary_edit.setText("newer")
            self.assertFalse(self.window.rename_execute_button.isEnabled())
            self.window.rename_file_table.topLevelItem(0).setSelected(True)
            self.application.processEvents()

            self.assertFalse(self.window.rename_execute_button.isEnabled())
            with patch("app.QMessageBox.information") as information:
                self.window.rename_files()
            information.assert_called_once()
            self.assertTrue(source.exists())

    def test_rename_hard_limit_keeps_existing_list(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            extra = Path(temporary_directory) / "extra.txt"
            extra.touch()
            existing = [f"/tmp/existing-{index}.txt" for index in range(20000)]
            self.window.rename_source_files = existing.copy()

            with patch("app.QMessageBox.warning"):
                accepted = self.window.add_rename_paths([extra])

            self.assertFalse(accepted)
            self.assertEqual(self.window.rename_source_files, existing)

    def test_large_rename_preview_runs_with_progress(self):
        self.window.rename_source_files = [
            f"/tmp/example-{index}.txt" for index in range(5001)
        ]

        with patch("app.preview_renames", return_value=()) as preview:
            started = self.window.refresh_rename_file_list()
            for _ in range(100):
                self.application.processEvents()
                if self.window.background_task_thread is None:
                    break
                QTest.qWait(10)

        self.assertTrue(started)
        preview.assert_called_once()
        self.assertTrue(
            self.window.rename_limit_label.text().startswith(
                "当前 5,001 / 20,000 个文件"
            )
        )

    def test_cloud_ocr_temporarily_disables_enhanced_layout(self):
        self.window.document_enhanced_layout_checkbox.setChecked(True)

        self.window.document_ocr_checkbox.setChecked(True)

        self.assertFalse(self.window.document_enhanced_layout_checkbox.isChecked())
        self.assertFalse(self.window.document_enhanced_layout_checkbox.isEnabled())

        self.window.document_ocr_checkbox.setChecked(False)

        self.assertTrue(self.window.document_enhanced_layout_checkbox.isEnabled())

    def test_window_refuses_to_close_while_background_task_is_running(self):
        worker = QThread(self.window)
        worker.run = lambda: QThread.msleep(200)
        self.window.document_ocr_thread = worker
        worker.start()
        self.window.show()
        self.application.processEvents()

        with patch("app.QMessageBox.warning") as warning:
            closed = self.window.close()

        self.assertFalse(closed)
        warning.assert_called_once()
        worker.wait()
        self.window.document_ocr_thread = None

    def test_global_progress_keeps_the_window_responsive(self):
        timer_fired = []
        completed = []

        def worker(progress_callback):
            progress_callback(0, 2, "正在处理第 1 / 2 个文件")
            QThread.msleep(120)
            progress_callback(2, 2, "已处理 2 / 2 个文件")
            return "done"

        started = self.window.start_background_task(
            "正在测试任务",
            "准备处理文件…",
            worker,
            completed.append,
            total=2,
        )
        QTimer.singleShot(20, lambda: timer_fired.append(True))
        for _ in range(50):
            self.application.processEvents()
            if completed:
                break
            QTest.qWait(10)

        self.assertTrue(started)
        self.assertTrue(timer_fired)
        self.assertEqual(completed, ["done"])
        self.assertIsNone(self.window.background_task_thread)
        self.assertTrue(self.window.stack.isEnabled())

    def test_pdf_export_all_failed_shows_failure_instead_of_completion(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            broken_pdf = root / "损坏.pdf"
            broken_pdf.write_text("not a pdf", encoding="utf-8")
            self.window.pdf_export_source_files = [str(broken_pdf)]
            self.window.pdf_export_output_folder_edit.setText(str(root / "output"))

            with patch("app.QMessageBox.critical") as critical, patch.object(
                self.window, "save_pdf_result_message"
            ) as completion:
                self.window.export_pdf_to_images()
                for _ in range(100):
                    self.application.processEvents()
                    if self.window.background_task_thread is None:
                        break
                    QTest.qWait(10)

            critical.assert_called_once()
            self.assertIn("所有 PDF 都转换失败", critical.call_args.args[2])
            completion.assert_not_called()
            self.assertTrue(self.window.pdf_export_status_label.text().startswith("转换失败"))

    def test_document_inspection_runs_in_background(self):
        self.window.document_source_file = "/tmp/large.pdf"
        self.window.document_output_folder = "/tmp/output"
        inspection = SimpleNamespace(page_count=3, scanned_pages=())

        def slow_inspection(_source):
            QThread.msleep(100)
            return inspection

        with patch("app.inspect_pdf", side_effect=slow_inspection), patch.object(
            self.window, "document_inspection_completed"
        ) as completed:
            self.window.start_document_inspection("process")
            self.assertIsNotNone(self.window.background_task_thread)
            for _ in range(50):
                self.application.processEvents()
                if self.window.background_task_thread is None:
                    break
                QTest.qWait(10)

        completed.assert_called_once_with("process", inspection)

    def test_pdf_batch_result_opens_the_selected_root_folder(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_subfolder = root / "第一份"
            first_subfolder.mkdir()
            first_image = first_subfolder / "第一份_1.jpg"
            first_image.touch()
            log_file = root / "log.txt"
            log_file.touch()
            result = PdfToolResult(
                "",
                str(log_file),
                image_files=(str(first_image),),
            )

            with patch("app.QMessageBox") as message_class, patch.object(
                self.window, "open_output_file"
            ) as open_output:
                message = message_class.return_value
                open_button = MagicMock()
                ok_button = MagicMock()
                message.addButton.side_effect = [open_button, ok_button]
                message.clickedButton.return_value = open_button

                self.window.save_pdf_result_message(
                    "PDF 导出图片完成",
                    result,
                    open_target=str(root),
                )

            open_output.assert_called_once_with(str(root))

    def test_software_settings_combines_appearance_and_ocr_services(self):
        with tempfile.TemporaryDirectory() as temporary_directory, patch.dict(
            os.environ,
            {
                "EGGIE_OCR_CONFIG_DIR": temporary_directory,
                "BAIDU_OCR_API_KEY": "",
                "BAIDU_OCR_SECRET_KEY": "",
                "ALIBABA_CLOUD_ACCESS_KEY_ID": "",
                "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "",
            },
        ):
            dialog = SoftwareSettingsDialog(
                "baidu",
                (("cyan", "青色"), ("blue", "蓝色")),
                "cyan",
            )
            group_titles = {
                group.title() for group in dialog.findChildren(QGroupBox)
            }
            button_texts = {
                button.text() for button in dialog.findChildren(QPushButton)
            }

            self.assertEqual(dialog.windowTitle(), "软件设置")
            self.assertIn("外观", group_titles)
            self.assertIn("第三方服务", group_titles)
            self.assertIn("保存当前平台密钥", button_texts)
            self.assertIn("保存并测试连接", button_texts)
            dialog.close()

    def test_pdf_export_accepts_multiple_sources_and_uses_high_quality_default(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pdf_files = []
            for filename in ("第一份.pdf", "第二份.pdf"):
                pdf_file = root / filename
                writer = PdfWriter()
                writer.add_blank_page(width=200, height=300)
                with pdf_file.open("wb") as handle:
                    writer.write(handle)
                pdf_files.append(pdf_file)

            added, repeated = self.window.add_pdf_export_sources(
                [pdf_files[0], pdf_files[1], pdf_files[0]]
            )

            self.assertEqual(added, 2)
            self.assertEqual(repeated, 1)
            self.assertEqual(len(self.window.pdf_export_source_files), 2)
            self.assertEqual(self.window.pdf_export_source_tree.topLevelItemCount(), 2)
            self.assertEqual(self.window.pdf_export_quality_combo.currentData(), 300)
            self.assertEqual(self.window.pdf_export_button.text(), "开始转换")
            self.assertEqual(self.window.pdf_save_pages_button.text(), "保存结果")
            self.assertEqual(
                self.window.pdf_save_pages_button.parent().title(),
                "输出设置",
            )
            self.assertTrue(self.window.pdf_clear_export_sources_button.isEnabled())

    def test_pdf_export_folder_adds_only_direct_pdf_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            nested = root / "子文件夹"
            nested.mkdir()
            for pdf_file in (root / "第一份.pdf", root / "第二份.PDF", nested / "第三份.pdf"):
                writer = PdfWriter()
                writer.add_blank_page(width=200, height=300)
                with pdf_file.open("wb") as handle:
                    writer.write(handle)
            (root / "说明.txt").write_text("not a pdf", encoding="utf-8")

            found, added, repeated = self.window.add_pdf_export_source_folder(root)
            found_again, added_again, repeated_again = (
                self.window.add_pdf_export_source_folder(root)
            )

            self.assertEqual((found, added, repeated), (2, 2, 0))
            self.assertEqual((found_again, added_again, repeated_again), (2, 0, 2))
            self.assertEqual(len(self.window.pdf_export_source_files), 2)
            self.assertNotIn("第三份.pdf", " ".join(self.window.pdf_export_source_files))


if __name__ == "__main__":
    unittest.main()
