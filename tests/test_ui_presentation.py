"""User-visible layout regressions for the warm desktop presentation."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QLabel
from app import ExcelMergerWindow
from ocr_settings_dialog import SoftwareSettingsDialog


class PresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = ExcelMergerWindow()
        self.window.resize(1180, 720)
        self.window.show()
        self.qt.processEvents()

    def tearDown(self):
        self.window.pdf_workspace.undo_stack.setClean()
        self.window.close()
        self.qt.processEvents()

    def test_pdf_navigation_does_not_move_between_modules(self):
        w = self.window; w.show_pdf_tool()
        for size in ((1180, 720), (1280, 820)):
            w.resize(*size); w.pdf_tabs.setCurrentIndex(0); self.qt.processEvents()
            before = w.pdf_tabs.tabBar().mapTo(w, QPoint(0, 0))
            for index in (1, 2, 0, 2, 1):
                w.pdf_tabs.setCurrentIndex(index); self.qt.processEvents()
                self.assertEqual(w.pdf_tabs.tabBar().mapTo(w, QPoint(0, 0)), before)
                self.assertEqual(w.size().toTuple(), size)

    def test_pdf_module_tabs_precede_the_document_actions(self):
        w = self.window; w.show_pdf_tool()
        tabs = w.pdf_tabs.tabBar(); header = w.pdf_workspace.document_header
        for index in (0, 1, 2, 0, 1):
            w.pdf_tabs.setCurrentIndex(index); self.qt.processEvents()
            if index < 2:
                self.assertTrue(header.isVisible())
                tab_bottom = tabs.mapTo(w, QPoint(0, tabs.height())).y()
                self.assertGreaterEqual(header.mapTo(w, QPoint(0, 0)).y(), tab_bottom)
                self.assertIs(header.parentWidget(), w.pdf_tabs.currentWidget())
            else:
                self.assertFalse(header.isVisible())
        self.assertLessEqual(tabs.mapTo(w.pdf_workspace, QPoint(0, 0)).y(), 8)

    def test_conversion_switch_keeps_buttons_and_content_in_place(self):
        w = self.window; w.show_pdf_tool(); w.pdf_tabs.setCurrentIndex(2)
        w.pdf_more_tabs.setCurrentIndex(1)
        buttons = (w.pdf_image_mode_button, w.pdf_export_mode_button)
        def geometry():
            return [(x.mapTo(w, QPoint(0, 0)), x.size()) for x in (*buttons, w.pdf_convert_stack)]
        for size in ((1180, 720), (1280, 820)):
            w.resize(*size); self.qt.processEvents(); before = geometry()
            for index in (1, 0, 0, 1):
                buttons[index].click(); self.qt.processEvents()
                self.assertEqual(w.pdf_convert_stack.currentIndex(), index)
                self.assertEqual([x.isChecked() for x in buttons], [index == 0, index == 1])
                self.assertEqual(geometry(), before)

    def test_password_fields_do_not_overlap_at_small_window_size(self):
        w = self.window
        w.show_pdf_tool(); w.pdf_tabs.setCurrentIndex(2)
        w.pdf_more_tabs.setCurrentIndex(2)
        self.qt.processEvents()
        pairs = [(w.pdf_new_password_label, w.pdf_new_password_edit),
                 (w.pdf_confirm_password_label, w.pdf_confirm_password_edit)]
        for label, field in pairs:
            self.assertGreaterEqual(field.height(), 32)
            self.assertFalse(label.geometry().intersects(field.geometry()))

    def test_deduplication_columns_are_only_shown_when_needed(self):
        w = self.window; w.show_cleanup_tool(); self.qt.processEvents()
        self.assertFalse(w.cleanup_columns_tree.isVisible())
        w.cleanup_deduplicate_checkbox.setChecked(True); self.qt.processEvents()
        self.assertTrue(w.cleanup_columns_tree.isVisible())
        w.cleanup_deduplicate_checkbox.setChecked(False); self.qt.processEvents()
        self.assertFalse(w.cleanup_columns_tree.isVisible())

    def test_watermark_type_only_shows_relevant_fields(self):
        w = self.window; w.show_pdf_tool(); w.pdf_tabs.setCurrentIndex(1)
        pdf = w.pdf_workspace; pdf.tool_tabs.setCurrentIndex(1)
        pdf.watermark_kind.setCurrentIndex(1); self.qt.processEvents()
        self.assertTrue(pdf.watermark_text.isVisible())
        self.assertFalse(pdf.watermark_image_button.isVisible())
        pdf.watermark_kind.setCurrentIndex(2); self.qt.processEvents()
        self.assertFalse(pdf.watermark_text.isVisible())
        self.assertTrue(pdf.watermark_image_button.isVisible())

    def test_settings_credential_fields_have_usable_width(self):
        with patch('ocr_settings_dialog.load_credentials', return_value={}):
            dialog = SoftwareSettingsDialog(parent=self.window)
        dialog.show(); self.qt.processEvents()
        try:
            for field in dialog._fields['baidu']:
                self.assertGreaterEqual(field.width(), 320)
        finally:
            dialog.close()

    def test_classification_source_field_uses_available_space(self):
        w = self.window; w.show_split_tool(); w.split_mode_tabs.setCurrentIndex(1)
        self.qt.processEvents()
        self.assertGreaterEqual(w.category_split_page.source_edit.width(), 320)

    def test_document_progress_is_visible_before_result_exists(self):
        w = self.window; w.show_document_tool(); self.qt.processEvents()
        self.assertFalse(w.document_result_path_edit.text())
        self.assertTrue(w.document_status_label.isVisible())

    def test_scrolling_form_does_not_cover_the_page_heading(self):
        w = self.window; w.show_cleanup_tool(); self.qt.processEvents()
        title = next(label for label in w.cleanup_page.findChildren(QLabel)
                     if label.property('role') == 'title')
        title_bottom = title.mapTo(w, QPoint(0, title.height())).y()
        source_top = w.cleanup_source_path_edit.mapTo(w, QPoint(0, 0)).y()
        self.assertGreater(source_top, title_bottom + 30)


if __name__ == '__main__':
    unittest.main()
