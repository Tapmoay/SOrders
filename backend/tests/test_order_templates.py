"""预订单（订单模板）：空运费 ≠ 0 运费、部分更新、软删与恢复、审计留痕、权限。

## 为什么这几条必须钉住（每一条都是"不报错但会错"的形状）
1. **`freight_fee` 空与 `0` 是两件事**：前者是"这单不预设运费（下单时按规则算）"，
   后者是"免运费"。把空当 0 的后果是**每一张没填运费的预设单都变成免运费单** ——
   一键下单时钱就少收了，而界面上两个都显示"¥0.00"。
2. **部分更新不许把没提到的键覆盖成默认值**：`PATCH` 只传 `name` 时，
   货主/地址/行货/运费必须原样不动（写回默认值的表现是"改个名字把预设的商品清空了"）。
3. **`shipper_id` 必须能清空**（键出现就按给的值写）：从"固定货主"改回"下单时再选"。
4. **删了一律软删 + 能恢复**（用户定的硬规矩），并且**回收站里的预设单改不了**。
5. **每次写都要留痕**：预设单会变成真订单，"谁改的"必须查得到。

## 一条刻意钉住的**不做**：不校验商品是否存在
预设单只是一张便签 —— 商品可能今天建、明天改名、后天下架，而预设单要一直能存着。
真校验在下单那一刻（`POST /orders` 那条路本来就会校验商品与库存）。
⚠️ 这条行为有测试钉着（`test_预设单不校验商品是否存在`）：哪天要改成"存的时候就校验"，
请连着这条测试一起改，别让它变成"文档说校验、代码不校验"。
"""
from __future__ import annotations

import json

from sqlalchemy import select

from app.models import OperationLog
from tests.conftest import auth_headers

BASE = "/api/v1/order-templates"


def _mk(client, h, name: str, **over):
    body = {
        "name": name,
        "address": "惠风东三路40号",
        "receiver_name": "小张",
        "receiver_phone": "13512345678",
        "lines": [
            {"product_id": 9001, "name": "红富士苹果", "unit": "件", "qty": 6},
            {"product_id": 9002, "name": "赣南脐橙", "unit": "箱", "qty": 2},
        ],
    }
    body.update(over)
    r = client.post(BASE, json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _logs(db, action: str) -> list[dict]:
    rows = db.scalars(select(OperationLog).where(OperationLog.action == action)).all()
    return [json.loads(r.change_content or "{}") for r in rows]


def _ids(client, h) -> list[int]:
    """当前列表里的 id 顺序（⚠️ 测试库在**同一次运行里是累积的**：别的用例建的预设单还在，
    所以任何"整张列表等于什么"的断言都会假红 —— 一律用"相对顺序/在不在"来判）。"""
    return [r["id"] for r in client.get(BASE, headers=h).json()]


def test_建一张预设单_行货与字段都对(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    t = _mk(client, h, "永盛食品每周单")
    assert t["name"] == "永盛食品每周单"
    assert [ln["name"] for ln in t["lines"]] == ["红富士苹果", "赣南脐橙"]
    assert [ln["qty"] for ln in t["lines"]] == [6, 2]
    assert t["shipper_id"] is None and t["shipper_name"] is None
    # ⚠️ 没填运费 = **不预设**（None），不是 "0.00"
    assert t["freight_fee"] is None
    # 列表里立刻能看到（内容从列表那条路回来也要一模一样）
    row = next(r for r in client.get(BASE, headers=h).json() if r["id"] == t["id"])
    assert row["lines"] == t["lines"] and row["address"] == "惠风东三路40号"


def test_免运费与不预设是两件事(client, token_dispatcher):
    """`freight_fee="0"` → `"0.00"`（就是免运费）；不传/传空 → `None`（不预设）。"""
    h = auth_headers(token_dispatcher)
    free = _mk(client, h, "免运费单", freight_fee="0")
    none = _mk(client, h, "不预设运费单")
    blank = _mk(client, h, "空字符串运费单", freight_fee="")
    assert free["freight_fee"] == "0.00"
    assert none["freight_fee"] is None
    assert blank["freight_fee"] is None, "空字符串也要当成「不预设」，不能悄悄变成 0"
    preset = _mk(client, h, "预设 38.5 的单", freight_fee="38.5")
    assert preset["freight_fee"] == "38.50", "金额出参一律两位小数"


def test_部分更新不许把没提到的键覆盖成默认值(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    t = _mk(client, h, "原始名", freight_fee="12.00", remark="留着")
    r = client.patch(f"{BASE}/{t['id']}", json={"name": "改过的名"}, headers=h)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["name"] == "改过的名"
    assert got["remark"] == "留着", "只改名不该把备注清掉"
    assert got["freight_fee"] == "12.00", "只改名不该把预设运费清掉"
    assert len(got["lines"]) == 2, "只改名不该把预设的商品行清掉"


def test_货主可以清空_也可以重新指定(client, token_dispatcher, token_shipper, db_session):
    """`shipper_id` 走 `model_fields_set`：**键出现就按给的值写**（null = 清空）。"""
    h = auth_headers(token_dispatcher)
    me = client.get("/api/v1/users/me", headers=auth_headers(token_shipper)).json()
    t = _mk(client, h, "指定货主", shipper_id=me["id"])
    assert t["shipper_id"] == me["id"] and t["shipper_name"]
    cleared = client.patch(f"{BASE}/{t['id']}", json={"shipper_id": None}, headers=h).json()
    assert cleared["shipper_id"] is None, "显式传 null 必须能把货主清掉（改回「下单时再选」）"
    again = client.patch(f"{BASE}/{t['id']}", json={"shipper_id": me["id"]}, headers=h).json()
    assert again["shipper_id"] == me["id"]


def test_不给货主时不许乱塞一个编号(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    bad = client.post(BASE, json={"name": "x", "shipper_id": 999999}, headers=h)
    assert bad.status_code == 400 and "货主" in bad.json()["detail"]


def test_同一个商品两行要拒绝_没有商品的行也要拒绝(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    dup = client.post(
        BASE,
        json={"name": "重复行", "lines": [
            {"product_id": 7, "name": "苹果", "qty": 1},
            {"product_id": 7, "name": "苹果", "qty": 2},
        ]},
        headers=h,
    )
    assert dup.status_code == 400 and "又出现了一次" in dup.json()["detail"]
    empty = client.post(BASE, json={"name": "空行", "lines": [{"qty": 3}]}, headers=h)
    # ⛔ 不许静默丢掉这一行：少一行货会在下单时变成"少订了一样"，两边都不报错
    assert empty.status_code == 400 and "没有选商品" in empty.json()["detail"]


def test_列表按常用度_用过的排前面(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    a = _mk(client, h, "先建的")
    b = _mk(client, h, "后建的")
    before = _ids(client, h)
    assert before.index(a["id"]) < before.index(b["id"]), "都没用过时：先建的在前"
    r = client.post(f"{BASE}/{b['id']}/use", headers=h)
    assert r.status_code == 200, r.text
    after = _ids(client, h)
    assert after.index(b["id"]) < after.index(a["id"]), "用过的那张要排到前面（2026-09-22 统一列表规则）"


def test_删除是软删_能恢复_回收站里改不了(client, token_dispatcher, db_session):
    h = auth_headers(token_dispatcher)
    t = _mk(client, h, "要删的预设单")
    assert client.delete(f"{BASE}/{t['id']}", headers=h).status_code == 204
    assert t["id"] not in _ids(client, h), "删掉的不该还出现在列表里"
    # 名字加了可见后缀（全项目软删同一形状），恢复时去掉
    from app.models import OrderTemplate

    row = db_session.get(OrderTemplate, t["id"])
    db_session.refresh(row)
    assert row.is_deleted and row.name.endswith(f"_del{t['id']}")
    # ⚠️ 回收站里的改不了：改了只会让用户以为改的是"现在在用的那一张"
    blocked = client.patch(f"{BASE}/{t['id']}", json={"name": "偷偷改"}, headers=h)
    assert blocked.status_code == 400 and "恢复" in blocked.json()["detail"]
    back = client.post(f"{BASE}/{t['id']}/restore", headers=h)
    assert back.status_code == 200, back.text
    assert back.json()["name"] == "要删的预设单", "恢复要还原原来的名字"
    assert t["id"] in _ids(client, h)


def test_预设单不校验商品是否存在(client, token_dispatcher):
    """**刻意不校验**（见文件头最后一条）：预设单是便签，真校验在下单那一刻。

    这条测试钉的是"行为与文档一致"。要改成存的时候就校验，请连着改这里与文件头。
    """
    h = auth_headers(token_dispatcher)
    t = _mk(client, h, "引用了不存在的商品", lines=[{"product_id": 424242, "name": "还没建的商品", "qty": 1}])
    assert t["lines"][0]["product_id"] == 424242


def test_每个写动作都留痕(client, token_dispatcher, db_session):
    h = auth_headers(token_dispatcher)
    t = _mk(client, h, "留痕探针")
    client.patch(f"{BASE}/{t['id']}", json={"remark": "改一下"}, headers=h)
    client.delete(f"{BASE}/{t['id']}", headers=h)
    client.post(f"{BASE}/{t['id']}/restore", headers=h)
    upserts = [x for x in _logs(db_session, "ORDER_TEMPLATE_UPSERT") if x.get("template_id") == t["id"]]
    assert [x["scope"] for x in upserts] == ["create", "update"], "建与改各要一条"
    assert _logs(db_session, "ORDER_TEMPLATE_DELETE"), "删要留痕"
    assert _logs(db_session, "ORDER_TEMPLATE_RESTORE"), "恢复要留痕"


def test_只有派单员能管预设单(client, token_shipper, token_driver):
    """用户：「这些功能**主要是给派单员做的**」—— 权限点 `ORDER_EDIT` 只在派单员那一格。"""
    for tok in (token_shipper, token_driver):
        h = auth_headers(tok)
        assert client.get(BASE, headers=h).status_code == 403
        assert client.post(BASE, json={"name": "越权"}, headers=h).status_code == 403
