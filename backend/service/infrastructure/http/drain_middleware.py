"""HTTP 排空边界：计数覆盖完整响应流，不拷贝请求或图像。"""

from starlette.responses import JSONResponse

from backend.service.infrastructure.http.liveness import ServiceLiveness


class HttpDrainMiddleware:
    """在服务端 HTTP 接入处拒绝排空期间的新工作。"""

    def __init__(self, app, liveness: ServiceLiveness):
        """保存 ASGI 下游与单实例状态。"""
        self.app, self.liveness = app, liveness

    async def __call__(self, scope, receive, send):
        """传递原始 ASGI 消息，最终响应完成或异常后归还计数。"""
        if scope["type"] != "http" or scope.get("path") == "/api/v1/system/liveness":
            return await self.app(scope, receive, send)
        if not self.liveness.begin_request():
            return await JSONResponse({"detail": "Service is draining"}, status_code=503)(scope, receive, send)
        try:
            await self.app(scope, receive, send)
        finally:
            self.liveness.end_request()
