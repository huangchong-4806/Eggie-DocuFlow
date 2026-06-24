# Eggie Excel Tool / Excel 合并拆分工具

![Version](https://img.shields.io/badge/version-1.2.0-blue)
![Platform](https://img.shields.io/badge/macOS-Apple%20Silicon-black)
![Python](https://img.shields.io/badge/Python-3.9%2B-green)

Eggie Excel Tool 是一个面向日常办公场景的 Excel 与 PDF 工具。当前版本支持
Excel 合并、Excel 拆分和文本型 PDF 发票结构化解析。

当前版本重点解决以下问题：

- 多个 Excel 文件批量合并
- 按文件列表顺序合并
- 尽量保留原始单元格格式、列宽、合并单元格和公式
- 按自定义数据行数拆分 Excel 文件
- 拆分文件自动保留指定表头
- 拆分结果自动集中保存到独立文件夹
- PDF 发票转换为财务结构化 Excel，并自动校验金额与税额
- 支持较大文件的低内存处理
- 提供简单易用的 macOS 图形界面

Eggie Excel Tool is a desktop utility for everyday office workflows. It supports
Excel merging, Excel splitting, and structured parsing of text-based PDF invoices.

The current release focuses on:

- Batch merging multiple Excel files
- Merging files in the order shown in the file list
- Preserving cell styles, column widths, merged cells, and formulas whenever possible
- Splitting Excel files by a custom number of data rows
- Keeping the configured header rows in every split file
- Saving split output files into an automatically created folder
- Converting PDF invoices into finance-ready Excel files with amount and tax validation
- Low-memory processing for larger workbooks
- A simple and user-friendly macOS graphical interface

## 普通用户如何下载 / Download

如果你只是想直接使用软件，不需要安装 Python，也不需要运行源码。

1. 打开本项目右侧的 **Releases**
2. 下载最新版安装包
3. 解压后运行 `EggieExcelTool_V1.2.0_mac.app`
4. 本版本未做 Apple 公证；如果 macOS 阻止打开，请在 Finder 中右键 App，选择“打开”，再确认“打开”

If you only want to use the application, you do not need to install Python or
run the source code.

1. Open **Releases** on the right side of this repository
2. Download the latest application package
3. Extract the package and launch `EggieExcelTool_V1.2.0_mac.app`
4. This release is not Apple-notarized. If macOS blocks it, right-click the App in Finder, choose **Open**, then confirm **Open**

> 当前正式版主要支持 Apple 芯片 macOS，Windows 版本后续再考虑。
> The current release primarily supports Apple Silicon macOS. A Windows version may be considered in the future.

## 软件界面 / Screenshot

![Eggie Excel Tool](docs/screenshot.jpg)

## 主要功能 / Features

### Excel 合并 / Excel Merge

- 添加单个文件或递归添加整个文件夹 / Add individual files or recursively add an entire folder
- 通过“上移 / 下移”按钮调整合并顺序 / Reorder files with the **Move Up / Move Down** buttons
- 后续文件可跳过 `0-99` 行表头 / Skip `0-99` header rows in subsequent files
- 自动保留字体、填充、边框、对齐、数字格式和保护设置 / Preserve fonts, fills, borders, alignment, number formats, and protection settings
- 自动调整复制后的公式引用 / Adjust copied formula references automatically
- 可选择是否保留合并单元格 / Choose whether to preserve merged cells
- 保存窗口跟随 macOS 系统语言 / Use the macOS system language in the save dialog
- 普通工作簿使用低内存流式合并，复杂合并单元格自动切换兼容模式 / Use low-memory streaming for standard workbooks and compatibility mode for complex merged cells

### Excel 拆分 / Excel Split

- 新增 Excel 拆分工具 / Added a new Excel split tool
- 支持选择 Excel 文件进行拆分 / Users can select an Excel file to split
- 支持设置表头行数 / Users can configure the number of header rows
- 支持设置每个文件的数据行数 / Users can split an Excel file by a custom number of data rows
- 拆分行数不包含表头 / The split row count does not include header rows
- 每个拆分文件都会自动带上表头 / Each output file keeps the configured header rows
- 自动创建“原文件名_拆分结果”文件夹 / Output files are saved into an automatically created folder
- 拆分文件命名规则为“原文件名_拆分001.xlsx” / Split files are named like `原文件名_拆分001.xlsx`
- 优化了大文件拆分速度 / Large-file splitting performance has been improved
- 原始 Excel 文件只读取，不会被修改 / The original Excel file is read-only and will not be modified

### PDF发票解析工具 / PDF Invoice Parser

- 支持 100 页以内、可复制文字的 PDF 发票 / Supports text-based PDF invoices up to 100 pages
- 统一输出发票头信息、明细表和校验结果 / Outputs header, item, and validation sheets
- 校验数量与单价、金额与税额、价税合计 / Validates quantities, prices, amounts, taxes, and totals
- 不输出 PDF 原始逐行文本 / Never exports raw line-by-line PDF text

## 使用方法 / Usage

1. 打开 `EggieExcelTool_V1.2.0_mac.app`。 / Open `EggieExcelTool_V1.2.0_mac.app`.
2. 选择需要使用的工具。 / Choose the tool you need.

合并 Excel：

1. 添加 Excel 文件或包含 Excel 文件的文件夹。 / Add Excel files or a folder containing Excel files.
2. 使用“上移 / 下移”确认文件顺序。 / Confirm the merge order with **Move Up / Move Down**.
3. 设置后续文件跳过的行数。 / Set the number of rows to skip in subsequent files.
4. 选择输出文件位置并点击“开始合并”。 / Choose an output location and click **Start Merge**.

拆分 Excel：

1. 选择一个 `.xlsx` Excel 文件。 / Select one `.xlsx` Excel file.
2. 设置表头行数。 / Configure the number of header rows.
3. 设置每个文件的数据行数。 / Configure the number of data rows per output file.
4. 选择输出位置并点击“开始拆分”。 / Choose an output location and click **Start Split**.
5. 程序会自动创建“原文件名_拆分结果”文件夹并保存全部拆分文件。 / The app automatically creates an output folder and saves all split files there.

解析 PDF 发票：

1. 选择单张文本型 PDF 发票。 / Select one text-based PDF invoice.
2. 确认 Excel 保存位置并点击“开始识别并生成 Excel”。 / Confirm the output location and start parsing.
3. 在“校验结果”中复核异常项。 / Review exceptions in the validation sheet.

## 使用说明与注意事项 / Notes

- 建议合并前关闭正在打开的 Excel 文件。 / Close any open Excel files before merging.
- 建议合并前先备份原始文件。 / Back up the original files before merging.
- 当前优先支持 `.xlsx` 和 `.xlsm` 文件。 / `.xlsx` and `.xlsm` files are currently the primary supported formats.
- Excel 拆分工具当前仅支持 `.xlsx` 文件。 / The Excel split tool currently supports `.xlsx` files only.
- PDF 发票解析工具仅支持文本型、单票 PDF，扫描件请先转为可复制文字的 PDF。 / The PDF invoice parser supports one text-based invoice per PDF; scanned PDFs are not supported.
- 拆分工具只读取原始 Excel 文件，不会修改原文件。 / The split tool only reads the original Excel file and will not modify it.
- 加密、损坏、受保护的 Excel 文件可能无法正常合并。 / Encrypted, corrupted, or protected workbooks may not merge correctly.
- 合并大文件时请耐心等待。 / Large workbooks may require additional processing time.
- 如果合并结果异常，请先检查源文件格式是否一致。 / If the result looks incorrect, first check whether the source files use consistent structures and formats.
- 本版本未做 Apple 公证；首次打开被拦截时，请右键 App 并选择“打开”。 / This release is not Apple-notarized. If first launch is blocked, right-click the App and choose **Open**.

## 本地运行 / Run from Source

开发者可以使用以下命令从源码运行。普通用户无需执行这些步骤。

Developers can run the project from source with the commands below. Regular
users do not need to follow these steps.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

## 测试 / Tests

```bash
python -m unittest discover -s tests -v
```

性能基准 / Performance benchmark:

```bash
python scripts/benchmark.py /path/to/excel-folder
```

## macOS 构建 / Build for macOS

当前正式构建仅支持 Apple 芯片 Mac。

The current release build supports Apple Silicon Macs only.

```bash
PYTHON=.venv/bin/python scripts/build_macos.sh
```

构建结果位于 `release/`，正式版文件名为：

- `EggieExcelTool_V1.2.0_mac.app`
- `EggieExcelTool_V1.2.0_mac.zip`

打包脚本保留所有 `qtbase` 系统语言翻译，并移除本工具不使用的 Qt 网络、TLS、
SVG 和图片插件。

Build artifacts are written to `release/`. The packaging script keeps all
`qtbase` system-language translations and removes unused Qt network, TLS, SVG,
and image plugins.

## 版本记录 / Changelog

### V1.2.0

- 新增 PDF发票解析工具 / Added the PDF invoice parser
- 输出发票头信息、明细表和校验结果 / Added structured header, item, and validation sheets
- 新增金额、税额与价税合计校验 / Added amount, tax, and total validation
- 修复免税行、跨行字段和长项目名称的解析 / Fixed tax-exempt rows, wrapped fields, and long item names
- 防止未确认覆盖已有 Excel 文件 / Prevented unconfirmed overwrites of existing Excel files
- 扫描件和多票 PDF 会明确提示，不生成错账文件 / Scanned and multi-invoice PDFs are rejected safely

### V1.1.1

- 精简界面代码并改用系统原生控件 / Simplified the UI and adopted native system controls.
- 防止输出路径别名覆盖源 Excel 文件 / Prevented output path aliases from overwriting source workbooks.
- 合并结果采用安全的临时文件写入 / Added atomic saves to preserve existing output when a merge fails.
- 拆分前检测跨边界合并单元格，避免静默丢失内容 / Detect merged cells across split boundaries to prevent silent data loss.
- 拆分失败时自动清理本次残缺结果 / Remove incomplete split output created by a failed run.
- 新增相关自动化测试 / Added regression tests for the new safeguards.

### V1.1.0

- 新增 Excel 拆分工具 / Added Excel split tool.
- 支持自定义表头行数 / Added support for custom header row count.
- 支持自定义每个文件的数据行数 / Added support for custom data rows per output file.
- 每个拆分文件自动保留表头 / Each split file keeps the configured header rows.
- 自动创建拆分结果文件夹 / Added automatic output subfolder creation.
- 优化拆分文件命名规则 / Improved split file naming.
- 优化大文件拆分速度 / Improved large Excel file split performance.
- 原始 Excel 文件只读取、不修改 / Original Excel file is read-only and will not be modified.

### V1.0.1

- 优化大文件合并速度并显著降低内存占用 / Improved large-file merge speed and significantly reduced memory usage
- 使用轻量 XLSX 元数据扫描加快文件信息读取 / Added lightweight XLSX metadata scanning for faster file inspection
- 自动选择流式模式或合并单元格兼容模式 / Automatically selects streaming or merged-cell compatibility mode
- 缓存重复单元格样式 / Caches repeated cell styles
- 精简 macOS 应用体积 / Reduced the macOS application size

### V1.0.0

- 首个正式版本 / Initial public release
- 支持文件、文件夹、排序、保存路径和格式保留 / Added file and folder selection, ordering, output paths, and formatting preservation

更多项目历史见 [docs/PROJECT_HISTORY.md](docs/PROJECT_HISTORY.md)。

See [docs/PROJECT_HISTORY.md](docs/PROJECT_HISTORY.md) for additional project history.

## 许可证

本项目采用 MIT License 开源协议。

你可以自由使用、复制、修改和分发本项目，但请保留原始版权和作者信息。

请勿将本项目重新包装后冒充原创，或用于误导性传播。

## License

This project is licensed under the MIT License.

You are free to use, copy, modify, and distribute this project, but please retain the original copyright and author information.

Please do not repackage this project as your own original work or use it for misleading distribution.
