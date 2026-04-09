"""Socket.IO 发送封装（供 message_center / push_events 引用）。"""

from __future__ import annotations

from typing import Any

from app.core.socket_io import emit_to_user as _emit


async def emit_to_user(user_id: int, event: str, data: dict[str, Any]) -> None:
    await _emit(user_id, event, data)
