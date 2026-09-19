from datetime import datetime, timedelta, timezone
import logging
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

logger = logging.getLogger(__name__)

#: 已知的**弱/公开**密钥：出现在仓库、文档、示例里的那些一律不认。
#: 为什么要有这张表而不是"只判断空"：改配置的人最容易做的动作就是把它设回示例串
#: （或者从 README 复制），而那一刻系统看起来"配好了"——这正是最难发现的状态。
WEAK_JWT_SECRETS = frozenset(
    {
        "change-me-in-production-use-openssl-rand-hex-32",
        "change-me",
        "changeme",
        "secret",
        "sorders",
        "sorders-prod-secret-key-2026-change-in-production",
        "test",
        "dev",
    }
)

#: 低于这个长度的 HS256 密钥没有实际强度（32 字符 = 256 bit 的量级起步）
MIN_SECRET_LEN = 32


#: 回落密钥的落盘位置：**必须共享**，否则多 worker 各生成一个 → token 随机失效。
#: 放在 backend/ 下（与 sorders.db 同级），权限 600。⚠️ 这是一条**活密钥**，两道防线都在：
#: ① `.gitignore` 的 `.jwt_secret*` 规则忽略它；② `_tools/qa/_check_secrets.py` 认得"整行只有
#: 一条长随机串"这个形状。**改动前这里写着「已被 .gitignore 覆盖」，而那是假的**——
#: 2026-09-19 审计实测 `git check-ignore` 退出码 1、文件是未跟踪状态，`git add -A` 即可把它
#: 推进这个**公开**仓库（那等于把签名材料交出去：任何人都能签发派单员 token）。
#: 所以：改这两处任何一处之前，先跑一遍 `python _tools/qa/_check_secrets.py`。
FALLBACK_SECRET_FILE = Path(__file__).resolve().parents[2] / ".jwt_secret.local"


def _fallback_secret(why: str) -> str:
    """生成/复用一个**本地开发用**的随机密钥，并留下痕迹。

    为什么要落盘而不是每次 `secrets.token_urlsafe()`：
    生产是 `uvicorn --workers 2`，两个进程各自随机会导致"一半请求 401"这种极难排查的现象
    （用户表现为随机被踢下线）。落盘后所有 worker 读到同一个值，本机开发也不再一重启就掉登录。
    """
    try:
        if FALLBACK_SECRET_FILE.exists():
            existing = FALLBACK_SECRET_FILE.read_text(encoding="utf-8").strip()
            if len(existing) >= MIN_SECRET_LEN:
                logger.warning(
                    "%s —— 正在使用本地回落密钥 %s（仅限开发机；生产请在 .env 配置 JWT_SECRET_KEY）",
                    why, FALLBACK_SECRET_FILE,
                )
                return existing
        fresh = secrets.token_urlsafe(48)
        FALLBACK_SECRET_FILE.write_text(fresh, encoding="utf-8")
        try:
            FALLBACK_SECRET_FILE.chmod(0o600)
        except OSError:  # Windows 上 chmod 能力有限，忽略
            pass
        logger.warning(
            "%s —— 已生成新的本地回落密钥并写入 %s（生产请在 .env 配置 JWT_SECRET_KEY）",
            why, FALLBACK_SECRET_FILE,
        )
        return fresh
    except OSError as exc:  # 落盘失败（只读目录等）：退回进程内随机，但要说清后果
        logger.warning(
            "%s —— 落盘失败（%s），改用**本进程专用**随机密钥：多 worker 下 token 会随机失效，"
            "重启后所有人需重新登录。", why, exc,
        )
        return secrets.token_urlsafe(48)


@lru_cache
def get_jwt_secret() -> str:
    """取本次进程使用的 JWT 密钥（**唯一一处**）。

    三条判据按顺序：
    1. 配了、且不在 `WEAK_JWT_SECRETS` 里、且长度够 → 用它；
    2. 没配或配的是弱值 → 用（或生成）落盘的本地随机密钥；
    3. 两种都要留痕迹（第 2 种必须警告，因为它是"开发兜底"，生产不该走到这里）。
    """
    raw = (get_settings().jwt_secret_key or "").strip()
    if raw and raw not in WEAK_JWT_SECRETS and len(raw) >= MIN_SECRET_LEN:
        return raw
    why = "未配置 JWT_SECRET_KEY" if not raw else (
        "JWT_SECRET_KEY 是已知的示例/弱口令" if raw in WEAK_JWT_SECRETS
        else f"JWT_SECRET_KEY 只有 {len(raw)} 位（< {MIN_SECRET_LEN}）"
    )
    return _fallback_secret(why)


def verify_password(plain: str, hashed: str) -> bool:
    """校验口令。**任何解析不了的哈希都按"口令不对"处理**（2026-09-19 审计 R12-H3）。

    ### 原来的样子
    直接 `pwd_context.verify(...)`：库里只要有一个**不是** `hash_password` 产物
    （历史脏数据、手工插入、导入脚本写坏）的值，passlib 就抛
    `UnknownHashError` → 穿过 `auth_service.login` 的 `or` 链 → 登录接口返回 **500**
    「服务器内部错误」。本机库里有 38 个这样的账号（30 货主 + 8 司机），
    **它们永远登不进去**，而用户看到的是"服务器坏了"。

    顺带堵掉一个轻量的**账号存在性预言机**：正常账号打错口令 = 401、
    不存在的号 = 401，而脏 hash 的账号 = 500 —— 一眼就能分辨。

    为什么返回 False 而不是抛一个"账号数据损坏"的错：登录接口不该因为
    **某一行数据坏了**就报 500（那等于给所有人发一个"服务不可用"的信号），
    也不能因此泄露"这个号存在"。口令校验失败就是 False，与打错口令同一种答复。
    """
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:  # noqa: BLE001 - 脏哈希/未知算法/空值一律按"不对"处理
        return False


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def create_access_token(subject: str, extra_claims: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {"sub": subject, "exp": expire}
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, get_jwt_secret(), algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, get_jwt_secret(), algorithms=[settings.jwt_algorithm])


def safe_decode_token(token: str) -> dict[str, Any] | None:
    try:
        return decode_token(token)
    except JWTError:
        return None
