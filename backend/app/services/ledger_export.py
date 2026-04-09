"""账本导出：Excel / PDF 写入 uploads/exports。"""

from datetime import date
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Ledger, Order, User

UPLOAD_EXPORTS = Path("uploads") / "exports"


def ensure_export_dir() -> None:
    UPLOAD_EXPORTS.mkdir(parents=True, exist_ok=True)


def build_ledger_rows(
    db: Session,
    shipper_id: int,
    date_from: date,
    date_to: date,
) -> tuple[list[Ledger], str]:
    shipper = db.get(User, shipper_id)
    shipper_label = (shipper.full_name or shipper.phone or str(shipper_id)) if shipper else str(shipper_id)
    q = (
        select(Ledger)
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
    ensure_export_dir()
    rows, shipper_label = build_ledger_rows(db, shipper_id, date_from, date_to)
    ext = "xlsx" if fmt == "excel" else "pdf"
    fname = f"ledger_{shipper_id}_{job_id}.{ext}"
    path = UPLOAD_EXPORTS / fname
    if fmt == "excel":
        write_excel(db, path, rows, shipper_label, date_from, date_to)
    else:
        write_pdf(path, rows, shipper_label, date_from, date_to)
    return f"/static/uploads/exports/{fname}"
