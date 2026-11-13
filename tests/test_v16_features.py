import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from zipfile import ZipFile

from openpyxl import load_workbook
from excel_category_split import SplitOptions, inspect_source, build_preview, export_split
from layout_batch.queue_system import TaskQueue
from pdf_invoice_tool import PdfInvoiceResult, write_invoice_ledger, extract_invoice


class FormatAndStopTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_duplicate_groups_do_not_mix_old_codes_or_missing_numbers(self):
        identities=[("0001","00000001"),("0002","00000001"),(" 0001 ","00000001"),
                    ("","00000001"),("",""),("",""),("","0"*20),("","0"*20)]
        results=[PdfInvoiceResult(str(i),1,0,invoice_code=c,invoice_number=n) for i,(c,n) in enumerate(identities)]
        ledger=write_invoice_ledger(results,[],self.root)
        self.assertEqual((ledger.duplicate_groups,ledger.duplicate_invoices,ledger.duplicate_extra),(2,4,2))
        wb=load_workbook(ledger.output_file)
        self.addCleanup(wb.close)
        rows=list(wb.active.values)[1:]
        self.assertEqual([r[14] for r in rows],[2,1,2,1,0,0,2,2])
        self.assertEqual(rows[-1][1],"0"*20)

    def test_csv_preserves_text_and_cancel_only_keeps_complete_files(self):
        src=self.root/"source.csv"
        src.write_bytes('类别;编号\r\n甲;00123456789012345678\r\n乙;"=ab;cd"\r\n'.encode("gbk"))
        for mode in ("files","sheets"):
            options=SplitOptions(src,"CSV",key_columns=(1,),output_dir=self.root,output_mode=mode,csv_encoding="gbk",csv_delimiter=";")
            preview=build_preview(inspect_source(options),options)
            stop=Event()
            result=export_split(preview,lambda *_:stop.set(),stop)
            if mode=="sheets":
                self.assertFalse(result.output_files)
                self.assertFalse(result.output_folder.exists())
            else:
                self.assertEqual(len(result.output_files),1)
                self.assertEqual(result.exported_rows,1)
                wb=load_workbook(result.output_files[0])
                self.assertEqual(wb.active["B2"].value,"00123456789012345678")
                wb.close()
        src.write_bytes(src.read_bytes()+b"\r\n")
        with self.assertRaisesRegex(ValueError,"变化"):
            export_split(preview)

    def test_batch_stop_does_not_start_another_file(self):
        stop=Event()
        def worker(path):
            stop.set()
            return {"status":"success","output_file":path}
        result=TaskQueue(worker,max_workers=1).run(["a","b","c"],stop_event=stop)
        self.assertEqual([r["status"] for r in result],["success","unprocessed","unprocessed"])

    def test_broken_ofd_does_not_create_output(self):
        p=self.root/"bad.ofd"
        with ZipFile(p,"w") as z:z.writestr("OFD.xml","<broken>")
        with self.assertRaisesRegex(ValueError,"OFD"):
            extract_invoice(p)
