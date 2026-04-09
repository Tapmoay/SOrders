"""注册短信验证码（内存存储，适合开发与单实例；生产可换 Redis + 真实短信网关）。"""

from __future__ import annotations

import random
import re
import time

PHONE_CN_RE = re.compile(r"^1[3-9]\d{9}$")

# phone -> (code, sent_at)
_store: dict[str, tuple[str, float]] = {}
_last_send: dict[str, float] = {}

CODE_TTL_SEC = 300
SEND_INTERVAL_SEC = 60


def validate_cn_mobile(phone: str) -> bool:
    return bool(PHONE_CN_RE.match(phone.strip()))


def send_code(phone: str) -> tuple[str, str | None]:
    """生成并存储验证码。返回 (code, error_message)。"""
    p = phone.strip()
    if not validate_cn_mobile(p):
        return "", "手机号格式不正确"
    now = time.time()
    prev = _last_send.get(p, 0.0)
    if now - prev < SEND_INTERVAL_SEC:
        return "", f"请{SEND_INTERVAL_SEC}秒后再试"
    code = f"{random.randint(0, 999999):06d}"
    _store[p] = (code, now)
    _last_send[p] = now
    return code, None


def verify_and_consume(phone: str, code: str) -> tuple[bool, str | None]:
    """校验并一次性消费验证码。"""
    p = phone.strip()
    c = code.strip()
    if not validate_cn_mobile(p):
        return False, "手机号格式不正确"
    if p not in _store:
        return False, "请先获取验证码"
    stored, sent_at = _store[p]
    if time.time() - sent_at > CODE_TTL_SEC:
        del _store[p]
        return False, "验证码已过期，请重新获取"
    if stored != c:
        return False, "验证码不正确"
    del _store[p]
    return True, None


def clear_store() -> None:
    """测试用：清空内存状态。"""
    _store.clear()
    _last_send.clear()
