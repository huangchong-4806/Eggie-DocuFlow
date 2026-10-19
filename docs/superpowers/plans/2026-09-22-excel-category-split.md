# Excel 分类拆分 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 用户已审阅并明确授权开发，实施及验证证据见文末。当前不安排并行代理、提交、推送、打包或发布。

**Goal:** 在 V1.5 分类拆分中支持准确分组、可选导出、固定公式结果和执行前核对，保留原有按行数拆分。

**Architecture:** 使用独立分类读取、分组和导出模块，PySide6 三步页面接入原导航与后台任务。读取公式和缓存两种视图，预览产生不可变行映射和源文件摘要；导出只能消费确认过的预览。沿用现有 openpyxl，不引入 pandas 或外部服务，不直接套用简单网络脚本。

**Tech Stack:** Python、openpyxl==3.1.5、PySide6-Essentials==6.10.3、unittest；以现有 `.venv-pdf` 环境实测为准，不改旧环境。

**Spec:** [PRD 第十节](../../../PRD.md#十v15-excel-分类拆分2026-09-22-文档评审版)

## Global Constraints

- 用户已授权本地开发和完整功能测试；发布仍需另行授权。
- 默认全部数据；筛选／隐藏提示先于最终确认，选定后重新统计。
- 分类模式公式转为已保存的固定结果；不改变按行数模式。
- 原文件不变，不覆盖已有结果；取消和失败不公布半成品。
- 数据区域非分类列纵向合并数字或公式结果必须阻止自动重复。
- 输出类别默认全选；空白分类保留；完全空白行跳过并单独计数。
- 不把已保存的公式缓存说成最新计算结果。
- 任何生成的验收 Excel 必须使用 Microsoft Excel 实际打开；未验证平台明确记录。
- 现有工作区有 PDF 1.5 未提交修改，不能 reset、覆盖或混入本功能提交。

## Review Focus

1. 显示一样但类型不同的分类，及合法名称与清理后的名称碰撞：任务 2、3 覆盖。
2. 筛选状态、表格对象筛选、手动隐藏与全空行重叠，不能重复计数：任务 1、2 覆盖。
3. 合并区域被选区截断、数字看似文本、公式缓存缺失／空字符串：任务 1 覆盖。
4. 确认后源文件被保存或输出位置被占用，不能输出过时内容或覆盖文件：任务 3、4 覆盖。
5. 源单元格公式结果为等号开头文本，不能被输出组件重新当作公式：任务 3 覆盖。

## 已确认功能取舍与开发门槛

以 PRD 10.2—10.8 和用户后续逐项确认作为最终范围，不再以复制全部 Ablebits 选项作为交付目标。

| 功能 | 最终决定 | 对应任务 |
| --- | --- | --- |
| 原工作簿或副本内追加结果 | 不做，仅生成全新结果文件 | 3、4 |
| 前 N 个字符分类 | 不加入，只按完整值分类，保留忽略首尾空格选项 | 2、4 |
| 序号及自定义前后缀命名 | 不支持，沿用分类命名和必要的防重名编号 | 3、4 |
| 复制表头与首行格式 | 按表头行数重复复制、保留各行基本格式；不增加首行格式统一选项 | 3、4 |
| 保存／复用设置方案 | 不支持，每次重新设置、预览和确认 | 4 |
| 输入及复杂内容边界 | 只支持 .xlsx；跨边界、二维数据合并及不能保留的复杂对象预检阻止 | 1、3 |

产品功能选项、文档审阅和开发授权已完成。不得为已排除的功能添加页面选项、配置存储或导出分支。

官方资料：https://www.ablebits.com/docs/excel-split-table/ （2026-09-22 阅读，未实际操作商业插件）。没有官方证据的合并、缓存、空格行为不标为 Ablebits 已验证行为。

## 文件范围与职责

| 文件 | 后续拟操作与责任 |
| --- | --- |
| `excel_category_split.py` | 新增，数据类型、读取检查、分组、预览、命名和安全导出；规模增长时按实际职责拆分，不能引入无关重构 |
| `ui/excel_category_split.py` | 新增，三步表单、预览、异常、提示弹窗和任务状态 |
| `app.py` | 仅接入分类模式，当前拆分入口约 670 行及 5140—5320 行；执行前重新定位 |
| `tests/test_excel_category_split.py` | 新增，行映射、计数、缓存、合并、输出及失败处理 |
| `tests/test_excel_category_split_ui.py` | 新增，三步流程、可见性提示、确认／返回、选择及预览失效 |
| `tests/test_app_navigation.py` | 修改，两个模式切换和原入口回归 |
| `excel_merge_tool.py` | 默认只复用已读到的辅助逻辑；如需提取公用样式函数，单独展示最小差异，不改变 split_workbook_by_rows |
| `ui/tasks.py`、`ui/theme.py` | 默认复用，不计划无关修改 |
| `PRD.md`、本计划 | 更新确认状态和验收记录 |

## 任务 1：读取快照和前置检查（PRD 10.2—10.4）

**Files:** 创建 `excel_category_split.py` 和 `tests/test_excel_category_split.py`。

**Interfaces:** 使用以下不可变类型，后续任务不得另创字段名。键值保留类型，避免 True 与 1 或文本编号混在一起。

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class SplitOptions:
    source: Path
    sheet: str
    area: str | None
    header_rows: int = 1
    key_columns: tuple[int, ...] = ()  # 源工作表绝对列号
    trim_keys: bool = False
    visible_only: bool = False
    output_mode: str = "files"  # files 或 sheets
    output_dir: Path = Path(".")

@dataclass(frozen=True)
class SourceRow:
    number: int
    values: tuple[object, ...]  # 合并和公式结果解析后的值
    hidden: bool
    blank: bool

@dataclass(frozen=True)
class SourceSnapshot:
    source_sha256: str
    data_rows: tuple[SourceRow, ...]
    has_filter: bool
    has_hidden: bool
    issues: tuple[str, ...]

# inspect_source(options: SplitOptions) -> SourceSnapshot
```

- [ ] 先添加临时测试工作簿用例：指定区域、0／2 行表头、重复表头、选区超出有效区域、无数据、普通筛选、表格对象筛选、手动隐藏。
- [ ] 添加合并检查用例：分类列 A2:A4 文本展开；其他列数字 1000 跨三行必须列出地址并阻止；选区截断合并不可静默输出；二维合并按评审结论执行。
- [ ] 添加缓存用例：公式结果为 0、False、日期、字符串、错误值、缺失和合法空字符串。缓存样本用 Microsoft Excel 保存产生，禁止通过拆解重组 Excel 内部文件制造缓存；样本保留在测试专用范围，任务后清理临时文件。
- [ ] 运行 `./.venv-pdf/bin/python -B -m unittest discover -s tests -p 'test_excel_category_split.py' -v`，先确认尚未实现的行为失败。
- [ ] 实现两次只读源文件视图（保留公式／data_only），先核对地址和值再确定空白状态；公式视图不能混为输出值。映射过程只操作内存，出现问题返回具体位置并禁止后续输出。
- [ ] 用相同命令验证通过，检查输入文件字节摘要没变；记录新增用例覆盖和剩余边界。

## 任务 2：稳定分组、计数和类别选择（PRD 10.3、10.6）

**Files:** 修改 `excel_category_split.py` 和对应测试。

**Interfaces:** `build_preview(snapshot: SourceSnapshot, options: SplitOptions) -> SplitPreview`；`select_groups(preview: SplitPreview, ids: tuple[int, ...]) -> SplitPreview`。

```python
@dataclass(frozen=True)
class Group:
    id: int
    label: str
    source_rows: tuple[int, ...]

@dataclass(frozen=True)
class Counts:
    total: int
    hidden: int
    blank: int
    unselected: int
    exported: int

@dataclass(frozen=True)
class SplitPreview:
    options: SplitOptions
    source_sha256: str
    groups: tuple[Group, ...]
    selected_ids: tuple[int, ...]
    counts: Counts
```

- [ ] 添加数据序列 A／B／A／空类别：A 行必须跨位置归同组且保持源顺序，重复行保留。
- [ ] 添加多列组合碰撞、空值与真实“未分类”、001 与 1、大小写、空格差异测试；忽略空格选项只改变键，不改变 SourceRow.values。
- [ ] 添加可见性与空白重叠、部分选择、全不选测试，核心断言：

```python
self.assertEqual(
    preview.counts.total,
    preview.counts.hidden + preview.counts.blank
    + preview.counts.unselected + preview.counts.exported,
)
self.assertEqual(group.source_rows, (2, 4))
```

- [ ] 运行任务 1 的命令，确认新用例先失败。
- [ ] 实现先可见性、后空白、再分组和选择的顺序。内部用有类型的元组键，输出名只用作展示；根据首次出现顺序赋稳定 group.id，不能用名称作为身份。
- [ ] 相同命令验证全部用例通过；每个导出源行出现一次且仅一次。

## 任务 3：命名、基本格式及安全输出（PRD 10.4—10.6）

**Files:** 修改 `excel_category_split.py` 和对应测试；读取现有 `excel_merge_tool.py` 的复制行、列宽及目录防冲突实现作为本地参考。

**Interfaces:** `plan_names(preview: SplitPreview) -> tuple[str, ...]`；`export_split(preview: SplitPreview, progress_callback=None) -> ExportResult`。名称顺序对应 selected_ids；名字是导出确认方案的一部分，执行前变化应回到预览。

```python
@dataclass(frozen=True)
class ExportResult:
    output_files: tuple[Path, ...]
    exported_rows: int
    # 源行号 -> 输出文件、工作表、目标行号
    row_map: tuple[tuple[int, str, str, int], ...]
```

- [ ] 添加 Windows 保留名、中文长名、工作表 31 字符、大小写碰撞、非法字符清理后碰撞、生成后缀与真实分类同名测试。
- [ ] 添加两种输出的表头、行高列宽、日期金额格式和合并输出测试。字符串以等号开头时必须明确写为字符串。
- [ ] 添加保存中途异常、目录已存在、确认后源文件变化和 0 类别用例，先运行并确认失败。
- [ ] 在源文件摘要一致后重新读取快照；以明确的源行映射复制格式与固定结果，不调用旧的公式平移函数。多个文件各含一个结果表，一个文件则包含多个结果表。
- [ ] 使用独占创建的本次目录和暂存结果，全部保存成功并回读核对后公布；失败仅删除本次拥有的文件。写入名称再检查防碰撞，变化时要求重新确认。
- [ ] 回读固定结果并确认无公式：

```python
self.assertEqual(result.exported_rows, preview.counts.exported)
self.assertEqual(len({m[0] for m in result.row_map}), result.exported_rows)
for row in output_sheet.iter_rows():
    for cell in row:
        self.assertNotEqual(cell.data_type, "f")
```

- [ ] 运行分类测试及 `./.venv-pdf/bin/python -B -m unittest discover -s tests -p 'test_excel_merge_tool.py' -v`；旧按行数公式与格式测试必须不变。

## 任务 4：三步页面和两阶段确认（PRD 10.2、10.6）

**Files:** 新增 `ui/excel_category_split.py`、`tests/test_excel_category_split_ui.py`；修改 `app.py`、`tests/test_app_navigation.py`。

**Interfaces:** `CategorySplitPage(QWidget)`，通过构造参数 `inspect_fn`、`preview_fn`、`export_fn` 注入前述函数；使用现有 BackgroundTaskThread 执行读取和导出，UI 主线程只更新状态。内部 `confirmed_preview: SplitPreview | None` 在任何影响结果的输入变化时清空。

- [ ] 编写 UI 测试：返回不调用 export_fn；未选类别按钮禁用；有筛选或隐藏只提示一次当前快照；改变范围重新提示；选仅可见后数量同步；重复点击只触发一次导出。
- [ ] 核心交互断言示例（实际控件名固定为 confirm_button、back_button）：

```python
export_fn = MagicMock()
# 创建并填充预览后，使用 QTest.mouseClick 驱动 back_button。
export_fn.assert_not_called()
# 最终确认并等待后台完成后：
self.assertEqual(export_fn.call_count, 1)
```

- [ ] 运行 `QT_QPA_PLATFORM=offscreen ./.venv-pdf/bin/python -B -m unittest discover -s tests -p 'test_excel_category_split_ui.py' -v`，确认新测试失败。
- [ ] 实现三步表单、源列位置显示、选区输入校验和类别表。先弹“仅可见行／全部数据／取消”，刷新后才能弹最终摘要；关闭弹窗等同返回，不执行。
- [ ] 将确认文字按 PRD 10.6 完整展示，长路径和名称可查看完整内容；异常用普通中文解释并指出地址。预览过期、任务进行中禁用执行按钮。
- [ ] 原按行数页面保留，分类模式不覆盖原控件状态。仅接入相关导航，不能重构 PDF 页面。
- [ ] 重跑 UI 测试和 `QT_QPA_PLATFORM=offscreen ./.venv-pdf/bin/python -B -m unittest discover -s tests -p 'test_app_navigation.py' -v`。

## 任务 5：完整验收和审阅交付（PRD 10.7）

**Files:** 更新本计划的实际证据；测试临时文件只放专用目录，不能改业务原件。

- [ ] 核对已确认功能取舍；界面和输出不得包含已排除的追加原工作簿、字符截取、自定义命名、设置方案保存或首行格式统一功能。工程边界按开发前评审结果验证。
- [ ] 用真实鼠标完成三步、返回调整、仅可见／全部、部分类别和两种输出。界面检查覆盖中文长名称、多分类滚动和输出失败恢复。
- [ ] 性能样本分别采用 1,000／10,000／100,000 行以及 10／100／1,000 类，记录耗时和内存；只在合理资源范围执行，任何限制都依据实测提交评审，不声称无限规模。
- [ ] 执行 `QT_QPA_PLATFORM=offscreen ./.venv-pdf/bin/python -B -m unittest discover -s tests -v` 和 `git diff --check`；既有失败独立记录，不能算作本功能通过。
- [ ] 在 Mac Microsoft Excel 实际打开两种输出的验收文件、带格式和缓存值的样本，检查每个输出和计算预期；记录绝对路径、是否出现损坏／修复／恢复提示。出现提示则该结果失败，重新从原始输入处理。
- [ ] Windows 在相应环境完成相同核心测试和 Microsoft Excel 打开；无环境标未验证。安装包验收只有获得后续打包授权才执行，不能用源码测试冒充。
- [ ] 清理临时样本，保留用户同意的交付文件和现有任务记录。最终报告改动范围、源文件未变证据、恢复方式、计数、平台验证及限制。
- [ ] 由用户审阅最终差异；没有单独授权不提交 Git、不推送和发布。

## 本次文档整理核对

- 已确认规则对应 PRD 10.2—10.7，并分配到任务 1—5。
- 官方对标项的最终取舍已同步 PRD 10.8；尚需评审的工程边界与已确认产品选项分开列出。
- 任务中的测试和接口是后续实施计划，不是当前可运行实现或已通过证据。
- 本次没有创建 Excel、运行程序测试或进行客户端打开测试。

## 开发执行记录（2026-09-22）

用户已确认开始开发，覆盖上文历史的“仅文档授权”状态；仍不提交、推送、打包或发布。

- Ruling: 在现有 codex/workspace-cleanup-20260914 开发分支原位实施并备份将改文件，保持现有未提交 PDF 1.5 状态，不创建遗漏未提交成果的空基线副本。
- Ruling: 以本计划作为现有进度记录，不创建无关日志；由本会话实现和检查，不安排并行代理。
- Ruling: 首期 .xlsx；跨边界、二维数据合并阻止，复杂对象预检列出不能保留内容并阻止，不静默降级。
- Pre-flight: 任务 1 快照供任务 2 分组；任务 2 预览供任务 3 导出及任务 4 确认。实现允许增加快照绑定的选区／选项身份和最终名称，防止设置不一致与导出名称漂移。

- 任务 1—3：16 项分类引擎测试通过；跨工作簿样式索引问题由真实回读测试发现并修复，改为注册各样式组件。
- 任务 4：4 项 UI 测试通过；原导航新增模式测试完成先失败后通过。
- 首次全套 229 项：1 项既有 PDF 临时路径比较失败（/var 与 /private/var），其余通过；将使用规范化 TMPDIR 复核，未改 PDF 代码。


## 最新验收结论（2026-09-22，覆盖前述阶段记录）

- 本地实现完成，任务 1—4 的核心读取、分类、安全导出、三步页面及导航已落地；历史任务清单保留原计划粒度，不作为全部人工验收通过的标记。
- 最新分类专项：41 项通过（33 项数据／导出、8 项页面流程）；另有原导航切换回归。
- 全项目：250 项全部通过，12.269 秒。命令：`TMPDIR=/private/tmp QT_QPA_PLATFORM=offscreen PYTHON="$PWD/.venv-pdf/bin/python" bash scripts/run_macos_python.sh -B -m unittest discover -s tests -q`。此前 PDF 临时目录别名失败通过规范化 TMPDIR 消除，未修改 PDF 逻辑。`git diff --check` 通过。
- 覆盖单列／多列、类型区别、空白／隐藏互斥计数、实际筛选与仅筛选箭头、表格对象筛选、指定区域、多行表头、合并边界、缓存公式成功与错误、零值和布尔值、等号文本、非法／重名／长名称、源文件变动、选择子集、取消、不重复执行、写入失败撤回，以及 12 组固定随机种子的组合数据核对。
- 测试发现并修复跨工作簿样式索引、行列样式注册、分组列宽、主题保留、特殊工作表名和选列后源文件变动问题。导出后采用完整工作簿回读，逐行核对内容和总数。
- 性能测试（3 列普通数据，单文件多工作表）：1,000 行／10 类合计 0.11 秒；10,000 行／100 类 1.01 秒；100,000 行／1,000 类 12.23 秒。进程内存高水位依次约 46.3／83.3／501.3 MB；是该测试进程的累计峰值，不代表任意复杂表性能。临时压力样本已自动清理。
- 工程保护：处理区域最多 2,000,000 个单元格，超限要求缩小区域；这不是无限规模承诺。
- Microsoft Excel 实际打开通过：下列 3 个输出均未出现损坏、修复或恢复提示；A 类 2 条、B 类 1 条，多工作表结果共 2 表／3 条。已实际切换 B 表，核对金额 25.00、0.00、24.00、文本 001、FALSE 和等号开头文字，表头蓝色及冻结表头存在。
  - `/Users/huang/Documents/eggieflow/test_files/category_split_acceptance/category_formula_cache_分类拆分结果/category_formula_cache_A供应商.xlsx`
  - `/Users/huang/Documents/eggieflow/test_files/category_split_acceptance/category_formula_cache_分类拆分结果/category_formula_cache_B供应商.xlsx`
  - `/Users/huang/Documents/eggieflow/test_files/category_split_acceptance/category_formula_cache_分类拆分结果_1/category_formula_cache_分类结果.xlsx`
- 原生公式缓存测试源 `/Users/huang/Documents/eggieflow/tests/fixtures/category_formula_cache.xlsx` 由 Microsoft Excel 计算保存并实际打开检查；其中错误结果工作表的除零公式是故意设置的拦截用例。未拆解或重新拼装 Excel 内部结构。`.gitignore` 仅对这一回归样本增加例外。
- 页面交互已通过 QTest 自动点击测试；桌面工具连接 Python 开发版持续超时，因此完整真实桌面鼠标流程与视觉验收仍未完成，不能用自动化测试代替。Excel 原生打开已通过访达路径完成。
- Windows 和安装包未验收；未提交 Git、推送、打包或发布。源码开发完成不代表跨平台发布完成。
- 本次改动限定分类模块、页面、拆分入口、对应测试、测试样本和需求／计划文件。既有 PDF 未提交改动保留；原行数拆分算法未改。改前文件保存在 `docs/superpowers/backups/excel-category-code-20260922-105838/`，可按文件恢复本任务范围。


## 界面改版（用户确认后实施）

- 统一拆分标题和模式切换；分类页增加三步状态条、白色卡片、统一间距、蓝色主按钮和可滚动内容，底部动作保持可见。预览增加已选类别／导出记录／文件数卡片，确认弹窗按范围、结果和公式提醒分段。
- 仅修改 app.py 的拆分页面构建与 ui/excel_category_split.py；本轮未改变分类数据算法。改前文件保存于 docs/superpowers/backups/excel-category-visual-20260922/。
- 本轮 250 项回归通过，12.206 秒；三个步骤均完成 Qt 实际组件渲染检查，1180×720 最小窗口下主按钮在页面内可见。该检查与桌面鼠标人工验收不同；原生桌面工具连接 Python 仍超时，未宣称该项通过。
- 本轮未生成或修改 Excel；此前 Microsoft Excel 的三个结果打开验收仍为数据输出证据。Windows、安装包及发布仍未执行。


## 2026-10-12 Mac internal test build

- User authorized isolated Apple Silicon Mac beta build and acceptance; no commit, push or release. Existing workspace and old packages preserved. Snapshot: release/internal-test-20261012/source. Only snapshot branding/date/bundle metadata and corresponding assertions changed.
- Snapshot tests initially failed because PDF test fixtures were absent and branding assertion expected old text. Copied original fixtures and updated branding assertion; all 250 tests passed in 12.453 seconds. No functional code changes. Existing signed Qt test runner required.
- PyInstaller build passed. Initial signing had resource-fork error; clean temporary staging and ad-hoc signing passed codesign --verify --deep --strict. All project modules verified to originate from snapshot.
- ZIP: /Users/huang/Documents/eggieflow/release/internal-test-20261012/EggieDocuFlow_V1.5.0_InternalTest_20261012_mac_arm64.zip (76.4 MiB). CRC passed, 884 entries, no .env. SHA256: aad3a65e53a7ef60b5aef241c6218acd0ed8464245fa2a59f893e50b747f6b74.
- Packaged application launched natively; --version returned 1.5.0; internal test 20261012 branding visible. Actual UI: load formula fixture, select supplier column, preview 2 groups/3 rows, cancel confirmation (no files), confirm export (2 files, execution disabled).
- Readback: A has 2 rows, amounts 25 and 0; B has 1 row, amount 24. Text 001, False and equals-prefixed text preserved. Zero output formulas.
- This run's final Excel outputs have NOT been opened in Microsoft Excel; pending acceptance:
  - /Users/huang/Documents/eggieflow/release/internal-test-20261012/acceptance/category_formula_cache_分类拆分结果/category_formula_cache_A供应商.xlsx
  - /Users/huang/Documents/eggieflow/release/internal-test-20261012/acceptance/category_formula_cache_分类拆分结果/category_formula_cache_B供应商.xlsx
- Blockers: native combo action returned AXError.notImplemented/no change; Finder repeatedly reported user changed application. Multi-sheet/visible-row native flow, legacy packaged tool regression, and Excel client acceptance remain incomplete. Windows excluded. Historical/source tests do not substitute package acceptance.
- Temporary build/dist removed; source snapshot, ZIP and acceptance outputs retained. Running signed app remains in /private/tmp/eggie-beta-20261012-yf48ih4d until closed after acceptance.
- Status: beta artifact produced, partial package acceptance only; not release ready.


### 2026-10-12 UI wording review

User approved wording changes across existing functions. Updated five UI source files and the existing toolbar-label assertion; processing rules unchanged. Backup: docs/superpowers/backups/ui-wording-20261012/. Category output choices now 每类一个文件 / 每类一个工作表 with explanatory text. File-list removal distinguished from deleting PDF pages; redaction warnings retain irreversible-content warning. OCR service language and stale platform wording clarified.

Validation: full unittest suite 250 passed in 11.910s; git diff --check passed. Offscreen renders inspected for eight main tools, category settings and five PDF extra tools. Narrow-window check requested 1080x760; actual minimum width 1180, no detected QPushButton text overflow in main views. This is not native packaged acceptance or exhaustive dialog-state visual coverage. Existing internal-test ZIP does not include these wording changes; refreshed package and native/Excel acceptance remain pending.


### 2026-10-12 refreshed internal beta R2 and independent review

Independent reviewer found one P2: Unicode-equivalent category names can collide on Mac filesystems. Fixed naming comparison using NFD + casefold without changing grouping keys or original values. Added regression test: failed before fix (1 unique name versus 2), passed after fix with both actual exported rows verified. Independent re-review accepted fix; no further confirmed blockers within reviewed scope. Backups: docs/superpowers/backups/beta-r2-review-20261012/.

Root full suite: 251 passed, 11.946s. Exact build snapshot full suite: 251 passed, 13.138s. Snapshot files match current source except documented internal-test branding/version metadata. PyInstaller source audit: no project Python files imported outside snapshot. Fresh build and ad-hoc signing passed; ZIP CRC and extracted app deep/strict signature passed. Extracted binary --version: 1.5.0. No .env archive entries.

Artifact: release/internal-test-20261012-r2/EggieDocuFlow_V1.5.0_InternalTest_20261012_R2_mac_arm64.zip, 76.8 MiB. SHA256 d2324bddfc66f747d50420f0af756e4da6613f78610e56723e6d7f8cd90cd4d3. Old package untouched. Native launch from final ZIP extraction passed; version label, legacy split tab, new category wording, fixture loading and category selection page inspected. UI tool shows only a tilted window thumbnail and AX row clicks do not focus/check the row, preventing reliable export execution. Asked user to bring R2 window fully to foreground. Native split export and Excel client acceptance remain pending; no new R2 Excel outputs produced. Windows build/test and notarization not performed.


### R2 native acceptance continuation (2026-10-12)

After user brought R2 to foreground, native category split completed against tests/fixtures/category_formula_cache.xlsx, sheet 公式明细, supplier column A, all rows, one file per category. Preview: 2 classes/3 rows. Cancelled final confirmation and verified acceptance folder remained empty, then confirmed and obtained 2 files/3 rows; duplicate execution button disabled.

Microsoft Excel actually opened both final R2 files:
- /Users/huang/Documents/eggieflow/release/internal-test-20261012-r2/acceptance/category_formula_cache_分类拆分结果/category_formula_cache_A供应商.xlsx
- /Users/huang/Documents/eggieflow/release/internal-test-20261012-r2/acceptance/category_formula_cache_分类拆分结果/category_formula_cache_B供应商.xlsx

No file-specific damage, repair or content recovery prompts. Excel startup displayed a previous-session recovery banner; inspecting it opened an unrelated historical workbook, not these outputs. No edits/saves made to historical workbook. Returned to exact output paths and confirmed clean workbook views A1:E3 and A1:E2. Excel formula bar D2 showed literal 25 (A) and 24 (B); A E2 showed 001. Full openpyxl readback confirmed all 3 original records, A zero and False values, B literal =原始文字, no formula cells. Initial wildcard readback also encountered Excel's ~$ lock file; corrected readback excluded locks and passed for both actual results.

Native files-output acceptance passed. Native sheets-output retest could not be completed: after switching to Excel, R2 screenshot again became a stage-manager thumbnail and combo AX click/keyboard could not reliably select sheets. Did not execute an uncertain selection. Sheets-output remains covered by passing automated tests, not native packaged acceptance. ZIP unchanged.
