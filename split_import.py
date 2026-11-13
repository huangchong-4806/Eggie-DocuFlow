"""Convert plain data sheets in memory for the existing category splitter."""
import csv
from io import BytesIO, StringIO
from pathlib import Path
import struct

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


def csv_rows(raw, encoding, delimiter):
    reader = csv.reader(StringIO(raw.decode(encoding, errors="strict"), newline=""),
                        delimiter=delimiter, strict=True)
    width = None
    for row in reader:
        if not row:
            yield []
            continue
        if width is None:
            width = len(row)
        if len(row) != width:
            raise ValueError(f"CSV 第 {reader.line_num} 行列数与表头不一致，请核对分隔符。")
        if any(len(value) > 32767 for value in row):
            raise ValueError(f"CSV 第 {reader.line_num} 行有字段超过 Excel 单元格长度。")
        yield row


def guess_csv(raw):
    for encoding in ("utf-8-sig","gbk"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        try:
            delimiter = csv.Sniffer().sniff(text[:16384], delimiters=",;\t").delimiter
        except csv.Error:
            delimiter = ","
        return encoding, delimiter
    return "utf-8-sig", ","


def _check_xls_records(book):
    # xlrd skips drawing objects, filters and validation. Reject those before converting.
    offset, end = book.base, book.base + book.stream_len
    rejected = {0x005D,0x00EC,0x00EB,0x01B0,0x01B1,0x01BE,0x01B2,0x009D,0x009E,
                0x00B0,0x01B8,0x001C,0x00D3}
    while offset + 4 <= end:
        opcode, size = struct.unpack_from("<HH", book.mem, offset)
        offset += 4
        if offset + size > end:
            raise ValueError("XLS 工作簿结构不完整。")
        if opcode in rejected:
            raise ValueError("此 XLS 含图形、筛选或其他不能可靠转换的内容，请先另存普通明细表。")
        if opcode in (6, 0x206, 0x406) and size >= 14:
            result = book.mem[offset+6:offset+14]
            if result[6:] == b"\xff\xff" and result[0] in (2,3):
                raise ValueError("XLS 公式结果为空或错误，请在 Excel 重新计算并保存。")
        offset += size


def _copy_xls(data, wb):
    import xlrd
    try:
        book = xlrd.open_workbook(file_contents=data, formatting_info=True, on_demand=True)
    except xlrd.XLRDError as exc:
        raise ValueError("无法读取此 XLS，请检查文件格式或加密状态。") from exc
    try:
        _check_xls_records(book)
        wb.remove(wb.active)
        styles = {}
        def color(index):
            rgb = book.colour_map.get(index)
            return ("FF" + "".join(f"{c:02X}" for c in rgb)) if rgb else None
        def style(idx):
            if idx not in styles:
                xf = book.xf_list[idx]
                f, bg, align, border = book.font_list[xf.font_index], xf.background, xf.alignment, xf.border
                if bg.fill_pattern not in (0,1) or border.diag_up or border.diag_down:
                    raise ValueError("XLS 含不支持的填充或对角边框，请先另存普通明细表。")
                sides = ["none","thin","medium","dashed","dotted","thick","double","hair","mediumDashed",
                         "dashDot","mediumDashDot","dashDotDot","mediumDashDotDot","slantDashDot"]
                def side(name):
                    line = getattr(border,name+"_line_style")
                    return Side(style=sides[line],color=color(getattr(border,name+"_colour_index"))) if line else Side()
                fill = PatternFill()
                if bg.fill_pattern:
                    fill = PatternFill("solid", fgColor=color(bg.pattern_colour_index) or "FF000000")
                rotation = align.rotation
                angle = 90 + abs(rotation) if -90 <= rotation < 0 else rotation
                styles[idx] = (Font(name=f.name,sz=f.height/20,b=f.bold,i=f.italic,strike=f.struck_out,
                                   color=color(f.colour_index), u={0:None,1:"single",2:"double",33:"singleAccounting",34:"doubleAccounting"}.get(f.underline_type)),
                               fill, Alignment(horizontal=("general","left","center","right","fill","justify","centerContinuous","distributed")[align.hor_align],
                                               vertical=("top","center","bottom","justify","distributed")[align.vert_align], wrap_text=bool(align.text_wrapped),
                                               indent=align.indent_level,textRotation=angle),
                               Border(**{n:side(n) for n in ("left","right","top","bottom")}),
                               book.format_map[xf.format_key].format_str)
            return styles[idx]
        for sheet in book.sheets():
            if sheet.nrows * sheet.ncols > 2000000:
                raise ValueError("XLS 工作表超过可转换的 200 万单元格。")
            ws = wb.create_sheet(sheet.name)
            ws.sheet_state = ("visible","hidden","veryHidden")[sheet.visibility]
            for r,info in sheet.rowinfo_map.items():
                d=ws.row_dimensions[r+1]
                d.hidden=bool(info.hidden)
                if info.has_default_height==0:
                    d.height=info.height/20
            for c,info in sheet.colinfo_map.items():
                d=ws.column_dimensions[get_column_letter(c+1)]
                d.width=info.width/256
                d.hidden=bool(info.hidden)
            for r in range(sheet.nrows):
                for c,cell in enumerate(sheet.row(r)):
                    if cell.ctype==xlrd.XL_CELL_EMPTY:
                        continue
                    if cell.ctype==xlrd.XL_CELL_ERROR:
                        raise ValueError(f"{sheet.name} 第 {r+1} 行存在 Excel 错误值。")
                    dest=ws.cell(r+1,c+1)
                    value=cell.value
                    if cell.ctype==xlrd.XL_CELL_DATE:
                        value=xlrd.xldate_as_datetime(value,book.datemode)
                        if 0<=cell.value<1: value=value.time()
                    elif cell.ctype==xlrd.XL_CELL_BOOLEAN:
                        value=bool(value)
                    elif cell.ctype==xlrd.XL_CELL_BLANK:
                        value=None
                    dest.value=value
                    if isinstance(value,str):dest.data_type="s"
                    dest.font,dest.fill,dest.alignment,dest.border,dest.number_format=style(cell.xf_index)
            for r0,r1,c0,c1 in sheet.merged_cells:
                ws.merge_cells(start_row=r0+1,end_row=r1,start_column=c0+1,end_column=c1)
    finally:
        book.release_resources()


def workbook_bytes(path, raw, encoding="utf-8-sig", delimiter=","):
    suffix=Path(path).suffix.lower()
    if suffix==".xlsx":
        return raw
    wb=Workbook()
    try:
        if suffix==".xls":
            _copy_xls(raw,wb)
        elif suffix==".csv":
            ws=wb.active
            ws.title="CSV"
            for i,row in enumerate(csv_rows(raw,encoding,delimiter),1):
                if len(row)>16384 or i>1048576 or i*len(row)>2000000:
                    raise ValueError("CSV 超出可处理范围，请缩小数据量。")
                for j,value in enumerate(row,1):
                    cell=ws.cell(i,j,value)
                    cell.data_type="s"
        else:
            raise ValueError("支持 .xlsx、.xls 和 .csv 文件。")
        with BytesIO() as buffer:
            wb.save(buffer)
            return buffer.getvalue()
    finally:
        wb.close()
