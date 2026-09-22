"""派单员动**别人的**站内信必须留痕；动自己的不记（2026-09-23 复核 A8）。

## 这条测试在钉什么

`notifications.py` 有三个会改数据的端点，判据都是
`n.recipient_id != current.id and user_role_key(current) != DISPATCHER → 403`
—— 也就是说**派单员可以读/改/删任何账号的消息**（产品口径：消息中心是全局视图）。
权限本身没动，但在这之前它**一条审计都不写**：

    一次 `POST /notifications/batch-delete {"recipient_id": X, "all": true}`
    就能永久清空 X 的全部站内信，事后在审计页上查不到任何痕迹。

所以现在按"动自己的不记、动**别人的**必须记"落地（`NOTIFICATION_MODERATE`）。
两半都要钉：**跨账号要留痕**（不然等于没修），**动自己的不许记**（不然一条群发几十行、
审计页会被淹掉，而那正是当初给它豁免的理由）。
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Notification, OperationLog, User
from app.models.enums import OperationAction
from tests.conftest import auth_headers


def _mk_notification(db: Session, recipient_id: int, title: str) -> int:
    n = Notification(
        recipient_id=recipient_id,
        category="system",
        type="system",
        title=title,
        content="内容",
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return int(n.id)


def _moderate_logs(db: Session) -> list[OperationLog]:
    db.expire_all()
    return (
        db.query(OperationLog)
        .filter(OperationLog.action == OperationAction.NOTIFICATION_MODERATE.value)
        .order_by(OperationLog.id)
        .all()
    )


@pytest.mark.dispatcher
def test_dispatcher_deleting_someone_elses_message_is_logged(
    client: TestClient, token_dispatcher: str, users: dict[str, User], db_session: Session
) -> None:
    shipper = users["shipper"]
    nid = _mk_notification(db_session, shipper.id, "别人的一条消息")
    before = len(_moderate_logs(db_session))

    r = client.delete(f"/api/v1/notifications/{nid}", headers=auth_headers(token_dispatcher))
    assert r.status_code == 204, r.text

    logs = _moderate_logs(db_session)
    assert len(logs) == before + 1, "派单员删了别人的消息却没留痕"
    payload = json.loads(logs[-1].change_content or "{}")
    assert payload.get("act") == "delete"
    assert payload.get("recipient_id") == shipper.id
    assert payload.get("notification_id") == nid
    assert logs[-1].operator_id == users["dispatcher"].id


@pytest.mark.dispatcher
def test_dispatcher_editing_someone_elses_message_is_logged(
    client: TestClient, token_dispatcher: str, users: dict[str, User], db_session: Session
) -> None:
    nid = _mk_notification(db_session, users["shipper"].id, "原标题")
    before = len(_moderate_logs(db_session))

    r = client.patch(
        f"/api/v1/notifications/{nid}",
        json={"title": "被派单员改过的标题"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text

    logs = _moderate_logs(db_session)
    assert len(logs) == before + 1, "派单员改了别人的消息却没留痕"
    payload = json.loads(logs[-1].change_content or "{}")
    assert payload.get("act") == "update"
    assert "title" in (payload.get("fields") or [])
    assert payload.get("recipient_id") == users["shipper"].id


@pytest.mark.dispatcher
def test_batch_delete_for_another_account_is_logged(
    client: TestClient, token_dispatcher: str, users: dict[str, User], db_session: Session
) -> None:
    for i in range(3):
        _mk_notification(db_session, users["shipper"].id, f"待清空 {i}")
    before = len(_moderate_logs(db_session))

    r = client.post(
        "/api/v1/notifications/batch-delete",
        json={"recipient_id": users["shipper"].id, "all": True},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] >= 3

    logs = _moderate_logs(db_session)
    assert len(logs) == before + 1, "清空别人整个收件箱却没留痕（这是最该留痕的一次）"
    payload = json.loads(logs[-1].change_content or "{}")
    assert payload.get("act") == "batch_delete"
    assert payload.get("scope") == "all"
    assert payload.get("recipient_id") == users["shipper"].id
    assert payload.get("deleted", 0) >= 3


@pytest.mark.dispatcher
def test_acting_on_own_messages_is_not_logged(
    client: TestClient, token_dispatcher: str, users: dict[str, User], db_session: Session
) -> None:
    """动**自己的**消息不许写这条日志（否则一条群发几十行，审计页会被淹掉）。"""
    own = _mk_notification(db_session, users["dispatcher"].id, "我自己的消息")
    before = len(_moderate_logs(db_session))

    assert client.post(
        f"/api/v1/notifications/{own}/read", headers=auth_headers(token_dispatcher)
    ).status_code == 200
    assert client.delete(
        f"/api/v1/notifications/{own}", headers=auth_headers(token_dispatcher)
    ).status_code == 204

    assert len(_moderate_logs(db_session)) == before, "动自己的消息也写了 NOTIFICATION_MODERATE"
