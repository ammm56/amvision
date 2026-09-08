"""在文件传输结束前持有资源读取操作权。"""

from pathlib import Path
from uuid import uuid4

import anyio
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from backend.service.application.errors import ResourceNotFoundError
from backend.service.application.project_mutation import ProjectMutationAdmissionService


class ResourceFileResponse(FileResponse):
    """防止异步文件响应发送过程中被 Project 或资源删除移走。"""

    def __init__(self, *, session_factory, project_id: str, resource_id: str, **kwargs):
        """使用每个下载独立的读取声明，允许同一资源的并行下载。"""
        super().__init__(**kwargs)
        self.resource_operation = ProjectMutationAdmissionService(
            session_factory
        ).operation(
            project_id=project_id,
            mutation_kind="resource-download",
            resource_id=f"download-{uuid4().hex}",
        )
        self.resource_id = resource_id

    async def __call__(self, scope, receive, send) -> None:
        """声明覆盖完整 ASGI 发送，异常和客户端断连均释放声明。"""
        await run_in_threadpool(self.resource_operation.__enter__)
        try:
            if not Path(self.path).is_file():
                raise ResourceNotFoundError(
                    "下载文件已不存在", details={"resource_id": self.resource_id}
                )
            # pathsend 会把发送委托给服务器，提前释放声明；此处使用文件流发送。
            scope = {
                **scope,
                "extensions": {
                    key: value
                    for key, value in scope.get("extensions", {}).items()
                    if key != "http.response.pathsend"
                },
            }
            await super().__call__(scope, receive, send)
        finally:
            # 客户端断连会取消发送任务；释放声明必须在取消屏蔽范围中完成。
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(self.resource_operation.__exit__, None, None, None)
