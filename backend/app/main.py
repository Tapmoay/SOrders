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
from app.redis_client import redis_ok

settings = get_settings()

os.makedirs("uploads/delivery", exist_ok=True)
os.makedirs("uploads/exports", exist_ok=True)
os.makedirs("uploads/products", exist_ok=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """库表迁移在 `app.database` 导入时已执行 `bootstrap_schema(engine)`。"""
    yield


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
        body: dict[str, Any] = {"status": "ok", **redis_ok()}
        return body

    return application


fastapi_app = create_fastapi_app()

app = socketio.ASGIApp(
    sio,
    other_asgi_app=fastapi_app,
    socketio_path="socket.io",
)
