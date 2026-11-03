"""已保存点云的只读显示数据面；构建工作仍由 Cloud Preview worker 执行。"""

from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from backend.contracts.workflows.metrology import ResourceReference
from backend.contracts.workflows.point_cloud_detail import CloudDetailIndex
from backend.service.api.deps.auth import _require_backend_service_settings
from backend.service.application.errors import (
    ServiceConfigurationError,
    InvalidRequestError,
)
from backend.service.application.workflows.documents.measurement_resources import (
    MeasurementResourceService,
)
from backend.service.application.workflows.point_cloud.detail_index import (
    read_index,
    read_block,
)
from .documents import _ensure_project_visible
from .measurement_resources import Reader, Storage

cloud_resource_details_router = APIRouter(
    prefix="/projects/{project_id}/measurement-resources"
)
Digest = Annotated[str, Query(pattern=r"^[0-9a-f]{64}$")]
Generation = Annotated[str, Query(pattern=r"^[0-9a-f]{32}$")]


def _context(project_id, resource_id, version, digest, request, principal, storage):
    """项目鉴权和源摘要均检查，不接受客户端对象路径。"""
    _ensure_project_visible(principal=principal, project_id=project_id)
    policy = _require_backend_service_settings(request.app).workflow_runtime.point_cloud
    if policy is None:
        raise ServiceConfigurationError("点云显示尚未配置预算")
    try:
        reference = ResourceReference(
            project_id=project_id,
            resource_id=resource_id,
            version=version,
            sha256=digest,
            kind="point-cloud",
        )
    except ValueError as error:
        raise InvalidRequestError("点云资产身份无效") from error
    return MeasurementResourceService(storage), reference, policy.preview


@cloud_resource_details_router.get(
    "/{resource_id}/versions/{version}/details", response_model=CloudDetailIndex
)
def get_details(
    project_id: str,
    resource_id: str,
    version: int,
    sha256: Digest,
    request: Request,
    response: Response,
    principal: Reader,
    storage: Storage,
):
    """只返回完整提交且绑定同一资产版本的索引。"""
    response.headers["Cache-Control"] = "no-store"
    service, reference, policy = _context(
        project_id, resource_id, version, sha256, request, principal, storage
    )
    return read_index(service, reference, project_id=project_id, policy=policy)


@cloud_resource_details_router.get(
    "/{resource_id}/versions/{version}/details/{block_id}"
)
def get_detail_block(
    project_id: str,
    resource_id: str,
    version: int,
    block_id: int,
    sha256: Digest,
    generation: Generation,
    request: Request,
    principal: Reader,
    storage: Storage,
):
    """每次至多一个显式容量块，索引切换时拒绝旧代次。"""
    service, reference, policy = _context(
        project_id, resource_id, version, sha256, request, principal, storage
    )
    data = read_block(
        service,
        reference,
        block_id,
        generation=generation,
        project_id=project_id,
        policy=policy,
    )
    return Response(
        data,
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-store"},
    )
