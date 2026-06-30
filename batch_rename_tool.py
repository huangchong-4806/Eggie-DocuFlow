import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ILLEGAL_NAME_CHARS = {"/", "\0", ":"}


@dataclass(frozen=True)
class RenameOptions:
    find_text: str = ""
    replace_text: str = ""
    delete_text: str = ""
    trim_start_count: int = 0
    trim_end_count: int = 0
    prefix: str = ""
    suffix: str = ""
    extension: str = ""
    numbering_enabled: bool = False
    number_start: int = 1
    number_digits: int = 3


@dataclass(frozen=True)
class RenamePreview:
    source_path: str
    target_path: str
    status: str
    message: str
    will_rename: bool
    blocked: bool


@dataclass(frozen=True)
class RenameAction:
    source_path: str
    target_path: str
    status: str
    error: str = ""


@dataclass(frozen=True)
class RenameApplyResult:
    log_file: str
    actions: tuple

    @property
    def success_count(self):
        return sum(1 for action in self.actions if action.status == "成功")

    @property
    def failed_count(self):
        return sum(1 for action in self.actions if action.status == "失败")

    @property
    def skipped_count(self):
        return sum(1 for action in self.actions if action.status == "跳过")


def discover_rename_files(folder):
    files = []
    for root, directory_names, filenames in os.walk(folder):
        directory_names[:] = sorted(
            (
                name
                for name in directory_names
                if not name.startswith(".") and name != "__MACOSX"
            ),
            key=str.casefold,
        )
        for filename in sorted(filenames, key=str.casefold):
            if filename.startswith("."):
                continue
            path = Path(root, filename)
            if path.is_file():
                files.append(str(path.resolve()))
    return files


def _normalized_extension(extension, original_suffix):
    extension = extension.strip()
    if not extension:
        return original_suffix
    if extension == ".":
        raise ValueError("新后缀不能只填写一个点。")
    if any(character in extension for character in ILLEGAL_NAME_CHARS):
        raise ValueError("新后缀包含不允许使用的字符。")
    return extension if extension.startswith(".") else f".{extension}"


def _validate_name(filename):
    if not filename.strip():
        raise ValueError("新文件名不能为空。")
    if any(character in filename for character in ILLEGAL_NAME_CHARS):
        raise ValueError("新文件名包含不允许使用的字符。")


def _target_for(source_path, options, sequence_number):
    source = Path(source_path)
    stem = source.stem
    if options.find_text:
        stem = stem.replace(options.find_text, options.replace_text)
    if options.delete_text:
        stem = stem.replace(options.delete_text, "")
    if options.trim_start_count:
        stem = stem[max(0, options.trim_start_count) :]
    if options.trim_end_count:
        trim_count = max(0, options.trim_end_count)
        stem = stem[:-trim_count] if trim_count < len(stem) else ""
    stem = f"{options.prefix}{stem}{options.suffix}"
    if options.numbering_enabled:
        digits = max(1, options.number_digits)
        stem = f"{stem}_{sequence_number:0{digits}d}"
    if not stem.strip():
        raise ValueError("新文件名不能为空。")

    extension = _normalized_extension(options.extension, source.suffix)
    target_name = f"{stem}{extension}"
    _validate_name(target_name)
    return source.with_name(target_name)


def _path_key(path):
    return str(Path(path).parent.resolve() / Path(path).name).casefold()


def _same_file(left, right):
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False


def preview_renames(files, options):
    absolute_files = [os.path.abspath(filename) for filename in files]
    rows = []
    target_counts = {}

    for index, source_path in enumerate(absolute_files):
        try:
            if not Path(source_path).is_file():
                raise ValueError("源文件不存在。")
            target_path = os.path.abspath(
                _target_for(
                    source_path,
                    options,
                    options.number_start + index,
                )
            )
            key = _path_key(target_path)
            target_counts[key] = target_counts.get(key, 0) + 1
            rows.append((source_path, target_path, "", key))
        except ValueError as error:
            rows.append((source_path, source_path, str(error), ""))

    previews = []
    for source_path, target_path, error, key in rows:
        if error:
            previews.append(
                RenamePreview(source_path, target_path, "不可改名", error, False, True)
            )
            continue

        if target_counts.get(key, 0) > 1:
            previews.append(
                RenamePreview(
                    source_path,
                    target_path,
                    "文件名重复",
                    "多个文件会改成同一个名字。",
                    False,
                    True,
                )
            )
            continue

        if Path(target_path).exists() and not _same_file(source_path, target_path):
            previews.append(
                RenamePreview(
                    source_path,
                    target_path,
                    "目标已存在",
                    "目标文件夹里已有同名文件。",
                    False,
                    True,
                )
            )
            continue

        will_rename = os.path.abspath(source_path) != os.path.abspath(target_path)
        previews.append(
            RenamePreview(
                source_path,
                target_path,
                "可以改名" if will_rename else "无需改名",
                "",
                will_rename,
                False,
            )
        )

    return tuple(previews)


def _log_path(folder):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(folder) / f"批量改名日志_{timestamp}.txt"


def _write_action_log(handle, index, preview, status, error):
    handle.write(f"序号：{index}\n")
    handle.write(f"处理时间：{datetime.now().isoformat(timespec='seconds')}\n")
    handle.write(f"原文件路径：{preview.source_path}\n")
    handle.write(f"新文件路径：{preview.target_path}\n")
    handle.write(f"原文件名：{Path(preview.source_path).name}\n")
    handle.write(f"新文件名：{Path(preview.target_path).name}\n")
    handle.write(f"处理结果：{status}\n")
    handle.write(f"失败原因：{error}\n")
    handle.write("-" * 60 + "\n")


def apply_renames(previews, log_folder=None):
    if any(preview.blocked for preview in previews):
        raise ValueError("预览中还有不能改名的文件，请先处理后再执行。")
    if not previews:
        raise ValueError("没有需要处理的文件。")

    log_folder = Path(log_folder or Path(previews[0].source_path).parent)
    log_folder.mkdir(parents=True, exist_ok=True)
    log_file = _log_path(log_folder)
    actions = []

    with log_file.open("w", encoding="utf-8") as handle:
        handle.write("批量改名操作日志\n")
        handle.write(f"生成时间：{datetime.now().isoformat(timespec='seconds')}\n")
        handle.write(f"文件数量：{len(previews)}\n")
        handle.write("=" * 60 + "\n")
        for index, preview in enumerate(previews, start=1):
            status = "跳过"
            error = ""
            if preview.will_rename:
                try:
                    Path(preview.source_path).rename(preview.target_path)
                    status = "成功"
                except OSError as rename_error:
                    status = "失败"
                    error = str(rename_error)

            _write_action_log(handle, index, preview, status, error)
            actions.append(
                RenameAction(preview.source_path, preview.target_path, status, error)
            )

    return RenameApplyResult(str(log_file), tuple(actions))
