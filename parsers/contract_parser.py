import re


PAGE_HEADING = re.compile(r"^=== 第 (\d+) 页 ===$")


def parse_contract(text_file):
    wrote_content = False
    pending_blank = False
    with open(text_file, encoding="utf-8") as source:
        for line in source:
            value = re.sub(r"[ \t]+", " ", line.rstrip("\r\n")).strip()
            if PAGE_HEADING.fullmatch(value.strip()):
                if wrote_content:
                    yield "page_break", ""
                pending_blank = False
                continue
            if not value.strip():
                pending_blank = wrote_content
                continue
            if pending_blank:
                yield "blank", ""
            yield "paragraph", value
            wrote_content = True
            pending_blank = False
