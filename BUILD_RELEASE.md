# V1.5.0 构建入口

本版构建号2026101601。业务代码沿用已验收RC2；版本标识、说明及PDFium随包声明更新。不能用默认PyPI PyMuPDF wheel代替实际组合：PyMuPDF1.28.2 / MuPDF1.28.5。

## 输入与环境

同一GitHub v1.5.0发布页提供项目源码、第三方源码材料及SHA256SUMS.txt。项目源码对应v1.5.0标签；第三方材料包含MuPDF1.28.5完整源码（含thirdparty），其SHA256为98a5c10cda20c3992cdf76ff6b2a1149c32bd79cc796d3f703230b1185b7e934。

- Mac：Python3.12.13，Apple Silicon；实际构建主机macOS27.0.1，成品最低系统声明macOS15。
- Windows：Python3.12.10 x64、Visual Studio2022 C++、Inno Setup6；实际为Windows11 ARM虚拟机运行x64。
- `packaging/rebuild/requirements-*-portable.txt`为两端构建版本清单，排除PyMuPDF以防覆盖定制引擎；不是含所有平台wheel的离线包。
- 项目级打包脚本会写入构建输出目录，仅在新的源码副本执行，勿指向已有交付文件。

## 重建顺序

1. 在新目录解压源码和第三方材料，创建相应Python虚拟环境，按对应portable清单安装依赖，并运行`python -m pip check`。
2. Windows需要两处构建修正：pipcl按Python目标平台判断x64；MuPDF七条预构建命令复用本次虚拟环境。使用`packaging/rebuild/prepare_windows_engine.py --help`查看参数；默认只检查，`--apply`才修改新副本并备份原件。不要直接使用历史补丁中的绝对路径。
3. 设置`PYMUPDF_SETUP_MUPDF_BUILD`为MuPDF源码绝对路径。Windows另设置`PYMUPDF_SETUP_DEVENV`为devenv.com路径和`PYMUPDF_SETUP_MUPDF_VS_UPGRADE=1`。
4. 执行`python -m pip wheel --no-build-isolation --no-deps --no-index <PyMuPDF源码目录> -w <新wheel目录>`，再安装生成的wheel。先导入PySide6.QtCore，再核对pymupdf.VersionBind为1.28.2、VersionFitz为1.28.5。
5. 运行项目测试，再用PyInstaller及`packaging/EggieDocuFlow.spec`或`packaging/EggieDocuFlow_windows.spec`打包，明确给定新的distpath/workpath。Mac使用本机临时签名，未做Apple开发者签名和公证。
6. Windows安装器用`packaging/EggieDocuFlow_windows.iss`生成，四个变量必须完整：EGGIE_APP_VERSION=1.5.0、EGGIE_APP_SOURCE_DIR、EGGIE_APP_OUTPUT_DIR、EGGIE_CHINESE_LANGUAGE_FILE。后三项分别指向本次应用目录、新安装包目录和packaging/ChineseSimplified.isl。
7. 核对冻结代码、依赖版本、随包许可证及成品启动。重新编译的哈希可能因工具链、时间和签名而不同，版本号相同不代表同一成品。

## 范围说明

Mac实验MuPDF wheel文件名的macOS11标记与实际二进制最低macOS15不一致，该实验wheel不单独发布。Qt测试插件须取自相应环境，不复用原构建机临时路径。

第三方材料按实际成品、官方归档及固定配方核对；PDFium历史检出和cryptography原始OpenSSL构建任务仍缺部分直接记录。未声称完成所有库的逐字节重建、完整离线重建或跨电脑重建。其他电脑和最低系统实测已移出本轮范围，状态仍为未实测。
