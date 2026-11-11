import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_rename_tool import suggest_smart_renames


class SmartRenameToolTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    @patch("smart_rename_tool._suggest_one")
    def test_invoice_suggestion_and_duplicate_content_are_previewed(self, suggest_one):
        first = self.root / "a.pdf"
        second = self.root / "b.pdf"
        first.write_bytes(b"same-content")
        second.write_bytes(b"same-content")
        suggest_one.return_value = ("INVOICE", "20260807_示例_100.00", "")

        result = suggest_smart_renames([first, second])

        self.assertEqual(Path(result.previews[0].target_path).name, "20260807_示例_100.00.pdf")
        self.assertTrue(result.previews[0].blocked)
        self.assertTrue(result.previews[1].blocked)
        self.assertEqual(result.suggestions[1].duplicate_of, str(first.resolve()))
        self.assertIn("多个文件会改成同一个名字", result.previews[1].message)
        self.assertIn("内容与 a.pdf 相同", result.previews[1].message)
        self.assertIn("重复文件", result.metadata_by_source[str(second.resolve())])

    @patch("smart_rename_tool._suggest_one")
    def test_unrecognized_pdf_keeps_original_name(self, suggest_one):
        source = self.root / "普通.pdf"
        source.write_bytes(b"content")
        suggest_one.return_value = ("UNKNOWN", "", "无法可靠识别")

        result = suggest_smart_renames([source])

        self.assertFalse(result.previews[0].blocked)
        self.assertFalse(result.previews[0].will_rename)
        self.assertEqual(result.previews[0].status, "保持原名")
        self.assertIn("无法可靠识别", result.previews[0].message)

    @patch("smart_rename_tool._suggest_one")
    def test_illegal_filename_characters_are_cleaned(self, suggest_one):
        source = self.root / "contract.pdf"
        source.write_bytes(b"contract")
        suggest_one.return_value = ("CONTRACT", "20260807_采购/合同:终稿", "")

        result = suggest_smart_renames([source])

        self.assertEqual(Path(result.previews[0].target_path).name, "20260807_采购 合同 终稿.pdf")
        self.assertTrue(result.previews[0].will_rename)

    @patch("smart_rename_tool._suggest_one", return_value=("CONTRACT", "newname", ""))
    def test_same_size_same_time_replacement_is_not_renamed(self, _suggest):
        import os
        from batch_rename_tool import apply_renames
        source = self.root / "old.pdf"
        source.write_bytes(b"first")
        stamp = source.stat()
        preview = suggest_smart_renames([source])
        source.write_bytes(b"other")
        os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        result = apply_renames(preview.previews)
        self.assertEqual(result.unprocessed_count, 1)
        self.assertEqual(source.read_bytes(), b"other")
        self.assertFalse((self.root / "newname.pdf").exists())

    def test_journal_failure_after_rename_reports_actual_paths_and_stops(self):
        from batch_rename_tool import apply_renames, preview_explicit_renames
        pairs = []
        for index in range(3):
            source = self.root / f"{index}.pdf"
            source.write_bytes(bytes([index]))
            pairs.append((source, self.root / f"new-{index}.pdf"))
        previews = preview_explicit_renames(pairs)
        with patch("batch_rename_tool._write_action_log", side_effect=OSError("log")):
            result = apply_renames(previews)
        self.assertTrue(result.warning)
        self.assertEqual([a.status for a in result.actions], ["成功", "未处理", "未处理"])
        for index, (source, target) in enumerate(pairs):
            self.assertEqual(source.exists(), index != 0)
            self.assertEqual(target.exists(), index == 0)


if __name__ == "__main__":
    unittest.main()
