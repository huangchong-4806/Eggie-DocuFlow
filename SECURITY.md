# 下载校验与安全事项

## V1.5.2 下载与更新

V1.5.2 的版本编号为 2026110601。V1.5.1 或更早版本需先完整安装一次，才能获得软件内更新能力。软件内更新先验证发行公钥对应的 Ed25519 签名，再核对下载文件的大小与 SHA-256；校验不通过时停止安装。

Mac 使用本机临时代码签名，未做 Apple 公证；Windows 未使用付费平台发行证书。更新文件的独立签名用于确认更新来源与内容，不能代替平台发行证书或保证软件没有缺陷。

## V1.5.1 历史组件说明

旧构建 2026110401 包含已发布上游安全公告所涉及的 PDF 和图片解析库。该旧构建已由 2026110402 替换，V1.5.2 沿用修复后的组件。以下是与本软件相关的例子；不是对每条公告在 Eggie 中可被利用的判定。

| 随包组件 | 已确认的上游风险 |
| --- | --- |
| pypdf 6.10.0 | 特制 PDF 的交叉引用流或对象流可使读取耗时异常。[上游公告](https://github.com/py-pdf/pypdf/security/advisories/GHSA-jj6c-8h6c-hppx) |
| Pillow 12.2.0 | 上游报告了分块 TIFF 图像的解码越界读取。[上游公告](https://github.com/python-pillow/Pillow/security/advisories/GHSA-462x-pgg6-55fp) |
| pdfminer.six 20251107（由 pdfplumber 使用） | 如果本地字体映射文件可被不受信任的用户替换，加载映射时可能执行代码。请用普通账户运行，尤其是在多人共用电脑时。[上游公告](https://github.com/pdfminer/pdfminer.six/security/advisories/GHSA-f83h-ghpp-7wcc) |

构建 2026110402 使用 pypdf 6.21.4、Pillow 13.0.0、pdfplumber 0.11.10 及 pdfminer.six 20260107，并更新了相关网络依赖。SHA-256 校验可以确认下载文件与发布文件一致，不能排除软件本身的安全问题。

## 核对下载

从[正式发布页](https://github.com/huangchong-4806/Eggie-DocuFlow/releases/tag/v1.5.2)下载对应系统的安装包和 `SHA256SUMS.txt`。在下载目录运行以下命令，对照清单中**同一文件名**所在行的 64 位十六进制值。Windows 显示的大写字母和清单里的小写字母等价。

macOS：

```sh
shasum -a 256 EggieDocuFlow_V1.5.2_mac_arm64.zip
```

Windows PowerShell：

```powershell
Get-FileHash .\EggieDocuFlow_V1.5.2_Windows_x64_Setup.exe -Algorithm SHA256
```

## 私下报告问题

请使用 [GitHub 私密漏洞报告入口](https://github.com/huangchong-4806/Eggie-DocuFlow/security/advisories/new)。提供版本、系统和使用模拟数据的最小复现步骤即可。请勿附上 OCR 密钥、`.env`、客户文档、真实订单或含这些信息的日志和截图。已经公开的密钥应先到服务商处撤销，再处理仓库中的副本。
