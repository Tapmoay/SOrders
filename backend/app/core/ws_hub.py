from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from starlette.websockets import WebSocket


class WsHub:
    """按 user_id 管理 WebSocket 连接（单机内存；多实例需 Redis Pub/Sub 扩展）。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_user: dict[int, set[WebSocket]] = defaultdict(set)

    async def register(self, user_id: int, ws: WebSocket) -> None:
        async with self._lock:
            self._by_user[user_id].add(ws)

    async def unregister(self, user_id: int, ws: WebSocket) -> None:
        async with self._lock:
            s = self._by_user.get(user_id)
            if not s:
                return
            s.discard(ws)
            if not s:
                del self._by_user[user_id]

    async def send_to_user(self, user_id: int, message: dict[str, Any]) -> None:
        async with self._lock:
            sockets = list(self._by_user.get(user_id, set()))
        for ws in sockets:
            try:
                await ws.send_json(message)
            except Exception:
                await self.unregister(user_id, ws)


hub = WsHub()
