"""pose deployment response builder。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.pose_deployments.schemas import PoseDeploymentInstanceResponse
from backend.service.application.deployments.pose_deployment_service import PoseDeploymentInstanceView


def build_pose_deployment_instance_response(instance: PoseDeploymentInstanceView) -> PoseDeploymentInstanceResponse:
    """把 pose DeploymentInstance view 转成 API response。"""

    return PoseDeploymentInstanceResponse(
        deployment_instance_id=instance.deployment_instance_id,
        project_id=instance.project_id,
        model_id=instance.model_id,
        model_version_id=instance.model_version_id,
        model_build_id=instance.model_build_id,
        model_name=instance.model_name,
        model_scale=instance.model_scale,
        task_type=instance.task_type,
        source_kind=instance.source_kind,
        display_name=instance.display_name,
        status=instance.status,
        runtime_profile_id=instance.runtime_profile_id,
        runtime_backend=instance.runtime_backend,
        device_name=instance.device_name,
        runtime_precision=instance.runtime_precision,
        runtime_execution_mode=instance.runtime_execution_mode,
        instance_count=instance.instance_count,
        input_size=instance.input_size,
        labels=instance.labels,
        process_status=getattr(instance, "process_status", None),
        metadata=dict(instance.metadata),
        created_at=instance.created_at,
        updated_at=instance.updated_at,
        created_by=instance.created_by,
    )
