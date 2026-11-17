"""Generated PDFs for party panels, continuation tables, notes and raw fields."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pymupdf
from openpyxl import load_workbook

from pdf_invoice_tool import ITEM_FIELDS, TextBlock, convert_invoice_pdfs, extract_invoice, parse_invoice_blocks


def make_sample(path, *, number="00000000000000000001", dates=("2026年11月10日",),
                roles=("购买方", "销售方"), continuation=None, notes=(), amount="100.00",
                unit_price="100.00", total="100.00", combined_titles=False, caption_offset=0):
    xs = (22, 140, 230, 295, 365, 510, 670, 775)
    with pymupdf.open() as doc:
        def put(x, y, text):
            if text:
                font = "china-s" if not text.isascii() else "helv"
                page.insert_text((x, y), text, fontname=font, fontsize=9)

        def item(y, name, price, money, positions=xs):
            values = (name, "T1", "件", "1", price, money, "0%", "0.00")
            for x, value in zip(positions, values):
                put(x, y, value)

        for index in range(2 if continuation is not None else 1):
            page = doc.new_page(width=915, height=410)
            put(22, 25, "发票号码:" + number)
            if dates[index % len(dates)]:
                put(440, 25, "开票日期:" + dates[index % len(dates)])
            if index == 0:
                if combined_titles:
                    put(22, 53, "购买方销售方")
                else:
                    for x, y, role in zip((22, 435), (53, 53 + caption_offset), roles):
                        put(x, y, role)
                for x, name, identity in ((22, "甲公司", "910000000000000001"),
                                          (435, "乙公司", "910000000000000002")):
                    put(x, 68, "名称:"); put(x + 60, 68, name)
                    put(x, 84, "税号:"); put(x + 60, 84, identity)
            if index == 0 or continuation == "repeated":
                for x, label in zip(xs, ITEM_FIELDS):
                    put(x, 112, label)
            if index == 0:
                item(144, "项目甲", unit_price, amount)
            else:
                if continuation != "note_only":
                    item(144, "项目乙", "20.00", "20.00")
                    positions = list(xs)
                    if continuation == "shifted":
                        positions[5], positions[6], positions[7] = 410, 510, 600
                    item(169, "折扣", "-20.00", "-20.00", positions)
            if index == 0 and continuation is not None:
                put(22, 215, "小计"); put(xs[5], 215, amount)
            elif continuation != "note_only" or index == 0:
                put(22, 215, "合计"); put(xs[5], 215, total); put(xs[7], 215, "0.00")
                put(22, 240, "价税合计(小写)"); put(xs[7], 240, total)
            if index < len(notes):
                value = notes[index]
                if value is not None:
                    page.draw_rect((20, 265, 680, 331))
                    page.draw_line((70, 265), (70, 331))
                    put(29, 300, "备注"); put(92, 300, value)
                    put(22, 359, "开票人:测试员")
                else:
                    put(22, 288, "备注:"); put(92, 310, "无框续页说明")
            if continuation == "note_only" and index == 0:
                put(22, 245, "合计"); put(xs[5], 245, total); put(xs[7], 245, "0.00")
                put(22, 258, "价税合计(小写)"); put(xs[7], 258, total)
        doc.save(path)


class InvoicePagesTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def read(self, **kwargs):
        path = self.root / "input.pdf"
        make_sample(path, **kwargs)
        return extract_invoice(path)

    def test_horizontal_and_reversed_panels(self):
        for roles in (("购买方", "销售方"), ("销售方", "购买方")):
            with self.subTest(roles=roles):
                invoice = self.read(roles=roles, caption_offset=-15 if roles[0] == "销售方" else 0)
                for role, name, tax_id in zip(roles, ("甲公司", "乙公司"), ("910000000000000001", "910000000000000002")):
                    self.assertEqual(invoice.header[role + "名称"], name)
                    self.assertEqual(invoice.header[role + "税号"], tax_id)
                self.assertFalse(any(v.abnormal for v in invoice.validations))

    def test_unclear_party_boundaries_require_review(self):
        invoice = self.read(combined_titles=True)
        self.assertEqual(invoice.header["购买方名称"], "")
        self.assertEqual(invoice.header["销售方税号"], "")
        self.assertTrue(any(v.abnormal and "购买方名称" in v.abnormal_fields for v in invoice.validations))

    def test_offsetting_rows_survive_with_and_without_repeated_header(self):
        for layout in ("repeated", "same"):
            with self.subTest(layout=layout):
                invoice = self.read(continuation=layout)
                self.assertEqual([i.project_name for i in invoice.items], ["项目甲", "项目乙", "折扣"])
                self.assertEqual([i.amount for i in invoice.items], [100, 20, -20])
                self.assertFalse(any(v.abnormal for v in invoice.validations))

    def test_partially_shifted_continuation_requests_review_of_specific_page(self):
        invoice = self.read(continuation="shifted")
        self.assertEqual([i.project_name for i in invoice.items], ["项目甲", "项目乙"])
        self.assertTrue(any(v.abnormal and "第 2 页" in v.note for v in invoice.validations))

    def test_notes_from_each_page_and_note_only_attachment(self):
        for notes, output in ((("", "分批交付"), "分批交付"), (("同一说明", "同一说明"), "同一说明"),
                              (("首批", "续批"), "第 1 页：首批\n第 2 页：续批"),
                              (("首批", None), "第 1 页：首批\n第 2 页：无框续页说明")):
            with self.subTest(notes=notes):
                invoice = self.read(continuation="note_only", notes=notes)
                self.assertEqual(invoice.header["备注"], output)
                self.assertEqual(len(invoice.items), 1)
                self.assertFalse(any(v.abnormal for v in invoice.validations))

    def test_flat_detail_keeps_invalid_amount_in_its_own_column(self):
        lines = ["发票号码:00000001", "开票日期:2026/11/11", "项目名称 数量 单价 金额 税率 税额",
                 "项目甲 1 1234.00 12,34.00 0% 0.00", "合计 1234.00 0.00", "价税合计(小写) 1234.00"]
        blocks = [TextBlock(t, 1, top=20*i) for i, t in enumerate(lines)]
        result = parse_invoice_blocks(blocks)
        self.assertEqual(len(result.items), 1)
        item = result.items[0]
        self.assertEqual((item.quantity, item.unit_price, item.amount, item.tax_amount), (1, 1234, None, 0))
        self.assertTrue(any(v.item_row == "1" and "12,34.00" in v.note for v in result.validations))

    def test_ambiguous_last_page_note_preserves_earlier_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "base.pdf"
            make_sample(path, notes=("合同甲",))
            from pdf_invoice_tool import _pdf_text_blocks
            blocks, _, first = _pdf_text_blocks(path)
        blocks += [TextBlock("备", 2, 20, 155, 29), TextBlock("注", 2, 20, 170, 29),
                   TextBlock("不明归属", 2, 200, 160, 240)]
        invoice = parse_invoice_blocks(blocks, boxed_remark={1: first})
        self.assertEqual(invoice.header["备注"], "合同甲")
        self.assertTrue(any(v.abnormal_fields == "备注" and "第 2 页" in v.note for v in invoice.validations))

    def test_invalid_grouping_or_dates_export_raw_evidence_in_batch(self):
        cases = [
            ("1,234.00", "1,234.00", "2024年2月29日", 1234, False),
            ("12,34.00", "1234.00", "2026年2月30日", None, True),
            ("1234.00", "1,,234.00", "", 1234, True),
            (",1234.00", ",1234.00", "待核", None, True),
        ]
        pdfs = []
        for n, (amount, total, date, _, _) in enumerate(cases, 1):
            pdf = self.root / f"source{n}.pdf"
            make_sample(pdf, number=f"{n:020d}", amount=amount, unit_price="1234.00", total=total, dates=(date,))
            pdfs.append(pdf)
        results, failures = convert_invoice_pdfs(pdfs, self.root)
        self.assertEqual(failures, [])
        self.assertEqual(len(results), len(cases))
        for result, (amount, total, date, value, abnormal) in zip(results, cases):
            with self.subTest(amount=amount):
                self.assertEqual(bool(result.abnormal_count), abnormal)
                wb = load_workbook(result.output_file)
                try:
                    self.assertEqual(wb["明细表"]["F2"].value, value)
                    cell_date = wb["发票头信息"]["C2"].value
                    checks = list(wb["校验结果"].values)[1:]
                    messages = "\n".join(str(r[-1]) for r in checks)
                    if abnormal:
                        self.assertEqual(cell_date, date or None)
                        self.assertTrue(any(r[3] == "异常" and r[4] == "开票日期" for r in checks))
                        if value is None:
                            self.assertIn(amount, messages)
                        if total.startswith(",") or ",," in total:
                            self.assertIsNone(wb["发票头信息"]["L2"].value)
                            self.assertIn(total, messages)
                    else:
                        self.assertIsInstance(cell_date, datetime)
                finally:
                    wb.close()
