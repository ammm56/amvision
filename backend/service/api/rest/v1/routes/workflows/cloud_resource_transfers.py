"""计量资源 v2 点云包的有界传输，不在 API 解析或计算点云。"""

from hashlib import sha256
import json
from tempfile import TemporaryFile
from threading import Event
from typing import Annotated

import anyio
from fastapi import APIRouter, Header, Query, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from backend.contracts.workflows.measurement_resources import (
    MeasurementResourceDocument,
)
from backend.service.api.deps.auth import _require_backend_service_settings
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
    OperationCancelledError,
)
from backend.service.application.workflows.documents.measurement_resources import (
    MeasurementResourceService,
)
from .documents import _ensure_project_visible
from .measurement_resources import Reader, Storage, Writer, _mutation


cloud_resource_transfers_router = APIRouter(
    prefix="/projects/{project_id}/measurement-resources"
)


@cloud_resource_transfers_router.get("/cloud/capabilities")
def cloud_capabilities(project_id: str, request: Request, principal: Reader):
    """只返回实际配置；页面不能用测试数值代替未配置容量。"""
    _ensure_project_visible(principal=principal, project_id=project_id)
    policy = _require_backend_service_settings(request.app).workflow_runtime.point_cloud
    return {
        "max_archive_bytes": policy.max_archive_bytes if policy else None,
        "renderer": policy.renderer.model_dump(mode="json")
        if policy and policy.renderer is not None else None,
    }


def require_cloud_policy(request):
    """缺少显式配置即拒绝，不使用示例或测试容量代替生产配置。"""
    policy = _require_backend_service_settings(request.app).workflow_runtime.point_cloud
    if policy is None:
        raise ServiceConfigurationError("点云资源传输尚未配置运行预算，未启用")
    return policy.assets()


async def run_cloud_transfer(request, operation):
    """仅在请求内监听断连；取消同步块操作并等待其 finally 完成。"""
    disconnected = Event()

    def check_connection():
        if disconnected.is_set():
            raise OperationCancelledError("点云资源传输连接已关闭")

    async def watch_connection():
        try:
            while True:
                message = await request.receive()
                if message["type"] == "http.disconnect":
                    return
        finally:
            disconnected.set()

    failure = None
    async with anyio.create_task_group() as group:
        group.start_soon(watch_connection)
        try:
            result = await run_in_threadpool(operation, check_connection)
        except Exception as error:
            # 保留既有 ServiceError 映射，不让 TaskGroup 把 400/409 包成 500。
            failure = error
        finally:
            group.cancel_scope.cancel()
    if failure is not None:
        raise failure
    return result


class CloudArchiveResponse(StreamingResponse):
    """持有临时归档直至传输完成或断连；两条路径均关闭文件。"""

    def __init__(self, stream, *, length, chunk_bytes):
        self.archive = stream

        def chunks():
            while chunk := stream.read(chunk_bytes):
                yield chunk

        super().__init__(
            chunks(),
            media_type="application/zip",
            headers={
                "Content-Length": str(length),
                "Content-Disposition": 'attachment; filename="point-cloud-resource.zip"',
            },
        )

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.archive.close()


async def export_cloud_response(request, storage, document):
    """线程池中的管理面归档，失败不交付部分响应。"""
    policy = require_cloud_policy(request)
    stream = TemporaryFile(mode="w+b", dir=storage.root_dir)
    try:

        def encode(cancel):
            return MeasurementResourceService(storage).export_cloud_archive(
                document.reference,
                project_id=document.reference.project_id,
                stream=stream,
                policy=policy,
                cancel=cancel,
            )

        length = await run_cloud_transfer(request, encode)
        stream.seek(0)
        return CloudArchiveResponse(
            stream, length=length, chunk_bytes=policy.chunk_bytes
        )
    except BaseException:
        stream.close()
        raise


@cloud_resource_transfers_router.post(
    "/cloud/import", response_model=MeasurementResourceDocument, status_code=201
)
async def import_cloud_resource(
    project_id: str,
    request: Request,
    principal: Writer,
    storage: Storage,
    name: Annotated[str, Query(min_length=1, max_length=128)],
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
        ),
    ],
):
    """先鉴权再逐块暂存；容量、包结构和摘要全部通过才提交版本。"""
    _ensure_project_visible(principal=principal, project_id=project_id)
    policy = require_cloud_policy(request)
    if not name.strip():
        raise InvalidRequestError("计量资源名称不能为空")
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/zip"
    ):
        raise InvalidRequestError("点云资产包需要 application/zip 请求体")
    declared = request.headers.get("content-length")
    declared_length = None
    if declared is not None:
        normalized = declared.lstrip("0")
        if (
            not declared.isascii()
            or not declared.isdecimal()
            or not normalized
            or len(normalized) > len(str(policy.max_archive_bytes))
        ):
            raise InvalidRequestError("点云资产包 Content-Length 无效或超过显式限额")
        declared_length = int(normalized)
        if declared_length > policy.max_archive_bytes:
            raise InvalidRequestError("点云资产包 Content-Length 超过显式限额")
    identity = sha256(
        json.dumps(
            ["cloud-import", project_id, principal.principal_id, idempotency_key],
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    with TemporaryFile(mode="w+b", dir=storage.root_dir) as stream:
        received = 0
        async for chunk in request.stream():
            received += len(chunk)
            if received > policy.max_archive_bytes:
                raise InvalidRequestError("点云资产包超过显式限额")
            if chunk and await run_in_threadpool(stream.write, chunk) != len(chunk):
                raise OSError("点云资产包暂存短写")
        if received == 0 or (
            declared_length is not None and received != declared_length
        ):
            raise InvalidRequestError("点云资产包为空或实际长度与声明不符")

        def commit(cancel):
            with _mutation(request, project_id, "cloud-import"):
                stream.seek(0)
                return MeasurementResourceService(storage).import_cloud_archive(
                    stream=stream,
                    project_id=project_id,
                    name=name,
                    write_identity=identity,
                    policy=policy,
                    cancel=cancel,
                    actor_id=principal.principal_id,
                )

        return await run_cloud_transfer(request, commit)
