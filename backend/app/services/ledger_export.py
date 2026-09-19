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


def _append_text_row(ws, cells: list) -> None:
    """写一行；**字符串一律强制成文本节点**（以 `=` 开头的值不许变成活公式）。

    ### 缺陷现场（2026-09-19 第二轮外部检查 R2-1）
    原来这里是 `ws.append([...])`，而 openpyxl 把"以 `=` 开头的字符串"写成**公式节点**。
    本机实测（openpyxl 3.1.5，读产物里的 `xl/worksheets/sheet1.xml` 而不是看对象属性）：

    | 写法 | 产物里的节点 |
    | --- | --- |
    | `ws.append(["=1+1"])` | `<c r="A1"><f>1+1</f><v></v></c>` ← **活公式** |
    | 强制 `data_type='s'` 后同一个值 | `<c r="A1" t="inlineStr"><is><t>=1+1</t></is></c>` ← 文本 |

    这张表里用户可控的格子有：货主名、**订单说明**（`Order.delivery_description`，
    货主下单时自己填的）、商品名、订单号、备注。任何一处以 `=` 开头，
    导出的 xlsx 在别人的 Excel 里就是公式（`=HYPERLINK(...)` 一类可以直接外联）。
    顺带实测：`+` / `-` / `@` / 前导 Tab / 前导 CR 开头的值**本来**就是
    `t="inlineStr"` 文本（CSV 时代的那张危险前缀表在 xlsx 上不成立，
    因为 xlsx 的单元格类型是显式写死的），唯一能变成活公式的入口就是 `=`。

    ### 为什么用"强制类型"而不是"加前导 `'` 或空格"
    前导引号/空格是 CSV 的业界做法，代价是**改动了数据本身**：格子里多一个字符，
    复制出去、再导回来都是脏的。xlsx 的类型是显式的，设一次 `data_type='s'`
    就能既不执行公式、又**一字不改**原值：逐字节对比过改前/改后的产物，
    同一个值写出的 `<c>` 节点完全一致（含中文、空格、Tab/CR 的 `xml:space="preserve"`），
    **唯一变化的格子就是 `=` 开头的那些**（`<f>` → `<is><t>`）——
    所以这份改动没有"极少数值要付出代价"这一档。

    ⚠️ 只对 `str` 生效：数量/单价/总价是**真数值列**，必须继续能被 Excel 求和
    （司机绩效那列"待结运费"是同一个道理，见 `api/v1/reports.py` 的 R2-3）。
    """
    ws.append(cells)
    for c in ws[ws.max_row]:
        if isinstance(c.value, str):
            c.data_type = "s"


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
