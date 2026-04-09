"""派单员看板 Excel 导出（内存流）。"""

from datetime import date
from io import BytesIO

from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.schemas.stats import StatsExportBody
from app.services import stats_service


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
        ws.append(
            [
                "时间粒度",
                body.chart_granularity,
                "指标",
                body.chart_metric,
                "",
                f"{body.date_from} ~ {body.date_to}",
            ]
        )
        ws.append(["周期"] + [s["name"] for s in series])
        for i, cat in enumerate(cats):
            row = [cat]
            for s in series:
                d = s.get("data") or []
                row.append(d[i] if i < len(d) else 0)
            ws.append(row)

    if body.include_driver_perf:
        ws = next_sheet("司机绩效")
        rows = stats_service.driver_performance(db, body.date_from, body.date_to)
        ws.append([f"送达时间范围 {body.date_from} ~ {body.date_to}"])
        ws.append(
            [
                "司机ID",
                "司机",
                "完成单量",
                "准时率",
                "平均送达秒",
                "照片上传率",
            ]
        )
        for r in rows:
            ws.append(
                [
                    r["driver_id"],
                    r["driver_name"],
                    r["completed_count"],
                    r["on_time_rate"] if r["on_time_rate"] is not None else "",
                    r["avg_delivery_seconds"] if r["avg_delivery_seconds"] is not None else "",
                    r["photo_upload_rate"],
                ]
            )

    if body.include_exceptions:
        ws = next_sheet("异常订单")
        ex = stats_service.exception_orders(db, body.date_from, body.date_to)
        ws.append([f"下单日期 {body.date_from} ~ {body.date_to}"])
        ws.append(
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
            ws.append(
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
        ws.append(["未选择任何导出项"])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
