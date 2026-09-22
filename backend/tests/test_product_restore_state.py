"""商品的「恢复」必须**还原**状态，而不是"顺手重新上架"（2026-09-23 复核 K6）。

## 这条测试在钉什么

删除商品会强制下架（`is_active=False`），而"删除"与"下架"是两件事：
用户完全可能**先刻意下架**（暂时不卖），过一阵再删掉；等他哪天恢复，
如果恢复无条件把 `is_active` 设回 True，那个商品就**悄悄回到货架**——
选品页/下单页又会看到它，而他以为自己早就下架了（界面上没有任何地方告诉他这件事）。

三档都要钉住：
1. 删除前是上架的 → 恢复后仍然上架（正常的"删错了，恢复"）；
2. 删除前是**刻意下架**的 → 恢复后仍然下架（这条是本次修的那个缺陷）；
3. 读不到"删除前的状态"（历史数据 / 日志里没有 `was_active`）→ **保持下架**（fail-closed）。

⚠️ 判据要读**库里的行**（`ProductOut` 不下发 `is_deleted`，只看接口出参会漏掉一半事实）。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import OperationLog, Product
from app.models.enums import OperationAction
from tests.conftest import auth_headers


def _create(client: TestClient, token: str, name: str) -> int:
    r = client.post(
        "/api/v1/products",
        json={"name": name, "default_unit_price": "10", "name_color": None},
        headers=auth_headers(token),
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _delete(client: TestClient, token: str, pid: int) -> None:
    r = client.delete(f"/api/v1/products/{pid}", headers=auth_headers(token))
    assert r.status_code == 204, r.text


def _restore(client: TestClient, token: str, pid: int) -> dict:
    r = client.post(f"/api/v1/products/{pid}/restore", headers=auth_headers(token))
    assert r.status_code == 200, r.text
    return r.json()


def _row(db: Session, pid: int) -> Product:
    db.expire_all()  # 接口那边的改动要重新从库里读（身份映射里可能是旧对象）
    row = db.get(Product, pid)
    assert row is not None
    return row


@pytest.mark.dispatcher
def test_restore_keeps_deliberately_off_shelf_product_off_shelf(
    client: TestClient, token_dispatcher: str, db_session: Session
) -> None:
    pid = _create(client, token_dispatcher, "刻意下架再删的商品")
    # ① 先**刻意下架**（这是用户的真实意图：暂时不卖）
    r = client.patch(
        f"/api/v1/products/{pid}",
        json={"is_active": False},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False

    # ② 再删掉、然后恢复
    _delete(client, token_dispatcher, pid)
    body = _restore(client, token_dispatcher, pid)

    assert _row(db_session, pid).is_deleted is False, "恢复后不该还在回收站里"
    assert body["is_active"] is False, (
        "恢复把「刻意下架」的商品重新上架了 —— 它会在选品页/下单页重新出现，"
        "而用户以为自己早就下架了"
    )


@pytest.mark.dispatcher
def test_restore_brings_back_an_active_product(
    client: TestClient, token_dispatcher: str, db_session: Session
) -> None:
    pid = _create(client, token_dispatcher, "正常删了又恢复的商品")

    _delete(client, token_dispatcher, pid)
    body = _restore(client, token_dispatcher, pid)

    assert _row(db_session, pid).is_deleted is False
    assert body["is_active"] is True, "删除前它是上架的，恢复应该一并还原（不然用户以为恢复没生效）"


@pytest.mark.dispatcher
def test_restore_without_history_does_not_relist(
    client: TestClient, token_dispatcher: str, db_session: Session
) -> None:
    """读不到"删除前的状态"时保持下架（fail-closed），而不是猜成"上架"。"""
    pid = _create(client, token_dispatcher, "没有删除前状态的商品")
    _delete(client, token_dispatcher, pid)

    # 把那两条日志改成"加 was_active 之前"的样子（历史数据的形状：只有 id/名字/库存）
    logs = (
        db_session.query(OperationLog)
        .filter(OperationLog.action == OperationAction.PRODUCT_DELETE.value)
        .order_by(OperationLog.id.desc())
        .limit(500)
        .all()
    )
    hit = 0
    for log in logs:
        if f'"product_id": {pid},' in (log.change_content or ""):
            log.change_content = '{"product_id": %d, "name": "旧日志", "stock": 0}' % pid
            hit += 1
    assert hit == 1, "没改到那条删除日志（测试的前提不成立）"
    db_session.commit()

    body = _restore(client, token_dispatcher, pid)
    assert _row(db_session, pid).is_deleted is False
    assert body["is_active"] is False, "读不到删除前的状态时不许猜成「上架」（fail-closed）"
