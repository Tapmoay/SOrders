"""派单员看板 Excel 导出（内存流）。"""

from datetime import date
from io import BytesIO

from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.schemas.stats import StatsExportBody
from app.services import stats_service
from app.services.sheet_text import append_text_row


def build_stats_export_bytes(db: Session, body: StatsExportBody) -> bytes:
    wb = Workbook()
    first_sheet = True

    def next_sheet(title: str):
        nonlocal first_sheet
        if first_sheet:
            ws = wb.active
            ws.title = title
            first_sheet = False
            return ws
        return wb.create_sheet(title)

    if body.include_shipper_chart:
        ws = next_sheet("货主商品")
        cats, series = stats_service.shipper_product_chart(
            db,
            body.date_from,
            body.date_to,
            body.chart_granularity,
            body.chart_metric,
        )
        append_text_row(ws, 
            [
                "时间粒度",
                body.chart_granularity,
                "指标",
                body.chart_metric,
                "",
                f"{body.date_from} ~ {body.date_to}",
            ]
        )
        append_text_row(ws, ["周期"] + [s["name"] for s in series])
        # ⛔ **如实说出"这不是全部"**（2026-09-24 第 20 轮 D11-4）：这张表的数据来自
        #    `stats_service.shipper_product_chart`，而它为画曲线**只取前 12 个商品** ——
        #    导出沿用它，于是文件里静默少了其余商品（整个导出家族里唯一一处静默截断）。
        #    曲线限 12 条是画布的限制，导出不是；在没改成"导出全量"之前，
        #    必须让拿文件的人一眼看到这句话（否则他会拿这 12 行当全部去对账）。
        if len(series) >= stats_service.TOP_PRODUCTS:
            append_text_row(ws, [
                f"⚠️ 本表只列了金额/数量最高的前 {len(series)} 个商品（按指标排序），"
                "不是全部商品；需要完整清单请用「报表中心 → 商品」或导出 kind=products。"
            ])
        for i, cat in enumerate(cats):
            row = [cat]
            for s in series:
                d = s.get("data") or []
                row.append(d[i] if i < len(d) else 0)
            append_text_row(ws, row)

    if body.include_driver_perf:
        ws = next_sheet("司机绩效")
        rows = stats_service.driver_performance(db, body.date_from, body.date_to)
        append_text_row(ws, [f"送达时间范围 {body.date_from} ~ {body.date_to}"])
        # ⚠️ **列名/列序/单位必须与 `/reports/export?kind=drivers` 对得上**（2026-09-24 第 20 轮 D11-5）：
        #    两份导出同名同源（`stats_service.driver_performance`），而原来一份是
        #    「司机 / 完成单量 / 准时率 / 拍照率 / **平均送达分钟** / 计费方式 / 待结运费」、
        #    另一份（本文件）是「司机ID / 司机 / 完成单量 / 准时率 / **平均送达秒** / 照片上传率」
        #    —— 同一个数一处 `12.5`、一处 `750.0`（差 60 倍），谁拿两张表对账都会对不上。
        #    现在两张表**逐列同名同序同单位**（分钟），金额列也补上（本文件原来漏了这两列）。
        append_text_row(ws, 
            [
                "司机",
                "完成单量",
                "准时率",
                "拍照率",
                "平均送达分钟",
                "计费方式",
                "待结运费",
            ]
        )
        for r in rows:
            avg_min = r.get("avg_delivery_seconds")
            append_text_row(ws, 
                [
                    r["driver_name"],
                    r["completed_count"],
                    r["on_time_rate"] if r["on_time_rate"] is not None else "",
                    r["photo_upload_rate"],
                    round(avg_min / 60, 2) if avg_min is not None else "",
                    r.get("billing_mode") or "",
                    r["freight_owed"] if r.get("freight_owed") is not None else "",
                ]
            )

    if body.include_exceptions:
        ws = next_sheet("异常订单")
        ex = stats_service.exception_orders(db, body.date_from, body.date_to)
        append_text_row(ws, [f"下单日期 {body.date_from} ~ {body.date_to}"])
        append_text_row(ws, 
            [
                "订单ID",
                "订单号",
                "下单日",
                "状态",
                "货主",
                "司机",
                "异常原因",
                "处理结果",
                "约定送达前",
                "实际送达",
            ]
        )
        for o in ex:
            append_text_row(ws, 
                [
                    o["id"],
                    o["order_no"],
                    o["order_date"].isoformat(),
                    o["status"],
                    o["shipper_name"] or "",
                    o["driver_name"] or "",
                    o["exception_reason"],
                    o["exception_resolution"],
                    o["expected_deliver_before"].isoformat() if o["expected_deliver_before"] else "",
                    o["delivered_at"].isoformat() if o["delivered_at"] else "",
                ]
            )

    if first_sheet:
        ws = wb.active
        ws.title = "导出"
        append_text_row(ws, ["未选择任何导出项"])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
