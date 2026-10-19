import re
from bisect import bisect_left, bisect_right
from copy import copy
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.formula import Tokenizer
from openpyxl.utils.cell import coordinate_from_string
from openpyxl.worksheet.views import Selection

from utils.file_helper import available_output_path, publish_output, temporary_output


SUPPORTED_SUFFIXES = {".xlsx", ".xlsm"}


@dataclass(frozen=True)
class CleanupOptions:
    sheet_name: str
    header_row: int = 1
    remove_empty_rows: bool = True
    trim_whitespace: bool = True
    deduplicate: bool = False
    duplicate_columns: tuple = ()
    normalize_dates: bool = False
    normalize_numbers: bool = False


@dataclass(frozen=True)
class CleanupPreview:
    source_file: str
    sheet_name: str
    headers: tuple
    original_rows: int
    original_columns: int
    blank_rows: int
    duplicate_rows: int
    whitespace_cells: int
    date_cells: int
    number_cells: int
    formula_cells: int


@dataclass(frozen=True)
class CleanupResult:
    output_file: str
    log_file: str
    preview: CleanupPreview
    final_rows: int
    removed_rows: int


def _source_path(source_file):
    source = Path(source_file).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Excel 文件不存在：{source}")
    if source.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError("只支持 .xlsx 和 .xlsm 文件。")
    return source


def workbook_sheet_names(source_file):
    source = _source_path(source_file)
    workbook = load_workbook(
        source,
        read_only=True,
        data_only=False,
        keep_vba=source.suffix.lower() == ".xlsm",
    )
    try:
        return tuple(workbook.sheetnames)
    finally:
        workbook.close()


def _clean_text(value):
    if not isinstance(value, str) or value.startswith("="):
        return value
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(lines).strip()


def _is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _row_values(row, trim_whitespace):
    values = []
    for cell in row:
        value = cell.value
        values.append(_clean_text(value) if trim_whitespace else value)
    return tuple(values)


def _selected_key(values, columns):
    selected = values if not columns else tuple(
        values[index - 1] if index <= len(values) else None for index in columns
    )
    # Excel logical values are distinct from numbers; 1 and 1.0 remain numeric equals.
    return tuple(("number" if isinstance(v, (int, float)) and not isinstance(v, bool)
                  else type(v).__name__, v) for v in selected)


def _sheet_preview(source, sheet, options):
    if sheet.max_row is None or sheet.max_column is None:
        sheet.calculate_dimension(force=True)
    max_row = max(sheet.max_row or 1, 1)
    max_column = max(sheet.max_column or 1, 1)
    if options.header_row < 1 or options.header_row > max_row:
        raise ValueError("表头行超出工作表范围。")
    header_cells = next(
        sheet.iter_rows(
            min_row=options.header_row,
            max_row=options.header_row,
            max_col=max_column,
        )
    )
    headers = tuple(
        str(cell.value).strip() if cell.value is not None else f"第 {index} 列"
        for index, cell in enumerate(header_cells, 1)
    )

    blank_rows = 0
    duplicate_rows = 0
    whitespace_cells = 0
    date_cells = 0
    number_cells = 0
    formula_cells = 0
    seen = set()
    for row_number, row in enumerate(sheet.iter_rows(), 1):
        for cell in row:
            value = cell.value
            if isinstance(value, str):
                if value.startswith("="):
                    formula_cells += 1
                elif _clean_text(value) != value:
                    whitespace_cells += 1
            elif isinstance(value, (datetime, date)):
                date_cells += 1
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                number_cells += 1

        if row_number <= options.header_row:
            continue
        values = _row_values(row, options.trim_whitespace)
        if all(_is_blank(value) for value in values):
            blank_rows += 1
            continue
        if options.deduplicate:
            key = _selected_key(values, options.duplicate_columns)
            if key in seen:
                duplicate_rows += 1
            else:
                seen.add(key)

    return CleanupPreview(
        str(source),
        options.sheet_name,
        headers,
        max(0, max_row - options.header_row),
        max_column,
        blank_rows,
        duplicate_rows,
        whitespace_cells,
        date_cells,
        number_cells,
        formula_cells,
    )


def preview_cleanup(source_file, options):
    source = _source_path(source_file)
    workbook = load_workbook(
        source,
        read_only=True,
        data_only=False,
        keep_vba=source.suffix.lower() == ".xlsm",
    )
    try:
        if options.sheet_name not in workbook.sheetnames:
            raise ValueError("选择的工作表不存在。")
        return _sheet_preview(source, workbook[options.sheet_name], options)
    finally:
        workbook.close()


def _rewrite_formula(formula, formula_sheet, target_sheet, removed):
    """Adjust A1 references for row deletion, not for copying a formula."""
    def fail():
        raise ValueError('删除行涉及无法安全调整的公式引用，请取消删除空行和重复行，或先在 Excel 中处理。')
    try:
        tokens = Tokenizer(formula).items
    except Exception:
        fail()
    for token in tokens:
        if token.type == 'FUNC' and token.subtype == 'OPEN':
            if token.value[:-1].upper().split('.')[-1] in {'INDIRECT', 'OFFSET'}:
                fail()
        if token.type != 'OPERAND' or token.subtype != 'RANGE':
            continue
        raw = token.value
        prefix, ref = raw.rsplit('!', 1) if '!' in raw else ('', raw)
        sheet_name = prefix[1:-1].replace("''", "'") if prefix.startswith("'") and prefix.endswith("'") else prefix
        if '[' in prefix or ':' in prefix:
            fail()
        # Unqualified references on other sheets are unaffected.
        active = sheet_name.casefold() == target_sheet.casefold() if prefix else formula_sheet == target_sheet
        if not active:
            continue
        if re.fullmatch(r'\$?[A-Za-z]{1,3}:\$?[A-Za-z]{1,3}', ref):
            continue
        parts = ref.split(':')
        if len(parts) not in (1, 2):
            fail()
        matches = [re.fullmatch(r'(\$?[A-Za-z]{1,3})(\$?)([1-9][0-9]*)', v) for v in parts]
        if not all(matches):
            # Whole-row ranges are supported; names/structured references are not guessed.
            matches = [re.fullmatch(r'()(\$?)([1-9][0-9]*)', v) for v in parts] if len(parts) == 2 else []
        if not matches or not all(matches):
            fail()
        rows = [int(m[3]) for m in matches]
        if any(r > 1048576 for r in rows) or rows != sorted(rows):
            fail()
        start, end = rows[0], rows[-1]
        if len(rows) == 1:
            if start in removed:
                fail()
            adjusted = [start - bisect_left(removed, start)]
        else:
            remaining = end - start + 1 - (bisect_right(removed, end) - bisect_left(removed, start))
            if not remaining:
                fail()
            first = start - bisect_left(removed, start)
            adjusted = [first, first + remaining - 1]
        rewritten = ':'.join(f'{m[1]}{m[2]}{r}' for m, r in zip(matches, adjusted))
        token.value = (prefix + '!' if prefix else '') + rewritten
    return '=' + ''.join(t.value for t in tokens)


def _delete_rows_safely(sheet, remove_rows):
    if not remove_rows:
        return
    workbook = sheet.parent
    # These structures also contain row references and need Excel's own editor.
    if workbook.defined_names or any(
        other.defined_names or other.tables or other.conditional_formatting
        or other.data_validations.count or other._charts or other._pivots
        or other.print_area or other.print_title_rows or other.print_title_cols
        for other in workbook
    ):
        raise ValueError('工作簿含命名区域、表格、图表或规则，无法安全调整删除行后的引用。请取消删除空行和重复行，或先在 Excel 中处理。')
    merged = list(sheet.merged_cells.ranges)
    for region in merged:
        if bisect_right(remove_rows, region.max_row) > bisect_left(remove_rows, region.min_row):
            raise ValueError(f'要删除的行与合并单元格 {region} 交叉，请先在 Excel 中处理合并区域。')
    # Compute everything before changing structure, including dependent worksheets.
    updates = []
    link_updates = []
    for other in workbook:
        for row in other:
            for cell in row:
                if other is sheet and cell.row in remove_rows:
                    continue
                if cell.hyperlink:
                    link = copy(cell.hyperlink)
                    if link.location and not link.target:
                        link.location = _rewrite_formula('='+link.location, other.title, sheet.title, remove_rows)[1:]
                    if link.target and link.target.startswith('#'):
                        link.target = '#' + _rewrite_formula('='+link.target[1:], other.title, sheet.title, remove_rows)[1:]
                    dest_row = cell.row - bisect_left(remove_rows, cell.row) if other is sheet else cell.row
                    link_updates.append((other, dest_row, cell.column, link))
                if cell.data_type != 'f':
                    continue
                if not isinstance(cell.value, str):
                    raise ValueError('删除行涉及数组公式，无法安全调整，请先在 Excel 中处理。')
                formula = _rewrite_formula(cell.value, other.title, sheet.title, remove_rows)
                dest_row = cell.row - bisect_left(remove_rows, cell.row) if other is sheet else cell.row
                updates.append((other, dest_row, cell.column, formula))
    dimensions = [(r, copy(d)) for r, d in sheet.row_dimensions.items() if r not in remove_rows]
    auto_filter = copy(sheet.auto_filter)
    if auto_filter.ref:
        auto_filter.ref = _rewrite_formula('='+auto_filter.ref, sheet.title, sheet.title, remove_rows)[1:]
        if auto_filter.sortState:
            auto_filter.sortState = copy(auto_filter.sortState)
            auto_filter.sortState.ref = _rewrite_formula('='+auto_filter.sortState.ref, sheet.title, sheet.title, remove_rows)[1:]
            auto_filter.sortState.sortCondition = [copy(condition) for condition in auto_filter.sortState.sortCondition]
            for condition in auto_filter.sortState.sortCondition:
                condition.ref = _rewrite_formula('='+condition.ref, sheet.title, sheet.title, remove_rows)[1:]
    freeze = sheet.freeze_panes
    if freeze:
        col, row = coordinate_from_string(freeze)
        freeze = f'{col}{row - bisect_left(remove_rows, row)}'
    for region in merged:
        sheet.unmerge_cells(str(region))
    for row in reversed(remove_rows):
        sheet.delete_rows(row, 1)
    sheet.row_dimensions.clear()
    for old_row, dimension in dimensions:
        dimension.index = old_row - bisect_left(remove_rows, old_row)
        sheet.row_dimensions[dimension.index] = dimension
    for region in merged:
        shift = bisect_left(remove_rows, region.min_row)
        sheet.merge_cells(start_row=region.min_row-shift, end_row=region.max_row-shift,
                          start_column=region.min_col, end_column=region.max_col)
    for other, row, col, formula in updates:
        other.cell(row, col, formula)
    for other, row, col, link in link_updates:
        other.cell(row, col).hyperlink = link
    sheet.auto_filter = auto_filter
    if freeze:
        sheet.sheet_view.selection = [Selection()]
        sheet.freeze_panes = freeze


def _apply_cleanup(sheet, options, progress_callback=None):
    total_rows = max(sheet.max_row, 1)
    if options.trim_whitespace or options.normalize_dates or options.normalize_numbers:
        for row_number, row in enumerate(sheet.iter_rows(), 1):
            for cell in row:
                value = cell.value
                if options.trim_whitespace and isinstance(value, str) and not value.startswith("="):
                    cell.value = _clean_text(value)
                    value = cell.value
                if options.normalize_dates and isinstance(value, datetime):
                    cell.number_format = (
                        "yyyy-mm-dd hh:mm:ss"
                        if value.time() != time(0, 0)
                        else "yyyy-mm-dd"
                    )
                elif options.normalize_dates and isinstance(value, date):
                    cell.number_format = "yyyy-mm-dd"
                if options.normalize_numbers and isinstance(value, (int, float)) and not isinstance(value, bool):
                    cell.number_format = "#,##0" if float(value).is_integer() else "#,##0.00"
            if progress_callback and row_number % 200 == 0:
                progress_callback(row_number, total_rows, f"正在清理第 {row_number} 行")

    remove_rows = []
    seen = set()
    for row in sheet.iter_rows(
        min_row=options.header_row + 1,
        max_row=sheet.max_row,
        max_col=sheet.max_column,
    ):
        values = tuple(cell.value for cell in row)
        if all(_is_blank(value) for value in values):
            if options.remove_empty_rows:
                remove_rows.append(row[0].row)
            continue
        if options.deduplicate:
            key = _selected_key(values, options.duplicate_columns)
            if key in seen:
                remove_rows.append(row[0].row)
            else:
                seen.add(key)

    remove_rows.sort()
    _delete_rows_safely(sheet, remove_rows)
    if progress_callback:
        progress_callback(total_rows, total_rows, "数据清理完成，正在保存新文件")
    return len(remove_rows)


def _write_log(log_file, source, options, preview, output_file, final_rows, removed_rows):
    with Path(log_file).open("w", encoding="utf-8") as handle:
        handle.write("Eggie DocuFlow Excel 数据清理日志\n")
        handle.write(f"来源文件：{source}\n")
        handle.write(f"工作表：{options.sheet_name}\n")
        handle.write(f"表头行：{options.header_row}\n")
        handle.write(f"删除空白行：{options.remove_empty_rows}\n")
        handle.write(f"清理文字空格：{options.trim_whitespace}\n")
        handle.write(f"排重：{options.deduplicate}\n")
        handle.write(f"排重列：{','.join(map(str, options.duplicate_columns)) or '整行'}\n")
        handle.write(f"统一日期显示：{options.normalize_dates}\n")
        handle.write(f"统一数字显示：{options.normalize_numbers}\n\n")
        handle.write("匹配结果：\n")
        handle.write(f"original_rows={preview.original_rows}\n")
        handle.write(f"blank_rows={preview.blank_rows}\n")
        handle.write(f"duplicate_rows={preview.duplicate_rows}\n")
        handle.write(f"whitespace_cells={preview.whitespace_cells}\n")
        handle.write(f"date_cells={preview.date_cells}\n")
        handle.write(f"number_cells={preview.number_cells}\n")
        handle.write(f"formula_cells={preview.formula_cells}\n\n")
        handle.write("计算过程：\n")
        handle.write(f"removed_rows={removed_rows}\n")
        handle.write(f"final_rows={final_rows}\n\n")
        handle.write("文件生成状态：\n")
        handle.write(f"output_file={output_file}\n")
        handle.write(f"log_file={log_file}\n")


def clean_workbook(
    source_file,
    output_folder,
    options,
    progress_callback=None,
):
    source = _source_path(source_file)
    output_folder = Path(output_folder).expanduser().resolve()
    output_folder.mkdir(parents=True, exist_ok=True)
    preview = preview_cleanup(source, options)
    keep_vba = source.suffix.lower() == ".xlsm"
    workbook = load_workbook(source, data_only=False, keep_vba=keep_vba)
    temporary_file = None
    try:
        if options.sheet_name not in workbook.sheetnames:
            raise ValueError("选择的工作表不存在。")
        sheet = workbook[options.sheet_name]
        removed_rows = _apply_cleanup(sheet, options, progress_callback)
        final_rows = max(0, sheet.max_row - options.header_row)
        output_file = available_output_path(
            output_folder / f"{source.stem}_清理结果{source.suffix.lower()}"
        )
        temporary_file = temporary_output(output_file)
        workbook.save(temporary_file)
        output_file = Path(publish_output(temporary_file, output_file))
    finally:
        workbook.close()
        if temporary_file:
            Path(temporary_file).unlink(missing_ok=True)

    log_file = available_output_path(output_file.with_name(f"{output_file.stem}_日志.txt"))
    _write_log(
        log_file,
        source,
        options,
        preview,
        output_file,
        final_rows,
        removed_rows,
    )
    return CleanupResult(
        str(output_file),
        str(log_file),
        preview,
        final_rows,
        removed_rows,
    )
