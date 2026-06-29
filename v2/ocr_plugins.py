import importlib.util
import os
from abc import ABC, abstractmethod
from pathlib import Path


class OCRProvider(ABC):
    name = "OCR"

    def _result(self, source_file, data=None, status="success", output_file=""):
        payload = {"provider": self.name, "source_file": str(Path(source_file))}
        if data:
            payload.update(data)
        return {
            "doc_type": "OCR",
            "data": payload,
            "output_file": output_file,
            "status": status,
        }

    @abstractmethod
    def detect(self, source_file):
        """Return provider availability and source information."""

    @abstractmethod
    def recognize(self, source_file):
        """Return recognized content as unified JSON."""


class _ClientOCR(OCRProvider):
    env_vars = ()

    def __init__(self, client=None):
        self.client = client

    def _configured(self):
        return self.client is not None or all(os.environ.get(name) for name in self.env_vars)

    def detect(self, source_file):
        available = self._configured()
        return self._result(
            source_file,
            {"available": available},
            status="success" if available else "failed",
        )

    def recognize(self, source_file):
        if self.client is None:
            return self._result(
                source_file,
                {"error_message": f"{self.name} 未配置客户端，未执行 OCR"},
                status="failed",
            )
        try:
            response = self.client(str(Path(source_file)))
        except Exception as error:
            return self._result(
                source_file,
                {"error_message": f"{type(error).__name__}: {error}"},
                status="failed",
            )
        if isinstance(response, dict):
            return self._result(source_file, response)
        return self._result(source_file, {"text": str(response)})


class BaiduOCR(_ClientOCR):
    name = "BaiduOCR"
    env_vars = ("BAIDU_OCR_API_KEY", "BAIDU_OCR_SECRET_KEY")


class AlibabaOCR(_ClientOCR):
    name = "AlibabaOCR"
    env_vars = ("ALIBABA_CLOUD_ACCESS_KEY_ID", "ALIBABA_CLOUD_ACCESS_KEY_SECRET")


class PaddleOCR(OCRProvider):
    name = "PaddleOCR"

    def __init__(self, engine=None):
        self.engine = engine

    def _available(self):
        return self.engine is not None or importlib.util.find_spec("paddleocr") is not None

    def detect(self, source_file):
        available = self._available()
        return self._result(
            source_file,
            {"available": available},
            status="success" if available else "failed",
        )

    def recognize(self, source_file):
        if self.engine is None:
            try:
                from paddleocr import PaddleOCR as PaddleEngine
            except Exception:
                return self._result(
                    source_file,
                    {"error_message": "PaddleOCR 未安装，未执行 OCR"},
                    status="failed",
                )
            self.engine = PaddleEngine(use_angle_cls=True, lang="ch")

        try:
            response = self.engine.ocr(str(Path(source_file)), cls=True)
        except Exception as error:
            return self._result(
                source_file,
                {"error_message": f"{type(error).__name__}: {error}"},
                status="failed",
            )
        return self._result(source_file, {"raw": response})
