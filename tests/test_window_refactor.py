"""Window event dispatch and resource lookup after moving page methods."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPoint, QPointF, QSettings, QSize, Qt, QUrl
from PySide6.QtGui import QCloseEvent, QDragEnterEvent, QDropEvent, QResizeEvent
from PySide6.QtWidgets import QApplication

from app import ExcelMergerWindow, resource_path


class WindowRefactorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        settings = QSettings(str(self.root / "settings.ini"), QSettings.IniFormat)
        with patch("app.QSettings", return_value=settings):
            self.window = ExcelMergerWindow()

    def tearDown(self):
        with patch("app.QMessageBox.warning"):
            self.assertTrue(self.window.close())
        self.window.pdf_thumbnail_tempdir.cleanup()

    def test_invalid_drop_payloads_reach_the_qt_parent_without_changing_pages(self):
        for urls in ([], [QUrl.fromLocalFile(str(self.root / "note.txt"))],
                     [QUrl("https://example.invalid/document.pdf")]):
            with self.subTest(urls=urls):
                mime = QMimeData()
                mime.setUrls(urls)
                drag = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, mime,
                                       Qt.LeftButton, Qt.NoModifier)
                drop = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime,
                                  Qt.LeftButton, Qt.NoModifier)
                self.window.dragEnterEvent(drag)
                self.window.dropEvent(drop)
                self.assertFalse(drag.isAccepted())
                self.assertFalse(drop.isAccepted())
                self.assertEqual(self.window.document_source_file, "")
                self.assertIs(self.window.stack.currentWidget(), self.window.home_page)

    def test_pdf_drop_keeps_the_existing_document_navigation(self):
        source = str(self.root / "source.pdf")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(source)])
        drag = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, mime,
                               Qt.LeftButton, Qt.NoModifier)
        drop = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime,
                          Qt.LeftButton, Qt.NoModifier)
        self.window.dragEnterEvent(drag)
        with patch.object(self.window, "set_document_source_file", return_value=True) as load:
            self.window.dropEvent(drop)
        load.assert_called_once_with(source)
        self.assertTrue(drag.isAccepted())
        self.assertTrue(drop.isAccepted())
        self.assertIs(self.window.stack.currentWidget(), self.window.document_page)

    def test_resize_and_idle_close_still_call_qt_parent_methods(self):
        event = QResizeEvent(QSize(1280, 820), QSize(1180, 720))
        self.window.resizeEvent(event)
        closed = QCloseEvent()
        self.window.closeEvent(closed)
        self.assertTrue(closed.isAccepted())

    def test_resource_paths_work_from_source_and_frozen_bundle(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(resource_path("assets/app_icon.png"), root / "assets/app_icon.png")
        self.assertTrue(resource_path("docs/OCR使用说明.pdf").is_file())
        with patch("ui.app_support.sys._MEIPASS", str(self.root), create=True):
            self.assertEqual(resource_path("assets/app_icon.png"), self.root / "assets/app_icon.png")


if __name__ == "__main__":
    unittest.main()
