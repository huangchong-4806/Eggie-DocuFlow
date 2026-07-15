import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader, PdfWriter

import pdf_toolbox

from pdf_toolbox import (
    COMPRESSION_PRESETS,
    PdfPageRef,
    compress_pdf,
    estimate_compressed_size,
    images_to_pdf,
    is_supported_image_file,
    output_path,
    pdf_to_images,
    pdfs_to_images,
    save_pages,
)


class PdfToolboxTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
