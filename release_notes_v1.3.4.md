# v1.3.4 - Eggie DocuFlow

本版本统一软件整体界面风格，补强 Excel 和发票处理的操作提示，并修复打包版首页 logo 不显示的问题。

## 更新内容

- 首页和所有工具页统一为同一套浅色工作台风格。
- 首页改为左侧导航、常用工具卡片和右侧信息面板，减少入口拥挤和信息重叠。
- 统一按钮、输入框、表格、卡片边框和页面底色。
- Excel 合并增加合并前预览，显示行数、列数和合并单元格数量。
- Excel 拆分增加预计生成文件数量提示。
- PDF 发票解析新增发票台账汇总，并生成汇总日志。
- 修复打包后的软件首页左上角 logo 空白问题。
- 修正 Excel 预览列数统计，避免把仅设置宽度但没有数据的空列算进去。
- 发票台账改为先安全生成再保存，减少异常中断时留下半成品文件的风险。
- 保存整套页面截图，方便后续继续做 UI 调整和规划。

## 影响范围

- 影响首页和所有工具页的界面显示。
- 影响 Excel 合并预览信息、Excel 拆分前提示和 PDF 发票解析后的台账输出。
- 影响 macOS 打包资源。
- 不改变文档处理、批量改名和 PDF 工具箱的原有处理逻辑。

## 版本信息

- Version: 1.3.4
- Build Type: release
- Build Date: 2026-07-09

## 界面截图

![首页新版 UI](https://github.com/huangchong-4806/Eggie-DocuFlow/raw/main/docs/ui/home_runtime_check_20260709.png)

![全部页面总览](https://github.com/huangchong-4806/Eggie-DocuFlow/raw/main/docs/ui/all_pages_runtime_check_20260709.png)
