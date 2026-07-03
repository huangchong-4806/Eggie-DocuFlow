import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from core.classifier import CONTRACT, TABLE
from v2.batch_engine import BatchEngine
from v2.layout_extractor import _add_contract_table
from v2.layout_engine import process_layout_document
from v2.layout_exporters import export_contract_layout
from v2.ocr_plugins import BaiduOCR
from v2.queue_system import TaskQueue


class DocuFlowV2Tests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.project_root = Path(__file__).resolve().parents[1]

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_batch_engine_scans_pdfs_and_keeps_failed_file(self):
        (self.root / "ok.pdf").write_text("ok", encoding="utf-8")
        (self.root / "bad.pdf").write_text("bad", encoding="utf-8")
        (self.root / "ignore.txt").write_text("ignore", encoding="utf-8")
        progress = []

        def router(pdf_file, output_dir, progress_callback=None, log_root=None):
            output_file = Path(output_dir) / f"{Path(pdf_file).stem}.txt"
            if Path(pdf_file).name == "bad.pdf":
                return {
                    "doc_type": "UNKNOWN",
                    "output_file": "",
                    "status": "failed",
                    "error_message": "测试失败",
                }
            output_file.write_text("done", encoding="utf-8")
            return {
                "doc_type": "CONTRACT",
                "confidence": 0.86,
                "output_file": str(output_file),
                "status": "success",
            }

        results = BatchEngine(router=router).process_folder(
            self.root,
            progress_callback=lambda value, total, message: progress.append(message),
        )

        self.assertEqual([Path(item["data"]["source_file"]).name for item in results], ["bad.pdf", "ok.pdf"])
        self.assertEqual([item["status"] for item in results], ["failed", "success"])
        self.assertEqual(results[1]["data"]["confidence"], 0.86)
        self.assertTrue((self.root / "output" / "ok.txt").is_file())
        self.assertIn("发现 2 个 PDF", progress[0])

    def test_queue_retries_and_writes_error_log(self):
        log_file = self.root / "queue.log"
        attempts = {"count": 0}

        def worker(source_file):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("临时错误")
            return {
                "doc_type": "TABLE",
                "data": {"source_file": source_file},
                "output_file": "/tmp/table.xlsx",
                "status": "success",
            }

        results = TaskQueue(worker, max_retries=1, log_file=log_file).run(["a.pdf"])

        self.assertEqual(results[0]["status"], "success")
        self.assertEqual(attempts["count"], 2)
        self.assertIn("source_file=a.pdf attempt=1 error=RuntimeError: 临时错误", log_file.read_text(encoding="utf-8"))

    def test_ocr_provider_returns_unified_json_without_entering_router_flow(self):
        missing = BaiduOCR().recognize("scan.pdf")
        self.assertEqual(missing["doc_type"], "OCR")
        self.assertEqual(missing["output_file"], "")
        self.assertEqual(missing["status"], "failed")
        self.assertIn("未配置客户端", missing["data"]["error_message"])

        recognized = BaiduOCR(client=lambda source: {"text": "识别文本"}).recognize("scan.pdf")
        self.assertEqual(recognized["status"], "success")
        self.assertEqual(recognized["data"]["provider"], "BaiduOCR")
        self.assertEqual(recognized["data"]["text"], "识别文本")

    def test_contract_layout_export_keeps_page_and_paragraph_formatting(self):
        result = process_layout_document(self.project_root / "test_files" / "合同测试.pdf", self.root)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["doc_type"], CONTRACT)
        with ZipFile(result["output_file"]) as contract:
            document_xml = contract.read("word/document.xml").decode("utf-8")
        self.assertIn("<w:pgSz", document_xml)
        self.assertIn("<w:pgMar", document_xml)
        self.assertIn("<w:jc", document_xml)
        self.assertIn("<w:sz", document_xml)

    def test_contract_layout_can_apply_formal_contract_style(self):
        result = process_layout_document(
            self.project_root / "test_files" / "合同测试.pdf",
            self.root,
            style_template="formal_contract",
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["style_template"], "formal_contract")
        with ZipFile(result["output_file"]) as contract:
            document_xml = contract.read("word/document.xml").decode("utf-8")
        self.assertIn('w:eastAsia="宋体"', document_xml)
        self.assertIn('w:sz w:val="24"', document_xml)
        self.assertIn('w:firstLine="480"', document_xml)
        self.assertIn('w:line="360"', document_xml)
        self.assertIn('w:top="1440"', document_xml)

    def test_contract_layout_merges_one_row_table_continuation(self):
        pages = [{"tables": [{"bbox": (80, 600, 520, 760), "rows": [["首付款", "30%"], ["初验款", "40%"]]}]}]
        tables = []

        _add_contract_table(pages, tables, (80, 72, 520, 106), [["合计", "100%"]])

        self.assertEqual(tables, [])
        self.assertEqual(pages[-1]["tables"][-1]["rows"][-1], ["合计", "100%"])

    def test_formal_contract_style_keeps_subtitle_as_centered_title(self):
        output_file = self.root / "formal.docx"
        layout = {
            "pages": [
                {
                    "number": 1,
                    "width": 595,
                    "height": 842,
                    "lines": [
                        {"text": "董陈杨律师事务所服务推广项目", "x0": 100, "x1": 500, "top": 100, "bottom": 130},
                        {"text": "业务合作协议", "x0": 200, "x1": 400, "top": 150, "bottom": 180},
                        {"text": "甲方：广东董陈杨律师事务所", "x0": 80, "x1": 420, "top": 230, "bottom": 250},
                    ],
                },
                {
                    "number": 2,
                    "width": 595,
                    "height": 842,
                    "tables": [
                        {
                            "bbox": (80, 150, 520, 360),
                            "rows": [
                                ["对账及结算单", None, None],
                                ["序号", "成交项目", "备注"],
                                ["1", "", ""],
                            ],
                        }
                    ],
                    "lines": [
                        {"text": "乙方：深圳市怡泽通管理有限公司", "x0": 80, "x1": 420, "top": 100, "bottom": 130},
                        {"text": "对账及结算单", "x0": 200, "x1": 400, "top": 170, "bottom": 190},
                    ],
                },
            ]
        }

        export_contract_layout(layout, output_file, style_template="formal_contract")

        with ZipFile(output_file) as contract:
            document_xml = contract.read("word/document.xml").decode("utf-8")
        self.assertEqual(document_xml.count('w:sz w:val="32"'), 2)
        self.assertGreaterEqual(document_xml.count('w:jc w:val="center"'), 2)
        self.assertIn('w:firstLine="480"', document_xml)
        self.assertNotIn('w:type="page"', document_xml)
        self.assertIn("<w:tbl>", document_xml)
        self.assertIn("对账及结算单", document_xml)
        self.assertEqual(document_xml.count("对账及结算单"), 1)

    def test_formal_contract_style_cleans_text_and_merges_wrapped_lines(self):
        output_file = self.root / "formal_clean.docx"
        layout = {
            "pages": [
                {
                    "number": 1,
                    "width": 595,
                    "height": 842,
                    "lines": [
                        {"text": "委托投标及项目利润分配协议", "x0": 160, "x1": 430, "top": 120, "bottom": 145},
                        {"text": "- -", "x0": 400, "x1": 430, "top": 150, "bottom": 165},
                        {"text": "甲方（委托方 / 名义签约方）：深圳市怡通数科创新发展有限公司", "x0": 90, "x1": 500, "top": 200, "bottom": 220},
                        {"text": "联系地址：深圳市宝安区新安街道海滨社区滨港二路 31 号怡亚通大厦", "x0": 90, "x1": 500, "top": 230, "bottom": 250},
                        {"text": "9F 南侧", "x0": 90, "x1": 150, "top": 255, "bottom": 275},
                        {"text": "1.甲方为一家依法设立并有效存续的公司，具备签署对外服务合同及参与项目投标的", "x0": 90, "x1": 500, "top": 300, "bottom": 320},
                        {"text": "主体资格，拥有自有技术开发团队及项目实施能力。", "x0": 90, "x1": 450, "top": 325, "bottom": 345},
                    ],
                }
            ]
        }

        export_contract_layout(layout, output_file, style_template="formal_contract")

        with ZipFile(output_file) as contract:
            document_xml = contract.read("word/document.xml").decode("utf-8")
        self.assertNotIn("委托方 / 名义", document_xml)
        self.assertNotIn("- -", document_xml)
        self.assertIn("委托方/名义签约方", document_xml)
        self.assertIn("滨港二路31号怡亚通大厦9F南侧", document_xml)
        self.assertIn("参与项目投标的主体资格", document_xml)

    def test_formal_contract_style_merges_cross_page_sentence(self):
        output_file = self.root / "formal_cross_page.docx"
        layout = {
            "pages": [
                {
                    "number": 1,
                    "width": 595,
                    "height": 842,
                    "lines": [
                        {"text": "委托投标及项目利润分配协议", "x0": 160, "x1": 430, "top": 120, "bottom": 145},
                        {"text": "签署过程文件时，甲方应在收到书面请求后2个工作日内完成审核并提供必要的盖章", "x0": 90, "x1": 500, "top": 730, "bottom": 750},
                    ],
                },
                {
                    "number": 2,
                    "width": 595,
                    "height": 842,
                    "lines": [
                        {"text": "或授权支持，但甲方有权对文件内容进行合理审查。", "x0": 90, "x1": 450, "top": 75, "bottom": 95},
                        {"text": "3.3对外关系：各子项目的实际履约方在项目执行中与最终用户的所有往来函件。", "x0": 90, "x1": 500, "top": 120, "bottom": 140},
                    ],
                },
            ]
        }

        export_contract_layout(layout, output_file, style_template="formal_contract")

        with ZipFile(output_file) as contract:
            document_xml = contract.read("word/document.xml").decode("utf-8")
        self.assertIn("提供必要的盖章或授权支持", document_xml)
        self.assertNotIn("盖章</w:t>", document_xml)

    def test_table_layout_export_adds_borders_and_page_setup(self):
        from openpyxl import load_workbook

        result = process_layout_document(self.project_root / "test_files" / "表格测试.pdf", self.root)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["doc_type"], TABLE)
        workbook = load_workbook(result["output_file"])
        try:
            sheet = workbook.active
            self.assertEqual(sheet["A1"].border.left.style, "thin")
            self.assertEqual(sheet.row_dimensions[1].height, 22)
            self.assertEqual(sheet.page_setup.fitToWidth, 1)
        finally:
            workbook.close()


if __name__ == "__main__":
    unittest.main()
