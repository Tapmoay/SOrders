"""车辆台账 / 司机绑定（v3.44，2026-09-18）。

这一份盯的是用户原话里那句「司机的车辆绑定，App 端做不到」背后的两条**后端缺陷**：

1. `PATCH /vehicles/{id}` **不查车牌重复**（只有 `POST` 查）→ 可以把一辆车改成
   另一个已存在的车牌，两台车同号，而"哪台是哪台"再也分不出来。
2. `driver_id = null` 被 `if body.driver_id is not None` **静默忽略** → **解绑司机做不到**：
   用户说「把 A12345 从张三名下拿掉」，接口要么换成别人，要么什么都不做。
   而且它**不报错**——界面照旧显示"已保存"。

判据必须落在"两种语义真的分得开"上：**没传这个键 = 不动**，**显式传 null = 解绑**，
**专用入口缺省 = 解绑**。三者混掉任意一个，用户就会遇到一次"我明明点了解绑"。
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.models import OperationLog, User, Vehicle
from app.models.enums import OperationAction
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _reset_vehicles(db_session):
    """每个用例跑完把车辆表与绑定恢复原状。

    ## 为什么必须有（本项目已经栽过一次同类）
    测试库是**整个会话共用的一个文件**，而接口调用会 `db.commit()` ——
    "我建的那台车"会留在库里，别的用例（比如"车辆列表应该有 1 台"）就会莫名其妙地红。
    上一轮 `test_product_catalog.py` 正是这么把 7 个毫不相干的用例弄红的，
    所以这一条从第一版就带上：**先记下原有车辆及其绑定，跑完删掉新增的、恢复原有的**。
    """
    before = {v.id: v.driver_id for v in db_session.scalars(select(Vehicle)).all()}
    yield
    db_session.rollback()
    for v in db_session.scalars(select(Vehicle)).all():
        if v.id not in before:
            db_session.delete(v)
        else:
            v.driver_id = before[v.id]
    db_session.commit()


def _mk_vehicle(client, token, plate: str, vt: str = "trailer", driver_id=None):
    body: dict = {"plate_no": plate, "vehicle_type": vt}
    if driver_id is not None:
        body["driver_id"] = driver_id
    r = client.post("/api/v1/vehicles", json=body, headers=auth_headers(token))
    assert r.status_code == 200, r.text
    return r.json()


def _veh(db_session, vid: int) -> Vehicle:
    db_session.expire_all()
    return db_session.get(Vehicle, vid)


def _actions(db_session, action: OperationAction) -> list[OperationLog]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(OperationLog).where(OperationLog.action == action.value).order_by(OperationLog.id)
        )
    )


# ------------------------------------------------------------------ ① 车牌查重


def test_create_rejects_duplicate_plate(client, token_dispatcher):
    _mk_vehicle(client, token_dispatcher, "测A00001")
    r = client.post(
        "/api/v1/vehicles",
        json={"plate_no": "测A00001", "vehicle_type": "trailer"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 400
    assert "已经被另一辆车用了" in r.json()["detail"]


def test_patch_rejects_plate_taken_by_another_vehicle(client, token_dispatcher, db_session):
    """**修掉的缺陷 1**：`PATCH` 原来不查重，两台车可以同号。"""
    a = _mk_vehicle(client, token_dispatcher, "测A00002")
    b = _mk_vehicle(client, token_dispatcher, "测A00003")
    r = client.patch(
        f"/api/v1/vehicles/{b['id']}",
        json={"plate_no": "测A00002"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 400, "改成别人已经在用的车牌必须被拦下来"
    assert "已经被另一辆车用了" in r.json()["detail"]
    # 真正要断言的是**库里没被改掉**（只断言状态码的话，一个"先改后报错"的实现也能过）
    assert _veh(db_session, b["id"]).plate_no == "测A00003"
    assert _veh(db_session, a["id"]).plate_no == "测A00002"


def test_patch_does_not_collide_with_itself(client, token_dispatcher, db_session):
    """改车型时也会带上同一个车牌 → **不能自己撞自己**。

    这条是查重"排除自己"的判据：忘了排除的话，每次改车型都会得到
    「该车牌已存在」，而车牌根本没变——功能看起来坏了，原因却看不出。
    """
    v = _mk_vehicle(client, token_dispatcher, "测A00004")
    r = client.patch(
        f"/api/v1/vehicles/{v['id']}",
        json={"plate_no": "测A00004", "vehicle_type": "large"},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    assert r.json()["vehicle_type"] == "large"
    assert _veh(db_session, v["id"]).plate_no == "测A00004"


def test_patch_rejects_blank_plate(client, token_dispatcher):
    v = _mk_vehicle(client, token_dispatcher, "测A00005")
    r = client.patch(
        f"/api/v1/vehicles/{v['id']}", json={"plate_no": "   "}, headers=auth_headers(token_dispatcher)
    )
    assert r.status_code == 400
    assert "请输入车牌号" in r.json()["detail"]


def test_patch_rejects_unknown_vehicle_type(client, token_dispatcher):
    v = _mk_vehicle(client, token_dispatcher, "测A00006")
    r = client.patch(
        f"/api/v1/vehicles/{v['id']}", json={"vehicle_type": "飞机"}, headers=auth_headers(token_dispatcher)
    )
    assert r.status_code == 400
    assert "车型只能是" in r.json()["detail"]


# ------------------------------------------------------- ② 解绑：三种语义必须分得开


def test_patch_explicit_null_unbinds_driver(client, token_dispatcher, users, db_session):
    """**修掉的缺陷 2**：显式传 `null` = 解绑。"""
    v = _mk_vehicle(client, token_dispatcher, "测A00007", driver_id=users["driver"].id)
    assert _veh(db_session, v["id"]).driver_id == users["driver"].id

    r = client.patch(
        f"/api/v1/vehicles/{v['id']}", json={"driver_id": None}, headers=auth_headers(token_dispatcher)
    )
    assert r.status_code == 200, r.text
    assert r.json()["driver_id"] is None
    assert _veh(db_session, v["id"]).driver_id is None, "显式 null 必须真的解绑"


def test_patch_without_driver_key_keeps_driver(client, token_dispatcher, users, db_session):
    """部分更新语义**没被破坏**：没传这个键 = 不动司机。

    这条是上面那条的护栏——如果"没传"也被当成解绑，
    那么"改个车型"会顺手把司机拿掉，而卡片上只写着车型变了。
    """
    v = _mk_vehicle(client, token_dispatcher, "测A00008", driver_id=users["driver"].id)
    r = client.patch(
        f"/api/v1/vehicles/{v['id']}", json={"vehicle_type": "small"}, headers=auth_headers(token_dispatcher)
    )
    assert r.status_code == 200, r.text
    assert _veh(db_session, v["id"]).driver_id == users["driver"].id, "没点名司机就不许动他"


def test_dedicated_endpoint_binds_and_unbinds(client, token_dispatcher, users, db_session):
    """专用入口（安卓端唯一发得出"解绑"的形状）：带编号 = 绑，缺省 = 解绑。"""
    v = _mk_vehicle(client, token_dispatcher, "测A00009")

    r = client.post(
        f"/api/v1/vehicles/{v['id']}/driver",
        json={"driver_id": users["driver"].id},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    assert r.json()["driver_id"] == users["driver"].id
    assert r.json()["driver_name"] == users["driver"].full_name

    r = client.post(f"/api/v1/vehicles/{v['id']}/driver", json={}, headers=auth_headers(token_dispatcher))
    assert r.status_code == 200, r.text
    assert r.json()["driver_id"] is None
    assert _veh(db_session, v["id"]).driver_id is None


def test_bind_rejects_non_driver(client, token_dispatcher, users, db_session):
    """绑给货主/派单员 → 400 中文（车上挂着一个永远不出车的人，比报错糟得多）。"""
    v = _mk_vehicle(client, token_dispatcher, "测A00010")
    r = client.post(
        f"/api/v1/vehicles/{v['id']}/driver",
        json={"driver_id": users["shipper"].id},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 400
    assert "不是司机账号" in r.json()["detail"]
    assert _veh(db_session, v["id"]).driver_id is None


def test_bind_rejects_missing_driver(client, token_dispatcher):
    v = _mk_vehicle(client, token_dispatcher, "测A00011")
    r = client.post(
        f"/api/v1/vehicles/{v['id']}/driver",
        json={"driver_id": 987654321},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 404
    assert "未找到该司机" in r.json()["detail"]


def test_dedicated_endpoint_404_on_unknown_vehicle(client, token_dispatcher):
    r = client.post("/api/v1/vehicles/987654321/driver", json={}, headers=auth_headers(token_dispatcher))
    assert r.status_code == 404
    assert "车辆不存在" in r.json()["detail"]


# ------------------------------------------------------------------ ③ 留痕与权限


def _logs_of(db_session, action: OperationAction, **match) -> list[dict]:
    """这个动作码下、JSON 里各字段都对得上的留痕。

    ⚠️ **不许按 `vehicle_id` 认"这台车"**：清理用的 fixture 会把测试建的车删掉，
    而 SQLite 的 rowid **删完会重用** —— 于是每个用例里的"新车" id 都是 1，
    `vehicle_id=1` 把十几个用例的日志全算成同一台车的（实测：断言 2 条实得 15 条）。
    车牌的每个用例都不同，用它认才是准的。
    """
    out = []
    for x in _actions(db_session, action):
        try:
            d = json.loads(x.change_content or "{}")
        except ValueError:
            continue
        if all(d.get(k) == v for k, v in match.items()):
            out.append(d)
    return out


def test_driver_change_is_logged(client, token_dispatcher, users, db_session):
    """绑/解绑各留一条，能回答"谁把车从张三名下拿走了"。"""
    v = _mk_vehicle(client, token_dispatcher, "测A00012")
    client.post(
        f"/api/v1/vehicles/{v['id']}/driver",
        json={"driver_id": users["driver"].id},
        headers=auth_headers(token_dispatcher),
    )
    client.post(f"/api/v1/vehicles/{v['id']}/driver", json={}, headers=auth_headers(token_dispatcher))

    rows = _logs_of(db_session, OperationAction.VEHICLE_DRIVER_SET, plate_no="测A00012")
    assert len(rows) == 2, f"绑与解绑各应留一条痕，实际 {len(rows)}"
    assert rows[0]["op"] == "attach" and rows[0]["after_driver"] == users["driver"].full_name
    assert rows[1]["op"] == "detach" and rows[1]["after_driver"] is None


def test_plate_change_is_logged(client, token_dispatcher, db_session):
    v = _mk_vehicle(client, token_dispatcher, "测A00013")
    client.patch(
        f"/api/v1/vehicles/{v['id']}", json={"plate_no": "测A00014"}, headers=auth_headers(token_dispatcher)
    )
    # 建档那条日志里车牌是**改之前**的；改动那条里是**改之后**的（日志写的是"现在这台车叫什么"）
    assert len(_logs_of(db_session, OperationAction.VEHICLE_UPSERT, plate_no="测A00013", op="create")) == 1
    rows = _logs_of(db_session, OperationAction.VEHICLE_UPSERT, plate_no="测A00014", op="update")
    assert len(rows) == 1
    assert "测A00013 → 测A00014" in rows[0]["changes"][0]


def test_no_op_patch_writes_no_log(client, token_dispatcher, db_session):
    """把车型改成**它现在的值** → 不写日志（审计页不该被"什么都没变"的记录淹掉）。"""
    v = _mk_vehicle(client, token_dispatcher, "测A00015", vt="trailer")
    before = len(_actions(db_session, OperationAction.VEHICLE_UPSERT))
    r = client.patch(
        f"/api/v1/vehicles/{v['id']}", json={"vehicle_type": "trailer"}, headers=auth_headers(token_dispatcher)
    )
    assert r.status_code == 200
    assert len(_actions(db_session, OperationAction.VEHICLE_UPSERT)) == before


def test_unbind_already_unbound_writes_no_log(client, token_dispatcher, db_session):
    """对一辆**本来就没绑司机**的车再解绑一次 → 200，但**不留痕**。

    不拦的话审计页会多出一行「司机 （未绑） → （未绑）」——
    真改动混在这种记录里就分不出哪条有效了（"没变不记"这条规矩在 §17 也踩过）。
    """
    v = _mk_vehicle(client, token_dispatcher, "测A00017")
    before = len(_actions(db_session, OperationAction.VEHICLE_DRIVER_SET))
    r = client.post(f"/api/v1/vehicles/{v['id']}/driver", json={}, headers=auth_headers(token_dispatcher))
    assert r.status_code == 200
    assert r.json()["driver_id"] is None
    assert len(_actions(db_session, OperationAction.VEHICLE_DRIVER_SET)) == before


def test_unbind_already_unbound_writes_no_log(client, token_dispatcher, db_session):
    """对一辆**本来就没绑司机**的车再解绑一次 → 200，但**不留痕**。

    不拦的话审计页会多出一行「司机 （未绑） → （未绑）」——
    真改动混在这种记录里，翻起来就分不出哪条是有效的（同一类问题在 §17 的"没变不记"里踩过）。
    """
    v = _mk_vehicle(client, token_dispatcher, "测A00017")
    before = len(_actions(db_session, OperationAction.VEHICLE_DRIVER_SET))
    r = client.post(f"/api/v1/vehicles/{v['id']}/driver", json={}, headers=auth_headers(token_dispatcher))
    assert r.status_code == 200
    assert r.json()["driver_id"] is None
    assert len(_actions(db_session, OperationAction.VEHICLE_DRIVER_SET)) == before


def test_only_dispatcher_can_bind(client, token_shipper, token_dispatcher, users):
    v = _mk_vehicle(client, token_dispatcher, "测A00016")
    r = client.post(
        f"/api/v1/vehicles/{v['id']}/driver",
        json={"driver_id": users["driver"].id},
        headers=auth_headers(token_shipper),
    )
    assert r.status_code == 403, "绑车是派单员的事"
