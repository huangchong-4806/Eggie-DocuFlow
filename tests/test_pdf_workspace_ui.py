import os
import unittest
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QObject, QPointF, Qt, Signal
from PySide6.QtGui import QImage, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QListWidget, QDialog, QPushButton

from pdf_workspace import RedactionMark, WorkspacePage, WorkspaceState
from ui.pdf_widgets import PdfPageCanvas
from ui.pdf_workspace import PdfWorkspaceWidget


class FakeProcess(QObject):
    completed = Signal(int, int, object)
    failed = Signal(int, int, str)
    discarded = Signal(int)
    progress = Signal(int, int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.requests = []

    def submit(self, operation, payload, revision):
        self.requests.append((len(self.requests) + 1, revision, operation, payload))
        return len(self.requests)

    def cancel(self):
        pass

    def shutdown(self):
        pass


def sample_preview(rotation=0):
    image = QImage(300, 400, QImage.Format_RGB32)
    image.fill(QColor("white"))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    chars = tuple({"text": letter, "bbox": (30 + i * 12, 50 + line * 30, 42 + i * 12, 70 + line * 30),
                   "line_id": str(line), "char_id": line * 3 + i}
                  for line in range(2) for i, letter in enumerate("ABC"))
    return {"page_id": "p1", "png": bytes(data), "width_pt": 400 if rotation % 180 else 300,
            "height_pt": 300 if rotation % 180 else 400,
            "source_to_view": {0: (1, 0, 0, 1, 0, 0), 90: (0, 1, -1, 0, 400, 0),
                               180: (-1, 0, 0, -1, 300, 400), 270: (0, -1, 1, 0, 0, 300)}[rotation],
            "chars": chars}


class PdfWorkspaceUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.process_patch = patch("ui.pdf_workspace.PdfWorkspaceProcess", FakeProcess)
        self.process_patch.start()
        self.addCleanup(self.process_patch.stop)
        self.widget = PdfWorkspaceWidget()
        self.widget.resize(1100, 800)
        self.widget.show()
        self.addCleanup(self.widget.shutdown)
        self.addCleanup(self.widget.hide)
        QTest.qWait(10)

    def seed(self):
        self.widget.state = WorkspaceState(pages=[WorkspacePage("p1", "s", 0), WorkspacePage("p2", "s", 1)])
        self.widget.refresh_workspace()
        self.widget._display_preview(sample_preview(), 1600)

    def test_modules_share_state_and_initial_save_is_disabled(self):
        original = self.widget.state
        self.widget.module_tabs.setCurrentIndex(1)
        self.assertIs(self.widget.state, original)
        self.assertEqual([self.widget.module_tabs.tabText(i) for i in range(2)], ["页面编辑", "内容编辑"])
        self.assertFalse(self.widget.export_button.isEnabled())

    def test_save_dialog_uses_absolute_source_directory_for_full_and_partial_exports(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder).resolve() / "source.pdf"
            source.touch()
            self.widget._jobs[900] = ("open", ((str(source),), [], True))
            self.widget._completed(900, self.widget.revision, [WorkspacePage("p1", "s", 0)])
            self.widget._set_busy(False)
            for partial, name in ((False, "PDF编辑结果.pdf"), (True, "提取结果.pdf")):
                with patch("ui.pdf_workspace.QFileDialog.getSaveFileName", return_value=("", "")) as dialog:
                    self.widget._save_state(self.widget.state, partial)
                self.assertEqual(Path(dialog.call_args.args[2]), source.parent / name)
                self.assertFalse((source.parent / name).exists())

    def test_save_dialog_prefers_successful_output_and_falls_back_when_unavailable(self):
        from pdf_toolbox import PdfToolResult
        self.seed()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            documents = root / "Documents"
            documents.mkdir()
            output_dir = root / "outputs"
            output_dir.mkdir()
            output = output_dir / "saved.pdf"
            self.widget._jobs[900] = ("export", False)
            with patch("ui.pdf_workspace.QMessageBox.information"):
                self.widget._completed(900, self.widget.revision, PdfToolResult(str(output), ""))
            with patch("ui.pdf_workspace.QFileDialog.getSaveFileName", return_value=("", "")) as dialog:
                self.widget.export_current()
            self.assertEqual(Path(dialog.call_args.args[2]).parent, output_dir)
            with patch("PySide6.QtCore.QStandardPaths.writableLocation", return_value=str(documents)), patch(
                    "ui.pdf_workspace.os.access", side_effect=lambda path, flags: Path(path) != output_dir), patch(
                    "ui.pdf_workspace.QFileDialog.getSaveFileName", return_value=("", "")) as dialog:
                self.widget.export_current()
            self.assertEqual(Path(dialog.call_args.args[2]).parent, documents)
            output_dir.rmdir()
            with patch("PySide6.QtCore.QStandardPaths.writableLocation", return_value=str(documents)), patch(
                    "ui.pdf_workspace.QFileDialog.getSaveFileName", return_value=("", "")) as dialog:
                self.widget.export_current()
            self.assertEqual(Path(dialog.call_args.args[2]).parent, documents)

    def test_save_dialog_defaults_to_documents_without_source_and_ignores_failed_output(self):
        self.seed()
        with tempfile.TemporaryDirectory() as folder:
            documents = Path(folder).resolve() / "Documents"
            documents.mkdir()
            failed_directory = documents.parent / "failed-output"
            failed_directory.mkdir()
            with patch("PySide6.QtCore.QStandardPaths.writableLocation", return_value=str(documents)), patch(
                    "ui.pdf_workspace.QFileDialog.getSaveFileName", return_value=(str(failed_directory / "failed.pdf"), "")):
                self.widget.export_current()
            request_id = next(key for key, job in self.widget._jobs.items() if job[0] == "export")
            with patch.object(self.widget, "show_error"):
                self.widget._failed(request_id, self.widget.revision, "保存失败")
            with patch("PySide6.QtCore.QStandardPaths.writableLocation", return_value=str(documents)), patch(
                    "ui.pdf_workspace.QFileDialog.getSaveFileName", return_value=("", "")) as dialog:
                self.widget.export_current()
            self.assertEqual(Path(dialog.call_args.args[2]), documents / "PDF编辑结果.pdf")

    def test_save_dialog_skips_unwritable_source_without_creating_directories(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            source = root / "source.pdf"
            source.touch()
            documents = root / "Documents"
            documents.mkdir()
            self.widget._jobs[900] = ("open", ((str(source),), [], True))
            self.widget._completed(900, self.widget.revision, [WorkspacePage("p1", "s", 0)])
            self.widget._set_busy(False)
            before = set(root.rglob("*"))
            with patch("PySide6.QtCore.QStandardPaths.writableLocation", return_value=str(documents)), patch(
                    "ui.pdf_workspace.os.access", side_effect=lambda path, flags: Path(path) != root), patch(
                    "ui.pdf_workspace.QFileDialog.getSaveFileName", return_value=("", "")) as dialog:
                self.widget.export_current()
            self.assertEqual(Path(dialog.call_args.args[2]).parent, documents)
            self.assertEqual(set(root.rglob("*")), before)

    def test_page_navigation_keeps_thumbnails_above_readable_page_labels(self):
        from ui.common_widgets import ClearSpinBox, SelectionComboBox
        self.assertEqual(self.widget.page_list.viewMode(), QListWidget.IconMode)
        self.assertFalse(self.widget.page_list.isWrapping())
        self.assertIsInstance(self.widget.page_jump, ClearSpinBox)
        self.assertIsInstance(self.widget.thumbnail_size_combo, SelectionComboBox)
        self.widget.source_names["s"] = "source.pdf"
        self.seed()
        self.assertIn("source.pdf", self.widget.document_label.text())

    def test_scope_labels_count_actual_pages_and_flag_invalid_ranges(self):
        self.seed()
        self.widget.watermark_kind.setCurrentIndex(1)
        self.widget.watermark_skip.setChecked(True)
        self.widget.number_enabled.setChecked(True)
        self.assertIn("1 / 2", self.widget.watermark_scope_label.text())
        self.assertIn("2 / 2", self.widget.number_scope_label.text())
        self.widget.watermark_ranges.setText("9")
        self.widget._settings_changed()
        self.assertIn("范围无效", self.widget.watermark_scope_label.text())

    def test_signed_document_warns_before_editing_and_progress_does_not_complete_job(self):
        self.seed()
        self.widget._jobs[10] = ("inspect", "opened")
        result = {"signatures": 1, "attachments": 0, "annotations": 0, "forms": 1, "blocking_reasons": []}
        with patch("ui.pdf_workspace.QMessageBox.information") as notice, patch(
                "ui.pdf_workspace.QMessageBox.question") as apply_prompt:
            self.widget._completed(10, self.widget.revision, result)
        notice.assert_called_once()
        apply_prompt.assert_not_called()
        self.widget._jobs[11] = ("export", False)
        self.widget._busy = True
        self.widget.worker.progress.emit(11, self.widget.revision, "正在处理第 1 / 2 页")
        self.assertIn("1 / 2", self.widget.status_label.text())
        self.assertIn(11, self.widget._jobs)
        self.assertTrue(self.widget._busy)

    def test_page_rotation_reorder_delete_and_undo_keep_mark_binding(self):
        self.seed()
        mark = RedactionMark("m", "p1", ((30, 50, 60, 70),))
        self.widget.state.marks = [mark]
        self.widget.pdf_page_cards[0].set_checked(True)
        self.widget.rotate_selected_pdf_pages(90)
        self.assertEqual(self.widget.state.pages[0].rotation, 90)
        self.widget.reorder_pdf_page(0, 2)
        self.assertEqual(self.widget.state.pages[-1].page_id, "p1")
        self.assertEqual(self.widget.state.marks[0].page_id, "p1")
        self.widget.delete_selected_pdf_pages()
        self.assertEqual(self.widget.state.marks, [])
        self.widget.undo_stack.undo()
        self.assertEqual(self.widget.state.marks, [mark])

    def test_mouse_area_and_multiline_text_selection_use_source_coordinates(self):
        self.seed()
        self.widget.module_tabs.setCurrentIndex(1)
        canvas = self.widget.canvas
        for rotation in (0, 90, 180, 270):
            canvas.set_page(sample_preview(rotation))
            canvas.fit_page()
            for mode in ("area", "text"):
                canvas.set_mode(mode)
                start = canvas.mapFromScene(canvas.source_transform.map(QPointF(34, 58)))
                end = canvas.mapFromScene(canvas.source_transform.map(QPointF(61, 89)))
                QTest.mousePress(canvas.viewport(), Qt.LeftButton, pos=start)
                QTest.mouseMove(canvas.viewport(), end, delay=20)
                QTest.mouseRelease(canvas.viewport(), Qt.LeftButton, pos=end)
                mark = self.widget.state.marks[-1]
                self.assertEqual(mark.mode, mode)
                self.assertEqual(len(mark.rects), 1 if mode == "area" else 2)
                self.assertLess(abs(mark.rects[0][0] - (34 if mode == "area" else 30)), 2)

    def test_area_move_resize_escape_delete_and_undo(self):
        self.seed()
        widget, canvas = self.widget, self.widget.canvas
        widget.module_tabs.setCurrentIndex(1)
        widget.add_mark(((40, 120, 140, 210),), "area")
        widget.set_selection_mode("select")
        def drag(start, end, cancel=False):
            first = canvas.mapFromScene(QPointF(*start))
            last = canvas.mapFromScene(QPointF(*end))
            QTest.mousePress(canvas.viewport(), Qt.LeftButton, pos=first)
            QTest.mouseMove(canvas.viewport(), last, delay=20)
            if cancel:
                QTest.keyClick(canvas, Qt.Key_Escape)
            QTest.mouseRelease(canvas.viewport(), Qt.LeftButton, pos=last)
        drag((90, 165), (110, 175))
        moved = widget.state.marks[0].rects[0]
        self.assertAlmostEqual(moved[0], 60, delta=2)
        drag((moved[2], moved[3]), (180, 250))
        resized = widget.state.marks[0].rects[0]
        self.assertAlmostEqual(resized[2], 180, delta=2)
        drag((110, 175), (160, 200), cancel=True)
        self.assertEqual(widget.state.marks[0].rects[0], resized)
        QTest.keyClick(canvas, Qt.Key_Delete)
        self.assertEqual(widget.state.marks, [])
        widget.undo_stack.undo()
        self.assertEqual(widget.state.marks[0].rects[0], resized)

    def test_extraction_drops_preview_of_previously_selected_page(self):
        self.seed()
        dialog = QDialog(self.widget)
        canvas, button = PdfPageCanvas(dialog), QPushButton(dialog)
        button.setEnabled(False)
        canvas.setProperty("requestedPage", "p2")
        dialog.show()
        self.addCleanup(dialog.hide)
        self.widget._jobs[20] = ("render", ("extract_preview", dialog, canvas, button))
        self.widget._completed(20, self.widget.revision, sample_preview())
        self.assertFalse(button.isEnabled())
        self.assertIsNone(canvas.preview)
        self.widget._jobs[21] = ("render", ("extract_preview", dialog, canvas, button))
        preview = dict(sample_preview(), page_id="p2")
        self.widget._completed(21, self.widget.revision, preview)
        self.assertEqual(canvas.preview["page_id"], "p2")
        self.assertTrue(button.isEnabled())

    def test_process_progress_keeps_active_job_and_crash_discards_waiting_previews(self):
        from queue import Queue
        from types import SimpleNamespace
        from ui.tasks import PdfWorkspaceProcess
        process = PdfWorkspaceProcess()
        process._responses = Queue()
        process._process = SimpleNamespace(is_alive=lambda: True)
        process._active = (1, 5, "export", {})
        seen = []
        process.progress.connect(lambda *_: seen.append(process._active[0]))
        process.completed.connect(lambda *_: seen.append("done"))
        process._responses.put((1, 5, "progress", "正在核验"))
        process._responses.put((1, 5, "completed", True))
        process._poll()
        self.assertEqual(seen, [1, "done"])
        self.assertIsNone(process._active)
        process._active = (2, 5, "apply", {})
        process._pending = [(3, 5, "render", {})]
        process._process = SimpleNamespace(is_alive=lambda: False)
        errors, discarded = [], []
        process.failed.connect(lambda *args: errors.append(args))
        process.discarded.connect(discarded.append)
        process._poll()
        self.assertEqual(errors[0][0], 2)
        self.assertEqual(discarded, [3])
        self.assertEqual(process._pending, [])
        self.assertIsNone(process._active)

    def test_crashed_export_cleans_only_its_registered_temporary_file(self):
        import tempfile
        from pathlib import Path
        from queue import Queue
        from types import SimpleNamespace
        from ui.tasks import PdfWorkspaceProcess
        with tempfile.TemporaryDirectory() as folder:
            temporary = Path(folder) / ".export-owned.pdf"
            original = Path(folder) / "original.pdf"
            temporary.write_bytes(b"incomplete test data")
            original.write_bytes(b"keep")
            process = PdfWorkspaceProcess()
            process._temporary_path = str(temporary)
            process._responses = Queue()
            process._active = (1, 0, "export", {})
            process._process = SimpleNamespace(is_alive=lambda: False)
            process._poll()
            self.assertFalse(temporary.exists())
            self.assertEqual(original.read_bytes(), b"keep")

    def test_pending_marks_block_all_exports_and_return_to_editing_is_undoable(self):
        self.seed()
        self.widget.state.marks = [RedactionMark("m", "p1", ((30, 50, 60, 70),), applied=True)]
        self.widget.return_to_editing()
        self.assertFalse(self.widget.state.marks[0].applied)
        with patch.object(self.widget, "show_error") as error:
            self.widget.export_current()
        error.assert_called_once()
        self.widget.undo_stack.undo()
        self.assertTrue(self.widget.state.marks[0].applied)

    def test_cancel_close_preserves_dirty_state_and_view_changes_do_not_dirty(self):
        self.seed()
        self.assertFalse(self.widget.has_unsaved_changes())
        self.widget.module_tabs.setCurrentIndex(1)
        self.widget.canvas.fit_page()
        self.assertFalse(self.widget.has_unsaved_changes())
        self.widget.pdf_page_cards[0].set_checked(True)
        self.widget.rotate_selected_pdf_pages(90)
        with patch.object(self.widget, "confirm_discard", return_value="cancel"):
            self.assertFalse(self.widget.request_close())
        self.assertTrue(self.widget.has_unsaved_changes())

    def test_late_preview_is_ignored_but_export_result_is_not_dropped(self):
        self.seed()
        self.widget._jobs[101] = ("render", (0, "p1", 1600))
        self.widget.revision = 1
        with patch.object(self.widget.canvas, "set_page") as display:
            self.widget._completed(101, 0, sample_preview())
        display.assert_not_called()
        self.widget.pdf_page_cards[0].set_checked(True)
        self.widget.rotate_selected_pdf_pages(90)
        self.widget._jobs[102] = ("export", True)
        from pdf_toolbox import PdfToolResult
        with patch("ui.pdf_workspace.QMessageBox.information"):
            self.widget._completed(102, 0, PdfToolResult("/tmp/safe.pdf", ""))
        self.assertIn("safe.pdf", self.widget.status_label.text())
        self.assertTrue(self.widget.has_unsaved_changes())

    def test_successful_full_save_cleans_but_failure_and_cancel_do_not_close(self):
        self.seed()
        self.widget.pdf_page_cards[0].set_checked(True)
        self.widget.rotate_selected_pdf_pages(90)
        with patch.object(self.widget, "confirm_discard", return_value="save"), patch(
                "ui.pdf_workspace.QFileDialog.getSaveFileName", return_value=("", "")):
            self.assertFalse(self.widget.request_close())
        self.assertTrue(self.widget.has_unsaved_changes())
        self.assertIsNone(self.widget._after_save)
        self.widget._jobs[10] = ("export", False)
        with patch.object(self.widget, "show_error"):
            self.widget._failed(10, self.widget.revision, "保存失败")
        self.assertTrue(self.widget.has_unsaved_changes())
        self.widget._jobs[11] = ("export", False)
        from pdf_toolbox import PdfToolResult
        with patch("ui.pdf_workspace.QMessageBox.information"):
            self.widget._completed(11, self.widget.revision, PdfToolResult("/tmp/safe.pdf", ""))
        self.assertFalse(self.widget.has_unsaved_changes())

    def test_apply_then_new_mark_and_cancelled_apply_keep_correct_state(self):
        self.seed()
        self.widget.add_mark(((30, 50, 60, 70),), "area")
        self.widget._jobs[10] = ("apply", ())
        self.widget._completed(10, self.widget.revision, True)
        self.assertTrue(self.widget.state.marks[0].applied)
        self.widget._display_preview(sample_preview(), 1600)
        self.widget.add_mark(((90, 50, 120, 70),), "area")
        self.assertFalse(self.widget.state.marks[-1].applied)
        self.widget._jobs[11] = ("apply", ())
        self.widget.cancel_operation()
        self.widget._completed(11, self.widget.revision, True)
        self.assertFalse(self.widget.state.marks[-1].applied)

    def test_ten_thousand_marks_are_paged_without_truncating_the_state(self):
        self.seed()
        self.widget.state.marks = [RedactionMark(str(i), "p1", ((30, 50, 60, 70),)) for i in range(10001)]
        self.widget._refresh_marks()
        self.assertEqual(self.widget.mark_list.count(), 50)
        self.assertIn("10001", self.widget.mark_count_label.text())
        self.widget._mark_list_page = 200
        self.widget._refresh_marks()
        self.assertEqual(self.widget.mark_list.count(), 1)
        self.assertEqual(len(self.widget.state.marks), 10001)

    def test_cancel_after_page_switch_never_marks_the_wrong_page(self):
        self.seed()
        self.widget.module_tabs.setCurrentIndex(1)
        self.widget._set_busy(True)
        self.widget.page_list.setCurrentRow(1)
        self.widget._jobs[10] = ("apply", ())
        self.widget.cancel_operation()
        self.widget._completed(10, self.widget.revision, True)
        self.assertFalse(self.widget.canvas.isEnabled())
        with patch.object(self.widget, "show_error"):
            self.widget.add_mark(((30, 50, 60, 70),), "area")
        self.assertEqual(self.widget.state.marks, [])

    def test_blocked_save_does_not_leave_a_deferred_close_action(self):
        self.seed()
        self.widget.add_mark(((30, 50, 60, 70),), "area")
        with patch.object(self.widget, "confirm_discard", return_value="save"), patch.object(self.widget, "show_error"):
            self.assertFalse(self.widget.request_close())
        self.assertIsNone(self.widget._after_save)

    def test_editing_settings_in_the_middle_keeps_the_cursor(self):
        self.seed()
        self.widget.module_tabs.setCurrentIndex(1)
        for edit, tool, original, position, inserted, expected in (
                (self.widget.watermark_text, 1, "ABCD", 2, "xy", "ABxyCD"),
                (self.widget.watermark_ranges, 1, "1,2", 1, "-2", "1-2,2"),
                (self.widget.number_ranges, 2, "1,2", 1, "-2", "1-2,2")):
            with self.subTest(field=original, tool=tool):
                self.widget.tool_tabs.setCurrentIndex(tool)
                edit.setText(original)
                self.widget._settings_changed()
                edit.setFocus()
                edit.setCursorPosition(position)
                QTest.keyClicks(edit, inserted)
                self.assertEqual(edit.text(), expected)
                self.assertEqual(edit.cursorPosition(), position + len(inserted))

    def test_undo_redo_and_clear_keep_watermark_image_name_in_sync(self):
        self.seed()
        for request, name, image in ((801, "first.png", "a"), (802, "second.png", "b")):
            self.widget._jobs[request] = ("image", name)
            self.widget._completed(request, self.widget.revision, image)
        self.widget.undo_stack.undo()
        self.assertEqual(self.widget.state.watermark.image_id, "a")
        self.assertEqual(self.widget.watermark_image_label.text(), "first.png")
        self.widget.undo_stack.redo()
        self.assertEqual(self.widget.watermark_image_label.text(), "second.png")
        with patch.object(self.widget, "confirm_discard", return_value="discard"):
            self.widget.clear_workspace()
        self.assertEqual(self.widget.watermark_image_label.text(), "尚未选择图片")

    def test_replacing_document_releases_old_sources_but_inserting_preserves_undo(self):
        self.seed()
        self.widget.source_names["s"] = "old.pdf"
        inserted = WorkspacePage("inserted", "inserted-source", 0)
        self.widget._jobs[800] = ("open", (("inserted.pdf",), [], False))
        self.widget._completed(800, self.widget.revision, [inserted])
        self.assertFalse(any(r[2] == "release" for r in self.widget.worker.requests))
        self.widget._set_busy(False)
        self.widget.undo_stack.undo()
        self.assertEqual(len(self.widget.state.pages), 2)
        self.widget.undo_stack.redo()
        self.assertEqual(self.widget.state.pages[-1], inserted)
        new = WorkspacePage("new-page", "new-source", 0)
        self.widget._jobs[801] = ("open", (("new.pdf",), [], True))
        self.widget._completed(801, self.widget.revision, [new])
        releases = [r[3] for r in self.widget.worker.requests if r[2] == "release"]
        self.assertEqual(len(releases), 1)
        self.assertEqual(set(releases[0]["source_ids"]), {"s", "inserted-source"})
        self.assertEqual(self.widget.source_names, {"new-source": "new.pdf"})
        self.assertFalse(self.widget.undo_stack.canUndo())

    def test_cancelled_and_failed_imports_release_only_the_new_snapshots(self):
        self.seed()
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                imported = [WorkspacePage("unused-page", "unused-source", 0)]
                self.widget._jobs[810] = ("open", (("second.pdf",), imported, True))
                if cancel:
                    self.widget.cancel_operation()
                    self.widget._completed(810, self.widget.revision, [WorkspacePage("last", "last-source", 0)])
                else:
                    with patch.object(self.widget, "show_error"):
                        self.widget._failed(810, self.widget.revision, "文件无法读取")
                releases = [r[3] for r in self.widget.worker.requests if r[2] == "release"]
                self.assertTrue(releases)
                self.assertEqual(set(releases[-1]["source_ids"]), {"unused-source", "last-source"} if cancel else {"unused-source"})
                self.assertEqual([ref.page_id for ref in self.widget.state.pages], ["p1", "p2"])

    def test_cancelling_queued_export_removes_it_before_dispatch(self):
        import tempfile
        from pathlib import Path
        from queue import Queue
        from threading import Event
        from types import SimpleNamespace
        from ui.tasks import PdfWorkspaceProcess
        with tempfile.TemporaryDirectory() as folder:
            process = PdfWorkspaceProcess()
            process._process = SimpleNamespace(is_alive=lambda: True)
            process._cancel = Event()
            process._requests, process._responses = Queue(), Queue()
            process._active = (900, 0, "render", {})
            request = process.submit("export", {"output_file": str(Path(folder) / "cancelled.pdf")}, 0)
            seen = []
            process.failed.connect(lambda *args: seen.append(args))
            process.cancel()
            self.assertTrue(process._cancel.is_set())
            process._responses.put((900, 0, "completed", {}))
            process._poll()
            try:
                self.assertTrue(process._requests.empty(), "Cancelled export was dispatched")
                self.assertEqual([item[0] for item in seen], [request])
                self.assertEqual(list(Path(folder).iterdir()), [])
            finally:
                process._clear_temporary()
                process._process = None

    def test_cancel_before_worker_start_does_not_cancel_resource_release(self):
        from ui.tasks import PdfWorkspaceProcess
        process = PdfWorkspaceProcess()
        process.submit("release", {"source_ids": ("old",)}, 0)
        request = process.submit("export", {"output_file": "/tmp/not-dispatched.pdf"}, 0)
        seen = []
        process.failed.connect(lambda *args: seen.append(args[0]))
        process.cancel()
        try:
            self.assertEqual([r[2] for r in process._pending], ["release"])
            self.assertEqual(seen, [request])
        finally:
            process._pending.clear()

    def test_success_with_cleanup_warning_cleans_document_without_claiming_log_failure(self):
        from pdf_toolbox import PdfToolResult
        self.seed()
        self.widget.pdf_page_cards[0].set_checked(True)
        self.widget.rotate_selected_pdf_pages(90)
        self.widget._jobs[820] = ("export", False)
        with patch("ui.pdf_workspace.QMessageBox.information"):
            self.widget._completed(820, self.widget.revision, PdfToolResult("/tmp/result.pdf", "/tmp/log.txt", failures=("临时文件未清理",)))
        self.assertFalse(self.widget.has_unsaved_changes())
        self.assertNotIn("记录未能写入", self.widget.status_label.text())
        self.assertIn("提醒", self.widget.status_label.text())


if __name__ == "__main__":
    unittest.main()
