import os
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook, load_workbook

from excel_merge_tool import build_merged_workbook, compare_merge_sources, inspect_merge_file


class MergePreflightTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.output = self.folder / "合并结果.xlsx"

    def source(self, filename, rows, title="明细", setup=None):
        path = self.folder / filename
        workbook = Workbook()
        workbook.active.title = "汇总"
        workbook.active.append(("错误页",))
        sheet = workbook.create_sheet(title)
        for row in rows:
            sheet.append(row)
        if setup:
            setup(sheet)
        workbook.save(path)
        workbook.close()
        return path

    def review(self, name, rows, **kwargs):
        path = self.source(name + ".xlsx", rows, **kwargs)
        return inspect_merge_file(path, kwargs.get("title", "明细"))

    def merge(self, sources, **kwargs):
        build_merged_workbook([s.path for s in sources], self.output,
                              reviewed_sources=sources, **kwargs)

    def test_default_sheet_and_changed_selection_with_preview(self):
        path = self.source("深圳.xlsx", [("十月报表",), ("单号", "数量"), ("0001", 2)])
        active = inspect_merge_file(path)
        self.assertEqual(active.sheet_name, "汇总")
        self.assertEqual(active.sheet_names, ("汇总", "明细"))
        selected = inspect_merge_file(path, "明细", 2)
        self.assertEqual(selected.headers, ("单号", "数量"))
        self.assertIn((3, ("0001", "2")), selected.preview)
        with self.assertRaisesRegex(ValueError, "找不到"):
            inspect_merge_file(path, "已移除")

    def test_reordering_missing_extra_and_explicit_consequence(self):
        ref = self.review("深圳", [("订单号", "名称", "数量", "金额"), ("a", "苹果", 1, 8)])
        moved = self.review("广州", [("订单号", "名称", "金额", "数量"), ("b", "梨", 5, 2)])
        missing = self.review("少列", [("订单号", "数量", "原价")])
        self.assertEqual(compare_merge_sources([ref, moved])[1].summary, "列顺序不同 · 2 处")
        details = "\n".join(compare_merge_sources([ref, moved])[1].details)
        self.assertIn("C 列", details)
        self.assertIn("“金额”会写入“数量”", details)
        detail = "\n".join(compare_merge_sources([ref, missing])[1].details)
        self.assertIn("缺少字段：名称、金额", detail)
        self.assertIn("多出字段：原价", detail)
        for headerless in (False, True):
            with self.subTest(headerless=headerless):
                with self.assertRaisesRegex(ValueError, "列顺序不同"):
                    self.merge([ref, moved], headerless=headerless)
                self.assertFalse(self.output.exists())

    def test_headerless_blocks_substantial_column_swap_along_with_renamed_fields(self):
        ref = self.review("深圳", [("订单号", "数量", "单价", "备注")])
        moved = self.review("广州", [("订单号", "单价", "数量", "说明")])
        self.assertFalse(compare_merge_sources([ref, moved], headerless=True)[1].ok)

    def test_headerless_all_text_or_reversed_numeric_records_are_valid(self):
        for index, rows in enumerate([
            [(1, 2), (2, 1)],
            [("深圳", "南山"), ("广州", "番禺")],
        ]):
            with self.subTest(rows=rows):
                sources = [self.review(f"无表头{index}-{n}", [row]) for n, row in enumerate(rows)]
                self.merge(sources, skip_rows=0, headerless=True)
                workbook = load_workbook(self.output, read_only=True)
                try:
                    self.assertEqual(list(workbook.active.values), rows)
                finally:
                    workbook.close()

    def test_wide_sheet_preview_includes_data_beyond_first_twelve_columns(self):
        cells = tuple(f"字段{i}" for i in range(1, 16))
        source = self.review("宽表", [cells, tuple(range(1, 16))])
        self.assertEqual(source.preview[0][1], cells)
        self.assertEqual(source.preview[1][1][-1], "15")

    def test_headerless_width_covers_rows_before_selected_header(self):
        first = self.source("甲.xlsx", [("大", "小", "还有数据"), ("甲", "乙")])
        second = self.source("乙.xlsx", [("大", "小"), ("丙", "丁")])
        selected = [inspect_merge_file(p, "明细", 2) for p in (first, second)]
        self.assertFalse(compare_merge_sources(selected, headerless=True)[1].ok)

    def test_blank_duplicate_formula_and_merged_headers(self):
        rows = [("订单号", "金额", "金额", None)] + [("a", 1, 2)] * 80 + [("b", 1, 2, 0)]
        blank = self.review("重名", rows)
        self.assertIn("B、C 列都叫", " ".join(blank.issues))
        self.assertIn("D 列下方有数据", " ".join(blank.issues))
        self.assertFalse(compare_merge_sources([blank])[0].ok)
        formula = self.review("公式", [("订单号", "=1")])
        self.assertIn("B1", " ".join(formula.issues))
        merged = self.review("合并", [("标题",), ("名", "号")], setup=lambda s:s.merge_cells("A1:B1"))
        self.assertIn("A1:B1", " ".join(merged.issues))
        flat = inspect_merge_file(merged.path, "明细", 2)
        self.assertFalse(flat.issues)
        def add_groups(sheet):
            sheet.merge_cells("A1:B1")
            sheet.merge_cells("C1:D1")
        grouped = self.source("分组.xlsx", [("含税", None, "不含税"), ("数量", "总价", "净额", "单价")],
                              setup=add_groups)
        self.assertTrue(inspect_merge_file(grouped, "明细", 2).issues)

    def test_block_missing_sources_order_changes_or_replacements(self):
        sources = [self.review(name, [("单号", "数量"), (name, 1)]) for name in ("深圳", "广州")]
        self.output.write_bytes(b"previous")
        with self.assertRaisesRegex(ValueError, "顺序"):
            build_merged_workbook([s.path for s in reversed(sources)], self.output,
                                  reviewed_sources=sources)
        replacement = self.source("替换.xlsx", [("单号", "金额")])
        os.replace(replacement, sources[1].path)
        with self.assertRaisesRegex(ValueError, "发生变化"):
            self.merge(sources)
        Path(sources[1].path).unlink()
        with self.assertRaisesRegex(ValueError, "无法复核"):
            self.merge(sources)
        self.assertEqual(self.output.read_bytes(), b"previous")

    def test_copy_during_merge_does_not_publish_stale_data(self):
        source = self.review("变更", [("单号", "数量"), ("00001", 1)])
        other = self.source("替换.xlsx", [("单号", "数量"), ("00002", 4)])
        self.output.write_bytes(b"previous")
        with self.assertRaisesRegex(ValueError, "发生变化"):
            self.merge([source], progress_callback=lambda *_: os.replace(other, source.path))
        self.assertEqual(self.output.read_bytes(), b"previous")
        self.assertFalse(list(self.folder.glob(".合并结果.*.xlsx")))

    def test_selected_sheets_supply_values_formulas_widths_and_merged_ranges(self):
        for compatibility in (False, True):
            with self.subTest(compatibility=compatibility):
                def style(sheet):
                    sheet.column_dimensions["A"].width = 26
                    if compatibility:
                        sheet.merge_cells("D3:E3")
                header = ("订单号", "数量", "金额", "备注", "补充")
                first = self.source("深圳.xlsx", [("九月",), header, ("000000000000000001", 2, "=B3*10", "一")],
                                    title="深圳明细", setup=style)
                second = self.source("广州.xlsx", [("十月",), header, ("000000000000000002", 3, "=B3*10", "二")],
                                     title="广州明细", setup=style)
                sources = [inspect_merge_file(first, "深圳明细", 2), inspect_merge_file(second, "广州明细", 2)]
                self.assertTrue(all(check.ok for check in compare_merge_sources(sources)))
                self.merge(sources, skip_rows=2)
                result = load_workbook(self.output)
                try:
                    sheet = result.active
                    self.assertEqual(sheet.max_row, 4)
                    self.assertEqual(sheet["A4"].value, "000000000000000002")
                    self.assertEqual(sheet["B4"].value, 3)
                    self.assertEqual(sheet["C4"].value, "=B4*10")
                    self.assertEqual(sheet.column_dimensions["A"].width, 26)
                    self.assertEqual("D4:E4" in sheet.merged_cells, compatibility)
                finally:
                    result.close()

    def test_unsafe_formula_in_selected_sheet_but_not_in_active_is_blocked(self):
        src = self.review("公式", [("名称", "金额"), ("a", "=汇总!A1")])
        with self.assertRaisesRegex(ValueError, "明细!B2"):
            self.merge([src])
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
