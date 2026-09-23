"""账本导出：Excel / PDF 写入 `exports/`（**不在 uploads 之下**，见下面的理由）。

⛔ 为什么不能放在 `uploads/`（2026-09-19 审计）：`/static/uploads/**` 是一条**无鉴权**路由，
生产 nginx 还把它 alias 到磁盘直出。账本导出物里是货主名/商品/单价/总额/订单号，
放进那里等于"谁都能匿名下载别家的账本"，而且文件名以前是可枚举的。
现在产物目录在 uploads 之外，只能经带鉴权的下载端点取。

⚠️ 产物的**命名与定位**只有一处实现（[ledger_export_paths]）：生成时怎么起名、
下载时怎么找到它、给前端的 URL 长什么样，三件事各写一份的话就会像 2026-09-19 那样
"生成写 URL、下载端读一个不存在的属性" → 每次下载 500。
"""

from datetime import date
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Ledger, Order, User
from app.services.ledger_scope import visible_ledger_select
from app.services.sheet_text import append_text_row
from app.services.ledger_export_paths import (
    EXPORT_DIR,
    LEGACY_UPLOAD_EXPORTS,
    download_url,
    ensure_export_dir,
    export_file_name,
    find_export_file,
    legacy_file_names,
)

__all__ = [
    "EXPORT_DIR",
    "LEGACY_UPLOAD_EXPORTS",
    "build_ledger_rows",
    "download_url",
    "ensure_export_dir",
    "export_file_name",
    "find_export_file",
    "legacy_file_names",
    "run_ledger_export_file",
    "write_excel",
    "write_pdf",
]


def build_ledger_rows(
    db: Session,
    shipper_id: int,
    date_from: date,
    date_to: date,
) -> tuple[list[Ledger], str]:
    shipper = db.get(User, shipper_id)
    shipper_label = (shipper.full_name or shipper.phone or str(shipper_id)) if shipper else str(shipper_id)
    q = (
        # 隔离区（软删）订单的那份账不算（R13-R6）：与报表侧同一句
        visible_ledger_select()
        .where(Ledger.shipper_id == shipper_id)
        .where(Ledger.entry_date >= date_from)
        .where(Ledger.entry_date <= date_to)
        .order_by(Ledger.entry_date.asc(), Ledger.id.asc())
    )
    rows = list(db.scalars(q).all())
    return rows, shipper_label


def _append_text_row(ws, cells: list) -> None:
    """写一行；**字符串一律强制成文本节点**（以 `=` 开头的值不许变成活公式）。

    ⚠️ 2026-09-24 第 20 轮（D7-1）：实现搬到了 `services/sheet_text.py`，因为
    `api/v1/reports.py` 的六个 kind 与 `services/stats_export.py` 原来**没有抄这份防护**
    （报表导出里全是裸 `ws.append`）—— 同一条规矩一个仓库里两份实现，迟早就分叉。
    这里保留这个名字只是为了不动本文件里的 15 个调用点。
    """
    append_text_row(ws, cells)


def write_excel(
    db: Session,
    path: Path,
    rows: list[Ledger],
    shipper_label: str,
    date_from: date,
    date_to: date,
) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "账本"
    _append_text_row(ws, ["货主", shipper_label, "", "", f"{date_from} ~ {date_to}"])
    _append_text_row(
        ws, ["日期", "订单说明", "商品", "数量", "单价", "总价", "关联订单ID", "订单号", "来源", "备注"]
    )
    # 订单说明/订单号**一次查完**（2026-09-19 第二轮外部检查 R2-6(exp)）：原来在循环里
    # 逐行 `db.get(Order, r.order_id)`，一份 500 行的账本 = 500 次 `SELECT ... FROM orders`。
    # ⚠️ 这**不是**"命中身份映射所以没事"：`Session` 的身份映射持**弱引用**，
    #    上一个订单对象随时可能被回收，所以每一行都真的发一次 SQL。
    # 只取这两列（不装载整个 Order 对象），语义与 `db.get` 完全一致：
    #    不过滤 `deleted_at`（隔离区订单的说明照样要印）、查不到的行给空串。
    order_text: dict[int, tuple[str, str]] = {}
    order_ids = {r.order_id for r in rows if r.order_id}
    if order_ids:
        for oid, desc_raw, no_raw in db.execute(
            select(Order.id, Order.delivery_description, Order.order_no).where(Order.id.in_(order_ids))
        ):
            order_text[oid] = ((desc_raw or "").strip(), no_raw or "")
    for r in rows:
        desc, ord_no = order_text.get(r.order_id, ("", ""))
        _append_text_row(
            ws,
            [
                r.entry_date.isoformat(),
                desc,
                r.product_name,
                r.quantity,
                float(r.unit_price),
                float(r.total),
                r.order_id or "",
                ord_no,
                r.source.value if hasattr(r.source, "value") else str(r.source),
                r.note or "",
            ]
        )
    wb.save(path)


def _ascii_cell(s: str, max_len: int = 80) -> str:
    """PDF 核心字体仅支持 Latin-1；非 ASCII 替换为 ?，避免 fpdf 抛错。"""
    t = (s or "")[:max_len]
    return t.encode("ascii", "replace").decode("ascii")


def write_pdf(path: Path, rows: list[Ledger], shipper_label: str, date_from: date, date_to: date) -> None:
    """横向 PDF 表格。

    ⛔ **这条路已经关掉了**（2026-09-24 第 20 轮 D11-1）：fpdf2 的核心字体 Helvetica 只支持
    Latin-1，`_ascii_cell` 会把所有中文换成 `?`（实测 `'水东芥菜' → '????'`），
    而任务照样落 `DONE` 并发下载链接 —— 用户打开才知道是废纸。创建任务那一侧现在直接 400
    （`api/v1/ledger.py::create_export_job` 里那条"PDF 导出暂时关闭"）。
    这里再兜一层：**只要内容里有非 ASCII 就抛错**，让任务落 `FAILED` 并带上能读懂的原因
    （而不是悄悄产出一份 `?` 文件）—— 历史遗留的 pending 任务也会走到这里。

    要重新打开这条路，需要：① 一个可嵌入的 CJK 字体（`pdf.add_font(...)`）；
    ② 删掉 `create_export_job` 里那条 400；③ 把 `_ascii_cell` 换成真正的中文排版。
    """
    from fpdf import FPDF

    for r in rows:
        if any(ord(ch) > 127 for ch in (r.product_name or "") + (r.unit or "")):
            raise ValueError(
                "PDF 导出里的中文无法渲染（服务器没有内嵌中文字体，商品名会变成「?」）。"
                "请改用 Excel 导出。"
            )
    if any(ord(ch) > 127 for ch in shipper_label or ""):
        raise ValueError(
            "PDF 导出里的中文无法渲染（服务器没有内嵌中文字体，货主名会变成「?」）。"
            "请改用 Excel 导出。"
        )

    pdf = FPDF(orientation="L")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=9)
    title = _ascii_cell(f"Ledger {shipper_label} {date_from} ~ {date_to}", 120)
    pdf.cell(0, 8, text=title, ln=1)
    pdf.ln(2)
    col_w = [28, 55, 14, 22, 24, 22]
    headers = ["Date", "Product", "Qty", "Unit", "Total", "Order"]
    for i, h in enumerate(headers):
        pdf.cell(col_w[i], 7, text=h[:20], border=1)
    pdf.ln()
    for r in rows:
        cells = [
            r.entry_date.isoformat(),
            _ascii_cell(r.product_name or "", 60),
            str(r.quantity),
            str(r.unit_price),
            str(r.total),
            str(r.order_id or ""),
        ]
        for i, c in enumerate(cells):
            pdf.cell(col_w[i], 7, text=str(c)[:40], border=1)
        pdf.ln()


def run_ledger_export_file(
    db: Session,
    shipper_id: int,
    date_from: date,
    date_to: date,
    fmt: str,
    job_id: int,
) -> str:
    """生成产物，返回**文件名**（相对 [EXPORT_DIR]，不含目录）。

    ⚠️ 这里原来返回的是"下载 URL"，任务行把它存进 `file_path`，而下载端点又拿它当文件名去
    磁盘上找 → 必然 404；更早还返回过 `/static/uploads/...`（无鉴权可枚举，2026-09-19 审计）。
    现在只回名字：**数据库里存的是"产物叫什么"，URL 由 [download_url] 现算**——
    这样"改路由前缀"不会让历史数据失效，"改文件名规则"也不会让下载端猜错。
    """
    ensure_export_dir()
    rows, shipper_label = build_ledger_rows(db, shipper_id, date_from, date_to)
    fname = export_file_name(shipper_id, job_id, fmt)
    path = EXPORT_DIR / fname
    if fmt == "excel":
        write_excel(db, path, rows, shipper_label, date_from, date_to)
    else:
        write_pdf(path, rows, shipper_label, date_from, date_to)
    return fname
