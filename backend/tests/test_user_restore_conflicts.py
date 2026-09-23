"""账号「删掉再用同号重建」之后的**半条记录**：恢复回来的号码可能已经不是他的了。

## 抓到的形状（2026-09-24 第 20 轮并行渗透 D9-F3 / 第 19 轮 C6-1）
删号时 `users.phone` / `users.username` 会被加上 `_del{id}` 后缀（把号码/用户名让给新账号），
`POST /users/{id}/restore` 负责去掉后缀。两条分支的**冲突处理不一致**：

| 列 | 撞了别的账号时 | 后果 |
| --- | --- | --- |
| `phone` | 保留 `13800000003_del7`，**照样 `is_active=True`** | 他成了一条"号码带后缀的活账号" |
| `username` | **不查冲突**，直接去后缀 | 撞唯一索引 → `IntegrityError` → **整次恢复回滚**（老账号再也放不回来） |

而 `phone` 那一支的后果比"看着难看"严重得多：订单出参有三处把 `_del{id}` 后缀**去掉再显示**
（`order_response.py` 的 `driver_phone`、`ledger.py`、`freight_settlement.py`），
于是**订单详情上那个拨号键会拨给抢走这个号码的另一个人** —— 与这一单毫无关系的人。

## 判据
1. 撞了 `username` 时**不许崩**：保留后缀、把冲突如实写进返回与审计（与 `phone` 那一支同形）。
2. "活账号 + 号码带 `_del` 后缀" ⇒ **那号码不是他的** ⇒ 出参**不许**去尾显示、也不许给拨号入口
   （宁可没有号码，也不能给一个错的号码 —— 这是本项目最贵的一类错）。
3. 反向对照：**被软删**的账号（号码带后缀、`is_active=False`）仍然按老口径去尾显示
   （那个后缀只是把号码让出去的痕迹，历史订单上还要能看出"这单是谁拉的"）。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import OperationLog, Order, User
from app.models.enums import OrderStatus
from app.services.auth_service import issue_token
from tests.conftest import auth_headers


def _mk_driver(db_session, phone: str) -> User:
    u = User(
        phone=phone,
        full_name="恢复冲突探针司机",
        username=phone,
        password_hash="x",
        role="DRIVER",
        is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    return u


def _order_of(db_session, driver: User) -> Order:
    from datetime import date

    o = Order(
        order_no=f"SO-RESTORE-{uuid.uuid4().hex[:8].upper()}",
        shipper_id=None,
        driver_id=driver.id,
        status=OrderStatus.DISPATCHED,
        order_date=date(2026, 9, 20),
        freight_fee=50,
    )
    db_session.add(o)
    db_session.commit()
    return o


def test_用户名撞了也要能恢复(client, db_session, users, token_dispatcher):
    """`username` 那一支原来不查冲突 → 撞唯一索引 → 整次恢复回滚（老账号永久放不回来）。"""
    h = auth_headers(token_dispatcher)
    phone = "138" + uuid.uuid4().hex[:8]
    a = _mk_driver(db_session, phone)
    aid = a.id
    assert client.delete(f"/api/v1/users/{aid}", headers=h).status_code in (200, 204)
    # 号被新账号抢走（建号默认 `username = phone`）
    b = _mk_driver(db_session, phone)

    r = client.post(f"/api/v1/users/{aid}/restore", headers=h)
    assert r.status_code == 200, (
        f"恢复失败（HTTP {r.status_code}）：{r.text[:200]} —— "
        "用户名撞唯一索引时整次恢复回滚，老账号就再也放不回来了"
    )
    db_session.expire_all()
    restored = db_session.get(User, aid)
    assert restored.is_active is True
    assert restored.username.endswith(f"_del{aid}"), (
        f"用户名被别的账号占了（{b.username}）却把后缀去掉了：{restored.username!r} —— "
        "那要么撞唯一索引、要么把别人顶掉"
    )
    # 冲突要留痕（与手机号那一支同形的口径）
    db_session.expire_all()
    logs = [
        x for x in db_session.scalars(
            select(OperationLog).where(OperationLog.action == "USER_RESTORE")
        )
        if f'"user_id": {aid}' in (x.change_content or "") or f'"user_id":{aid}' in (x.change_content or "")
    ]
    assert logs, "恢复没有留痕"
    assert "conflicts" in (logs[-1].change_content or "")


def test_恢复后号码不是他的_就不给拨号入口(client, db_session, users, token_dispatcher):
    """**这一条是本轮那个"打错人"的确证**：出参不许把 `_del` 后缀去掉后当成他的号码。"""
    h = auth_headers(token_dispatcher)
    phone = "137" + uuid.uuid4().hex[:8]
    a = _mk_driver(db_session, phone)
    aid = a.id
    order = _order_of(db_session, a)
    # 删号 → 号码带后缀
    assert client.delete(f"/api/v1/users/{aid}", headers=h).status_code in (200, 204)
    # 新账号抢走这个号码
    b = _mk_driver(db_session, phone)
    assert client.post(f"/api/v1/users/{aid}/restore", headers=h).status_code == 200

    db_session.expire_all()
    r = client.get(f"/api/v1/orders/{order.id}", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    got = body.get("driver_phone")
    assert got != phone, (
        f"订单详情把 `{phone}` 当成这位司机的号码下发 —— 可那是账号 #{b.id} 的号码，"
        "派单员一点拨号键就打给与这一单无关的人"
    )
    assert got in (None, ""), f"拿不到真实号码时应给空（现在是 {got!r}）"


def test_被软删的账号仍然去尾显示(client, db_session, users, token_dispatcher):
    """反向对照：**没恢复**的软删账号，历史订单上还要能看出"这单是谁拉的"。"""
    h = auth_headers(token_dispatcher)
    phone = "136" + uuid.uuid4().hex[:8]
    a = _mk_driver(db_session, phone)
    order = _order_of(db_session, a)
    assert client.delete(f"/api/v1/users/{a.id}", headers=h).status_code in (200, 204)

    db_session.expire_all()
    r = client.get(f"/api/v1/orders/{order.id}", headers=h)
    assert r.status_code == 200, r.text
    assert r.json().get("driver_phone") == phone, (
        "软删账号（号码带 `_del` 后缀、只是把号码让出去了）应当照旧去尾显示"
    )
