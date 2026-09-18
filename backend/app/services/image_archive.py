# -*- coding: utf-8 -*-
"""图片归档：原始图保留 1 年，到期自动转「感知无损」压缩图（WebP Q90 / 长边≤1920）。
在数据治理循环（每日一次）中扫描；单张失败不影响整体（保留原图兜底）。
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


def compress_image(src: Path) -> Path | None:
    """生成同目录 <stem>.compressed.webp（EXIF 旋转 → 等比缩小 → Q90 WebP）。
    成功返回压缩图路径；失败返回 None（调用方保留原图兜底）。"""
    try:
        im = Image.open(src)
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
        else:
            im = im.convert("RGB")
        w, h = im.size
        if w > MAX_EDGE or h > MAX_EDGE:
            scale = MAX_EDGE / max(w, h)
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        dst = src.with_name(src.stem + ".compressed.webp")
        im.save(dst, "WEBP", quality=WEBP_QUALITY, method=6)
        return dst
    except Exception:
        logger.warning("图片压缩失败（保留原图）: %s", src, exc_info=True)
        return None


def archive_images_older_than(days: int = ORIGINAL_RETENTION_DAYS) -> int:
    """扫描 uploads/{delivery,products,locations} 下超过 days 天的原图 → 压缩并删除原图。
    返回压缩成功数量。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    done = 0
    for base in (Path("uploads") / "delivery", Path("uploads") / "products", Path("uploads") / "locations"):
        if not base.is_dir():
            continue
        for f in base.rglob("*"):
            if not f.is_file() or f.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp"}:
                continue
            if f.suffix.lower() in {".webp"} or ".compressed.webp" in f.name:
                continue
            age = f.stat().st_mtime
            if age > cutoff.timestamp():
                continue
            dst = compress_image(f)
            if dst is None:
                continue
            # 原子替换：压缩成功后才删除原图
            f.unlink(missing_ok=True)
            done += 1
            logger.info("图片自动压缩：%s → %s", f, dst)
    return done
