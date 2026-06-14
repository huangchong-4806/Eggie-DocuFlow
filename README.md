# Excel Merge Tool / Excel 合并工具

![Version](https://img.shields.io/badge/version-1.0.1-blue)
![Platform](https://img.shields.io/badge/macOS-Apple%20Silicon-black)
![Python](https://img.shields.io/badge/Python-3.9%2B-green)

Excel Merge Tool 是一个面向日常办公场景的 Excel 批量合并工具，适合需要按文件顺序
汇总多份 Excel 表格、并尽量保留原始格式的用户。

当前版本重点解决以下问题：

- 多个 Excel 文件批量合并
- 按文件列表顺序合并
- 尽量保留原始单元格格式、列宽、合并单元格和公式
- 支持较大文件的低内存处理
- 提供简单易用的 macOS 图形界面

Excel Merge Tool is a desktop utility for everyday office workflows. It is
designed for users who need to combine multiple Excel workbooks in a specific
file order while preserving the original formatting whenever possible.

The current release focuses on:

- Batch merging multiple Excel files
- Merging files in the order shown in the file list
- Preserving cell styles, column widths, merged cells, and formulas whenever possible
- Low-memory processing for larger workbooks
- A simple and user-friendly macOS graphical interface

## 普通用户如何下载 / Download

如果你只是想直接使用软件，不需要安装 Python，也不需要运行源码。

1. 打开本项目右侧的 **Releases**
2. 下载最新版安装包
3. 解压后运行 Excel 合并工具
4. 如果 macOS 提示无法打开，请在“系统设置 - 隐私与安全性”中允许运行

If you only want to use the application, you do not need to install Python or
run the source code.

1. Open **Releases** on the right side of this repository
2. Download the latest application package
3. Extract the package and launch Excel Merge Tool
4. If macOS blocks the application, allow it in **System Settings - Privacy & Security**

> 当前正式版主要支持 Apple 芯片 macOS，Windows 版本后续再考虑。
> The current release primarily supports Apple Silicon macOS. A Windows version may be considered in the future.

## 软件界面 / Screenshot

![Excel Merge Tool](docs/screenshot.jpg)

## 主要功能 / Features

- 添加单个文件或递归添加整个文件夹 / Add individual files or recursively add an entire folder
- 通过“上移 / 下移”按钮调整合并顺序 / Reorder files with the **Move Up / Move Down** buttons
- 后续文件可跳过 `0-99` 行表头 / Skip `0-99` header rows in subsequent files
- 自动保留字体、填充、边框、对齐、数字格式和保护设置 / Preserve fonts, fills, borders, alignment, number formats, and protection settings
- 自动调整复制后的公式引用 / Adjust copied formula references automatically
- 可选择是否保留合并单元格 / Choose whether to preserve merged cells
- 保存窗口跟随 macOS 系统语言 / Use the macOS system language in the save dialog
- 普通工作簿使用低内存流式合并，复杂合并单元格自动切换兼容模式 / Use low-memory streaming for standard workbooks and compatibility mode for complex merged cells

## 使用方法 / Usage

1. 打开 `Excel合并工具V1.0.1.app`。 / Open `Excel合并工具V1.0.1.app`.
2. 添加 Excel 文件或包含 Excel 文件的文件夹。 / Add Excel files or a folder containing Excel files.
3. 使用“上移 / 下移”确认文件顺序。 / Confirm the merge order with **Move Up / Move Down**.
4. 设置后续文件跳过的行数。 / Set the number of rows to skip in subsequent files.
5. 选择输出文件位置并点击“开始合并”。 / Choose an output location and click **Start Merge**.

## 使用说明与注意事项 / Notes

- 建议合并前关闭正在打开的 Excel 文件。 / Close any open Excel files before merging.
- 建议合并前先备份原始文件。 / Back up the original files before merging.
- 当前优先支持 `.xlsx` 和 `.xlsm` 文件。 / `.xlsx` and `.xlsm` files are currently the primary supported formats.
- 加密、损坏、受保护的 Excel 文件可能无法正常合并。 / Encrypted, corrupted, or protected workbooks may not merge correctly.
- 合并大文件时请耐心等待。 / Large workbooks may require additional processing time.
- 如果合并结果异常，请先检查源文件格式是否一致。 / If the result looks incorrect, first check whether the source files use consistent structures and formats.

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

构建结果位于 `release/`。打包脚本保留所有 `qtbase` 系统语言翻译，并移除
本工具不使用的 Qt 网络、TLS、SVG 和图片插件。

Build artifacts are written to `release/`. The packaging script keeps all
`qtbase` system-language translations and removes unused Qt network, TLS, SVG,
and image plugins.

## 版本记录 / Changelog

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
