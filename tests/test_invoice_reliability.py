"""Local, synthetic invoice layouts. No customer documents are stored in Git."""
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pymupdf
from openpyxl import load_workbook

from pdf_invoice_tool import TextBlock, convert_invoice_pdf, parse_invoice_blocks, write_invoice_workbook
from ui.pages.invoice_page import InvoicePageMixin


def flat_page(number="00000001", code="001234567890", page=1, rate="0%"):
    text = ([f"发票代码: {code}"] if code else []) + [
        f"发票号码: {number}", "开票日期: 2026年11月10日", "项目名称 数量 单价 金额 税率 税额",
        f"服务 1 100 100 {rate} 0.00", "合计 ¥100.00 ¥0.00", "价税合计(小写) ¥100.00",
    ]
    return [TextBlock(v, page, top=20*i) for i, v in enumerate(text)]


class InvoiceReliabilityTests(unittest.TestCase):
    def test_zero_is_distinct_from_missing_and_tax_text_is_preserved(self):
        for rate in ("0%", "免税", "不征税"):
            with self.subTest(rate=rate), tempfile.TemporaryDirectory() as temp:
                blocks = flat_page(rate=rate)
                invoice = parse_invoice_blocks(blocks)
                self.assertEqual(invoice.header["合计税额"], Decimal("0.00"))
                self.assertEqual(invoice.items[0].tax_amount, Decimal("0.00"))
                self.assertEqual(any(v.abnormal for v in invoice.validations), rate != "0%")
                path = Path(temp) / "result.xlsx"
                write_invoice_workbook(invoice, path)
                wb = load_workbook(path)
                try:
                    for cell in (wb["发票头信息"]["M2"], wb["明细表"]["H2"]):
                        self.assertEqual((cell.value, cell.data_type), (0, "n"))
                        self.assertNotIn('"-"', cell.number_format)
                    self.assertEqual(wb["明细表"]["G2"].value, 0 if rate == "0%" else rate)
                finally:
                    wb.close()
        missing = [replace(b, text=b.text.replace(" ¥0.00", "")) for b in flat_page()]
        invoice = parse_invoice_blocks(missing)
        self.assertIsNone(invoice.header["合计税额"])
        self.assertTrue(any(v.abnormal and "合计税额" in v.abnormal_fields for v in invoice.validations))

        explicit = flat_page() + [TextBlock("合计税额：***", 1, top=160),
                                  TextBlock("价税合计(小写) ¥100.00", 1, top=180)]
        self.assertIsNone(parse_invoice_blocks(explicit).header["合计税额"])

    def test_identity_uses_code_and_number_but_allows_continuations(self):
        old = flat_page()
        for second in (flat_page(code="009999999999", page=2),
                       flat_page(code="", page=2), flat_page(number="00000002", page=2),
                       flat_page(code="009999999999")):
            with self.subTest(second=second[0].text), self.assertRaisesRegex(ValueError, "多张发票"):
                parse_invoice_blocks(old + second)
        for code, number in (("001234567890", "00000001"), ("", "00000000000000000123")):
            first = flat_page(number, code)
            for full_header in (True, False):
                second = flat_page(number, code, page=2)
                if not full_header:
                    second = [b for b in second if "发票" not in b.text]
                parsed = parse_invoice_blocks(first + second)
                self.assertEqual((parsed.header["发票代码"], parsed.header["发票号码"]), (code, number))
                self.assertEqual(len(parsed.items), 2)

    def test_unruled_shifted_and_split_headings_keep_spec_separate(self):
        top = [(10,"项目名称"),(102,"规格"),(119,"型号"),(177,"单位"),(229,"数量"),
               (272,"单价"),(360,"金额"),(440,"税率/征收率"),(510,"税额")]
        values = [(10,"配件"),(99,"AB-12"),(177,"件"),(229,"1"),(272,"100"),
                  (360,"100"),(440,"免税"),(510,"0.00")]
        blocks = [TextBlock(v, 1, x, y, x + 12) for y, row in ((50, top), (74,values)) for x,v in row]
        item = parse_invoice_blocks(blocks).items[0]
        self.assertEqual((item.project_name, item.specification, item.unit), ("配件", "AB-12", "件"))
        self.assertEqual((item.tax_rate_text, item.tax_amount), ("免税", Decimal("0.00")))

    def test_actual_pdf_column_rules_and_different_widths_on_each_page(self):
        with tempfile.TemporaryDirectory() as temp:
            pdf = Path(temp) / "sample.pdf"
            with pymupdf.open() as doc:
                for page_number, shift in enumerate((0, 65), 1):
                    page = doc.new_page(width=680, height=400)
                    def write(x, y, text):
                        page.insert_text((x, y), text, fontsize=8, fontname="china-s")
                    write(10, 30, "发票号码:00000001")
                    write(220, 30, "开票日期:2026年11月10日")
                    columns = (10, 107+shift, 209+shift, 250+shift, 300+shift, 380+shift, 450+shift, 540+shift)
                    for x, label in zip(columns, ("项目名称","规格型号","单位","数量","单价","金额","税率","税额")):
                        write(x, 70, label)
                    page.draw_line((95+shift, 50), (95+shift, 210))
                    write(80+shift, 95, "泵")
                    for x, val in zip(columns[1:], ("AB12","件","1","100","100","0%","0")):
                        write(x, 95, val)
                    write(14, 110, "配件"); write(108+shift, 110, "XL")
                    if page_number == 2:
                        write(20, 170, "合计 ¥200.00 ¥0.00")
                        write(20, 190, "价税合计(小写) ¥200.00")
                doc.save(pdf)
            result = convert_invoice_pdf(pdf, Path(temp) / "out.xlsx")
            wb = load_workbook(result.output_file)
            try:
                rows = list(wb["明细表"].values)[1:]
                self.assertEqual(rows, [("泵配件","AB12XL","件",1,100,100,0,0)] * 2)
                self.assertEqual(result.abnormal_count, 0)
            finally:
                wb.close()

    def test_page_status_replaces_last_progress_for_all_outcomes(self):
        host = SimpleNamespace(invoice_source_files=["sample.pdf"], invoice_output_folder="out",
                               invoice_file_status_label=Mock(), start_background_task=Mock(),
                               show_invoice_complete_message=Mock())
        with patch("ui.pages.invoice_page.os.name", "nt"), patch("ui.pages.invoice_page.InvoiceBatchProcessThread"), \
             patch("ui.pages.invoice_page.QMessageBox"):
            InvoicePageMixin.convert_invoice(host)
            args, opts = host.start_background_task.call_args
            label = host.invoice_file_status_label.setText
            for error, ledger, text in (("", None, "需核对 1 个"),
                                       ("写入失败", None, "汇总未生成"),
                                       ("", SimpleNamespace(log_error="失败"), "日志未生成")):
                args[3](([SimpleNamespace(abnormal_count=1)], [], ledger, error))
                self.assertIn(text, label.call_args.args[0])
            args[3](([], [("invoice.pdf", "失败")], None, ""))
            self.assertIn("失败 1 个", label.call_args.args[0])
            args[4]("中断")
            self.assertIn("失败", label.call_args.args[0])
            opts["on_cancel"]()
            self.assertIn("已停止", label.call_args.args[0])
