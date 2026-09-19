"""登录失败限流（2026-09-19 审计：登录零限流 + 口令下限 6 位）。

## 为什么必须做
生产是**公网 80**，账号就是手机号（业务上公开的信息），而原来 `POST /auth/login` 可以
**无限重试**：全仓 grep `slowapi|ratelimit|limit|throttl` 在后端零命中，没有失败计数、没有锁定、
没有验证码、没有退避；口令下限只有 6 位。6 位纯数字的空间是 10^6，脚本几小时就能撞开；
撞开货主＝订单＋账本，撞开派单员＝整个系统。

## 做法（两条轨，Redis 优先）
- **Redis 可用时**用 `INCR` + `EXPIRE` 计数：生产是多 worker（`--workers 2`），进程内计数会被
  放大成"每个 worker 各允许 N 次"，等于把限流放宽一倍；
- Redis 不可用（本机开发、或 Redis 挂了）就退回**进程内**计数 —— 限流失效一小会儿，
  总比"登录直接 500"好；退回这件事会打一条 warning，不静默。

## 判据（两条锁，任一条触发即拒）
- 同一**登录名**（手机号）：`MAX_FAILS_PER_ID` 次失败 → 锁 `LOCK_SECONDS`；
- 同一**来源 IP**：`MAX_FAILS_PER_IP` 次失败（对所有登录名合计）→ 锁 `LOCK_SECONDS`。
登录成功会清掉该登录名的失败计数（IP 计数保留，避免"用一个正确账号把 IP 洗白"）。

被拒时回 **429 + 中文**，并如实告诉还要等多久 —— 不泄露"这个账号存不存在"。
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque

from app.config import get_settings

logger = logging.getLogger(__name__)

#: 同一登录名允许的连续失败次数与锁定时长
MAX_FAILS_PER_ID = 5
#: 同一来源 IP 允许的连续失败次数（对所有登录名合计）
MAX_FAILS_PER_IP = 20
#: 统计窗口与锁定时长（秒）
WINDOW_SECONDS = 15 * 60
LOCK_SECONDS = 15 * 60

_lock = threading.Lock()
#: key → 失败时间戳队列（进程内兜底）
_fails: dict[str, deque[float]] = defaultdict(deque)

_redis_client = None
_redis_checked = False


def _redis():
    """惰性拿一个 Redis 客户端；拿不到就返回 None（并只警告一次）。"""
    global _redis_client, _redis_checked
    if _redis_checked:
        return _redis_client
    _redis_checked = True
    url = (get_settings().redis_url or "").strip()
    if not url:
        logger.warning("登录限流：未配置 REDIS_URL，使用**进程内**计数（多 worker 下限流会放宽）")
        return None
    try:
        import redis  # type: ignore

        client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        _redis_client = client
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "登录限流：Redis 不可用（%s），本次使用**进程内**计数（多 worker 下限流会放宽）",
            type(e).__name__,
        )
        _redis_client = None
    return _redis_client


def _now() -> float:
    return time.time()


def _key(kind: str, value: str) -> str:
    return f"login_fail:{kind}:{value}"


def _hits_in_process(key: str) -> int:
    q = _fails[key]
    cutoff = _now() - WINDOW_SECONDS
    while q and q[0] < cutoff:
        q.popleft()
    return len(q)


def _bump_process(key: str) -> int:
    with _lock:
        _fails[key].append(_now())
        return _hits_in_process(key)


def _bump_redis(key: str) -> int | None:
    client = _redis()
    if client is None:
        return None
    try:
        n = int(client.incr(key))
        if n == 1:
            client.expire(key, WINDOW_SECONDS)
        return n
    except Exception as e:  # noqa: BLE001
        logger.warning("登录限流：Redis 计数失败（%s），退回进程内计数", type(e).__name__)
        return None


def _hits(key: str) -> int:
    client = _redis()
    if client is None:
        return _hits_in_process(key)
    try:
        return int(client.get(key) or 0)
    except Exception:  # noqa: BLE001
        return _hits_in_process(key)


def _bump(key: str) -> int:
    n = _bump_redis(key)
    return _bump_process(key) if n is None else n


def _clear(key: str) -> None:
    client = _redis()
    if client is not None:
        try:
            client.delete(key)
        except Exception:  # noqa: BLE001
            pass
    with _lock:
        _fails.pop(key, None)


def block_reason(login_id: str, client_ip: str | None) -> str | None:
    """要不要拒这次登录尝试。返回中文原因（None = 放行）。"""
    ident = (login_id or "").strip()
    if ident and _hits(_key("id", ident)) >= MAX_FAILS_PER_ID:
        return (
            f"这个账号连续登录失败太多次，已被临时锁定（约 {LOCK_SECONDS // 60} 分钟）。"
            "请稍后再试；忘记密码请联系派单员重置。"
        )
    if client_ip and _hits(_key("ip", client_ip)) >= MAX_FAILS_PER_IP:
        return (
            f"这个网络地址登录失败太多次，已被临时限制（约 {LOCK_SECONDS // 60} 分钟）。"
            "请稍后再试。"
        )
    return None


def note_failure(login_id: str, client_ip: str | None) -> None:
    ident = (login_id or "").strip()
    if ident:
        _bump(_key("id", ident))
    if client_ip:
        _bump(_key("ip", client_ip))


def note_success(login_id: str) -> None:
    """登录成功清掉**该登录名**的失败计数（IP 计数保留）。"""
    _clear(_key("id", (login_id or "").strip()))


def reset_for_tests() -> None:
    """测试用：清空进程内计数（Redis 由测试自己决定要不要清）。"""
    with _lock:
        _fails.clear()
