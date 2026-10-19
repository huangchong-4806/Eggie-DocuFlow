# Eggie DocuFlow V1.5.0 PDF Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 V1.5.0 将已确认的 PDF 工作区 V2 落地为原生桌面功能，提供安全脱敏、完整页面预览、图片水印及多样式页码。

**Architecture:** 页面编辑和内容编辑共用一个内存会话，保留不可变来源快照及小型编辑记录。一个串行后台进程完成 PyMuPDF 操作；主界面使用现有 Qt 控件和文件安全发布工具。只新增工作区业务文件和界面文件，现有组件就地复用，不重构其他工具。

**Tech Stack:** Python >=3.10；本机可用 Python 3.12.13；PyMuPDF 1.28.2（新增、AGPLv3）、现有 PySide6 / pypdf / Pillow；unittest / QtTest。

**Spec:** `PRD.md` 第九节，2026-09-15 V1.5.0 PDF 工作区升级。第一至八节为 V1.4.0 历史基线，不是本次打包发布指令。

**Approved UI:** `/Users/huang/.codex/visualizations/2026/09/14/01a09e8c-8cac-7420-a4dc-b5a4e7f76a52/eggie-pdf-workspace-v2.html`。该 HTML 为视觉与交互参考，不能直接当作真实 PDF 引擎；同目录 V1 原型保持原样。

## Global Constraints

- 目标版本固定为 V1.5.0（用户已确认）；当前已发布版本为 V1.4.0，旧版下载和发布记录保留。新功能验收后统一修改运行程序的版本标识，不在本次文档整理中提前改号。
- 名称为 Eggie DocuFlow / Eggie文档处理系统；沿用已确认的蓝色原生桌面界面。
- 未涂黑的原有文字继续可以选中、复制和搜索；不能把整页改成图片来完成本功能。
- 标记数量不设人为上限；现有单次 1,000 页的导入保护暂保留。
- 源 PDF 始终不修改；任何正式结果先完整写入并验证，再以不覆盖的方式发布。
- PyMuPDF 操作集中在一个串行后台进程中，不跨线程共享引擎对象。
- 不记录选择文字、原文、密码或水印图片内容；不自动 OCR、不上传文件。
- 新功能先有失败测试，再实现，再验证；不得仅以原型测试代替 PDF 和桌面测试。
- 保留原型 V1、V2 和旧 `.venv`；不改系统 Python，不变更无关业务规则。
- 用户已确认范围并要求开始开发；在当前任务内顺序执行，不默认派发子任务，不自动创建新开发副本。
- 各任务完成后检查差异和测试；只有用户另行授权才执行 Git 提交、推送或发布。下文“检查点”不代表自动提交。

## 文件边界

| 文件 | 职责与改动 |
| --- | --- |
| `pdf_workspace.py`（新增） | 数据类、页范围／编号计算、来源快照、渲染、文字几何、真实脱敏、导出验证、后台进程入口 |
| `ui/pdf_workspace.py`（新增） | 页面／内容工作区、共享状态、撤销、设置、另存与未保存提示 |
| `ui/pdf_widgets.py` | 复用缩略图卡片／网格，增加可缩放页面画布与区域／文字选择 |
| `ui/tasks.py` | 在现有进程模式旁增加一个具体的 PDF 工作进程控制器 |
| `pdf_toolbox.py` | 修复 `save_pages` 重复读取与直接写最终路径，保留其他后端调用契约 |
| `app.py`、`ui/theme.py` | 工作区入口、更多工具、退出检查；仅增加必要的主题选择器 |
| `tests/test_pdf_workspace.py`（新增） | 会话规则、几何、真实 PDF、安全导出、进程协议检查 |
| `tests/test_pdf_workspace_ui.py`（新增） | Qt 鼠标、键盘、页面切换、未保存、预览和操作状态检查 |
| `tests/test_pdf_toolbox.py`、`tests/test_app_navigation.py`、`tests/test_release_metadata.py` | 相关旧行为回归及许可证资源检查 |
| `requirements.txt`、`.github/workflows/ci.yml` | 固定引擎版本及 CI 安装；不顺手升级其他依赖 |
| `version.py`、`tests/test_release_metadata.py`、`app.py`、`packaging/EggieDocuFlow.spec` | 新功能验收后统一为 1.5.0，核对开发状态、软件显示和构建号；不修改旧版发布记录 |
| `LICENSE`、`licenses/AGPL-3.0.txt`（新增）、`THIRD_PARTY_NOTICES.md`（新增）、`README.md`、两个 `packaging/*.spec` | 保留 MIT 原文、明确组合分发条款、完整 AGPL 与第三方声明、运行说明和随包资源 |
| `.gitignore`、`licenses/GPL-3.0.txt`、`licenses/LGPL-3.0.txt` | 忽略 README 中的新独立环境目录；补齐 Qt 所需的本地许可证正文 |

不生成专用审计日志、常驻服务、插件框架、网页应用或新的测试框架。测试样本由 unittest 在临时目录生成，用虚构内容，测试退出自动清理。

## 任务 1：安全保存与可复现的开发环境

**Files:** 修改 `pdf_toolbox.py`、`tests/test_pdf_toolbox.py`；只读核对启动脚本和原依赖。

**Interfaces:** 消费 `PdfPageRef`、`PdfToolResult`、`_publish_writer(writer, output_file)`；保持 `save_pages(page_refs, output_file, title="PDF 页面整理") -> PdfToolResult` 不变。

- [x] 记录 `git status --short` 和原有测试结果。本机 `.venv` 实测为 3.9.6；使用已核验的 `/Users/huang/.local/bin/python3.12` 在 `mktemp -d` 创建的任务临时目录内建独立环境，不覆盖原 `.venv`。后续命令中 `PDF_WORK_PYTHON` 指该目录内的 `bin/python`，全程不更改 HOME / CODEX_HOME。

```bash
PDF_WORK_ENV=$(mktemp -d /private/tmp/eggie-pdf-workspace.XXXXXX)
/Users/huang/.local/bin/python3.12 -m venv "$PDF_WORK_ENV"
PDF_WORK_PYTHON="$PDF_WORK_ENV/bin/python"
"$PDF_WORK_PYTHON" -m pip install -r requirements.txt
QT_QPA_PLATFORM=offscreen PYTHON="$PDF_WORK_PYTHON" scripts/run_macos_python.sh -m unittest discover -s tests -v
```

- [x] 在 `PdfToolboxTests` 中加入失败测试，沿用该类的临时目录和 `make_pdf`。同一个文件读取一次；写入中断不产生最终 PDF。

```python
def test_save_pages_reads_source_once(self):
    source = self.make_pdf("source.pdf", 3)
    with patch("pypdf.PdfReader", wraps=PdfReader) as reader:
        save_pages([PdfPageRef(str(source), i) for i in range(3)], self.root / "out.pdf")
    self.assertEqual(reader.call_count, 1)

def test_save_pages_failed_write_has_no_final_pdf(self):
    source = self.make_pdf("source.pdf", 1)
    target = self.root / "out.pdf"
    with patch("pypdf.PdfWriter.write", side_effect=OSError("disk full")):
        with self.assertRaises(OSError):
            save_pages([PdfPageRef(str(source), 0)], target)
    self.assertFalse(target.exists())
```

- [x] 运行 `QT_QPA_PLATFORM=offscreen PYTHON="$PDF_WORK_PYTHON" scripts/run_macos_python.sh -m unittest discover -s tests -p test_pdf_toolbox.py -v`，确认新测试分别因读取 3 次、残留最终文件而失败。
- [x] 最小修复：用显式条件缓存 reader，末尾调用 `_publish_writer`；记录其返回的实际路径。其余 PDF 工具不改。

```python
if source not in readers:
    readers[source] = PdfReader(source)
# writer 构造完成之后：
output_file = Path(_publish_writer(writer, output_file))
```

- [x] 重跑同一命令及原有同名文件测试，必须全部通过。检查点：只改变页面保存，不改变排序、旋转或日志字段。独立环境路径保存在本次任务状态中，最终清理时核对确切路径，不运行宽泛递归删除。

## 任务 2：纯数据会话、页范围和编号规则

**Files:** 新增 `pdf_workspace.py`、`tests/test_pdf_workspace.py`。

**Interfaces:** 定义以下普通数据，不存 Qt / PyMuPDF 对象，不在模型中做文件 IO。

```python
from dataclasses import dataclass, field, replace

Rect = tuple[float, float, float, float]

@dataclass(frozen=True)
class WorkspacePage:
    page_id: str
    source_id: str
    source_index: int
    rotation: int = 0  # 相对来源的额外顺时针旋转

@dataclass(frozen=True)
class RedactionMark:
    mark_id: str
    page_id: str
    rects: tuple[Rect, ...]
    mode: str = "area"  # area / text
    applied: bool = False

@dataclass(frozen=True)
class PageScope:
    ranges: str = ""  # 空字符串 = 全部；非空遵守 1-3,5
    skip_first: bool = False

@dataclass(frozen=True)
class WatermarkOptions:
    kind: str = "none"  # none / text / image
    text: str = ""
    image_id: str = ""
    angle: int = -32  # 0 / -32，与已确认 V2 原型一致
    tiled: bool = False
    size: float = 100.0  # 百分比，与 V2 原型一致，布局时换算为页面单位
    opacity: float = 0.18
    spacing: float = 120.0  # 平铺间距，与 V2 原型一致
    scope: PageScope = field(default_factory=PageScope)

@dataclass(frozen=True)
class NumberOptions:
    enabled: bool = False
    style: str = "plain"  # plain / dash / chinese / fraction / chinese_total
    start: int = 1
    position: str = "bottom_center"
    scope: PageScope = field(default_factory=PageScope)

@dataclass
class WorkspaceState:
    pages: list[WorkspacePage] = field(default_factory=list)
    marks: list[RedactionMark] = field(default_factory=list)
    watermark: WatermarkOptions = field(default_factory=WatermarkOptions)
    numbers: NumberOptions = field(default_factory=NumberOptions)

def pending_count(state: WorkspaceState) -> int:
    return sum(not mark.applied for mark in state.marks)

def marks_with_state(marks: list[RedactionMark], applied: bool) -> list[RedactionMark]:
    return [replace(mark, applied=applied) for mark in marks]
```

另外实现 `resolve_pages(scope: PageScope, count: int) -> tuple[int, ...]`（零基、按文档顺序、去重）和 `number_label(options: NumberOptions, ordinal: int, total: int) -> str`（ordinal 零基、total 为输出总页数）。位置仅接受六个明确值；矩形要求有限数值、非空且位于来源页面内。

- [x] 新测试至少包含以下断言；附加表驱动无效输入 `0`、`3-1`、越界、空选中结果、非数字、负起始数，均期待 `ValueError`。

```python
scope = PageScope("1-3,2,5", True)
self.assertEqual(resolve_pages(scope, 5), (1, 2, 4))
self.assertEqual(number_label(NumberOptions(style="fraction"), 0, 4), "1 / 4")
state = WorkspaceState(marks=[RedactionMark(str(i), "page-a", ((1, 1, 2, 2),)) for i in range(10001)])
self.assertEqual(pending_count(state), 10001)
state.marks = marks_with_state(state.marks, True)
state.marks.append(RedactionMark("new", "page-a", ((3, 3, 4, 4),)))
self.assertEqual(pending_count(state), 1)
```

- [x] 运行 `"$PDF_WORK_PYTHON" -m unittest discover -s tests -p test_pdf_workspace.py -v`，先见缺失接口失败。
- [x] 实现数据类和上述函数；范围按逗号拆分、每段整数或闭区间验证后累积到集合，最终排序，按 skip_first 删除 0；不添加通用解析器依赖。
- [x] 同一命令通过后，检查“密文按 page_id 归属”和“旋转不修改密文源坐标”，避免后续代码重新按列表下标定位标记。

## 任务 3：引擎、真实页面预览与坐标

**Files:** 修改 `pdf_workspace.py`、`tests/test_pdf_workspace.py`、`requirements.txt`、`.github/workflows/ci.yml`。

**Interfaces:** 新增 `PdfWorkspaceEngine`，只在后端进程或单线程测试中使用：

- `open_pdf(path: str, password: str = "") -> tuple[WorkspacePage, ...]`：读取一次并保留 bytes 快照、生成稳定 source_id / page_id，错误文件不替换旧会话。
- `render_page(state: WorkspaceState, page_id: str, max_pixels: int = 1600) -> dict`：返回 `png: bytes`、`width_pt: float`、`height_pt: float`、`source_to_view: tuple[float, ...]`（六元素仿射矩阵）、`chars: tuple[dict, ...]`；每个 char 含 `text`、`bbox`、`line_id`、`char_id`。
- `inspect_document(state: WorkspaceState) -> dict`：返回可见批注、表单、附件、图层、签名、复用图片等计数，以及 `blocking_reasons: tuple[str, ...]`。
- `close() -> None`：关闭所有文档并释放快照；不写原文缓存文件。

- [x] 先加最小真实 PDF 测试，不用真实业务材料：

```python
import pymupdf

doc = pymupdf.open()
page = doc.new_page(width=300, height=400)
page.insert_text((30, 50), "SECRET-123 KEEP-456")
source = self.root / "synthetic.pdf"
doc.save(str(source))
doc.close()
engine = PdfWorkspaceEngine()
state = WorkspaceState(pages=list(engine.open_pdf(str(source))))
preview = engine.render_page(state, state.pages[0].page_id)
self.assertTrue(preview["png"].startswith(b"\x89PNG"))
self.assertIn("KEEP-456", "".join(char["text"] for char in preview["chars"]))
engine.close()
```

- [x] 安装固定 `PyMuPDF==1.28.2` 到独立环境，加入 requirements 与现有 CI 依赖列表。先确认测试因缺失 `PdfWorkspaceEngine` 失败；如果无兼容 wheel，不自动编译或替换系统环境，报告具体依赖原因。
- [x] 使用 `pymupdf.open(stream=source_bytes, filetype="pdf")` 缓存来源；按页创建工作副本，`get_pixmap` 输出 PNG，`get_text("rawdict")` 获取逐字坐标。来源坐标统一为引擎的未旋转页面坐标；视图应用来源 rotation 与额外 rotation，鼠标命中通过同一个矩阵的逆变换还原，不能重复扣裁剪偏移。

```python
# 只传普通坐标；Qt 层使用同一组六个元素建立 QTransform。
matrix_values = tuple(page.rotation_matrix)
raw = page.get_text("rawdict")
png = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png")
```

- [x] 扩展同一测试文件：0/90/180/270 度、额外旋转、非零 CropBox、大小混合页；源点 → 视图 → 逆变换误差小于 0.1 pt，真实截图中的字符范围与选择吻合。加密文件错误密码、坏 PDF、打开后来源被改动均不得污染旧快照。
- [x] 重跑后端测试通过。检查点：不能把渲染图片当作文档保存，文本信息仅在进程／界面内存使用，禁止 debug 打印原文。

## 任务 4：真实脱敏与验证后导出

**Files:** 修改 `pdf_workspace.py`、`tests/test_pdf_workspace.py`；复用 `utils/file_helper.py`，不改变其其他调用者。

**Interfaces:** 为引擎新增：

- `validate_apply(state: WorkspaceState, allow_cleanup: bool = False) -> None`：执行全部待应用标记的试处理与结构检查，成功才允许 UI 将它们设为 applied。
- `export_pdf(state: WorkspaceState, output_file: str, allow_cleanup: bool = False) -> PdfToolResult`：全局 pending 检查、页数／范围校验、真实重建、临时保存、重新核对、安全发布。
- 内部 `_build_document(state: WorkspaceState, allow_cleanup: bool)` 同时服务真实预览与导出；仅 applied 标记生效。验证应用时传入临时全部 applied 的副本，失败不改变原 state。

- [x] 测试在任务 3 的虚构文件中用 `search_for("SECRET-123")` 得到范围，构造已应用标记；输出用独立 pypdf 提取，来源哈希前后不变。

```python
import hashlib
from pypdf import PdfReader

before = hashlib.sha256(source.read_bytes()).hexdigest()
with pymupdf.open(str(source)) as doc:
    rect = tuple(doc[0].search_for("SECRET-123")[0])
state.marks = [RedactionMark("m1", state.pages[0].page_id, (rect,), "text", True)]
result = engine.export_pdf(state, str(self.root / "redacted.pdf"))
text = "\n".join(page.extract_text() or "" for page in PdfReader(result.output_file).pages)
self.assertNotIn("SECRET-123", text)
self.assertIn("KEEP-456", text)
self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
```

- [x] 运行后端测试，确认缺失 export 接口或仅覆盖黑块的实现不能通过。
- [x] 实现每页 `add_redact_annot` 与 `apply_redactions`，明确选择文本删除、图片像素处理和相交矢量处理的版本常量，先用微型测试验证常量真实语义，不能依赖文档中有歧义的数字默认值。每次从来源新建，避免二次应用累积损伤。

```python
for mark in page_marks:
    for rect in mark.rects:
        page.add_redact_annot(pymupdf.Rect(rect), fill=(0, 0, 0))
page.apply_redactions(
    images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
    graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
    text=pymupdf.PDF_REDACT_TEXT_REMOVE,
)
```

- [x] 普通注释和表单用可验证的静态外观处理；清理附属信息需 allow_cleanup 明确授权。隐藏图层、动态表单或不能证明安全的复用图片报明确错误。敏感区域外的隐形 OCR 文字不能被全局 scrub 默认选项误删；保留必要 producer 署名，但不能复制原作者、主题、附件等可能包含敏感内容的元数据。
- [x] 临时 PDF 使用完整新写入（`incremental=False, garbage=4, deflate=True`），重开核对页数、文字区域、附属对象以及页面渲染；再复用 `publish_output`。验证失败只删除本次临时路径。日志失败返回有效结果及界面警告，不能把已成功生成的 PDF 报成失败。

```python
temporary = temporary_output(target)
try:
    document.save(str(temporary), incremental=False, garbage=4, deflate=True)
    self._verify_output(str(temporary), state)
    final = publish_output(temporary, target)
finally:
    Path(temporary).unlink(missing_ok=True)
```

`_verify_output(path: str, state: WorkspaceState) -> None` 必须实现而非空函数：核对输出页数／页面尺寸、目标区域无原始文字、区域外保留预期字符和位置、文档无附件／脚本／原文元数据、可提取图像无未处理目标像素；不以敏感词在其他未标记位置仍存在而误判失败。无法验证的结构在 inspect 阶段阻止。

- [ ] 在同一测试文件添加：原文隐藏 OCR、可提取图片像素、同图片多次引用、矢量、注释文本／表单值、附件与脚本、增量旧版本、中文、部分字符相交、重叠密文、标记旁完整文字。检查解码对象和提取图片，另用 pypdfium2 渲染结果核对；“安全拒绝”与“安全成功”都要断言明确结果。
- [x] 加入全局 pending 阻止、空文档、同名目标、模拟写满／核验失败／取消、有效 PDF 之后日志失败的回归。所有测试通过后才允许接入 UI 中的“应用密文”按钮。

## 任务 5：一个后台进程与预览请求

**Files:** 修改 `pdf_workspace.py`、`ui/tasks.py`、`tests/test_pdf_workspace.py`。

**Interfaces:** `run_pdf_workspace_worker(request_queue, response_queue)` 为可 pickle 的顶层进程入口；`PdfWorkspaceProcess(QObject)` 提供 `submit(operation: str, payload: dict, revision: int) -> int`、`shutdown() -> None` 和 `completed(int, int, object)` / `failed(int, int, str)` 信号（request_id、revision、结果）。

允许的 operation 仅 `open`、`inspect`、`render`、`apply`、`export`、`close`；payload 为对应方法的具名普通参数。未知操作明确拒绝，不用反射任意执行方法。worker 独占引擎，Qt 定时器只轮询队列，不在 Qt 线程调用引擎。

- [x] 创建 spawn 进程测试，打开临时虚构 PDF 再渲染后关闭：

```python
context = multiprocessing.get_context("spawn")
requests, responses = context.Queue(), context.Queue()
process = context.Process(target=run_pdf_workspace_worker, args=(requests, responses))
process.start()
requests.put((1, 0, "open", {"path": str(source)}))
request_id, revision, kind, result = responses.get(timeout=15)
self.assertEqual((request_id, revision, kind), (1, 0, "completed"))
requests.put((2, 0, "close", {}))
process.join(timeout=5)
self.assertFalse(process.is_alive())
```

- [x] 运行后端测试，先确认进程入口缺失而失败。实现明确分支分派和 `finally: engine.close()`；消息带 revision，由 UI 丢弃过期 render 结果，但不能丢掉 export 的正式成功／失败。
- [x] 只排队当前页和可见缩略图，缓存以 source/page/rotation/settings revision 为键并按总字节 LRU 淘汰；预算不是标记上限。设置快速变化时合并未开始的 render 请求，不能积累整份文档的高分辨率图片。
- [x] 添加退出、无效操作、工作进程异常、旧 revision 迟到、取消导出的检查。正常取消由任务边界处理并清临时文件；进程被迫停止后禁止未验证文件发布，UI 保留现有编辑状态并提示重新打开。
- [x] 重跑测试通过。检查点：现有 invoice 进程与 OCR 线程保持原行为；沿用 `main.py` 的 freeze_support，不另加启动器。

## 任务 6：原生画布、页面编辑与共用状态

**Files:** 新增 `ui/pdf_workspace.py`、`tests/test_pdf_workspace_ui.py`；修改 `ui/pdf_widgets.py`、`app.py`、`ui/theme.py`、`tests/test_app_navigation.py`。

**Interfaces:** `PdfWorkspaceWidget(parent=None)` 持有 `state: WorkspaceState`、`undo_stack: QUndoStack` 和进程；提供 `open_paths(paths: tuple[str, ...]) -> None`、`has_unsaved_changes() -> bool`、`request_close() -> bool`、`shutdown() -> None`。`PdfPageCanvas(QGraphicsView)` 提供 `set_page(preview: dict) -> None`、`set_mode(mode: str) -> None`、`set_marks(marks: tuple[RedactionMark, ...]) -> None`，发出 `area_selected(object)`、`text_selected(object)`、`mark_changed(str, object)`；矩形均为来源坐标。

- [x] QtTest 使用不访问网络／真实业务文件的假进程结果，先验证页面编辑和内容编辑切换不清空同一 state、旋转／排序后 page_id 与 marks 关系不变。保留旧导航测试其余断言，只替换旧七标签布局的期望。

```python
widget = PdfWorkspaceWidget()
original = widget.state
widget.module_tabs.setCurrentIndex(1)
self.assertIs(widget.state, original)
self.assertEqual(widget.module_tabs.tabText(0), "页面编辑")
self.assertEqual(widget.module_tabs.tabText(1), "内容编辑")
```

- [x] 运行 `QT_QPA_PLATFORM=offscreen PYTHON="$PDF_WORK_PYTHON" scripts/run_macos_python.sh -m unittest discover -s tests -p test_pdf_workspace_ui.py -v`，确认缺失 widget 而失败。
- [x] `app.py` 只创建一个工作区和“更多工具”容器；后者复用现有五个 tab 创建函数。接入 shared state 后移除旧页面整理／水印的重复 UI 入口和不再引用的回调，保留 `pdf_toolbox.py` 兼容 API。删除前 `rg` 核对每个调用者，避免悬空方法。
- [x] 画布用 QGraphicsView 原生缩放／滚动，图片按比例完整展示，叠加可编辑矩形；复用 PdfPageCard / PdfPageBoard 的拖拽和选择，仅将 owner 指向工作区。标准／大图只改卡片尺寸和渲染目标，不裁剪页面。

```python
self.canvas.fitInView(self.canvas.sceneRect(), Qt.KeepAspectRatio)
# 命中位置使用 preview['source_to_view'] 的逆变换；缩放由 mapToScene 先处理。
scene_point = self.canvas.mapToScene(event.position().toPoint())
source_point = source_transform.inverted()[0].map(scene_point)
```

- [x] 多选移动、旋转、删除、增加页面用 QUndoCommand 保存变更的 page refs 和关联 marks，不保存整份 PDF；删除页面后对应标记随之移出，撤销恢复。提供按钮作为拖拽的键盘可达替代。
- [ ] 测试网格完整长宽比、双击预览、页码跳转越界、适合整页／宽度、1000 页提示、加载失败保留旧文档、小窗口工具栏换行、其他五工具可打开。重跑 UI 和导航测试通过；实际源文件拖入和窗口缩放另作人工检查。

## 任务 7：区域／文字密文操作与可逆会话

**Files:** 修改 `ui/pdf_workspace.py`、`ui/pdf_widgets.py`、`tests/test_pdf_workspace_ui.py`。

**Interfaces:** 消费 Canvas 三个选择信号及 worker `apply`。`PdfWorkspaceWidget.apply_pending() -> None`、`return_to_editing() -> None`、`export_current() -> None` 均操作同一 state。定义 `module_tabs`、`tool_tabs`、`apply_button`、`export_button`、`canvas` 等实际控件属性供测试使用，避免按中文文本模糊定位多个同名按钮。

- [x] QtTest 用鼠标按下／移动／释放完成真实框选，而不是直接调用新增方法；再验证跨行文字返回多个 rect、缩放及旋转后仍命中。示例：

```python
QTest.mousePress(widget.canvas.viewport(), Qt.LeftButton, pos=start)
QTest.mouseMove(widget.canvas.viewport(), end, delay=20)
QTest.mouseRelease(widget.canvas.viewport(), Qt.LeftButton, pos=end)
self.assertEqual(len(widget.state.marks), 1)
```

start/end 由任务 3 的已知虚构字符位置经 `source_to_view` 和 `mapFromScene` 得出，不硬编码窗口屏幕坐标。

- [x] 运行 UI 测试先见选区或状态断言失败。实现区域边界拖动／缩放，文字命中按 char_id 范围并按 line_id 分组，不在标记模型里存明文。
- [x] 点击应用时先 inspect；清理附属信息明确确认后提交 apply。完成消息匹配此次 revision 才把待应用改成 applied，载入真实重渲染结果。apply 失败不改状态；返回修改恢复全部 pending 并重渲染。

```python
candidate = replace(self.state, marks=marks_with_state(self.state.marks, True))
self.worker.submit("apply", {"state": candidate, "allow_cleanup": approved}, self.revision)
# 仅成功回调把 candidate 作为一次可撤销的会话变更。
```

- [ ] 添加“应用→新增→返回修改→删除→撤销／重做”、10,001 条标记列表分页和全量计数、无文字页提示、Escape 取消当前拖拽、Delete 删除选中、Tab 焦点和区域越界拒绝测试。
- [x] 在水印或页面编辑中尝试导出时全局 pending 同样被阻止；导出按钮不是唯一安全判断，后端测试继续断言拒绝。全部通过后再用真实样本应用和独立打开导出文件。

## 任务 8：图片水印与页码样式

**Files:** 修改 `pdf_workspace.py`、`ui/pdf_workspace.py`、`tests/test_pdf_workspace.py`、`tests/test_pdf_workspace_ui.py`；必要时复用 `pdf_toolbox.py` 的 Qt 绘制思路，不沿用旧 crop/rotation 假设。

**Interfaces:** 引擎新增 `open_watermark_image(path: str) -> str`，在 worker 的明确 `image` 操作中返回 image_id 并保存规范化图片快照；预览和导出共同使用 WatermarkOptions、NumberOptions。新增 `watermark_boxes(width: float, height: float, item_width: float, item_height: float, spacing: float, tiled: bool) -> tuple[Rect, ...]` 用页面单位生成布局。

- [ ] 先加入横向／倾斜 × 单个／平铺、文字／图片、五样式 × 六位置及范围测试；图片由 Pillow 生成透明 PNG，导出后独立渲染检查颜色及透明区域，不只检查设置值。

```python
self.assertEqual(number_label(NumberOptions(style="chinese_total", start=3), 1, 8), "第 4 页，共 8 页")
boxes = watermark_boxes(300, 400, 60, 30, 20, True)
self.assertGreater(len(boxes), 1)
self.assertTrue(all(x1 > x0 and y1 > y0 for x0, y0, x1, y1 in boxes))
```

- [x] 运行后端和 UI 测试，确认布局／样式缺失导致失败。实现一个渲染路径：先来源和密文，后水印，再页码；水印文字用已嵌入的可用中文字体，图片使用 Pillow 校验、转正 EXIF 方向、保留 alpha，不保留原始 EXIF 元数据。
- [x] 单个居中；平铺用已旋转元素的外接矩形尺寸加 spacing 生成覆盖页面的规则网格并裁到页面。文字字号／图片比例换算成 PDF 点，禁止直接复用屏幕像素。每个 page 范围先 `resolve_pages`，分页标签 `number_label`，当前文档／提取结果各自传入其实际总页数。

```python
numbered = resolve_pages(state.numbers.scope, len(state.pages))
labels = {index: number_label(state.numbers, ordinal, len(state.pages))
          for ordinal, index in enumerate(numbered)}
```

- [x] 设置面板提供方向、布局两组独立控件，图片文件选择、透明度、大小、间距与范围；切换工具不销毁设置。默认及上下限以 V2 原型已确认控件为准，界面和后端一致验证有限数值、opacity 在 0..1、正尺寸、非负间距，拒绝空图片／空文字。
- [ ] 检查小页面、不同纸张、旋转和 CropBox、中文字体跨平台、跳过首页、重复范围、提取后总数重算。实际操作本地文件选择器，不以假进程图片测试冒充真实选图通过。全部测试通过后记录真实渲染结果。

## 任务 9：未保存、导出、取消与关闭保护

**Files:** 修改 `ui/pdf_workspace.py`、`app.py`、`ui/tasks.py`、两个新测试文件。

**Interfaces:** `has_unsaved_changes` 比较已成功完整保存的会话版本；`request_close` 负责另存／放弃／取消，允许异步保存完成后再继续待执行的关闭动作。完整另存调用 `export_current`；提取先构建仅选中页面的临时 state，保留主 state 不变。

- [x] 先测试：换文件保存失败不能丢旧文档；另存对话框取消不能关闭；保存全部成功才清 dirty；提取成功不清主文档 dirty；恢复编辑后重新变 dirty。

```python
with patch.object(widget, "confirm_discard", return_value="cancel"):
    self.assertFalse(widget.request_close())
self.assertTrue(widget.has_unsaved_changes())
```

`confirm_discard() -> str` 是工作区内一个具体 QMessageBox 包装，只返回 `save` / `discard` / `cancel`，供真实弹窗和测试共用。

- [x] 运行 UI 测试确认保护缺失而失败。实现仅在编辑变更时更新 revision；滚动、缩放、选页不弄脏文档。主窗口 closeEvent 先保持既有其他任务保护，再调用工作区关闭保护，确认后释放 worker。
- [x] 任务进行中仅锁定冲突操作，保留取消与进度；不要调用现有全栈禁用方式让取消按钮一起失效。错误提示用操作、页码和简短原因，避免原文及密码进入 traceback 文案。
- [x] 提取前检查主文档 pending，然后显示提取结果预览与实际水印／页码范围；空范围或无效页号阻止操作。导出消息附真实 final path，同名竞态由共享 publish_output 处理。
- [ ] 模拟中断、worker 退出、预览失败、输出只读、同名竞争、日志失败；源哈希不变，当前会话可继续，临时目录无半成品。运行后端、UI、导航和全部原有测试。

## 任务 10：开源声明、全面检查、V1.5.0 标识与本地交付

**Files:** 修改 `LICENSE`、`README.md`、`ui/pdf_workspace.py`、`version.py`、`app.py`、`tests/test_release_metadata.py`、`packaging/EggieDocuFlow.spec`、`packaging/EggieDocuFlow_windows.spec`；新增 `licenses/AGPL-3.0.txt`、`THIRD_PARTY_NOTICES.md`；只读核对 `main.py`、`scripts/build_macos.sh`、`scripts/build_windows.ps1`、`packaging/EggieDocuFlow_windows.iss` 的版本传递；更新本计划实际勾选状态。

**Interfaces:** 原 MIT 正文与作者署名保持，LICENSE 说明含 PyMuPDF 的组合应用遵守 AGPLv3，AGPL 正文来自官方许可证；notice 对应实际安装版本和随包组件。两个 spec 的 datas 包含上述文件；README 的“源码运行／开源说明”注明 V1.5.0 尚未发布，不改变现有 V1.4.0 下载链接。版本唯一来源仍为 `version.py` 的 `APP_VERSION`；构建脚本继续从该文件取值，不增加第二套版本配置。

- [x] 执行已安装包元数据只读核对，包含 PyMuPDF／MuPDF、PySide6／Qt 等实际随包组件。不能因为项目本身开源就跳过第三方要求；发现冲突先报告，不替他人重新授权。
- [x] 在已有发行元数据测试中加入资源存在／声明包含原作者和 AGPL 路径的失败测试，然后补齐声明和 spec 数据项。

```python
root = Path(__file__).resolve().parents[1]
self.assertIn("Copyright (c) 2026 qq448223855-rgb", (root / "LICENSE").read_text())
self.assertIn("GNU AFFERO GENERAL PUBLIC LICENSE", (root / "licenses/AGPL-3.0.txt").read_text())
for spec_name in ("EggieDocuFlow.spec", "EggieDocuFlow_windows.spec"):
    self.assertIn("THIRD_PARTY_NOTICES.md", (root / "packaging" / spec_name).read_text())
```

- [x] 源码获取说明必须能映射到实际发布版本、依赖和构建脚本；当前未发布，不编造新 tag 或下载地址。工作区帮助菜单提供本地许可证可读入口，不能必须联网才能读许可。
- [x] 执行全量测试、`git diff --check`，检查新增依赖没有夹带凭证／`.env`／私有 PDF，复查全局调用链、异常路径和共享坐标。记录实际测试数量与失败数，不沿用历史“120 项”的数字。

```bash
QT_QPA_PLATFORM=offscreen PYTHON="$PDF_WORK_PYTHON" scripts/run_macos_python.sh -m unittest discover -s tests -v
git diff --check
git status --short
```

- [x] macOS 真实运行 `PYTHON="$PDF_WORK_PYTHON" scripts/run_macos_python.sh main.py`：逐项操作区域框选、文字选择、应用后新增、返回修改、页面完整预览、真实选图、五个页码样式、页面范围、另存及退出提示。在独立 PDF 阅读器打开结果验证黑块和未遮挡文字复制／搜索；不得使用业务敏感资料上传测试。
- [x] 功能验收通过后，将现有 `test_v1_4_0_metadata_is_consistent` 拆成“当前开发版本”和“V1.4.0 历史下载”两项：前者要求 `APP_VERSION == "1.5.0"`、macOS 构建号为 `12`；后者保留对现有下载链接及 `release_notes_v1.4.0.md` 的检查。先确认新版断言在旧代码上失败，再更新版本；不为通过测试删除旧发布文件。

```python
# 新版元数据测试中的关键断言：
self.assertEqual(APP_VERSION, "1.5.0")
spec = (ROOT / "packaging" / "EggieDocuFlow.spec").read_text(encoding="utf-8")
self.assertIn('"CFBundleVersion": "12"', spec)
```

- [x] 在 `version.py` 设置 `APP_VERSION = "1.5.0"`、`BUILD_TYPE = "development"`，`BUILD_DATE` 使用实际完成核验当天的日期；`app.py` 的版本标签在该状态下显示“版本 1.5.0（开发版）”。将 macOS 构建号由 `11` 改为 `12`；确认 Mac ZIP／App 和 Windows 安装包仍由同一版本值自动命名，不生成安装包。
- [x] 重跑版本测试、全量测试和 `main.py --version`，真实窗口核对“1.5.0（开发版）”；README 分清“已发布 V1.4.0”和“开发中 V1.5.0”。正式发布另经确认后再设为 release，不能用修改版本号冒充新功能已交付。
- [x] Windows 若无实际环境，明确列为未验证，不声称已跨平台可用或已打包。打包脚本仅核对资源配置；生成／上传安装包要等用户另行确认。
- [x] 按 PRD 9.10 逐项记录完成与未完成；清理本次临时测试目录、预览文件和隔离环境，保留原 `.venv`、原 PDF、原型。交付差异、测试事实和运行环境说明，不自动提交。

## 书面自检与执行顺序

规格覆盖：9.2→任务6；9.3→任务1/5/9；9.4→任务2/3/4/7；9.5→任务1/3/5/6；9.6/9.7→任务2/8/9；9.8→任务1/3/5/10；9.9→全局约束；9.10→任务4/6/7/8/9/10。

依赖顺序：1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10。引擎安全检查失败时继续可独立完成的页面/UI测试，但不能开放或宣称密文导出完成。许可文件须与引擎接入在同一个可发布变更集中交付，不允许先对外分发程序再补许可。

### 本地开发验收记录（2026-09-15）

- 用户已要求开始开发；当前分支 `codex/workspace-cleanup-20260914`，保留已有 PRD／计划改动，不提交或推送。
- 基线：原有 137 项测试全部通过。默认测试沙箱曾阻止 macOS Quick Look 子进程，获准在沙箱外复核后通过，未改动原转换逻辑。
- 页面安全保存：两项新增测试先复现重复读取和半成品残留；修复后 5 项页面保存测试通过。
- 会话规则：4 项测试通过，覆盖范围去重／越界、五种页码，以及 10,001 条标记应用后新增和返回修改。
- 已实现：统一页面／内容工作区；完整缩略图、旋转排序和提取；区域／跨行文字密文；应用后新增、返回修改、撤销重做；文字／图片水印；五种页码、六个位置、独立范围；未保存、取消和安全另存保护。
- 安全检查：独立 pypdf、PDFium 提取与渲染；未遮挡的中文、英文、原有隐藏 OCR 文字保留；覆盖图片像素、矢量、附件、表单隐藏值、脚本和旧增量记录。隐藏图层、动态表单、替代文字、不可安全处理的复用／透明／旋转图片明确拒绝。
- 检查后修复：嵌套或转义名称的替代文字遗漏；取消操作后旧页面选区错绑；被阻止的保存残留关闭动作；同路径重新打开仍取旧快照；提取预览迟到；后台异常退出后仅清理自己登记的临时文件。保存后重新核对文字、结构及页面外观，再发布结果。
- macOS 真实窗口：实际打开 PDF、原生图片选择框与保存框；框选、多行文字选择、应用后新增、返回修改；三页完整缩略图；图片平铺、五种页码、跳过首页、未保存取消关闭；提取预览及真实后台导出通过。另用 macOS“预览”实际打开测试结果，观察黑块与保留内容；独立文字提取验证未遮挡内容可读取。
- 界面收尾：工具栏、缩略图导航、页码箭头、文件名、实际作用页数、签名提醒和进度文字已补齐；1440×940 与实际最小宽度 1180 的缩小窗口均检查。小窗口使用原生工具栏溢出入口，设置区域滚动，不遮挡另存按钮。
- 最终自动检查：197 项全部通过，0 失败；Python 3.12.13、PyMuPDF / MuPDF 1.28.2、PySide6 6.10.3。`git diff --check` 通过，`main.py --version` 与真实窗口均为 1.5.0（开发版）；原有 1.4.0 下载和发布文件保留。
- 负载样本：101 页虚构 PDF、10,001 条实际应用标记，首张 1600 像素预览约 0.10 秒；包含保存后外观核验的导出约 6.40 秒，测试进程峰值内存约 96.0 MiB。最后一条标记生效、输出 101 页、处理记录计数 10,001。该数字只代表本机合成样本，不是所有 PDF 的性能保证。
- 开源准备：保留原 MIT 全文；新增 AGPL／GPL／LGPL 正文与第三方声明；两个打包配置均能找到 48 项递归元数据资源。只检查配置及资源，不代表安装包已经构建或完成分发合规验收。
- 未逐项完成的扩展检查仍保留未勾选：Windows 实机与安装包、各类 PDF 的全部排列组合、Finder 实际拖入／完整 Tab 焦点巡检、真实只读输出目录场景。它们不被本机自动测试或“预览”打开测试冒充；正式发布前继续核验。
- 最后一次限定代码复核未发现阻断问题；另有 9 项相关检查通过，并复核了正常导出后登记临时文件清理、原文件不变、符号链接路径拒绝和进度消息不提前结束任务。
- 原 `.venv`、V1／V2 HTML 原型及用户 PDF 均保留。确认测试进程全部结束后，已删除 `/private/tmp/eggie-pdf-workspace.NTOO3d` 中约 487 MB 的独立环境、合成 PDF、测试截图与脚本，并确认该目录不存在；这些测试内容可重建。不修改系统 Python，不提交或推送，HEAD 仍为 `5d6e216`。

本次交付是 V1.5.0 本地开发代码，不是正式安装版。勾选表示相应本机实施和验证已完成；未勾选的复合验收项仍需补齐，以上记录优先于原计划示例。源码运行方式见 README，旧 Python 3.9 环境不能直接运行新增引擎。

### 复核后的限定修复（2026-09-15）

依据：PRD 9.11 和用户“确认修改”。仅修改 `pdf_workspace.py`、`ui/pdf_workspace.py`、`ui/tasks.py`、两份对应测试、README 及现有需求／计划记录；保留原有未提交改动。不新增依赖、界面布局或发布操作。

- [x] 先补失败检查：输入位置、撤销图片名称、排队取消、替换／放弃导入的资源释放、缺字阻断、保存后清理与日志异常。
- [x] 在既有进程队列内移除被取消的未开始任务；保留后台资源清理，活动导出仍检查取消事件。
- [x] 按明确的废弃来源 ID 释放快照，避免误删后来打开的文档；插入页面的撤销／重做来源不释放。
- [x] 设置内容未变化时不回填输入框；图片名称按当前图片 ID 同步；缺字在实际字体检查中拒绝。
- [x] 分清“正式文件未生成”和“正式文件已核验但清理失败”，保留全部提醒；修正构建环境说明。
- [x] 局部验证：25 项界面检查、41 项 PDF 核心检查通过；新增检查在修复前已观察到对应失败。
- [x] 完整回归与独立增量审查：当前代码 208 项检查全部通过（10.046 秒），新增 11 项检查。独立复核未发现运行逻辑阻塞问题；补齐其发现的 Windows 构建预期文件名，正式下载不变。
- [x] 真实界面组件与后台进程串联检查：换文件后旧来源不可再读取；插入及撤销／重做仍可预览；密文、中文水印与页码另存后重新读取正确，两份原文件摘要均不变。另用 Poppler 渲染并目视检查黑块、保留文字、水印和页码；此项为离屏组件检查，不冒充新一轮原生窗口或安装包验收。
- [x] 首轮全量检查曾停在原有 `test_global_progress_keeps_the_window_responsive` 的关闭提示。进程采样定位到测试收尾 `closeEvent` 的运行中线程提醒；结束该临时测试后，原测试单独复跑通过，再次全量运行 208 项通过。未修改该测试或相关功能，保留此偶发收尾时序记录。
- [x] `git diff --check` 通过；`main.py --version` 返回 `1.5.0`。没有构建安装包，没有提交、推送或发布；Windows 实机仍未验收。
- [x] 全部测试进程结束后，已删除 `/private/tmp/eggie-pdf-fixes.0J9Y4N` 中约 965 MB 的临时环境、缓存、合成样本、截图和测试快照，并确认目录不存在。测试内容可重建，原 `.venv` 和用户原文件保留；未额外留存本轮修复前代码备份。
