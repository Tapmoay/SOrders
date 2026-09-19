"""结算付款的**原子占位**：直接钉"条件 UPDATE 只让一个人赢"（2026-09-19 审计 S5）。

## 为什么不写成"顺序付两次"的用例
顺序双付本来就被 `if s.status != CONFIRMED: raise` 挡住 —— 那种用例**摘掉占位也照样绿**
（我在跨域 E2E 的反向验证里实测过：把 `if claimed.rowcount != 1` 改成 `if False` 之后
E2E 仍然通过）。所以它的判据必须是**条件 UPDATE 本身**，与
`test_concurrent_delivery_money.py::test_paid_claim_is_atomic_on_this_db` 同一套形状。

真实风险是**并发**：派单员两台设备同时点「付款」，两条请求都读到 confirmed →
各自写一条 `PAYMENT_DRIVER` 现金流水 → **同一笔钱在账上扣两次**（`cash_flows` 上没有
`(doc_id, biz_type)` 唯一约束兜底）。
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import update

from app.models import DriverSettlement
from app.models.enums import DriverBillType, SettlementStatus


def test_settlement_pay_claim_is_atomic_on_this_db(db_session, users) -> None:
    """`confirmed → paid` 的条件占位：第一次 1 行、第二次 0 行。"""
    s = DriverSettlement(
        driver_id=users["driver"].id,
        settle_type=DriverBillType.PIECE,
        month="2026-09",
        period_from=date(2026, 9, 1),
        period_to=date(2026, 9, 30),
        amount=100,
        status=SettlementStatus.CONFIRMED,
    )
    db_session.add(s)
    db_session.commit()

    def claim() -> int:
        res = db_session.execute(
            update(DriverSettlement)
            .where(
                DriverSettlement.id == s.id,
                DriverSettlement.status == SettlementStatus.CONFIRMED,
            )
            .values(status=SettlementStatus.PAID, method="cash")
        )
        db_session.commit()
        return res.rowcount

    assert claim() == 1, "第一次占位必须成功"
    assert claim() == 0, "第二次占位必须失败（否则并发下同一笔付款会写两条流出流水）"
