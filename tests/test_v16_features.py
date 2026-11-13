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

    def test_safe_stop_after_failure_does_not_retry_or_hide_pending_paths(self):
        stop=Event()
        calls=[]
        def worker(path):
            calls.append(path)
            stop.set()
            raise ValueError("test failure")
        results=TaskQueue(worker,max_retries=2).run(["A","B"],stop_event=stop)
        self.assertEqual(calls,["A"])
        self.assertEqual(results[0]["data"]["attempts"],1)
        self.assertEqual(results[1]["status"],"unprocessed")
        ledger=write_invoice_ledger([PdfInvoiceResult("A.xlsx",1,0,source_file="A")],[],self.root,unprocessed=["B"])
        wb=load_workbook(ledger.output_file)
        self.addCleanup(wb.close)
        self.assertEqual(list(wb["未处理"].values)[-1],("未处理","B"))

    def test_ofd_reads_paged_discount_and_preserves_empty_remarks(self):
        from xml.etree.ElementTree import Element, SubElement, tostring
        from decimal import Decimal
        p=self.root/"synthetic.ofd"
        fields={"InvoiceNo":"00000000000000000042","IssueDate":"2026年11月13日",
                "BuyerName":"甲公司","BuyerTaxID":"913000000000000001","SellerName":"乙公司",
                "SellerTaxID":"913000000000000002","TaxExclusiveTotalAmount":"9.00",
                "TaxTotalAmount":"1.17","TaxInclusiveTotalAmount":"10.17"}
        tags=Element("Tags")
        with ZipFile(p,"w") as z:
            z.writestr("OFD.xml","<OFD><DocBody><DocRoot>Doc/Doc.xml</DocRoot></DocBody></OFD>")
            z.writestr("Doc/Doc.xml",'<Document><Pages><Page ID="1" BaseLoc="p1.xml"/><Page ID="2" BaseLoc="p2.xml"/></Pages><CustomTags>idx.xml</CustomTags></Document>')
            z.writestr("Doc/idx.xml","<Index><FileLoc>tags.xml</FileLoc></Index>")
            for i in (1,2):
                page=Element("Page")
                def obj(key,x,y,t):
                    node=SubElement(page,"TextObject",ID=key,Boundary=f"{x} {y} 5 2")
                    SubElement(node,"TextCode").text=t
                obj("title",0,0,"电子发票（普通发票）")
                if i==1:
                    for n,(key,value) in enumerate(fields.items()):
                        obj(key,0,n+2,value)
                        SubElement(SubElement(tags,key),"ObjectRef",PageRef="1").text=key
                for n,title in enumerate(("项目名称","规格型号","单位","数量","单价","金额","税率","税额")):
                    obj(f"h{n}",10*n,20,title)
                amount,tax=("10.00","1.30") if i==1 else ("-1.00","-0.13")
                row=("用品" if i==1 else "折扣","","件","1" if i==1 else "",amount if i==1 else "",amount,"13%",tax)
                for n,value in enumerate(row):
                    if value:obj(f"v{n}",10*n,24,value)
                obj("end",0,27,"小计");obj("amount",50,27,amount);obj("tax",70,27,tax)
                if i==2:
                    obj("total",0,30,"价税合计");obj("signer",0,40,"开票人：测试员")
                z.writestr(f"Doc/p{i}.xml",tostring(page,encoding="utf-8"))
            z.writestr("Doc/tags.xml",tostring(tags,encoding="utf-8"))
        result=extract_invoice(p)
        self.assertEqual(result.header["发票号码"],fields["InvoiceNo"])
        self.assertEqual(result.header["备注"],"")
        self.assertEqual([x.amount for x in result.items],[Decimal("10"),Decimal("-1")])
        self.assertFalse(any(r.check=="分页小计" for r in result.validations if r.abnormal))

    def test_broken_ofd_does_not_create_output(self):
        p=self.root/"bad.ofd"
        with ZipFile(p,"w") as z:z.writestr("OFD.xml","<broken>")
        with self.assertRaisesRegex(ValueError,"OFD"):
            extract_invoice(p)
