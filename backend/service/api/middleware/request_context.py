"""请求上下文中间件。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """为每个请求补充最小上下文信息。"""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """为请求写入 request_id 并透传到响应头。

        参数：
        - request：当前 HTTP 请求。
        - call_next：下一个中间件或路由处理器。

        返回：
        - 追加了 request_id 响应头的响应对象。
        """

        request.state.request_id = request.headers.get("x-request-id", str(uuid4()))
        response = await call_next(request)
        response.headers.setdefault("x-request-id", request.state.request_id)

        return response