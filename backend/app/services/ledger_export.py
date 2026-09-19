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
    ws.append(["货主", shipper_label, "", "", f"{date_from} ~ {date_to}"])
    ws.append(["日期", "订单说明", "商品", "数量", "单价", "总价", "关联订单ID", "订单号", "来源", "备注"])
    for r in rows:
        desc = ""
        ord_no = ""
        if r.order_id:
            o = db.get(Order, r.order_id)
            if o:
                desc = (o.delivery_description or "").strip()
                ord_no = o.order_no or ""
        ws.append(
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
    """横向 PDF 表格（ASCII 安全；含中文字段以 ? 代替，Excel 导出保留原文）。"""
    from fpdf import FPDF

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
