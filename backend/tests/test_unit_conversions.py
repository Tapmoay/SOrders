"""单位换算这条链路（`/api/v1/unit-conversions`）—— 2026-09-24 用户要求。

用户原话：「我们的**货主和派单员**，他可以自动的设置单位，比如说一车等于 8 方……
我们再计算的时候或者是算账的时候会自动启动换算的功能，比如说我下的十车，
会有 **2 个数据**：第一个是 10 车，第 2 个则是 80 方。」

这一份盯的是**用户看得见**的几件事：
1. 建一条换算（1 车 = 8 方）读得回来，而且是**全库共用**（另一个角色也看得到 —— 同一张单
   在两个角色那儿必须是同一个数）；
2. 四类不合法的输入各给一句**能照着改的中文**（不是 500、也不是英文结构体）；
3. 删掉是**伪装删除**：回收站里看得到、能恢复；恢复时**要重新过冲突判据**；
4. 删掉再建同一条 → 那条被放回来（不是撞唯一键报 500）；
5. 司机没有这个功能（他不是下单、也不录单位的那个人）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete

from app.models import UnitConversion
from tests.conftest import auth_headers, get_test_session_factory


@pytest.fixture(autouse=True)
def _clean_unit_conversions():
    """每个用例跑完**把换算表清空**。

    ⚠️ 为什么必须自清理：`conftest.db_session` 的隔离只有 `session.rollback()` ——
    那只回滚**它自己那个 session**，而端点里的写是真的 `commit`（`get_db` 是另一个 session）。
    所以上一个用例建的「1 车 = 8 方」会留在库里，下一个用例再建同一条就是 409
    （本文件第一版就是这么红的：11 个用例里 10 个互相踩）。
    """
    yield
    session = get_test_session_factory()()
    try:
        session.execute(delete(UnitConversion))
        session.commit()
    finally:
        session.close()


def _create(client, token, f="车", t="方", factor="8", **kw):
    body = {"from_unit": f, "to_unit": t, "factor": factor}
    body.update(kw)
    return client.post("/api/v1/unit-conversions", json=body, headers=auth_headers(token))


def _list(client, token, **params):
    r = client.get("/api/v1/unit-conversions", params=params, headers=auth_headers(token))
    assert r.status_code == 200, r.text
    return r


def test_create_and_read_back(client, token_shipper):
    r = _create(client, token_shipper, remark="沙子按 8 方算")
    assert r.status_code == 201, r.text
    row = r.json()
    assert (row["from_unit"], row["to_unit"]) == ("车", "方")
    assert str(row["factor"]) in ("8", "8.0000")
    assert row["remark"] == "沙子按 8 方算"

    rows = _list(client, token_shipper).json()
    assert any(x["id"] == row["id"] for x in rows)


def test_conversions_are_shared_between_roles(client, token_shipper, token_dispatcher):
    """**全库共用**：货主建的换算，派单员也看得到（同一张单要显示同一个数）。"""
    row = _create(client, token_shipper).json()
    rows = _list(client, token_dispatcher).json()
    assert any(x["id"] == row["id"] for x in rows), "派单员看不到货主建的换算 —— 同一单会有两个数"


def test_driver_has_no_access(client, token_driver):
    """司机没有这个功能（他不下单、也不录单位）—— 进来会被角色门槛挡掉。"""
    r = client.get("/api/v1/unit-conversions", headers=auth_headers(token_driver))
    assert r.status_code == 403, r.text
    assert _create(client, token_driver).status_code == 403


def test_bad_input_gives_chinese(client, token_shipper):
    """四类不合法的输入都要给一句**能照着改的中文**。

    ⚠️ 状态码分两种，都是对的：判据抛 `ValueError` → 400；而"根本不是个数字"
    （`八`）在 pydantic 解析 `Decimal` 时就挂了 → 422，但全局异常处理器会把它翻成
    「factor：要填数字」（**不是**英文结构体）。所以这里只钉"有中文、说得清是哪一项"。
    """
    cases = [
        {"from_unit": "", "to_unit": "方", "factor": "8"},
        {"from_unit": "车", "to_unit": "车", "factor": "8"},
        {"from_unit": "车", "to_unit": "方", "factor": "0"},
        {"from_unit": "车", "to_unit": "方", "factor": "八"},
    ]
    for body in cases:
        r = client.post("/api/v1/unit-conversions", json=body, headers=auth_headers(token_shipper))
        assert r.status_code in (400, 422), f"{body} → {r.status_code} {r.text}"
        detail = r.json()["detail"]
        text = detail if isinstance(detail, str) else str(detail)
        assert any("\u4e00" <= ch <= "\u9fff" for ch in text), f"{body} 的报错里没有中文：{text}"


def test_one_source_unit_only(client, token_shipper):
    """一个源单位只能换算到一处 —— 否则「10 车 ≈ ?」没有唯一答案。"""
    assert _create(client, token_shipper, "车", "方", "8").status_code == 201
    r = _create(client, token_shipper, "车", "袋", "50")
    assert r.status_code == 409, r.text
    assert "1 车 = 8 方" in r.json()["detail"], "拒绝时必须点名挡住它的那一条"


def test_reverse_pair_is_rejected(client, token_shipper):
    assert _create(client, token_shipper, "车", "方", "8").status_code == 201
    r = _create(client, token_shipper, "方", "车", "0.125")
    assert r.status_code == 409, r.text
    assert "反过来" in r.json()["detail"]


def test_update_changes_factor_and_rejects_conflict(client, token_shipper):
    row = _create(client, token_shipper, "车", "方", "8").json()
    other = _create(client, token_shipper, "袋", "斤", "2").json()

    # 改换算率：8 → 10
    r = client.patch(
        f"/api/v1/unit-conversions/{row['id']}", json={"factor": "10"}, headers=auth_headers(token_shipper)
    )
    assert r.status_code == 200, r.text
    assert str(r.json()["factor"]) in ("10", "10.0000")

    # 把另一条改成同一个源单位 → 拒绝
    r = client.patch(
        f"/api/v1/unit-conversions/{other['id']}", json={"from_unit": "车"}, headers=auth_headers(token_shipper)
    )
    assert r.status_code == 409, r.text

    # 改自己（同一个源单位、只换目标单位）是允许的
    r = client.patch(
        f"/api/v1/unit-conversions/{row['id']}", json={"to_unit": "立方米"}, headers=auth_headers(token_shipper)
    )
    assert r.status_code == 200, r.text
    assert r.json()["to_unit"] == "立方米"


def test_delete_is_soft_and_restorable(client, token_shipper):
    row = _create(client, token_shipper, "车", "方", "8").json()

    assert client.delete(
        f"/api/v1/unit-conversions/{row['id']}", headers=auth_headers(token_shipper)
    ).status_code == 204
    assert all(x["id"] != row["id"] for x in _list(client, token_shipper).json()), "删了还在列表里"
    recycle = _list(client, token_shipper, deleted_only=True).json()
    assert any(x["id"] == row["id"] for x in recycle), "回收站里找不到 —— 那就没有恢复入口了"

    r = client.post(f"/api/v1/unit-conversions/{row['id']}/restore", headers=auth_headers(token_shipper))
    assert r.status_code == 200, r.text
    assert any(x["id"] == row["id"] for x in _list(client, token_shipper).json())


def test_restore_refuses_when_it_would_duplicate_the_source_unit(client, token_shipper):
    """删掉之后又建了一条同源单位的换算 → 恢复必须**如实拒绝**（否则"10 车 ≈ ?"有两个答案）。"""
    row = _create(client, token_shipper, "车", "方", "8").json()
    client.delete(f"/api/v1/unit-conversions/{row['id']}", headers=auth_headers(token_shipper))
    assert _create(client, token_shipper, "车", "袋", "50").status_code == 201

    r = client.post(f"/api/v1/unit-conversions/{row['id']}/restore", headers=auth_headers(token_shipper))
    assert r.status_code == 409, r.text
    assert "1 车 = 50 袋" in r.json()["detail"]


def test_recreate_after_delete_revives_the_same_row(client, token_shipper):
    """删掉再建同一条 → 把被删的那一行**放回来并改掉换算率**（不是撞唯一键报 500）。"""
    row = _create(client, token_shipper, "车", "方", "8").json()
    client.delete(f"/api/v1/unit-conversions/{row['id']}", headers=auth_headers(token_shipper))

    again = _create(client, token_shipper, "车", "方", "10").json()
    assert again["id"] == row["id"], "又建了一条新的 —— 库里会有两条同源单位的换算"
    assert str(again["factor"]) in ("10", "10.0000")
    assert len([x for x in _list(client, token_shipper).json() if x["from_unit"] == "车"]) == 1


def test_deleted_row_cannot_be_edited(client, token_shipper):
    """回收站里的行不许再被改（改了用户也看不见，而 200 会让他以为改的是另一条）。"""
    row = _create(client, token_shipper, "车", "方", "8").json()
    client.delete(f"/api/v1/unit-conversions/{row['id']}", headers=auth_headers(token_shipper))
    r = client.patch(
        f"/api/v1/unit-conversions/{row['id']}", json={"factor": "12"}, headers=auth_headers(token_shipper)
    )
    assert r.status_code == 400, r.text


def test_writes_are_logged(client, token_shipper, db_session):
    """换算率是"看起来像系统算的"那种数 —— 必须能回答是谁把它从 8 改成了 10。"""
    from sqlalchemy import select

    from app.models import OperationAction, OperationLog

    row = _create(client, token_shipper, "车", "方", "8").json()
    client.patch(
        f"/api/v1/unit-conversions/{row['id']}", json={"factor": "10"}, headers=auth_headers(token_shipper)
    )
    client.delete(f"/api/v1/unit-conversions/{row['id']}", headers=auth_headers(token_shipper))

    logs = db_session.scalars(
        select(OperationLog).where(
            OperationLog.action.in_(
                [
                    OperationAction.UNIT_CONVERSION_UPSERT,
                    OperationAction.UNIT_CONVERSION_DELETE,
                ]
            )
        )
    ).all()
    assert len(logs) >= 2, "建/改/删至少各要留一条痕"
