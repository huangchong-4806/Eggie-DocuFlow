# Staged Stability Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在用户操作、文件处理规则和界面显示完全不变的前提下，建立可追溯的安全基线，并把 `app.py` 中最独立的界面样式、后台任务、常用输入控件和 PDF 缩略图控件分阶段移到 `ui/`。

**Architecture:** `app.py` 继续保留主窗口、导航、页面创建和业务调用，只从 `ui/` 加载四类独立界面部件。先原样移动并逐项检查，再只合并 PDF 缩略图中完全相同的基础行为；每个任务单独提交，失败时只回退当前任务。

**Tech Stack:** Python 3、PySide6、unittest、PyInstaller、openpyxl、macOS Microsoft Excel

## Global Constraints

- 软件定位为个人使用的办公工具，稳定性优先于追求文件行数或形式上的整齐。
- 不申请 Apple Developer 账号，不做 Apple 公证，不产生公证费用。
- 不改变 PDF 页数上限：页面整理最多 1,000 页，发票解析和文档处理保持 100 页。
- 不升级 openpyxl、pdfplumber、pypdf、Pillow、PySide6 等基础组件。
- 不改变 Excel 合并、Excel 拆分、发票解析、批量改名、文档处理和 PDF 工具箱的业务规则。
- 不改变用户看到的文字、按钮位置、页面顺序、颜色、拖拽方式和操作步骤。
- 不改变 OCR 密钥的保存位置和 `.env` 保护规则，不把任何密钥写入软件文件。
- 不修改 `packaging/EggieDocuFlow.spec`、`version.py`、`requirements.txt`、发布说明或正式安装包。
- 测试安装包只生成在 `/tmp/eggie-staged-stability-package`，不得运行会覆盖 `release/` 的正式构建脚本。
- Excel 测试结果必须用 Microsoft Excel 客户端真实打开；出现任何损坏、修复或恢复提示都算失败。
- 只修改本计划列出的文件；测试临时文件在记录结果后删除。

## File Map

- Create `ui/__init__.py`: 界面部件文件夹入口。
- Create `ui/theme.py`: 颜色表、主题颜色组合和完整界面样式。
- Create `ui/tasks.py`: 通用后台任务和文档 OCR 后台任务。
- Create `ui/common_widgets.py`: 数字输入框和下拉选择框的自定义绘制。
- Create `ui/pdf_widgets.py`: PDF 页面卡片、图片卡片和两个拖拽区域。
- Modify `app.py`: 删除已移动的定义，保留兼容导入和主窗口逻辑。
- Modify `tests/test_app_navigation.py`: 增加 5 项结构保护检查。
- Create and update `docs/optimization_logs/2026-07-15-staged-stability-log.md`: 记录基线、逐步结果、实际启动和 Excel 打开结果。

---

### Task 1: 建立独立分支、基线和执行日志

**Files:**
- Create: `docs/optimization_logs/2026-07-15-staged-stability-log.md`
- Verify: `version.py`
- Verify: all current tests

**Interfaces:**
- Consumes: current confirmed design at commit `40e30a7`
- Produces: branch `codex/staged-stability-refactor`
- Produces: baseline record showing version `1.3.6` and `103 / 103` automated checks passed

- [ ] **Step 1: Confirm the current workspace and create the task branch**

Run:

```bash
git status -sb
git switch -c codex/staged-stability-refactor
```

Expected: the existing untracked `.workbuddy/`, review document, old release notes and home reference files remain untouched; the active branch becomes `codex/staged-stability-refactor`.

- [ ] **Step 2: Run the unchanged baseline suite**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v
```

Expected: `Ran 103 tests` and `OK`. If any existing test fails, stop and report the exact test name and message; do not continue to Task 2.

- [ ] **Step 3: Create the execution log with the confirmed baseline**

Create `docs/optimization_logs/2026-07-15-staged-stability-log.md` with exactly this initial content:

```markdown
# Eggie DocuFlow 分阶段稳定整理执行日志

## 基线

- 日期：2026-07-15
- 版本：1.3.6
- 来源记录：40e30a7
- 执行分支：codex/staged-stability-refactor
- 修改前主界面文件：app.py，共 5,315 行
- 自动检查：103 / 103 通过
- 用户功能变化：无
- Apple 公证：不在范围内

## 逐步结果

后续每项记录修改文件、检查命令、通过数量、失败信息和回退结果。

## 文件生成状态

- 基线阶段未生成 Excel、PDF 或安装包。
- `.env` 和用户文件未修改。
```

- [ ] **Step 4: Check and commit the baseline record**

Run:

```bash
git diff --check
git status -sb
git add docs/optimization_logs/2026-07-15-staged-stability-log.md
git commit -m "docs: record staged refactor baseline"
```

Expected: only the new execution log is committed; pre-existing untracked user files remain untracked and unchanged.

### Task 2: 原样分离界面样式

**Files:**
- Create: `ui/__init__.py`
- Create: `ui/theme.py`
- Modify: `app.py` at baseline lines `551-1072`
- Modify: `tests/test_app_navigation.py`
- Modify: `docs/optimization_logs/2026-07-15-staged-stability-log.md`

**Interfaces:**
- Produces: `ui.theme.ACCENT_PALETTES: dict`
- Produces: `ui.theme.build_theme_colors(accent_name: str) -> dict`
- Produces: `ui.theme.build_theme_stylesheet(colors: dict) -> str`
- Preserves: `app.ACCENT_PALETTES`, `app.build_theme_colors`, and `app.build_theme_stylesheet` as imports of the same objects

- [ ] **Step 1: Add the failing canonical-theme test**

Add this method to `AppNavigationTests`:

```python
def test_theme_module_is_the_canonical_source(self):
    import app
    from ui.theme import (
        ACCENT_PALETTES as UI_ACCENT_PALETTES,
        build_theme_colors as ui_build_theme_colors,
        build_theme_stylesheet as ui_build_theme_stylesheet,
    )

    self.assertIs(app.ACCENT_PALETTES, UI_ACCENT_PALETTES)
    self.assertIs(app.build_theme_colors, ui_build_theme_colors)
    self.assertIs(app.build_theme_stylesheet, ui_build_theme_stylesheet)
    stylesheet = ui_build_theme_stylesheet(ui_build_theme_colors("cyan"))
    self.assertIn("QMainWindow", stylesheet)
    self.assertIn("QWidget#pdfThumbnailBox", stylesheet)
```

- [ ] **Step 2: Run the test and verify it fails for the expected reason**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_app_navigation.AppNavigationTests.test_theme_module_is_the_canonical_source -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ui'`.

- [ ] **Step 3: Create the theme package and move the existing theme unchanged**

Create `ui/__init__.py`:

```python
"""Eggie DocuFlow interface building blocks."""
```

Create `ui/theme.py` by moving the complete current block from `ACCENT_PALETTES = {` through the end of `build_theme_stylesheet()` from baseline `app.py:551-1072`. Do not edit any color, selector, spacing, font size, text or fallback value. Add this export list after the moved block:

```python
__all__ = [
    "ACCENT_PALETTES",
    "build_theme_colors",
    "build_theme_stylesheet",
]
```

Replace the removed block in `app.py` with this import near the other project imports:

```python
from ui.theme import ACCENT_PALETTES, build_theme_colors, build_theme_stylesheet
```

- [ ] **Step 4: Run targeted and full checks**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_app_navigation.AppNavigationTests.test_theme_module_is_the_canonical_source tests.test_app_navigation.AppNavigationTests.test_sidebar_controls_every_page_and_marks_the_active_menu -v
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v
```

Expected: targeted tests PASS; full suite reports `Ran 104 tests` and `OK`.

- [ ] **Step 5: Record and commit the theme move**

Append to the execution log:

```markdown
### 界面样式分离

- 修改文件：app.py、ui/__init__.py、ui/theme.py、tests/test_app_navigation.py
- 处理方式：现有颜色和样式原样移动，没有改写界面规则。
- 自动检查：104 / 104 通过
- 文件生成状态：未生成用户文件。
- 回退状态：不需要回退。
```

Run:

```bash
git diff --check
git add app.py ui/__init__.py ui/theme.py tests/test_app_navigation.py docs/optimization_logs/2026-07-15-staged-stability-log.md
git commit -m "refactor: separate theme styling"
```

### Task 3: 原样分离后台任务

**Files:**
- Create: `ui/tasks.py`
- Modify: `app.py` at baseline lines `77-83` and `145-200`
- Modify: `tests/test_app_navigation.py`
- Modify: `docs/optimization_logs/2026-07-15-staged-stability-log.md`

**Interfaces:**
- Produces: `DocumentOCRThread(task_kind, source_file, output_folder, provider, parent=None)`
- Produces: `BackgroundTaskThread(worker, parent=None)`
- Preserves signals: `progress(int, int, str)`, `completed(object)`, `failed(str)`
- Preserves: `app.DocumentOCRThread` and `app.BackgroundTaskThread` as imports of the same classes

- [ ] **Step 1: Add the failing thread-source and result test**

Add this method to `AppNavigationTests`:

```python
def test_task_threads_use_ui_module_and_report_results(self):
    import app
    from ui.tasks import BackgroundTaskThread, DocumentOCRThread

    self.assertIs(app.BackgroundTaskThread, BackgroundTaskThread)
    self.assertIs(app.DocumentOCRThread, DocumentOCRThread)

    progress = []
    completed = []
    succeeded = BackgroundTaskThread(
        lambda callback: (callback(1, 1, "完成"), "result")[1]
    )
    succeeded.progress.connect(lambda value, total, text: progress.append((value, total, text)))
    succeeded.completed.connect(completed.append)
    succeeded.run()

    failures = []

    def fail(_callback):
        raise OSError("disk full")

    failed = BackgroundTaskThread(fail)
    failed.failed.connect(failures.append)
    failed.run()

    self.assertEqual(progress, [(1, 1, "完成")])
    self.assertEqual(completed, ["result"])
    self.assertEqual(failures, ["OSError: disk full"])
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_app_navigation.AppNavigationTests.test_task_threads_use_ui_module_and_report_results -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ui.tasks'`.

- [ ] **Step 3: Create `ui/tasks.py` with the existing behavior**

Create the file with this complete content:

```python
from PySide6.QtCore import QThread, Signal

from api_layer import extract_document_to_files, process_document_with_ocr


class DocumentOCRThread(QThread):
    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, task_kind, source_file, output_folder, provider, parent=None):
        super().__init__(parent)
        self.task_kind = task_kind
        self.source_file = source_file
        self.output_folder = output_folder
        self.provider = provider

    def _progress(self, value, total, message):
        self.progress.emit(value, total, message)

    def run(self):
        try:
            if self.task_kind == "process":
                result = process_document_with_ocr(
                    self.source_file,
                    self.output_folder,
                    provider_name=self.provider,
                    progress_callback=self._progress,
                )
            else:
                result = extract_document_to_files(
                    self.source_file,
                    self.output_folder,
                    self.provider,
                    progress_callback=self._progress,
                )
        except Exception as error:
            self.failed.emit(f"{type(error).__name__}: {error}")
            return
        self.completed.emit(result)


class BackgroundTaskThread(QThread):
    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, worker, parent=None):
        super().__init__(parent)
        self.worker = worker

    def _progress(self, value, total, message):
        self.progress.emit(int(value), int(total), str(message))

    def run(self):
        try:
            result = self.worker(self._progress)
        except Exception as error:
            self.failed.emit(f"{type(error).__name__}: {error}")
            return
        self.completed.emit(result)


__all__ = ["BackgroundTaskThread", "DocumentOCRThread"]
```

In `app.py`:

- Remove the two original class definitions.
- Remove `Signal` from the PySide6 imports; keep `QThread` because `closeEvent()` still uses it.
- Remove `extract_document_to_files` and `process_document_with_ocr` from the `api_layer` import because they now belong to `ui.tasks`.
- Add:

```python
from ui.tasks import BackgroundTaskThread, DocumentOCRThread
```

- [ ] **Step 4: Run targeted and full checks**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_app_navigation.AppNavigationTests.test_task_threads_use_ui_module_and_report_results tests.test_app_navigation.AppNavigationTests.test_global_progress_keeps_the_window_responsive tests.test_app_navigation.AppNavigationTests.test_document_inspection_runs_in_background -v
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v
```

Expected: targeted tests PASS; full suite reports `Ran 105 tests` and `OK`.

- [ ] **Step 5: Record and commit the task move**

Append to the execution log:

```markdown
### 后台任务分离

- 修改文件：app.py、ui/tasks.py、tests/test_app_navigation.py
- 成功路径：进度 1 / 1、结果 result 正常返回。
- 失败路径：OSError: disk full 正常传回，没有导致主程序退出。
- 自动检查：105 / 105 通过
- 文件生成状态：未生成用户文件。
- 回退状态：不需要回退。
```

Run:

```bash
git diff --check
git add app.py ui/tasks.py tests/test_app_navigation.py docs/optimization_logs/2026-07-15-staged-stability-log.md
git commit -m "refactor: separate background tasks"
```

### Task 4: 原样分离常用输入控件

**Files:**
- Create: `ui/common_widgets.py`
- Modify: `app.py` at baseline lines `22-31`, `52-55`, and `1122-1176`
- Modify: `tests/test_app_navigation.py`
- Modify: `docs/optimization_logs/2026-07-15-staged-stability-log.md`

**Interfaces:**
- Produces: `ClearSpinBox()`
- Produces: `SelectionComboBox()`
- Preserves: `app.ClearSpinBox` and `app.SelectionComboBox` as imports of the same classes

- [ ] **Step 1: Add the failing common-widget source test**

Add this method to `AppNavigationTests`:

```python
def test_common_widgets_use_ui_module(self):
    import app
    from ui.common_widgets import ClearSpinBox, SelectionComboBox

    self.assertIs(app.ClearSpinBox, ClearSpinBox)
    self.assertIs(app.SelectionComboBox, SelectionComboBox)
    self.assertEqual(len(self.window.findChildren(ClearSpinBox)), 6)
    self.assertIsInstance(self.window.pdf_export_format_combo, SelectionComboBox)
    self.assertIsInstance(self.window.pdf_export_quality_combo, SelectionComboBox)
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_app_navigation.AppNavigationTests.test_common_widgets_use_ui_module -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ui.common_widgets'`.

- [ ] **Step 3: Create `ui/common_widgets.py` and import it from `app.py`**

Create `ui/common_widgets.py` with the two existing classes unchanged, using this import block and export list:

```python
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QSpinBox, QStyle, QStyleOptionSpinBox


class ClearSpinBox(QSpinBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor("#46515D" if self.isEnabled() else "#AAB2BB"))
        pen.setWidthF(2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        for control, direction in (
            (QStyle.SubControl.SC_SpinBoxUp, -1),
            (QStyle.SubControl.SC_SpinBoxDown, 1),
        ):
            rect = self.style().subControlRect(
                QStyle.ComplexControl.CC_SpinBox,
                option,
                control,
                self,
            )
            center_x = rect.center().x()
            center_y = rect.center().y()
            half_width = max(4, min(6, rect.width() // 4))
            half_height = 3
            painter.drawLine(
                center_x - half_width,
                center_y - direction * half_height,
                center_x,
                center_y + direction * half_height,
            )
            painter.drawLine(
                center_x,
                center_y + direction * half_height,
                center_x + half_width,
                center_y - direction * half_height,
            )


class SelectionComboBox(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(self.palette().color(self.foregroundRole()))
        pen.setWidthF(1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        center_x = self.width() - 16
        center_y = self.height() // 2
        painter.drawLine(center_x - 4, center_y - 2, center_x, center_y + 2)
        painter.drawLine(center_x, center_y + 2, center_x + 4, center_y - 2)


__all__ = ["ClearSpinBox", "SelectionComboBox"]
```

The moved class bodies must remain byte-for-byte equivalent to baseline `app.py:1122-1176`; do not change line width, pen width, arrow positions, colors or enabled/disabled behavior.

In `app.py`, remove the original class bodies and add:

```python
from ui.common_widgets import ClearSpinBox, SelectionComboBox
```

Remove `QColor`, `QPainter`, `QPen`, `QSpinBox`, `QStyle`, and `QStyleOptionSpinBox` from `app.py` imports only after confirming `rg` finds no remaining use in `app.py`.

- [ ] **Step 4: Run targeted and full checks**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_app_navigation.AppNavigationTests.test_common_widgets_use_ui_module tests.test_app_navigation.AppNavigationTests.test_sidebar_controls_every_page_and_marks_the_active_menu -v
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v
```

Expected: targeted tests PASS; full suite reports `Ran 106 tests` and `OK`.

- [ ] **Step 5: Record and commit the common-widget move**

Append to the execution log:

```markdown
### 常用输入控件分离

- 修改文件：app.py、ui/common_widgets.py、tests/test_app_navigation.py
- 数字输入控件数量：6
- PDF 导出下拉控件：2 个，类型保持不变。
- 自动检查：106 / 106 通过
- 文件生成状态：未生成用户文件。
- 回退状态：不需要回退。
```

Run:

```bash
git diff --check
git add app.py ui/common_widgets.py tests/test_app_navigation.py docs/optimization_logs/2026-07-15-staged-stability-log.md
git commit -m "refactor: separate common widgets"
```

### Task 5: 原样分离 PDF 缩略图和拖拽区域

**Files:**
- Create: `ui/pdf_widgets.py`
- Modify: `app.py` at baseline lines `9-32`, `117-123`, and `203-549`
- Modify: `tests/test_app_navigation.py`
- Modify: `docs/optimization_logs/2026-07-15-staged-stability-log.md`

**Interfaces:**
- Produces: `PdfPageCard(owner, data)`
- Produces: `PdfImageCard(owner, image_file, thumbnail_file="")`
- Produces: `PdfPageBoard(owner)`
- Produces: `PdfImageBoard(owner)`
- Preserves: all four names as imports from `app`
- Preserves MIME values: `application/x-eggie-pdf-page-card` and `application/x-eggie-pdf-image-card`

- [ ] **Step 1: Add the failing PDF-widget source test**

Add this method to `AppNavigationTests`:

```python
def test_pdf_widgets_use_ui_module(self):
    import app
    from ui.pdf_widgets import PdfImageBoard, PdfImageCard, PdfPageBoard, PdfPageCard

    self.assertIs(app.PdfPageCard, PdfPageCard)
    self.assertIs(app.PdfImageCard, PdfImageCard)
    self.assertIs(app.PdfPageBoard, PdfPageBoard)
    self.assertIs(app.PdfImageBoard, PdfImageBoard)
    self.assertIsInstance(self.window.pdf_page_board, PdfPageBoard)
    self.assertIsInstance(self.window.pdf_image_board, PdfImageBoard)
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_app_navigation.AppNavigationTests.test_pdf_widgets_use_ui_module -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ui.pdf_widgets'`.

- [ ] **Step 3: Create `ui/pdf_widgets.py` by moving the existing code unchanged**

Start the new file with:

```python
from pathlib import Path

from PySide6.QtCore import QMimeData, QSize, Qt
from PySide6.QtGui import QDrag, QPixmap, QTransform
from PySide6.QtWidgets import QApplication, QCheckBox, QGridLayout, QLabel, QVBoxLayout, QWidget


PDF_PAGE_DRAG_MIME = "application/x-eggie-pdf-page-card"
PDF_IMAGE_DRAG_MIME = "application/x-eggie-pdf-image-card"
PDF_PAGE_CARD_WIDTH = 176
PDF_PAGE_CARD_HEIGHT = 282
PDF_PAGE_CARD_H_SPACING = 18
PDF_PAGE_CARD_V_SPACING = 34
PDF_PAGE_THUMBNAIL_SIZE = QSize(132, 180)
```

Move baseline `app.py:203-549` into this file without changing any method body. Add:

```python
__all__ = ["PdfImageBoard", "PdfImageCard", "PdfPageBoard", "PdfPageCard"]
```

In `app.py`:

- Remove baseline constants `PDF_PAGE_DRAG_MIME` through `PDF_PAGE_THUMBNAIL_SIZE`.
- Remove the four original class definitions.
- Add:

```python
from ui.pdf_widgets import PdfImageBoard, PdfImageCard, PdfPageBoard, PdfPageCard
```

- Remove `QMimeData` and `QDrag` from `app.py` imports.
- Keep `QSize` because the home logo still uses it.
- Keep `QTransform` because full-size PDF preview still rotates images.
- Keep `QPixmap`, `QCheckBox`, `QGridLayout`, `QLabel`, `QVBoxLayout`, `QWidget`, and `QApplication` because the main window still uses them.

- [ ] **Step 4: Run PDF widget and full checks**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest \
  tests.test_app_navigation.AppNavigationTests.test_pdf_widgets_use_ui_module \
  tests.test_app_navigation.AppNavigationTests.test_pdf_image_card_reuses_cached_preview \
  tests.test_app_navigation.AppNavigationTests.test_pdf_page_card_reuses_cached_thumbnail \
  tests.test_app_navigation.AppNavigationTests.test_pdf_page_rotation_keeps_cached_preview_inside_card -v
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v
```

Expected: targeted tests PASS; full suite reports `Ran 107 tests` and `OK`.

- [ ] **Step 5: Record and commit the unchanged PDF-widget move**

Append to the execution log:

```markdown
### PDF 缩略图控件原样分离

- 修改文件：app.py、ui/pdf_widgets.py、tests/test_app_navigation.py
- PDF 页面卡片：缓存、旋转、页码和拖拽规则未改变。
- 图片卡片：缓存、文件名、预览和拖拽规则未改变。
- 自动检查：107 / 107 通过
- 文件生成状态：未生成用户文件。
- 回退状态：不需要回退。
```

Run:

```bash
git diff --check
git add app.py ui/pdf_widgets.py tests/test_app_navigation.py docs/optimization_logs/2026-07-15-staged-stability-log.md
git commit -m "refactor: separate PDF widgets"
```

### Task 6: 只合并 PDF 控件的共同基础行为

**Files:**
- Modify: `ui/pdf_widgets.py`
- Modify: `tests/test_app_navigation.py`
- Modify: `docs/optimization_logs/2026-07-15-staged-stability-log.md`

**Interfaces:**
- Produces internal base: `PdfThumbnailCard(owner)`
- Produces internal base: `DragDropBoard(owner)`
- Preserves public constructors and names from Task 5
- Preserves separate `PdfPageCard.update_display()` and `PdfImageCard.update_display()` methods

- [ ] **Step 1: Add the failing inheritance-boundary test**

Add this method to `AppNavigationTests`:

```python
def test_pdf_widgets_share_only_common_base_behavior(self):
    from ui.pdf_widgets import (
        DragDropBoard,
        PdfImageBoard,
        PdfImageCard,
        PdfPageBoard,
        PdfPageCard,
        PdfThumbnailCard,
    )

    self.assertTrue(issubclass(PdfPageCard, PdfThumbnailCard))
    self.assertTrue(issubclass(PdfImageCard, PdfThumbnailCard))
    self.assertTrue(issubclass(PdfPageBoard, DragDropBoard))
    self.assertTrue(issubclass(PdfImageBoard, DragDropBoard))
    self.assertIsNot(PdfPageCard.update_display, PdfImageCard.update_display)
    self.assertNotEqual(PdfPageCard.drag_mime, PdfImageCard.drag_mime)
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_app_navigation.AppNavigationTests.test_pdf_widgets_share_only_common_base_behavior -v
```

Expected: FAIL because `PdfThumbnailCard` and `DragDropBoard` do not exist.

- [ ] **Step 3: Add the common card base**

Add this class before `PdfPageCard` in `ui/pdf_widgets.py`:

```python
class PdfThumbnailCard(QWidget):
    drag_mime = ""
    owner_cards_attribute = ""
    owner_reorder_method = ""
    owner_preview_method = ""
    owner_checked_method = ""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.thumbnail_cache = QPixmap()
        self.drag_start_position = None
        self.setAcceptDrops(True)
        self.setFixedSize(PDF_PAGE_CARD_WIDTH, PDF_PAGE_CARD_HEIGHT)
        self.setProperty("pdfCard", "true")
        self.setProperty("checked", "false")
        self.setProperty("dragging", "false")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.thumbnail_box = QWidget()
        self.thumbnail_box.setObjectName("pdfThumbnailBox")
        self.thumbnail_box.setFixedSize(148, 192)
        thumbnail_layout = QGridLayout(self.thumbnail_box)
        thumbnail_layout.setContentsMargins(6, 6, 6, 6)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.checkbox = QCheckBox()
        self.checkbox.setFixedSize(24, 24)
        thumbnail_layout.addWidget(self.image_label, 0, 0, Qt.AlignCenter)
        thumbnail_layout.addWidget(self.checkbox, 0, 0, Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(self.thumbnail_box, 0, Qt.AlignHCenter)

        self.page_label = QLabel()
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setFixedHeight(24)
        self.page_label.setProperty("pdfCardTitle", "true")
        self.file_label = QLabel()
        self.file_label.setAlignment(Qt.AlignCenter)
        self.file_label.setFixedHeight(22)
        self.file_label.setWordWrap(False)
        self.file_label.setProperty("pdfCardName", "true")
        layout.addWidget(self.page_label)
        layout.addWidget(self.file_label)
        layout.addStretch(1)

        self.checkbox.stateChanged.connect(self.handle_checked_changed)

    def _owner_cards(self):
        return getattr(self.owner, self.owner_cards_attribute)

    def polish(self):
        self.style().unpolish(self)
        self.style().polish(self)

    def is_checked(self):
        return self.checkbox.isChecked()

    def set_checked(self, checked):
        self.checkbox.setChecked(checked)

    def set_dragging(self, dragging):
        self.setProperty("dragging", "true" if dragging else "false")
        self.polish()

    def handle_checked_changed(self):
        self.setProperty("checked", "true" if self.is_checked() else "false")
        self.polish()
        getattr(self.owner, self.owner_checked_method)()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_position = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton) or self.drag_start_position is None:
            super().mouseMoveEvent(event)
            return
        distance = (event.position().toPoint() - self.drag_start_position).manhattanLength()
        if distance < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return

        source_index = self._owner_cards().index(self)
        mime_data = QMimeData()
        mime_data.setData(self.drag_mime, str(source_index).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        pixmap = self.image_label.pixmap()
        if pixmap:
            drag.setPixmap(pixmap)
        self.set_dragging(True)
        try:
            drag.exec(Qt.MoveAction)
        finally:
            self.set_dragging(False)

    def mouseDoubleClickEvent(self, event):
        getattr(self.owner, self.owner_preview_method)(self)
        event.accept()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(self.drag_mime):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(self.drag_mime):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(self.drag_mime):
            return
        source_index = int(bytes(event.mimeData().data(self.drag_mime)).decode("utf-8"))
        target_index = self._owner_cards().index(self)
        if event.position().x() > self.width() / 2:
            target_index += 1
        getattr(self.owner, self.owner_reorder_method)(source_index, target_index)
        event.acceptProposedAction()
```

Change the subclasses to start with these exact declarations, keep their existing `update_display()` bodies unchanged, and delete only the methods now supplied by the base:

```python
class PdfPageCard(PdfThumbnailCard):
    drag_mime = PDF_PAGE_DRAG_MIME
    owner_cards_attribute = "pdf_page_cards"
    owner_reorder_method = "reorder_pdf_page"
    owner_preview_method = "preview_pdf_page"
    owner_checked_method = "refresh_pdf_page_numbers"

    def __init__(self, owner, data):
        super().__init__(owner)
        self.data = data
        self.display_rotation = None


class PdfImageCard(PdfThumbnailCard):
    drag_mime = PDF_IMAGE_DRAG_MIME
    owner_cards_attribute = "pdf_image_cards"
    owner_reorder_method = "reorder_pdf_image"
    owner_preview_method = "preview_pdf_image"
    owner_checked_method = "refresh_pdf_image_cards"

    def __init__(self, owner, image_file, thumbnail_file=""):
        super().__init__(owner)
        self.image_file = image_file
        self.thumbnail_file = thumbnail_file or image_file
```

From both subclasses delete the duplicate `polish`, `is_checked`, `set_dragging`, `handle_checked_changed`, `mousePressEvent`, `mouseMoveEvent`, `mouseDoubleClickEvent`, `dragEnterEvent`, `dragMoveEvent`, and `dropEvent` methods. Delete `PdfPageCard.set_checked` because the base supplies the same behavior. Keep both existing `update_display()` implementations exactly as they were after Task 5.

- [ ] **Step 4: Add the common board base**

Add this class before the board subclasses:

```python
class DragDropBoard(QWidget):
    drag_mime = ""
    owner_cards_attribute = ""
    owner_reorder_method = ""
    owner_refresh_layout_method = ""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setAcceptDrops(True)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(8, 8, 8, 8)
        self.grid.setHorizontalSpacing(PDF_PAGE_CARD_H_SPACING)
        self.grid.setVerticalSpacing(PDF_PAGE_CARD_V_SPACING)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        getattr(self.owner, self.owner_refresh_layout_method)()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(self.drag_mime):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(self.drag_mime):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(self.drag_mime):
            return
        source_index = int(bytes(event.mimeData().data(self.drag_mime)).decode("utf-8"))
        target_index = len(getattr(self.owner, self.owner_cards_attribute))
        getattr(self.owner, self.owner_reorder_method)(source_index, target_index)
        event.acceptProposedAction()


class PdfPageBoard(DragDropBoard):
    drag_mime = PDF_PAGE_DRAG_MIME
    owner_cards_attribute = "pdf_page_cards"
    owner_reorder_method = "reorder_pdf_page"
    owner_refresh_layout_method = "refresh_pdf_page_cards_layout"


class PdfImageBoard(DragDropBoard):
    drag_mime = PDF_IMAGE_DRAG_MIME
    owner_cards_attribute = "pdf_image_cards"
    owner_reorder_method = "reorder_pdf_image"
    owner_refresh_layout_method = "refresh_pdf_image_cards_layout"
```

Update `__all__` so the new bases are importable for the structure test:

```python
__all__ = [
    "DragDropBoard",
    "PdfImageBoard",
    "PdfImageCard",
    "PdfPageBoard",
    "PdfPageCard",
    "PdfThumbnailCard",
]
```

- [ ] **Step 5: Run focused behavior and full checks**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest \
  tests.test_app_navigation.AppNavigationTests.test_pdf_widgets_share_only_common_base_behavior \
  tests.test_app_navigation.AppNavigationTests.test_pdf_image_card_reuses_cached_preview \
  tests.test_app_navigation.AppNavigationTests.test_pdf_page_card_reuses_cached_thumbnail \
  tests.test_app_navigation.AppNavigationTests.test_pdf_page_rotation_keeps_cached_preview_inside_card \
  tests.test_app_navigation.AppNavigationTests.test_pdf_image_addition_runs_in_background_and_updates_visible_count -v
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v
```

Expected: focused tests PASS; full suite reports `Ran 108 tests` and `OK`.

- [ ] **Step 6: Record and commit the limited deduplication**

Append to the execution log:

```markdown
### PDF 控件共同基础整理

- 修改文件：ui/pdf_widgets.py、tests/test_app_navigation.py
- 合并范围：基础布局、勾选外观、拖拽开始/结束、拖拽区域接收。
- 保留差异：PDF 页旋转与页码、图片文件名、两类预览、两类排序规则。
- 自动检查：108 / 108 通过
- 文件生成状态：未生成用户文件。
- 回退状态：不需要回退。
```

Run:

```bash
git diff --check
git add ui/pdf_widgets.py tests/test_app_navigation.py docs/optimization_logs/2026-07-15-staged-stability-log.md
git commit -m "refactor: share PDF widget behavior"
```

### Task 7: 全量检查、实际启动、Excel 真实打开和清理

**Files:**
- Modify: `docs/optimization_logs/2026-07-15-staged-stability-log.md`
- Verify only: all files changed by Tasks 1-6
- Generate temporarily: `/tmp/eggie-staged-stability-package/`
- Generate temporarily: `/tmp/eggie-staged-stability-excel/`

**Interfaces:**
- Consumes: all five new structure checks and the existing 103 behavior checks
- Produces: final evidence for 108 automated checks, source launch, temporary packaged-App launch, seven-page navigation, PDF widget behavior and Microsoft Excel openability

- [ ] **Step 1: Run source and scope checks**

Run:

```bash
git diff --check codex/release-v1.3.6...HEAD
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v
git diff --name-only codex/release-v1.3.6...HEAD
```

Expected: no diff errors; `Ran 108 tests` and `OK`; changed source files are limited to `app.py`, `ui/`, `tests/test_app_navigation.py` and the execution log.

- [ ] **Step 2: Actually open the source application**

Run the source application in a managed terminal session:

```bash
.venv/bin/python main.py
```

Use the Computer Use skill to verify the real window:

- Version remains 1.3.6.
- Workbench and all six tool entries open, giving seven main pages in total.
- Theme color and layout match the current software.
- PDF page and image panels appear normally.
- Close the application normally after the check.

Expected: no startup error, blank page, missing control or crash.

- [ ] **Step 3: Build a temporary App without touching the formal release folder**

Run:

```bash
rm -rf /tmp/eggie-staged-stability-package
mkdir -p /tmp/eggie-staged-stability-package/dist /tmp/eggie-staged-stability-package/build
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m PyInstaller --noconfirm --clean --distpath /tmp/eggie-staged-stability-package/dist --workpath /tmp/eggie-staged-stability-package/build packaging/EggieDocuFlow.spec
/usr/bin/codesign --force --deep --sign - '/tmp/eggie-staged-stability-package/dist/Eggie DocuFlow.app'
/usr/bin/codesign --verify --deep --strict '/tmp/eggie-staged-stability-package/dist/Eggie DocuFlow.app'
/usr/bin/plutil -p '/tmp/eggie-staged-stability-package/dist/Eggie DocuFlow.app/Contents/Info.plist'
```

Expected: the temporary App exists, signature verification succeeds, and both visible version fields remain 1.3.6. The project `release/` folder is unchanged.

- [ ] **Step 4: Actually open the temporary packaged App**

Run:

```bash
open -n '/tmp/eggie-staged-stability-package/dist/Eggie DocuFlow.app'
```

Use the Computer Use skill to open all seven pages and verify that theme, input controls, PDF page cards, image cards and progress behavior are present. Close the App normally.

Expected: no missing-module error; the `ui/` files are included automatically by the existing packaging configuration.

- [ ] **Step 5: Generate representative Excel results and perform program checks**

Create only temporary test workbooks and results:

```bash
rm -rf /tmp/eggie-staged-stability-excel
mkdir -p /tmp/eggie-staged-stability-excel
.venv/bin/python - <<'PY'
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from excel_merge_tool import build_merged_workbook, split_workbook_by_rows

root = Path("/tmp/eggie-staged-stability-excel")


def make_workbook(path, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "数据"
    sheet.append(["姓名", "金额"])
    for row in rows:
        sheet.append(row)
    sheet["A1"].font = Font(bold=True)
    sheet["A1"].fill = PatternFill("solid", fgColor="D9EAD3")
    sheet["B2"].number_format = "#,##0.00"
    workbook.save(path)
    workbook.close()


first = root / "合并源一.xlsx"
second = root / "合并源二.xlsx"
split_source = root / "拆分源.xlsx"
make_workbook(first, [["第一份", 100]])
make_workbook(second, [["第二份", 200]])
make_workbook(split_source, [["甲", 10], ["乙", 20], ["丙", 30], ["丁", 40]])

merged = root / "合并结果.xlsx"
build_merged_workbook([first, second], merged, skip_rows=1)
split_result = split_workbook_by_rows(split_source, root, rows_per_file=2, header_rows=1)

expected = [merged, *(Path(path) for path in split_result.output_files)]
for path in expected:
    workbook = load_workbook(path, data_only=False)
    assert workbook.active.max_row >= 3, path
    workbook.close()
    print(path)
PY
```

Expected output paths:

```text
/tmp/eggie-staged-stability-excel/合并结果.xlsx
/tmp/eggie-staged-stability-excel/拆分源_拆分结果/拆分源_拆分001.xlsx
/tmp/eggie-staged-stability-excel/拆分源_拆分结果/拆分源_拆分002.xlsx
```

- [ ] **Step 6: Open every generated workbook in Microsoft Excel**

Run:

```bash
open -a 'Microsoft Excel' \
  '/tmp/eggie-staged-stability-excel/合并结果.xlsx' \
  '/tmp/eggie-staged-stability-excel/拆分源_拆分结果/拆分源_拆分001.xlsx' \
  '/tmp/eggie-staged-stability-excel/拆分源_拆分结果/拆分源_拆分002.xlsx'
```

Use the Computer Use skill to inspect Microsoft Excel and confirm for all three files:

- The workbook opens and the visible sheet contains the expected rows.
- No “文件损坏” prompt appears.
- No “是否修复” prompt appears.
- No “无法打开或修复” prompt appears.
- No “Excel 已修复部分内容” prompt appears.

Close all three temporary workbooks without saving.

- [ ] **Step 7: Update the final verification log only after every check succeeds**

Append:

```markdown
## 最终验证

- 自动检查：108 / 108 通过
- 源码运行版：实际启动成功，版本 1.3.6，七个主要页面全部打开成功。
- 临时测试安装包：实际启动成功，未覆盖 release 正式安装包。
- PDF 页面卡片：勾选、缓存、旋转、预览和排序检查通过。
- PDF 图片卡片：勾选、缓存、预览和排序检查通过。
- 后台任务：成功和失败结果均能正常返回主窗口。

### Microsoft Excel 实际打开测试

- `/tmp/eggie-staged-stability-excel/合并结果.xlsx`：实际打开成功，无损坏或修复提示。
- `/tmp/eggie-staged-stability-excel/拆分源_拆分结果/拆分源_拆分001.xlsx`：实际打开成功，无损坏或修复提示。
- `/tmp/eggie-staged-stability-excel/拆分源_拆分结果/拆分源_拆分002.xlsx`：实际打开成功，无损坏或修复提示。

### 影响与回退

- 用户功能变化：无。
- 业务规则变化：无。
- 版本和依赖变化：无。
- 影响范围：主界面内部文件整理。
- 可逆：每个阶段均有独立提交，可单独回退。
- Apple 公证：未执行。
```

- [ ] **Step 8: Clean temporary files and confirm the workspace scope**

After Excel and both Apps are closed, run:

```bash
rm -rf /tmp/eggie-staged-stability-package
rm -rf /tmp/eggie-staged-stability-excel
find . -type d -name '__pycache__' -not -path './.venv/*' -not -path './build/*'
git status -sb
git diff --check codex/release-v1.3.6...HEAD
```

Expected: both temporary folders are gone; no task-created cache remains; pre-existing user untracked files remain untouched; only intended tracked changes are present.

- [ ] **Step 9: Commit the final verification record**

Run:

```bash
git add docs/optimization_logs/2026-07-15-staged-stability-log.md
git commit -m "docs: record staged refactor verification"
```

Expected: implementation ends on `codex/staged-stability-refactor` with separate reversible commits and no public release, push, merge or notarization action.
