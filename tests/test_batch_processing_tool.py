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

    def test_stale_pdf_is_unprocessed_and_valid_peer_is_saved_once(self):
        import shutil
        sample = Path(__file__).resolve().parents[1] / "test_files" / "表格测试.pdf"
        first = Path(shutil.copy(sample, self.root / "a.pdf"))
        second = Path(shutil.copy(sample, self.root / "b.pdf"))
        previews = inspect_pdf_files([first, second])
        first.write_bytes(b"replacement")
        with patch("batch_processing_tool._batch_log", side_effect=PermissionError("log")), patch("core.document_router.SessionLogger"):
            result = process_pdf_files([first, second], self.root / "out", expected_previews=previews)
        self.assertEqual((len(result.successful), len(result.unprocessed), len(result.failed)), (1, 1, 0))
        self.assertEqual(result.unprocessed[0]["data"]["source_file"], str(first.resolve()))
        self.assertTrue(Path(result.successful[0]["output_file"]).is_file())
        self.assertEqual(result.log_file, "")
        self.assertIn("日志未写入", result.warning)

    def test_queue_log_failure_and_uncertain_output_cannot_replay_worker(self):
        from unittest.mock import Mock
        from layout_batch.queue_system import TaskQueue
        output = self.root / "completed.txt"
        output.write_text("result")
        for status in ("success", "failed"):
            worker = Mock(return_value={"status": status, "output_file": str(output)})
            queue = TaskQueue(worker, max_retries=2)
            with patch.object(queue, "_write_log", side_effect=PermissionError("log")):
                item, = queue.run([str(self.root / "a.pdf")])
            worker.assert_called_once()
            self.assertEqual(item["output_file"], str(output))
            self.assertIn("日志未写入", item["data"]["warning"])
            if status == "failed":
                self.assertFalse(item["data"]["retryable"])


if __name__ == "__main__":
    unittest.main()
