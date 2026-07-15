import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

import api_layer.document as document_module
from api_layer.config import (
    delete_credentials,
    get_config_file,
    is_provider_configured,
    load_credentials,
    save_credentials,
    select_provider,
    selected_provider,
)
from api_layer.document import extract_document_to_files, process_document_with_ocr
from api_layer.models import DocumentExtraction, PageText, TextBlock
from api_layer.providers import AlibabaOCRProvider, BaiduOCRProvider


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.payload


class _FakeProvider:
    key = "baidu"
    label = "测试 OCR"

    def __init__(self, text):
        self.text = text
        self.calls = 0

    def recognize_image(self, image_bytes, page_number, width, height):
        self.calls += 1
        return PageText(
            page_number=page_number,
            text=self.text,
            method="cloud_ocr",
            blocks=(TextBlock(self.text, (0.1, 0.1, 0.9, 0.2), 0.98),),
            width=width,
            height=height,
            request_id="request-test-1",
            elapsed_seconds=0.01,
        )


class APILayerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.environment = patch.dict(
            os.environ,
            {"EGGIE_OCR_CONFIG_DIR": str(self.root / "config")},
            clear=False,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temporary_directory.cleanup()

    def _scanned_pdf(self, filename="scan.pdf"):
        image = Image.new("RGB", (900, 1200), "white")
        pdf_file = self.root / filename
        image.save(pdf_file, "PDF", resolution=150)
        image.close()
        return pdf_file

    def test_extraction_failure_leaves_no_partial_files(self):
        source = self.root / "sample.pdf"
        source.touch()
        output_folder = self.root / "output"
        extraction = DocumentExtraction(
            source_file=str(source),
            provider="local",
            pages=(PageText(1, "测试文字", "local_text"),),
            started_at="2026-07-15T00:00:00",
        )
        original_write = document_module._atomic_write
        calls = {"count": 0}

        def fail_on_second_write(path, content):
            calls["count"] += 1
            if calls["count"] == 2:
                raise OSError("模拟第二个结果生成失败")
            return original_write(path, content)

        with patch.object(
            document_module,
            "extract_document",
            return_value=extraction,
        ), patch.object(
            document_module,
            "_atomic_write",
            side_effect=fail_on_second_write,
        ):
            with self.assertRaises(OSError):
                extract_document_to_files(source, output_folder, "baidu")

        self.assertEqual(list(output_folder.glob("sample_\u6587\u5b57\u63d0\u53d6*")), [])

    def test_extraction_publication_failure_removes_newly_published_files(self):
        output_folder = self.root / "output"
        output_folder.mkdir()
        final_paths = (
            output_folder / "sample_文字提取.txt",
            output_folder / "sample_文字提取.json",
            output_folder / "sample_文字提取_日志.txt",
        )
        extraction = DocumentExtraction(
            source_file=str(self.root / "sample.pdf"),
            provider="local",
            pages=(PageText(1, "测试文字", "local_text"),),
            started_at="2026-07-15T00:00:00",
        )
        original_link = os.link
        publications = {"count": 0}

        def fail_on_second_publication(source, destination):
            if Path(destination).parent == output_folder:
                publications["count"] += 1
                if publications["count"] == 2:
                    raise OSError("模拟第二个结果发布失败")
            return original_link(source, destination)

        with patch.object(
            document_module.os,
            "link",
            side_effect=fail_on_second_publication,
        ):
            with self.assertRaises(OSError):
                document_module._write_extraction_bundle(
                    extraction,
                    *final_paths,
                )

        self.assertTrue(all(not path.exists() for path in final_paths))

    def test_extraction_publication_never_overwrites_existing_result(self):
        output_folder = self.root / "output"
        output_folder.mkdir()
        final_paths = (
            output_folder / "sample_文字提取.txt",
            output_folder / "sample_文字提取.json",
            output_folder / "sample_文字提取_日志.txt",
        )
        final_paths[0].write_text("以前的结果", encoding="utf-8")
        extraction = DocumentExtraction(
            source_file=str(self.root / "sample.pdf"),
            provider="local",
            pages=(PageText(1, "新的文字", "local_text"),),
            started_at="2026-07-15T00:00:00",
        )

        with self.assertRaises(FileExistsError):
            document_module._write_extraction_bundle(extraction, *final_paths)

        self.assertEqual(final_paths[0].read_text(encoding="utf-8"), "以前的结果")
        self.assertFalse(final_paths[1].exists())
        self.assertFalse(final_paths[2].exists())

    def test_credentials_are_saved_to_private_env_file_and_can_be_deleted(self):
        secret = "unit-test-secret"
        config_file = save_credentials(
            "baidu",
            {
                "BAIDU_OCR_API_KEY": "unit-test-api",
                "BAIDU_OCR_SECRET_KEY": secret,
            },
        )

        self.assertEqual(config_file, get_config_file())
        self.assertEqual(config_file.stat().st_mode & 0o777, 0o600)
        self.assertTrue(is_provider_configured("baidu"))
        self.assertEqual(load_credentials("baidu")["BAIDU_OCR_SECRET_KEY"], secret)

        delete_credentials("baidu")

        self.assertFalse(is_provider_configured("baidu"))
        self.assertNotIn(secret, config_file.read_text(encoding="utf-8"))

    def test_each_ocr_provider_keeps_its_own_credentials_when_switching(self):
        with patch.dict(
            os.environ,
            {
                "BAIDU_OCR_API_KEY": "",
                "BAIDU_OCR_SECRET_KEY": "",
                "ALIBABA_CLOUD_ACCESS_KEY_ID": "",
                "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "",
                "EGGIE_OCR_PROVIDER": "",
            },
            clear=False,
        ):
            save_credentials(
                "baidu",
                {
                    "BAIDU_OCR_API_KEY": "baidu-api",
                    "BAIDU_OCR_SECRET_KEY": "baidu-secret",
                },
            )
            save_credentials(
                "alibaba",
                {
                    "ALIBABA_CLOUD_ACCESS_KEY_ID": "ali-id",
                    "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "ali-secret",
                },
            )

            select_provider("baidu")
            self.assertEqual(selected_provider(), "baidu")
            self.assertEqual(
                load_credentials("baidu")["BAIDU_OCR_SECRET_KEY"],
                "baidu-secret",
            )
            self.assertEqual(
                load_credentials("alibaba")["ALIBABA_CLOUD_ACCESS_KEY_SECRET"],
                "ali-secret",
            )

            delete_credentials("baidu")
            self.assertFalse(is_provider_configured("baidu"))
            self.assertTrue(is_provider_configured("alibaba"))

    def test_switching_provider_does_not_clear_external_environment_keys(self):
        external_values = {
            "BAIDU_OCR_API_KEY": "external-baidu-api",
            "BAIDU_OCR_SECRET_KEY": "external-baidu-secret",
            "ALIBABA_CLOUD_ACCESS_KEY_ID": "external-ali-id",
            "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "external-ali-secret",
        }
        with patch.dict(os.environ, external_values, clear=False):
            select_provider("alibaba")

            for key, value in external_values.items():
                self.assertEqual(os.environ.get(key), value)

    def test_baidu_provider_normalizes_text_and_coordinates(self):
        responses = iter(
            [
                _Response({"access_token": "short-lived-test-token", "expires_in": 3600}),
                _Response(
                    {
                        "log_id": 123456,
                        "words_result": [
                            {
                                "words": "合同编号 A-01",
                                "location": {"left": 10, "top": 20, "width": 80, "height": 20},
                                "probability": {"average": 0.96},
                            }
                        ],
                    }
                ),
            ]
        )
        provider = BaiduOCRProvider(
            credentials={
                "BAIDU_OCR_API_KEY": "test-api",
                "BAIDU_OCR_SECRET_KEY": "test-secret",
            },
            opener=lambda request, timeout: next(responses),
        )

        result = provider.recognize_image(b"image", 2, 100, 200)

        self.assertEqual(result.page_number, 2)
        self.assertEqual(result.text, "合同编号 A-01")
        self.assertEqual(result.request_id, "123456")
        self.assertEqual(result.blocks[0].bbox, (0.1, 0.1, 0.9, 0.2))
        self.assertEqual(result.blocks[0].confidence, 0.96)

    def test_alibaba_provider_normalizes_official_sdk_response(self):
        detail = SimpleNamespace(
            block_content="甲方：测试公司",
            block_confidence=95,
            block_points=[
                SimpleNamespace(x=10, y=20),
                SimpleNamespace(x=90, y=20),
                SimpleNamespace(x=90, y=40),
                SimpleNamespace(x=10, y=40),
            ],
        )
        data = SimpleNamespace(
            width=100,
            height=200,
            content="甲方：测试公司",
            sub_images=[
                SimpleNamespace(
                    block_info=SimpleNamespace(block_details=[detail])
                )
            ],
        )
        response = SimpleNamespace(
            body=SimpleNamespace(code="", request_id="ali-request-1", data=data)
        )
        client = SimpleNamespace(recognize_all_text=lambda request: response)
        provider = AlibabaOCRProvider(
            credentials={
                "ALIBABA_CLOUD_ACCESS_KEY_ID": "test-id",
                "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "test-secret",
            },
            client=client,
        )

        result = provider.recognize_image(b"image", 1, 100, 200)

        self.assertEqual(result.text, "甲方：测试公司")
        self.assertEqual(result.request_id, "ali-request-1")
        self.assertEqual(result.blocks[0].bbox, (0.1, 0.1, 0.9, 0.2))
        self.assertEqual(result.blocks[0].confidence, 0.95)

    def test_scanned_pdf_writes_text_json_and_diagnostic_log_without_text_leak(self):
        source = self._scanned_pdf("scan.v2.pdf")
        provider = _FakeProvider("隐私文字不应出现在日志")
        output_folder = self.root / "output"

        with patch("api_layer.document.create_provider", return_value=provider):
            result = extract_document_to_files(source, output_folder, "baidu")

        self.assertEqual(provider.calls, 1)
        self.assertEqual(result.cloud_page_count, 1)
        self.assertIn("隐私文字", Path(result.text_file).read_text(encoding="utf-8"))
        payload = json.loads(Path(result.json_file).read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["pages"][0]["request_id"], "request-test-1")
        log_text = Path(result.log_file).read_text(encoding="utf-8")
        self.assertNotIn("隐私文字", log_text)
        self.assertIn("cloud_page_count=1", log_text)
        self.assertIn("request_id=request-test-1", log_text)
        self.assertIn("secrets_written=false", log_text)
        self.assertEqual(Path(result.text_file).name, "scan.v2_文字提取.txt")
        self.assertEqual(Path(result.json_file).name, "scan.v2_文字提取.json")

    def test_scanned_contract_enters_existing_document_processing_flow(self):
        source = self._scanned_pdf("contract.pdf")
        provider = _FakeProvider("采购合同 甲方：甲公司 乙方：乙公司 第一条 合同条款")
        output_folder = self.root / "processed"

        with patch("api_layer.document.create_provider", return_value=provider):
            result = process_document_with_ocr(
                source,
                output_folder,
                provider_name="baidu",
                log_root=self.root / "logs",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["doc_type"], "CONTRACT")
        self.assertTrue(result["ocr_used"])
        self.assertTrue(Path(result["output_file"]).is_file())
        self.assertEqual(Path(result["output_file"]).suffix, ".docx")
        session_log = next((self.root / "logs").rglob("session-*.log"))
        log_text = session_log.read_text(encoding="utf-8")
        self.assertIn("request_id=request-test-1", log_text)
        self.assertNotIn("采购合同", log_text)


if __name__ == "__main__":
    unittest.main()
