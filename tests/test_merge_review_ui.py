import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from openpyxl import Workbook, load_workbook
from PySide6.QtWidgets import QApplication, QDialog

from app import ExcelMergerWindow
from ui.merge_review import HeaderlessReviewDialog, MergeReviewDialog


class MergeReviewUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.window = ExcelMergerWindow()
        self.window.output_file = str(self.root / "结果.xlsx")

        def run(_title, _message, worker, success, failure=None, **_kwargs):
            try:
                result = worker(lambda *_: None)
            except Exception as exc:
                if not failure:
                    raise
                failure(str(exc))
            else:
                success(result)
            return True

        self.tasks = self.enterContext(patch.object(self.window, "start_background_task", side_effect=run))
        self.enterContext(patch.object(self.window, "show_merge_complete_message"))

    def tearDown(self):
        self.window.close()
        self.window.pdf_thumbnail_tempdir.cleanup()
        self.tmp.cleanup()

    def workbook(self, name, header, row, other=False):
        path = self.root / (name + ".xlsx")
        book = Workbook()
        if other:
            book.active.title = "汇总"
            book.active.append(["看板"])
            sheet = book.create_sheet("明细")
        else:
            sheet = book.active
            sheet.title = "订单"
        sheet.append(header)
        sheet.append(row)
        book.save(path)
        book.close()
        return str(path)

    def select(self, row):
        item = self.window.file_table.topLevelItem(row)
        self.window.file_table.setCurrentItem(item)
        return item

    def test_reselection_writes_only_reviewed_sheet_and_keeps_settings(self):
        w = self.window
        first = self.workbook("深圳", ["编号", "数量"], ["000123456789012345", 11])
        second = self.workbook("广州", ["编号", "数量"], ["000123456789012346", 22], True)
        w.add_paths([first, second])
        self.assertFalse(w.merge_button.isEnabled())
        combo = w.file_table.itemWidget(self.select(1), 2)
        combo.setCurrentText("明细")
        combo.activated.emit(combo.currentIndex())
        self.assertTrue(w.merge_button.isEnabled())
        w.merge_files()
        book = load_workbook(w.output_file)
        try:
            self.assertEqual(list(book.active.values), [
                ("编号", "数量"), ("000123456789012345", 11), ("000123456789012346", 22)
            ])
        finally:
            book.close()

    def test_mismatch_shows_consequence_and_cannot_be_bypassed_by_mode(self):
        w = self.window
        first = self.workbook("基准", ["编号", "数量", "金额"], ["001", 6, 30])
        swapped = self.workbook("错列", ["编号", "金额", "数量"], ["002", 50, 8])
        w.add_paths([first, swapped])
        self.select(1)
        self.assertIn("列顺序不同", w.file_table.topLevelItem(1).text(4))
        self.assertIn("写入", w.merge_detail.text())
        dialog = MergeReviewDialog(w.merge_sources[swapped], w.merge_sources[first],
                                   w.merge_checks[swapped], w)
        self.assertEqual(dialog.sheet.currentText(), "订单")
        dialog.close()
        w.merge_headerless.setChecked(True)
        self.assertFalse(w.merge_button.isEnabled())
        w.merge_headerless.setChecked(False)
        w.toggle_merge_exclusion()
        self.assertTrue(w.merge_button.isEnabled())
        self.assertIn("已排除 1 份", w.status_label.text())
        w.toggle_merge_exclusion()
        self.assertFalse(w.merge_button.isEnabled())
        corrected = self.workbook("纠正", ["编号", "数量", "金额"], ["002", 8, 50])
        with patch("app.QFileDialog.getOpenFileName", return_value=(corrected, "")):
            w.replace_merge_file()
        self.assertEqual(w.files, [first, corrected])
        self.assertTrue(w.merge_button.isEnabled())

    def test_changed_review_options_never_show_previous_success(self):
        first = self.workbook("对照", ["编号", "数量"], ["001", 1])
        second = self.workbook("来源", ["编号", "数量"], ["002", 2], True)
        w = self.window
        w.add_paths([first, second])
        w.set_merge_choice(second, "明细", 1)
        source = w.merge_sources[second]
        dialog = MergeReviewDialog(source, w.merge_sources[first], w.merge_checks[second], w)
        try:
            self.assertEqual(dialog.status.text(), "表头一致")
            dialog.header_row.setValue(2)
            self.assertEqual(dialog.status.text(), "待重新核对")
            dialog.header_row.setValue(1)
            self.assertEqual(dialog.status.text(), "表头一致")
            dialog.sheet.setCurrentText("汇总")
            self.assertEqual(dialog.status.text(), "待重新核对")
            self.assertEqual(dialog.preview_stack.currentIndex(), 1)
            dialog.sheet.setCurrentText("明细")
            self.assertEqual(dialog.preview_stack.currentIndex(), 0)
            self.assertEqual(dialog.status.text(), "表头一致")
            dialog.reject()
            self.assertEqual(w.merge_sources[second], source)
            self.assertFalse(Path(w.output_file).exists())
        finally:
            dialog.close()

    def test_headerless_confirmation_required_and_default_keeps_first_data_row(self):
        w = self.window
        first = self.workbook("上期", ["001", 6], ["002", 7])
        second = self.workbook("下期", ["005", 15], ["007", 8])
        w.add_paths([first, second])
        w.merge_headerless.setChecked(True)
        self.assertEqual(w.skip_rows_spinbox.value(), 0)
        self.assertTrue(w.merge_button.isEnabled())
        d = HeaderlessReviewDialog(tuple(w.merge_sources.values()), 0, w)
        model = d.current_preview.model()
        self.assertEqual(model.data(model.index(0, 0)), "005")
        d.close()
        with patch("app.HeaderlessReviewDialog.exec", return_value=QDialog.Rejected):
            w.merge_files()
        self.assertFalse(Path(w.output_file).exists())
        with patch("app.HeaderlessReviewDialog.exec", return_value=QDialog.Accepted):
            w.merge_files()
        book = load_workbook(w.output_file)
        try:
            self.assertEqual([r[0] for r in book.active.values], ["001", "002", "005", "007"])
        finally:
            book.close()

    def test_excluded_source_hardlink_and_stale_inputs_are_protected(self):
        w = self.window
        first = self.workbook("甲", ["编号"], ["001"])
        second = self.workbook("乙", ["编号"], ["002"])
        w.add_paths([first, second])
        self.select(1)
        w.toggle_merge_exclusion()
        os.link(second, w.output_file)
        with patch("app.QMessageBox.warning") as msg:
            w.merge_files()
            self.assertIn("源文件", msg.call_args.args[2])
        os.unlink(w.output_file)
        self.workbook("甲", ["编号"], ["999"])
        with patch("app.QMessageBox.warning") as msg:
            w.merge_files()
            self.assertIn("来源已更改", msg.call_args.args[1])
        self.assertFalse(w.merge_button.isEnabled())
        self.assertFalse(Path(w.output_file).exists())
        w.refresh_merge_sources()
        self.assertTrue(w.merge_button.isEnabled())

    def test_old_background_response_is_discarded(self):
        w = self.window
        source = self.workbook("测试", ["编号"], ["001"])
        with patch.object(w, "start_background_task") as deferred:
            w.add_paths([source])
            worker, success = deferred.call_args.args[2:4]
            outcome = worker(lambda *_: None)
            w.merge_source_changed(source)
            success(outcome)
        self.assertNotIn(source, w.merge_sources)
        self.assertFalse(w.merge_button.isEnabled())

    def test_reordering_reassigns_reference_and_shows_actual_skip(self):
        w = self.window
        files = [self.workbook(n, ["数量"], [i]) for i, n in enumerate(("甲", "乙"))]
        w.add_paths(files)
        self.select(1)
        w.move_up()
        self.assertEqual(w.participating_merge_files(), list(reversed(files)))
        self.assertEqual(w.file_table.topLevelItem(0).text(5), "全部保留")
        w.skip_rows_spinbox.setValue(0)
        self.select(1)
        self.assertIn("第 1 行", w.file_table.topLevelItem(1).text(5))
        self.assertIn("表头也写入", w.merge_detail.text())

    def test_different_header_rows_warn_before_skipping_data_or_including_a_header(self):
        w = self.window
        root = self.workbook("基准", ["编号"], ["001"])
        early = self.workbook("少标题", ["编号"], ["002"])
        other = self.root / "多标题.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.append(["统计报表"])
        ws.append(["统计区间"])
        ws.append(["编号"])
        ws.append(["003"])
        wb.save(other)
        wb.close()
        w.add_paths([root, early, other])
        w.set_merge_choice(str(other), None, 3)
        w.skip_rows_spinbox.setValue(2)
        self.assertTrue(w.merge_button.isEnabled())
        captured = []

        def go_back(dialog):
            from PySide6.QtWidgets import QPlainTextEdit
            captured.append(dialog.findChild(QPlainTextEdit).toPlainText())
            return QDialog.Rejected

        with patch("app.SkipRowReviewDialog.exec", new=go_back):
            w.merge_files()
        self.assertFalse(Path(w.output_file).exists())
        self.assertIn("少标题", captured[0])
        self.assertIn("第 2 行也会跳过", captured[0])
        self.assertIn("多标题", captured[0])
        self.assertIn("从第 3 行追加，表头行也会写入结果", captured[0])
        self.assertNotIn("基准", captured[0])
        with patch("app.SkipRowReviewDialog.exec", return_value=QDialog.Accepted):
            w.merge_files()
        result = load_workbook(w.output_file)
        try:
            self.assertEqual([r[0] for r in result.active.values], ["编号", "001", "编号", "003"])
        finally:
            result.close()

    def test_aliases_are_added_once_and_cannot_replace_another_list_entry(self):
        w = self.window
        primary = self.workbook("原件", ["编号"], ["001"])
        alias = self.root / "链接.xlsx"
        try:
            alias.symlink_to(primary)
        except OSError as error:
            if os.name == "nt" and getattr(error, "winerror", None) == 1314:
                self.skipTest("Creating symlinks requires permission on this Windows host")
            raise
        second = self.workbook("另外一份", ["编号"], ["002"])
        self.assertEqual(w.add_paths([primary, alias, second]), 2)
        self.assertEqual(w.add_paths([alias]), 0)
        self.select(1)
        with patch("app.QFileDialog.getOpenFileName", return_value=(str(alias), "")), patch("app.QMessageBox.warning") as warning:
            w.replace_merge_file()
            self.assertIn("已在本批", warning.call_args.args[2])
        self.assertEqual(w.files, [primary, second])
