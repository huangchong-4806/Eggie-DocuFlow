import tempfile
import unittest
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter

from pdf_toolbox import (
    COMPRESSION_PRESETS,
    PdfPageRef,
    compress_pdf,
    estimate_compressed_size,
    images_to_pdf,
    is_supported_image_file,
    output_path,
    pdf_to_images,
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
        with Image.open(image_result.image_files[0]) as image:
            self.assertGreater(image.width, 0)
            self.assertGreater(image.height, 0)

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


if __name__ == "__main__":
    unittest.main()
