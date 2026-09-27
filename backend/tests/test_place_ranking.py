# -*- coding: utf-8 -*-
"""FEAT-0002 · 共享地点列表的**距离分档排序**（用户 2026-09-27：Q3 = 只排序、不合并）。

这批用例要挡住三件事，每一件都是"不报错但会骗人"的形状：

1. **档位边界**：≤1 / ≤10 / ≤50 / ≤100 米必须各归各档，边界值取小的那一档；
2. **没有坐标的行不许当 0 米** —— 折成 0.0 的话它们会跑到列表最前面，
   用户看到的是"这些点就在我附近"（而那些点**根本没有坐标**）；
3. **>100 米不许被提前**，而且"其余的"必须**保持原顺序**（原顺序 = 我自己的常用度 → 先创建）。

⛔ 与本文件成对的还有一条静态判据 `_tools/qa/_check_place_ranking.py`
（它管"合并半径有没有被误改成搜索半径"这类**代码形状**），两边都要过。
"""
from decimal import Decimal

import pytest

from app.models import Place
from app.services import place_service as ps


# ---------------------------------------------------------------- 纯函数：档位

@pytest.mark.parametrize(
    "meters,expect",
    [
        (0.0, 0), (0.5, 0), (1.0, 0),          # ≤1 米（边界含）
        (1.01, 1), (5.0, 1), (10.0, 1),        # ≤10 米
        (10.01, 2), (30.0, 2), (50.0, 2),      # ≤50 米
        (50.01, 3), (89.1, 3), (100.0, 3),     # ≤100 米
        (100.01, 4), (167.0, 4), (99999.0, 4), # **不优先**
    ],
)
def test_tier_boundaries(meters: float, expect: int):
    assert ps.tier_of(meters) == expect


def test_tiers_are_nested_and_ordered():
    """四档必须是**嵌套**的（≤1 ⊂ ≤10 ⊂ ≤50 ⊂ ≤100）—— 排序规则就建立在这上面。"""
    assert list(ps.NEAR_TIERS) == sorted(ps.NEAR_TIERS)
    assert ps.NEAR_METERS == ps.NEAR_TIERS[-1] == 100.0


def test_missing_coords_is_last_not_zero():
    """⛔ 没有坐标 **不是** 0 米 —— 它必须排在**所有**有坐标的行后面（含 >100 米的那些）。"""
    far = ps.rank_key(5000.0)
    unknown = ps.rank_key(None)
    assert unknown > far, "没有坐标的行被当成了'就在脚下'"
    assert unknown[0] == len(ps.NEAR_TIERS)


# ---------------------------------------------------------------- 端点：真排序

def _hdr(token: str) -> dict[str, str]:
    """鉴权头（`auth_headers` 是 conftest 里的**普通函数**，不是 fixture —— 实测踩过）。"""
    return {"Authorization": "Bearer " + token}


def _mk(db, name: str, lat: float, lng: float, by: int) -> Place:
    row = Place(
        name=name,
        detail_address=name + " 详细地址",
        lat=Decimal(str(lat)),
        lng=Decimal(str(lng)),
        source="dispatcher",
        created_by=by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_near_place_is_promoted_to_first(client, db_session, users, token_shipper):
    """**核心用例**：一个原本排在最后的点，站到它旁边之后必须被提到第一。

    ⚠️ 这条用例故意让"被提前的那个"**不是**原顺序第一名 —— 否则它恒过，
    证明不了任何事（2026-09-27 第一次手工验收就是这么空过的）。
    """
    uid = users["dispatcher"].id
    base_lat, base_lng = 23.0, 114.0
    first = _mk(db_session, "RANK 原第一名", base_lat, base_lng, uid)
    _mk(db_session, "RANK 中间", base_lat + 1.0, base_lng, uid)
    target = _mk(db_session, "RANK 原本最后", base_lat + 3.0, base_lng + 3.0, uid)

    before = client.get("/api/v1/places", headers=_hdr(token_shipper)).json()
    ids_before = [p["id"] for p in before]
    # ⚠️ 断言一律**相对 before**，不许拿绝对 id 比 —— 测试库是**同一个 worker 共用**的，
    #    前一个用例留下的行会排在前面（第一版就栽在这：断言 `ids_before[0] == first.id`）。
    assert first.id in ids_before and target.id in ids_before
    assert ids_before.index(target.id) > 0, "前置条件不成立：目标点本来就在第一（这条用例就白跑了）"

    # 站到目标点旁边 ≈5 米（≤10 米档）
    got = client.get(
        "/api/v1/places",
        params={"lat": float(target.lat) + 0.00005, "lng": float(target.lng)},
        headers=_hdr(token_shipper),
    ).json()
    ids_after = [p["id"] for p in got]

    assert ids_after[0] == target.id, "站过去之后它没有被提到第一"
    # 其余的**保持原顺序**（把被提前的那条剔掉再比）
    assert [i for i in ids_after if i != target.id] == [i for i in ids_before if i != target.id]
    assert len(ids_after) == len(ids_before), "条数变了 —— 这个功能只该排序，不该增删"


def test_far_place_is_not_promoted(client, db_session, users, token_shipper):
    """**阴性对照**：>100 米时不许动顺序。没有这一条，上面那条用例证明不了"是距离起的作用"。"""
    uid = users["dispatcher"].id
    first = _mk(db_session, "FAR 原第一名", 23.5, 114.5, uid)
    target = _mk(db_session, "FAR 远处", 24.5, 115.5, uid)   # 离第一名很远

    before = [p["id"] for p in client.get("/api/v1/places", headers=_hdr(token_shipper)).json()]
    assert before.index(target.id) > 0, "前置条件不成立：目标点本来就在第一"
    after = [
        p["id"]
        for p in client.get(
            "/api/v1/places",
            params={"lat": float(target.lat) + 0.0015, "lng": float(target.lng)},   # ≈167 米
            headers=_hdr(token_shipper),
        ).json()
    ]
    # ⛔ 这条是**阴性对照**：>100 米时顺序必须**逐条不变**（含第一名的位置）。
    assert after == before, ">100 米那一档不该改变任何顺序"


def test_without_coords_behaviour_is_unchanged(client, db_session, users, token_shipper):
    """⛔ 回归：**不给坐标 = 今天的行为**（我自己的常用度 → 先创建的在前）。

    ⚠️ 这条用例原来写的是"调两次比一比"—— 那是**空的**：两次调用走同一条代码路径，
    永远相等。现在改成核对**文档里写的那条顺序规则**本身：本用例新建的三条
    都没被用过，所以必须严格按 id 升序出现。
    """
    uid = users["dispatcher"].id
    a = _mk(db_session, "NOCOORD A", 22.0, 113.0, uid)
    b = _mk(db_session, "NOCOORD B", 22.1, 113.1, uid)
    c = _mk(db_session, "NOCOORD C", 22.2, 113.2, uid)

    got = [p["id"] for p in client.get("/api/v1/places", headers=_hdr(token_shipper)).json()]
    mine = [i for i in got if i in {a.id, b.id, c.id}]
    assert mine == [a.id, b.id, c.id], "没人用过的新地点必须按 id 升序（= 先创建的在前）"
