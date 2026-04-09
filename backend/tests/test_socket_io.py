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
