"""classification deployment 路由响应构造辅助函数。"""

from __future__ import annotations

from typing import Any

from backend.service.application.deployments.classification_deployment_service import (
    ClassificationDeploymentInstanceView,
)


def build_classification_deployment_instance_response(instance: ClassificationDeploymentInstanceView) -> dict[str, Any]:
    return {
        "deployment_instance_id": instance.deployment_instance_id,
        "project_id": instance.project_id,
        "model_id": instance.model_id,
        "model_version_id": instance.model_version_id,
        "model_build_id": instance.model_build_id,
        "display_name": instance.display_name,
        "status": instance.status,
        "runtime_profile_id": instance.runtime_profile_id,
        "runtime_backend": instance.runtime_backend,
        "device_name": instance.device_name,
        "instance_count": instance.instance_count,
        "process_status": instance.process_status,
        "metadata": dict(instance.metadata),
        "created_at": instance.created_at,
        "updated_at": instance.updated_at,
        "created_by": instance.created_by,
    }
