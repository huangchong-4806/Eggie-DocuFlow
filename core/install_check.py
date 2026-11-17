"""Offline checks for the update verifier and document engines in a frozen app."""
import base64
import json
from io import BytesIO

from eggie_update_feed import verify_manifest
from update_check import Release, UpdateCheckError


def _check_update_signature():
    # A fixed manifest signed once with a disposable test key. It is never installed
    # as an update trust anchor. Keep the exact signed bytes independent of this build.
    payload = (
        b'{"schema":1,"target":{"version":"0.0.0","build":"0000000000"},"assets":['
        b'{"platform":"windows-x64","kind":"full","base":null,"filename":"check.exe","size":1,'
        b'"sha256":"' + b'0' * 64 +
        b'","url":"https://github.com/huangchong-4806/Eggie-DocuFlow/releases/download/v0.0.0/check.exe"}]}'
    )
    envelope = json.dumps({
        "payload": base64.b64encode(payload).decode("ascii"),
        "signature": "WSONGMcSvyEZYneiswo9MyR+Fu9iI7Hevq0mfqHNYndSxsbPUVPJ88G8oqjuLVwxoQIWgG7nAGZKgtaHbeoMBA==",
    }).encode("ascii")
    public_key = bytes.fromhex("d80fba3dc1aa73431a84f08b39c1bfbd5a476cf3b1cfc31046ede7345d75d3e5")
    try:
        verify_manifest(envelope, public_key, Release("0.0.0", "0000000000"))
    except (ImportError, OSError, UpdateCheckError) as error:
        raise RuntimeError("Update signature self-check failed (Ed25519)") from error


def check_install():
    _check_update_signature()

    from openpyxl import Workbook, load_workbook
    from PIL import Image
    from pypdf import PdfReader
    import pdfplumber
    import pymupdf
    import pypdfium2

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
