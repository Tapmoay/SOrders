# -*- coding: utf-8 -*-
"""图片归档：原始图保留 1 年，到期自动转「感知无损」压缩图（Q90 / 长边≤1920）。

## ⚠️ 压缩必须**原地替换**（2026-09-19 审计 R12-H2，真机/代码双证）
原来的实现是"生成 `<stem>.compressed.webp`，然后 `unlink` 原图"。听起来很干净，
但它和**库里存的东西**对不上：库里存的是
`/static/uploads/delivery/{order_id}/{uuid}.jpg`（`orders.py` 上传时就是这么写的），
而全仓库**没有任何地方**会把引用改写成 `.compressed.webp`——于是满 1 年之后：
- 每一张送达照片（货损、纠纷、对账的唯一影像证据）**404 / 白图**；
- 生成出来的 `.compressed.webp` 没有任何消费方，磁盘占用反而**变大**（同一张图存了两份）；
- 而且不可恢复：原图已经被物理删了。

这条是"清理删掉了还在用的数据"，且**第 366 天起 100% 必然发生**。

## 现在怎么做
- **文件名不变、内容替换**：把压缩后的图写回**同一个路径**，扩展名与内容保持一致
  （`.jpg/.jpeg` → JPEG q90，`.png` → PNG 优化，`.webp` → WebP q90）——
  这样"改 MIME / 改扩展名"的连带风险为零：nginx（生产把 `/static/uploads/` alias 直出磁盘）
  与 App 都只看扩展名，不需要任何"内容嗅探"赌运气。
- `.bmp` **不归档**（留在原地）：BMP 无法在保持扩展名的前提下变小，改名又会让库里的引用失效。
- 顺带清理历史遗留的孤儿 `.compressed.webp`（它们按定义没有任何引用）。

⚠️ 产品口径上有一处**取舍**（已写进台账，等用户拍板）：WebP q90 比 JPEG q90 再小约 25~35%。
要拿这部分空间，就得"改扩展名 + 同步改写库里的引用"，那是另一条改动链（要覆盖
orders 的 JSON 数组、products、shipper_addresses/locations 等多处），风险明显更高。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.order import Order
from app.models.product import Product
from app.models.shipper import ShipperAddress, ShipperLocation

logger = logging.getLogger(__name__)

ORIGINAL_RETENTION_DAYS = 365   # 原图保留 1 年
MAX_EDGE = 1920                 # 压缩图长边上限（票据/单号/地址等文字信息保持可读）
WEBP_QUALITY = 90               # 感知无损档：肉眼基本不可辨、细节信息完整保留
JPEG_QUALITY = 90

#: 归档**允许解码**的最大像素数。超过就原图不动（连解码都不做）。
#:
#: ⚠️ 为什么必须有这个上限（2026-09-19 外部完整检查 C-7）：`PIL.Image.open` 只读 header，
#: 真正吃内存的是随后的解码，而峰值 ≈ 宽×高×通道数 —— **完全由客户端声明的尺寸决定**。
#: 实测：一张不到 1MB 的图声明 9000×9000（8100 万像素）就能让本进程吃到 260MB 以上。
#: PIL 自己的 `MAX_IMAGE_PIXELS`（8947 万）只**告警不拦**，要到它的 2 倍才抛
#: `DecompressionBombError`（实测 20000×20000 在 `open` 阶段就抛，反而便宜）——
#: 所以 8947 万~1.79 亿这一段是**真的会把内存吃满**的区间。
#: 取 6000 万：按 RGBA 4 字节算解码峰值约 240MB，是"单张图可以接受的上限"；
#: 而归档的目标只是把长边压到 [MAX_EDGE]，上传端本身还有 4~8MB 体积限制，
#: 业务里不存在"必须靠一张 6000 万像素原图才能看清"的场景。
MAX_ARCHIVE_PIXELS = 60_000_000

#: 无引用图片的宽限期（天）：上传接口先落盘、用户随后才把 URL 存进库（可能在填表单）。
#: 比表单可能的滞留时间长得多，比"一年后压缩原图"短得多。
ORPHAN_IMAGE_GRACE_DAYS = 7

#: 「库里还在引用 `uploads/` 下图片」的**全部**列。`(模型, 列名, 是否是 JSON 数组)`。
#:
#: ⚠️ 这份清单是"删除文件"这件事的**唯一**判据来源：漏一列 = 删掉还在用的图（不可恢复）。
#: 所以它不许靠人记着更新：`_tools/qa/_check_image_refs.py` 会**自己扫** `app/models/`
#: 里所有 `image_url*` 列，任何一个不在这张表里就报错（清单过期时先报错，而不是安静地删图）。
#: ⚠️ `orders.delivery_photo_urls`（送达凭证）**故意不在**这里，见 `purge_orphan_images`。
REFERENCED_IMAGE_COLUMNS: tuple[tuple[type, str, bool], ...] = (
    (Product, "image_url", False),
    (ShipperAddress, "image_url", False),
    (ShipperAddress, "image_urls", True),
    (ShipperLocation, "image_url", False),
    (ShipperLocation, "image_urls", True),
    (Order, "address_image_url", False),
    (Order, "image_urls", True),
)

#: 扩展名 → PIL 保存格式。**扩展名与写出的格式必须一致**（见模块头的说明）。
_FORMAT_BY_SUFFIX = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}


def _save_kwargs(fmt: str) -> dict:
    if fmt == "JPEG":
        return {"quality": JPEG_QUALITY, "optimize": True, "progressive": True}
    if fmt == "WEBP":
        return {"quality": WEBP_QUALITY, "method": 6}
    return {"optimize": True}  # PNG


def compress_image(src: Path) -> Path | None:
    """**原地**压缩：[src] 的内容换成缩小后的图，路径与扩展名都不变。

    返回 [src]（成功）或 None（跳过 → 原样保留，单张失败不影响整体）。
    """
    fmt = _FORMAT_BY_SUFFIX.get(src.suffix.lower())
    if fmt is None:
        return None
    # 临时名带随机段：两个执行者同时压同一张图时不会互相踩（原来用固定的
    # `x.jpg.archiving`，实测 2 线程 × 40 轮里有 4 张**根本没压成**、还有 30 轮是一方失败）。
    # 互斥的正解是 `run_daily_retention` 里的跨进程锁，这里是"就算锁没生效也不会互相毁文件"。
    tmp = src.with_name(f"{src.name}.{uuid4().hex}.archiving")
    try:
        im = Image.open(src)          # ← 只读 header，不解码
        w, h = im.size
        # ⚠️ 必须在**任何**会触发解码的调用之前判（`exif_transpose`/`convert`/`resize`/`save`
        #    全都会 load）。见 `MAX_ARCHIVE_PIXELS` 的说明：这里是唯一的内存闸。
        if w * h > MAX_ARCHIVE_PIXELS:
            logger.warning(
                "图片过大，跳过归档（原图保留）：%s 声明尺寸 %sx%s = %s 万像素，上限 %s 万",
                src, w, h, w * h // 10000, MAX_ARCHIVE_PIXELS // 10000,
            )
            return None
        im = ImageOps.exif_transpose(im)
        if fmt == "JPEG":
            im = im.convert("RGB")
        elif im.mode not in ("RGB", "RGBA", "L", "LA"):
            im = im.convert("RGBA")
        w, h = im.size
        if w > MAX_EDGE or h > MAX_EDGE:
            scale = MAX_EDGE / max(w, h)
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        # 先写临时文件再替换：中途失败不会留下半张图（原图还在）
        im.save(tmp, fmt, **_save_kwargs(fmt))
        tmp.replace(src)
        return src
    except Exception:
        logger.warning("图片压缩失败（保留原图）: %s", src, exc_info=True)
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return None


def archive_images_older_than(days: int = ORIGINAL_RETENTION_DAYS) -> int:
    """扫描 uploads/{delivery,products,locations} 下超过 days 天的原图 → **原地**压缩。
    返回压缩成功数量。文件名不变，所以库里的引用一直有效。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    done = 0
    for base in (Path("uploads") / "delivery", Path("uploads") / "products", Path("uploads") / "locations"):
        if not base.is_dir():
            continue
        for f in base.rglob("*"):
            if not f.is_file() or f.suffix.lower() not in _FORMAT_BY_SUFFIX:
                continue
            try:
                # ⚠️ 无保护的 stat 会抛 FileNotFoundError（另一个 worker 刚删掉它）——
                #    那不是 DBAPIError，没有任何地方接得住，会把当天的治理整轮打断。
                mtime = f.stat().st_mtime
            except OSError:
                continue
            if mtime > cutoff.timestamp():
                continue
            if compress_image(f) is not None:
                done += 1
                logger.info("图片自动压缩（原地）：%s", f)
    return done


def purge_orphan_compressed() -> int:
    """清理历史遗留的 `<stem>.compressed.webp` 与中断留下的 `*.archiving`。

    - `.compressed.webp` 是旧实现（改名 + 删原图）留下的产物，**按定义没有任何引用**：
      库里存的都是原文件名。留着只会白占磁盘、还会让人以为"压缩后要访问这个文件"。
    - `*.archiving` 是压缩到一半进程被杀留下的临时文件（随机段临时名之后更是**必然**
      不会被下一次覆盖）——同样没有任何引用，且扩展名不在归档扫描范围内，不清就永远留着。
    """
    removed = 0
    for base in (Path("uploads") / "delivery", Path("uploads") / "products", Path("uploads") / "locations"):
        if not base.is_dir():
            continue
        for pattern in ("*.compressed.webp", "*.archiving"):
            for f in base.rglob(pattern):
                try:
                    f.unlink(missing_ok=True)
                    removed += 1
                except OSError:
                    logger.warning("清理无引用的中间文件失败：%s", f, exc_info=True)
    if removed:
        logger.info("清理孤儿文件 %s 个（旧实现改名 / 中断的压缩临时文件）", removed)
    return removed


def referenced_image_urls(db: Session) -> set[str]:
    """库里**还在引用**的全部图片 URL（含软删行）。

    ⚠️ 软删行必须算进来（`shipper_addresses` / `shipper_locations` 有回收站 + 恢复端点）：
    按 `is_deleted` 过滤会让"删掉又恢复"的地点永久丢图——而那是**不可恢复**的。
    """
    out: set[str] = set()
    for model, col, is_list in REFERENCED_IMAGE_COLUMNS:
        for (value,) in db.execute(select(getattr(model, col))).all():
            if not value:
                continue
            if not is_list:
                out.add(str(value).strip())
                continue
            try:
                items = json.loads(value) if isinstance(value, str) else value
            except (TypeError, ValueError):
                continue                      # 毒化过的 JSON 列：跳过，不因它中断整轮治理
            if isinstance(items, list):
                out.update(str(i).strip() for i in items if i)
    out.discard("")
    return out


def purge_orphan_images(db: Session, days: int = ORPHAN_IMAGE_GRACE_DAYS) -> int:
    """删除**没有任何行引用**的图片文件：`uploads/locations/` 与 `uploads/products/`。

    ### 为什么需要（2026-09-19 外部完整检查 C-6）
    上传接口的设计是"先落盘、再把 URL 存进库"（`POST /shipper/locations/image` 直接返回
    `/static/uploads/locations/{uuid}.jpg`，用户随后保存地点才建立引用）。于是有两条永久堆积路径：
    ① 用户传了图又放弃表单 → 这个文件**永远**没有人引用；
    ② 地点/商品被删 → 引用没了，文件还在。
    而治理原来只清 `uploads/delivery/{order_id}`（随订单物理删除走），`locations/` 下
    **一行删除代码都没有** —— 实测 42 个文件跑完整条治理链前后不变。nginx 也没有速率限制，
    所以这是**唯一永久且无限的**磁盘堆积路径。

    ### 为什么按"引用"而不是按"时间"清
    时间是错的尺子：图存进库之后就一直有用（地点可能两年没人碰但要能从订单里点开）。
    判据只能是"还有没有任何一行指着它"。

    ### 为什么**不含** `delivery/`
    送达照片是货损/纠纷的唯一影像证据，它们的生命周期**绑在订单上**：
    `delete_orders_by_ids` 已经按订单 id 精确清理（订单行还在就一张都不动）。
    把它改写成"按引用扫"会让"某次引用写坏"直接变成"删掉凭证"，风险明显更大。

    `days` 是宽限期（见 `ORPHAN_IMAGE_GRACE_DAYS`）：只删"早就没人引用"的，
    不碰"刚上传、用户正在填表单"的。
    """
    keep = referenced_image_urls(db)
    cutoff = time.time() - days * 86400
    uploads = Path("uploads")
    removed = 0
    for sub in ("locations", "products"):
        base = uploads / sub
        if not base.is_dir():
            continue
        for f in base.rglob("*"):
            if not f.is_file():
                continue
            try:
                if f.stat().st_mtime > cutoff:
                    continue                  # 宽限期内：可能还没被保存进库
            except OSError:
                continue                      # 另一个执行者刚删掉它
            url = f"/static/uploads/{f.relative_to(uploads).as_posix()}"
            if url in keep:
                continue
            try:
                f.unlink()
                removed += 1
            except OSError:
                logger.warning("清理无引用图片失败：%s", f, exc_info=True)
    if removed:
        logger.info("清理无引用图片 %s 个（locations/products，宽限 %s 天）", removed, days)
    return removed
