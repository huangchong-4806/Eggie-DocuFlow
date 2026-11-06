import os
import ssl
import unittest
from io import BytesIO
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from update_check import (
    LATEST_RELEASE_URL, RELEASES_URL, Release, UpdateCheckError,
    fetch_latest_release, parse_version_record,
)
from ui.update_check import UpdateCheckButton, UpdateResultDialog
from update_check import DeltaNotApplicable
from version import APP_VERSION, BUILD_NUMBER, BUILD_TYPE


def record(version="1.5.1", build="2026110402"):
    return (f'APP_VERSION = "{version}"\nBUILD_TYPE = "release"\nBUILD_NUMBER = "{build}"\n').encode()


class Response(BytesIO):
    def __init__(self, url, payload=b""):
        super().__init__(payload)
        self.geturl = lambda: url


class ReleaseCheckTests(unittest.TestCase):
    def test_official_tag_source_and_local_record(self):
        tag = "1.5.1"
        raw = "https://raw.githubusercontent.com/huangchong-4806/Eggie-DocuFlow/v1.5.1/version.py"
        responses = [Response(f"{RELEASES_URL}/tag/v{tag}"), Response(raw, record())]
        with patch("update_check.urlopen", side_effect=responses) as read:
            result = fetch_latest_release()
        self.assertEqual(result, Release(tag, "2026110402"))
        self.assertEqual(result.page, f"{RELEASES_URL}/tag/v1.5.1")
        requests = [call.args[0] for call in read.call_args_list]
        self.assertEqual([(r.get_method(), r.full_url) for r in requests], [
            ("HEAD", LATEST_RELEASE_URL), ("GET", raw),
        ])
        root = Path(__file__).resolve().parents[1]
        if BUILD_TYPE == "release":
            self.assertEqual(parse_version_record(APP_VERSION, (root / "version.py").read_bytes()),
                             Release(APP_VERSION, BUILD_NUMBER))
        else:
            with self.assertRaises(UpdateCheckError):
                parse_version_record(APP_VERSION, (root / "version.py").read_bytes())

    def test_bundled_certificates_when_portable_system_trust_is_empty(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.assertFalse(context.cert_store_stats()["x509_ca"])
        with patch("update_check.ssl.create_default_context", return_value=context), \
             patch("update_check.urlopen", side_effect=TimeoutError()) as network:
            with self.assertRaises(UpdateCheckError):
                fetch_latest_release()
        self.assertTrue(context.cert_store_stats()["x509_ca"])
        self.assertIs(context, network.call_args.kwargs["context"])
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_older_build_and_semantic_version_order(self):
        self.assertGreater(Release("1.5.1", "2026110402").sort_key(), Release("1.5.1", "2026110401").sort_key())
        self.assertGreater(Release("1.10.0", "2026100101").sort_key(), Release("1.9.8", "2026110101").sort_key())

    def test_incomplete_mismatched_or_executable_record_is_unknown(self):
        for bad in [b'APP_VERSION = "1.5.1"', record("1.5.2"), record(build=""),
                    record(build="1e9"), record() + b'BUILD_NUMBER = "2026110401"',
                    record() + b'print("should never execute")', record().replace(b'release', b'rc')]:
            with self.subTest(bad=bad), self.assertRaises(UpdateCheckError):
                parse_version_record("1.5.1", bad)

    def test_release_redirect_must_be_an_official_stable_tag(self):
        for url in ["https://example.com/tag/v1.5.1", LATEST_RELEASE_URL,
                    f"{RELEASES_URL}/tag/v1.6.0-rc1"]:
            with self.subTest(url=url), patch("update_check.urlopen", return_value=Response(url)) as read:
                with self.assertRaises(UpdateCheckError):
                    fetch_latest_release()
                self.assertEqual(read.call_count, 1)

    def test_failed_or_redirected_record_is_unknown(self):
        release = f"{RELEASES_URL}/tag/v1.5.1"
        for failure in [TimeoutError(), Response("https://example.com", record())]:
            with self.subTest(failure=failure), patch("update_check.urlopen", side_effect=[Response(release), failure]):
                with self.assertRaises(UpdateCheckError):
                    fetch_latest_release()


class UpdateButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = QWidget()
        self.button = UpdateCheckButton(self.window)
        self.window.show()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def result_box(self):
        for _ in range(120):
            self.app.processEvents()
            boxes = [box for box in self.window.findChildren(UpdateResultDialog) if box.isVisible()]
            if boxes:
                return boxes[0]
            QTest.qWait(10)
        self.fail("没有看到更新查询结果")

    def test_manual_only_new_build_and_explicit_download(self):
        latest = Release("1.5.1", "2026110402")
        with patch("ui.update_check.APP_VERSION", "1.5.1"), patch("ui.update_check.BUILD_NUMBER", "2026110401"), \
             patch("ui.update_check.fetch_latest_release", return_value=latest) as check, \
             patch("ui.update_check.QDesktopServices.openUrl", return_value=True) as open_url:
            self.app.processEvents()
            check.assert_not_called()
            self.button.click()
            self.button.start_check()
            box = self.result_box()
            self.assertEqual(box.heading.text(), "有可用更新")
            self.assertEqual([label.text() for label in box.detail_labels],
                             ["当前版本　V1.5.1（2026110401）", "最新版本　V1.5.1（2026110402）"])
            check.assert_called_once()
            open_url.assert_not_called()
            next(b for b in box.buttons.buttons() if b.text() == "打开官方下载页").click()
            self.assertEqual(open_url.call_args.args[0].toString(), latest.page)

    def test_failure_can_retry_and_confirm_equal(self):
        with patch("ui.update_check.fetch_latest_release", side_effect=[
            UpdateCheckError("网络不可用"), Release(APP_VERSION, BUILD_NUMBER),
        ]) as check:
            self.button.click()
            box = self.result_box()
            self.assertEqual(box.heading.text(), "本次未能确认是否有更新")
            next(b for b in box.buttons.buttons() if b.text() == "重试").click()
            self.assertEqual(self.result_box().heading.text(), "当前已是最新版")
            self.assertEqual(check.call_count, 2)

    def test_result_dialogs_open_at_the_same_size_with_room_for_version_numbers(self):
        results = [Release("1.5.1", "2026110401"), Release("1.5.1", "2026110402"),
                   UpdateCheckError("暂时无法连接官方发布页，请检查网络后重试。")]
        with patch("ui.update_check.APP_VERSION", "1.5.1"), patch("ui.update_check.BUILD_NUMBER", "2026110401"), \
             patch("ui.update_check.fetch_latest_release", side_effect=results):
            for result in results:
                with self.subTest(result=result):
                    self.button.click()
                    box = self.result_box()
                    self.assertEqual((box.width(), box.height()), (376, 164))
                    for label in box.detail_labels:
                        self.assertGreaterEqual(label.contentsRect().width(), label.fontMetrics().horizontalAdvance(label.text()))
                    box.reject()
                    self.app.processEvents()

    def test_signed_full_or_delta_download_requires_explicit_restart(self):
        latest = Release(APP_VERSION, str(int(BUILD_NUMBER) + 1))
        for kind, phrase in (("delta", "增量更新"), ("full", "完整更新包")):
            with self.subTest(kind=kind):
                asset = SimpleNamespace(kind=kind, size=1048576, target=latest, platform="macos-arm64")
                staged = Mock(asset=asset)
                self.window.restart_for_update = Mock()
                with patch("ui.update_check.installed_platform", return_value="macos-arm64"), \
                     patch("ui.update_check.fetch_latest_release", return_value=latest), \
                     patch("ui.update_check.fetch_update_asset", return_value=asset), \
                     patch("ui.update_check.stage_download", return_value=staged) as download:
                    self.button.click()
                    box = self.result_box()
                    self.assertEqual((box.width(), box.height()), (376, 164))
                    self.assertIn(phrase, box.detail_labels[-1].text())
                    self.assertIn("1.0 MB", box.detail_labels[-1].text())
                    download.assert_not_called()
                    next(b for b in box.buttons.buttons() if b.text() == "下载更新").click()
                    ready = self.result_box()
                    self.assertEqual(ready.heading.text(), "更新已准备好")
                    ready.reject()
                    self.window.restart_for_update.assert_not_called()
                    self.button.click()
                    ready = self.result_box()
                    next(b for b in ready.buttons.buttons() if b.text() == "重启并更新").click()
                    self.window.restart_for_update.assert_called_once()
                    self.button.launch_prepared()
                    staged.launch.assert_called_once()
                    staged.discard.assert_not_called()
                    self.app.processEvents()

    def test_unsuitable_delta_offers_full_size_without_downloading_it(self):
        latest = Release(APP_VERSION, str(int(BUILD_NUMBER) + 1))
        delta = SimpleNamespace(kind="delta", size=4000, target=latest)
        full = SimpleNamespace(kind="full", size=5 * 1024 ** 2, target=latest)
        with patch("ui.update_check.installed_platform", return_value="windows-x64"), \
             patch("ui.update_check.fetch_latest_release", return_value=latest), \
             patch("ui.update_check.fetch_update_asset", return_value=delta), \
             patch("ui.update_check.full_alternative", return_value=full), \
             patch("ui.update_check.stage_download", side_effect=DeltaNotApplicable("旧文件有变化")) as download:
            self.button.click()
            box = self.result_box()
            next(b for b in box.buttons.buttons() if b.text() == "下载更新").click()
            fallback = self.result_box()
            self.assertEqual(fallback.heading.text(), "此安装需要完整更新包")
            self.assertIn("5.0 MB", fallback.detail_labels[-1].text())
            download.assert_called_once()
            fallback.reject()
            self.app.processEvents()
            self.assertFalse(self.button.is_downloading())
            self.assertEqual(self.button.text(), "检查更新")

    def test_invalid_signed_offer_has_no_install_or_browser_action(self):
        with patch("ui.update_check.installed_platform", return_value="windows-x64"), \
             patch("ui.update_check.fetch_latest_release", return_value=Release(APP_VERSION, str(int(BUILD_NUMBER) + 1))), \
             patch("ui.update_check.fetch_update_asset", side_effect=UpdateCheckError("更新清单签名无效")):
            self.button.click()
            box = self.result_box()
            self.assertEqual(box.heading.text(), "本次未能确认是否有更新")
            self.assertIn("更新清单签名无效", [label.text() for label in box.detail_labels])
            self.assertEqual({b.text() for b in box.buttons.buttons()}, {"重试", "关闭"})

    def test_cancelling_download_discards_even_a_late_prepared_result(self):
        started, release = Event(), Event()
        latest = Release(APP_VERSION, str(int(BUILD_NUMBER) + 1))
        asset = SimpleNamespace(kind="delta", size=4000, target=latest)
        staged = Mock(asset=asset)

        def download(*args):
            started.set()
            release.wait(2)
            return staged

        with patch("ui.update_check.installed_platform", return_value="windows-x64"), \
             patch("ui.update_check.fetch_latest_release", return_value=latest), \
             patch("ui.update_check.fetch_update_asset", return_value=asset), \
             patch("ui.update_check.stage_download", side_effect=download):
            self.button.click()
            offer = self.result_box()
            next(b for b in offer.buttons.buttons() if b.text() == "下载更新").click()
            self.assertTrue(started.wait(1))
            cancel = self.button._download_dialog.findChild(QPushButton)
            cancel.click()
            release.set()
            for _ in range(120):
                self.app.processEvents()
                if not self.button.is_downloading():
                    break
                QTest.qWait(10)
            staged.discard.assert_called_once()
            staged.launch.assert_not_called()
            self.assertEqual(self.button.text(), "检查更新")

    def test_closing_active_window_does_not_open_a_dialog(self):
        gate = Event()
        def slow_check():
            gate.wait(2)
            return Release(APP_VERSION, BUILD_NUMBER)
        with patch("ui.update_check.fetch_latest_release", side_effect=slow_check):
            self.button.click()
            self.window.close()
            gate.set()
            QTest.qWait(250)
            self.assertFalse(self.window.findChildren(UpdateResultDialog))


if __name__ == "__main__":
    unittest.main()
