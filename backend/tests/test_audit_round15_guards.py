"""第十五轮审计的回归测试：消息列表的上限/时间基准、批量删除的空 ids、报表日期参数、
表格解析的列截断、重复的未读角标推送（R14-8 / R14-9 / R14-10 / R14-15 / R14-16 / A8）。

这些都是"后端自己悄悄少给/多删/说错话"的形状 —— 界面上看不出来：

| 缺陷 | 用户看到的样子 |
|---|---|
| 消息列表硬上限 200、不分页也不回报截断（R14-8） | 第 201 条以前的消息在 App 里**一个入口都没有**（含带唯一下载链接的「导出完成」）；点「全部已读」把 1134 条标掉，其实只看过 200 条 |
| `days` 用进程本地时间去比 UTC 的 `created_at`（R14-9） | 本机实测「最近一天」**少 8 小时 / 1508 条**，而且同一列在 SQLite 与 MySQL 上基准还不一样 |
| 表格解析 40 列以上**静默**砍列（R14-10） | 卡片写「200 行 × 40 列」、提示词里也写 40 列 → 模型按「这张表只有 40 列」作答 |
| `batch-delete` 的 `ids: []` 落到 else 分支（A8） | 参数为空 ＝ **删光该账号全部消息**，无二次确认、不可恢复 |
| 报表导出的日期参数非法 → 500（R14-15） | 调用方以为系统坏了并重试，而不是「我的日期写错了」 |
| 未读角标重复推送（R14-16） | 每张新单每个派单员多一条事件 + 多一次 count 查询 |
"""
from __future__ import annotations

from datetime import date, timedelta

from tests.conftest import auth_headers


def _mk_notifications(db_session, recipient_id: int, n: int, prefix: str = "探针消息") -> list[int]:
    """造 n 条消息，返回 id 列表（升序）。`created_at` 显式写 UTC（与库口径一致）。"""
    from app.core.business_time import utc_now_naive
    from app.models import Notification

    base = utc_now_naive() - timedelta(minutes=n + 1)
    ids: list[int] = []
    for i in range(n):
        row = Notification(
            recipient_id=recipient_id,
            category="system",
            type="probe",
            title=f"{prefix}{i}",
            content="探针",
            created_at=base + timedelta(minutes=i),
        )
        db_session.add(row)
        db_session.flush()
        ids.append(row.id)
    db_session.commit()
    return ids


# --------------------------------------------------- R14-8 列表上限 / 截断回报 / 游标
def test_notification_list_reports_truncation_and_honours_limit(client, token_shipper, users, db_session):
    h = auth_headers(token_shipper)
    made = _mk_notifications(db_session, users["shipper"].id, 5)

    r = client.get("/api/v1/notifications?limit=3", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 3, f"limit 没有被遵守：拿到 {len(body)} 条"
    assert r.headers.get("X-Truncated") == "1", (
        "还有更多消息却不回报截断 —— 客户端只能自己猜（App 里就是『第 201 条以前没有入口』）"
    )
    # 倒序（最新在前）
    got = [x["id"] for x in body]
    assert got == sorted(got, reverse=True), got

    # 要满全部 → 不该再标截断
    r2 = client.get("/api/v1/notifications?limit=200", headers=h)
    assert r2.status_code == 200
    assert r2.headers.get("X-Truncated") == "0", "拿满了还说有更多"
    assert made[-1] == r2.json()[0]["id"], "最新的一条必须排在最前"


def test_notification_list_cursor_can_page_backwards(client, token_shipper, users, db_session):
    """`before_id` 游标：第 201 条以前的消息必须有入口（这是这条缺陷的核心）。"""
    h = auth_headers(token_shipper)
    made = _mk_notifications(db_session, users["shipper"].id, 6)

    first = client.get("/api/v1/notifications?limit=2", headers=h).json()
    first_ids = [x["id"] for x in first]
    cursor = first_ids[-1]

    second = client.get(f"/api/v1/notifications?limit=2&before_id={cursor}", headers=h).json()
    second_ids = [x["id"] for x in second]
    assert second_ids, "游标翻页翻不出第二页"
    assert max(second_ids) < cursor, f"第二页里出现了不早于游标的消息：{second_ids} vs 游标 {cursor}"
    assert not set(first_ids) & set(second_ids), "两页重复了"

    # 一直翻到底，必须能覆盖全部（否则"没有入口"只是换了个地方）
    seen = set(first_ids) | set(second_ids)
    cursor = min(second_ids)
    while True:
        page = client.get(f"/api/v1/notifications?limit=2&before_id={cursor}", headers=h).json()
        if not page:
            break
        seen |= {x["id"] for x in page}
        cursor = min(x["id"] for x in page)
    assert set(made) <= seen, f"翻页翻不到这些消息：{sorted(set(made) - seen)}"


def test_notification_limit_is_capped_server_side(client, token_shipper):
    """上限仍在（不许有人把 limit 开到 100000 拖垮接口），并且是**中文 422**。"""
    h = auth_headers(token_shipper)
    r = client.get("/api/v1/notifications?limit=100000", headers=h)
    assert r.status_code == 422, f"超过上限应当被拒：{r.status_code}"
    assert "条数" in r.text, f"报错要说人话（字段名要翻成中文）：{r.text[:200]}"
    # ⚠️ 上限必须**高于** 200（R14-8）：AI 判断"还有更多"的唯一办法是**多要一行**
    #    （`AiReadService` 传 `limit + 1`，最多 201）。钉死在 200 会让探针自己撞 422，
    #    于是模型永远被告知"一共就 200 条"。
    r2 = client.get("/api/v1/notifications?limit=201", headers=h)
    assert r2.status_code == 200, f"AI 的截断探针（201 条）被拒了：{r2.status_code} {r2.text[:200]}"


# --------------------------------------------------- R14-9 时间基准是同源的
def test_days_cutoff_uses_the_utc_single_source(client, token_shipper, users, db_session, monkeypatch):
    """`days` 的窗口起点必须来自 `business_time.utc_now_naive()`。

    判据不依赖跑测试的机器时区：把模块里的"现在"**冻住**再往后推 10 小时，
    那条通知必须因此掉出窗口 —— 老代码（`datetime.now()`）根本不看这个函数，
    所以推不推都一样、永远在窗口里。
    """
    from app.api.v1 import notifications as notif

    h = auth_headers(token_shipper)
    real = notif.utc_now_naive()
    ids = _mk_notifications(db_session, users["shipper"].id, 1)
    probe = ids[0]

    monkeypatch.setattr(notif, "utc_now_naive", lambda: real)
    r = client.get("/api/v1/notifications?days=1&limit=200", headers=h)
    assert any(x["id"] == probe for x in r.json()), "刚刚创建的通知不在『最近一天』窗口里"

    # 把"现在"往后推 10 小时 → 这条通知变成 10 小时前之外（days=1 的窗口是 24 小时，
    # 但这里是"现在往前 24 小时"，推 10 小时不影响；所以改推 30 小时）
    monkeypatch.setattr(notif, "utc_now_naive", lambda: real + timedelta(hours=30))
    r2 = client.get("/api/v1/notifications?days=1&limit=200", headers=h)
    assert not any(x["id"] == probe for x in r2.json()), (
        "把『现在』往后推 30 小时之后它还在窗口里 —— 说明窗口起点不是从 "
        "business_time.utc_now_naive() 算的（老代码用的是进程本地时间）"
    )


def test_soft_delete_timestamp_is_utc_single_source(client, token_dispatcher, db_session):
    """软删除的 `deleted_at` 必须写 **UTC**（六张表与 orders 同源），否则 30 天隔离期会漂。"""
    from app.core.business_time import utc_now_naive
    from app.models import Product

    h = auth_headers(token_dispatcher)
    r = client.post(
        "/api/v1/products",
        json={"name": "软删时间探针", "unit": "件", "price": "10.00", "stock": 1},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]

    d = client.delete(f"/api/v1/products/{pid}", headers=h)
    assert d.status_code in (200, 204), d.text

    db_session.expire_all()
    p = db_session.get(Product, pid)
    assert p is not None and p.deleted_at is not None, "软删没写 deleted_at"
    delta = abs((p.deleted_at - utc_now_naive()).total_seconds())
    assert delta < 120, (
        f"deleted_at 与 UTC 的『现在』差 {delta:.0f} 秒 —— 写的是进程本地时间，"
        "而 30 天隔离期是按 UTC 比的（R14-9）"
    )


# --------------------------------------------------- A8 空 ids 不许删光
def test_batch_delete_with_empty_ids_is_rejected(client, token_shipper, users, db_session):
    """`{"ids": [], "all": false}` 必须 400（客户端的默认形状就是这个）。"""
    h = auth_headers(token_shipper)
    made = _mk_notifications(db_session, users["shipper"].id, 3)

    r = client.post("/api/v1/notifications/batch-delete", json={"ids": [], "all": False}, headers=h)
    assert r.status_code == 400, f"空 ids 被当成『清空全部』了：{r.status_code} {r.text[:200]}"
    assert "ids" in r.text or "消息" in r.text, f"报错要说清怎么改：{r.text[:200]}"

    left = client.get("/api/v1/notifications?limit=200", headers=h).json()
    assert set(made) <= {x["id"] for x in left}, "被拒绝的请求却把消息删了"


def test_batch_delete_all_still_works(client, token_shipper, users, db_session):
    h = auth_headers(token_shipper)
    _mk_notifications(db_session, users["shipper"].id, 2)
    r = client.post("/api/v1/notifications/batch-delete", json={"all": True}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] >= 2, r.json()
    assert client.get("/api/v1/notifications?limit=200", headers=h).json() == []


# --------------------------------------------------- R14-15 报表导出的日期参数
def test_report_export_bad_date_is_a_chinese_422(client, token_dispatcher):
    """非法日期 → 422 + 中文（不是 500「服务器内部错误」）。"""
    h = auth_headers(token_dispatcher)
    for url in (
        "/api/v1/reports/export?kind=finance&mode=day&date=notadate",
        "/api/v1/reports/export?kind=finance&mode=day&date=2026-09-18&date_from=xx&date_to=yy",
        "/api/v1/reports/turnover?mode=day&date=nope",
        "/api/v1/reports/arrears-summary?date_from=zz&date_to=yy",
    ):
        r = client.get(url, headers=h)
        assert r.status_code == 422, f"{url} → {r.status_code}（应当是可读的参数错误）"
        assert "2026-09-18" in r.text, f"{url} 的错误提示没告诉用户该写成什么样：{r.text[:200]}"


def test_report_export_good_date_still_works(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    r = client.get("/api/v1/reports/export?kind=turnover&mode=day&date=2026-09-18", headers=h)
    assert r.status_code == 200, r.text
    assert r.content[:2] == b"PK", "导出的不是 xlsx"


# --------------------------------------------------- R14-10 列截断必须说出来
def test_sheet_parser_flags_column_truncation():
    """50 列的表只读 40 列时：`truncated=True` + warning 说清砍了几列。"""
    from app.services.sheet_parser import MAX_COLS, parse_upload

    header = ",".join(f"列{i}" for i in range(1, 51))
    row = ",".join(str(i) for i in range(1, 51))
    parsed = parse_upload("宽表.csv", (header + "\n" + row + "\n").encode("utf-8"), max_rows=200)
    t = parsed.tables[0]
    assert t.col_count == MAX_COLS, f"列数应当停在 {MAX_COLS}，实际 {t.col_count}"
    assert t.truncated is True, "列被砍了却不说（静默截断 = 模型按『只有 40 列』作答）"
    assert any("列" in w and "没读" in w for w in parsed.warnings), f"没有解释砍了几列：{parsed.warnings}"
    assert len(t.rows[0]) == MAX_COLS


def test_sheet_parser_does_not_cry_wolf_on_narrow_tables():
    from app.services.sheet_parser import parse_upload

    parsed = parse_upload("普通.csv", "商品,单价\n苹果,45.5\n".encode("utf-8"), max_rows=200)
    t = parsed.tables[0]
    assert t.truncated is False, f"普通表不该被标截断：{parsed.warnings}"
    assert t.col_count == 2


def test_sheet_parser_row_truncation_message_unchanged():
    from app.services.sheet_parser import parse_upload

    body = "商品\n" + "\n".join(f"货{i}" for i in range(30)) + "\n"
    parsed = parse_upload("长表.csv", body.encode("utf-8"), max_rows=5)
    t = parsed.tables[0]
    assert t.truncated is True
    assert t.row_count == 31, "真实行数要保留（含表头；否则用户不知道总共有多少）"
    assert any("只读了前 5 行" in w for w in parsed.warnings), parsed.warnings


# --------------------------------------------------- R14-16 未读角标不许推两次
def test_no_duplicate_unread_count_push(monkeypatch, users, db_session):
    """一次新单 → 每个派单员只应收到 **一条** `unread_count`（`emit_notification` 里已经发过）。"""
    import asyncio

    from app.models import User
    from app.services import message_center, message_push

    events: list[tuple[int, str]] = []

    async def spy(user_id: int, event: str, data: dict) -> None:
        events.append((user_id, event))

    monkeypatch.setattr(message_push, "emit_to_user", spy)
    monkeypatch.setattr(message_center, "emit_to_user", spy)

    dispatcher = db_session.query(User).filter_by(phone="13800000001").first()
    n = message_center.create_message(
        db_session,
        recipient_id=dispatcher.id,
        category="order",
        type="order.created",
        title="探针新单",
        content="探针",
    )
    db_session.commit()
    db_session.refresh(n)

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        message_center.emit_notification(n)
    )
    counts = [e for (uid, e) in events if uid == dispatcher.id and e == "unread_count"]
    assert len(counts) == 1, f"一次通知推了 {len(counts)} 条 unread_count（重复推送）"
    assert ("unread_count" in [e for _u, e in events])


# --------------------------------------------------- Socket 回补窗口取的是**最新**的 200 条
def test_socket_sync_returns_the_newest_not_the_oldest(db_session, users):
    """冷启动游标=0 时，回补必须是**最新**的 200 条（老代码按 id 升序 → 给最旧的 200 条）。"""
    from app.core.socket_io import SYNC_LIMIT, sync_payload_for

    made = _mk_notifications(db_session, users["shipper"].id, 3)
    payload = sync_payload_for(users["shipper"].id, 0)
    ids = [x["id"] for x in payload["notifications"]]
    assert ids == sorted(ids), "下发的顺序必须是升序（客户端靠最后一条推游标）"
    assert made[-1] == ids[-1], "回补窗口里必须包含**最新**的那条"
    assert payload["unread_count"] >= 3
    assert len(ids) <= SYNC_LIMIT


def test_socket_sync_only_sends_what_is_newer_than_the_cursor(db_session, users, token_shipper):
    """带上游标时只补比它新的（否则每次重连都把历史消息再推一遍当新消息）。"""
    from app.core.socket_io import sync_payload_for

    made = _mk_notifications(db_session, users["shipper"].id, 4)
    payload = sync_payload_for(users["shipper"].id, made[1])
    ids = [x["id"] for x in payload["notifications"]]
    assert ids == made[2:], f"游标之后的应该正好是 {made[2:]}，实际 {ids}"


# --------------------------------------------------- R14-4 合并临时货主：名字两份都要改
def test_merge_renames_both_copies_and_survives_a_resync(client, token_dispatcher, users, db_session):
    """合并临时货主之后，**重新同步订单到账本**不许把改名还原回去。

    `temp_shipper_name` 在这个系统里存**两份**：`orders.temp_shipper_name`（下单时定的）
    与 `ledgers.temp_shipper_name`（送达自动记账从订单抄过来的）。合并时只改账本那一份的后果是：
    `ledger_sync.sync_ledger_from_delivered_order` 会拿订单上的**旧名字**覆盖回去
    （`existing.temp_shipper_name = temp_shipper_name`）→ "合并过的两笔账"又裂回两行，全程无提示。
    """
    from app.models import Customer, Ledger, Order, OrderProduct
    from app.models.enums import CustomerKind, LedgerSource, OrderStatus
    from app.services.ledger_sync import sync_ledger_from_delivered_order

    h = auth_headers(token_dispatcher)
    tag = "合并探针甲"
    tag2 = "合并探针乙"

    def add_customer(name: str) -> int:
        r = client.post("/api/v1/customers", json={"kind": "tmp", "name": name}, headers=h)
        assert r.status_code in (200, 201), r.text
        return int(r.json()["id"])

    keep_id = add_customer(tag2)
    merge_id = add_customer(tag)
    assert keep_id != merge_id

    # 一张属于"甲"的已送达单 + 它的账本行（名字从订单抄过来，与真实链路一致）
    o = Order(
        order_no=f"SOMERGE{merge_id}",
        shipper_id=None,
        temp_shipper_name=tag,
        status=OrderStatus.DELIVERED,
        order_date=date(2026, 9, 10),
    )
    db_session.add(o)
    db_session.flush()
    db_session.add(
        OrderProduct(
            order_id=o.id,
            product_name_snapshot="探针货",
            quantity=1,
            unit_price=100,
            line_total=100,
        )
    )
    db_session.commit()
    sync_ledger_from_delivered_order(db_session, o)
    db_session.commit()

    # 合并：把"甲"并进"乙"
    r = client.post(
        "/api/v1/customers/merge", json={"keep_id": keep_id, "merge_ids": [merge_id]}, headers=h
    )
    assert r.status_code == 200, r.text

    db_session.expire_all()
    assert db_session.get(Order, o.id).temp_shipper_name == tag2, "订单上的临时货主名没跟着改"
    row = db_session.query(Ledger).filter(Ledger.order_id == o.id).first()
    assert row is not None and row.temp_shipper_name == tag2, "账本上的临时货主名没跟着改"

    # 关键一步：再同步一次（真实链路上送达/补账都会走它）→ 名字必须仍是"乙"
    sync_ledger_from_delivered_order(db_session, db_session.get(Order, o.id))
    db_session.commit()
    db_session.expire_all()
    row = db_session.query(Ledger).filter(Ledger.order_id == o.id).first()
    assert row.temp_shipper_name == tag2, (
        f"重新同步把改名还原成了 {row.temp_shipper_name!r} —— 合并的效果被静默撤销"
    )

    # 收尾：清掉探针数据（这些不是业务数据，别留在测试库里影响别的用例）
    db_session.query(Ledger).filter(Ledger.order_id == o.id).delete()
    db_session.query(OrderProduct).filter(OrderProduct.order_id == o.id).delete()
    db_session.query(Customer).filter(Customer.id.in_([keep_id, merge_id])).delete(
        synchronize_session=False
    )
    db_session.query(Order).filter(Order.id == o.id).delete()
    db_session.commit()


