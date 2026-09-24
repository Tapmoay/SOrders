import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import socketio
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import DataError, IntegrityError

from app.api.v1.router import api_router
from app.config import get_settings
from app.core.request_id import RequestIdFilter, RequestIdMiddleware
from app.core.socket_io import sio
from app.database import SessionLocal
from app.redis_client import redis_ok
from app.services.data_retention import run_daily_retention

settings = get_settings()
logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """把应用自己的日志接出来（**只配一次**，且不抢别人的配置）。

    ⚠️ 为什么必须有（2026-09-19 外部完整检查 R2-6）：全仓库**从来没有日志配置**
    （`basicConfig`/`dictConfig` 一处都没有），而 `uvicorn` 只给自己那几个 logger
    （`uvicorn`/`uvicorn.error`/`uvicorn.access`）装 handler，**root logger 是空的**。
    于是 `logging.getLogger("app.…").info(...)` 全部被 `lastResort`（只放 WARNING 以上）
    丢掉：生产 journal 里 289,926 行，**"数据保留治理完成"一行都没有** ——
    每天在物理删数据的那个任务，成功时是完全不可观测的，出事时也只有一行谁也看不到的日志。

    写在这里而不是日志配置文件：`uvicorn app.main:app` 就是进程入口，
    模块导入时配一次即可（也要覆盖 `python -m scripts.*` 这类不经过 lifespan 的入口）。
    已有 handler 时不覆盖（pytest 的日志插件、gunicorn、`--log-config` 都算"别人配好了"），
    所以它不会把测试输出或宿主环境的日志格式改掉。
    日志级别可用环境变量 `LOG_LEVEL` 调（默认 INFO）。
    """
    if "pytest" in sys.modules:
        # 测试里不接管日志：pytest 自己有 caplog/失败重放，抢过来只会让每个用例多刷一堆
        # 应用日志（400+ 个用例各起一次 lifespan，治理循环的 INFO 会铺满输出）。
        return
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        # 2026-09-24（整改阶段 8 ①）：日志带上**请求追踪 id** —— 报告 §15 要的第一件小事。
        # 每个请求一个 id（`core/request_id.py`）；并发时那串日志才第一次能按请求串起来。
        format="%(asctime)s %(levelname)s [%(name)s] [rid=%(request_id)s] %(message)s",
    )
    for _h in logging.getLogger().handlers:
        _h.addFilter(RequestIdFilter())


_configure_logging()

os.makedirs("uploads/delivery", exist_ok=True)
# ⛔ **不再重建 `uploads/exports/`**（2026-09-19 审计 R12-A3）：导出产物已改到 `exports/`
#    （不在公开静态目录之下）。而 `uploads/` 在生产是 nginx 用 alias **直出磁盘**的
#    （`/etc/nginx/conf.d/sorders.conf` 的 `location /static/uploads/`），凡落在这个目录里的
#    东西都是**匿名可下载**的。每次启动把这个空目录重建出来，等于给下一个往这里写文件的人
#    留了个陷阱。（老文件的读取路径仍然保留：`ledger_export_paths.LEGACY_UPLOAD_EXPORTS`。）
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

    # 请求追踪 id：最先挂上去的那个（异常也要能带上 id）+ 回写 X-Request-ID（见 core/request_id.py）
    application.add_middleware(RequestIdMiddleware)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # ⚠️ **浏览器只让脚本读"被显式暴露"的响应头**（2026-09-19 审计）：
        #    列表接口把"这次是不是被截断了"写在 `X-Truncated` / `X-Result-Limit` 里
        #    （响应体是裸数组，加不了元数据），而 `allow_headers` 只管**请求**头。
        #    不写这一条时：同源部署（nginx 反代 / Vite 代理）读得到，
        #    一旦把 H5 放到别的源上（`VITE_API_BASE_URL` 指到 API 域名），
        #    axios 拿到的 `headers['x-truncated']` 是 `undefined` —— **界面永远是"没有更多了"**，
        #    而这正是"派单员以为看到了全部订单"那条缺陷的静默版本。
        #    清单由 `_tools/qa/_check_pagination_wiring.py` 从客户端源码算出来对账。
        #    `Content-Disposition` 同理：导出下载要靠它取文件名
        #    （不暴露就只能用一个兜底名，用户拿到 `ledger-export-7.xlsx`，看不出这是哪份账）。
        expose_headers=["X-Truncated", "X-Result-Limit", "Content-Disposition"],
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

    # 唯一约束冲突 → **409 + 中文**（2026-09-19 审计）。
    #
    # 为什么必须收口：全库原来**没有 IntegrityError 处理器**，于是任何唯一约束冲突都会变成
    # `500 Internal Server Error`。而这类冲突恰恰是**正常业务**会遇到的：
    #   · 同一车牌建两次（`vehicles.plate_no` 唯一）；
    #   · 同一分类名建两次（`product_categories.name` 唯一）；
    #   · 同一挂账单位名建两次（`arrears_units.name` 唯一）；
    #   · 同一联系人电话建两次（`shipper_contacts` 的唯一约束）；
    #   · **并发/双击**提交同一条记录（先查后插在并发下必然撞约束）。
    # 用户看到"服务器内部错误"只会以为系统坏了、然后重试（把冲突刷得更多）；
    # 而这里能给出的信息是明确的："这条已经存在了，改一个再试"。
    @application.exception_handler(IntegrityError)
    async def _integrity_error(_request: Request, exc: IntegrityError) -> JSONResponse:
        logger.warning("唯一约束/外键冲突：%s", exc, exc_info=True)
        text = str(getattr(exc, "orig", exc)).lower()
        if "foreign key" in text or "1452" in text:
            detail = "这条记录引用了不存在的关联数据（可能刚被别处删掉了），请刷新后重新选择"
        elif "cannot be null" in text or "1048" in text:
            detail = "有必填项没填"
        else:
            detail = "已经有一条一模一样的记录了（同名/同号/同电话不能重复），请换一个再试"
        return JSONResponse(status_code=409, content={"detail": detail})

    @application.get("/static/uploads/{file_path:path}")
    def static_uploads(file_path: str):
        """静态文件服务（经应用层：防目录穿越；图片已由数据治理自动压缩归档）。
        客户端 URL 如 /static/uploads/delivery/{order_id}/{name}。"""
        # ⛔ `exports/` 一律不给（2026-09-19 审计）：账本导出产物里是货主名/商品/单价/总额/订单号，
        #    而这条路由**没有鉴权**（生产 nginx 还把 /static/uploads/ alias 直出磁盘）。
        #    以前文件名是 `ledger_{货主id}_{任务id}.xlsx` 这种可枚举的小整数 → 匿名就能拖走别家账本。
        #    产物现在写到 uploads **之外**的 `exports/`，只经带鉴权的
        #    `GET /api/v1/ledger/export-jobs/{id}/download` 取；这里再堵一道历史文件。
        if file_path.split("/", 1)[0] == "exports":
            raise HTTPException(status_code=404, detail="文件不存在")
        base = Path("uploads").resolve()
        target = (base / file_path).resolve()
        # ⚠️ 判据必须是**路径关系**，不能是字符串前缀（2026-09-19 审计 L-15）：
        #    原来是 `str(target).startswith(str(base))`，而 `uploads_evil/…` 的前缀**就是** `uploads/`
        #    的前缀 —— 于是 `/static/uploads/..%2Fuploads_evil%2Fx.txt`（点段被 `%2F` 编码后
        #    路由不做归一）真的以 200 读到了 uploads 之外的兄弟目录（实测复现，见
        #    `tests/test_audit_round24_hardening.py`）。`is_relative_to` 是按路径分量判的。
        if not target.is_relative_to(base) or not target.is_file():
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
