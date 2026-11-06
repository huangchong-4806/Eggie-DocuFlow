# V1.5.2 正式版构建入口

本版编号 2026110601，正式标识为 `BUILD_TYPE = "release"`。沿用 V1.5.1（2026110402）已核验的 PDF、图片和网络依赖，并纳入软件内更新及 Qt Cocoa 修复。不能用默认PyPI PyMuPDF wheel代替实际组合：PyMuPDF1.28.2 / MuPDF1.28.5。

## 输入与环境

本版项目源码使用 `EggieDocuFlow_V1.5.2_project-source.zip`；待正式发布后对应 v1.5.2 标签。未变化的第三方源码材料仍可从 [V1.5.1 发布页](https://github.com/huangchong-4806/Eggie-DocuFlow/releases/tag/v1.5.1) 取得。本版新增的 Qt 修复源码材料另附 `QtCocoa_6.10.3_Eggie0503_source.zip`，发行公钥和 SHA256SUMS.txt 随本版交付。定制 MuPDF 引擎及未升级的库使用归档中的原始材料。新增或升级的依赖见本次第三方源码包的清单。第三方材料包含MuPDF1.28.5完整源码（含thirdparty），其SHA256为98a5c10cda20c3992cdf76ff6b2a1149c32bd79cc796d3f703230b1185b7e934。

- Mac：Python3.12.13，Apple Silicon；实际构建主机 macOS 27.2，成品最低系统声明macOS15。
- Windows：Python3.12.10 x64、Visual Studio2022 C++、Inno Setup6；V1.5.1 基线在 GitHub Actions 的 Windows Server 2022 x64 环境构建并安装验证；V1.5.2 沿用已核验组件，在 Windows 11 ARM64 虚拟机中使用 x64 Python 构建和验收。定制 PDF 引擎来自已经核验的 Windows x64 wheel。
- `packaging/rebuild/requirements-*-portable.txt`为两端构建版本清单，排除PyMuPDF以防覆盖定制引擎；不是含所有平台wheel的离线包。
- 使用已重建的定制 wheel 打包时，请核对 PyMuPDF 和 MuPDF 的实际版本。Windows 的 libclang、pipcl 和 SWIG 仅在从源码重建引擎时使用。
- 项目级打包脚本会写入构建输出目录，仅在新的源码副本执行，勿指向已有交付文件。

## 重建顺序

1. 在新目录解压源码和第三方材料，创建相应Python虚拟环境，按对应portable清单安装依赖，并运行`python -m pip check`。
2. Windows需要两处构建修正：pipcl按Python目标平台判断x64；MuPDF七条预构建命令复用本次虚拟环境。使用`packaging/rebuild/prepare_windows_engine.py --help`查看参数；默认只检查，`--apply`才修改新副本并备份原件。不要直接使用历史补丁中的绝对路径。
3. 设置`PYMUPDF_SETUP_MUPDF_BUILD`为MuPDF源码绝对路径。Windows另设置`PYMUPDF_SETUP_DEVENV`为devenv.com路径和`PYMUPDF_SETUP_MUPDF_VS_UPGRADE=1`。
4. 执行`python -m pip wheel --no-build-isolation --no-deps --no-index <PyMuPDF源码目录> -w <新wheel目录>`，再安装生成的wheel。先导入PySide6.QtCore，再核对pymupdf.VersionBind为1.28.2、VersionFitz为1.28.5。
5. 运行项目测试，再用PyInstaller及`packaging/EggieDocuFlow.spec`或`packaging/EggieDocuFlow_windows.spec`打包，明确给定新的distpath/workpath。Mac使用本机临时签名，未做Apple开发者签名和公证。
   Windows 使用本构建的依赖清单。更新安装时，安装器按文件名和旧构建哈希清理已退出发行的私有运行文件。清单随项目源码提供。旧构建的全量 DLL 相等检查仅用于复现 2026110401。

6. Windows安装器用`packaging/EggieDocuFlow_windows.iss`生成，四个变量必须完整：EGGIE_APP_VERSION=1.5.2、EGGIE_APP_SOURCE_DIR、EGGIE_APP_OUTPUT_DIR、EGGIE_CHINESE_LANGUAGE_FILE。后三项分别指向本次应用目录、新安装包目录和packaging/ChineseSimplified.isl。
7. 核对冻结代码、依赖版本、随包许可证及成品启动。重新编译的哈希可能因工具链、时间和签名而不同，版本号相同不代表同一成品。

## 范围说明

Mac实验MuPDF wheel文件名的macOS11标记与实际二进制最低macOS15不一致，该实验wheel不单独发布。Qt测试插件须取自相应环境，不复用原构建机临时路径。

第三方材料按实际成品、官方归档及固定配方核对；PDFium历史检出和cryptography原始OpenSSL构建任务仍缺部分直接记录。未声称完成所有库的逐字节重建、完整离线重建或跨电脑重建。其他电脑和最低系统实测已移出本轮范围，状态仍为未实测。

仓库测试与成品检查分开。两端主程序可运行 `--check-install` 执行内置组件的离线读写检查，成功退出码为 0。正式下载须核对同一发布页的 SHA256SUMS.txt。

## 软件内更新的签名清单

Mac arm64 与 Windows x64 的完整包和增量包可以放在同一个 GitHub 正式发布里。签名清单名固定为 `EggieUpdate-v1.json`。同一版本重新打包仍须分配新的十位编号。增量包只用于指定平台和指定旧版本、旧编号。

1. 为发行渠道保管一对 Ed25519 密钥。私钥由受控密钥服务或系统钥匙串保管。只将 **32 字节原始公钥** 编成一行 Base64，保存为 `eggie-update-ed25519.pub`。两端构建时设置 `EGGIE_UPDATE_PUBLIC_KEY_FILE` 指向这个公钥文件，再运行相应的 PyInstaller 打包流程。新正式包、候选包必须提供公钥，漏配就会在两端打包时停止。仅普通开发构建、复现历史 V1.5.1 的 2026110401／2026110402 可以省略。测试跨版本更新时，作为起点的旧包也须包含同一公钥。运行客户端时设置环境变量不会替换公钥。没有内置公钥的旧安装只能引导到官方下载页。
2. 先生成并验收各平台的完整包，以及从指定旧包生成的增量包。Windows 两种载荷都是现有安装路径适用的 EXE；Mac 完整包使用 ZIP，增量包使用 Sparkle 的 `.delta`。将最终成品集中到发布暂存目录。存档与安装包内只包含公钥。
3. 准备仅供签名工具使用的输入 JSON。下面的编号仅作示例。起始包须已具备软件内更新功能，文件名需换为实际成品。

```json
{
  "target": {"version": "1.6.0", "build": "2026110501"},
  "assets": [
    {"platform": "windows-x64", "kind": "full", "base": null, "filename": "Eggie-1.6.0-Win-Setup.exe"},
    {"platform": "windows-x64", "kind": "delta", "base": {"version": "1.5.2", "build": "2026110491"}, "filename": "Eggie-0491-to-0501-Win.exe"},
    {"platform": "macos-arm64", "kind": "full", "base": null, "filename": "Eggie-1.6.0-Mac.zip"},
    {"platform": "macos-arm64", "kind": "delta", "base": {"version": "1.5.2", "build": "2026110491"}, "filename": "Eggie-0491-to-0501-Mac.delta"}
  ]
}
```

4. 在项目根目录运行 `python scripts/sign_update_release.py --spec <输入JSON> --assets <成品目录> --public-key <内置公钥文件>`。用受控密钥工具通过标准输入直接提供 Base64 编码的 32 字节 Ed25519 私钥种子，勿将私钥写入命令行、仓库、日志或普通文件。签名工具核对公钥，读取每件成品的真实大小与 SHA-256，并校验签名和清单结构，最后在成品目录生成清单。如果同名清单存在会停止。
5. 双端验收并获准发布后，将已签名清单和清单中所有成品放到同一 GitHub 正式发布的附件里。客户端按系统及已安装版本选择有签名的最小适用包。若增量基线不匹配，则展示同平台完整包及真实大小。签名或文件校验失败时停止，不能继续安装。

### 含应用内更新的 Mac 测试及后续发布

构建机需要 macOS 的 Xcode 命令行工具。打包时通过 `EGGIE_UPDATE_PUBLIC_KEY_FILE` 指定发行公钥，Mac 打包脚本会在构建临时目录编译更新助手，并从固定版本 Sparkle 归档中取出 BinaryDelta 和许可证。离线构建可通过 `EGGIE_SPARKLE_ARCHIVE` 指定 Sparkle 2.10.1 原始官方 tar.xz 路径，在线和离线两种方式均核对内置 SHA-256。

保留用户实际安装的已签名 A 版和准备分发的已签名 B 版。在项目根目录执行 `python scripts/build_mac_delta.py "/绝对路径/A.app" "/绝对路径/B.app" "/新路径/A-to-B.delta"`，脚本会把补丁实际应用到新的临时副本并核对版本、签名和目标代码摘要。完整 ZIP 使用 `ditto -c -k --norsrc --keepParent "B.app" "新的完整包.zip"`。同一份已签名发布清单须同时包含目标版本的完整包和对应起始版本的增量包。

验收时从独立测试位置启动 A 版，确认“检查更新”显示增量大小，下载后选择“重启并更新”，再核对原位置 B 版、主窗口、新旧设置与实际处理功能。Mac 更新只在可写、支持原子交换的原安装目录执行，签名或版本不符时不切换。无法安全套用增量时由用户选择完整包；新进程未确认主窗口已就绪时，更新助手切回旧应用。

若在原位切换时断电或更新助手被强制结束，原安装位置旁的“Eggie 更新恢复-… .noindex”文件夹内保有应用副本和恢复入口。退出相关 Eggie，打开“双击恢复旧版.command”可由旧版助手核对签名后换回安装位置。如果原路径已被改动则保留两个副本。该恢复无需管理员权限或登录服务。

### Windows 增量打包及中断恢复

1. 保留两份干净的 Windows x64 应用运行目录（旧 A、新 B）。带更新公钥构建的正式安装包包含 `eggie-runtime.json`。该文件列出程序文件的 SHA-256；如果是尚未打标的隔离打包目录，运行 `python scripts/build_windows_update.py stamp --root "<运行目录>" --version "<版本>" --build "<十位编号>"`。不要在用户正在使用的安装目录制作补丁。
2. 运行 `python scripts/build_windows_update.py delta --old "<A>" --new "<B>" --output "<尚不存在的工程目录>" --iscc "<Inno Setup 6 的 ISCC.exe>"`。命令核对两套成品、生成差异工程并编译 EXE。将生成的 EXE 和 B 的完整安装器都列入签名清单。未经端到端验收的测试包不要作为正式附件。
3. Windows 客户端须使用正常用户启动、受保护的 Program Files 安装目录和匹配的系统安装记录。单独双击原始增量 EXE 无法跳过旧版核对及更新助手备份。更新使用系统权限确认，完成后以原用户身份打开办公界面。
4. 转换过程中断电或助手被终止时，保留程序目录同级的 `.eggie-update-…` 恢复目录。若已有 `installing` 标志且自动恢复没有完成，先退出 Eggie，双击该目录中的 `EggieUpdateRestore.exe`，通过 Windows 正常管理员权限确认。核对它显示的原安装位置和旧版本后，输入 `RESTORE` 才会还原。独立恢复程序在打包时使用 Windows 自带 .NET Framework 编译器制作，不依赖 Python、Qt 或 PowerShell 脚本执行策略。保留恢复目录直至核对旧应用可以使用。
5. 排查失败时，先核对同一事务目录的 `stage`、`result`、`failure.json` 及 `installer.log`；恢复本身失败时另有 `restore-failure.json`。`not-started` 表示原安装未改动，`restored` 表示已恢复旧安装，`failed` 表示需保留备份处理。不要仅凭更新助手退出成功或安装器返回零判断整个更新已完成，还须取得新界面的启动回执和程序文件一致性结果。

### 本机钥匙串签名方式

当前候选版使用 `scripts/update_keychain.swift` 构建的本机签名助手。私钥保存在 macOS 登录钥匙串，服务名 `com.huang.eggiedocuflow.update-signing`，账号 `ed25519-release-v1`。助手的 `init <公钥路径>` 仅在没有密钥时创建，已有密钥会复用；`public` 只返回公钥，`sign` 从标准输入读取待签名内容，仅返回签名。

`python scripts/sign_update_release.py --spec <输入JSON> --assets <成品目录> --public-key <内置公钥文件> --keychain-helper "<本机签名助手绝对路径>"`

此方式不向 Python 导出私钥；Python 会再次独立核对签名。助手不随安装包分发。正式发布前须妥善保留钥匙串及安全备份；本轮没有导出或生成私钥备份。候选清单只用于本地核验，不代表相关地址已上线。

## V1.5.2 Mac Cocoa 辅助功能修复

Mac 打包前按 `packaging/macos/qt-cocoa/README.md` 提供已核验的 Qt 6.10.3 源码和 SDK，在独立目录执行 `scripts/build_mac_cocoa.py`；用 `EGGIE_QT_COCOA_REPAIR_DIR` 指向生成的组件目录。打包入口会检查 Qt 版本、上游修复编号、输入摘要、配方及库摘要；缺失或不匹配则停止，不生成仍包含原崩溃组件的应用。

PyInstaller 收集原有 Qt 库后，仅替换 Cocoa 平台插件，再改写依赖路径并签名；开发虚拟环境不变。成品须实际加载应用内的 Qt 库，不引用临时 SDK。组件的 SHA-256 在改写路径、去符号和签名前后会不同，分别记录输入组件和最终成品摘要。随包包含补丁、CMake 配方及来源说明；完整 Qt Base 源码归档作为对应源码材料另行保留。只有代码测试、原生窗口检查和成品核验全部完成，才能将该候选包标为验收通过。
