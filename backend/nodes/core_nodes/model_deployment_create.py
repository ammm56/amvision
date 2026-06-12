"""deployment create service node。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._platform_service_node_support import (
    build_platform_model_type_parameter_schema,
    build_platform_task_model_type_schema_guards,
    build_platform_task_type_parameter_schema,
    require_platform_model_type,
    require_platform_task_type,
    get_supported_platform_model_types,
)
from backend.nodes.core_nodes._service_node_support import (
    build_service_node_deployment_service,
    build_response_body_output,
    get_optional_bool_parameter,
    get_optional_dict_parameter,
    get_optional_int_parameter,
    get_optional_str_parameter,
    overlay_parameters_from_object_input,
    require_str_parameter,
    require_workflow_service_node_runtime,
    resolve_created_by,
)
from backend.service.application.deployments.classification_deployment_service import (
    ClassificationDeploymentInstanceCreateRequest,
)
from backend.service.application.deployments.detection_deployment_service import (
    DetectionDeploymentInstanceCreateRequest,
)
from backend.service.application.deployments.obb_deployment_service import (
    ObbDeploymentInstanceCreateRequest,
)
from backend.service.application.deployments.pose_deployment_service import (
    PoseDeploymentInstanceCreateRequest,
)
from backend.service.application.deployments.segmentation_deployment_service import (
    SegmentationDeploymentInstanceCreateRequest,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.application.workflows.execution_cleanup import register_deployment_cleanup
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE


def _model_deployment_create_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """调用正式平台 deployment 创建服务。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：deployment create API 对齐的 response body。
    """

    request = overlay_parameters_from_object_input(request)
    runtime_context = require_workflow_service_node_runtime(request)
    task_type = require_platform_task_type(request)
    request_cls = _resolve_deployment_create_request_class(task_type)
    model_type = require_platform_model_type(
        request,
        supported_model_types=get_supported_platform_model_types(task_type),
    )
    view = build_service_node_deployment_service(
        runtime_context,
        task_type=task_type,
    ).create_deployment_instance(
        request_cls(
            project_id=require_str_parameter(request, "project_id"),
            model_type=model_type,
            model_version_id=get_optional_str_parameter(request, "model_version_id"),
            model_build_id=get_optional_str_parameter(request, "model_build_id"),
            runtime_profile_id=get_optional_str_parameter(request, "runtime_profile_id"),
            runtime_backend=get_optional_str_parameter(request, "runtime_backend"),
            device_name=get_optional_str_parameter(request, "device_name"),
            runtime_precision=get_optional_str_parameter(request, "runtime_precision"),
            instance_count=get_optional_int_parameter(request, "instance_count") or 1,
            display_name=get_optional_str_parameter(request, "display_name") or "",
            metadata=_build_request_metadata(request),
        ),
        created_by=resolve_created_by(request),
    )
    if get_optional_bool_parameter(request, "cleanup_on_completion") is True:
        _register_created_deployment_for_cleanup(
            request=request,
            view=view,
            task_type=task_type,
        )
    return build_response_body_output(view)


def _build_request_metadata(request: WorkflowNodeExecutionRequest) -> dict[str, object] | None:
    """构造 deployment create 节点最终提交的 metadata。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object] | None：合并显式参数后的 metadata；没有 metadata 时返回 None。
    """

    metadata = get_optional_dict_parameter(request, "metadata")
    keep_warm_enabled = get_optional_bool_parameter(request, "keep_warm_enabled")
    if keep_warm_enabled is None:
        return metadata

    normalized_metadata = dict(metadata) if metadata is not None else {}
    raw_process_metadata = normalized_metadata.get("deployment_process")
    process_metadata = dict(raw_process_metadata) if isinstance(raw_process_metadata, dict) else {}
    process_metadata["keep_warm_enabled"] = keep_warm_enabled
    normalized_metadata["deployment_process"] = process_metadata
    return normalized_metadata


def _register_created_deployment_for_cleanup(
    request: WorkflowNodeExecutionRequest,
    *,
    view: object,
    task_type: str,
) -> None:
    """把当前创建出的 DeploymentInstance 登记为执行结束后清理。

    参数：
    - request：当前 workflow 节点执行请求。
    - view：deployment create 返回的视图对象或字典。
    """

    raw_deployment_instance_id = (
        view.get("deployment_instance_id")
        if isinstance(view, dict)
        else getattr(view, "deployment_instance_id", None)
    )
    if not isinstance(raw_deployment_instance_id, str) or not raw_deployment_instance_id.strip():
        return
    register_deployment_cleanup(
        request.execution_metadata,
        deployment_instance_id=raw_deployment_instance_id,
        task_type=task_type,
    )


def _resolve_deployment_create_request_class(
    task_type: str,
) -> type:
    """按 task_type 返回 deployment create request 类型。"""

    if task_type == DETECTION_TASK_TYPE:
        return DetectionDeploymentInstanceCreateRequest
    if task_type == "classification":
        return ClassificationDeploymentInstanceCreateRequest
    if task_type == "segmentation":
        return SegmentationDeploymentInstanceCreateRequest
    if task_type == "pose":
        return PoseDeploymentInstanceCreateRequest
    if task_type == "obb":
        return ObbDeploymentInstanceCreateRequest
    raise ValueError(f"unsupported task_type: {task_type}")


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.service.model-deployment.create",
        display_name="Create Deployment",
        category="service.model.deployment.resource",
        description="按 task_type 调用正式 deployment API 创建 DeploymentInstance。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="request",
                display_name="Request",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="body",
                display_name="Body",
                payload_type_id="response-body.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "task_type": build_platform_task_type_parameter_schema(),
                "model_type": build_platform_model_type_parameter_schema(),
                "project_id": {"type": "string"},
                "model_version_id": {"type": "string"},
                "model_build_id": {"type": "string"},
                "runtime_profile_id": {"type": "string"},
                "runtime_backend": {"type": "string"},
                "device_name": {"type": "string"},
                "runtime_precision": {"type": "string"},
                "instance_count": {"type": "integer", "minimum": 1},
                "keep_warm_enabled": {"type": "boolean"},
                "display_name": {"type": "string"},
                "metadata": {"type": "object"},
                "cleanup_on_completion": {"type": "boolean"},
                "created_by": {"type": "string"},
            },
            "required": ["task_type", "model_type", "project_id"],
            "anyOf": [
                {"required": ["model_version_id"]},
                {"required": ["model_build_id"]}
            ],
            "allOf": build_platform_task_model_type_schema_guards(),
        },
        capability_tags=("service.model.deployment", "resource.create", "resource.control-plane"),
    ),
    handler=_model_deployment_create_handler,
)

