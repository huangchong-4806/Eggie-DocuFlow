import copy
import difflib
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from utils.file_helper import available_output_path, publish_output, temporary_output


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
COMPRESSION_PRESETS = {
    "clear": {
        "label": "清晰优先",
        "estimate": (0.75, 1.0),
        "scale": None,
        "quality": None,
    },
    "standard": {
        "label": "标准压缩",
        "estimate": (0.45, 0.8),
        "scale": 2.0,
        "quality": 88,
    },
    "small": {
        "label": "体积优先",
        "estimate": (0.3, 0.65),
        "scale": 1.7,
        "quality": 84,
    },
}


@dataclass(frozen=True)
class PdfPageRef:
    source_file: str
    page_index: int
    rotation: int = 0


@dataclass(frozen=True)
class PdfToolResult:
    output_file: str
    log_file: str
    source_size: int = 0
    output_size: int = 0
    image_files: tuple = ()
    source_files: tuple = ()
    failures: tuple = ()

    @property
    def saved_bytes(self):
        return max(0, self.source_size - self.output_size)

    @property
    def saved_percent(self):
        if not self.source_size:
            return 0
        return round(self.saved_bytes / self.source_size * 100, 1)


def today_stamp():
    return datetime.now().strftime("%Y%m%d")


def timestamp_stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def default_output_name(label, suffix=".pdf"):
    return f"{label}_{today_stamp()}{suffix}"


def clean_pdf_filename(filename, fallback):
    filename = (filename or "").strip() or fallback
    if not filename.lower().endswith(".pdf"):
        filename = f"{filename}.pdf"
    if any(character in filename for character in {"/", "\0", ":"}):
        raise ValueError("文件名包含不允许使用的字符。")
    return filename


def is_supported_image_file(image_file):
    from PIL import Image

    source = Path(image_file).expanduser()
    if not source.is_file() or source.suffix.lower() not in IMAGE_SUFFIXES:
        return False
    try:
        with Image.open(source) as image:
            image.verify()
    except Exception:
        return False
    return True


def prepare_image_thumbnail(image_file, thumbnail_file, size=(132, 180)):
    from PIL import Image, ImageOps

    source = Path(image_file).expanduser().resolve()
    destination = Path(thumbnail_file).expanduser().resolve()
    if not is_supported_image_file(source):
        raise ValueError("图片无法读取或格式不支持。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        preview = ImageOps.exif_transpose(image).convert("RGB")
        try:
            preview.thumbnail(tuple(size), Image.Resampling.LANCZOS)
            preview.save(destination, "JPEG", quality=85)
        finally:
            preview.close()
    return str(destination)


def output_path(folder, filename, fallback):
    folder = Path(folder).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    return available_output_path(folder / clean_pdf_filename(filename, fallback))


def compression_preset(preset):
    return COMPRESSION_PRESETS.get(preset, COMPRESSION_PRESETS["standard"])


def estimate_compressed_size(source_size, preset="standard"):
    low, high = compression_preset(preset)["estimate"]
    return int(source_size * low), int(source_size * high)


def page_count(pdf_file):
    from pypdf import PdfReader

    return len(PdfReader(str(pdf_file)).pages)


def write_log(folder, title, lines):
    folder = Path(folder).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    log_file = available_output_path(folder / f"PDF工具箱日志_{timestamp_stamp()}.txt")
    with log_file.open("w", encoding="utf-8") as handle:
        handle.write(f"{title}\n")
        handle.write(f"生成时间：{datetime.now().isoformat(timespec='seconds')}\n")
        handle.write("=" * 60 + "\n")
        for line in lines:
            handle.write(f"{line}\n")
    return str(log_file)


def _publish_writer(writer, output_file):
    output_file = available_output_path(Path(output_file).expanduser().resolve())
    output_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = temporary_output(output_file)
    try:
        with Path(temporary_file).open("wb") as handle:
            writer.write(handle)
        return publish_output(temporary_file, output_file)
    finally:
        Path(temporary_file).unlink(missing_ok=True)


def _decrypt_reader(reader, password):
    if not reader.is_encrypted:
        return
    if not password:
        raise ValueError("这个 PDF 已加密，请输入原密码。")
    if not reader.decrypt(password):
        raise ValueError("原 PDF 密码不正确。")


def secure_pdf(pdf_file, output_file, new_password="", source_password=""):
    from pypdf import PdfReader, PdfWriter

    source = Path(pdf_file).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".pdf":
        raise ValueError("请选择有效的 PDF 文件。")
    reader = PdfReader(str(source))
    _decrypt_reader(reader, source_password)
    if not new_password and not reader.is_encrypted:
        raise ValueError("这个 PDF 当前没有密码。")

    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    if reader.metadata:
        writer.add_metadata(dict(reader.metadata))
    action = "移除密码"
    if new_password:
        writer.encrypt(new_password, algorithm="AES-256-R5")
        action = "设置密码"
    final_file = _publish_writer(writer, output_file)
    log_file = write_log(
        Path(final_file).parent,
        f"PDF {action}",
        [
            f"来源文件：{source}",
            f"页数：{len(reader.pages)}",
            f"操作：{action}",
            "密码写入日志：否",
            f"文件生成状态：output_file={final_file}",
        ],
    )
    return PdfToolResult(
        final_file,
        log_file,
        source.stat().st_size,
        Path(final_file).stat().st_size,
    )


def _qt_pdf_page(output_file, width, height, draw_callback):
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QGuiApplication, QPageLayout, QPageSize, QPainter, QPdfWriter

    if QGuiApplication.instance() is None:
        raise RuntimeError("PDF 文字绘制需要从 Eggie DocuFlow 软件界面执行。")
    writer = QPdfWriter(str(output_file))
    writer.setResolution(72)
    writer.setPageSize(QPageSize(QSizeF(width, height), QPageSize.Point))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Point)
    painter = QPainter()
    if not painter.begin(writer):
        raise RuntimeError("无法创建 PDF 文字图层。")
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        draw_callback(painter, width, height)
    finally:
        painter.end()


def _watermark_position(position, width, height, text_width, text_height):
    margin = 28
    positions = {
        "top_left": (margin, margin),
        "top_right": (width - text_width - margin, margin),
        "bottom_left": (margin, height - text_height - margin),
        "bottom_right": (width - text_width - margin, height - text_height - margin),
    }
    return positions.get(position, ((width - text_width) / 2, (height - text_height) / 2))


def _page_number_position(position, width, height, text_width, text_height):
    margin_x = 32
    margin_y = 18
    top = position.startswith("top")
    if position.endswith("left"):
        left = margin_x
    elif position.endswith("right"):
        left = width - text_width - margin_x
    else:
        left = (width - text_width) / 2
    y = margin_y if top else height - text_height - margin_y
    return left, y


def add_pdf_marks(
    pdf_file,
    output_file,
    watermark_text="",
    watermark_opacity=0.18,
    watermark_angle=-30,
    watermark_font_size=40,
    watermark_position="center",
    add_page_numbers=False,
    page_number_start=1,
    page_number_position="bottom_center",
    progress_callback=None,
):
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QFontMetricsF
    from pypdf import PdfReader, PdfWriter

    source = Path(pdf_file).expanduser().resolve()
    if not watermark_text.strip() and not add_page_numbers:
        raise ValueError("请填写水印文字或启用页码。")
    if not 0.05 <= float(watermark_opacity) <= 0.8:
        raise ValueError("水印透明度必须在 5% 到 80% 之间。")
    reader = PdfReader(str(source))
    _decrypt_reader(reader, "")
    writer = PdfWriter()
    with tempfile.TemporaryDirectory(prefix="eggie-pdf-marks-") as folder:
        folder = Path(folder)
        for index, source_page in enumerate(reader.pages, 1):
            if progress_callback:
                progress_callback(index - 1, len(reader.pages), f"正在处理第 {index} 页")
            width = float(source_page.cropbox.width)
            height = float(source_page.cropbox.height)
            overlay_file = folder / f"overlay-{index}.pdf"

            def draw(painter, page_width, page_height, page_index=index):
                if watermark_text.strip():
                    font = QFont("PingFang SC")
                    font.setPixelSize(int(watermark_font_size))
                    painter.setFont(font)
                    painter.setPen(QColor(28, 72, 115, round(255 * float(watermark_opacity))))
                    metrics = QFontMetricsF(font)
                    text_width = metrics.horizontalAdvance(watermark_text)
                    text_height = metrics.height()
                    left, top = _watermark_position(
                        watermark_position,
                        page_width,
                        page_height,
                        text_width,
                        text_height,
                    )
                    painter.save()
                    painter.translate(left + text_width / 2, top + text_height / 2)
                    painter.rotate(float(watermark_angle))
                    painter.drawText(
                        QRectF(-text_width, -text_height, text_width * 2, text_height * 2),
                        Qt.AlignCenter,
                        watermark_text,
                    )
                    painter.restore()
                if add_page_numbers:
                    number_text = str(int(page_number_start) + page_index - 1)
                    number_font = QFont("PingFang SC")
                    number_font.setPixelSize(11)
                    painter.setFont(number_font)
                    painter.setPen(QColor(45, 55, 65, 210))
                    metrics = QFontMetricsF(number_font)
                    text_width = metrics.horizontalAdvance(number_text)
                    text_height = metrics.height()
                    left, top = _page_number_position(
                        page_number_position,
                        page_width,
                        page_height,
                        text_width,
                        text_height,
                    )
                    painter.drawText(QRectF(left, top, text_width + 4, text_height + 2), number_text)

            _qt_pdf_page(overlay_file, width, height, draw)
            writer.add_page(copy.deepcopy(source_page))
            writer.pages[-1].merge_page(PdfReader(str(overlay_file)).pages[0])
            if progress_callback:
                progress_callback(index, len(reader.pages), f"第 {index} 页已完成")

    final_file = _publish_writer(writer, output_file)
    log_file = write_log(
        Path(final_file).parent,
        "PDF 水印与页码",
        [
            f"来源文件：{source}",
            f"页数：{len(reader.pages)}",
            f"水印：{'已添加' if watermark_text.strip() else '未添加'}",
            f"水印透明度：{float(watermark_opacity):.2f}",
            f"水印角度：{watermark_angle}",
            f"页码：{'已添加' if add_page_numbers else '未添加'}",
            f"页码起始值：{page_number_start}",
            f"文件生成状态：output_file={final_file}",
        ],
    )
    return PdfToolResult(
        final_file,
        log_file,
        source.stat().st_size,
        Path(final_file).stat().st_size,
    )


def _searchable_overlay_page(output_file, width, height, blocks):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QFont

    def draw(painter, page_width, page_height):
        painter.setPen(QColor(0, 0, 0, 1))
        for block in blocks:
            text = str(block.text or "").strip()
            if not text:
                continue
            left, top, right, bottom = block.bbox
            rect = QRectF(
                float(left) * page_width,
                float(top) * page_height,
                max(2.0, (float(right) - float(left)) * page_width),
                max(2.0, (float(bottom) - float(top)) * page_height),
            )
            font = QFont("PingFang SC")
            font.setPixelSize(
                max(
                    5,
                    min(
                        72,
                        round(rect.height() * 0.8),
                        round(rect.width() / max(len(text), 1) * 1.5),
                    ),
                )
            )
            painter.setFont(font)
            painter.drawText(rect, text)

    _qt_pdf_page(output_file, width, height, draw)


def make_searchable_pdf(
    pdf_file,
    output_file,
    provider_name,
    progress_callback=None,
):
    from api_layer.document import extract_document
    from pypdf import PdfReader, PdfWriter

    source = Path(pdf_file).expanduser().resolve()
    extraction = extract_document(source, provider_name, progress_callback)
    reader = PdfReader(str(source))
    _decrypt_reader(reader, "")
    writer = PdfWriter()
    with tempfile.TemporaryDirectory(prefix="eggie-searchable-pdf-") as folder:
        folder = Path(folder)
        for index, source_page in enumerate(reader.pages, 1):
            writer.add_page(copy.deepcopy(source_page))
            page_text = extraction.pages[index - 1]
            if page_text.method == "cloud_ocr" and page_text.blocks:
                overlay_file = folder / f"text-{index}.pdf"
                _searchable_overlay_page(
                    overlay_file,
                    float(source_page.cropbox.width),
                    float(source_page.cropbox.height),
                    page_text.blocks,
                )
                writer.pages[-1].merge_page(PdfReader(str(overlay_file)).pages[0])
    final_file = _publish_writer(writer, output_file)
    log_file = write_log(
        Path(final_file).parent,
        "可搜索 PDF",
        [
            f"来源文件：{source}",
            f"页数：{extraction.page_count}",
            f"本机文字页：{extraction.local_page_count}",
            f"云 OCR 页：{extraction.cloud_page_count}",
            f"OCR 平台：{extraction.provider}",
            "密钥写入日志：否",
            "文档正文写入日志：否",
            f"文件生成状态：output_file={final_file}",
        ],
    )
    return PdfToolResult(
        final_file,
        log_file,
        source.stat().st_size,
        Path(final_file).stat().st_size,
    )


def compare_pdf_text(left_pdf, right_pdf, output_file, progress_callback=None):
    from utils.pdf_helper import SCANNED_MARKER, extract_text

    left = Path(left_pdf).expanduser().resolve()
    right = Path(right_pdf).expanduser().resolve()
    output_file = available_output_path(Path(output_file).expanduser().resolve())
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="eggie-pdf-compare-") as folder:
        folder = Path(folder)
        texts = []
        for index, source in enumerate((left, right), 1):
            if progress_callback:
                progress_callback(index - 1, 2, f"正在读取：{source.name}")
            text_file = folder / f"source-{index}.txt"
            sampled, _page_count = extract_text(source, text_file)
            full_text = text_file.read_text(encoding="utf-8")
            if SCANNED_MARKER in sampled or SCANNED_MARKER in full_text:
                raise ValueError(
                    f"{source.name} 包含扫描页，请先生成可搜索 PDF 后再比较。"
                )
            texts.append(full_text.splitlines())
        report = difflib.HtmlDiff(tabsize=4, wrapcolumn=100).make_file(
            texts[0],
            texts[1],
            fromdesc=left.name,
            todesc=right.name,
            context=False,
            charset="utf-8",
        )
        temporary_file = temporary_output(output_file)
        try:
            Path(temporary_file).write_text(report, encoding="utf-8")
            final_file = publish_output(temporary_file, output_file)
        finally:
            Path(temporary_file).unlink(missing_ok=True)
    if progress_callback:
        progress_callback(2, 2, "文字对比报告已生成")
    log_file = write_log(
        Path(final_file).parent,
        "PDF 文字对比",
        [
            f"第一份文件：{left}",
            f"第二份文件：{right}",
            f"第一份文字行数：{len(texts[0])}",
            f"第二份文字行数：{len(texts[1])}",
            "处理方式：仅本机逐行比较",
            f"文件生成状态：output_file={final_file}",
        ],
    )
    return PdfToolResult(final_file, log_file, source_files=(str(left), str(right)))


def save_pages(page_refs, output_file, title="PDF 页面整理"):
    from pypdf import PdfReader, PdfWriter

    page_refs = tuple(page_refs)
    if not page_refs:
        raise ValueError("没有可保存的 PDF 页面。")

    writer = PdfWriter()
    readers = {}
    page_lines = []
    source_sizes = {}

    for index, page_ref in enumerate(page_refs, 1):
        source = str(Path(page_ref.source_file).expanduser().resolve())
        readers.setdefault(source, PdfReader(source))
        page = copy.deepcopy(readers[source].pages[page_ref.page_index])
        rotation = page_ref.rotation % 360
        if rotation:
            page.rotate(rotation)
        writer.add_page(page)
        source_sizes[source] = Path(source).stat().st_size
        page_lines.append(
            f"第{index}页：来源={source} 原页码={page_ref.page_index + 1} 旋转={rotation}"
        )

    output_file = Path(output_file).expanduser().resolve()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file = available_output_path(output_file)
    with output_file.open("wb") as handle:
        writer.write(handle)

    lines = [f"页面数量：{len(page_refs)}", f"输出文件：{output_file}", *page_lines]
    log_file = write_log(output_file.parent, title, lines)
    return PdfToolResult(
        str(output_file),
        log_file,
        source_size=sum(source_sizes.values()),
        output_size=output_file.stat().st_size,
    )


def write_structural_compressed_pdf(source, output_file):
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(source))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
        writer.pages[-1].compress_content_streams()
    if reader.metadata:
        writer.add_metadata(reader.metadata)

    with output_file.open("wb") as handle:
        writer.write(handle)


def write_raster_compressed_pdf(source, output_file, preset):
    import pypdfium2 as pdfium

    options = compression_preset(preset)
    scale = options["scale"]
    quality = options["quality"]
    if not scale or not quality:
        raise ValueError("当前压缩档位不需要图片式压缩。")

    document = pdfium.PdfDocument(str(source))
    images = []
    try:
        for index in range(len(document)):
            page = document[index]
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil().convert("RGB")
            page.close()
            images.append(image)
        if not images:
            raise ValueError("这个 PDF 没有可压缩的页面。")
        images[0].save(
            output_file,
            "PDF",
            save_all=True,
            append_images=images[1:],
            resolution=72 * scale,
            quality=quality,
        )
    finally:
        for image in images:
            image.close()
        document.close()


def compress_pdf(pdf_file, output_file, preset="standard"):
    source = Path(pdf_file).expanduser().resolve()
    preset = preset if preset in COMPRESSION_PRESETS else "standard"
    output_file = Path(output_file).expanduser().resolve()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file = available_output_path(output_file)
    method = "保留文字结构"

    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_root = Path(temporary_directory)
        structural_file = temporary_root / "structural.pdf"
        write_structural_compressed_pdf(source, structural_file)
        best_file = structural_file

        if preset != "clear":
            raster_file = temporary_root / "raster.pdf"
            try:
                write_raster_compressed_pdf(source, raster_file, preset)
                if raster_file.stat().st_size < best_file.stat().st_size:
                    best_file = raster_file
                    method = "图片式压缩"
            except Exception:
                method = "保留文字结构"

        shutil.copyfile(best_file, output_file)

    source_size = source.stat().st_size
    output_size = output_file.stat().st_size
    estimated_low, estimated_high = estimate_compressed_size(source_size, preset)
    log_file = write_log(
        output_file.parent,
        "PDF 压缩",
        [
            f"来源文件：{source}",
            f"输出文件：{output_file}",
            f"压缩档位：{compression_preset(preset)['label']}",
            f"实际方式：{method}",
            f"预计大小：{estimated_low}-{estimated_high}",
            f"压缩前大小：{source_size}",
            f"压缩后大小：{output_size}",
            f"节省比例：{PdfToolResult(str(output_file), '', source_size, output_size).saved_percent}%",
        ],
    )
    return PdfToolResult(str(output_file), log_file, source_size, output_size)


def images_to_pdf(image_files, output_file):
    from PIL import Image, ImageOps
    import PIL.JpegImagePlugin  # noqa: F401

    image_files = tuple(image_files)
    if not image_files:
        raise ValueError("请先选择图片。")

    converted = []
    for image_file in image_files:
        source = Path(image_file).expanduser().resolve()
        if not is_supported_image_file(source):
            raise ValueError(f"不支持的图片格式：{source.name}")
        with Image.open(source) as image:
            converted.append(ImageOps.exif_transpose(image).convert("RGB"))

    output_file = Path(output_file).expanduser().resolve()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file = available_output_path(output_file)
    try:
        converted[0].save(output_file, save_all=True, append_images=converted[1:])
    finally:
        for image in converted:
            image.close()

    source_size = sum(Path(image_file).stat().st_size for image_file in image_files)
    log_file = write_log(
        output_file.parent,
        "图片转 PDF",
        [
            f"图片数量：{len(image_files)}",
            f"输出文件：{output_file}",
            *[f"来源图片：{Path(image_file).expanduser().resolve()}" for image_file in image_files],
        ],
    )
    return PdfToolResult(
        str(output_file),
        log_file,
        source_size,
        output_file.stat().st_size,
    )


def _render_pdf_to_images(
    pdf_file,
    output_folder,
    image_format="jpg",
    dpi=300,
    page_progress_callback=None,
):
    source = Path(pdf_file).expanduser().resolve()
    if source.suffix.lower() != ".pdf":
        raise ValueError("只支持 PDF 文件。")
    if not source.is_file():
        raise FileNotFoundError("PDF 文件不存在。")

    output_folder = Path(output_folder).expanduser().resolve()
    output_folder.mkdir(parents=True, exist_ok=True)
    image_format = image_format.lower().strip(".") or "png"
    if image_format not in {"png", "jpg", "jpeg"}:
        raise ValueError("图片格式只支持 PNG 或 JPG。")
    dpi = int(dpi)
    if not 72 <= dpi <= 600:
        raise ValueError("图片清晰度必须在 72 到 600 DPI 之间。")

    import sys

    if sys.platform == "darwin" and Path("/usr/bin/qlmanage").is_file():
        return _render_pdf_to_images_macos(
            source,
            output_folder,
            image_format,
            dpi,
            page_progress_callback,
        )
    return _render_pdf_to_images_pdfium(
        source,
        output_folder,
        image_format,
        dpi,
        page_progress_callback,
    )


def _render_pdf_to_images_macos(
    source,
    output_folder,
    image_format,
    dpi,
    page_progress_callback,
):
    import subprocess

    from PIL import Image
    from pypdf import PdfReader, PdfWriter

    image_files = []
    created_destination = None
    output_file = None
    with source.open("rb") as source_handle:
        reader = PdfReader(source_handle)
        total_pages = len(reader.pages)
        if not total_pages:
            raise ValueError("这个 PDF 没有可转换的页面。")

        destination = output_folder
        if total_pages > 1:
            destination = available_output_path(output_folder / source.stem)
            destination.mkdir(parents=True, exist_ok=True)
            created_destination = destination

        try:
            with tempfile.TemporaryDirectory(prefix="eggie_pdf_render_") as temporary:
                temporary = Path(temporary)
                for index, page in enumerate(reader.pages):
                    if page_progress_callback:
                        page_progress_callback(index + 1, total_pages)

                    page_pdf = temporary / f"page_{index + 1}.pdf"
                    writer = PdfWriter()
                    writer.add_page(page)
                    with page_pdf.open("wb") as page_handle:
                        writer.write(page_handle)

                    preview_folder = temporary / f"preview_{index + 1}"
                    preview_folder.mkdir()
                    page_width = max(float(page.cropbox.width), 1.0)
                    page_height = max(float(page.cropbox.height), 1.0)
                    max_pixels = max(1, round(max(page_width, page_height) * dpi / 72))
                    completed = subprocess.run(
                        [
                            "/usr/bin/qlmanage",
                            "-t",
                            "-s",
                            str(max_pixels),
                            "-o",
                            str(preview_folder),
                            str(page_pdf),
                        ],
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    previews = tuple(preview_folder.glob("*.png"))
                    if completed.returncode != 0 or len(previews) != 1:
                        reason = completed.stderr.strip() or completed.stdout.strip()
                        raise RuntimeError(f"Mac 页面转换失败：{reason or '未生成页面图片'}")

                    suffix = "jpg" if image_format == "jpeg" else image_format
                    output_file = available_output_path(
                        destination / f"{source.stem}_{index + 1}.{suffix}"
                    )
                    with Image.open(previews[0]) as preview:
                        image = preview.convert("RGB") if suffix == "jpg" else preview.copy()
                    try:
                        save_options = {"dpi": (dpi, dpi)}
                        if suffix == "jpg":
                            save_options["quality"] = 95
                        image.save(output_file, **save_options)
                    finally:
                        image.close()
                    image_files.append(str(output_file))
        except Exception:
            for image_file in image_files:
                Path(image_file).unlink(missing_ok=True)
            if output_file is not None:
                Path(output_file).unlink(missing_ok=True)
            if created_destination is not None:
                try:
                    created_destination.rmdir()
                except OSError:
                    pass
            raise

    return source, destination, tuple(image_files), "Mac 原生页面显示（与“预览”一致）"


def _render_pdf_to_images_pdfium(
    source,
    output_folder,
    image_format,
    dpi,
    page_progress_callback,
):
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(source))
    image_files = []
    created_destination = None
    output_file = None
    try:
        total_pages = len(document)
        if not total_pages:
            raise ValueError("这个 PDF 没有可转换的页面。")

        destination = output_folder
        if total_pages > 1:
            destination = available_output_path(output_folder / source.stem)
            destination.mkdir(parents=True, exist_ok=True)
            created_destination = destination

        for index in range(total_pages):
            if page_progress_callback:
                page_progress_callback(index + 1, total_pages)
            page = document[index]
            image = None
            output_file = None
            try:
                bitmap = page.render(scale=dpi / 72)
                suffix = "jpg" if image_format == "jpeg" else image_format
                image = bitmap.to_pil()
                if suffix == "jpg" and image.mode != "RGB":
                    converted = image.convert("RGB")
                    image.close()
                    image = converted
                output_file = available_output_path(
                    destination / f"{source.stem}_{index + 1}.{suffix}"
                )
                save_options = {"dpi": (dpi, dpi)}
                if suffix == "jpg":
                    save_options["quality"] = 95
                image.save(output_file, **save_options)
            finally:
                if image is not None:
                    image.close()
                page.close()
            image_files.append(str(output_file))
    except Exception:
        for image_file in image_files:
            Path(image_file).unlink(missing_ok=True)
        if output_file is not None:
            Path(output_file).unlink(missing_ok=True)
        if created_destination is not None:
            try:
                created_destination.rmdir()
            except OSError:
                pass
        raise
    finally:
        document.close()

    return source, destination, tuple(image_files), "通用 PDF 页面显示"


def _image_output_log_line(image_file):
    from PIL import Image

    with Image.open(image_file) as image:
        width, height = image.size
    return f"输出图片：{image_file} 像素={width}x{height} 状态=已生成"


def pdf_to_images(pdf_file, output_folder, image_format="jpg", dpi=300):
    source, destination, image_files, renderer = _render_pdf_to_images(
        pdf_file,
        output_folder,
        image_format,
        dpi,
    )
    output_folder = Path(output_folder).expanduser().resolve()

    log_file = write_log(
        output_folder,
        "PDF 转图片",
        [
            f"来源文件：{source}",
            f"输出文件夹：{output_folder}",
            f"实际保存位置：{destination}",
            f"图片格式：{image_format.upper()}",
            f"图片清晰度：{int(dpi)} DPI",
            f"页面呈现方式：{renderer}",
            f"PDF页数：{len(image_files)}",
            f"图片数量：{len(image_files)}",
            *[_image_output_log_line(image_file) for image_file in image_files],
        ],
    )
    return PdfToolResult(
        "",
        log_file,
        source.stat().st_size,
        sum(Path(image_file).stat().st_size for image_file in image_files),
        image_files,
        (str(source),),
    )


def pdfs_to_images(
    pdf_files,
    output_folder,
    image_format="jpg",
    dpi=300,
    progress_callback=None,
):
    pdf_files = tuple(
        dict.fromkeys(str(Path(pdf_file).expanduser().resolve()) for pdf_file in pdf_files)
    )
    if not pdf_files:
        raise ValueError("请先添加 PDF 文件。")

    output_folder = Path(output_folder).expanduser().resolve()
    output_folder.mkdir(parents=True, exist_ok=True)
    image_files = []
    source_files = []
    failures = []
    detail_lines = []

    total_files = len(pdf_files)
    for file_index, pdf_file in enumerate(pdf_files, 1):
        source = Path(pdf_file)
        if progress_callback:
            progress_callback(
                file_index - 1,
                total_files,
                f"正在转换第 {file_index} / {total_files} 个：{source.name}",
            )
        try:
            def update_page(page_number, total_pages):
                if progress_callback:
                    progress_callback(
                        file_index - 1,
                        total_files,
                        f"正在转换第 {file_index} / {total_files} 个：{source.name}"
                        f"（第 {page_number} / {total_pages} 页）",
                    )

            rendered_source, destination, rendered_images, renderer = _render_pdf_to_images(
                source,
                output_folder,
                image_format,
                dpi,
                page_progress_callback=update_page,
            )
            source_files.append(str(rendered_source))
            image_files.extend(rendered_images)
            detail_lines.append(
                "处理成功："
                f"来源={rendered_source} "
                f"页数={len(rendered_images)} "
                f"保存位置={destination} "
                f"页面呈现方式={renderer}"
            )
            detail_lines.extend(
                _image_output_log_line(image_file) for image_file in rendered_images
            )
        except Exception as error:
            reason = f"{type(error).__name__}: {error}"
            failures.append((str(source), reason))
            detail_lines.append(f"处理失败：来源={source} 原因={reason}")
        if progress_callback:
            progress_callback(
                file_index,
                total_files,
                f"已完成 {file_index} / {total_files} 个 PDF",
            )

    log_file = write_log(
        output_folder,
        "批量 PDF 转图片",
        [
            f"PDF总数：{len(pdf_files)}",
            f"成功文件数：{len(source_files)}",
            f"失败文件数：{len(failures)}",
            f"图片总数：{len(image_files)}",
            f"图片格式：{image_format.upper()}",
            f"图片清晰度：{int(dpi)} DPI",
            f"输出根文件夹：{output_folder}",
            *detail_lines,
        ],
    )
    return PdfToolResult(
        "",
        log_file,
        0,
        0,
        tuple(image_files),
        tuple(source_files),
        tuple(failures),
    )


def render_page_thumbnail(pdf_file, page_index, output_file, max_width=180):
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(pdf_file))
    try:
        page = document[page_index]
        width = max(float(page.get_width()), 1.0)
        scale = max_width / width
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil()
        image.thumbnail((max_width, int(max_width * 1.5)))
        image.save(output_file)
        image.close()
        page.close()
    finally:
        document.close()
    return str(output_file)
