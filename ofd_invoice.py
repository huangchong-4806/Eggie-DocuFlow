"""Read text objects in supported digital VAT invoices directly from their OFD package."""
from bisect import bisect_right
from collections import defaultdict
from math import isfinite
import posixpath
import re
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from pdf_invoice_tool import InvoiceData, InvoiceItem, ValidationRecord, _to_decimal, validate_invoice


class _XmlTree(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise ValueError("OFD 包含不支持的 XML 声明。")


class _Document:
    def __init__(self, archive):
        self.archive = archive
        members = archive.infolist()
        if len(members) > 10000 or len({e.filename for e in members}) != len(members):
            raise ValueError("OFD 内部文件数量异常或名称重复。")
        self.remaining = 64 * 1024 * 1024

    def read(self, parent, location):
        path = posixpath.normpath(posixpath.join(posixpath.dirname(parent), location)).lstrip("/")
        if not location or path == ".." or path.startswith("../"):
            raise ValueError("OFD 内部页面路径无效。")
        member = self.archive.getinfo(path)
        if member.file_size > min(self.remaining, 16 * 1024 * 1024):
            raise ValueError("OFD 页面或文档过大，无法安全读取。")
        self.remaining -= member.file_size
        return path, ET.fromstring(self.archive.read(member), parser=ET.XMLParser(target=_XmlTree()))


_FIELDS = {"InvoiceNo": "发票号码", "IssueDate": "开票日期", "BuyerName": "购买方名称",
           "SellerName": "销售方名称", "BuyerTaxID": "购买方税号", "SellerTaxID": "销售方税号",
           "TaxExclusiveTotalAmount": "合计金额（不含税）", "TaxTotalAmount": "合计税额",
           "TaxInclusiveTotalAmount": "价税合计（小写）", "Note": "备注"}
_MONEY = ("合计金额（不含税）", "合计税额", "价税合计（小写）")
_COLUMNS = ("项目名称", "规格型号", "单位", "数量", "单价", "金额", "税率", "税额")


def _elements(node, name):
    return node.findall(".//{*}" + name)


def _printed(text):
    return re.sub(r"\s+", "", text).replace("：", ":")


def _page_objects(page):
    entries = {}
    for node in _elements(page, "TextObject"):
        x, y, width, height = map(float, node.get("Boundary", "").split())
        if not all(isfinite(n) for n in (x, y, width, height)):
            raise ValueError("OFD 文字区域无效。")
        text = "".join(c.text or "" for c in _elements(node, "TextCode"))
        key = node.get("ID")
        if not key or key in entries:
            raise ValueError("OFD 页面文字编号重复。")
        entries[key] = (x, y, width, text)
    return entries


def _page_rows(objects, items, page_no, issues):
    cells = sorted((r for r in objects.values() if r[3].strip()), key=lambda r: (r[1], r[0]))
    groups = []
    for cell in cells:
        if not groups or abs(cell[1] - groups[-1][0][1]) > 0.5:
            groups.append([])
        groups[-1].append(cell)
    header = next((line for line in groups if any(_printed(r[3]) == "项目名称" for r in line)), [])
    titles = sorted(header)
    if len(titles) != 8 or any(not _printed(r[3]).startswith(k) for r,k in zip(titles, _COLUMNS)):
        raise ValueError(f"第 {page_no} 页的明细栏目无法确认。")
    borders = [(a[0]+a[2]+b[0])/2 for a,b in zip(titles,titles[1:])]
    start = len(items)
    subtotal = None
    ended = False
    for line in groups[groups.index(header)+1:]:
        line = sorted(line)
        label = _printed(line[0][3])
        if label in ("小计", "合计"):
            ended = True
            if label == "小计":
                subtotal = [_to_decimal(c[3]) for c in line[1:]]
            break
        values = defaultdict(list)
        for x,y,w,s in line:
            # Long wrapped names and models are left-aligned. Numeric columns are right-aligned.
            column = bisect_right(borders, x if x < borders[1] else x + w/2)
            values[column].append(s)
        if set(values) <= {0,1}:
            if not items:
                raise ValueError(f"第 {page_no} 页有无法归属的明细续行。")
            items[-1].project_name += "".join(values[0])
            items[-1].specification += "".join(values[1])
            continue
        row = ["".join(values[i]).strip() for i in range(8)]
        numbers = [_to_decimal(v) for v in row[3:]]
        rate = row[6]
        items.append(InvoiceItem(row[0], row[1], row[2], *numbers, tax_rate_text=rate if rate in ("免税","不征税") else ""))
        if not row[0] or not rate or any(raw and num is None and raw not in ("***","免税","不征税") for raw,num in zip(row[3:],numbers)):
            issues.append((str(len(items)), "明细字段", f"第 {page_no} 页有无法确认的项目或数值，请对照原票。"))
    if not ended:
        raise ValueError(f"第 {page_no} 页未找到明细结束位置。")
    if subtotal is not None:
        for i,k in enumerate(("amount","tax_amount")):
            amounts = [getattr(r,k) for r in items[start:]]
            if len(subtotal)!=2 or subtotal[i] is None or None in amounts or sum(amounts) != subtotal[i]:
                issues.append(("", "分页小计", f"第 {page_no} 页的{'金额' if i==0 else '税额'}小计需核对。"))
    # Only the printed rectangle between the totals and signatory can contain remarks.
    big = next((line for line in groups if any("价税合计" in _printed(r[3]) for r in line)), [])
    signer = next((line for line in groups if any(_printed(r[3]).startswith("开票人") for r in line)), [])
    note = ""
    upper = ""
    if big:
        big = sorted(big)
        upper = next((r[3] for r in big[1:] if "小写" not in r[3]), "")
        if signer and signer[0][1] > big[0][1]:
            note = "".join(r[3] for r in cells if big[0][1]+0.5 < r[1] < signer[0][1]-0.5 and _printed(r[3]) not in ("备","注","备注"))
        else:
            issues.append(("", "备注", f"第 {page_no} 页未能确定备注区域。"))
    return upper,note


def _invoice(package, progress):
    rootpath,root = package.read("", "OFD.xml")
    roots = _elements(root, "DocRoot")
    if len(roots) != 1:
        raise ValueError("请选择仅含一张数电发票的 OFD。")
    docpath,doc = package.read(rootpath, roots[0].text or "")
    tags = doc.findtext("{*}CustomTags")
    if not tags:
        raise ValueError("此 OFD 缺少数电发票字段标记，当前无法识别。")
    indexpath,index = package.read(docpath,tags)
    nodes = _elements(doc,"Page")
    invoice = InvoiceData()
    entries = {}
    issues = []
    notes = []
    supported = {"电子发票（普通发票）","电子发票（增值税专用发票）"}
    for n, node in enumerate(nodes,1):
        _,page = package.read(docpath,node.get("BaseLoc",""))
        objects = _page_objects(page)
        if n==1 and not any(_printed(r[3]).replace("(", "（").replace(")", "）") in supported for r in objects.values()):
            raise ValueError("当前支持 20 位号码的数电普通发票和增值税专用发票。")
        if node.get("ID") in entries:
            raise ValueError("OFD 页码引用重复。")
        entries[node.get("ID")] = objects
        upper,note = _page_rows(objects,invoice.items,n,issues)
        if upper:
            invoice.header["价税合计（大写）"] = upper
        if note:
            notes.append(note)
        if progress:
            progress(n,len(nodes),f"第 {n} 页")
    fields = defaultdict(list)
    for loc in _elements(index,"FileLoc"):
        _,tree = package.read(indexpath,loc.text or "")
        for tag in tree.iter():
            key = _FIELDS.get(tag.tag.rsplit("}",1)[-1])
            if key is None:
                continue
            value = "".join(entries[r.get("PageRef")][(r.text or "").strip()][3] for r in tag.findall("{*}ObjectRef"))
            if value and value not in fields[key]:
                fields[key].append(value)
    h = invoice.header
    for key in _FIELDS.values():
        values = fields[key]
        if key == "备注":
            continue
        if key in _MONEY:
            h[key] = None
        if len(values) != 1:
            if key=="发票号码":
                raise ValueError("OFD 发票号码缺失或多页号码不一致。")
            issues.append(("",key,"字段缺失或页面之间的值不一致，请核对原票。"))
        elif key in _MONEY:
            h[key] = _to_decimal(values[0])
        else:
            h[key] = values[0]
    if not re.fullmatch(r"[0-9]{20}", h["发票号码"]) or not invoice.items:
        raise ValueError("未找到 20 位数电发票号码或可读取的明细。")
    h["备注"] = "\n".join(notes)
    if fields["备注"] and _printed("".join(fields["备注"])) != _printed(h["备注"]):
        issues.append(("", "备注", "备注标记与票面区域不一致，请核对。"))
    validate_invoice(invoice)
    invoice.validations.extend(ValidationRecord(h["发票号码"],row,field,True,field,note=msg) for row,field,msg in issues)
    return invoice


def extract_ofd_invoice(path, progress=None):
    try:
        with ZipFile(path) as archive:
            return _invoice(_Document(archive),progress)
    except (BadZipFile, KeyError, ET.ParseError, RuntimeError) as exc:
        raise ValueError("OFD 文件损坏、受保护或缺少可读取的页面内容。") from exc
