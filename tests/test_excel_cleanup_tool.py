import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook, load_workbook
from openpyxl.worksheet._read_only import ReadOnlyWorksheet

from excel_cleanup_tool import (
    CleanupOptions,
    clean_workbook,
    preview_cleanup,
    workbook_sheet_names,
)


class ExcelCleanupToolTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source = self.root / "source.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "数据"
        sheet.append(["姓名", "数量", "日期", "计算"])
        sheet.append([" Alice  ", 1, date(2026, 8, 1), "=B2*2"])
        sheet.append(["Alice", 1, date(2026, 8, 1), "=B3*2"])
        sheet.append([None, None, None, None])
        sheet.append(["Bob   Smith", 2.5, date(2026, 8, 2), "=B5*2"])
        workbook.create_sheet("保留")
        workbook.save(self.source)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def options(self, **values):
        defaults = dict(
            sheet_name="数据",
            remove_empty_rows=True,
            trim_whitespace=True,
            deduplicate=True,
            duplicate_columns=(1, 2, 3),
            normalize_dates=True,
            normalize_numbers=True,
        )
        defaults.update(values)
        return CleanupOptions(**defaults)

    def test_preview_reports_changes_without_modifying_source(self):
        preview = preview_cleanup(self.source, self.options())

        self.assertEqual(workbook_sheet_names(self.source), ("数据", "保留"))
        self.assertEqual(preview.blank_rows, 1)
        self.assertEqual(preview.duplicate_rows, 1)
        self.assertEqual(preview.whitespace_cells, 2)
        self.assertEqual(preview.formula_cells, 3)

        workbook = load_workbook(self.source, data_only=False)
        try:
            self.assertEqual(workbook["数据"]["A2"].value, " Alice  ")
            self.assertEqual(workbook["数据"].max_row, 5)
        finally:
            workbook.close()

    def test_preview_reads_workbook_without_saved_dimension(self):
        original_init = ReadOnlyWorksheet.__init__

        def init_without_dimension(sheet, *args, **kwargs):
            original_init(sheet, *args, **kwargs)
            sheet._max_row = None
            sheet._max_column = None

        with patch.object(ReadOnlyWorksheet, "__init__", init_without_dimension):
            preview = preview_cleanup(self.source, self.options())

        self.assertEqual(preview.original_rows, 4)
        self.assertEqual(preview.original_columns, 4)

    def test_cleanup_saves_copy_keeps_other_sheet_and_writes_log(self):
        result = clean_workbook(self.source, self.root / "output", self.options())

        workbook = load_workbook(result.output_file, data_only=False)
        try:
            sheet = workbook["数据"]
            self.assertEqual(sheet.max_row, 3)
            self.assertEqual(sheet["A2"].value, "Alice")
            self.assertEqual(sheet["A3"].value, "Bob Smith")
            self.assertEqual(sheet["B3"].number_format, "#,##0.00")
            self.assertEqual(sheet["C2"].number_format, "yyyy-mm-dd")
            self.assertEqual(sheet["D2"].value, "=B2*2")
            self.assertEqual(sheet["D3"].value, "=B3*2")
            self.assertIn("保留", workbook.sheetnames)
        finally:
            workbook.close()

        self.assertEqual(load_workbook(self.source)["数据"].max_row, 5)
        self.assertEqual(result.final_rows, 2)
        log_text = Path(result.log_file).read_text(encoding="utf-8")
        self.assertIn("blank_rows=1", log_text)
        self.assertIn("duplicate_rows=1", log_text)
        self.assertIn(f"output_file={result.output_file}", log_text)

    def test_cleanup_can_keep_blank_and_duplicate_rows(self):
        options = self.options(
            remove_empty_rows=False,
            deduplicate=False,
            trim_whitespace=False,
            normalize_dates=False,
            normalize_numbers=False,
        )
        result = clean_workbook(self.source, self.root / "output", options)

        workbook = load_workbook(result.output_file)
        try:
            self.assertEqual(workbook["数据"].max_row, 5)
            self.assertEqual(workbook["数据"]["A2"].value, " Alice  ")
        finally:
            workbook.close()

    def save_sample(self, rows, setup=None):
        w=Workbook();s=w.active;s.title='数据'
        for row in rows:s.append(row)
        if setup:setup(w,s)
        w.save(self.source);w.close()

    def cleaned(self, **kwargs):
        result=clean_workbook(self.source,self.root/'output',CleanupOptions('数据',**kwargs))
        w=load_workbook(result.output_file);self.addCleanup(w.close)
        return w

    def test_hyperlink_follows_row_without_creating_phantom_content(self):
        def setup(w, s):
            s['A4'].hyperlink = 'https://example.com/second'
        self.save_sample([['项目'], ['一'], [None], ['二']], setup)
        w = self.cleaned()
        self.assertEqual(list(w.active.values), [('项目',), ('一',), ('二',)])
        self.assertEqual(w.active['A3'].hyperlink.target, 'https://example.com/second')
        self.assertEqual(w.active['A3'].hyperlink.ref, 'A3')

    def test_internal_hyperlink_target_follows_deleted_rows(self):
        from openpyxl.worksheet.hyperlink import Hyperlink
        def setup(w, s):
            s['B2'].hyperlink = Hyperlink(ref='B2', location="'数据'!A4", display='跳转')
            other = w.create_sheet('导航')
            other['A1'] = '跳转'
            other['A1'].hyperlink = "#'数据'!A4"
        self.save_sample([['项目','链接'], ['一','跳转'], [None,None], ['二',None]], setup)
        w = self.cleaned()
        self.assertEqual(w['数据']['B2'].hyperlink.location, "'数据'!A3")
        self.assertEqual(w['导航']['A1'].hyperlink.target, "#'数据'!A3")

    def test_filter_sort_and_freeze_follow_deleted_rows(self):
        def setup(w, s):
            s.auto_filter.ref = 'A1:B5'
            s.auto_filter.add_sort_condition('B2:B5')
            s.freeze_panes = 'B4'
        self.save_sample([['项目','数'],['一',1],[None,None],['二',2],['三',3]], setup)
        w = self.cleaned()
        s = w.active
        self.assertEqual(s.auto_filter.ref, 'A1:B4')
        self.assertEqual(s.auto_filter.sortState.ref, 'A1:B4')
        self.assertEqual(s.auto_filter.sortState.sortCondition[0].ref, 'B2:B4')
        self.assertEqual(s.freeze_panes, 'B3')
        self.assertEqual([v.pane for v in s.sheet_view.selection], ['topRight', 'bottomLeft', 'bottomRight'])

    def test_merged_region_moves_without_losing_following_value(self):
        self.save_sample([['类','金额'],[None,None],['组',10],[None,20],['下一组',30]],
                         lambda w,s:s.merge_cells('A3:A4'))
        w=self.cleaned()
        self.assertEqual(str(w.active.merged_cells),'A2:A3')
        self.assertEqual(w.active['A4'].value,'下一组')
        self.assertEqual(w.active['B4'].value,30)

    def test_cross_row_and_absolute_references_follow_deleted_rows(self):
        self.save_sample([['金额'],[100],[None],[20],[None,'=A2+$A$4']],
            lambda w,s:w.create_sheet('汇总').__setitem__('A1',"='数据'!A4"))
        w=self.cleaned()
        self.assertEqual(w['数据']['B4'].value,'=A2+$A$3')
        self.assertEqual(w['汇总']['A1'].value,"='数据'!A3")

    def test_boolean_numeric_and_text_keys_are_distinct_in_preview_and_output(self):
        self.save_sample([['ID'],[1],[True],[0],[False],['1'],[1.0],[True]])
        options=CleanupOptions('数据',deduplicate=True)
        self.assertEqual(preview_cleanup(self.source,options).duplicate_rows,2)
        w=self.cleaned(deduplicate=True)
        self.assertEqual([r[0] for r in list(w.active.values)[1:]],[1,True,0,False,'1'])
        self.assertIs(type(w.active['A3'].value),bool)

    def test_ranges_contract_and_other_sheet_local_references_stay(self):
        self.save_sample([['金额', '=SUM(A2:A5)'],[10],[None],[20],[30]],
            lambda w,s:w.create_sheet('保留').__setitem__('A1','=SUM(A2:A5)'))
        w=self.cleaned()
        self.assertEqual(w['数据']['B1'].value,'=SUM(A2:A4)')
        self.assertEqual(w['保留']['A1'].value,'=SUM(A2:A5)')

    def test_unsafe_merge_intersection_does_not_publish_output(self):
        self.save_sample([['类'],['合并'],[None],['尾']],lambda w,s:s.merge_cells('A2:A3'))
        with self.assertRaisesRegex(ValueError,'合并'):
            self.cleaned()
        self.assertEqual(list((self.root/'output').glob('*.xlsx')),[])

    def test_dynamic_reference_does_not_publish_output(self):
        self.save_sample([['金额'],[10],[None],[20,'=INDIRECT("A4")']])
        with self.assertRaisesRegex(ValueError,'公式'):
            self.cleaned()
        self.assertEqual(list((self.root/'output').glob('*.xlsx')),[])

    def test_range_endpoints_and_whole_rows_contract(self):
        self.save_sample([['金额','=SUM(A2:A5)+SUM(2:5)'],[None],[10],[20],[None],[30]])
        w=self.cleaned()
        self.assertEqual(w.active['B1'].value,'=SUM(A2:A3)+SUM(2:3)')

    def test_deleted_single_reference_is_blocked_not_silently_retargeted(self):
        self.save_sample([['金额'],[10],[None],[20,'=$A$3']])
        original=self.source.read_bytes()
        with self.assertRaisesRegex(ValueError,'公式'):self.cleaned()
        self.assertEqual(self.source.read_bytes(),original)
        self.assertEqual(list((self.root/'output').glob('*.xlsx')),[])

    def test_strings_and_other_sheet_references_are_not_rewritten(self):
        self.save_sample([['金额'],[10],[None],[20,'=IF(A4=20,"A4",保留!A4)']],
                         lambda w,s:w.create_sheet('保留'))
        w=self.cleaned()
        self.assertEqual(w.active['B3'].value,'=IF(A3=20,"A4",保留!A4)')

    def test_merged_styles_and_row_height_move_together(self):
        from openpyxl.styles import Font,Border,Side
        def setup(w,s):
            s.merge_cells('A3:B3');s['A3'].font=Font(bold=True)
            s['A3'].border=Border(bottom=Side(style='thin'))
            s.row_dimensions[3].height=36
        self.save_sample([['类别','金额'],[None,None],['组',None],['尾',30]],setup)
        w=self.cleaned()
        self.assertEqual(str(w.active.merged_cells),'A2:B2')
        self.assertTrue(w.active['A2'].font.bold)
        self.assertEqual(w.active['A2'].border.bottom.style,'thin')
        self.assertEqual(w.active.row_dimensions[2].height,36)

    def test_complex_formula_allowed_when_rows_are_not_deleted(self):
        self.save_sample([['金额'],[10],[None],[20,'=INDIRECT("A4")']])
        w=self.cleaned(remove_empty_rows=False)
        self.assertEqual(w.active['B4'].value,'=INDIRECT("A4")')

    def test_other_sheet_validation_and_chart_dependencies_block_deletion(self):
        from openpyxl.worksheet.datavalidation import DataValidation
        from openpyxl.chart import BarChart,Reference
        for kind in ('validation','chart'):
            with self.subTest(kind=kind):
                def setup(w,s):
                    other=w.create_sheet('录入')
                    if kind=='validation':
                        rule=DataValidation(type='list',formula1="'数据'!$A$4")
                        other.add_data_validation(rule);rule.add(other['A1'])
                    else:
                        chart=BarChart();chart.add_data(Reference(s,min_col=1,min_row=2,max_row=4))
                        other.add_chart(chart,'C1')
                self.save_sample([['金额'],[10],[None],[20]],setup)
                with self.assertRaisesRegex(ValueError,'规则|图表'):self.cleaned()
                self.assertEqual(list((self.root/'output').glob('*.xlsx')),[])


if __name__ == "__main__":
    unittest.main()
