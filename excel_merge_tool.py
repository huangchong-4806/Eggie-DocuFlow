import os
import warnings
from copy import copy
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.formula.translate import Translator


SUPPORTED_EXTENSIONS = {".xlsx", ".xlsm"}


def discover_excel_files(folder):
    excel_files = []

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
            if filename.startswith(("~$", ".")):
                continue
            if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue

            path = Path(root, filename)
            if path.is_file():
                excel_files.append(str(path.resolve()))

    return excel_files


def copy_cell_style(source_cell, target_cell):
    if not source_cell.has_style:
        return

    target_cell.font = copy(source_cell.font)
    target_cell.fill = copy(source_cell.fill)
    target_cell.border = copy(source_cell.border)
    target_cell.alignment = copy(source_cell.alignment)
    target_cell.number_format = source_cell.number_format
    target_cell.protection = copy(source_cell.protection)


def copy_cell_value(source_cell, target_cell):
    value = source_cell.value

    if source_cell.data_type == "f" and isinstance(value, str):
        try:
            target_cell.value = Translator(
                value,
                origin=source_cell.coordinate,
            ).translate_formula(target_cell.coordinate)
        except Exception:
            target_cell.value = value
        return

    target_cell.value = value

    # Keep formula-looking source text as text instead of converting it to a formula.
    if (
        source_cell.data_type == "s"
        and isinstance(value, str)
        and value.startswith("=")
    ):
        target_cell.data_type = "s"


def format_file_size(size):
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024


def get_file_info(filename):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        workbook = load_workbook(
            filename,
            read_only=True,
            data_only=False,
            keep_links=False,
        )
        try:
            worksheet = workbook.active
            row_count = worksheet.max_row

            # Some exported workbooks incorrectly report A1 as their used range.
            if row_count <= 1 and os.path.getsize(filename) > 50 * 1024:
                worksheet.reset_dimensions()
                row_count = sum(1 for _ in worksheet.iter_rows())
        finally:
            workbook.close()

    return {
        "size": format_file_size(os.path.getsize(filename)),
        "rows": row_count,
    }


def build_merged_workbook(
    files,
    output_file,
    skip_rows=1,
    keep_merged_cells=True,
    progress_callback=None,
):
    output_workbook = Workbook()
    output_sheet = output_workbook.active
    output_sheet.title = "合并结果"

    current_row = 1
    is_first_sheet = True

    try:
        for file_index, filename in enumerate(files):
            workbook = load_workbook(filename)
            try:
                worksheet = workbook.active
                start_row = skip_rows + 1 if file_index > 0 else 1
                row_offset = current_row - start_row

                for row in worksheet.iter_rows(min_row=start_row):
                    for cell in row:
                        target_cell = output_sheet.cell(
                            row=cell.row + row_offset,
                            column=cell.column,
                        )
                        copy_cell_value(cell, target_cell)
                        copy_cell_style(cell, target_cell)

                if is_first_sheet:
                    for column_letter, column_dimension in (
                        worksheet.column_dimensions.items()
                    ):
                        output_sheet.column_dimensions[column_letter].width = (
                            column_dimension.width
                        )
                    is_first_sheet = False

                if keep_merged_cells:
                    for merged_range in worksheet.merged_cells.ranges:
                        min_col, min_row, max_col, max_row = merged_range.bounds
                        if min_row < start_row:
                            continue

                        output_sheet.merge_cells(
                            start_row=min_row + row_offset,
                            start_column=min_col,
                            end_row=max_row + row_offset,
                            end_column=max_col,
                        )

                current_row = output_sheet.max_row + 1
            finally:
                workbook.close()

            if progress_callback:
                progress_callback(file_index + 1, os.path.basename(filename))

        output_workbook.save(output_file)
    finally:
        output_workbook.close()
