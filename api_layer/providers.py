import base64
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod

from api_layer.config import PROVIDER_LABELS, load_credentials
from api_layer.models import PageText, TextBlock


class OCRProviderError(RuntimeError):
    def __init__(self, message, code="", request_id="", retriable=False):
        super().__init__(message)
        self.code = str(code or "")
        self.request_id = str(request_id or "")
        self.retriable = bool(retriable)


class OCRProvider(ABC):
    key = ""

    @property
    def label(self):
        return PROVIDER_LABELS[self.key]

    @abstractmethod
    def recognize_image(self, image_bytes, page_number, width, height):
        """识别一张已处理的页面图片，并返回统一的页面结果。"""

    @abstractmethod
    def test_connection(self):
        """验证当前密钥是否能与平台通信。"""


def _normalized_bbox(left, top, right, bottom, width, height):
    width = max(float(width or 0), 1.0)
    height = max(float(height or 0), 1.0)
    return (
        max(0.0, min(1.0, float(left) / width)),
        max(0.0, min(1.0, float(top) / height)),
        max(0.0, min(1.0, float(right) / width)),
        max(0.0, min(1.0, float(bottom) / height)),
    )


class BaiduOCRProvider(OCRProvider):
    key = "baidu"
    TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
    OCR_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/general"

    def __init__(self, credentials=None, opener=None, timeout=30):
        values = credentials or load_credentials(self.key)
        self.api_key = values.get("BAIDU_OCR_API_KEY", "").strip()
        self.secret_key = values.get("BAIDU_OCR_SECRET_KEY", "").strip()
        if not self.api_key or not self.secret_key:
            raise ValueError("百度智能云 OCR 密钥未配置完整。")
        self.opener = opener or urllib.request.urlopen
        self.timeout = timeout
        self._access_token = ""
        self._token_deadline = 0.0

    def _json_request(self, request):
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            raise OCRProviderError(
                f"百度 OCR 连接失败（HTTP {error.code}）。",
                code=error.code,
                retriable=error.code == 429 or error.code >= 500,
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise OCRProviderError(
                f"百度 OCR 网络连接失败：{type(error).__name__}。",
                retriable=True,
            ) from None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise OCRProviderError("百度 OCR 返回了无法读取的结果。") from None

    def _get_access_token(self):
        if self._access_token and time.monotonic() < self._token_deadline:
            return self._access_token
        query = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self.api_key,
                "client_secret": self.secret_key,
            }
        )
        request = urllib.request.Request(
            f"{self.TOKEN_URL}?{query}",
            data=b"",
            method="POST",
        )
        payload = self._json_request(request)
        token = str(payload.get("access_token", ""))
        if not token:
            code = payload.get("error") or payload.get("error_code") or "AUTH_FAILED"
            raise OCRProviderError(
                "百度 OCR 密钥验证失败，请检查 API Key 和 Secret Key。",
                code=code,
            )
        expires_in = max(int(payload.get("expires_in") or 3600), 300)
        self._access_token = token
        self._token_deadline = time.monotonic() + expires_in - 120
        return token

    def test_connection(self):
        self._get_access_token()
        return True, "密钥验证通过，未上传文档页面。"

    def recognize_image(self, image_bytes, page_number, width, height):
        started = time.monotonic()
        token = self._get_access_token()
        body = urllib.parse.urlencode(
            {
                "image": base64.b64encode(image_bytes).decode("ascii"),
                "language_type": "CHN_ENG",
                "detect_direction": "true",
                "paragraph": "true",
                "probability": "true",
            }
        ).encode("ascii")
        request = urllib.request.Request(
            f"{self.OCR_URL}?{urllib.parse.urlencode({'access_token': token})}",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        payload = self._json_request(request)
        if payload.get("error_code"):
            code = str(payload.get("error_code"))
            request_id = str(payload.get("log_id", ""))
            retriable = code in {"18", "110", "111", "282000"}
            raise OCRProviderError(
                f"百度 OCR 识别失败，错误码：{code}。",
                code=code,
                request_id=request_id,
                retriable=retriable,
            )

        blocks = []
        for item in payload.get("words_result") or []:
            text = str(item.get("words", "")).strip()
            if not text:
                continue
            location = item.get("location") or {}
            left = float(location.get("left") or 0)
            top = float(location.get("top") or 0)
            right = left + float(location.get("width") or 0)
            bottom = top + float(location.get("height") or 0)
            probability = item.get("probability") or {}
            confidence = probability.get("average")
            blocks.append(
                TextBlock(
                    text=text,
                    bbox=_normalized_bbox(left, top, right, bottom, width, height),
                    confidence=float(confidence) if confidence is not None else None,
                )
            )
        return PageText(
            page_number=page_number,
            text="\n".join(block.text for block in blocks),
            method="cloud_ocr",
            blocks=tuple(blocks),
            width=width,
            height=height,
            request_id=str(payload.get("log_id", "")),
            elapsed_seconds=time.monotonic() - started,
        )


class AlibabaOCRProvider(OCRProvider):
    key = "alibaba"

    def __init__(self, credentials=None, client=None):
        values = credentials or load_credentials(self.key)
        self.access_key_id = values.get("ALIBABA_CLOUD_ACCESS_KEY_ID", "").strip()
        self.access_key_secret = values.get(
            "ALIBABA_CLOUD_ACCESS_KEY_SECRET", ""
        ).strip()
        if not self.access_key_id or not self.access_key_secret:
            raise ValueError("阿里云 OCR 密钥未配置完整。")
        self._client = client

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from alibabacloud_ocr_api20210707.client import Client
            from alibabacloud_tea_openapi.models import Config
        except ImportError:
            raise RuntimeError("缺少阿里云 OCR 官方连接组件。") from None
        config = Config(
            access_key_id=self.access_key_id,
            access_key_secret=self.access_key_secret,
        )
        config.endpoint = "ocr-api.cn-hangzhou.aliyuncs.com"
        config.connect_timeout = 10000
        config.read_timeout = 30000
        self._client = Client(config)
        return self._client

    @staticmethod
    def _points_bbox(points, width, height):
        values = [
            (float(getattr(point, "x", 0) or 0), float(getattr(point, "y", 0) or 0))
            for point in (points or [])
        ]
        if not values:
            return (0.0, 0.0, 0.0, 0.0)
        xs = [value[0] for value in values]
        ys = [value[1] for value in values]
        return _normalized_bbox(min(xs), min(ys), max(xs), max(ys), width, height)

    def recognize_image(self, image_bytes, page_number, width, height):
        started = time.monotonic()
        try:
            from alibabacloud_ocr_api20210707 import models
        except ImportError:
            raise RuntimeError("缺少阿里云 OCR 官方连接组件。") from None
        request = models.RecognizeAllTextRequest(
            type="Advanced",
            body=io.BytesIO(image_bytes),
            output_coordinate="points",
            output_oricoord=True,
            advanced_config=models.RecognizeAllTextRequestAdvancedConfig(
                output_row=True,
                output_paragraph=True,
            ),
        )
        try:
            response = self._get_client().recognize_all_text(request)
        except Exception as error:
            code = str(getattr(error, "code", "") or "SDK_ERROR")
            request_id = str(getattr(error, "request_id", "") or "")
            retriable = code in {
                "Throttling",
                "Throttling.User",
                "ServiceUnavailable",
                "InternalError",
                "SDK.ServerUnreachable",
            }
            raise OCRProviderError(
                f"阿里云 OCR 识别失败，错误码：{code}。",
                code=code,
                request_id=request_id,
                retriable=retriable,
            ) from None

        body = getattr(response, "body", None)
        code = str(getattr(body, "code", "") or "")
        request_id = str(getattr(body, "request_id", "") or "")
        if code not in {"", "200", "Success"}:
            raise OCRProviderError(
                f"阿里云 OCR 识别失败，错误码：{code}。",
                code=code,
                request_id=request_id,
            )
        data = getattr(body, "data", None)
        result_width = float(getattr(data, "width", 0) or width)
        result_height = float(getattr(data, "height", 0) or height)
        blocks = []
        for sub_image in getattr(data, "sub_images", None) or []:
            block_info = getattr(sub_image, "block_info", None)
            for detail in getattr(block_info, "block_details", None) or []:
                text = str(getattr(detail, "block_content", "") or "").strip()
                if not text:
                    continue
                confidence = getattr(detail, "block_confidence", None)
                if confidence is not None:
                    confidence = float(confidence) / 100
                blocks.append(
                    TextBlock(
                        text=text,
                        bbox=self._points_bbox(
                            getattr(detail, "block_points", None),
                            result_width,
                            result_height,
                        ),
                        confidence=confidence,
                    )
                )
        content = str(getattr(data, "content", "") or "").strip()
        if not blocks and content:
            blocks.append(TextBlock(text=content))
        return PageText(
            page_number=page_number,
            text=content or "\n".join(block.text for block in blocks),
            method="cloud_ocr",
            blocks=tuple(blocks),
            width=result_width,
            height=result_height,
            request_id=request_id,
            elapsed_seconds=time.monotonic() - started,
        )

    def test_connection(self):
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            raise RuntimeError("缺少图片处理组件 Pillow。") from None
        image = Image.new("RGB", (96, 48), "white")
        ImageDraw.Draw(image).text((8, 14), "TEST", fill="black")
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=85)
        self.recognize_image(buffer.getvalue(), 1, image.width, image.height)
        return True, "连接测试通过，本次测试可能占用 1 次 OCR 调用额度。"


def create_provider(provider):
    if provider == "baidu":
        return BaiduOCRProvider()
    if provider == "alibaba":
        return AlibabaOCRProvider()
    raise ValueError("不支持的 OCR 服务平台。")
