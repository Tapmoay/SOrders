"""第十二轮审计（第二部分）的回归测试：登录 500 / 长连接撤销 / 归档毁图 / 到期清理。

| 编号 | 症状 | 这条测试钉什么 |
|---|---|---|
| R12-H3 | 脏 `password_hash` → 登录返回 **500**（不是 401），账号永久锁死 + 账号存在性预言机 | 脏 hash 的账号登录 = 401，且不泄露内部错误 |
| R12-H2b | Socket.IO 握手不校验 `token_version` → 登出后旧令牌仍能建长连接收推送 | 撤销后的令牌 connect 必须被拒 |
| R12-H2 | 「1 年后转 WebP」把原图删了、另写一个没人引用的文件 → 满 1 年照片全 404 | 归档后**原路径仍然可用**、内容确实变小 |
| R12-M7 | 物理清理只处理前 200 个订单的图片目录（每轮上限 2000） | 第 201 张起的目录也要清 |
| R12-H4 | 到期清理作废司机账单时**只有一行日志**，界面上没人看得见 | 司机与派单员各收到一条站内信 |
| R12-L6 | 逐单金额没有上界（1e20 本机收下、生产 500） | 超上限的覆盖值被拒 |
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from tests.conftest import auth_headers


def _connect(sio_mod, sid: str, auth: dict):
    """跑一次 socket 握手（传输层不重要，测的是 connect 的判据）。"""
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(sio_mod.connect(sid, {}, auth))
    finally:
        loop.close()


# --------------------------------------------------------- R12-H3 脏密码哈希
def test_dirty_password_hash_logs_in_as_401_not_500(client, db_session):
    """库里只要有一个不是 hash_password 产物的值，那个账号就永远登不进去且报 500。"""
    from app.models import User

    u = User(phone="13710000029", username="13710000029", password_hash="x", role="shipper", full_name="脏哈希")
    db_session.add(u)
    db_session.commit()

    r = client.post("/api/v1/auth/login", json={"phone": "13710000029", "password": "123321"})
    assert r.status_code == 401, f"脏 hash 的账号登录不该 500：{r.status_code} {r.text}"
    # 口令对不对都该是同一种答复（否则就是账号存在性预言机）
    r2 = client.post("/api/v1/auth/login", json={"phone": "13710000029", "password": "错误口令"})
    assert r2.status_code == 401, r2.text
    # 不存在的号与它同一答复
    r3 = client.post("/api/v1/auth/login", json={"phone": "13710099999", "password": "123321"})
    assert r3.status_code == 401, r3.text


def test_verify_password_never_raises():
    from app.core.security import verify_password

    for bad in ("x", "", "not-a-hash", "$2b$12$broken"):
        assert verify_password("123321", bad) is False


# ------------------------------------------------- R12-H2b 长连接的令牌撤销
def test_socket_connect_rejects_revoked_token(client, db_session):
    """登出（token_version+1）之后，同一个令牌**不能**再通过长连接握手。

    判据抽在 `authenticate_socket_token` 里（`connect` 一调就会 enter_room，
    在单测里根本调不起来——那正是这条洞此前测不到的原因）。
    """
    from app.core.socket_io import authenticate_socket_token as auth_socket
    from app.models import User
    from app.services.auth_service import bump_token_version, issue_token

    user = db_session.query(User).filter_by(phone="13800000001").first()
    token = issue_token(user)

    # 有效令牌：握手要能过（前提，否则这条测试是空转）
    assert auth_socket(token) == user.id, "有效令牌应当能通过握手（否则判据在空转）"

    bump_token_version(db_session, user)
    db_session.commit()

    assert auth_socket(token) is None, "登出之后旧令牌仍能建立长连接（撤销在实时通道上失效）"
    # 没令牌 / 乱令牌同样拒绝（收紧时不许把这两种放过去）
    assert auth_socket(None) is None
    assert auth_socket("") is None
    assert auth_socket("not-a-jwt") is None
    assert auth_socket(12345) is None


# ----------------------------------------------------- R12-H2 归档不许毁图
def test_archive_compresses_in_place_and_keeps_url_alive(tmp_path, monkeypatch):
    """归档后：**原路径仍在**、内容确实变小、扩展名与格式一致、不生成孤儿文件。"""
    import os

    from PIL import Image

    from app.services import image_archive as ia

    d = tmp_path / "uploads" / "delivery" / "1234"
    d.mkdir(parents=True)
    src = d / "abc123.jpg"
    Image.new("RGB", (2600, 2000), (120, 30, 30)).save(src, "JPEG", quality=95)
    size_before = src.stat().st_size
    old = (datetime.now(timezone.utc) - timedelta(days=400)).timestamp()
    os.utime(src, (old, old))

    monkeypatch.chdir(tmp_path)
    n = ia.archive_images_older_than(days=365)

    assert n == 1, "过期原图应当被归档"
    assert src.is_file(), "归档不许删掉被引用的原图（库里存的就是这个路径）"
    assert src.stat().st_size < size_before, "归档之后文件应当变小"
    with Image.open(src) as im:
        assert im.format == "JPEG", f"扩展名是 .jpg，写出的格式却是 {im.format}"
    assert not list(d.glob("*.compressed.webp")), "不该再生成没有任何引用的孤儿文件"


def test_archive_leaves_fresh_images_alone(tmp_path, monkeypatch):
    from PIL import Image

    from app.services import image_archive as ia

    d = tmp_path / "uploads" / "products" / "7"
    d.mkdir(parents=True)
    src = d / "fresh.png"
    Image.new("RGB", (40, 40), (1, 2, 3)).save(src, "PNG")
    before = src.stat().st_mtime
    monkeypatch.chdir(tmp_path)
    assert ia.archive_images_older_than(days=365) == 0
    assert src.stat().st_mtime == before, "没到期的图不该被碰"


def test_orphan_compressed_cleanup(tmp_path, monkeypatch):
    from app.services import image_archive as ia

    d = tmp_path / "uploads" / "delivery" / "9"
    d.mkdir(parents=True)
    orphan = d / "old.compressed.webp"
    orphan.write_bytes(b"RIFF0000WEBP")
    monkeypatch.chdir(tmp_path)
    assert ia.purge_orphan_compressed() == 1
    assert not orphan.exists()


# --------------------------------------- R12-M7 清理要覆盖本轮所有订单的图片
def test_purge_removes_image_dirs_beyond_the_first_200(tmp_path, monkeypatch, db_session):
    """`ids[:200]` 那道上限删掉之后，第 201 张起的目录也要清（R12-M7）。"""
    from app.services import data_retention as dr

    monkeypatch.chdir(tmp_path)
    ids = list(range(1000, 1205))
    for oid in ids:
        d = Path("uploads") / "delivery" / str(oid)
        d.mkdir(parents=True)
        (d / "x.jpg").write_bytes(b"x")

    src = (Path(__file__).resolve().parents[1] / "app/services/data_retention.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
    assert "ids[:200]" not in code, "物理清理的图片目录又出现了 200 这个硬编码上限"
    assert "for oid in ids:" in code, "图片目录清理应当覆盖本轮全部订单"

    n = dr.delete_orders_by_ids(db_session, ids)
    assert n == 205
    left = [oid for oid in ids if (Path("uploads") / "delivery" / str(oid)).exists()]
    assert left == [], f"这些订单已经删了，但图片目录还在：{left[:5]}"


# ------------------------------------- R12-H4 作废司机账单必须通知到人
def test_cancelled_driver_bills_notify_driver_and_dispatchers(client, token_dispatcher, db_session):
    from app.models import DriverBill, Notification, Order, OrderStatus, User
    from app.models.enums import DriverBillStatus, DriverBillType
    from app.services import data_retention as dr

    shipper = db_session.query(User).filter_by(phone="13800000002").first()
    driver = db_session.query(User).filter_by(phone="13800000003").first()
    o = Order(
        order_no="SOBILLNOTIFY001",
        shipper_id=shipper.id,
        driver_id=driver.id,
        order_date=date(2026, 9, 19),
        status=OrderStatus.DELIVERED,
        address_detail="通知探针路 1 号",
        freight_fee=Decimal("100"),
        collect_cash=False,
        paid=False,
    )
    db_session.add(o)
    db_session.flush()
    bill = DriverBill(
        order_id=o.id,
        driver_id=driver.id,
        # ⚠️ 列是 `String(8)`，存的是**枚举值**（小写 "piece"），不是枚举名
        bill_type=DriverBillType.PIECE,
        month="2026-09",
        amount=Decimal("300"),
        # ⚠️ 列是 `String(12)`，存的是**枚举值**（小写 "open"），不是枚举名
        status=DriverBillStatus.OPEN,
    )
    db_session.add(bill)
    db_session.commit()
    bill_id = bill.id

    before = db_session.query(Notification).count()
    dr.delete_orders_by_ids(db_session, [o.id])
    db_session.commit()
    after = db_session.query(Notification).count()
    assert after > before, "作废了一笔应付明细，却没有任何人收到站内信（只有一行日志）"
    db_session.expire_all()
    saved = db_session.get(DriverBill, bill_id)
    assert str(getattr(saved.status, "value", saved.status)) == "cancelled"

    notes = db_session.query(Notification).filter(Notification.type == "driver_bill_cancelled").all()
    recipients = {n.recipient_id for n in notes}
    assert driver.id in recipients, "司机本人必须收到（他那笔钱没了）"
    dispatcher = db_session.query(User).filter_by(phone="13800000001").first()
    assert dispatcher.id in recipients, "派单员必须收到（他负责复核）"
    assert any("300" in (n.content or "") for n in notes), "通知里要写出金额"

    # 收尾：把这条账单与通知删掉。订单已经被物理清理，而 SQLite 的 INTEGER PRIMARY KEY
    # **会复用**刚删掉的 id —— 留着它，后面任何"新建订单 + 建账单"的用例都可能撞上
    # `uq_driver_bills_order_type`（实测撞过一条，排查起来完全不相关）。
    db_session.query(Notification).filter(Notification.type == "driver_bill_cancelled").delete()
    db_session.query(DriverBill).filter(DriverBill.id == bill_id).delete()
    db_session.commit()


# ------------------------------------------- R12-L10 出参不许被 NULL 毒化
def test_driver_bill_out_tolerates_null_display_columns():
    """显示用的字符串列读成 `None` 时不许让整个账单列表 500（模型层断言）。

    背景：`note` / `rule_name` 是**后加的列**（`rule_name` 由 `schema_bootstrap` 的
    `ALTER TABLE ADD COLUMN` 补出）。今天的建表语句是 NOT NULL，但历史库/被别的脚本写过的行
    完全可能是 NULL —— 而出参是 `note: str`，一行脏数据会让 `GET /driver-bills` 整体
    500（`ResponseValidationError`），结算页与司机端一起打不开。
    本项目已经在"出参 JSON 列被 NULL 毒化"上栽过一次，所以这里统一兜住。

    ⚠️ 为什么是模型层断言而不是"往库里写一行 NULL"：本机 SQLite 与生产的列都是 NOT NULL，
    写 NULL 会被数据库直接拦下（那说明"今天"造不出这个状态），真正要钉的是**出参的容错**。
    """
    from app.models.enums import DriverBillStatus, DriverBillType
    from app.schemas.accounting_v2 import DriverBillOut

    out = DriverBillOut.model_validate(
        {
            "id": 1,
            "driver_id": 3,
            "bill_type": DriverBillType.PIECE,
            "order_id": None,
            "month": "2026-09",
            "amount": Decimal("10"),
            "status": DriverBillStatus.OPEN,
            "settled_doc_id": None,
            "note": None,
            "rule_name": None,
        }
    )
    assert out.note == "" and out.rule_name == ""


# ------------------------------------------- R12-L6 逐单金额要有上界
def test_per_order_piece_amount_has_upper_bound(client, token_dispatcher, db_session):
    import uuid

    h = auth_headers(token_dispatcher)
    # 专用司机（给公用司机挂规则会污染同轮其它用例——见 round12_guards 里同一个 helper 的说明）
    phone = "13" + uuid.uuid4().hex[:9].translate(str.maketrans("abcdef", "012345"))
    r = client.post(
        "/api/v1/users",
        json={"phone": phone, "password": "pass12345", "full_name": "上界探针司机", "role": "driver"},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    driver_id = int(r.json()["id"])
    r = client.post(
        "/api/v1/driver-billing-rules",
        json={"name": f"上界探针规则-{driver_id}", "piece_amount": "200", "remark": "审计探针"},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    rule_id = r.json()["id"]
    client.post(
        "/api/v1/driver-billing-rules/attach", json={"driver_id": driver_id, "rule_id": rule_id}, headers=h
    )

    o = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": 2,
            "lines": [{"product_name_snapshot": "探针货", "quantity": 1, "unit_price": "100", "line_total": "100"}],
            "address_detail": "上界探针路 1 号",
            "freight_fee": "1000",
        },
        headers=h,
    )
    assert o.status_code in (200, 201), o.text
    order_id = o.json()["id"]

    r = client.post(
        f"/api/v1/orders/{order_id}/assign",
        json={"driver_id": driver_id, "driver_piece_amount": "1e20"},
        headers=h,
    )
    assert r.status_code == 400, f"1e20 这种金额必须被拒（不能落库）：{r.status_code} {r.text}"

    r = client.post(
        f"/api/v1/orders/{order_id}/assign",
        json={"driver_id": driver_id, "driver_piece_amount": "99999999999.99"},
        headers=h,
    )
    assert r.status_code == 400, f"超过金钱上限的逐单金额应当被拒：{r.status_code} {r.text}"
    assert "不能超过" in r.json()["detail"], r.json()
