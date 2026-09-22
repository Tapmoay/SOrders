"""把上传文件读进内存的**唯一一处**实现——带硬上限。

## 为什么单独做成一个函数（2026-09-23 全项目复核 G8）

复核发现**5 个上传端点全是同一个形状**：先 `raw = await file.read()` 把整个请求体读进内存，
下一行才 `if len(raw) > 8 * 1024 * 1024: raise ...`。也就是说"上限"挡的是**读进内存之后**的处理，
**挡不住内存本身** —— 客户端传一个 2GB 的 xlsx，进程先被撑到 OOM，然后才轮到那句"文件过大"。
（生产前面有 nginx `client_max_body_size 32m` 兜着，所以外部能打到的最大是 32MB；
 本机直连 uvicorn 时没有任何上限，而 AI 的附件通道正好走这条路。）

## 判据

`file.read(n)` **最多读 n 字节**，所以"读 上限+1 字节"就能同时做到两件事：
① 内存占用与文件大小无关（恒定 ≤ 上限+1）；
② 还能分辨"刚好等于上限"（允许）与"超过上限"（拒绝）。
多读的那 1 个字节只用来做这个判断，不参与后续解析。

判据钉在 `_tools/qa/_check_upload_limits.py`：**凡是收了 `UploadFile` 的端点都必须走这里**
（或在那张表里写清理由）。
"""
from __future__ import annotations

from fastapi import HTTPException, UploadFile

#: 单张图片的上限（商品图 / 地点图 / 补地点图都用它）。
MAX_IMAGE_BYTES = 4 * 1024 * 1024

#: 送货照片的上限（比别的图宽一倍）：司机在现场拍的，可能没压缩过。
#: 这个数**沿用原来的 8MB**，本轮只改"什么时候判"，不改"判多少"。
MAX_DELIVERY_PHOTO_BYTES = 8 * 1024 * 1024

#: 表格类附件的上限（与 `services/sheet_parser.py::MAX_BYTES` 一致；那边是"解析"的上限，
#: 这边是"读进内存"的上限，两个数必须同源，否则会出现"读进来了、解析拒了"的白读）。
MAX_SHEET_BYTES = 8 * 1024 * 1024


async def read_limited(file: UploadFile, limit: int, *, detail: str | None = None) -> bytes:
    """读上传文件，超过 `limit` 字节立刻 400 —— **绝不把整个请求体读进内存**。

    `detail` 不传时给一句通用的话；传了就原样用（各端点原来的提示语保持不变，
    免得改掉用户已经熟悉的错误文案）。
    """
    raw = await file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(
            status_code=400,
            detail=detail or f"文件过大（最大 {limit // 1024 // 1024}MB）",
        )
    return raw
