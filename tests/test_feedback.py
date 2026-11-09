import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from ui.feedback import DEFAULT_FEEDBACK_CHANNEL, normalize_feedback_channel


class FeedbackChannelTests(unittest.TestCase):
    def test_default_email_blank_and_questionnaire_are_accepted(self):
        self.assertEqual(normalize_feedback_channel(""), DEFAULT_FEEDBACK_CHANNEL)
        self.assertEqual(normalize_feedback_channel("  "), DEFAULT_FEEDBACK_CHANNEL)
        self.assertEqual(normalize_feedback_channel("448223855@qq.com"), "mailto:448223855@qq.com")
        self.assertEqual(
            normalize_feedback_channel("mailto:448223855@qq.com"),
            "mailto:448223855@qq.com",
        )
        self.assertEqual(
            normalize_feedback_channel("https://jinshuju.net/f/example"),
            "https://jinshuju.net/f/example",
        )
        self.assertEqual(
            normalize_feedback_channel("http://wj.qq.com/s2/1.html"),
            "http://wj.qq.com/s2/1.html",
        )

    def test_github_and_invalid_values_are_rejected(self):
        for value in (
            "https://github.com/huangchong-4806/Eggie-DocuFlow/issues",
            "https://gist.github.com/x",
            "not an address",
            "mailto:not-an-email",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_feedback_channel(value)


class FeedbackEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_sidebar_opens_the_default_mailbox_and_settings_can_switch_channel(self):
        from app import ExcelMergerWindow
        from ocr_settings_dialog import SoftwareSettingsDialog

        window = ExcelMergerWindow()
        self.addCleanup(window.close)
        window.settings.remove("feedback/channel")
        self.assertEqual(window.feedback_channel(), DEFAULT_FEEDBACK_CHANNEL)
        self.assertNotIn("feedback", window.nav_buttons)
        button = next(item for item in window.findChildren(QPushButton) if item.text() == "反馈")
        with patch("app.QDesktopServices.openUrl") as open_url:
            button.click()
        self.assertEqual(open_url.call_args.args[0].toString(), DEFAULT_FEEDBACK_CHANNEL)

        dialog = SoftwareSettingsDialog(parent=window, feedback_channel="https://jinshuju.net/f/example")
        texts = [label.text() for label in dialog.findChildren(QLabel)]
        self.assertTrue(any("不会上传业务文件" in text for text in texts))
        self.assertTrue(any("448223855@qq.com" in text for text in texts))
        self.assertNotIn("github.com", " ".join(texts).lower())
        dialog.feedback_edit.setText("https://github.com/example/issues")
        with patch("ocr_settings_dialog.QMessageBox.warning") as warning:
            dialog.accept()
        warning.assert_called_once()
        self.assertFalse(dialog.result())
        dialog.feedback_edit.setText("https://wj.qq.com/s2/1.html")
        dialog.accept()
        window.save_feedback_channel(dialog.feedback_channel)
        self.assertEqual(window.feedback_channel(), "https://wj.qq.com/s2/1.html")
        window.settings.remove("feedback/channel")
