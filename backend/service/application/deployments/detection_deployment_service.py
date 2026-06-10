"""detection DeploymentInstance 公共服务。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.service.application.detection_backend_registry import (
    get_detection_backend_registration,
)
from backend.service.application.deployments.yolox_deployment_service import (
    SqlAlchemyYoloXDeploymentService,
    YoloXDeploymentInstanceView as DetectionDeploymentInstanceView,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.runtime.rfdetr_runtime_target import (
    SqlAlchemyRfdetrRuntimeTargetResolver,
)
from backend.service.application.runtime.yolo11_runtime_target import (
    SqlAlchemyYolo11RuntimeTargetResolver,
)
from backend.service.application.runtime.yolo26_runtime_target import (
    SqlAlchemyYolo26RuntimeTargetResolver,
)
from backend.service.application.runtime.yolov8_runtime_target import (
    SqlAlchemyYoloV8RuntimeTargetResolver,
)
from backend.service.application.runtime.runtime_target import (
    RuntimeTargetResolveRequest,
    RuntimeTargetSnapshot,
    SqlAlchemyRuntimeTargetResolver,
)


@dataclass(frozen=True)
class DetectionDeploymentInstanceCreateRequest:
    """描述一次 detection DeploymentInstance 创建请求。"""

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


_RUNTIME_TARGET_RESOLVER_BY_MODEL_TYPE: dict[str, type] = {
    "yolox": SqlAlchemyRuntimeTargetResolver,
    "yolov8": SqlAlchemyYoloV8RuntimeTargetResolver,
    "yolo11": SqlAlchemyYolo11RuntimeTargetResolver,
    "yolo26": SqlAlchemyYolo26RuntimeTargetResolver,
    "rfdetr": SqlAlchemyRfdetrRuntimeTargetResolver,
}


class SqlAlchemyDetectionDeploymentService(SqlAlchemyYoloXDeploymentService):
    """按模型分类分发 runtime target resolver 的 detection 部署服务。"""

    def create_deployment_instance(
        self,
        request: DetectionDeploymentInstanceCreateRequest,
        *,
        created_by: str | None,
    ) -> DetectionDeploymentInstanceView:
        """创建一个 detection DeploymentInstance。"""

        return super().create_deployment_instance(request, created_by=created_by)

    def list_deployment_instances(
        self,
        *,
        project_id: str,
        model_type: str | None = None,
        model_version_id: str | None = None,
        model_build_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> tuple[DetectionDeploymentInstanceView, ...]:
        """按公开筛选条件列出 detection DeploymentInstance。"""

        views = super().list_deployment_instances(
            project_id=project_id,
            model_version_id=model_version_id,
            model_build_id=model_build_id,
            status=status,
            limit=limit,
        )
        normalized_model_type = _normalize_model_type(model_type)
        if normalized_model_type is None:
            return views
        matched: list[DetectionDeploymentInstanceView] = []
        for item in views:
            runtime_target = self.resolve_inference_target(item.deployment_instance_id)
            if runtime_target.model_type == normalized_model_type:
                matched.append(item)
        return tuple(matched[:limit])

    def _resolve_create_target(
        self,
        request: DetectionDeploymentInstanceCreateRequest,
    ) -> RuntimeTargetSnapshot:
        """根据创建请求和模型分类解析运行时快照。"""

        normalized_model_type = _require_model_type(request.model_type)
        resolver_cls = _RUNTIME_TARGET_RESOLVER_BY_MODEL_TYPE.get(normalized_model_type)
        if resolver_cls is None:
            registration = get_detection_backend_registration(normalized_model_type)
            raise ServiceConfigurationError(
                "当前 detection deployment 尚未接通指定模型分类",
                details={
                    "model_type": normalized_model_type,
                    "display_name": registration.display_name if registration is not None else None,
                },
            )
        runtime_target = resolver_cls(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
        ).resolve_target(
            RuntimeTargetResolveRequest(
                project_id=request.project_id,
                model_version_id=request.model_version_id,
                model_build_id=request.model_build_id,
                runtime_profile_id=request.runtime_profile_id,
                runtime_backend=request.runtime_backend,
                device_name=request.device_name,
                runtime_precision=request.runtime_precision,
            )
        )
        if runtime_target.model_type != normalized_model_type:
            raise InvalidRequestError(
                "请求中的 model_type 与来源模型记录不匹配",
                details={
                    "requested_model_type": normalized_model_type,
                    "resolved_model_type": runtime_target.model_type,
                    "model_version_id": request.model_version_id,
                    "model_build_id": request.model_build_id,
                },
            )
        return runtime_target


def _normalize_model_type(model_type: str | None) -> str | None:
    """把模型分类归一为小写非空字符串。"""

    if isinstance(model_type, str) and model_type.strip():
        return model_type.strip().lower()
    return None


def _require_model_type(model_type: str | None) -> str:
    """读取并校验 detection 模型分类。"""

    normalized_model_type = _normalize_model_type(model_type)
    if normalized_model_type is None:
        raise InvalidRequestError("model_type 不能为空")
    return normalized_model_type
