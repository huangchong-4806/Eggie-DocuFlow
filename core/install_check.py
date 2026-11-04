"""Offline check for the parsers and native libraries included in a frozen app."""
from io import BytesIO
from openpyxl import Workbook, load_workbook
from PIL import Image
from pypdf import PdfReader
import pdfplumber
import pymupdf
import pypdfium2


def check_install():
    if (pymupdf.VersionBind, pymupdf.VersionFitz) != ("1.28.2", "1.28.5"):
        raise RuntimeError("Unexpected PDF engine")
    with pymupdf.open() as doc:
        doc.new_page().insert_text((30, 60), "Release check")
        pdf = doc.tobytes()
    with pdfplumber.open(BytesIO(pdf)) as parsed, pypdfium2.PdfDocument(pdf) as rendered:
        if (parsed.pages[0].extract_text() != "Release check"
                or len(PdfReader(BytesIO(pdf)).pages) != 1 or len(rendered) != 1):
            raise RuntimeError("PDF parser check failed")
        page = rendered[0]
        try:
            bitmap = page.render(scale=0.25)
            try:
                png = BytesIO()
                bitmap.to_pil().save(png, format="PNG")
                png.seek(0)
                with Image.open(png) as image:
                    image.load()
                    if image.width < 1:
                        raise RuntimeError("Image decoding check failed")
            finally:
                bitmap.close()
        finally:
            page.close()
    book = Workbook()
    book.active["A1"] = "00001234567890123456"
    stream = BytesIO()
    book.save(stream)
    book.close()
    stream.seek(0)
    check = load_workbook(stream, read_only=True)
    try:
        if check.active["A1"].value != "00001234567890123456":
            raise RuntimeError("Workbook check failed")
    finally:
        check.close()
