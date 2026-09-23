"""`uploads/delivery/{order_id}/` 的生命周期：**删目录 ≠ 这一单独占**。

## 两个方向都会出事（2026-09-23 第 18 轮并行渗透 B7-1/B7-2，高）

**① 删多了（不可恢复）**：`uploads/delivery/{order_id}/` 里不只是送达凭证 ——
"补地址参考图"（`POST /orders/{id}/address-image`）也落在这个目录，而那张图的 URL 会被
`place_service.attach_order_photo` 写进**共享地点库** `places.image_urls` 与上传人/货主的
`shipper_locations.image_urls`（三种角色都看得到）。原来的清理是**按 id 整目录删**：
订单软删满 30 天（或满 3 年）物理清理时，**仍在被参考的那张照片**被一起 unlink，
地点缩略图永久白图 —— 而且这是**到期必然发生**的，不是概率事件。

**② 删少了（永久堆积）**：`purge_orphan_images` 原来只扫 `locations/` 与 `products/`，
delivery 明确排除；`delete_orders_by_ids` 又只在**订单行被物理删除**时才清目录。
于是三条只写盘、不建引用的路径（司机拿了 URL 没走完配送 / `complete-with-upload`
业务校验失败回滚但文件已落盘 / 一次多选里第 N 张类型不对而前 N-1 张已落盘）
产生的文件**谁都不删**：本机实测 534 个文件里 0 个被引用。

## 判据（这一条测试要同时钉住两边）
- 送达凭证（`orders.delivery_photo_urls`）**永远**受保护；
- 地点/共享库/地址簿里出现的 delivery URL 也受保护；
- 谁都不引用的那个文件**要**被清掉（否则"改了等于没改"）。

⚠️ 测试用 `monkeypatch.chdir(tmp_path)`：`purge_orphan_images` 走的是**相对路径**
`Path("uploads")`，不换根的话它会扫到**本机开发库真实的 500 多个上传文件**
（而测试库里没有那些引用）→ 一次测试就把真实开发数据删掉一批。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app.models import Order, Place
from app.models.enums import OrderStatus
from app.services.image_archive import (
    delivery_photo_urls,
    protected_image_urls,
    purge_orphan_images,
    referenced_image_urls,
)


def _order(db_session, no: str, photo_urls: list[str]) -> Order:
    o = Order(
        order_no=no,
        shipper_id=None,
        status=OrderStatus.DELIVERED,
        order_date=date(2026, 9, 10),
        delivery_photo_urls=photo_urls,
    )
    db_session.add(o)
    db_session.commit()
    return o


def _place(db_session, name: str, url: str, *, is_deleted: bool = False) -> Place:
    # ⚠️ `places.lat/lng` 是 NOT NULL（位置本来就得有坐标）——不传会 IntegrityError。
    p = Place(
        name=name,
        lat=23.1,
        lng=113.2,
        image_urls=json.dumps([url], ensure_ascii=False),
        image_url=url,
        is_deleted=is_deleted,
    )
    db_session.add(p)
    db_session.commit()
    return p


def test_送达凭证与地点照片都在保护集里(db_session):
    """保护集必须是**两类的并集**：通用引用清单 + 送达凭证。"""
    o = _order(db_session, "SO-PROTECT-1", ["/static/uploads/delivery/1/take.jpg"])
    _place(db_session, "保护集探针地点", "/static/uploads/delivery/1/place.jpg")

    generic = referenced_image_urls(db_session)
    delivery = delivery_photo_urls(db_session)
    both = protected_image_urls(db_session)

    assert "/static/uploads/delivery/1/place.jpg" in generic, "地点库引用的图必须在通用清单里"
    assert "/static/uploads/delivery/1/take.jpg" not in generic, (
        "送达凭证**故意**不在通用清单里（它的生命周期绑订单，由订单清理按 id 处理）"
    )
    assert "/static/uploads/delivery/1/take.jpg" in delivery
    assert both == generic | delivery
    assert o.id is not None


def test_按引用清delivery_只删没人引用的那些(db_session, tmp_path, monkeypatch):
    """三个文件：只被订单声明 / 只被地点引用 / 谁都不引用 → 只有第三个该被删。"""
    d = tmp_path / "uploads" / "delivery" / "77"
    d.mkdir(parents=True)
    kept_by_order = d / "take.jpg"
    kept_by_place = d / "place.jpg"
    orphan = d / "abandoned.jpg"
    for f in (kept_by_order, kept_by_place, orphan):
        f.write_bytes(b"fake-jpeg")

    _order(db_session, "SO-PURGE-1", [f"/static/uploads/delivery/77/{kept_by_order.name}"])
    _place(db_session, "按引用清探针地点", f"/static/uploads/delivery/77/{kept_by_place.name}")

    monkeypatch.chdir(tmp_path)          # ⛔ 不换根会去扫真实开发库的 uploads/
    removed = purge_orphan_images(db_session, days=0)

    assert removed == 1, f"应当只清掉那个谁都不引用的文件，实际清了 {removed} 个"
    assert orphan.exists() is False, "没人引用的孤儿文件必须被清掉（否则磁盘只增不减）"
    assert kept_by_order.exists(), "**送达凭证被删了** —— 那是货损/纠纷的唯一影像证据"
    assert kept_by_place.exists(), (
        "**地点库还在引用的照片被删了** —— 这是不可恢复的（原图已 unlink），"
        "而它正是第 18 轮 B7-1 记的那条"
    )


def test_订单物理清理不删still_referenced的照片(db_session, tmp_path, monkeypatch):
    """**这一条是本轮那个"高"的确证**：按 id 整目录删会把共享地点库还在用的图删掉。

    路径：补地址图落在 `uploads/delivery/{order_id}/` → URL 被写进共享地点库
    → 订单软删满 30 天被物理清理 → 原实现 `for f in d.iterdir(): f.unlink()` +
    `d.rmdir()` 把整目录清掉（**包括那张还在被参考的**）→ 地点缩略图永久白图。
    现在：删之前先算一次保护集，被引用的留下；目录非空就不 rmdir。
    """
    from app.services.data_retention import delete_orders_by_ids

    o = _order(db_session, "SO-PURGE-TARGET", ["/static/uploads/delivery/{}/take.jpg".format("?")])
    oid = o.id
    d = tmp_path / "uploads" / "delivery" / str(oid)
    d.mkdir(parents=True)
    take = d / "take.jpg"          # 这张单自己的送达凭证
    shared = d / "address.jpg"     # 补地址图：URL 已经进了共享地点库
    take.write_bytes(b"x")
    shared.write_bytes(b"x")
    # 凭证写回这一单（真实形状：`delivery_photo_urls` 里是完整 URL）
    o.delivery_photo_urls = [f"/static/uploads/delivery/{oid}/{take.name}"]
    _place(db_session, "共享地点库探针", f"/static/uploads/delivery/{oid}/{shared.name}")
    db_session.commit()

    monkeypatch.chdir(tmp_path)
    assert delete_orders_by_ids(db_session, [oid]) == 1

    assert shared.exists(), (
        "**共享地点库还在引用的地址参考图被订单清理删掉了** —— "
        "它不属于这张单，原图已 unlink、不可恢复（第 18 轮 B7-1）"
    )
    assert take.exists() is False, (
        "这张单自己的送达凭证应当随单清理（它还留在磁盘上说明清理漏了）"
    )
    assert d.is_dir(), "目录里还有被引用的照片 → 不许 rmdir（非空自然删不掉）"


def test_宽限期内的新文件不动(db_session, tmp_path, monkeypatch):
    """`days` 是给"刚上传、用户还在填表单"留的窗口（默认 7 天）。"""
    d = tmp_path / "uploads" / "locations"
    d.mkdir(parents=True)
    fresh = d / "just-uploaded.jpg"
    fresh.write_bytes(b"x")

    monkeypatch.chdir(tmp_path)
    assert purge_orphan_images(db_session, days=7) == 0
    assert fresh.exists()


def test_保护集不看软删状态(db_session, tmp_path, monkeypatch):
    """软删的地点（回收站里，有恢复端点）也必须保护 —— 否则"删掉又恢复"的地点永久丢图。"""
    d = tmp_path / "uploads" / "locations"
    d.mkdir(parents=True)
    f = d / "trashed-place.jpg"
    f.write_bytes(b"x")
    p = Place(
        name="软删地点探针",
        lat=23.1,
        lng=113.2,
        image_urls=json.dumps([f"/static/uploads/locations/{f.name}"]),
        is_deleted=True,
    )
    db_session.add(p)
    db_session.commit()

    monkeypatch.chdir(tmp_path)
    purge_orphan_images(db_session, days=0)
    assert f.exists(), "回收站里的地点（可恢复）的照片被删掉了"
    assert Path(d).is_dir()
