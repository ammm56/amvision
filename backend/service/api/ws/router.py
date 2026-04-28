"""WebSocket 路由定义。"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket


ws_router = APIRouter(prefix="/ws")


@ws_router.websocket("/events")
async def subscribe_events(socket: WebSocket) -> None:
    """建立最小事件订阅会话。

    参数：
    - socket：当前 WebSocket 连接。
    """

    await socket.accept()
    await socket.send_json(
        {
            "event_type": "system.connected",
            "event_version": "v1",
        }
    )
    await socket.close(code=1000)