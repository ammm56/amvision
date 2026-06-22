"""classification deployment response builder。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.classification_deployments.schemas import (
    ClassificationDeploymentInstanceResponse,
)
from backend.service.application.deployments.classification_deployment_service import (
    ClassificationDeploymentInstanceView,
)


def build_classification_deployment_instance_response(
    instance: ClassificationDeploymentInstanceView,
) -> ClassificationDeploymentInstanceResponse:
    """把 classification DeploymentInstance view 转成 API response。"""

    return ClassificationDeploymentInstanceResponse(
        deployment_instance_id=instance.deployment_instance_id,
        project_id=instance.project_id,
        model_id=instance.model_id,
        model_version_id=instance.model_version_id,
        model_build_id=instance.model_build_id,
        display_name=instance.display_name,
        status=instance.status,
        runtime_profile_id=instance.runtime_profile_id,
        runtime_backend=instance.runtime_backend,
        device_name=instance.device_name,
        instance_count=instance.instance_count,
        process_status=getattr(instance, "process_status", None),
        metadata=dict(instance.metadata),
        created_at=instance.created_at,
        updated_at=instance.updated_at,
        created_by=instance.created_by,
    )
