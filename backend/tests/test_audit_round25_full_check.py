# -*- coding: utf-8 -*-
"""第二轮外部完整检查报告（`SOrders-FULL-CHECK-REPORT.md`）里**后端侧**的判据。

这份报告是**仓库之外**产出的（`_security-audit/reports/`），条目带编号与证据行号。
本文件只钉那些"能被一条断言证明、且退回旧写法就会立刻变红"的行为——
每条都做过注入式反向验证（把修复改回旧写法 → 红；改回 → 绿）。

已覆盖：
- **S5** 422 的中文兜底在 `NaN`/`Infinity` 上自己炸掉 → 任何数值写端点 500
- **PERF-05 / R2-5(bak)** 每日治理没有跨进程锁（两个 worker 各跑一遍）
- **C-4 / PERF-02 / R2B-2** 账本列表全量下发 + 逐行 `db.get`（N+1）
- **C-5 / R2-7(exp)** 账本导出没有并发/配额/区间闸
- **C-6** `uploads/locations/` 永不清理
- **C-7 / R2-5(bak)** 图片归档全解码「客户端声明多大就多大」的图 + 固定临时名
"""

from __future__ import annotations

import json
import math
import re

import pytest
from starlette.testclient import TestClient

from tests.conftest import auth_headers

# ============================================================
# S5：422 兜底自己在 NaN / Infinity 上炸掉
# ============================================================


def _post_raw(client: TestClient, url: str, raw: str, tok: str):
    """发**原始** body：`NaN` 不是合法 JSON，只有绕过 `json=` 序列化才发得出去。

    ⚠️ 这正是攻击面成立的前提：Python 的 `json.loads` **默认接受** `NaN`/`Infinity`
    字面量（`parse_constant` 默认可放行），所以客户端随手发得进来。
    """
    return client.post(
        url,
        content=raw,
        headers={**auth_headers(tok), "Content-Type": "application/json"},
    )


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_validation_fallback_survives_non_finite_numbers(client, token_dispatcher, bad):
    """非法数值 → **422 + 中文**，绝不是 500。

    缺陷现场（2026-09-19 外部完整检查 S5）：`safe_errors` 用白名单放行 `float`，
    而 `NaN` **就是** float → 原样进 `JSONResponse` → Starlette 的
    `json.dumps(..., allow_nan=False)` 抛 `ValueError` → **处理器自己 500**。
    本文件（`validation_errors.py`）存在的全部意义就是"绝不把 500 甩给用户"，
    所以这是最不能破的一条：兜底必须对**任意**客户端输入都成立。
    """
    raw = (
        '{"entry_date": "2026-09-19", "product_name": "测试",'
        ' "temp_shipper_name": "散客", "quantity": %s}' % bad
    )
    r = _post_raw(client, "/api/v1/ledger/entries", raw, token_dispatcher)
    assert r.status_code == 422, f"{bad} 应当是可读的参数错误，实际 {r.status_code}：{r.text[:300]}"
    body = r.json()
    assert isinstance(body.get("detail"), str), body
    assert any("\u4e00" <= ch <= "\u9fff" for ch in body["detail"]), body["detail"]
    # 这一格原来印"填写的内容不符合要求"（`finite_number` 不在 TYPE_CN 里，落兜底）——
    # 它正是"以前会 500 的那个输入"，所以要说清是什么问题
    assert "数字" in body["detail"], body["detail"]
    # 原始结构仍要留着（排障用）：非有限浮点降级成同名字符串，不能丢字段
    dumped = json.dumps(body, allow_nan=False)   # ← 这一行就是原来炸掉的地方
    assert str(float(bad)).lower() in dumped.lower()


def test_validation_fallback_survives_nested_non_finite():
    """递归：`NaN` 藏在 list / dict 里同样不许漏出去（白名单式写法只挡得住顶层）。"""
    from app.core.validation_errors import safe_errors

    raw_errors = [
        {
            "type": "float_parsing",
            "loc": ("body", "amounts"),
            "msg": "Input should be a valid number",
            "input": [1.0, float("nan"), {"deep": [float("inf")]}],
            "ctx": {"error": ValueError("boom")},   # ctx 里是异常对象（上一轮的坑）
        }
    ]
    safe = safe_errors(raw_errors)
    json.dumps(safe, allow_nan=False)               # 不许抛
    assert safe[0]["input"][1] == "nan"
    assert safe[0]["input"][2]["deep"][0] == "inf"
    assert safe[0]["ctx"]["error"] == "boom"


def test_validation_fallback_keeps_finite_numbers_as_numbers():
    """有限浮点**不许**被降级成字符串：降级是给 NaN 用的，不是给所有数字用的。

    （报告给的候选修法是"白名单去掉 `float`"——那会让 `input: 500.0` 变成 `"500.0"`，
    排障时看不出"客户端到底发的是数字还是字符串"。这条判据把那个偷懒修法钉住。）
    """
    from app.core.validation_errors import safe_errors

    safe = safe_errors([{"type": "x", "loc": ("body", "n"), "msg": "m", "input": 500.0}])
    assert safe[0]["input"] == 500.0 and isinstance(safe[0]["input"], float)
    assert not math.isnan(safe[0]["input"])


# ============================================================
# PERF-05 / R2-5(bak)：每日治理的跨进程锁
# ============================================================


class _FakeFlock:
    """模拟 `fcntl.flock` 的**互斥语义**（Windows 上没有真的 `fcntl`，本机测不动）。

    只实现我们用到的那三件事：同一路径的第二个 `LOCK_EX|LOCK_NB` 必须失败、
    `LOCK_UN` 之后又能拿到、进程退出时锁不残留。
    """

    LOCK_EX = 2
    LOCK_NB = 4
    LOCK_UN = 8

    def __init__(self) -> None:
        self.held: set[str] = set()

    def flock(self, fileobj, op):  # noqa: ANN001
        path = fileobj.name
        if op & self.LOCK_UN:
            self.held.discard(path)
            return
        if path in self.held:
            raise OSError(11, "Resource temporarily unavailable")
        self.held.add(path)


def test_daily_governance_skips_when_another_process_holds_the_lock(monkeypatch):
    """第二个执行者**跳过**（而不是排队等它跑完、再原样跑一遍）。

    缺陷现场（2026-09-19 外部完整检查 PERF-05 / R2-5(bak)）：治理循环挂在 lifespan 上，
    生产是 `uvicorn --workers 2` → 两个 worker 各跑一遍，全套"物理删单/压图/清导出"
    没有任何互斥。实测两个执行者同时压图时 40 轮里 4 张**根本没压成**。
    """
    import sys
    import types

    from app.services import data_retention as dr

    fake = _FakeFlock()
    module = types.ModuleType("fcntl")
    module.flock = fake.flock           # type: ignore[attr-defined]
    for name in ("LOCK_EX", "LOCK_NB", "LOCK_UN"):
        setattr(module, name, getattr(fake, name))
    monkeypatch.setitem(sys.modules, "fcntl", module)

    ran: list[int] = []
    monkeypatch.setattr(dr, "_run_daily_retention_locked", lambda db: ran.append(1) or {})

    with dr._single_runner() as first:
        assert first is True, "第一个执行者应当拿到锁"
        with dr._single_runner() as second:
            assert second is False, "锁已被占用时，第二个执行者必须**跳过**"

        # 跳过时**不许**碰数据库
        class _NoTouch:
            def __getattr__(self, item):
                raise AssertionError("跳过时不该动数据库")

        assert dr.run_daily_retention(_NoTouch()) == {"skipped": 1}   # type: ignore[arg-type]
        assert ran == []

    with dr._single_runner() as third:
        assert third is True, "上一个跑完必须释放锁（否则治理从此再也不执行）"


def test_daily_governance_runs_and_releases_the_lock(monkeypatch, db_session, tmp_path):
    """正常路径：真的执行，且**跑完释放**（第二次调用照样执行）。"""
    import sys
    import types

    from app.services import data_retention as dr

    fake = _FakeFlock()
    module = types.ModuleType("fcntl")
    module.flock = fake.flock           # type: ignore[attr-defined]
    for name in ("LOCK_EX", "LOCK_NB", "LOCK_UN"):
        setattr(module, name, getattr(fake, name))
    monkeypatch.setitem(sys.modules, "fcntl", module)
    monkeypatch.chdir(tmp_path)

    calls: list[int] = []
    monkeypatch.setattr(dr, "_run_daily_retention_locked", lambda db: calls.append(1) or {"x": 1})

    assert dr.run_daily_retention(db_session) == {"x": 1}
    assert dr.run_daily_retention(db_session) == {"x": 1}
    assert calls == [1, 1]
    assert fake.held == set(), "跑完必须没有残留锁"


# ============================================================
# C-6：uploads/locations 与 products 的无引用图片清理
# ============================================================


def _backdate(path, days: int) -> None:
    import os
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    os.utime(path, (old, old))


def test_orphan_images_purged_but_referenced_ones_kept(tmp_path, monkeypatch, db_session, users):
    """没有任何行引用的地址图/商品图 → 删；**还被引用的一律不许动**。

    缺陷现场（2026-09-19 外部完整检查 C-6）：唯一清理路径只覆盖
    `uploads/delivery/{order_id}`，`uploads/locations/` 下**一行删除代码都没有**
    —— 实测 42 个文件跑完整条治理链前后不变，是全系统唯一永久且无限的堆积路径。
    """
    from app.models.shipper import ShipperLocation
    from app.services import image_archive as ia

    up = tmp_path / "uploads"
    (up / "locations").mkdir(parents=True)
    (up / "products" / "7").mkdir(parents=True)
    (up / "delivery" / "42").mkdir(parents=True)

    used_loc = up / "locations" / "used.jpg"
    orphan_loc = up / "locations" / "orphan.jpg"
    orphan_prod = up / "products" / "7" / "orphan.jpg"
    delivery_photo = up / "delivery" / "42" / "evidence.jpg"
    for f in (used_loc, orphan_loc, orphan_prod, delivery_photo):
        f.write_bytes(b"\xff\xd8\xff\xe0fake")
        _backdate(f, 30)

    # 一条**软删**地点也要保住它的图：回收站里的地点恢复后图必须还在
    db_session.add(
        ShipperLocation(
            shipper_id=users["shipper"].id,
            name="被引用的地点",
            detail_address="某地",
            image_url="/static/uploads/locations/used.jpg",
            is_deleted=True,
        )
    )
    db_session.flush()

    monkeypatch.chdir(tmp_path)
    removed = ia.purge_orphan_images(db_session, days=7)

    assert removed == 2, f"应当只删两张无引用的（实际 {removed}）"
    assert used_loc.is_file(), "还被引用的图**绝对不能删**"
    assert not orphan_loc.exists(), "无人引用的地址图应当清掉"
    assert not orphan_prod.exists(), "无人引用的商品图应当清掉"
    assert delivery_photo.is_file(), "送达凭证有自己的按单清理路径，这条扫描不许碰它"


def test_orphan_purge_respects_grace_period(tmp_path, monkeypatch, db_session):
    """宽限期内的新图不碰（上传接口先落盘、用户随后才保存表单）。"""
    from app.services import image_archive as ia

    up = tmp_path / "uploads" / "locations"
    up.mkdir(parents=True)
    fresh = up / "just-uploaded.jpg"
    fresh.write_bytes(b"\xff\xd8\xff\xe0fake")

    monkeypatch.chdir(tmp_path)
    assert ia.purge_orphan_images(db_session, days=7) == 0
    assert fresh.is_file()


def test_referenced_urls_reads_json_arrays_and_survives_poisoned_json(db_session, users):
    """引用集要读到 JSON 数组列，并且**不许**被毒化过的 JSON 打断整轮治理。"""
    from app.models.shipper import ShipperLocation
    from app.services import image_archive as ia

    db_session.add_all(
        [
            ShipperLocation(
                shipper_id=users["shipper"].id, name="a", detail_address="x",
                image_url="/static/uploads/locations/first.jpg",
                image_urls='["/static/uploads/locations/first.jpg", "/static/uploads/locations/second.jpg"]',
            ),
            ShipperLocation(
                shipper_id=users["shipper"].id, name="b", detail_address="y",
                image_url=None, image_urls="{不是数组",
            ),
        ]
    )
    db_session.flush()
    keep = ia.referenced_image_urls(db_session)
    assert "/static/uploads/locations/first.jpg" in keep
    assert "/static/uploads/locations/second.jpg" in keep


# ============================================================
# C-7：归档前的像素闸（不许让"客户端声明的尺寸"决定我们的内存）
# ============================================================


def _declared_size_png(w: int, h: int) -> bytes:
    """造一张**只声明了尺寸**的 PNG：header 说 w×h，IDAT 是垃圾。

    它是"小文件声明巨大尺寸"的最小复现（真实场景里 IDAT 是压得很好的数据）。
    关键点：`Image.open` 只读 header 不碰 IDAT，所以这张图在**不解码**的前提下完全合法。
    """
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)   # 8bit 灰度
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", b"\x00\x00\x00\x00")
        + chunk(b"IEND", b"")
    )


def test_archive_skips_oversized_image_without_decoding(tmp_path, monkeypatch):
    """声明尺寸超上限 → **不解码**就跳过（原图保留），而不是先吃几百 MB 再失败。

    缺陷现场（2026-09-19 外部完整检查 C-7）：归档在 API 进程里解码"客户端声明多大就多大"的图，
    实测不到 1MB 的请求 → **峰值 266.9MB**；更糟的是它**每天都重试**。
    PIL 自己的 `MAX_IMAGE_PIXELS`（8947 万）只告警不拦，要到 2 倍（1.79 亿）才抛错，
    所以 8947 万~1.79 亿这一段是真的会把内存吃满的区间。
    """
    from PIL import Image

    from app.services import image_archive as ia

    monkeypatch.chdir(tmp_path)
    d = tmp_path / "uploads" / "delivery" / "5"
    d.mkdir(parents=True)
    src = d / "huge.png"
    w = h = int((ia.MAX_ARCHIVE_PIXELS + 1) ** 0.5) + 1     # 刚过上限
    src.write_bytes(_declared_size_png(w, h))
    before = src.read_bytes()

    # 记录"到底有没有解码"。
    # ⚠️ 这里**不能**用"让 load 抛异常"来证明没解码：`compress_image` 自己的 `except Exception`
    #    会把那个异常吞掉并返回 None，于是去掉像素闸之后用例**照样绿**（实测：注入 `if False:`
    #    之后这条用例仍然通过）。必须用一个**只记录、不抛**的探针，把"解没解码"变成一个可断言的量。
    decoded: list[int] = []
    real_load = Image.Image.load

    def _spy(self):  # noqa: ANN001
        decoded.append(1)
        return real_load(self)

    monkeypatch.setattr(Image.Image, "load", _spy)
    assert ia.compress_image(src) is None
    assert not decoded, "超过像素上限的图**不许**被解码（内存炸弹正是解码那一下）"
    assert src.read_bytes() == before, "跳过归档时必须原样保留原图"


def test_archive_still_compresses_normal_photo(tmp_path, monkeypatch):
    """闸门不许误伤正常照片（长边超 1920 的照样要被压到 1920）。"""
    from PIL import Image

    from app.services import image_archive as ia

    monkeypatch.chdir(tmp_path)
    d = tmp_path / "uploads" / "delivery" / "6"
    d.mkdir(parents=True)
    src = d / "normal.jpg"
    Image.new("RGB", (2600, 2000), (200, 40, 40)).save(src, "JPEG", quality=95)
    assert ia.compress_image(src) is not None
    with Image.open(src) as im:
        assert max(im.size) == 1920
    assert not list(d.glob("*.archiving")), "临时文件必须被替换掉（随机段临时名不许残留）"


def test_interrupted_archiving_temp_files_are_cleaned(tmp_path, monkeypatch):
    """中断留下的 `*.archiving` 也要清（随机段临时名之后**必然**不会被下次覆盖）。"""
    from app.services import image_archive as ia

    monkeypatch.chdir(tmp_path)
    d = tmp_path / "uploads" / "locations"
    d.mkdir(parents=True)
    stale = d / "x.jpg.deadbeef.archiving"
    stale.write_bytes(b"half")
    assert ia.purge_orphan_compressed() == 1
    assert not stale.exists()


# ============================================================
# C-4 / PERF-02 / R2B-2：账本列表的上限、截断回报与逐行取数
# ============================================================


def _create_minimal_order(client: TestClient, token_shipper: str) -> int:
    r = client.post(
        "/api/v1/orders",
        headers=auth_headers(token_shipper),
        json={
            "lines": [
                {
                    "product_name_snapshot": "分页用商品",
                    "quantity": 1,
                    "unit_price": "10.00",
                    "line_total": "10.00",
                }
            ],
            "delivery_description": "分页用",
        },
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _seed_ledger_rows(
    db_session,
    *,
    order_ids: list[int | None],
    temp_shipper_name: str | None = None,
    shipper_id: int | None = None,
) -> None:
    """直接插账本行（**不走 HTTP**）：手工记账接口刻意把 `order_id` 置空
    （"手工行不挂订单"，见 `create_entry` 的注释），而这条用例要的正是"挂了订单的行"。"""
    from datetime import date as date_type
    from decimal import Decimal as D

    from app.models import Ledger
    from app.models.enums import LedgerSource

    db_session.add_all(
        [
            Ledger(
                shipper_id=shipper_id,
                temp_shipper_name=temp_shipper_name if shipper_id is None else None,
                entry_date=date_type.today(),
                product_name=f"分页商品-{oid}",
                quantity=1,
                unit_price=D("10.00"),
                total=D("10.00"),
                order_id=oid,
                order_product_id=None,
                product_id=None,
                source=LedgerSource.MANUAL,
                note="",
            )
            for oid in order_ids
        ]
    )
    db_session.flush()


def _fresh_shipper(db_session, phone: str):
    """建一个只属于本用例的货主账号（否则共享测试库里的历史流水会让计数用例变成偶发失败）。"""
    from app.core.security import hash_password
    from app.models import User

    u = User(
        username=phone, phone=phone, password_hash=hash_password("pass12345"),
        full_name=f"导出闸-{phone}", role="shipper",  # type: ignore[arg-type]
    )
    db_session.add(u)
    db_session.flush()
    return u



def test_ledger_list_reports_truncation_and_respects_limit(client, token_dispatcher, token_shipper, db_session):
    """`GET /ledger/entries` 必须有缺省上限，并且**如实回报截断**。

    缺陷现场（2026-09-19 外部完整检查 C-4）：这条端点原来**没有 limit**，
    实测 85,474 行 → 27.75 秒 / 响应体 29.12 MB / SQL 85,476 条；
    而两个已经发到用户手机上的安卓账本页在"清掉日期筛选"时走的正是这条全量路径。
    """
    import uuid

    tag = f"分页-{uuid.uuid4().hex[:8]}"
    _seed_ledger_rows(
        db_session,
        temp_shipper_name=tag,
        order_ids=[_create_minimal_order(client, token_shipper) for _ in range(3)],
    )

    r = client.get(
        "/api/v1/ledger/entries",
        params={"temp_shipper_name": tag, "limit": 2},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2, "limit=2 应当只回 2 行"
    assert r.headers.get("X-Truncated") == "1", "还有更多却没说"
    assert r.headers.get("X-Result-Limit") == "2", "要能说出这次的上限是多少"

    r2 = client.get(
        "/api/v1/ledger/entries",
        params={"temp_shipper_name": tag, "limit": 10},
        headers=auth_headers(token_dispatcher),
    )
    assert r2.status_code == 200
    assert len(r2.json()) == 3
    assert r2.headers.get("X-Truncated") == "0", "拿满了还说有更多"

    # 不传 limit 时也必须带上限（否则默认路径就是全量）
    r3 = client.get(
        "/api/v1/ledger/entries",
        params={"temp_shipper_name": tag},
        headers=auth_headers(token_dispatcher),
    )
    assert r3.status_code == 200
    assert r3.headers.get("X-Result-Limit") not in (None, ""), "缺省路径也必须说明上限"
    assert r3.headers.get("X-Truncated") == "0"


def test_ledger_list_fetches_orders_in_one_query(client, token_dispatcher, token_shipper, db_session):
    """逐行 `db.get(Order)` 必须改成批量：SQL 条数**不许随行数增长**。

    缺陷现场（2026-09-19 外部完整检查 PERF-02 / R2B-2）：`db.get()` 每次都真发一条 SQL
    （Session 身份映射持**弱引用**，"靠 identity map 兜着"不成立），
    于是列表端点的 SQL 条数 ≈ 行数（实测 85,474 行 → 85,476 条 SQL）。
    """
    import uuid

    from sqlalchemy import event

    from tests.conftest import get_test_engine

    tag = f"批量-{uuid.uuid4().hex[:8]}"
    order_ids = [_create_minimal_order(client, token_shipper) for _ in range(3)]
    _seed_ledger_rows(db_session, temp_shipper_name=tag, order_ids=order_ids)

    # ⚠️ 监听器必须装成**类级** `Session.do_orm_execute`（并行那条线实测出来的结论）：
    #    `event.listen(engine, "before_cursor_execute", …)` 只对**注册之后新建的连接**生效，
    #    而测试里那条连接早被 fixture（`db_session`/`users`）建好并复用了 ——
    #    装在 engine 上一条 SQL 都抓不到，这条用例就会在"根本没抓到"的情况下**假绿**。
    #    类级 ORM 事件对 `session.execute/scalars/get` 一律触发，与连接何时建立无关。
    from sqlalchemy import event
    from sqlalchemy.orm import Session as OrmSession

    stmts: list[str] = []

    def _record(state) -> None:  # noqa: ANN001
        try:
            stmts.append(str(state.statement))
        except Exception:  # noqa: BLE001 - 渲染失败不该让用例挂掉
            stmts.append("")

    event.listen(OrmSession, "do_orm_execute", _record)
    try:
        r = client.get(
            "/api/v1/ledger/entries",
            params={"temp_shipper_name": tag, "limit": 10},
            headers=auth_headers(token_dispatcher),
        )
    finally:
        event.remove(OrmSession, "do_orm_execute", _record)

    assert r.status_code == 200, r.text
    assert len(r.json()) == 3
    # 判据要钉在**取订单那一句**上：`visible_ledger_clause()` 自带的 EXISTS 子查询里也有
    # `orders.id = ledgers.order_id`（列比列），用宽泛的子串会把它误判成逐行取数。
    # 逐行 `db.get` 比的是**绑定参数**（`orders.id = :pk_1`），据此区分。
    assert stmts, "一条语句都没抓到 —— 监听器装错了地方，这条判据等于没检查"
    per_row = [s for s in stmts if re.search(r"orders\.id = :\w", s)]
    assert per_row == [], f"还在逐行取订单（{len(per_row)} 条单行查询）：{per_row[:1]}"
    batched = [s for s in stmts if re.search(r"orders\.id IN\b", s)]
    assert len(batched) == 1, f"应当只有一次批量取订单，实际 {len(batched)} 次"
    assert {row["order_no"] for row in r.json()} != {None}, "批量取数后订单号仍要填上"


# ============================================================
# C-5：账本导出的三道闸
# ============================================================


def test_export_slot_is_mutually_exclusive(monkeypatch):
    """同一个账号同时只能有一个导出在跑（文件锁；进程死了由操作系统自动释放）。"""
    import sys
    import types

    from app.services import ledger_export_worker as w

    fake = _FakeFlock()
    module = types.ModuleType("fcntl")
    module.flock = fake.flock           # type: ignore[attr-defined]
    for name in ("LOCK_EX", "LOCK_NB", "LOCK_UN"):
        setattr(module, name, getattr(fake, name))
    monkeypatch.setitem(sys.modules, "fcntl", module)

    first = w.acquire_export_slot(4242)
    try:
        assert first is not None, "空槽位应当能占住"
        assert w.acquire_export_slot(4242) is None, "同一个账号第二个导出必须被拒"
        other = w.acquire_export_slot(4243)
        assert other is not None, "不同账号之间不该互相拦"
        w.release_export_slot(other)
    finally:
        w.release_export_slot(first)
    third = w.acquire_export_slot(4242)
    assert third is not None, "放掉之后必须还能再导（否则这个账号再也导不出东西）"
    w.release_export_slot(third)


def test_export_rejected_while_another_is_running(client, token_dispatcher, users, db_session, monkeypatch):
    """占不到槽位 → 429 + 中文，且**不留下**一个永远不会被执行的 PENDING 任务。"""
    from sqlalchemy import func, select

    from app.api.v1 import ledger as ledger_api
    from app.models import LedgerExportJob

    def _jobs(uid: int) -> int:
        return int(
            db_session.scalar(
                select(func.count())
                .select_from(LedgerExportJob)
                .where(LedgerExportJob.created_by_id == uid)
            )
            or 0
        )

    before = _jobs(users["dispatcher"].id)
    monkeypatch.setattr(ledger_api, "acquire_export_slot", lambda uid: None)
    r = client.post(
        "/api/v1/ledger/export-jobs",
        headers=auth_headers(token_dispatcher),
        json={"shipper_id": users["shipper"].id, "date_from": "2026-01-01", "date_to": "2026-12-31"},
    )
    assert r.status_code == 429, r.text
    assert "还在生成中" in r.json()["detail"]
    assert _jobs(users["dispatcher"].id) == before, "被闸拦下的请求不该留下任务行"


def test_export_rejected_when_range_is_too_large(client, token_dispatcher, db_session, monkeypatch):
    """单次区间超过上限 → 400，并且**说清实际有多少笔**（不是闷头跑 40 秒）。"""
    import uuid

    from app.api.v1 import ledger as ledger_api

    u = _fresh_shipper(db_session, f"13900{uuid.uuid4().int % 1000000:06d}")
    _seed_ledger_rows(db_session, shipper_id=u.id, order_ids=[None, None, None])
    monkeypatch.setattr(ledger_api, "MAX_EXPORT_ROWS", 2)
    r = client.post(
        "/api/v1/ledger/export-jobs",
        headers=auth_headers(token_dispatcher),
        json={"shipper_id": u.id, "date_from": "2026-01-01", "date_to": "2026-12-31"},
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "3 笔流水" in detail, f"报文要说清实际有多少笔：{detail}"
    assert "缩小" in detail, f"要给出能照着做的办法：{detail}"


def test_export_daily_quota(client, token_dispatcher, users, db_session, monkeypatch):
    """当天导出次数用完 → 429 + 中文（产物可重复下载，不需要反复生成）。"""
    from sqlalchemy import func, select

    from app.api.v1 import ledger as ledger_api
    from app.models import LedgerExportJob

    already = int(
        db_session.scalar(
            select(func.count())
            .select_from(LedgerExportJob)
            .where(LedgerExportJob.created_by_id == users["dispatcher"].id)
        )
        or 0
    )
    monkeypatch.setattr(ledger_api, "EXPORT_DAILY_QUOTA", already + 1)
    body = {"shipper_id": users["shipper"].id, "date_from": "2026-01-01", "date_to": "2026-01-31"}
    r = client.post("/api/v1/ledger/export-jobs", headers=auth_headers(token_dispatcher), json=body)
    assert r.status_code == 201, r.text
    r2 = client.post("/api/v1/ledger/export-jobs", headers=auth_headers(token_dispatcher), json=body)
    assert r2.status_code == 429, r2.text
    assert "上限" in r2.json()["detail"] and "消息中心" in r2.json()["detail"]




# ============================================================
# S2：散客电话唯一性不许依赖 SQLite 专属的部分索引
# ============================================================


def test_customer_tmp_phone_index_has_no_sqlite_only_predicate():
    """**给 MySQL 方言渲染**这条索引，证明它是一条"无条件"的唯一索引。

    缺陷现场（2026-09-19 外部完整检查 S2）：原来写的是
    `Index(..., unique=True, sqlite_where=text("kind=''tmp'' AND phone IS NOT NULL"))`
    —— `sqlite_where` 只在 SQLite 上生效，MySQL 上被**静默忽略**，于是
    `CREATE UNIQUE INDEX uq_customers_tmp_phone ON customers (phone)` 变成**整表唯一**：
    给一个已存在的注册货主建同号散客档案**必然 409**（本机 201）。

    这条判据不看 SQLite 的行为（那正是"两库不同"的地方），只看**MySQL 会建出什么**。
    """
    from sqlalchemy.dialects import mysql
    from sqlalchemy.schema import CreateIndex

    from app.models.customer import Customer

    idx = next(i for i in Customer.__table__.indexes if i.name == "uq_customers_tmp_phone")
    ddl = str(CreateIndex(idx).compile(dialect=mysql.dialect()))
    assert idx.unique, "散客电话必须由数据库保证唯一（并发下'先查再插'挡不住重复档案）"
    assert "tmp_phone_key" in ddl, f"唯一性必须落在专用列上，实际 DDL：{ddl}"
    assert " WHERE " not in ddl.upper(), (
        f"MySQL 会忽略 sqlite_where，这条索引在那边会退化成整表唯一：{ddl}"
    )


def test_tmp_and_registered_customer_may_share_a_phone(client, token_dispatcher, users):
    """注册货主与散客**同号**必须能共存（生产上这条原来必然 409）。"""
    phone = users["shipper"].phone
    r = client.post(
        "/api/v1/customers",
        headers=auth_headers(token_dispatcher),
        json={"kind": "registered", "user_id": users["shipper"].id, "name": "注册货主"},
    )
    assert r.status_code == 200, r.text
    r2 = client.post(
        "/api/v1/customers",
        headers=auth_headers(token_dispatcher),
        json={"kind": "tmp", "name": "同号散客", "phone": phone},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["kind"] == "tmp"


def test_customer_tmp_phone_key_is_filled_only_for_tmp(db_session):
    """键值只在"散客 + 有电话"时填（其余一律 NULL，NULL 在唯一索引里不算冲突）。"""
    import uuid

    from sqlalchemy import select

    from app.models.customer import Customer

    # ⚠️ 用**新建的**货主账号：共享测试库里上一条用例已经给 `users["shipper"]` 建过注册客户，
    #    而 `uq_customers_registered` 是真的唯一约束（这里刻意不共用账号）。
    fresh = _fresh_shipper(db_session, f"13911{uuid.uuid4().int % 1000000:06d}")
    db_session.add_all(
        [
            Customer(kind="tmp", name="有电话的散客", phone="13900000001", tmp_phone_key="13900000001"),
            Customer(kind="registered", name="注册", user_id=fresh.id, phone="13900000002"),
        ]
    )
    db_session.flush()
    rows = {
        r.name: r.tmp_phone_key
        for r in db_session.scalars(
            select(Customer).where(Customer.name.in_(["有电话的散客", "注册"]))
        ).all()
    }
    assert rows["有电话的散客"] == "13900000001"
    assert rows["注册"] is None


# ============================================================
# C-3：令牌撤销必须同时断开长连接
# ============================================================


def test_all_three_revocation_paths_disconnect_sockets(client, token_dispatcher, users, db_session, monkeypatch):
    """登出 / 改密码 / 停用 —— 三条路都必须是"作废令牌 **+** 断开长连接"。

    缺陷现场（2026-09-19 外部完整检查 C-3）：`tv`（令牌版本）只在 socket **握手**时校验一次，
    而 `disconnect` 是空实现 —— 于是"登出/改密/停用"之后旧令牌打 HTTP 全 401，
    **但那条已经建起来的长连接继续收推送**（站内信正文、单号、账本）。丢手机场景里这正是止损点。
    """
    from app.services import auth_service

    calls: list[tuple[int, str]] = []

    async def _fake_revoke(user_id: int, reason: str = "") -> None:
        calls.append((user_id, reason))

    # `auth_service` 是 `from … import revoke_user_sockets` 的绑定，补丁要打在它自己的命名空间上
    monkeypatch.setattr(auth_service, "revoke_user_sockets", _fake_revoke)

    # ⚠️ 顺序是刻意的：**登出放最后**。它会作废派单员自己的令牌（`token_version +1`），
    #    之后再拿同一串 token 调接口就是 401（第一版就是这么红的）。
    # ① 改密码 / ② 停用：用一个**新建的**账号，别把种子账号的密码改掉（共享测试库）
    import uuid

    phone = f"13922{uuid.uuid4().int % 1000000:06d}"
    r = client.post(
        "/api/v1/users",
        headers=auth_headers(token_dispatcher),
        json={"phone": phone, "full_name": "撤销用账号", "role": "shipper", "password": "pass12345"},
    )
    assert r.status_code in (200, 201), r.text
    uid = int(r.json()["id"])

    r = client.patch(
        f"/api/v1/users/{uid}",
        headers=auth_headers(token_dispatcher),
        json={"password": "newpass12345"},
    )
    assert r.status_code == 200, r.text
    assert calls == [(uid, "改密码")], calls

    calls.clear()
    r = client.patch(
        f"/api/v1/users/{uid}",
        headers=auth_headers(token_dispatcher),
        json={"is_active": False},
    )
    assert r.status_code == 200, r.text
    assert calls == [(uid, "账号被停用")], calls

    # ③ 登出
    calls.clear()
    assert client.post("/api/v1/auth/logout", headers=auth_headers(token_dispatcher)).status_code == 200
    assert calls == [(users["dispatcher"].id, "登出")], calls
    db_session.refresh(users["dispatcher"])
    assert users["dispatcher"].token_version >= 1, "登出必须让已发出的令牌失效"


@pytest.mark.asyncio
async def test_revoke_user_sockets_emits_then_disconnects_local(monkeypatch):
    """撤销的两半：先推 `session_revoked`（跨 worker 靠它让客户端自己断），再断本进程的连接。"""
    from app.core import socket_io as si

    events: list[tuple] = []
    disconnected: list[str] = []

    async def _emit(event, data, room=None):  # noqa: ANN001
        events.append((event, data, room))

    async def _disconnect(sid):  # noqa: ANN001
        disconnected.append(sid)

    async def _participants(room):  # noqa: ANN001
        yield ("sid-1", "eio-1")
        yield ("sid-2", "eio-2")

    monkeypatch.setattr(si.sio, "emit", _emit)
    monkeypatch.setattr(si.sio, "disconnect", _disconnect)
    monkeypatch.setattr(si, "_participants", _participants)

    await si.revoke_user_sockets(7, "登出")
    assert events == [("session_revoked", {"reason": "登出"}, "user_7")], events
    assert disconnected == ["sid-1", "sid-2"], "本进程里的连接必须真的被断开（旧客户端不认识那个事件）"


@pytest.mark.asyncio
async def test_participants_adapts_to_both_manager_shapes(monkeypatch):
    """`_participants` 要同时吃得下"异步生成器"和"普通生成器"两种管理器。

    ⚠️ 这不是洁癖：`AsyncManager.get_participants` 是**异步生成器**，而
    `AsyncRedisManager.get_participants` 是**普通生成器**（python-socketio 的实际形状）。
    只按其中一种写，另一种下撤销会**静默不生效**（异常被我们自己的兜底吞掉）。
    """
    from app.core import socket_io as si

    class _AsyncMgr:
        def get_participants(self, namespace, room):  # noqa: ANN001
            async def _gen():
                yield ("a", "ea")
            return _gen()

    class _SyncMgr:
        def get_participants(self, namespace, room):  # noqa: ANN001
            return iter([("b", "eb")])

    monkeypatch.setattr(si.sio, "manager", _AsyncMgr())
    assert [s for s, _ in [x async for x in si._participants("user_1")]] == ["a"]
    monkeypatch.setattr(si.sio, "manager", _SyncMgr())
    assert [s for s, _ in [x async for x in si._participants("user_1")]] == ["b"]
