# V1.5.1 构建入口

本版构建号2026110401。本版基于已验收的 V1.5.1 构建 2026110302，并修复了缺少中文系统字体时旧水印接口的文字提取。不能用默认PyPI PyMuPDF wheel代替实际组合：PyMuPDF1.28.2 / MuPDF1.28.5。

## 输入与环境

同一GitHub v1.5.1发布页提供项目源码、第三方源码材料及SHA256SUMS.txt。项目源码对应 v1.5.1 标签。第三方引擎与依赖沿用 1.5.0，配套第三方源码归档按原样提供，其中的归档记录保留 1.5.0 版本标记；本次版本、构建入口以项目源码为准。第三方材料包含MuPDF1.28.5完整源码（含thirdparty），其SHA256为98a5c10cda20c3992cdf76ff6b2a1149c32bd79cc796d3f703230b1185b7e934。

- Mac：Python3.12.13，Apple Silicon；实际构建主机 macOS 27.2，成品最低系统声明macOS15。
- Windows：Python3.12.10 x64、Visual Studio2022 C++、Inno Setup6；本次应用及安装器在 GitHub Actions 的 Windows Server 2022 x64 环境构建并安装验证。定制 PDF 引擎来自已经核验的 Windows x64 wheel。
- `packaging/rebuild/requirements-*-portable.txt`为两端构建版本清单，排除PyMuPDF以防覆盖定制引擎；不是含所有平台wheel的离线包。
- 使用已重建的定制 wheel 打包时，请核对 PyMuPDF 和 MuPDF 的实际版本。Windows 的 libclang、pipcl 和 SWIG 仅在从源码重建引擎时使用。
- 项目级打包脚本会写入构建输出目录，仅在新的源码副本执行，勿指向已有交付文件。

## 重建顺序

1. 在新目录解压源码和第三方材料，创建相应Python虚拟环境，按对应portable清单安装依赖，并运行`python -m pip check`。
2. Windows需要两处构建修正：pipcl按Python目标平台判断x64；MuPDF七条预构建命令复用本次虚拟环境。使用`packaging/rebuild/prepare_windows_engine.py --help`查看参数；默认只检查，`--apply`才修改新副本并备份原件。不要直接使用历史补丁中的绝对路径。
3. 设置`PYMUPDF_SETUP_MUPDF_BUILD`为MuPDF源码绝对路径。Windows另设置`PYMUPDF_SETUP_DEVENV`为devenv.com路径和`PYMUPDF_SETUP_MUPDF_VS_UPGRADE=1`。
4. 执行`python -m pip wheel --no-build-isolation --no-deps --no-index <PyMuPDF源码目录> -w <新wheel目录>`，再安装生成的wheel。先导入PySide6.QtCore，再核对pymupdf.VersionBind为1.28.2、VersionFitz为1.28.5。
5. 运行项目测试，再用PyInstaller及`packaging/EggieDocuFlow.spec`或`packaging/EggieDocuFlow_windows.spec`打包，明确给定新的distpath/workpath。Mac使用本机临时签名，未做Apple开发者签名和公证。
   对齐 V1.5.1 的 Windows 原生运行库时，先用上一版 [V1.5.0 校验清单](https://github.com/huangchong-4806/Eggie-DocuFlow/releases/download/v1.5.0/SHA256SUMS.txt) 验证安装器，在隔离环境安装至参考目录。运行下方命令对比两套应用中的全部 DLL 和 PYD。缺少文件、同名内容不同或出现清单外的新增库时应停止。正式构建仅排除了 Windows Server 构建机额外收集的 45 个库，保留的 89 个均与参考安装器字节一致。

   ```powershell
   python packaging/rebuild/check_windows_runtime.py --reference $ReferenceApp --candidate $BuiltApp
   # 确认参考目录和本次构建目录后，仅在可重建的 PyInstaller 输出副本执行
   python packaging/rebuild/check_windows_runtime.py --reference $ReferenceApp --candidate $BuiltApp --apply
   ```

6. Windows安装器用`packaging/EggieDocuFlow_windows.iss`生成，四个变量必须完整：EGGIE_APP_VERSION=1.5.1、EGGIE_APP_SOURCE_DIR、EGGIE_APP_OUTPUT_DIR、EGGIE_CHINESE_LANGUAGE_FILE。后三项分别指向本次应用目录、新安装包目录和packaging/ChineseSimplified.isl。
7. 核对冻结代码、依赖版本、随包许可证及成品启动。重新编译的哈希可能因工具链、时间和签名而不同，版本号相同不代表同一成品。

## 范围说明

Mac实验MuPDF wheel文件名的macOS11标记与实际二进制最低macOS15不一致，该实验wheel不单独发布。Qt测试插件须取自相应环境，不复用原构建机临时路径。

第三方材料按实际成品、官方归档及固定配方核对；PDFium历史检出和cryptography原始OpenSSL构建任务仍缺部分直接记录。未声称完成所有库的逐字节重建、完整离线重建或跨电脑重建。其他电脑和最低系统实测已移出本轮范围，状态仍为未实测。

V1.5.1 的仓库测试与安装器验证分开执行。常规 CI 使用开发依赖；正式包另行核对定制引擎、实际安装结果及 [五项公开下载](https://github.com/huangchong-4806/Eggie-DocuFlow/actions/runs/41757197056)。对应源码请取 v1.5.1 标签或该发布页的项目源码包。当前主分支包含发布后的文档和维护工具。
