"""classification DeploymentInstance 公共服务。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.service.application.model_type_support import (
    normalize_optional_platform_model_type,
    require_supported_platform_model_type,
)
from backend.service.application.classification_backend_registry import (
    get_classification_backend_registration,
)
from backend.service.application.deployments.deployment_instance_service import (
    DeploymentInstanceView as ClassificationDeploymentInstanceView,
    SqlAlchemyDeploymentInstanceService,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.runtime.targets.yolo11 import (
    SqlAlchemyYolo11RuntimeTargetResolver,
)
from backend.service.application.runtime.targets.yolo26 import (
    SqlAlchemyYolo26RuntimeTargetResolver,
)
from backend.service.application.runtime.targets.yolov8 import (
    SqlAlchemyYoloV8RuntimeTargetResolver,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetResolveRequest,
    RuntimeTargetSnapshot,
)
from backend.service.domain.models.model_task_types import CLASSIFICATION_TASK_TYPE
from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentRuntimeConfiguration,
)


@dataclass(frozen=True)
class ClassificationDeploymentInstanceCreateRequest:
    """描述一次 classification DeploymentInstance 创建请求。"""

    project_id: str
    model_type: str
    model_version_id: str | None = None
    model_build_id: str | None = None
    runtime_profile_id: str | None = None
    runtime_backend: str | None = None
    device_name: str | None = None
    runtime_precision: str | None = None
    runtime_configuration: DeploymentRuntimeConfiguration | None = None
    display_name: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


_RUNTIME_TARGET_RESOLVER_BY_MODEL_TYPE: dict[str, type] = {
    "yolov8": SqlAlchemyYoloV8RuntimeTargetResolver,
    "yolo11": SqlAlchemyYolo11RuntimeTargetResolver,
    "yolo26": SqlAlchemyYolo26RuntimeTargetResolver,
}


class SqlAlchemyClassificationDeploymentService(SqlAlchemyDeploymentInstanceService):
    """按模型分类分发 runtime target resolver 的 classification 部署服务。"""

    def create_deployment_instance(
        self,
        request: ClassificationDeploymentInstanceCreateRequest,
        *,
        created_by: str | None,
    ) -> ClassificationDeploymentInstanceView:
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
    ) -> tuple[ClassificationDeploymentInstanceView, ...]:
        views = super().list_deployment_instances(
            project_id=project_id,
            model_version_id=model_version_id,
            model_build_id=model_build_id,
            status=status,
            limit=limit,
        )
        views = tuple(
            item for item in views if item.task_type == CLASSIFICATION_TASK_TYPE
        )
        normalized_model_type = _normalize_model_type(model_type)
        if normalized_model_type is None:
            return views
        matched: list[ClassificationDeploymentInstanceView] = []
        for item in views:
            runtime_target = self.resolve_inference_target(item.deployment_instance_id)
            if runtime_target.model_type == normalized_model_type:
                matched.append(item)
        return tuple(matched[:limit])

    def _resolve_create_target(
        self,
        request: ClassificationDeploymentInstanceCreateRequest,
    ) -> RuntimeTargetSnapshot:
        normalized_model_type = _require_model_type(request.model_type)
        resolver_cls = _RUNTIME_TARGET_RESOLVER_BY_MODEL_TYPE.get(normalized_model_type)
        if resolver_cls is None:
            registration = get_classification_backend_registration(
                normalized_model_type
            )
            raise ServiceConfigurationError(
                "当前 classification deployment 尚未接通指定模型分类",
                details={
                    "model_type": normalized_model_type,
                    "display_name": registration.display_name
                    if registration is not None
                    else None,
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
    return normalize_optional_platform_model_type(model_type)


def _require_model_type(model_type: str | None) -> str:
    return require_supported_platform_model_type(
        task_type=CLASSIFICATION_TASK_TYPE,
        model_type=model_type,
        unsupported_message="当前 classification deployment 不支持指定模型分类",
    )
