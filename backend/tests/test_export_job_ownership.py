"""导出任务的**归属闸**：查询与下载必须是同一套（2026-09-24 第 19 轮 C7-2）。

## 抓到的形状
`GET /export-jobs/{id}` 与 `GET /export-jobs/{id}/download` 各写了一份归属校验，
而**下载那一份对派单员是空的**：

```python
elif role == UserRole.DISPATCHER.value:
    if not role_has_permission(role, Permission.LEDGER_EDIT):   # ← 恒真
        raise HTTPException(403, "无权访问")
```

`core/rbac.py:145-147` 明确写着"派单员为最高业务权限：通过 `require_permission` 校验时
**一律放行**" —— 所以在**函数体内**用 `role_has_permission(role, X)` 判派单员，
等于写了一句永远不成立的 if。后果是同一个任务对派单员 B：
`GET` 是 403、`/download` 却是 200 → 他能把**另一个派单员给别的货主导出的整本账**拖走
（账本里有货主名、商品、单价、总额、订单号）。

判据只能是"**这个任务是他建的** 或 **这本账就是他的**"（与查询端点同源）：
`_ensure_export_job_visible()` 一处实现，两个端点共用。
"""

from __future__ import annotations

from datetime import date

from tests.conftest import auth_headers


def _job(db_session, *, creator_id: int, shipper_id: int):
    from app.models.export_job import LedgerExportJob

    job = LedgerExportJob(
        created_by_id=creator_id,
        shipper_id=shipper_id,
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
        kind="ledger",
    )
    db_session.add(job)
    db_session.commit()
    return job


def _second_dispatcher(db_session):
    """另一个派单员账号（同角色、不同人）—— 越权的那一格就靠他。"""
    import uuid

    from app.models import User
    from app.models.enums import UserRole
    from app.services.auth_service import issue_token

    phone = "139" + uuid.uuid4().hex[:8]
    u = User(
        phone=phone,
        full_name="越权探针派单员",
        username=phone,
        password_hash="x",
        role=UserRole.DISPATCHER,
        is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    return u, issue_token(u)


def test_另一个派单员不能下载别人的导出(client, db_session, users, token_dispatcher):
    """**这条是本轮那个洞的确证**：查询 403、下载 200（同一个任务、同一个人）。"""
    other, other_token = _second_dispatcher(db_session)
    job = _job(db_session, creator_id=users["dispatcher"].id, shipper_id=users["shipper"].id)

    # 查询：本来就挡着（403）
    q = client.get(f"/api/v1/ledger/export-jobs/{job.id}", headers=auth_headers(other_token))
    assert q.status_code == 403, q.text

    # 下载：**必须同样挡着** —— 原来这里是 200（闸对派单员恒真）
    d = client.get(f"/api/v1/ledger/export-jobs/{job.id}/download", headers=auth_headers(other_token))
    assert d.status_code == 403, (
        f"派单员 B 拿到了派单员 A 给别的货主导出的账本（HTTP {d.status_code}）—— "
        "`role_has_permission(role, …)` 对派单员恒真是空条件，归属校验得比『是不是他建的』"
    )


def test_建这个任务的人自己仍然能查能下(client, db_session, users, token_dispatcher):
    """反向对照：别把归属闸改宽到"连本人也挡住"。"""
    h = auth_headers(token_dispatcher)
    job = _job(db_session, creator_id=users["dispatcher"].id, shipper_id=users["shipper"].id)
    assert client.get(f"/api/v1/ledger/export-jobs/{job.id}", headers=h).status_code == 200


def test_这本账的主人也能查(client, db_session, users, token_shipper, token_dispatcher):
    """货主看自己那本账的导出任务 —— 归属口径里 `shipper_id == 他` 也算。"""
    h = auth_headers(token_dispatcher)
    job = _job(db_session, creator_id=users["dispatcher"].id, shipper_id=users["shipper"].id)
    r = client.get(f"/api/v1/ledger/export-jobs/{job.id}", headers=auth_headers(token_shipper))
    assert r.status_code == 200, r.text
    assert job.id == r.json()["id"]


def test_别人的账连查都查不到(client, db_session, users, token_shipper, token_dispatcher):
    """货主 A 不许看**货主 B 的**导出任务（这是原来就有的那一半，防止被改坏）。"""
    other, _ = _second_dispatcher(db_session)   # 借一个"别的用户"当另一个货主
    job = _job(db_session, creator_id=users["dispatcher"].id, shipper_id=other.id)
    assert client.get(
        f"/api/v1/ledger/export-jobs/{job.id}", headers=auth_headers(token_shipper)
    ).status_code == 403
