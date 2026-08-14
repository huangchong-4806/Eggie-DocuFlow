import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from PySide6.QtWidgets import QApplication
from pypdf import PdfReader, PdfWriter

import pdf_toolbox

from pdf_toolbox import (
    COMPRESSION_PRESETS,
    PdfPageRef,
    add_pdf_marks,
    compress_pdf,
    compare_pdf_text,
    estimate_compressed_size,
    images_to_pdf,
    is_supported_image_file,
    output_path,
    make_searchable_pdf,
    pdf_to_images,
    pdfs_to_images,
    save_pages,
    secure_pdf,
)
from api_layer.models import DocumentExtraction, PageText, TextBlock


class PdfToolboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def make_pdf(self, filename, page_count):
        path = self.root / filename
        writer = PdfWriter()
        for index in range(page_count):
            writer.add_blank_page(width=200 + index, height=300 + index)
        with path.open("wb") as handle:
            writer.write(handle)
        return path

    def test_save_pages_reorders_rotates_and_opens(self):
        pdf_file = self.make_pdf("source.pdf", 3)
        result = save_pages(
            [
                PdfPageRef(str(pdf_file), 2),
                PdfPageRef(str(pdf_file), 0, 90),
            ],
            self.root / "sorted.pdf",
        )

        reader = PdfReader(result.output_file)
        self.assertEqual(len(reader.pages), 2)
        self.assertEqual(reader.pages[1].get("/Rotate"), 90)
        self.assertTrue(Path(result.log_file).is_file())

    def test_save_pages_uses_custom_name_and_opens(self):
        first = self.make_pdf("a.pdf", 1)
        second = self.make_pdf("b.pdf", 2)
        output_file = output_path(self.root, "客户修改后的名字", "PDF合并结果.pdf")
        result = save_pages(
            [
                PdfPageRef(str(first), 0),
                PdfPageRef(str(second), 0),
                PdfPageRef(str(second), 1),
            ],
            output_file,
        )

        self.assertEqual(Path(result.output_file).name, "客户修改后的名字.pdf")
        self.assertEqual(len(PdfReader(result.output_file).pages), 3)

    def test_save_pages_log_uses_actual_non_duplicate_output(self):
        pdf_file = self.make_pdf("source.pdf", 1)
        (self.root / "已有文件.pdf").write_bytes(b"occupied")

        result = save_pages(
            [PdfPageRef(str(pdf_file), 0)],
            self.root / "已有文件.pdf",
        )

        self.assertEqual(Path(result.output_file).name, "已有文件_1.pdf")
        self.assertIn(result.output_file, Path(result.log_file).read_text(encoding="utf-8"))

    def test_compress_pdf_writes_openable_pdf(self):
        pdf_file = self.make_pdf("compress.pdf", 1)
        for preset in COMPRESSION_PRESETS:
            result = compress_pdf(pdf_file, self.root / f"compressed_{preset}.pdf", preset)

            self.assertEqual(len(PdfReader(result.output_file).pages), 1)
            self.assertGreater(result.output_size, 0)
            self.assertTrue(Path(result.log_file).is_file())

        low, high = estimate_compressed_size(1000, "standard")
        self.assertLess(low, high)

    def test_compress_pdf_handles_existing_content_streams(self):
        source = Path(__file__).resolve().parents[1] / "test_files" / "表格测试.pdf"

        result = compress_pdf(source, self.root / "content-streams.pdf")

        self.assertEqual(len(PdfReader(result.output_file).pages), 1)
        self.assertGreater(result.output_size, 0)

    def test_images_to_pdf_and_pdf_to_images_open(self):
        image_files = []
        for index, color in enumerate(("red", "blue"), 1):
            image_file = self.root / f"{index}.png"
            Image.new("RGB", (40, 50), color).save(image_file)
            image_files.append(image_file)

        pdf_result = images_to_pdf(image_files, self.root / "images.pdf")
        self.assertEqual(len(PdfReader(pdf_result.output_file).pages), 2)

        image_result = pdf_to_images(pdf_result.output_file, self.root / "pages")
        self.assertEqual(len(image_result.image_files), 2)
        self.assertEqual(Path(image_result.image_files[0]).suffix, ".jpg")
        self.assertEqual(Path(image_result.image_files[0]).name, "images_1.jpg")
        self.assertEqual(Path(image_result.image_files[1]).name, "images_2.jpg")
        self.assertEqual(Path(image_result.image_files[0]).parent.name, "images")
        with Image.open(image_result.image_files[0]) as image:
            self.assertGreaterEqual(image.width, 160)
            self.assertGreaterEqual(image.height, 200)
        log_text = Path(image_result.log_file).read_text(encoding="utf-8")
        self.assertIn("页面呈现方式：", log_text)
        self.assertIn("状态=已生成", log_text)
        self.assertIn("像素=", log_text)

    def test_single_page_pdf_outputs_directly_with_high_resolution(self):
        pdf_file = self.make_pdf("单页文件.pdf", 1)

        result = pdf_to_images(pdf_file, self.root / "single", "png", 300)

        self.assertEqual(len(result.image_files), 1)
        output_file = Path(result.image_files[0])
        self.assertEqual(output_file.parent, (self.root / "single").resolve())
        self.assertEqual(output_file.name, "单页文件_1.png")
        with Image.open(output_file) as image:
            self.assertGreaterEqual(image.width, 830)
            self.assertGreaterEqual(image.height, 1240)

    def test_batch_pdf_to_images_continues_after_one_failure(self):
        single = self.make_pdf("单页.pdf", 1)
        multiple = self.make_pdf("多页.pdf", 2)
        broken = self.root / "损坏.pdf"
        broken.write_text("not a pdf", encoding="utf-8")

        result = pdfs_to_images(
            [single, multiple, broken, single],
            self.root / "batch",
            "jpg",
            300,
        )

        self.assertEqual(len(result.source_files), 2)
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(len(result.image_files), 3)
        self.assertTrue((self.root / "batch" / "单页_1.jpg").is_file())
        self.assertTrue((self.root / "batch" / "多页" / "多页_1.jpg").is_file())
        self.assertTrue((self.root / "batch" / "多页" / "多页_2.jpg").is_file())
        log_text = Path(result.log_file).read_text(encoding="utf-8")
        self.assertIn("图片清晰度：300 DPI", log_text)
        self.assertIn("失败文件数：1", log_text)
        self.assertIn("损坏.pdf", log_text)
        self.assertIn("页面呈现方式=", log_text)
        self.assertIn("状态=已生成", log_text)

    def test_batch_pdf_to_images_reports_file_and_page_progress(self):
        pdf_file = self.make_pdf("进度测试.pdf", 2)
        updates = []

        result = pdfs_to_images(
            [pdf_file],
            self.root / "progress",
            "png",
            150,
            progress_callback=lambda value, total, message: updates.append(
                (value, total, message)
            ),
        )

        self.assertEqual(len(result.image_files), 2)
        self.assertEqual(updates[0][:2], (0, 1))
        self.assertEqual(updates[-1][:2], (1, 1))
        self.assertTrue(any("第 2 / 2 页" in message for _, _, message in updates))

    def test_batch_pdf_to_images_removes_partial_output_after_page_failure(self):
        multiple = self.make_pdf("中途失败.pdf", 2)
        original_save = Image.Image.save
        save_calls = {"count": 0}

        def fail_on_second_page(image, output_file, *args, **kwargs):
            save_calls["count"] += 1
            if save_calls["count"] == 2:
                raise OSError("模拟第二页保存失败")
            return original_save(image, output_file, *args, **kwargs)

        with patch.object(Image.Image, "save", fail_on_second_page):
            result = pdfs_to_images(
                [multiple],
                self.root / "partial",
                "jpg",
                150,
            )

        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.image_files, ())
        self.assertFalse((self.root / "partial" / "中途失败").exists())
        self.assertEqual(list((self.root / "partial").glob("**/*.jpg")), [])

    def test_image_filter_rejects_non_images(self):
        real_image = self.root / "real.jpg"
        fake_image = self.root / "fake.jpg"
        note = self.root / "note.txt"
        Image.new("RGB", (10, 10), "white").save(real_image)
        fake_image.write_text("not an image", encoding="utf-8")
        note.write_text("hello", encoding="utf-8")

        self.assertTrue(is_supported_image_file(real_image))
        self.assertFalse(is_supported_image_file(fake_image))
        self.assertFalse(is_supported_image_file(note))

    def test_prepare_image_thumbnail_creates_small_preview(self):
        source = self.root / "large.png"
        destination = self.root / "preview.jpg"
        Image.new("RGB", (1600, 900), "blue").save(source)

        preview = pdf_toolbox.prepare_image_thumbnail(
            source,
            destination,
            (132, 180),
        )

        self.assertEqual(Path(preview), destination.resolve())
        with Image.open(preview) as image:
            self.assertLessEqual(image.width, 132)
            self.assertLessEqual(image.height, 180)

    def test_pdf_marks_add_watermark_and_page_numbers(self):
        source = self.make_pdf("marks.pdf", 2)

        result = add_pdf_marks(
            source,
            self.root / "marked.pdf",
            watermark_text="内部资料",
            add_page_numbers=True,
            page_number_start=5,
        )

        reader = PdfReader(result.output_file)
        self.assertEqual(len(reader.pages), 2)
        extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn("内部资料", extracted)
        self.assertIn("5", extracted)
        self.assertIn("页码：已添加", Path(result.log_file).read_text(encoding="utf-8"))

    def test_pdf_password_can_be_set_and_removed(self):
        source = self.make_pdf("plain.pdf", 1)
        protected = secure_pdf(source, self.root / "protected.pdf", new_password="secret-123")
        protected_reader = PdfReader(protected.output_file)
        self.assertTrue(protected_reader.is_encrypted)
        self.assertFalse(protected_reader.decrypt("wrong"))
        self.assertTrue(protected_reader.decrypt("secret-123"))

        unprotected = secure_pdf(
            protected.output_file,
            self.root / "unprotected.pdf",
            source_password="secret-123",
        )
        self.assertFalse(PdfReader(unprotected.output_file).is_encrypted)
        log_text = Path(unprotected.log_file).read_text(encoding="utf-8")
        self.assertNotIn("secret-123", log_text)
        self.assertIn("密码写入日志：否", log_text)

    @patch("api_layer.document.extract_document")
    def test_searchable_pdf_keeps_page_and_adds_text_layer(self, extract_document_mock):
        source = self.make_pdf("scan.pdf", 1)
        extract_document_mock.return_value = DocumentExtraction(
            source_file=str(source),
            provider="baidu",
            pages=(
                PageText(
                    1,
                    "Searchable Text",
                    "cloud_ocr",
                    blocks=(TextBlock("Searchable Text", (0.1, 0.1, 0.6, 0.2)),),
                    width=200,
                    height=300,
                ),
            ),
            started_at="2026-08-07T12:00:00",
        )

        result = make_searchable_pdf(
            source,
            self.root / "searchable.pdf",
            "baidu",
        )

        reader = PdfReader(result.output_file)
        self.assertEqual(len(reader.pages), 1)
        extracted = " ".join(reader.pages[0].extract_text().split())
        self.assertIn("Searchable Text", extracted)
        self.assertIn("云 OCR 页：1", Path(result.log_file).read_text(encoding="utf-8"))

    def test_pdf_text_compare_writes_openable_html_report(self):
        project_root = Path(__file__).resolve().parents[1]
        left = project_root / "test_files" / "合同测试.pdf"
        right = project_root / "test_files" / "表格测试.pdf"

        result = compare_pdf_text(left, right, self.root / "compare.html")

        report = Path(result.output_file).read_text(encoding="utf-8")
        self.assertIn("合同测试.pdf", report)
        self.assertIn("表格测试.pdf", report)
        self.assertIn("diff_add", report)
        self.assertIn("仅本机逐行比较", Path(result.log_file).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
