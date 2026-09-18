"""把用户上传的表格文件读成「一格一格」的文本，供 AI 助手分析。

### 为什么这个活在后端干（而不是在手机上）
这是本项目里少见的一次"前后端分工反转"，理由只有一条：**真实的 Excel 比看上去脏**。
同一个 .xlsx 里可能有：公式（只有缓存值）、日期（存的是 45000 这个序列号，靠样式才认得出）、
合并单元格、多个工作表、数字被存成文本、中文 CSV 的 GBK 编码……
这些坑在服务端有现成的 `openpyxl`（requirements 里本来就有，导出报表一直在用），
在手机端要么自己写一个 xlsx 解析器（几百行、还不能测），要么引一个几 MB 的库。
手机端只负责"选文件、上传、把结果摆给用户看"。

### 两条硬约束
1. **不落盘**：这个接口是"读一遍就还给你"，文件不写进 `uploads/`、不进数据库。
   用户的商品表/账单表里有什么，只有他和模型知道（后端不留副本，也就没有清理和泄漏的问题）。
2. **一定要截断并如实说明**：任何"读进来"的东西都必须有上限（这里是每表 200 行 / 40 列 / 8MB），
   而且**截断这件事必须告诉用户**——一张 500 行的表只读了前 200 行却不说的话，
   用户会以为模型看到了全部，然后拿它算出来的结论去做决定。
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

#: 单文件字节上限。8MB 足够放几万行的表格；再大就不该走"让 AI 读一遍"这条路了。
MAX_BYTES = 8 * 1024 * 1024

#: 最多读几个工作表（一个工作簿常常有十几个 sheet，全读进来只会把上下文塞满）。
MAX_SHEETS = 5

#: 每张表最多几行/几列。
DEFAULT_MAX_ROWS = 200
MAX_MAX_ROWS = 1000
MAX_COLS = 40

#: 单个格子的字符上限（防止一个格子里塞了一篇文章）。
MAX_CELL_CHARS = 200

#: 认得出扩展名（小写，含点）。xls 故意不在里面：它是老的二进制格式，
#: openpyxl 读不了，而"读一半然后给出乱七八糟的表"比直接拒绝坏得多。
XLSX_EXT = {".xlsx", ".xlsm"}
TEXT_EXT = {".csv", ".tsv", ".txt", ".md"}
LEGACY_XLS_EXT = {".xls"}


class SheetParseError(Exception):
    """读不出来（格式不支持 / 文件损坏 / 超限）→ 调用方转成 400，并把人话带给用户。"""


@dataclass
class Table:
    """一张读出来的表。"""

    name: str
    rows: list[list[str]]
    #: 截断**前**的真实行数（用户要知道"这表到底多大"）
    row_count: int
    col_count: int
    truncated: bool


@dataclass
class ParsedSheet:
    kind: str
    tables: list[Table]
    warnings: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ 入口

def parse_upload(filename: str, data: bytes, max_rows: int = DEFAULT_MAX_ROWS) -> ParsedSheet:
    """按扩展名分派。读不出来一律抛 [SheetParseError]（message 直接给用户看）。"""
    if not data:
        raise SheetParseError("这个文件是空的。")
    if len(data) > MAX_BYTES:
        raise SheetParseError(
            f"文件有 {len(data) / 1024 / 1024:.1f}MB，超过 {MAX_BYTES // 1024 // 1024}MB 的上限。"
            "请先删掉用不到的列/行，或者拆成几个文件分次传。"
        )
    name = (filename or "").strip() or "未命名文件"
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    rows_cap = max(1, min(int(max_rows), MAX_MAX_ROWS))

    if ext in XLSX_EXT:
        return _parse_xlsx(data, rows_cap)
    if ext in LEGACY_XLS_EXT:
        raise SheetParseError(
            "这是旧版 Excel（.xls）的格式，服务器读不了。"
            "请在 Excel/WPS 里「另存为」成 .xlsx 或 .csv，再传一次。"
        )
    if ext in TEXT_EXT:
        return _parse_text(data, name, ext, rows_cap)
    raise SheetParseError(
        f"读不了「{ext or '无扩展名'}」这种文件。现在支持：Excel（.xlsx/.xlsm）"
        "和文本表格（.csv/.tsv/.txt）。"
    )


# ------------------------------------------------------------------ xlsx

def _parse_xlsx(data: bytes, rows_cap: int) -> ParsedSheet:
    try:
        from openpyxl import load_workbook
    except ImportError as e:  # pragma: no cover - 依赖缺失时给出人话
        raise SheetParseError("服务器缺少 Excel 解析组件（openpyxl），请联系管理员。") from e

    try:
        # read_only=True 是流式读，几万行的表也不会把内存吃光；
        # data_only=True 读的是公式的**缓存结果**（没有缓存时 openpyxl 给 None，
        # 那种情况由下面的"空表"分支兜住并说清楚）。
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:
        raise SheetParseError(
            "这个 .xlsx 打不开（文件可能损坏，或者是被改了扩展名的 .xls/.csv）。"
            "请用 Excel 打开确认能正常显示后另存为 .xlsx 再传。"
        ) from e

    warnings: list[str] = []
    tables: list[Table] = []
    try:
        names = list(wb.sheetnames)
        for sheet_name in names[:MAX_SHEETS]:
            ws = wb[sheet_name]
            rows, total, cols, truncated = _read_xlsx_sheet(ws, rows_cap)
            if not rows:
                # 空表不进结果（但要说一声，否则用户会以为"我明明有一个 sheet 没读到"）
                warnings.append(f"工作表「{sheet_name}」是空的，跳过了。")
                continue
            tables.append(
                Table(
                    name=str(sheet_name),
                    rows=rows,
                    row_count=total,
                    col_count=cols,
                    truncated=truncated,
                )
            )
        if len(names) > MAX_SHEETS:
            warnings.append(
                f"这个工作簿有 {len(names)} 个工作表，只读了前 {MAX_SHEETS} 个"
                f"（{ '、'.join(names[:MAX_SHEETS]) }）。要读别的表请把它们挪到前面，或单独另存一个文件。"
            )
    finally:
        try:
            wb.close()
        except Exception:  # pragma: no cover - 关闭失败不该影响已经读到的内容
            pass

    if not tables:
        raise SheetParseError(
            "这个 Excel 里没有读到任何内容。"
            "如果表格是用公式算出来的，请先在 Excel 里「复制 → 选择性粘贴为数值」再传。"
        )
    return ParsedSheet(kind="xlsx", tables=tables, warnings=warnings)


def _read_xlsx_sheet(ws: Any, rows_cap: int) -> tuple[list[list[str]], int, int, bool]:
    """读一张工作表：返回（行、真实行数、列数、是否截断）。"""
    out: list[list[str]] = []
    total = 0
    cols = 0
    truncated = False
    for raw_row in ws.iter_rows(values_only=True):
        cells = [_cell_text(v) for v in (raw_row or ())]
        # 整行都是空的 → 不算一行（Excel 的"到过那里"会留下无数空行）
        if not any(c for c in cells):
            continue
        total += 1
        if len(out) < rows_cap:
            out.append(cells)
        else:
            truncated = True
        cols = max(cols, len(cells))
    out = _trim(out, cols)
    # 列数按**裁完之后**的实际宽度算：Excel 里到过的空列（D 列以后什么都没写）不算列，
    # 否则用户会看到"5 列"而表里只有 3 列有内容，模型也会以为后面两列是空的。
    cols_out = len(out[0]) if out else 0
    return out, total, cols_out, truncated


def _cell_text(v: Any) -> str:
    """一个格子 → 一行文本。**空值一律成空串**（不要 None/NaN 混进提示词）。"""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, datetime):
        # Excel 里的"日期"常常带一个 00:00:00 的时间，那是格式带来的噪音
        if v.time() == time(0, 0):
            return v.date().isoformat()
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float):
        if v != v:  # NaN
            return ""
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        # 去掉浮点尾巴（3.7999999999999998 → 3.8）
        return f"{v:.10f}".rstrip("0").rstrip(".")
    if isinstance(v, Decimal):
        return _cell_text(float(v))
    s = str(v).replace("\u00a0", " ").strip()
    if len(s) > MAX_CELL_CHARS:
        s = s[:MAX_CELL_CHARS] + "…（这一格太长，已截断）"
    return s


def _trim(rows: list[list[str]], cols: int) -> list[list[str]]:
    """裁掉右侧全空的列，并把每行补齐到同样宽度（模型看表格时列数一致才不会串列）。"""
    if not rows:
        return rows
    keep = 0
    for i in range(cols):
        if any((r[i] if i < len(r) else "") for r in rows):
            keep = i + 1
    keep = min(keep, MAX_COLS)
    out: list[list[str]] = []
    for r in rows:
        row = list(r[:keep])
        if len(row) < keep:
            row += [""] * (keep - len(row))
        out.append(row)
    return out


# ------------------------------------------------------------------ csv / txt

def _parse_text(data: bytes, name: str, ext: str, rows_cap: int) -> ParsedSheet:
    text, warn = _decode(data)
    warnings = [warn] if warn else []
    if not text.strip():
        raise SheetParseError("这个文件里没有可读的文字。")

    delim = "\t" if ext == ".tsv" else _sniff_delim(text)
    rows_all: list[list[str]] = []
    try:
        for rec in csv.reader(io.StringIO(text), delimiter=delim):
            # 整行空 → 跳过（文本文件末尾常有空行）
            if not any((c or "").strip() for c in rec):
                continue
            rows_all.append([_clean_cell(c) for c in rec])
    except csv.Error as e:
        raise SheetParseError(f"这个文件按表格读的时候出错了：{e}。请确认它是规整的 CSV/文本表格。") from e

    if not rows_all:
        raise SheetParseError("这个文件里没有读到任何一行内容。")

    total = len(rows_all)
    truncated = total > rows_cap
    rows = rows_all[:rows_cap]
    cols = max((len(r) for r in rows), default=0)
    rows = _trim(rows, cols)
    if truncated:
        warnings.append(f"这个文件有 {total} 行，只读了前 {rows_cap} 行。")

    table = Table(
        name=name.rsplit(".", 1)[0] or name,
        rows=rows,
        row_count=total,
        col_count=min(cols, MAX_COLS),
        truncated=truncated,
    )
    return ParsedSheet(kind=("tsv" if ext == ".tsv" else "text"), tables=[table], warnings=warnings)


def _clean_cell(c: str) -> str:
    s = (c or "").replace("\u00a0", " ").strip()
    if len(s) > MAX_CELL_CHARS:
        s = s[:MAX_CELL_CHARS] + "…（这一格太长，已截断）"
    return s


def _decode(data: bytes) -> tuple[str, str | None]:
    """解码：UTF-8 优先，失败退中文 GB 系（Excel 导出的 CSV 默认就是 GBK）。

    为什么必须退：Windows 上的 Excel「另存为 CSV」写出来的是 GBK，
    直接按 UTF-8 读会得到一整片「锟斤拷」——而模型看到乱码后仍然会一本正经地分析它。
    """
    for enc, warn in (
        ("utf-8-sig", None),
        ("gb18030", "这个文件不是 UTF-8 编码，已按中文 GBK/GB18030 读取。"),
    ):
        try:
            return data.decode(enc), warn
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "这个文件的编码认不出来，个别字符可能显示成乱码。"


def _sniff_delim(text: str) -> str:
    """猜分隔符：**要求每一行都有、且个数基本一致**，否则当成"一行一格"的纯文本。"""
    lines = [ln for ln in text.splitlines() if ln.strip()][:10]
    if not lines:
        return ","
    best, best_count = ",", 0
    for d in (",", "\t", ";", "|"):
        counts = [ln.count(d) for ln in lines]
        if min(counts) <= 0:
            continue
        # 前 10 行里至少 8 行的分隔符个数一样 → 认它是表格
        if counts.count(counts[0]) >= max(1, len(counts) - 2) and counts[0] > best_count:
            best, best_count = d, counts[0]
    return best
