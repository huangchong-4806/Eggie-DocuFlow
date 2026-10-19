# Eggie DocuFlow V1.5.0

## 下载安装 / Download and install

- [Mac：Apple 芯片，macOS 15 及以上 / Apple silicon, macOS 15 or later](https://github.com/huangchong-4806/Eggie-DocuFlow/releases/download/v1.5.0/EggieDocuFlow_V1.5.0_mac_arm64.zip)
- [Windows：Windows 10/11，64 位 / Windows 10/11, 64-bit](https://github.com/huangchong-4806/Eggie-DocuFlow/releases/download/v1.5.0/EggieDocuFlow_V1.5.0_Windows_x64_Setup.exe)

无需安装 Python。Mac 下载后解压，将 `Eggie DocuFlow.app` 放入“应用程序”；Windows 运行安装包，按向导完成安装。<br>
No Python installation is required. On Mac, extract the ZIP and move `Eggie DocuFlow.app` to Applications. On Windows, run the installer and follow the setup wizard.

普通用户只需下载对应的安装包；项目源码、第三方源码材料和校验清单供开发者及文件核对使用。<br>
Regular users only need the installer for their platform. Project source, third-party source materials and checksums are provided for developers and file verification.

## 本次更新 / What's new

- **Excel 按类别拆分 / Split Excel by category**：按一列或多列分类，选择“每类一个文件”或“每类一个工作表”；后者保存在同一个新 Excel 文件中。原有按固定行数拆分继续保留。<br>
  Group rows by one or more columns, then save each group as a separate file or as a separate worksheet in one new workbook. Fixed-row splitting remains available.
- **拆分前预览 / Preview before splitting**：先查看类别、记录数和结果名称；遇到筛选或隐藏行时，可选择处理全部数据或仅可见行。分类拆分将公式转为源文件已保存的计算结果。<br>
  Review groups, row counts and output names first. Choose all rows or visible rows when filters or hidden rows are detected. Category splitting uses saved formula values.
- **PDF 页面编辑 / PDF page editing**：支持插入、删除、拖动排序、旋转和提取页面，并可撤销、重做。<br>
  Insert, delete, reorder, rotate and extract pages, with undo and redo.
- **PDF 内容处理 / PDF content tools**：支持区域或文字涂黑、文字与图片水印，以及页码样式、位置和页范围设置。<br>
  Redact selected areas or text, add text or image watermarks, and customize page-number style, position and page ranges.
- **界面与使用体验 / Interface and usability**：更新首页和工具页布局，简化操作文字；修复图片预览、转换按钮、保存位置，以及 Excel 长编号和引用处理等问题。<br>
  Updated home and tool layouts, clearer labels, and fixes for image previews, conversion buttons, save locations, long Excel identifiers and cell references.

## 使用说明 / Usage notes

- 分类拆分支持 `.xlsx`，保留指定表头并生成新文件。含公式的源文件请先在 Excel 中计算并保存；分类拆分使用已保存的计算结果。<br>
  Category splitting supports `.xlsx`, retains the selected header rows and creates new files. Recalculate and save workbooks containing formulas in Excel first; splitting uses their saved values.
- PDF 涂黑会从导出副本中移除选中的内容，导出后不能恢复这些内容，请保留原文件。无法可靠处理的结构会提示并停止导出。<br>
  PDF redaction removes selected content from the exported copy and cannot be reversed in that copy. Keep the original file. Unsupported structures are reported and export is stopped.
- PDF 独立工具需要单独选择文件；要继续处理编辑结果，请先另存副本，再选择该副本。<br>
  Independent PDF tools require their own input file. To process an edited document, save a copy first and select that copy.
- Excel 和 PDF 默认在本机处理。云 OCR 仅在主动配置、启用并确认后上传扫描页，可能产生服务商费用。<br>
  Excel and PDF processing runs locally by default. Cloud OCR sends scanned pages only after configuration, opt-in and confirmation; provider fees may apply.

## 历史版本与源码 / Previous release and source

[V1.4.0 下载 / V1.4.0 downloads](https://github.com/huangchong-4806/Eggie-DocuFlow/releases/tag/v1.4.0)继续保留。项目许可与第三方声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。<br>
V1.4.0 downloads remain available. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for project licensing and third-party notices.
