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

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

ORIGINAL_RETENTION_DAYS = 365   # 原图保留 1 年
MAX_EDGE = 1920                 # 压缩图长边上限（票据/单号/地址等文字信息保持可读）
WEBP_QUALITY = 90               # 感知无损档：肉眼基本不可辨、细节信息完整保留
JPEG_QUALITY = 90

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

    返回 [src]（成功）或 None（失败 → 原样保留，单张失败不影响整体）。
    """
    fmt = _FORMAT_BY_SUFFIX.get(src.suffix.lower())
    if fmt is None:
        return None
    tmp = src.with_name(src.name + ".archiving")
    try:
        im = Image.open(src)
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
    """清理历史遗留的 `<stem>.compressed.webp`。

    它们是旧实现（改名 + 删原图）留下的产物，**按定义没有任何引用**：
    库里存的都是原文件名。留着只会白占磁盘、还会让人以为"压缩后要访问这个文件"。
    """
    removed = 0
    for base in (Path("uploads") / "delivery", Path("uploads") / "products", Path("uploads") / "locations"):
        if not base.is_dir():
            continue
        for f in base.rglob("*.compressed.webp"):
            try:
                f.unlink(missing_ok=True)
                removed += 1
            except OSError:
                logger.warning("清理孤儿压缩图失败：%s", f, exc_info=True)
    if removed:
        logger.info("清理孤儿压缩图 %s 个（旧实现改名留下的、无引用的文件）", removed)
    return removed
