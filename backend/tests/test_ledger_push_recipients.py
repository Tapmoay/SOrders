"""账本/钱变动的**收件人**：货主 + 司机 + 派单员（2026-09-24 第 20 轮并行渗透 C12-1 / C12-2）。

## 抓到的形状
`publish_ledger_updated_event` 原来**只发给货主一个人**，而客户端有**三个角色**在订阅
`ledger.updated` → `refreshLedger`：
  · 货主「我的账本」；· **司机「我的运费」**（`DriverFreightViewModel.kt:85`）；
  · **派单员「账本管理」**（`DispatcherLedgerViewModel.kt:444`）。
后两者**永远收不到**这个信号 → 送达/改运费/记账/核销之后他们的页面停在旧数字，且不报错。

而**核销**（`POST /ledger/receipts`）更彻底：那条路径**一个推送都没有**（同文件的手工记账有）
—— 派单员在柜台收了钱，货主手机上零事件，「我的账本」还画着「欠 ¥192.60」，
**断线重连也补不回**（重连只回补通知表）。

判据（这一条测试钉住的）：
1. 三类收件人**都**要收到 `ledger.updated`；
2. ⛔ 但不许退化成"给所有人广播"（账本是按人的东西）—— 只给货主时**只发给他一个**。
"""

from __future__ import annotations

import asyncio
import uuid

from app.core.rbac import user_role_key
from app.services import message_center
from tests.conftest import auth_headers


def _capture(monkeypatch) -> list[tuple[int, str]]:
    sent: list[tuple[int, str]] = []

    async def fake_emit(user_id: int, payload: dict) -> None:
        sent.append((int(user_id), str(payload.get("type"))))

    # `publish_ledger_updated_event` 是在本模块里调 `emit_realtime` 的 → 打这个补丁就够
    monkeypatch.setattr(message_center, "emit_realtime", fake_emit)
    return sent


def test_账本事件发给货主司机和派单员(monkeypatch, db_session, users):
    sent = _capture(monkeypatch)
    asyncio.run(
        message_center.publish_ledger_updated_event(
            users["shipper"].id, driver_id=users["driver"].id, dispatchers=True
        )
    )
    who = {uid for uid, _t in sent}
    assert all(t == "ledger.updated" for _uid, t in sent), sent
    assert users["shipper"].id in who, "这本账的主人没收到"
    assert users["driver"].id in who, (
        "司机没收到 —— 他「我的运费」那页订阅的正是 ledger.updated，"
        "送达/改运费/核销之后那一页会停在旧数字（第 20 轮 C12-2）"
    )
    dispatchers = {u.id for u in users.values() if user_role_key(u) == "dispatcher"}
    assert dispatchers & who, "派单员没收到 —— 「账本管理」页也会停在旧数字"


def test_不许退化成给所有人广播(monkeypatch, db_session, users):
    """反向对照：只给了货主时，**只能**发给他一个（账本是按人的东西）。"""
    sent = _capture(monkeypatch)
    asyncio.run(message_center.publish_ledger_updated_event(users["shipper"].id))
    assert [uid for uid, _t in sent] == [users["shipper"].id], sent


def test_核销之后会推送(client, db_session, users, token_dispatcher, monkeypatch):
    """**C12-1 的确证**：`POST /ledger/receipts` 原来一个推送都不发。"""
    from app.models import Customer

    h = auth_headers(token_dispatcher)
    c = Customer(
        name=f"核销推送探针货主-{uuid.uuid4().hex[:6]}",
        user_id=users["shipper"].id,
        kind="registered",
    )
    db_session.add(c)
    db_session.commit()

    sent = _capture(monkeypatch)
    r = client.post(
        "/api/v1/ledger/receipts",
        json={
            "customer_id": c.id,
            "amount": "100.00",
            "method": "cash",
            "received_at": "2026-09-20",     # 必填（收款日期）
            "settle_mode": "rolling",     # 滚动收款：不绑订单，测试里最省事
            "note": "第 20 轮推送探针",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    # `TestClient` 会把 BackgroundTasks 跑完再返回 → 这里能直接断言
    assert sent, (
        "核销之后一条 `ledger.updated` 都没发 —— 货主界面会一直显示旧的欠款数，"
        "而且断线重连也补不回（重连只回补通知表）"
    )
    assert users["shipper"].id in {uid for uid, _t in sent}, (
        f"核销推送没发给这本账的主人：{sent}"
    )
