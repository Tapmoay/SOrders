"""共享地点库的**管理**（2026-09-19 用户要求）：改 / 撤销 / 删除 / 设为共享地址。

用户原话：
> 这个地址是可以编辑的。如果是来到了共享库的话，共享地址的编辑**只有派单员**可以编辑，
> 其他人都编辑不了。派单员可以改名称，也可以把一些地点给**设置为共享地址**，
> 也可以**撤销**某些共享地址，把它**降为普通的地址**，或者直接**删掉**。
> 如果是降为普通的地址的话，则这个地址会保存在**派单员**的地址库当中，其他的不会显示。

这份测试盯的就是上面每一句，外加三件**不说就一定会踩**的事：
1. 权限：货主/司机改不动共享库（403），货主**私有**的地点也推不进共享库（404，不是他的数据）；
2. 撤销之后：共享库里那一条真的没了、但**操作人自己的**地点库里多了一条，别人不受影响；
3. 删除之后：列表里看不见它，**补录同一个坐标也不会"并进"那条已经删掉的行**
   —— 这是"物理删除"最容易漏的后果：`find_place_near` 若还看得见它，
   用户新补的坐标会消失得无影无踪（合并进一条谁也看不见的记录）。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import OperationLog, Place, PlaceUserUsage, ShipperLocation
from app.models.enums import OperationAction
from tests.conftest import auth_headers


def _coords(i: int) -> tuple[float, float]:
    """第 i 条用例**自己的**坐标（彼此相差 0.001° ≈ 85 米）。

    ⚠️ 每条用例一个坐标，不能共用一个常量：`places` 是全库一张表，而"1 米内算同一个地点"
    正是它的写入判据 —— 两个用例都用同一个点，后一个用例建的"新点"会**并进前一个用例
    留下的那条**，于是 `merged` 变成 True，断言就变成在考"上一个用例干了什么"。
    （第一版就是这么红的：两条 `merged is False` 一起失败。）
    坐标整体选在昌平以西，避开种子数据里那些朝阳/顺义的点。
    """
    return 40.201 + i * 0.001, 116.301 + i * 0.001


def _mk_place(db: Session, i: int, *, name: str, detail: str) -> Place:
    """在**第 i 号坐标**上造一条共享地点（同一个 i 造出来的点互为"同一个地点"）。"""
    lat, lng = _coords(i)
    row = Place(name=name, detail_address=detail, lat=lat, lng=lng, source="driver", use_count=1)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _mk_location(db: Session, i: int | None, *, shipper_id: int, name: str, detail: str) -> ShipperLocation:
    """造一条私有地点；`i=None` = **没有坐标**的那种（共享库不收，见最后一条用例）。"""
    lat, lng = (None, None) if i is None else _coords(i)
    row = ShipperLocation(
        shipper_id=shipper_id, name=name, detail_address=detail,
        address_lat=lat, address_lng=lng, image_urls="[]",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _last_log(db: Session, action: OperationAction) -> OperationLog | None:
    return (db.query(OperationLog)
            .filter(OperationLog.action == action.value)
            .order_by(OperationLog.id.desc()).first())


def test_place_update_renames_and_keeps_history(
    client: TestClient, db_session: Session, users: dict, token_dispatcher: str
) -> None:
    """派单员改名字 → 库里变了，且**审计里留着改动前后**（共享库是全库共用的那一条）。"""
    place = _mk_place(db_session, 1, name="旧名字", detail="旧地址")
    r = client.patch(f"/api/v1/places/{place.id}", headers=auth_headers(token_dispatcher),
                     json={"name": "新名字"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "新名字"
    # 只点名的键才改：地址没传 → 一个字都不动（PATCH 的部分更新语义）
    assert r.json()["detail_address"] == "旧地址"

    db_session.expire_all()
    assert db_session.get(Place, place.id).name == "新名字"
    log = _last_log(db_session, OperationAction.PLACE_UPDATE)
    assert log is not None and "旧名字" in (log.change_content or "") and "新名字" in (log.change_content or "")


def test_place_update_rejects_blanking_both_fields(
    client: TestClient, db_session: Session, users: dict, token_dispatcher: str
) -> None:
    """把名字和地址**都清空**要拒绝：共享库里一条认不出来的记录，所有人都得看它。

    ⚠️ 判据必须看**改完之后的那一行**（PATCH 只带一个字段）—— 所以先清名字（地址还在，
    合法），再清地址（这时两个都空，必须 400）。分两步测就是为了钉住这一点。
    """
    place = _mk_place(db_session, 2, name="有名字", detail="有地址")
    r1 = client.patch(f"/api/v1/places/{place.id}", headers=auth_headers(token_dispatcher),
                      json={"name": ""})
    assert r1.status_code == 200, r1.text  # 地址还在 → 合法

    r2 = client.patch(f"/api/v1/places/{place.id}", headers=auth_headers(token_dispatcher),
                      json={"detail_address": ""})
    assert r2.status_code == 400
    assert "名字" in r2.json()["detail"]
    db_session.expire_all()
    # 拒绝之后库里**没有被改坏**（"先写再验"的写法会在这里留下两个空字段）
    assert db_session.get(Place, place.id).detail_address == "有地址"


def test_place_manage_is_dispatcher_only(
    client: TestClient, db_session: Session, users: dict, token_shipper: str, token_driver: str
) -> None:
    """货主和司机**都改不动**共享库 —— 用户原话「其他人都编辑不了」。"""
    place = _mk_place(db_session, 3, name="公共点", detail="公共地址")
    for tok in (token_shipper, token_driver):
        h = auth_headers(tok)
        assert client.patch(f"/api/v1/places/{place.id}", headers=h, json={"name": "x"}).status_code == 403
        assert client.post(f"/api/v1/places/{place.id}/demote", headers=h).status_code == 403
        assert client.delete(f"/api/v1/places/{place.id}", headers=h).status_code == 403
    # 三次都被挡下之后，那条记录原样还在
    db_session.expire_all()
    assert db_session.get(Place, place.id).name == "公共点"


def test_place_delete_removes_it_everywhere(
    client: TestClient, db_session: Session, users: dict, token_dispatcher: str
) -> None:
    """删除：列表里看不见、连"谁用过它"的计数一起删（否则外键会挡住 MySQL 的删除）。"""
    place = _mk_place(db_session, 4, name="要删的点", detail="要删的地址")
    db_session.add(PlaceUserUsage(user_id=users["shipper"].id, place_id=place.id, use_count=3))
    db_session.commit()

    r = client.delete(f"/api/v1/places/{place.id}", headers=auth_headers(token_dispatcher))
    assert r.status_code == 204
    db_session.expire_all()
    assert db_session.get(Place, place.id) is None
    assert db_session.query(PlaceUserUsage).filter_by(place_id=place.id).count() == 0
    listed = client.get("/api/v1/places", headers=auth_headers(token_dispatcher)).json()
    assert all(p["id"] != place.id for p in listed)
    log = _last_log(db_session, OperationAction.PLACE_DELETE)
    assert log is not None and "要删的点" in (log.change_content or "")


def test_deleted_place_is_not_merged_again(
    client: TestClient, db_session: Session, users: dict, token_dispatcher: str
) -> None:
    """删掉之后，**同一个坐标再补录一次**必须新建一条，而不是"并进那条已经删掉的行"。

    这是物理删除与"软删但要处处加过滤"的分水岭：如果删除只打标记而 `find_place_near`
    还看得见它，新点会被"合并"进一条列表上永远看不见的记录 —— 用户补了坐标却哪儿都没有。
    """
    place = _mk_place(db_session, 5, name="删了再补", detail="A")
    assert client.delete(f"/api/v1/places/{place.id}",
                         headers=auth_headers(token_dispatcher)).status_code == 204

    lat, lng = _coords(5)
    r = client.post("/api/v1/places", headers=auth_headers(token_dispatcher),
                    json={"name": "删了再补", "detail_address": "B",
                          "address_lat": str(lat), "address_lng": str(lng)})
    assert r.status_code == 201, r.text
    body = r.json()
    # ⚠️ 不要断言 `body["id"] != place.id`：SQLite 删掉最后一行后**会重用编号**，
    #    这条断言考的是数据库的编号策略，不是"有没有并进旧行"。
    assert body["merged"] is False
    assert body["detail_address"] == "B"
    db_session.expire_all()
    assert db_session.get(Place, body["id"]).detail_address == "B"


def test_demote_moves_place_into_operator_library(
    client: TestClient, db_session: Session, users: dict, token_dispatcher: str
) -> None:
    """**撤销**：共享库里消失，落进**操作人自己**的「我的地点」；别人不受影响。"""
    lat, _ = _coords(6)
    place = _mk_place(db_session, 6, name="撤销我", detail="撤销地址")
    r = client.post(f"/api/v1/places/{place.id}/demote", headers=auth_headers(token_dispatcher))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] is True

    db_session.expire_all()
    assert db_session.get(Place, place.id) is None, "撤销之后共享库里那条必须真的没了"
    loc = db_session.get(ShipperLocation, body["location_id"])
    assert loc is not None and loc.shipper_id == users["dispatcher"].id
    assert loc.name == "撤销我" and float(loc.address_lat) == pytest.approx(lat, abs=1e-6)
    # 「其他的不会显示」：货主自己的地点库里**不会**多出这一条
    assert db_session.query(ShipperLocation).filter_by(
        shipper_id=users["shipper"].id, name="撤销我").count() == 0
    log = _last_log(db_session, OperationAction.PLACE_DEMOTE)
    assert log is not None and "撤销我" in (log.change_content or "")


def test_demote_merges_into_existing_own_location(
    client: TestClient, db_session: Session, users: dict, token_dispatcher: str
) -> None:
    """操作人库里**本来就有**这个点时：不重复建一条，`created=False` 如实回报。"""
    _mk_location(db_session, 7, shipper_id=users["dispatcher"].id, name="已经有", detail="老地址")
    place = _mk_place(db_session, 7, name="已经有", detail="新地址")
    r = client.post(f"/api/v1/places/{place.id}/demote", headers=auth_headers(token_dispatcher))
    assert r.status_code == 200, r.text
    assert r.json()["created"] is False
    db_session.expire_all()
    assert db_session.query(ShipperLocation).filter_by(
        shipper_id=users["dispatcher"].id, name="已经有").count() == 1


def test_share_location_publishes_to_shared_library(
    client: TestClient, db_session: Session, users: dict, token_dispatcher: str
) -> None:
    """**设为共享地址**：私有地点 → 全库共用的那条；再点一次是"并入"而不是多一条。"""
    loc = _mk_location(db_session, 8, shipper_id=users["dispatcher"].id,
                       name="我的仓库", detail="某某路 1 号")
    r = client.post(f"/api/v1/shipper/locations/{loc.id}/share", headers=auth_headers(token_dispatcher))
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["merged"] is False and first["name"] == "我的仓库"

    # 第二次：同一个坐标 → 并进已有那条（共享库里不该出现两条一模一样的点）
    r2 = client.post(f"/api/v1/shipper/locations/{loc.id}/share", headers=auth_headers(token_dispatcher))
    assert r2.status_code == 200, r2.text
    assert r2.json()["merged"] is True and r2.json()["id"] == first["id"]

    log = _last_log(db_session, OperationAction.PLACE_PUBLISH)
    assert log is not None and "我的仓库" in (log.change_content or "")


def test_share_is_dispatcher_only_and_owns_the_location(
    client: TestClient, db_session: Session, users: dict, token_shipper: str, token_dispatcher: str
) -> None:
    """「设为共享地址」两道门：**只有派单员**能调；而且只能推**自己库里**的地点。"""
    mine = _mk_location(db_session, 9, shipper_id=users["shipper"].id,
                        name="货主的地点", detail="某某路 2 号")
    # ① 货主自己都调不动（用户原话：共享地址的编辑只有派单员可以）
    r = client.post(f"/api/v1/shipper/locations/{mine.id}/share", headers=auth_headers(token_shipper))
    assert r.status_code == 403
    # ② 派单员拿着**别人**的地点编号也推不上去（那是货主的私有数据，不是他的）
    r2 = client.post(f"/api/v1/shipper/locations/{mine.id}/share", headers=auth_headers(token_dispatcher))
    assert r2.status_code == 404
    assert db_session.query(Place).filter_by(name="货主的地点").count() == 0


def test_share_rejects_location_without_coords(
    client: TestClient, db_session: Session, users: dict, token_dispatcher: str
) -> None:
    """派单员推**自己**那条没坐标的地点 → 400，且**不会**在共享库里留下一条没有坐标的记录。"""
    loc = _mk_location(db_session, None, shipper_id=users["dispatcher"].id,
                       name="没坐标", detail="只有文字")
    before = db_session.query(Place).count()
    r = client.post(f"/api/v1/shipper/locations/{loc.id}/share", headers=auth_headers(token_dispatcher))
    assert r.status_code == 400
    assert "坐标" in r.json()["detail"]
    assert db_session.query(Place).count() == before
