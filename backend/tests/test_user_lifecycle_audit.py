"""账号生命周期：**删号/恢复必须撤销会话**、**「启用」不是「恢复」**、**身份级动作必须留痕**
（2026-09-23 第 17 轮并行渗透的 A3 + A12 两个区域，四件事同属一个文件 `api/v1/users.py`）。

## 四条判据（每条都对应一个"不报错"的现状）

1. **删号不撤销会话**：`auth_service.revoke_tokens_and_sockets` 的注释写着"三个撤销点都调这一个入口"，
   而 `DELETE /users/{id}` 是**第四个**、当时漏了 → 被删账号手机上那条 socket 长连接继续收推送
   （站内信正文、单号、账本），HTTP 侧只是因为 `deps` 查 `is_active` 才挡住。
2. **恢复让旧令牌复活**：删号并不作废令牌，`deps` 只查 `is_active` + 令牌版本 ——
   恢复的那一刻，"删除前签发、当时还没过期"的令牌又能用了。所以恢复也要撤销一次。
3. **「启用」不是「恢复」**：删号时手机号被加了 `_del{id}` 后缀（为了把号码释放给新账号），
   而登录按号码**精确匹配** → 界面报"已启用"、人拿原号码**登不进去**，两边都不报错。
4. **身份级动作零审计**：改密码（`before` 快照里没有 password → `changes` 为空 → 一行日志都不写）
   与货主↔司机互换（整个函数没有 `write_log`，而 AI 侧有一张 HIGH 卡直调它）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from app.models import OperationLog, User
from tests.conftest import auth_headers


def _mk_account(client: TestClient, disp_h: dict, phone: str, role: str = "shipper") -> int:
    r = client.post(
        "/api/v1/users",
        headers=disp_h,
        json={"phone": phone, "password": "pass12345", "full_name": f"账号探针{phone[-4:]}",
              "role": role},
    )
    assert r.status_code in (200, 201), r.text
    return int(r.json()["id"])


def _token_version(db_session, uid: int) -> int:
    db_session.expire_all()
    u = db_session.get(User, uid)
    assert u is not None
    return int(getattr(u, "token_version", 0) or 0)


def _user_logs(db_session, uid: int, action: str) -> list[OperationLog]:
    """这个账号的某类审计（`change_content` 里带 `"user_id": <id>`）。

    ⚠️ 审计表的明细列叫 `change_content`（JSON 文本），不是 `change_payload`
    —— 后者是 `write_log(...)` 的**入参名**。
    """
    db_session.expire_all()
    rows = list(
        db_session.scalars(select(OperationLog).where(OperationLog.action == action)).all()
    )
    return [r for r in rows if f'"user_id": {uid}' in (r.change_content or "")]


@pytest.mark.dispatcher
@pytest.mark.integration
def test_删号与恢复都要撤销会话且启用不是恢复(
    client: TestClient, db_session, token_dispatcher: str
) -> None:
    h = auth_headers(token_dispatcher)
    uid = _mk_account(client, h, "13700001234")

    before = _token_version(db_session, uid)
    assert client.delete(f"/api/v1/users/{uid}", headers=h).status_code == 204
    after_del = _token_version(db_session, uid)
    assert after_del > before, (
        "删号必须递增 token_version 并断长连接 —— 否则那条已经建起来的 socket 继续收推送"
    )

    # ① 「启用」不许冒充「恢复」：号码已经释放，启用之后拿原号码登不进去
    bad = client.patch(f"/api/v1/users/{uid}", headers=h, json={"is_active": True})
    assert bad.status_code == 400, (
        f"删掉的账号用「启用」改成 True 必须被拒（实际 {bad.status_code}）—— "
        "界面会报'已启用'而人登不进去"
    )
    assert "回收站" in bad.json()["detail"] and "恢复" in bad.json()["detail"], bad.json()["detail"]

    # ② 恢复：号码还原 + 会话再撤销一次（删除前签发的旧令牌不许复活）
    r = client.post(f"/api/v1/users/{uid}/restore", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["phone"] == "13700001234", r.json()
    assert _token_version(db_session, uid) > after_del, "恢复也必须撤销一次会话"

    # 现在「启用」这条路不再被拦（号码是好的，他不是回收站里的账号）
    assert client.patch(f"/api/v1/users/{uid}", headers=h, json={"is_active": False}).status_code == 200
    assert client.patch(f"/api/v1/users/{uid}", headers=h, json={"is_active": True}).status_code == 200


@pytest.mark.dispatcher
@pytest.mark.integration
def test_改密码与身份互换必须留痕(
    client: TestClient, db_session, token_dispatcher: str
) -> None:
    h = auth_headers(token_dispatcher)
    uid = _mk_account(client, h, "13700005678", role="driver")

    r = client.patch(f"/api/v1/users/{uid}", headers=h, json={"password": "brandnew123"})
    assert r.status_code == 200, r.text
    logs = _user_logs(db_session, uid, "USER_UPDATE")
    assert logs, "只改密码也必须写一行审计（身份级动作）"
    blob = (logs[-1].change_content or "")
    assert "password" in blob and "已重置" in blob, f"审计里要说清改的是密码：{blob[:200]}"
    assert "brandnew123" not in blob, "⛔ 密码本身绝不许进审计"

    n_before = len(_user_logs(db_session, uid, "USER_UPDATE"))
    sw = client.post(f"/api/v1/users/{uid}/swap-shipper-driver", headers=h)
    assert sw.status_code == 200, sw.text
    assert len(_user_logs(db_session, uid, "USER_UPDATE")) == n_before + 1, (
        "货主↔司机身份互换必须留痕（它会改变他能看到的数据范围与账目归属）"
    )
