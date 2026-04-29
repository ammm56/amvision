"""本地队列后端依赖定义。"""

from __future__ import annotations

from fastapi import Request

from backend.queue import LocalFileQueueBackend
from backend.service.application.errors import ServiceConfigurationError


def get_queue_backend(request: Request) -> LocalFileQueueBackend:
    """从 FastAPI 应用状态中读取 QueueBackend。

    参数：
    - request：当前 HTTP 请求。

    返回：
    - 当前应用使用的本地任务队列后端。

    异常：
    - 当应用未完成队列后端装配时抛出服务配置错误。
    """

    queue_backend = getattr(request.app.state, "queue_backend", None)
    if not isinstance(queue_backend, LocalFileQueueBackend):
        raise ServiceConfigurationError(
            "当前服务尚未完成任务队列装配",
            details={"state_field": "queue_backend"},
        )

    return queue_backend