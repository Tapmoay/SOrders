"""车辆分类名册（`/vehicle-categories`，2026-10-05）：改名级联、有车挂着拒绝删、排序整份提交、
以及「分类与车型/车身型式是三件事」。

用户 2026-10-05 原话：

> 「还有我们的账户管理司机管理货主管理批发商管理。车辆管理……在这个位置也加个分类，
>  默认是显示，全部，同样也是左边侧边栏，然后左边侧边栏同样也是可以新增分类的，
>  那个左边侧分栏的底下，凡是跟地点是同样的」

这里盯的是四件不说就会踩的事：
1. **归属那一格是字符串**（`vehicles.category`），不是名册 id —— 名册改名要**级联**；
2. **「在用」包含停用的车**（车不软删，停用的车照样挂着分类；删分类会把它变成未分类）
   —— 与账号那边「回收站不算在用」的口径**故意相反**，各自对应各自的删除语义；
3. **分类不参与任何计费/匹配**：改分类**不许**动 `vehicle_type`（计费口径）与 `body_type`；
4. 只有派单员能改名册（门是 `Permission.USER_MANAGE`，rbac 里只有 dispatcher 有），
   但**读**只要登录。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import OperationAction, OperationLog, Vehicle
from tests.conftest import auth_headers


def _mk_vehicle(client, headers, *, plate: str, category: str = "", vehicle_type: str = "small"):
    """登记一辆车（`POST /api/v1/vehicles`）。"""
    return client.post(
        "/api/v1/vehicles",
        headers=headers,
        json={"plate_no": plate, "vehicle_type": vehicle_type, "category": category},
    )


def _roster(client, headers) -> list[dict]:
    return client.get("/api/v1/vehicle-categories", headers=headers).json()


def _find(client, headers, name: str) -> dict | None:
    return next((c for c in _roster(client, headers) if c["name"] == name), None)


def test_建车时顺手建分类并进名册(client, token_dispatcher):
    """名册里没有的分类下建车 → 分类自动进名册（排到最后），条数是 1。"""
    h = auth_headers(token_dispatcher)
    name = "探针-顺手建车辆分类"
    assert _find(client, h, name) is None, "探针名撞上上一轮跑剩下的了，换个名字"

    r = _mk_vehicle(client, h, plate="沪A00001", category=name)
    assert r.status_code in (200, 201), r.text
    assert r.json()["category"] == name

    row = _find(client, h, name)
    assert row is not None, [c["name"] for c in _roster(client, h)]
    assert row["vehicle_count"] == 1
    others = [c["sort_order"] for c in _roster(client, h) if c["id"] != row["id"]]
    assert not others or row["sort_order"] >= max(others)


def test_改车分类也顺手补名册(client, token_dispatcher):
    """把已有车辆改成一个新分类名 → 同样进名册（编辑与新建同一条规矩）。"""
    h = auth_headers(token_dispatcher)
    name = "探针-改出来车辆分类"
    made = _mk_vehicle(client, h, plate="沪A00002")
    assert made.status_code in (200, 201), made.text
    assert made.json()["category"] == ""

    patched = client.patch(
        f"/api/v1/vehicles/{made.json()['id']}", headers=h, json={"category": name}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["category"] == name
    assert _find(client, h, name) is not None


def test_改名级联改掉挂着的车(client, db_session: Session, token_dispatcher):
    """改分类名 → 同一事务里把那些车的 category 也改掉（含**停用**的车）。"""
    h = auth_headers(token_dispatcher)
    old = "探针-车辆改名前"
    new = "探针-车辆改名后"
    a = _mk_vehicle(client, h, plate="沪A00003", category=old)
    b = _mk_vehicle(client, h, plate="沪A00004", category=old)
    assert a.status_code in (200, 201) and b.status_code in (200, 201), (a.text, b.text)
    assert client.patch(
        f"/api/v1/vehicles/{b.json()['id']}", headers=h, json={"is_active": False}
    ).status_code == 200

    row = _find(client, h, old)
    assert row is not None, _roster(client, h)
    r = client.patch(f"/api/v1/vehicle-categories/{row['id']}", headers=h, json={"name": new})
    assert r.status_code == 200, r.text

    db_session.expire_all()
    assert db_session.get(Vehicle, a.json()["id"]).category == new, "活着的车没跟着改名"
    assert db_session.get(Vehicle, b.json()["id"]).category == new, "停用的车没跟着改名"
    assert db_session.query(Vehicle).filter(Vehicle.category == old).count() == 0


def test_停用的车也算在用所以删不掉分类(client, token_dispatcher):
    """停用（`is_active=False`）的车照样挂着分类 —— 删分类会把它变成未分类，所以拒绝。

    ⚠️ 与账号那边**故意相反**：账号删除是软删（号码带 `_del{id}` 后缀），回收站里的不算在用；
    车辆没有软删，停用只是「不派它」，它仍然属于某一类。
    """
    h = auth_headers(token_dispatcher)
    name = "探针-车辆停用不算空闲"
    made = _mk_vehicle(client, h, plate="沪A00005", category=name)
    assert made.status_code in (200, 201), made.text
    vid = made.json()["id"]
    assert client.patch(f"/api/v1/vehicles/{vid}", headers=h, json={"is_active": False}).status_code == 200

    row = _find(client, h, name)
    assert row is not None and row["vehicle_count"] == 1, row
    r = client.delete(f"/api/v1/vehicle-categories/{row['id']}", headers=h)
    assert r.status_code == 400, r.text
    assert "1 辆车" in r.json()["detail"], r.json()["detail"]


def test_空闲分类能删掉(client, token_dispatcher):
    """没有车挂着的分类能删（204），删完从名册里消失。"""
    h = auth_headers(token_dispatcher)
    name = "探针-车辆空闲分类"
    made = client.post("/api/v1/vehicle-categories", headers=h, json={"name": name})
    assert made.status_code == 201, made.text
    cid = made.json()["id"]
    assert _find(client, h, name) is not None
    assert client.delete(f"/api/v1/vehicle-categories/{cid}", headers=h).status_code == 204
    assert _find(client, h, name) is None


def test_排序必须整份提交(client, token_dispatcher):
    """只传一部分 → 400 并点名少了几个；整份倒过来 → 真的按这个顺序返回。"""
    h = auth_headers(token_dispatcher)
    client.post("/api/v1/vehicle-categories", headers=h, json={"name": "探针-车辆排序A"})
    client.post("/api/v1/vehicle-categories", headers=h, json={"name": "探针-车辆排序B"})
    cats = _roster(client, h)
    assert len(cats) >= 2, cats
    ids = [c["id"] for c in cats]

    partial = client.post("/api/v1/vehicle-categories/reorder", headers=h, json={"ids": ids[:1]})
    assert partial.status_code == 400, partial.text
    assert "少了" in partial.json()["detail"], partial.json()["detail"]

    flipped = list(reversed(ids))
    ok = client.post("/api/v1/vehicle-categories/reorder", headers=h, json={"ids": flipped})
    assert ok.status_code == 200, ok.text
    assert [c["id"] for c in ok.json()] == flipped


def test_重名分类被拒绝(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    name = "探针-车辆重名"
    assert client.post("/api/v1/vehicle-categories", headers=h, json={"name": name}).status_code == 201
    again = client.post("/api/v1/vehicle-categories", headers=h, json={"name": name})
    assert again.status_code == 409, again.text
    assert name in again.json()["detail"]


def test_空名被拒绝(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    r = client.post("/api/v1/vehicle-categories", headers=h, json={"name": "   "})
    assert r.status_code == 422, r.text
    assert "不能为空" in r.text


def test_不存在的分类编号是404(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    r = client.patch("/api/v1/vehicle-categories/999999", headers=h, json={"name": "不存在"})
    assert r.status_code == 404, r.text
    assert client.delete("/api/v1/vehicle-categories/999999", headers=h).status_code == 404


def test_非派单员改不动名册但读得到(client, token_shipper, token_driver):
    """货主与司机：读 200、写 403。"""
    sh = auth_headers(token_shipper)
    dr = auth_headers(token_driver)
    assert client.get("/api/v1/vehicle-categories", headers=sh).status_code == 200
    assert client.get("/api/v1/vehicle-categories", headers=dr).status_code == 200
    for h in (sh, dr):
        assert client.post("/api/v1/vehicle-categories", headers=h, json={"name": "越权"}).status_code == 403


def test_分类不参与计费改分类不动车型(client, token_dispatcher):
    """改分类**只**动分组：`vehicle_type`（计费口径）与 `body_type` 一个字都不许变。

    这条防的是「改个分组名把运费改了」那类事故 —— 分类是纯展示维度。
    """
    h = auth_headers(token_dispatcher)
    made = _mk_vehicle(client, h, plate="沪A00006", vehicle_type="trailer")
    assert made.status_code in (200, 201), made.text
    before = made.json()
    assert before["vehicle_type"] == "trailer"

    patched = client.patch(
        f"/api/v1/vehicles/{before['id']}", headers=h, json={"category": "探针-车辆计费无关"}
    )
    assert patched.status_code == 200, patched.text
    after = patched.json()
    assert after["category"] == "探针-车辆计费无关"
    assert after["vehicle_type"] == before["vehicle_type"], "改分类把车型改了（车型是计费口径）"
    assert after["body_type"] == before["body_type"]
    assert after["attrs"] == before["attrs"]


def test_两个写动作都写审计日志(client, db_session: Session, token_dispatcher):
    """建类 / 删类都要留痕（与商品分类同一套动作码规矩）。"""
    h = auth_headers(token_dispatcher)
    name = "探针-车辆审计"
    made = client.post("/api/v1/vehicle-categories", headers=h, json={"name": name})
    assert made.status_code == 201, made.text
    assert client.delete(f"/api/v1/vehicle-categories/{made.json()['id']}", headers=h).status_code == 204

    kinds = [
        db_session.query(OperationLog)
        .filter(OperationLog.action == a)
        .filter(OperationLog.change_content.like(f"%{name}%"))
        .count()
        for a in (
            OperationAction.VEHICLE_CATEGORY_UPSERT,
            OperationAction.VEHICLE_CATEGORY_DELETE,
        )
    ]
    assert all(n >= 1 for n in kinds), kinds
