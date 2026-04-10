import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.config import get_settings
from app.core.socket_io import sio
from app.database import SessionLocal
from app.redis_client import redis_ok
from app.services.cancelled_order_retention import purge_expired_cancelled_orders

settings = get_settings()
logger = logging.getLogger(__name__)

os.makedirs("uploads/delivery", exist_ok=True)
os.makedirs("uploads/exports", exist_ok=True)
os.makedirs("uploads/products", exist_ok=True)


def _purge_cancelled_sync() -> None:
    db = SessionLocal()
    try:
        purge_expired_cancelled_orders(db)
        db.commit()
    except Exception:
        logger.exception("清理过期已撤销订单失败")
        db.rollback()
    finally:
        db.close()


async def _purge_cancelled_loop() -> None:
    """启动后立即执行一次，之后每 24 小时清理一次。"""
    while True:
        await asyncio.to_thread(_purge_cancelled_sync)
        await asyncio.sleep(86400)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """库表迁移在 `app.database` 导入时已执行 `bootstrap_schema(engine)`。"""
    task = asyncio.create_task(_purge_cancelled_loop())
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
    application.mount("/static/uploads", StaticFiles(directory="uploads"), name="static_uploads")

    @application.get("/health")
    def health() -> dict[str, Any]:
        body: dict[str, Any] = {
            "status": "ok",
            "version": settings.app_version,
            **redis_ok(),
        }
        return body

    return application


fastapi_app = create_fastapi_app()

app = socketio.ASGIApp(
    sio,
    other_asgi_app=fastapi_app,
    socketio_path="socket.io",
)
