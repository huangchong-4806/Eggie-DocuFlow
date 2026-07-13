import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from app import ClearSpinBox, ExcelMergerWindow


class AppNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = ExcelMergerWindow()

    def tearDown(self):
        self.window.close()
        self.window.pdf_thumbnail_tempdir.cleanup()

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


if __name__ == "__main__":
    unittest.main()
