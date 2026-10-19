"""Local PDF workspace state. PDF engine objects never leave their worker process."""

from dataclasses import dataclass, field, replace
from pathlib import Path
from collections import Counter
import math
import io
import re
import sys
from uuid import uuid4


Rect = tuple[float, float, float, float]


class WorkspaceError(ValueError):
    """Safe, user-facing validation message (never raw PDF parser output)."""


@dataclass(frozen=True)
class WorkspacePage:
    page_id: str
    source_id: str
    source_index: int
    rotation: int = 0


@dataclass(frozen=True)
class RedactionMark:
    mark_id: str
    page_id: str
    rects: tuple[Rect, ...]
    mode: str = "area"
    applied: bool = False


@dataclass(frozen=True)
class PageScope:
    ranges: str = ""
    skip_first: bool = False


@dataclass(frozen=True)
class WatermarkOptions:
    kind: str = "none"
    text: str = "内部资料"
    image_id: str = ""
    angle: int = -32
    tiled: bool = False
    size: float = 100.0  # Percentage, matching the approved UI.
    opacity: float = 0.18
    spacing: float = 120.0
    scope: PageScope = field(default_factory=PageScope)


@dataclass(frozen=True)
class NumberOptions:
    enabled: bool = False
    style: str = "plain"
    start: int = 1
    position: str = "bottom_center"
    scope: PageScope = field(default_factory=PageScope)


@dataclass
class WorkspaceState:
    pages: list[WorkspacePage] = field(default_factory=list)
    marks: list[RedactionMark] = field(default_factory=list)
    watermark: WatermarkOptions = field(default_factory=WatermarkOptions)
    numbers: NumberOptions = field(default_factory=NumberOptions)


def pending_count(state: WorkspaceState) -> int:
    return sum(not mark.applied for mark in state.marks)


def marks_with_state(marks: list[RedactionMark], applied: bool) -> list[RedactionMark]:
    return [replace(mark, applied=applied) for mark in marks]


def resolve_pages(scope: PageScope, count: int) -> tuple[int, ...]:
    if type(count) is not int or count <= 0:
        raise WorkspaceError("没有可处理的页面。")
    selected = set()
    if not scope.ranges.strip():
        selected.update(range(count))
    else:
        for part in scope.ranges.split(","):
            match = re.fullmatch(r"\s*([0-9]+)(?:\s*-\s*([0-9]+))?\s*", part)
            if not match:
                raise WorkspaceError("页码范围格式错误，请使用 1-3,5。")
            start = int(match[1])
            end = int(match[2] or match[1])
            if not 1 <= start <= end <= count:
                raise WorkspaceError(f"页码范围必须位于 1 到 {count} 之间，且不能倒序。")
            selected.update(range(start - 1, end))
    if scope.skip_first:
        selected.discard(0)
    if not selected:
        raise WorkspaceError("当前范围没有选中页面，请调整页码或取消跳过首页。")
    return tuple(sorted(selected))


def number_label(options: NumberOptions, ordinal: int, total: int) -> str:
    if type(options.start) is not int or options.start < 0:
        raise WorkspaceError("起始页码必须是非负整数。")
    if type(ordinal) is not int or type(total) is not int or not 0 <= ordinal < total:
        raise WorkspaceError("页码位置或总页数无效。")
    number = options.start + ordinal
    labels = {
        "plain": str(number), "dash": f"— {number} —", "chinese": f"第 {number} 页",
        "fraction": f"{number} / {total}", "chinese_total": f"第 {number} 页，共 {total} 页",
    }
    if options.style not in labels:
        raise WorkspaceError("页码样式无效。")
    return labels[options.style]


def watermark_boxes(width, height, item_width, item_height, spacing, tiled):
    if not all(math.isfinite(value) and value > 0 for value in (width, height, item_width, item_height)) or not math.isfinite(spacing) or spacing < 0:
        raise WorkspaceError("水印尺寸或间距无效。")
    if not tiled:
        x, y = (width - item_width) / 2, (height - item_height) / 2
        return ((x, y, x + item_width, y + item_height),)
    columns = math.ceil(width / 2 / (item_width + spacing))
    rows = math.ceil(height / 2 / (item_height + spacing))
    boxes = []
    for row in range(-rows, rows + 1):
        for column in range(-columns, columns + 1):
            x = (width - item_width) / 2 + column * (item_width + spacing)
            y = (height - item_height) / 2 + row * (item_height + spacing)
            if x < width and y < height and x + item_width > 0 and y + item_height > 0:
                boxes.append((x, y, x + item_width, y + item_height))
    return tuple(boxes)


def _page_chars(page):
    chars = []
    for block_index, block in enumerate(page.get_text("rawdict", flags=0)["blocks"]):
        for line_index, line in enumerate(block.get("lines", ())):
            for span in line["spans"]:
                for char in span["chars"]:
                    chars.append({
                        "text": char["c"], "bbox": tuple(char["bbox"]),
                        "line_id": f"{block_index}:{line_index}", "char_id": len(chars),
                    })
    return tuple(chars)


def _has_alternate_text(data):
    from pypdf.generic import NameObject

    # Inspect complete objects as well as decoded streams, including nested Properties.
    # PDF names may spell /Alt as /A#6Ct; raw keyword searches are not sufficient.
    for token in re.findall(rb"/[^\x00\t\n\f\r ()<>\[\]{}/%]+", data):
        if NameObject.unnumber(token) in (b"/Alt", b"/ActualText"):
            return True
    return False


class PdfWorkspaceEngine:
    """Own immutable source documents in one process; edit copies only."""

    def __init__(self):
        if sys.platform == "win32":
            # Qt ships the C++ runtime needed by PyMuPDF. Fresh workers must
            # load it too; DLLs loaded by the parent are not inherited on spawn.
            from PySide6 import QtCore  # noqa: F401
        import pymupdf

        self.pdf = pymupdf
        # Parser diagnostics can contain source text. Only safe errors reach the UI.
        pymupdf.TOOLS.mupdf_display_errors(False)
        pymupdf.TOOLS.mupdf_display_warnings(False)
        self._sources = {}
        self._images = {}
        self._font = None

    def open_pdf(self, path: str, password: str = "") -> tuple[WorkspacePage, ...]:
        source = str(Path(path).expanduser().resolve())
        document = None
        try:
            if Path(source).suffix.lower() != ".pdf":
                raise WorkspaceError("请选择 PDF 文件。")
            snapshot = Path(source).read_bytes()
            document = self.pdf.open(stream=snapshot, filetype="pdf")
            if document.needs_pass and not document.authenticate(password):
                raise WorkspaceError("PDF 已加密，请使用正确的原密码。")
            if not 1 <= len(document) <= 1000:
                raise WorkspaceError("单次支持 1 到 1,000 页，请先拆分文件。")
        except Exception as error:
            if document is not None:
                document.close()
            if isinstance(error, WorkspaceError) and not isinstance(error, self.pdf.FileDataError):
                raise
            raise WorkspaceError("PDF 无法读取，请检查文件是否损坏或不可访问。") from None
        # Each explicit open gets a fresh snapshot; undo references keep their old one.
        source_id = uuid4().hex
        self._sources[source_id] = document
        return tuple(WorkspacePage(uuid4().hex, source_id, index)
                     for index in range(len(self._sources[source_id])))

    def _copy_page(self, ref):
        source = self._sources.get(ref.source_id)
        if source is None or type(ref.source_index) is not int or not 0 <= ref.source_index < len(source):
            raise WorkspaceError("页面来源无效，请重新打开 PDF。")
        if type(ref.rotation) is not int or ref.rotation % 90:
            raise WorkspaceError("页面旋转必须是 90 度的整数倍。")
        document = self.pdf.open()
        try:
            document.insert_pdf(source, from_page=ref.source_index, to_page=ref.source_index)
            page = document[0]
            page.set_rotation((page.rotation + ref.rotation) % 360)
            return document
        except Exception:
            document.close()
            raise

    def render_page(self, state: WorkspaceState, page_id: str, max_pixels: int = 1600) -> dict:
        ref = next((page for page in state.pages if page.page_id == page_id), None)
        if ref is None:
            raise WorkspaceError("页面不存在。")
        if type(max_pixels) is not int or not 64 <= max_pixels <= 4096:
            raise WorkspaceError("预览尺寸必须位于 64 到 4096 像素之间。")
        self._validate_state(state)
        with self._edited_page(state, ref) as document:
            page = document[0]
            chars = _page_chars(page)
            self._decorate_page(page, state, state.pages.index(ref))
            scale = max_pixels / max(page.rect.width, page.rect.height)
            return {
                "page_id": page_id,
                "png": page.get_pixmap(matrix=self.pdf.Matrix(scale, scale), alpha=False).tobytes("png"),
                "width_pt": page.rect.width, "height_pt": page.rect.height,
                "source_to_view": tuple(page.rotation_matrix), "chars": chars,
            }

    def _validate_state(self, state):
        if not 1 <= len(state.pages) <= 1000:
            raise WorkspaceError("工作区需要 1 到 1,000 页。")
        refs = {ref.page_id: ref for ref in state.pages}
        if len(refs) != len(state.pages) or len({mark.mark_id for mark in state.marks}) != len(state.marks):
            raise WorkspaceError("页面或密文标记编号重复。")
        bounds = {}
        for ref in state.pages:
            source = self._sources.get(ref.source_id)
            if source is None or type(ref.source_index) is not int or not 0 <= ref.source_index < len(source):
                raise WorkspaceError("页面来源无效，请重新打开 PDF。")
            if type(ref.rotation) is not int or ref.rotation % 90:
                raise WorkspaceError("页面旋转必须是 90 度的整数倍。")
            page = source[ref.source_index]
            bounds[ref.page_id] = page.rect * page.derotation_matrix
        for mark in state.marks:
            if mark.page_id not in refs or not mark.rects or mark.mode not in ("area", "text"):
                raise WorkspaceError("密文标记引用了无效页面或区域。")
            for rect in mark.rects:
                if (len(rect) != 4 or not all(math.isfinite(value) for value in rect)
                        or rect[2] <= rect[0] or rect[3] <= rect[1]
                        or not bounds[mark.page_id].contains(self.pdf.Rect(rect))):
                    raise WorkspaceError("密文区域必须位于页面内，且宽高大于零。")
        options = state.watermark
        if options.kind not in ("none", "text", "image"):
            raise WorkspaceError("水印类型无效。")
        if options.kind != "none":
            if (not all(math.isfinite(value) for value in (options.size, options.opacity, options.spacing))
                    or not 40 <= options.size <= 170 or not 0.05 <= options.opacity <= 0.8
                    or not 70 <= options.spacing <= 180 or options.angle not in (0, -32)):
                raise WorkspaceError("水印大小、透明度、方向或间距超出支持范围。")
            if options.kind == "text" and (not options.text.strip() or "\n" in options.text):
                raise WorkspaceError("请输入单行水印文字。")
            if options.kind == "image" and options.image_id not in self._images:
                raise WorkspaceError("请先选择有效的 PNG 或 JPG 图片水印。")
            resolve_pages(options.scope, len(state.pages))
        if state.numbers.enabled:
            resolve_pages(state.numbers.scope, len(state.pages))
            number_label(state.numbers, 0, len(state.pages))
            if state.numbers.position not in {f"{edge}_{align}" for edge in ("top", "bottom") for align in ("left", "center", "right")}:
                raise WorkspaceError("页码显示位置无效。")

    def open_watermark_image(self, path):
        from PIL import Image, ImageOps

        try:
            source = Path(path)
            if source.suffix.lower() not in (".png", ".jpg", ".jpeg"):
                raise WorkspaceError("图片水印仅支持 PNG 和 JPG。")
            snapshot = source.read_bytes()
            with Image.open(io.BytesIO(snapshot)) as image:
                if image.format not in ("PNG", "JPEG") or image.width * image.height > 40_000_000:
                    raise WorkspaceError("图片水印格式无效或超过 4,000 万像素，请缩小图片后重试。")
                image.verify()
            with Image.open(io.BytesIO(snapshot)) as image:
                normalized = ImageOps.exif_transpose(image).convert("RGBA")
                # Retain normalized pixels only, not EXIF or other original metadata.
                normalized.info.clear()
                output = io.BytesIO()
                normalized.save(output, format="PNG")
            image_id = uuid4().hex
            self._images[image_id] = output.getvalue()
            return image_id
        except WorkspaceError:
            raise
        except Exception:
            raise WorkspaceError("图片无法读取，请选择有效的本地 PNG 或 JPG。") from None

    def _text_stamp(self, text, fontsize, opacity=1):
        if self._font is None:
            self._font = self.pdf.Font("cjk")
        if any(not self._font.has_glyph(ord(char)) for char in text):
            raise WorkspaceError("当前字体不支持部分水印或页码字符，请更换文字后重试；未生成缺字结果。")
        stamp = self.pdf.open()
        width = self._font.text_length(text, fontsize=fontsize) + 4
        height = (self._font.ascender - self._font.descender) * fontsize + 4
        page = stamp.new_page(width=max(4, width), height=max(4, height))
        page.insert_font(fontname="WorkspaceCJK", fontbuffer=self._font.buffer)
        page.insert_text((2, 2 + self._font.ascender * fontsize), text, fontsize=fontsize,
                         fontname="WorkspaceCJK", color=(0.25, 0.29, 0.34), fill_opacity=opacity)
        return stamp

    def _decorate_page(self, page, state, index):
        watermark, numbers = state.watermark, state.numbers
        watermark_on = watermark.kind != "none" and index in resolve_pages(watermark.scope, len(state.pages))
        numbered = resolve_pages(numbers.scope, len(state.pages)) if numbers.enabled else ()
        if not watermark_on and index not in numbered:
            return
        # Draw in the visible page's coordinates, then map this overlay back once.
        with self.pdf.open() as overlay:
            view = overlay.new_page(width=page.rect.width, height=page.rect.height)
            if watermark_on:
                if watermark.kind == "text":
                    stamp = self._text_stamp(watermark.text, 36 * watermark.size / 100, watermark.opacity)
                else:
                    from PIL import Image
                    with Image.open(io.BytesIO(self._images[watermark.image_id])) as image:
                        image.putalpha(image.getchannel("A").point(lambda value: round(value * watermark.opacity)))
                        buffer = io.BytesIO()
                        image.save(buffer, format="PNG")
                        width = 128 * watermark.size / 100
                        height = width * image.height / image.width
                    stamp = self.pdf.open()
                    stamp.new_page(width=width, height=height).insert_image(self.pdf.Rect(0, 0, width, height), stream=buffer.getvalue())
                try:
                    angle = math.radians(watermark.angle)
                    width, height = stamp[0].rect.width, stamp[0].rect.height
                    rotated_width = abs(width * math.cos(angle)) + abs(height * math.sin(angle))
                    rotated_height = abs(width * math.sin(angle)) + abs(height * math.cos(angle))
                    scale = min(1, view.rect.width * .9 / rotated_width, view.rect.height * .9 / rotated_height)
                    for box in watermark_boxes(view.rect.width, view.rect.height, rotated_width * scale,
                                               rotated_height * scale, watermark.spacing, watermark.tiled):
                        view.show_pdf_page(self.pdf.Rect(box), stamp, rotate=-watermark.angle)
                finally:
                    stamp.close()
            if index in numbered:
                label = number_label(numbers, numbered.index(index), len(state.pages))
                with self._text_stamp(label, 11) as stamp:
                    width, height = stamp[0].rect.width, stamp[0].rect.height
                    scale = min(1, view.rect.width * .8 / width, view.rect.height * .2 / height)
                    width, height = width * scale, height * scale
                    edge, align = numbers.position.split("_")
                    margin = min(18, view.rect.width * .08, view.rect.height * .08)
                    x = {"left": margin, "center": (view.rect.width - width) / 2, "right": view.rect.width - width - margin}[align]
                    y = margin if edge == "top" else view.rect.height - height - margin
                    view.show_pdf_page(self.pdf.Rect(x, y, x + width, y + height), stamp)
            page.show_pdf_page(page.rect * page.derotation_matrix, overlay, rotate=page.rotation)

    def inspect_document(self, state):
        self._validate_state(state)
        result = {"attachments": 0, "annotations": 0, "forms": 0, "signatures": 0,
                  "blocking_reasons": []}
        for source_id in {ref.source_id for ref in state.pages}:
            source = self._sources[source_id]
            result["attachments"] += source.embfile_count()
            if source.get_ocgs():
                result["blocking_reasons"].append("包含可切换隐藏图层，暂不支持安全脱敏。")
            for key in ("AcroForm/XFA", "StructTreeRoot"):
                if source.xref_get_key(source.pdf_catalog(), key)[0] != "null":
                    result["blocking_reasons"].append("包含动态表单或替代文字结构，暂不支持安全脱敏。")
            # ponytail: fail closed on alternate content; add support only with removal tests.
            for xref in range(1, source.xref_length()):
                if (_has_alternate_text(source.xref_object(xref).encode("utf-8"))
                        or (source.xref_is_stream(xref) and _has_alternate_text(source.xref_stream(xref)))):
                    result["blocking_reasons"].append("包含替代文字，暂不支持安全脱敏。")
                    break
        for ref in state.pages:
            page = self._sources[ref.source_id][ref.source_index]
            annotations = list(page.annots() or ())
            result["annotations"] += len(annotations)
            if any(annot.type[0] not in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16)
                   for annot in annotations):
                result["blocking_reasons"].append("包含不支持的互动批注，暂不支持安全脱敏。")
            for widget in page.widgets() or ():
                result["forms"] += 1
                result["signatures"] += widget.field_type == self.pdf.PDF_WIDGET_TYPE_SIGNATURE
        result["blocking_reasons"] = tuple(dict.fromkeys(result["blocking_reasons"]))
        return result

    def _check_redaction_safety(self, state, allow_cleanup):
        inspection = self.inspect_document(state)
        if inspection["blocking_reasons"]:
            raise WorkspaceError("\n".join(inspection["blocking_reasons"]))
        if not allow_cleanup and any(inspection[key] for key in ("attachments", "annotations", "forms", "signatures")):
            raise WorkspaceError("请先确认清除附件、批注备注、表单和签名信息；可见外观将保留，数字签名将失效。")
        occurrences = Counter()
        page_images = {}
        for ref in state.pages:
            images = self._sources[ref.source_id][ref.source_index].get_image_info(xrefs=True)
            page_images[ref.page_id] = images
            occurrences.update(image["digest"] for image in images)
        for mark in state.marks:
            if not mark.applied:
                continue
            for image in page_images[mark.page_id]:
                if not any(self.pdf.Rect(image["bbox"]).intersects(self.pdf.Rect(rect)) for rect in mark.rects):
                    continue
                if occurrences[image["digest"]] > 1:
                    raise WorkspaceError("标记区域包含被多处复用的图片，暂不支持安全脱敏。请先使用单页副本。")
                ref = next(ref for ref in state.pages if ref.page_id == mark.page_id)
                source = self._sources[ref.source_id]
                a, b, c, d, _, _ = image["transform"]
                if (not image["xref"] or abs(b) > 0.001 or abs(c) > 0.001 or a <= 0 or d <= 0
                        or source.xref_get_key(image["xref"], "SMask")[0] != "null"
                        or source.xref_get_key(image["xref"], "Mask")[0] != "null"):
                    raise WorkspaceError("标记区域包含透明、旋转或嵌入图片，暂不支持安全脱敏。")

    def _edited_page(self, state, ref):
        document = self._copy_page(ref)
        try:
            if any(mark.applied for mark in state.marks):
                document.bake(annots=True, widgets=True)
                page = document[0]
                rects = [self.pdf.Rect(rect) for mark in state.marks
                         if mark.page_id == ref.page_id and mark.applied for rect in mark.rects]
                before = _page_chars(page)
                images = [image for image in page.get_image_info(xrefs=True)
                          if any(self.pdf.Rect(image["bbox"]).intersects(rect) for rect in rects)]
                for rect in rects:
                    page.add_redact_annot(rect, fill=(0, 0, 0), cross_out=False)
                if rects:
                    page.apply_redactions(images=self.pdf.PDF_REDACT_IMAGE_PIXELS,
                                          graphics=self.pdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                                          text=self.pdf.PDF_REDACT_TEXT_REMOVE)
                    expected = [char for char in before if not any(self.pdf.Rect(char["bbox"]).intersects(r) for r in rects)]
                    self._verify_chars(expected, _page_chars(page))
                page.clean_contents(sanitize=True)
                if images:
                    self._verify_image_pixels(document.reload_page(page), images, rects)
            return document
        except Exception:
            document.close()
            raise

    def _verify_image_pixels(self, page, originals, rects):
        images = page.get_image_info(xrefs=True)
        for original in originals:
            if any(image["digest"] == original["digest"] for image in images):
                raise WorkspaceError("脱敏区域的原始图片仍可提取，已停止输出。")
            for image in images:
                if tuple(image["bbox"]) != tuple(original["bbox"]):
                    continue
                pixmap = self.pdf.Pixmap(page.parent, image["xref"])
                if pixmap.colorspace != self.pdf.csRGB:
                    pixmap = self.pdf.Pixmap(self.pdf.csRGB, pixmap)
                inverse = ~self.pdf.Matrix(*image["transform"])
                samples = pixmap.samples
                for rect in rects:
                    region = (rect & self.pdf.Rect(image["bbox"])) * inverse
                    x0, y0 = max(0, math.ceil(region.x0 * pixmap.width)), max(0, math.ceil(region.y0 * pixmap.height))
                    x1, y1 = min(pixmap.width, math.floor(region.x1 * pixmap.width)), min(pixmap.height, math.floor(region.y1 * pixmap.height))
                    for y in range(y0, y1):
                        row = samples[y * pixmap.stride + x0 * pixmap.n:y * pixmap.stride + x1 * pixmap.n]
                        if row and row != b"\xff" * len(row):
                            raise WorkspaceError("脱敏区域的原始图片像素清除核验失败，已停止输出。")

    @staticmethod
    def _verify_chars(expected, actual):
        def fingerprint(char):
            return char["text"], tuple(round(value, 1) for value in char["bbox"])
        # PDF extraction may synthesize whitespace after a removed span.
        expected = Counter(fingerprint(char) for char in expected if not char["text"].isspace())
        actual = Counter(fingerprint(char) for char in actual if not char["text"].isspace())
        if expected != actual:
            raise WorkspaceError("脱敏后的文字核验未通过：为防止误删或残留，已停止输出。")

    def validate_apply(self, state, allow_cleanup=False, cancelled=lambda: False, progress=lambda text: None):
        candidate = replace(state, marks=marks_with_state(state.marks, True))
        self._check_redaction_safety(candidate, allow_cleanup)
        for index, ref in enumerate(candidate.pages):
            if cancelled():
                raise InterruptedError("已取消应用，原有标记未改变。")
            progress(f"正在验证密文：第 {index + 1} / {len(candidate.pages)} 页")
            with self._edited_page(candidate, ref):
                pass
        return True

    def _visual_fingerprint(self, page):
        scale = min(1, 1000 / max(page.rect.width, page.rect.height))
        return page.get_pixmap(matrix=self.pdf.Matrix(scale, scale), alpha=False).digest

    def _verify_output(self, path, expected, secure):
        with self.pdf.open(str(path)) as document:
            if len(document) != len(expected) or document.needs_pass:
                raise WorkspaceError("输出 PDF 的页面或加密状态核验失败。")
            for page, (size, chars, appearance) in zip(document, expected):
                if tuple(page.rect) != size:
                    raise WorkspaceError("输出 PDF 的页面尺寸核验失败。")
                self._verify_chars(chars, _page_chars(page))
                if self._visual_fingerprint(page) != appearance:
                    raise WorkspaceError("输出 PDF 的页面外观核验失败，已停止输出。")
                if secure and (list(page.annots() or ()) or list(page.widgets() or ())):
                    raise WorkspaceError("输出仍含可编辑批注或表单，已停止输出。")
            if secure and (document.embfile_count() or document.get_ocgs() or document.metadata.get("title")):
                raise WorkspaceError("输出 PDF 的敏感附加信息清理失败。")

    def export_pdf(self, state, output_file, allow_cleanup=False, cancelled=lambda: False, progress=lambda text: None,
                   temporary_path=None):
        import pdf_toolbox
        from utils.file_helper import publish_output, temporary_output

        self._validate_state(state)
        if pending_count(state):
            raise WorkspaceError("还有待应用的密文标记，请先应用或删除后再导出。")
        target = Path(output_file).expanduser().resolve()
        if target.suffix.lower() != ".pdf":
            raise WorkspaceError("输出文件必须使用 .pdf 扩展名。")
        if temporary_path is not None:
            supplied = Path(temporary_path)
            if (supplied.is_symlink() or supplied.resolve().parent != target.parent
                    or not supplied.name.startswith(f".{target.stem}-") or supplied.suffix != target.suffix
                    or not supplied.is_file() or supplied.stat().st_size):
                raise WorkspaceError("临时输出路径无效，已停止保存。")
        secure = any(mark.applied for mark in state.marks)
        if secure:
            self._check_redaction_safety(state, allow_cleanup)
        temporary, published = None, None
        failures = ()
        try:
            with self.pdf.open() as output:
                expected = []
                for index, ref in enumerate(state.pages):
                    if cancelled():
                        raise InterruptedError("已取消导出。")
                    progress(f"正在生成 PDF：第 {index + 1} / {len(state.pages)} 页")
                    with self._edited_page(state, ref) as document:
                        self._decorate_page(document[0], state, len(output))
                        output.insert_pdf(document)
                if secure:
                    output.scrub(hidden_text=False, redactions=False)
                    output.set_metadata({"producer": "Eggie DocuFlow / PyMuPDF / MuPDF"})
                for page in output:
                    expected.append((tuple(page.rect), _page_chars(page), self._visual_fingerprint(page)))
                temporary = temporary_path or temporary_output(target)
                output.save(temporary, incremental=False, garbage=4, deflate=True)
            progress("正在重新打开并核验 PDF，请稍候…")
            self._verify_output(temporary, expected, secure)
            if cancelled():
                raise InterruptedError("已取消导出，未发布结果。")
            published = publish_output(temporary, target)
        finally:
            if temporary is not None:
                try:
                    Path(temporary).unlink(missing_ok=True)
                except OSError:
                    warning = f"临时文件未能清理，请手动检查：{temporary}"
                    if published is None:
                        raise WorkspaceError("PDF 未保存；" + warning) from None
                    failures += ("PDF 已保存并核验；" + warning,)
        log_file = ""
        try:
            log_file = pdf_toolbox.write_log(target.parent, "PDF工作区处理记录", [
                f"输出文件：{Path(published).name}", f"输出页数：{len(state.pages)}",
                f"已应用密文标记：{len(state.marks)}", "状态：已完成并重新读取核验；原文件未修改。",
            ])
        except Exception:
            failures += ("PDF 已保存并核验，但处理记录未能写入。",)
        return pdf_toolbox.PdfToolResult(published, str(log_file), output_size=Path(published).stat().st_size,
                                         failures=failures)

    def release_resources(self, source_ids=(), image_ids=()):
        # Explicit discarded IDs cannot remove snapshots opened by a later request.
        for source_id in source_ids:
            document = self._sources.pop(source_id, None)
            if document is not None:
                document.close()
        for image_id in image_ids:
            self._images.pop(image_id, None)

    def close(self) -> None:
        for document in self._sources.values():
            document.close()
        self._sources.clear()
        self._images.clear()
        self._font = None


def run_pdf_workspace_worker(request_queue, response_queue, cancel_event=None):
    """Spawn entry point. Only plain models and rendered bytes cross the boundary."""
    engine = PdfWorkspaceEngine()
    try:
        while True:
            request_id, revision, operation, payload = request_queue.get()
            def progress(message):
                response_queue.put((request_id, revision, "progress", message))
            try:
                if operation == "open":
                    result = engine.open_pdf(**payload)
                elif operation == "inspect":
                    result = engine.inspect_document(**payload)
                elif operation == "render":
                    result = engine.render_page(**payload)
                elif operation == "apply":
                    result = engine.validate_apply(**payload, cancelled=cancel_event.is_set if cancel_event else lambda: False, progress=progress)
                elif operation == "export":
                    result = engine.export_pdf(**payload, cancelled=cancel_event.is_set if cancel_event else lambda: False, progress=progress)
                elif operation == "image":
                    result = engine.open_watermark_image(**payload)
                elif operation == "release":
                    result = engine.release_resources(**payload)
                elif operation == "close":
                    response_queue.put((request_id, revision, "completed", None))
                    break
                else:
                    raise WorkspaceError("不支持的 PDF 操作。")
                response_queue.put((request_id, revision, "completed", result))
            except (WorkspaceError, InterruptedError) as error:
                response_queue.put((request_id, revision, "failed", str(error)))
            except Exception:
                response_queue.put((request_id, revision, "failed", "PDF 处理失败，原文件未修改。请检查文件和输出目录后重试。"))
    finally:
        engine.close()
