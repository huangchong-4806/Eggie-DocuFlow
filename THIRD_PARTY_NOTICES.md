# 开源说明与第三方组件

Eggie DocuFlow / Eggie文档处理系统。本文适用于 V1.5.0（构建号2026101601），不追溯替换旧版的许可证声明。

## 项目代码及完整许可文本

原有代码的 MIT 授权及 `Copyright (c) 2026 qq448223855-rgb` 署名完整保留在 [LICENSE](LICENSE)。PDF 工作区集成及包含 PyMuPDF / MuPDF 的组合应用按 GNU AGPLv3 分发；第三方组件继续遵守各自许可证，不因本项目开源而免除其要求。

- [GNU AGPLv3 全文](licenses/AGPL-3.0.txt)，来源：[GNU 官方](https://www.gnu.org/licenses/agpl-3.0.txt)
- [GNU GPLv3 全文](licenses/GPL-3.0.txt)，来源：[GNU 官方](https://www.gnu.org/licenses/gpl-3.0.txt)
- [GNU LGPLv3 全文](licenses/LGPL-3.0.txt)，来源：[GNU 官方](https://www.gnu.org/licenses/lgpl-3.0.txt)

软件不提供适销性或特定用途适用性的保证。脱敏无法验证的结构会拒绝输出，不能将这种保护当成对任意 PDF 的安全保证。

## 主要运行组件

以下版本与已验收RC2的成品和构建环境核对；本版沿用相同依赖，平台差异分别列出。

| 组件 | 核对版本 | 许可及来源 |
| --- | --- | --- |
| PyMuPDF / MuPDF | 1.28.2 / 1.28.5 | AGPLv3；Copyright Artifex Software, Inc.；[项目及源代码](https://github.com/pymupdf/PyMuPDF)、[MuPDF 源代码](https://github.com/ArtifexSoftware/mupdf)。采用开源路线，不使用商业授权或 PyMuPDF Pro 功能。 |
| PySide6 Essentials / Shiboken6 / Qt | 6.10.3 | 包元数据列为 LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only；本应用保留动态库及 LGPLv3 权利，未修改这些库；[Qt for Python 源代码](https://code.qt.io/cgit/pyside/pyside-setup.git/)、[Qt 源代码](https://code.qt.io/cgit/qt/)。 |
| pypdf | 6.10.0 | BSD-3-Clause；[源代码](https://github.com/py-pdf/pypdf)。 |
| pypdfium2 / PDFium | 5.10.1 / 151.0.7891.0 | BSD-3-Clause、Apache-2.0 及 PDFium 构建依赖的独立声明；[源代码](https://github.com/pypdfium2-team/pypdfium2)。随包保留 BUILD_LICENSES 与 LICENSES；准确配套的完整官方文本位于 licenses/pdfium/mac/ 和 licenses/pdfium/windows/，各16份，补正包装器内较旧的libpng、zlib、lcms和ICU声明。 |
| Pillow | 12.2.0 | MIT-CMU，包含其编解码依赖的许可证；[源代码](https://github.com/python-pillow/Pillow)。 |
| openpyxl | 3.1.5 | MIT；[源代码](https://foss.heptapod.net/openpyxl/openpyxl)。 |
| pdfplumber / pdfminer.six | 0.11.8 / 20251107 | MIT；[pdfplumber](https://github.com/jsvine/pdfplumber)、[pdfminer.six](https://github.com/pdfminer/pdfminer.six)。 |
| cryptography | Mac 50.0.1 / Windows 50.0.2，所用OpenSSL分别4.0.2/4.0.3 | Apache-2.0 OR BSD-3-Clause，另含所用加密库的声明；[源代码](https://github.com/pyca/cryptography)。 |
| Alibaba Cloud OCR SDK | 3.1.3 | Apache-2.0 及其传递依赖许可；[源代码](https://github.com/aliyun/alibabacloud-python-sdk)。仅原有用户主动配置的云 OCR 流程使用；新 PDF 工作区不联网、不自动 OCR。 |

本表不是第三方许可全文的替代品。打包配置会收集上述运行依赖及其递归依赖的发行元数据、包内许可证文件，随程序保留原作者和第三方声明。PyMuPDF 内置字体及 MuPDF 使用的第三方库仍适用上游各自声明；对应源码应包含原始第三方目录，不能仅提供本项目的 Python 文件。

## 源代码与分发要求

项目源代码仓库：[huangchong-4806/Eggie-DocuFlow](https://github.com/huangchong-4806/Eggie-DocuFlow)。本版源码对应v1.5.0标签；同一发布页提供准确的项目源码、第三方源码材料及SHA256清单。旧V1.4.0源码不是本版的对应源码。

同一发布位置提供本版项目源码、依赖源码材料、构建与安装脚本、本文件和许可证。重建入口见 BUILD_RELEASE.md 及 packaging/rebuild/；实际MuPDF1.28.5源码与其thirdparty目录完整保留。requirements.txt用于开发，准确重建须按说明准备定制引擎。

保留用户依据 LGPLv3 修改、替换和调试 Qt / PySide6 库的权利，包括为调试其修改而进行反向工程的权利；不得通过附加条款或打包技术限制这些权利。若未来将修改后的 AGPL 程序提供为网络交互服务，还需要履行 AGPL 第 13 条的源码提供要求。

This software is based in part on the work of the FreeType Team.

材料限制：PDFium官方历史任务日志已过期，历史源码检出未取得直接证明；cryptography所用OpenSSL的源码版本、哈希和参数有实际物料清单依据，但原始构建任务身份未直接定位。来源、许可证、源码和固定配方随材料保留；未声称完成独立离线或跨电脑重建。

## V1.5.0 PDF engine build

PyMuPDF 1.28.2 is built against MuPDF 1.28.5. Both are under AGPL-3.0; this non-default combination is not generally supported by upstream. Runtime verification and original-source/build-patch references are included in this release source and dependency materials. macOS minimum remains 15.
