import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import socketio
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import DataError

from app.api.v1.router import api_router
from app.config import get_settings
from app.core.socket_io import sio
from app.database import SessionLocal
from app.redis_client import redis_ok
from app.services.data_retention import run_daily_retention

settings = get_settings()
logger = logging.getLogger(__name__)

os.makedirs("uploads/delivery", exist_ok=True)
os.makedirs("uploads/exports", exist_ok=True)
os.makedirs("uploads/products", exist_ok=True)


def _retention_sync() -> None:
    db = SessionLocal()
    try:
        r = run_daily_retention(db)
        logger.info("数据保留治理完成: %s", r)
    except Exception:
        logger.exception("数据保留治理失败")
        db.rollback()
    finally:
        db.close()


async def _retention_loop() -> None:
    """数据保留治理：启动后立即执行一次，之后每 24 小时一次。
    治理内容（用户拍板 2026-09-04）：业务数据 3 年 / 软删除隔离 30 天 /
    原始图片 1 年后自动压缩为感知无损 WebP。"""
    while True:
        await asyncio.to_thread(_retention_sync)
        await asyncio.sleep(86400)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """库表迁移在 `app.database` 导入时已执行 `bootstrap_schema(engine)`。"""
    task = asyncio.create_task(_retention_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def create_fastapi_app() -> FastAPI:
    application = FastAPI(title=settings.app_name, lifespan=lifespan)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(api_router, prefix=settings.api_v1_prefix)

    # ---- 校验失败：422 的 body 换成人话（状态码不变） ----
    # Pydantic 的英文结构体会被手机界面原样摆给用户、被 AI 抄进回答里，
    # 而这类错误恰恰全都能自助修好。见 `app/core/validation_errors.py`。
    from app.core.validation_errors import install as install_validation_errors

    install_validation_errors(application)

    # ---- 超出数据库范围的数值：映射成 400，而不是 500 ----
    #
    # 缺陷现场（2026-09-18 模糊测试发现）：`POST /products {"stock": 99999999999999999999}`、
    # `POST /customers {"user_id": …20 位…}`、`POST /expenses`、`POST /ledger/entries`
    # 都会在 `db.flush()` 抛 `OverflowError: Python int too large to convert to SQLite INTEGER`
    # → FastAPI 默认回 500「Internal Server Error」。生产是 MySQL，同样输入会变成
    # `DataError: Out of range value`（一样是 500）。
    #
    # 为什么不逐个字段加 `le=`：这类字段（各种 *_id / 数量）散在十几个 schema 里，
    # 加一遍必然漏；而**判据其实是同一个**——"这个数根本存不进数据库"。
    # 所以按异常类型统一收口，并且**记日志**：映射不是吞掉，真出问题时日志里有栈。
    # 逐字段加边界仍然是更好的做法，这条是兜底。
    @application.exception_handler(OverflowError)
    async def _overflow(_request: Request, exc: OverflowError) -> JSONResponse:
        logger.warning("数值超出数据库可存范围：%s", exc, exc_info=True)
        return JSONResponse(
            status_code=400,
            content={"detail": "数值超出可保存范围：编号、数量请填正常的数字（整数最多 19 位）"},
        )

    @application.exception_handler(DataError)
    async def _data_error(_request: Request, exc: DataError) -> JSONResponse:
        logger.warning("写入被数据库拒绝（超范围/超长）：%s", exc, exc_info=True)
        return JSONResponse(
            status_code=400,
            content={"detail": "填写的内容超出可保存范围：数字太大或文字太长，请改小一些"},
        )

    @application.get("/static/uploads/{file_path:path}")
    def static_uploads(file_path: str):
        """静态文件服务（经应用层：防目录穿越；图片已由数据治理自动压缩归档）。
        客户端 URL 如 /static/uploads/delivery/{order_id}/{name}。"""
        base = Path("uploads").resolve()
        target = (base / file_path).resolve()
        if not str(target).startswith(str(base)) or not target.is_file():
            raise HTTPException(status_code=404, detail="文件不存在")
        suffix = target.suffix.lower()
        media_type = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".webp": "image/webp", ".bmp": "image/bmp", ".pdf": "application/pdf",
            # .apk 必须显式写出来：Starlette 的 FileResponse 在 media_type=None 且
            # mimetypes 猜不出后缀时**会退回 text/plain**。于是安装包被当文本发出去，
            # 手机浏览器拿到 text/plain 会试图把几十 MB 二进制当文本渲染（现象就是
            # "下载极慢、下完还打不开"），而不是存成文件。
            ".apk": "application/vnd.android.package-archive",
        }.get(suffix)
        # 安装包明确标成"下载"并给一个固定文件名，别让浏览器/下载器自己猜
        headers = (
            {"Content-Disposition": 'attachment; filename="' + target.name + '"'}
            if suffix == ".apk"
            else None
        )
        return FileResponse(target, media_type=media_type, headers=headers)

    @application.get("/health")
    def health() -> dict[str, Any]:
        body: dict[str, Any] = {
            "status": "ok",
            "version": settings.app_version,
            **redis_ok(),
        }
        return body

    @application.get("/api/v1/system/app-version")
    def app_version() -> dict[str, Any]:
        """App 检查更新：返回部署时写入 uploads/app/version.json 的版本信息。"""
        p = Path("uploads/app/version.json")
        if not p.is_file():
            return {"version": None, "url": None, "note": ""}
        try:
            import json as _json

            return _json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {"version": None, "url": None, "note": ""}

    return application


fastapi_app = create_fastapi_app()

app = socketio.ASGIApp(
    sio,
    other_asgi_app=fastapi_app,
    socketio_path="socket.io",
)
