import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from utils.file_helper import INVALID_XML_CHARS, publish_output, temporary_output


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
DOC_START = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>"""
DOC_END = """<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>"""
PARAGRAPH_SPACING = '<w:pPr><w:spacing w:before="0" w:after="0"/></w:pPr>'
COMPACT_BLANK_SPACING = (
    '<w:pPr><w:spacing w:before="0" w:after="0" '
    'w:line="60" w:lineRule="exact"/></w:pPr>'
)


def export_contract(elements, output_file, work_folder):
    document_xml = Path(work_folder) / "document.xml"
    with open(document_xml, "w", encoding="utf-8") as document:
        document.write(DOC_START)
        for element_type, value in elements:
            if element_type == "page_break":
                document.write('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
            elif element_type == "blank":
                document.write(f"<w:p>{COMPACT_BLANK_SPACING}</w:p>")
            else:
                value = escape(INVALID_XML_CHARS.sub("", value))
                document.write(
                    f'<w:p>{PARAGRAPH_SPACING}<w:r><w:t xml:space="preserve">'
                    f"{value}</w:t></w:r></w:p>"
                )
        document.write(DOC_END)

    temporary_file = temporary_output(output_file)
    try:
        with zipfile.ZipFile(temporary_file, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", CONTENT_TYPES)
            archive.writestr("_rels/.rels", ROOT_RELS)
            archive.write(document_xml, "word/document.xml")
        return publish_output(temporary_file, output_file)
    finally:
        Path(temporary_file).unlink(missing_ok=True)
