"""
Socket.IO auth: JWT validation and connect handler (sync payload on connect simulates post-reconnect replay).

Requirements Coverage:
- FR-GN-002: 实时推送
- 断线重连验证
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.core.security import create_access_token, safe_decode_token


@pytest.mark.socket
@pytest.mark.unit
@pytest.mark.fast
def test_access_token_includes_role_claim(users: dict) -> None:
    from app.services.auth_service import issue_token

    tok = issue_token(users["driver"])
    payload = safe_decode_token(tok)
    assert payload is not None
    assert payload["sub"] == str(users["driver"].id)
    assert payload["role"] == "driver"


@pytest.mark.socket
@pytest.mark.unit
@pytest.mark.fast
def test_invalid_token_safe_decode(users: dict) -> None:
    bad = create_access_token(str(users["shipper"].id), {"role": "shipper"}) + "x"
    assert safe_decode_token(bad) is None


@pytest.mark.socket
@pytest.mark.asyncio
@pytest.mark.integration
async def test_socket_connect_accepts_valid_token(users: dict) -> None:
    from app.core import socket_io as si
    from app.services.auth_service import issue_token

    tok = issue_token(users["driver"])
    with (
        patch.object(si.sio, "enter_room", new=AsyncMock()) as m_room,
        patch.object(si.sio, "emit", new=AsyncMock()) as m_emit,
    ):
        ok = await si.connect("test-sid", {}, {"token": tok, "lastNotificationId": 0})
    assert ok is True
    m_room.assert_awaited_once()
    m_emit.assert_awaited()
    assert m_emit.await_args[0][0] == "sync"
    sync_body = m_emit.await_args[0][1]
    assert "notifications" in sync_body
    assert "unread_count" in sync_body


@pytest.mark.fast
@pytest.mark.smoke
def test_api_docs_available(client) -> None:
    r = client.get("/docs")
    assert r.status_code == 200


@pytest.mark.socket
@pytest.mark.unit
@pytest.mark.fast
async def test_publish_failure_is_not_swallowed() -> None:
    """**投递边界的契约**：redis.publish 没成功，_publish 必须抛，⛔ 不许记条日志就当成功。

    这条判据的由来（2026-09-26 R3-06 生产 Drill C）：上游 AsyncRedisManager._publish 在两次
    发布都失败时只打一条 Cannot publish to redis... giving up 然后 return None —— 异常被吞掉，
    于是 sio.emit 永远成功返回，发件箱把「跨实例那条根本没发出去」记成了 sent / attempts=0。

    ⚠️ 这里刻意**不连真 Redis**：指向一个必然连不上的端口就够 —— 要证的是
    「失败会不会被翻成异常」，不是「真 Redis 能不能发」。
    """
    from app.core.socket_io import _StrictRedisManager

    mgr = _StrictRedisManager("redis://127.0.0.1:1/0")
    with pytest.raises(RuntimeError, match="redis.publish 没有成功返回"):
        await mgr._publish({"method": "emit", "event": "x"})