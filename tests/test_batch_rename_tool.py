import tempfile
import unittest
from pathlib import Path

from batch_rename_tool import (
    RenameOptions,
    apply_renames,
    discover_rename_files,
    preview_renames,
)


class BatchRenameToolTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_file(self, name):
        path = self.root / name
        path.write_text(name, encoding="utf-8")
        return path

    def test_preview_replaces_adds_number_and_changes_extension(self):
        source = self.write_file("订单草稿.txt")
        options = RenameOptions(
            find_text="草稿",
            replace_text="正式",
            prefix="2026_",
            numbering_enabled=True,
            number_start=7,
            number_digits=2,
            extension="md",
        )

        preview = preview_renames([source], options)[0]

        self.assertFalse(preview.blocked)
        self.assertTrue(preview.will_rename)
        self.assertEqual(Path(preview.target_path).name, "2026_订单正式_07.md")

    def test_preview_can_trim_start_or_end_characters(self):
        source = self.write_file("2026订单草稿.txt")

        start_preview = preview_renames(
            [source],
            RenameOptions(trim_start_count=4),
        )[0]
        end_preview = preview_renames(
            [source],
            RenameOptions(trim_end_count=2),
        )[0]
        empty_preview = preview_renames(
            [source],
            RenameOptions(trim_start_count=99),
        )[0]

        self.assertEqual(Path(start_preview.target_path).name, "订单草稿.txt")
        self.assertEqual(Path(end_preview.target_path).name, "2026订单.txt")
        self.assertTrue(empty_preview.blocked)
        self.assertEqual(empty_preview.status, "不可改名")
        self.assertEqual(empty_preview.message, "新文件名不能为空。")

    def test_preview_blocks_duplicate_targets_and_existing_file(self):
        first = self.write_file("A.txt")
        second = self.write_file("B.txt")
        self.write_file("已存在.txt")

        duplicate_previews = preview_renames(
            [first, second],
            RenameOptions(find_text="A", replace_text="B"),
        )
        self.assertTrue(all(preview.blocked for preview in duplicate_previews))
        self.assertEqual(duplicate_previews[0].status, "文件名重复")

        existing_preview = preview_renames(
            [first],
            RenameOptions(find_text="A", replace_text="已存在"),
        )[0]
        self.assertTrue(existing_preview.blocked)
        self.assertEqual(existing_preview.status, "目标已存在")

    def test_apply_renames_files_and_writes_audit_log(self):
        source = self.write_file("old.txt")
        previews = preview_renames(
            [source],
            RenameOptions(find_text="old", replace_text="new"),
        )

        result = apply_renames(previews, log_folder=self.root)

        self.assertFalse(source.exists())
        self.assertTrue((self.root / "new.txt").is_file())
        self.assertEqual(result.success_count, 1)
        self.assertEqual(result.failed_count, 0)
        self.assertTrue(Path(result.log_file).is_file())
        self.assertEqual(Path(result.log_file).suffix, ".txt")
        log_text = Path(result.log_file).read_text(encoding="utf-8")
        self.assertIn("原文件名：old.txt", log_text)
        self.assertIn("新文件名：new.txt", log_text)
        self.assertIn("处理结果：成功", log_text)

    def test_discover_rename_files_ignores_hidden_items(self):
        nested = self.root / "nested"
        nested.mkdir()
        hidden_folder = self.root / ".hidden"
        hidden_folder.mkdir()
        visible = self.write_file("visible.txt")
        nested_file = nested / "nested.txt"
        nested_file.write_text("nested", encoding="utf-8")
        (hidden_folder / "ignored.txt").write_text("hidden", encoding="utf-8")
        (self.root / ".ignored.txt").write_text("hidden", encoding="utf-8")

        files = discover_rename_files(self.root)

        self.assertEqual(
            [Path(filename).name for filename in files],
            [visible.name, nested_file.name],
        )


if __name__ == "__main__":
    unittest.main()
