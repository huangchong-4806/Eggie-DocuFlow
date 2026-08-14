import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api_layer.models import PdfInspection
from batch_processing_tool import (
    discover_pdf_files,
    inspect_pdf_files,
    process_pdf_files,
)


class BatchProcessingToolTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_discovery_can_include_subfolders(self):
        (self.root / "a.pdf").write_bytes(b"pdf")
        (self.root / "ignore.txt").write_text("text", encoding="utf-8")
        child = self.root / "child"
        child.mkdir()
        (child / "b.PDF").write_bytes(b"pdf")

        self.assertEqual([path.name for path in discover_pdf_files(self.root)], ["a.pdf"])
        self.assertEqual(
            [path.name for path in discover_pdf_files(self.root, recursive=True)],
            ["a.pdf", "b.PDF"],
        )

    @patch("batch_processing_tool.inspect_pdf")
    def test_inspection_marks_scanned_pages_and_keeps_invalid_file(self, mocked):
        first = self.root / "first.pdf"
        second = self.root / "second.pdf"
        mocked.side_effect = [
            PdfInspection(str(first), 3, (2,)),
            ValueError("损坏文件"),
        ]

        previews = inspect_pdf_files([first, second])

        self.assertEqual(previews[0].scanned_page_count, 1)
        self.assertIn("可选云 OCR", previews[0].suggested_action)
        self.assertIn("损坏文件", previews[1].error_message)

    @patch("batch_processing_tool.BatchEngine")
    def test_processing_writes_summary_log_without_secret_values(self, engine_class):
        source = self.root / "one.pdf"
        output = self.root / "output"
        engine_class.return_value.process_files.return_value = [
            {
                "doc_type": "CONTRACT",
                "data": {"source_file": str(source)},
                "output_file": str(output / "one.docx"),
                "status": "success",
            }
        ]

        result = process_pdf_files([source], output, use_ocr=True, provider_name="baidu")

        self.assertEqual(len(result.successful), 1)
        log_text = Path(result.log_file).read_text(encoding="utf-8")
        self.assertIn("成功数量：1", log_text)
        self.assertIn("OCR 平台：baidu", log_text)
        self.assertNotIn("API_KEY", log_text)


if __name__ == "__main__":
    unittest.main()
