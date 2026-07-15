# Large Batch Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为图片合成 PDF、PDF 页面整理和批量改名增加可见的数量保护，消除重复读取预览导致的界面卡顿，并保证 OCR 失败后不留下不完整结果。

**Architecture:** 在 `app.py` 中使用统一常量控制提醒数量和最大数量；界面状态文字始终显示上限和当前数量。图片和 PDF 卡片缓存已生成的小预览，批量改名用延迟刷新合并连续输入。OCR 结果先写入临时文件，全部成功后再发布。

**Tech Stack:** Python 3、PySide6、Pillow、unittest、tempfile、pathlib

## Global Constraints

- 图片合成 PDF：提醒线 100 张，上限 300 张。
- PDF 页面整理：提醒线 500 页，上限 1,000 页。
- 批量改名：提醒线 5,000 个文件，上限 20,000 个文件。
- 三个功能页必须始终显示上限，并显示当前数量。
- 超过最大数量时拒绝整次添加，不做部分添加。
- 用户取消数量提醒后，已有列表保持不变。
- 不改动输出文件夹选择、文件命名、PDF 转图片清晰度、密钥保存和安装包大小规则。

---

### Task 1: 可见数量规则与通用判断

**Files:**
- Modify: `app.py:107-121`
- Modify: `app.py:1942-2015`
- Modify: `app.py:2169-2271`
- Modify: `app.py:2358-2397`
- Test: `tests/test_app_navigation.py`

**Interfaces:**
- Produces: `PDF_IMAGE_WARNING_COUNT`, `PDF_IMAGE_MAX_COUNT`, `PDF_PAGE_WARNING_COUNT`, `PDF_PAGE_MAX_COUNT`, `RENAME_WARNING_COUNT`, `RENAME_MAX_COUNT`
- Produces: `ExcelMergerWindow.confirm_large_addition(kind: str, current: int, added: int, warning: int, maximum: int) -> bool`

- [ ] **Step 1: Write failing UI and boundary tests**

```python
def test_batch_limits_are_visible(self):
    self.assertIn("300", self.window.pdf_image_limit_label.text())
    self.assertIn("1,000", self.window.pdf_page_limit_label.text())
    self.assertIn("20,000", self.window.rename_limit_label.text())

def test_hard_limit_rejects_whole_addition(self):
    self.assertFalse(
        self.window.confirm_large_addition("images", 299, 2, 100, 300)
    )
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_app_navigation.AppNavigationTests.test_batch_limits_are_visible tests.test_app_navigation.AppNavigationTests.test_hard_limit_rejects_whole_addition -v`

Expected: FAIL because the limit labels and helper do not exist.

- [ ] **Step 3: Add constants, labels and helper**

```python
PDF_IMAGE_WARNING_COUNT = 100
PDF_IMAGE_MAX_COUNT = 300
PDF_PAGE_WARNING_COUNT = 500
PDF_PAGE_MAX_COUNT = 1000
RENAME_WARNING_COUNT = 5000
RENAME_MAX_COUNT = 20000

def confirm_large_addition(self, label, current, added, warning, maximum):
    total = current + added
    if total > maximum:
        QMessageBox.warning(self, "超过数量限制", f"{label}最多支持 {maximum:,} 个，本次没有添加。")
        return False
    if current <= warning < total:
        return QMessageBox.question(
            self,
            "数量较多",
            f"添加后共有 {total:,} 个，处理可能较慢。是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) == QMessageBox.Yes
    return True
```

Add `pdf_image_limit_label`, `pdf_page_limit_label`, and `rename_limit_label` beside the corresponding add buttons. Their text must include both warning and maximum values.

- [ ] **Step 4: Run targeted tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_app_navigation -v`

Expected: all navigation and visible-limit tests PASS.

- [ ] **Step 5: Commit task**

```bash
git add app.py tests/test_app_navigation.py
git commit -m "Add visible batch safety limits"
```

### Task 2: 图片添加进度与预览缓存

**Files:**
- Modify: `pdf_toolbox.py:83-94`
- Modify: `app.py:365-440`
- Modify: `app.py:3275-3359`
- Test: `tests/test_pdf_toolbox.py`
- Test: `tests/test_app_navigation.py`

**Interfaces:**
- Produces: `prepare_image_thumbnail(image_file, thumbnail_file, size=(132, 180)) -> str`
- Changes: `PdfImageCard(owner, image_file, thumbnail_file="")`
- Produces: `ExcelMergerWindow.start_adding_pdf_images(filenames) -> bool`

- [ ] **Step 1: Write failing thumbnail and limit tests**

```python
def test_prepare_image_thumbnail_creates_small_preview(self):
    preview = prepare_image_thumbnail(source, destination, (132, 180))
    with Image.open(preview) as image:
        self.assertLessEqual(image.width, 132)
        self.assertLessEqual(image.height, 180)

def test_pdf_image_card_reuses_cached_preview(self):
    card = PdfImageCard(self.window, source, preview)
    card.update_display(1)
    first_key = card.thumbnail_cache.cacheKey()
    card.update_display(2)
    self.assertEqual(card.thumbnail_cache.cacheKey(), first_key)
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_pdf_toolbox tests.test_app_navigation -v`

Expected: FAIL because thumbnail preparation and cached card preview do not exist.

- [ ] **Step 3: Implement thumbnail preparation and background addition**

```python
def prepare_image_thumbnail(image_file, thumbnail_file, size=(132, 180)):
    from PIL import Image, ImageOps
    with Image.open(image_file) as image:
        image.verify()
    with Image.open(image_file) as image:
        preview = ImageOps.exif_transpose(image).convert("RGB")
        preview.thumbnail(size, Image.Resampling.LANCZOS)
        Path(thumbnail_file).parent.mkdir(parents=True, exist_ok=True)
        preview.save(thumbnail_file, "JPEG", quality=85)
    return str(Path(thumbnail_file))
```

`start_adding_pdf_images` must deduplicate candidates, call `confirm_large_addition`, generate previews through `start_background_task`, and only append cards after every accepted preview is prepared. `PdfImageCard.update_display` loads `thumbnail_cache` only once; check and reorder operations only update text and counts.

- [ ] **Step 4: Run targeted tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_pdf_toolbox tests.test_app_navigation -v`

Expected: all image and navigation tests PASS.

- [ ] **Step 5: Commit task**

```bash
git add app.py pdf_toolbox.py tests/test_app_navigation.py tests/test_pdf_toolbox.py
git commit -m "Keep large image batches responsive"
```

### Task 3: PDF 页数提醒与缓存复用

**Files:**
- Modify: `app.py:195-281`
- Modify: `app.py:2843-2992`
- Test: `tests/test_app_navigation.py`

**Interfaces:**
- Changes: `PdfPageCard.update_display(index: int, refresh_thumbnail: bool = False) -> None`
- Produces: `ExcelMergerWindow.pdf_page_count_checked(pdf_files: tuple[str, ...], counts: tuple[tuple[str, int], ...]) -> None`

- [ ] **Step 1: Write failing page-count and cache tests**

```python
def test_pdf_page_card_reuses_cached_thumbnail(self):
    card = PdfPageCard(self.window, page_data)
    card.update_display(1)
    first_key = card.thumbnail_cache.cacheKey()
    card.update_display(2)
    self.assertEqual(card.thumbnail_cache.cacheKey(), first_key)

def test_pdf_page_limit_rejects_before_rendering(self):
    with patch("app.render_page_thumbnail") as render:
        self.window.pdf_page_count_checked(("large.pdf",), (("large.pdf", 1001),))
    render.assert_not_called()
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_app_navigation -v`

Expected: FAIL because page cards have no cache and page-count gate does not exist.

- [ ] **Step 3: Split page counting from rendering**

Use one short background task to call `page_count` for every selected PDF. Add the existing page count to the new total, reject above 1,000 pages, and ask before crossing 500 pages. Only accepted files enter the existing thumbnail-rendering task.

`PdfPageCard` stores one `thumbnail_cache` after the first load. Number, check state, rotation, reorder and status updates reuse the cache; a rotation changes the displayed cached preview without reopening the thumbnail file.

- [ ] **Step 4: Run targeted tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_app_navigation -v`

Expected: all page limit and cache tests PASS.

- [ ] **Step 5: Commit task**

```bash
git add app.py tests/test_app_navigation.py
git commit -m "Protect PDF organizer page limits"
```

### Task 4: 批量改名限制与延迟刷新

**Files:**
- Modify: `app.py:1153-1189`
- Modify: `app.py:1942-2140`
- Modify: `app.py:3991-4156`
- Test: `tests/test_app_navigation.py`

**Interfaces:**
- Produces: `ExcelMergerWindow.schedule_rename_preview() -> None`
- Produces: `ExcelMergerWindow.display_rename_previews(previews: tuple) -> None`
- Changes: `ExcelMergerWindow.add_rename_paths(paths) -> bool`

- [ ] **Step 1: Write failing timer and boundary tests**

```python
def test_rename_rule_changes_are_debounced(self):
    with patch.object(self.window, "refresh_rename_file_list") as refresh:
        self.window.rename_rule_primary_edit.setText("A")
        self.window.rename_rule_primary_edit.setText("AB")
        QTest.qWait(300)
    refresh.assert_called_once()

def test_rename_hard_limit_keeps_existing_list(self):
    self.window.rename_source_files = [f"existing-{i}" for i in range(20000)]
    self.assertFalse(self.window.add_rename_paths(["extra-file"]))
    self.assertEqual(len(self.window.rename_source_files), 20000)
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_app_navigation -v`

Expected: FAIL because each change refreshes immediately and addition has no limits.

- [ ] **Step 3: Add a 250 ms single-shot timer and large preview task**

```python
self.rename_preview_timer = QTimer(self)
self.rename_preview_timer.setSingleShot(True)
self.rename_preview_timer.setInterval(250)
self.rename_preview_timer.timeout.connect(self.refresh_rename_file_list)

def schedule_rename_preview(self):
    self.rename_preview_timer.start()
```

All rule controls call `schedule_rename_preview`. `add_rename_paths` deduplicates before mutation, applies the 5,000/20,000 gates, and returns `False` without changing the list when rejected. Above 5,000 files, preview calculation uses `start_background_task`; `display_rename_previews` adds prepared rows in one update-disabled block and restores updates afterward.

- [ ] **Step 4: Run targeted tests and batch timing check**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_app_navigation -v`

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -c 'from PySide6.QtWidgets import QApplication; from app import ExcelMergerWindow; q=QApplication([]); w=ExcelMergerWindow(); print(w.rename_preview_timer.interval())'`

Expected: tests PASS and the timing command prints `250`.

- [ ] **Step 5: Commit task**

```bash
git add app.py tests/test_app_navigation.py
git commit -m "Guard large rename batches"
```

### Task 5: OCR 结果全部成功后再保留

**Files:**
- Modify: `api_layer/document.py:227-330`
- Modify: `app.py:4578-4586`
- Test: `tests/test_api_layer.py`

**Interfaces:**
- Produces: `_write_extraction_bundle(extraction, text_path: Path, json_path: Path, log_path: Path) -> ExtractionFiles`

- [ ] **Step 1: Write failing cleanup tests**

```python
def test_extraction_failure_leaves_no_partial_files(self):
    with patch("api_layer.document._atomic_write", side_effect=[str(text_path), OSError("disk full")]):
        with self.assertRaises(OSError):
            extract_document_to_files(source, output_folder, "baidu")
    self.assertEqual(list(output_folder.glob("sample_\u6587\u5b57\u63d0\u53d6*")), [])
```

Use a wrapper around the real first write so the test proves that an already-created text result is removed when the second write fails.

- [ ] **Step 2: Run test and confirm failure**

Run: `.venv/bin/python -m unittest tests.test_api_layer.APILayerTests.test_extraction_failure_leaves_no_partial_files -v`

Expected: FAIL because the text file remains.

- [ ] **Step 3: Write all three temporary results and publish together**

Create a temporary result folder inside the requested output folder. Write text, JSON and log there first. Publish each final file only after all three writes succeed. If publication fails, remove every final path created by this call and remove the temporary folder in `finally`.

Update the user-facing failure text to include: `本次未保留不完整结果。`

- [ ] **Step 4: Run API tests**

Run: `.venv/bin/python -m unittest tests.test_api_layer -v`

Expected: all API and failure-cleanup tests PASS.

- [ ] **Step 5: Commit task**

```bash
git add api_layer/document.py app.py tests/test_api_layer.py
git commit -m "Remove partial OCR extraction results"
```

### Task 6: 全量验证和本地界面检查

**Files:**
- Verify only: all files changed by Tasks 1-5

**Interfaces:**
- Consumes: all task outputs above
- Produces: verified local application state with visible limits and responsive progress

- [ ] **Step 1: Run source checks**

Run: `git diff --check`

Expected: no output.

- [ ] **Step 2: Run all automated tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 3: Start the local application**

Run: `.venv/bin/python main.py`

Expected: the application opens without an error dialog.

- [ ] **Step 4: Inspect the three visible limit areas**

Verify in the actual local window:

- PDF 页面整理显示当前页数和“处理数量越多，处理速度越慢，请酌情拆分任务”。
- 图片转 PDF 显示当前图片数和同一条拆分任务建议。
- 批量改名显示当前文件数和同一条拆分任务建议。

- [ ] **Step 5: Review current changes**

Run: `git status -sb`

Expected: only the previously existing work plus files intentionally changed by this plan are present; no temporary test files remain.
