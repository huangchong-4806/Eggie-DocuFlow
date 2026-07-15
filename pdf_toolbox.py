import copy
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from utils.file_helper import available_output_path


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
    import pypdfium2 as pdfium

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

    return source, destination, tuple(image_files)


def pdf_to_images(pdf_file, output_folder, image_format="jpg", dpi=300):
    source, destination, image_files = _render_pdf_to_images(
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
            f"PDF页数：{len(image_files)}",
            f"图片数量：{len(image_files)}",
            *[f"输出图片：{image_file}" for image_file in image_files],
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

            rendered_source, destination, rendered_images = _render_pdf_to_images(
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
                f"保存位置={destination}"
            )
            detail_lines.extend(f"输出图片：{image_file}" for image_file in rendered_images)
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
