"""Regression fixtures are synthetic; no customer invoices are committed."""
import hashlib
import tempfile
import unittest
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pymupdf
from openpyxl import load_workbook

from pdf_invoice_tool import (
    _deduplicated_text_page,
    _to_decimal,
    convert_invoice_pdf,
    convert_invoice_pdfs,
    extract_invoice,
    write_invoice_ledger,
    write_invoice_workbook,
)
from ui.pages.invoice_page import InvoicePageMixin


def make_invoice(path, copies=1, pages=1):
    """A repeated real item row, leading-zero ID, and invisible overprints."""
    document = pymupdf.open()
    for _ in range(pages):
        page = document.new_page(width=595, height=400)
        fields = [
            (350, 25, "发票号码:"), (405, 25, "00000000000000112233"),
            (350, 45, "开票日期:2026年11月10日"),
            (30, 70, "名称:"), (60, 70, "测试购买方"),
            (318, 70, "名称:"), (348, 70, "测试销售方"),
            (30, 90, "纳税人识别号:"), (100, 90, "91310000123456789X"),
            (318, 90, "纳税人识别号:"), (390, 90, "91310000987654321X"),
            (10, 120, "项目名称"), (125, 120, "规格型号"),
            (200, 120, "单位"), (270, 120, "数量"),
            (330, 120, "单价"), (400, 120, "金额"),
            (470, 120, "税率"), (550, 120, "税额"),
        ]
        for y in (145, 175):
            fields.extend([
                (10, y, "测试商品"), (125, y, "AA-1111"), (200, y, "台"),
                (270, y, "11"), (330, y, "11.11"), (400, y, "122.21"),
                (470, y, "13%"), (550, y, "15.89"),
            ])
        if pages == 1 or len(document) == pages:
            fields.extend([
                (10, 250, "合计"), (400, 250, str(Decimal('244.42') * pages)),
                (550, 250, str(Decimal('31.78') * pages)),
                (10, 275, "价税合计(小写)"),
                (400, 275, str(Decimal('276.20') * pages)),
                (10, 305, "备"), (10, 320, "注"),
                (35, 295, "REF-2026-001"), (35, 335, "分批交付"),
                (35, 375, "开票人:测试"),
            ])
        else:
            fields.append((10, 250, "小计"))
        for x, y, text in fields:
            font = "china-s" if any(ord(char) > 127 for char in text) else "helv"
            page.insert_text((x, y), text, fontsize=8, fontname=font)
            for _ in range(copies - 1):
                page.insert_text((x, y), text, fontsize=8, fontname=font, render_mode=3)
    document.save(path)
    document.close()


class InvoiceOverprintTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def test_exact_overprints_match_plain_invoice_without_merging_real_rows(self):
        plain = self.root / 'plain.pdf'
        make_invoice(plain)
        expected = extract_invoice(plain)
        self.assertEqual(expected.header['发票号码'], '00000000000000112233')
        self.assertEqual(len(expected.items), 2)
        self.assertEqual(expected.items[0].quantity, Decimal('11'))
        self.assertEqual(expected.items[0].specification, 'AA-1111')
        self.assertEqual(expected.header['备注'], 'REF-2026-001\n分批交付')
        self.assertFalse(any(record.abnormal for record in expected.validations))
        for copies in (2, 3):
            with self.subTest(copies=copies):
                source = self.root / f'overprint-{copies}.pdf'
                make_invoice(source, copies=copies)
                digest = hashlib.sha256(source.read_bytes()).digest()
                actual = extract_invoice(source)
                self.assertEqual(asdict(actual), asdict(expected))
                self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), digest)

    def test_repeated_rows_on_different_pages_are_kept(self):
        source = self.root / 'multipage.pdf'
        make_invoice(source, copies=2, pages=2)
        invoice = extract_invoice(source)
        self.assertEqual(len(invoice.items), 4)
        self.assertEqual(sum(item.amount for item in invoice.items), Decimal('488.84'))
        self.assertFalse(any(record.abnormal for record in invoice.validations))

    def test_dedupe_does_not_remove_nearby_glyphs_different_fonts_or_images(self):
        char = dict(object_type='char', text='1', fontname='FontA', size=10,
                    upright=True, x0=10, x1=15, top=20, bottom=30)
        chars = [char, dict(char), dict(char, x0=10.1, x1=15.1),
                 dict(char, top=40, bottom=50), dict(char, fontname='FontB')]
        picture = dict(object_type='image', x0=10, top=20)
        page = SimpleNamespace(chars=chars,
                               filter=lambda predicate: list(filter(predicate, chars + [picture])))
        kept = _deduplicated_text_page(page)
        self.assertEqual(len(kept), 5)
        self.assertIs(kept[0], char)
        self.assertIs(kept[-1], picture)
        plain = SimpleNamespace(chars=chars[2:])
        self.assertIs(_deduplicated_text_page(plain), plain)
        missing_font = {key: value for key, value in char.items() if key != 'fontname'}
        ambiguous = SimpleNamespace(chars=[missing_font, dict(missing_font)])
        self.assertIs(_deduplicated_text_page(ambiguous), ambiguous)

    def test_malformed_money_is_not_silently_repaired(self):
        for value in ('1383.191383.19', '13%13%', 'NaN', 'Infinity', '-Infinity'):
            with self.subTest(value=value):
                self.assertIsNone(_to_decimal(value))
        self.assertEqual(_to_decimal('1,383.19'), Decimal('1383.19'))
        self.assertEqual(_to_decimal('600.8846153846154'), Decimal('600.8846153846154'))
        self.assertEqual(_to_decimal('11'), Decimal('11'))
        self.assertEqual(_to_decimal('-13.00'), Decimal('-13.00'))

    def test_single_and_batch_exports_match_and_keep_identifier_as_text(self):
        source = self.root / 'source.pdf'
        make_invoice(source, copies=2)
        single = self.root / 'single'
        batch = self.root / 'batch'
        single.mkdir()
        batch.mkdir()
        one = convert_invoice_pdf(source, single)
        results, failures = convert_invoice_pdfs([source], batch)
        self.assertEqual(failures, [])
        self.assertEqual(one.item_count, 2)
        self.assertEqual(one.abnormal_count, 0)
        for result in (one, results[0]):
            self.assertEqual(Path(result.output_file).name, '00000000000000112233.xlsx')
            workbook = load_workbook(result.output_file)
            try:
                self.assertEqual(workbook['发票头信息']['B2'].value, '00000000000000112233')
                self.assertEqual(workbook['发票头信息']['B2'].data_type, 's')
                self.assertEqual(workbook['明细表']['D2'].value, 11)
                self.assertEqual(workbook['明细表']['D2'].number_format, 'General')
                self.assertEqual(workbook['明细表']['F2'].value, 122.21)
                self.assertEqual(workbook['明细表']['G2'].value, 0.13)
                self.assertEqual(workbook['明细表'].max_row, 3)
            finally:
                workbook.close()
        self.assertEqual(asdict(one) | {'output_file': ''},
                         asdict(results[0]) | {'output_file': ''})

    def test_quantity_general_format_preserves_fractional_values(self):
        source = self.root / 'fractional.pdf'
        make_invoice(source)
        invoice = extract_invoice(source)
        invoice.items[0].quantity = Decimal('1.5')
        output = self.root / 'fractional.xlsx'
        write_invoice_workbook(invoice, output)
        workbook = load_workbook(output)
        try:
            self.assertEqual(workbook['明细表']['D2'].value, 1.5)
            self.assertEqual(workbook['明细表']['D2'].number_format, 'General')
            self.assertEqual(workbook['明细表']['D3'].value, 11)
            self.assertEqual(workbook['明细表']['D3'].number_format, 'General')
        finally:
            workbook.close()

    def test_ledger_and_log_distinguish_generated_files_with_validation_warnings(self):
        source = self.root / 'source.pdf'
        make_invoice(source)
        result = convert_invoice_pdf(source, self.root)
        from dataclasses import replace
        warned = replace(result, abnormal_count=2)
        ledger = write_invoice_ledger([result, warned], [('bad.pdf', 'bad input')], self.root)
        workbook = load_workbook(ledger.output_file)
        try:
            sheet = workbook['发票汇总']
            self.assertEqual(sheet['K1'].value, '处理状态')
            self.assertEqual(sheet['K2'].value, '已生成，校验通过')
            self.assertEqual(sheet['K3'].value, '已生成，需核对')
            self.assertEqual(sheet['I3'].value, 2)
        finally:
            workbook.close()
        log = Path(ledger.log_file).read_text()
        self.assertIn('已生成发票数=2', log)
        self.assertIn('校验通过发票数=1', log)
        self.assertIn('需核对发票数=1', log)
        self.assertIn('失败发票数=1', log)

    def test_completion_dialog_warns_for_validation_errors_even_without_failures(self):
        host = SimpleNamespace(invoice_output_folder=str(self.root))
        for abnormal_count in (0, 2):
            with self.subTest(abnormal_count=abnormal_count), \
                 patch('ui.pages.invoice_page.QMessageBox') as box:
                result = SimpleNamespace(abnormal_count=abnormal_count, item_count=2)
                InvoicePageMixin.show_invoice_complete_message(host, [result], [])
                dialog = box.return_value
                dialog.setIcon.assert_called_once_with(box.Warning if abnormal_count else box.Information)
                text = dialog.setText.call_args.args[0]
                self.assertIn(f'需核对 {int(abnormal_count > 0)} 个', text)
                self.assertNotIn('成功 1 个', text)


if __name__ == '__main__':
    unittest.main()
