"""obb DeploymentInstance 公共服务。"""

from __future__ import annotations
from dataclasses import dataclass, field
from backend.service.application.deployments.yolox_deployment_service import (
    SqlAlchemyYoloXDeploymentService,
    YoloXDeploymentInstanceView as ObbDeploymentInstanceView,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.obb_backend_registry import get_obb_backend_registration
from backend.service.application.runtime.yolo11_runtime_target import SqlAlchemyYolo11RuntimeTargetResolver
from backend.service.application.runtime.yolo26_runtime_target import SqlAlchemyYolo26RuntimeTargetResolver
from backend.service.application.runtime.yolov8_runtime_target import SqlAlchemyYoloV8RuntimeTargetResolver
from backend.service.application.runtime.runtime_target import RuntimeTargetResolveRequest, RuntimeTargetSnapshot

@dataclass(frozen=True)
class ObbDeploymentInstanceCreateRequest:
    project_id: str
    model_type: str
    model_version_id: str | None = None
    model_build_id: str | None = None
    runtime_profile_id: str | None = None
    runtime_backend: str | None = None
    device_name: str | None = None
    runtime_precision: str | None = None
    instance_count: int = 1
    display_name: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

_RUNTIME_TARGET_RESOLVER_BY_MODEL_TYPE = {
    "yolov8": SqlAlchemyYoloV8RuntimeTargetResolver,
    "yolo11": SqlAlchemyYolo11RuntimeTargetResolver,
    "yolo26": SqlAlchemyYolo26RuntimeTargetResolver,
}

class SqlAlchemyObbDeploymentService(SqlAlchemyYoloXDeploymentService):
    """按模型分类分发 runtime target resolver 的 obb 部署服务。"""

    def create_deployment_instance(self, request, *, created_by=None):
        return super().create_deployment_instance(request, created_by=created_by)

    def list_deployment_instances(self, *, project_id, model_type=None, model_version_id=None, model_build_id=None, status=None, limit=100):
        views = super().list_deployment_instances(project_id=project_id, model_version_id=model_version_id, model_build_id=model_build_id, status=status, limit=limit)
        n = _normalize_model_type(model_type)
        if n is None:
            return views
        return tuple(v for v in views if _match_obb_model_type(self, v, n))[:limit]

    def _resolve_create_target(self, request):
        n = _require_model_type(request.model_type)
        rc = _RUNTIME_TARGET_RESOLVER_BY_MODEL_TYPE.get(n)
        if rc is None:
            reg = get_obb_backend_registration(n)
            raise ServiceConfigurationError("当前 obb deployment 尚未接通指定模型分类", details={"model_type": n, "display_name": reg.display_name if reg else None})
        rt = rc(session_factory=self.session_factory, dataset_storage=self.dataset_storage).resolve_target(RuntimeTargetResolveRequest(
            project_id=request.project_id, model_version_id=request.model_version_id, model_build_id=request.model_build_id,
            runtime_profile_id=request.runtime_profile_id, runtime_backend=request.runtime_backend,
            device_name=request.device_name, runtime_precision=request.runtime_precision,
        ))
        if rt.model_type != n:
            raise InvalidRequestError("请求中的 model_type 与来源模型记录不匹配", details={"requested_model_type": n, "resolved_model_type": rt.model_type})
        return rt

def _match_obb_model_type(self, v, n):
    rt = self.resolve_inference_target(v.deployment_instance_id)
    return rt.model_type == n

def _normalize_model_type(mt):
    if isinstance(mt, str) and mt.strip():
        return mt.strip().lower()
    return None

def _require_model_type(mt):
    n = _normalize_model_type(mt)
    if n is None:
        raise InvalidRequestError("model_type 不能为空")
    return n
