"""YOLOX evaluation 结果包 service node。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._service_node_support import (
    build_response_body_output,
    get_optional_bool_parameter,
    get_optional_str_parameter,
    overlay_parameters_from_object_input,
    require_str_parameter,
    require_workflow_service_node_runtime,
)
from backend.service.application.workflows.execution_cleanup import register_dataset_storage_object_cleanup
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _yolox_evaluation_package_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """为已完成评估任务生成或复用结果包。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：response-body.v1 输出。
    """

    request = overlay_parameters_from_object_input(request)
    runtime_context = require_workflow_service_node_runtime(request)
    task_id = require_str_parameter(request, "task_id")
    cleanup_on_completion = get_optional_bool_parameter(request, "cleanup_on_completion") is True
    package_object_key = _resolve_package_object_key(
        request,
        task_id=task_id,
        cleanup_on_completion=cleanup_on_completion,
    )
    package = runtime_context.build_evaluation_task_service().package_evaluation_result(
        task_id,
        rebuild=get_optional_bool_parameter(request, "rebuild") is True,
        package_object_key=package_object_key,
    )
    if cleanup_on_completion:
        register_dataset_storage_object_cleanup(
            request.execution_metadata,
            object_key=package.package_object_key,
        )
    return build_response_body_output(package)


def _resolve_package_object_key(
    request: WorkflowNodeExecutionRequest,
    *,
    task_id: str,
    cleanup_on_completion: bool,
) -> str | None:
    """解析 evaluation package 节点的目标 object key。

    参数：
    - request：当前 workflow 节点执行请求。
    - task_id：评估任务 id。
    - cleanup_on_completion：是否在 workflow 结束时清理结果包。

    返回：
    - str | None：目标 object key；为 None 时复用服务默认路径。
    """

    explicit_object_key = get_optional_str_parameter(request, "package_object_key")
    if explicit_object_key is not None:
        return explicit_object_key
    if not cleanup_on_completion:
        return None
    workflow_run_id = str(request.execution_metadata.get("workflow_run_id") or "default-run")
    return (
        f"workflows/runtime/{workflow_run_id}/{request.node_id}/"
        f"yolox-evaluation-{task_id}-result-package.zip"
    )


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.service.yolox-evaluation.package",
        display_name="Package YOLOX Evaluation Result",
        category="service.model.evaluation",
        description=(
            "为一个已完成的 YOLOX evaluation task 生成或复用 zip 结果包；"
            "cleanup_on_completion 只会登记当前 workflow 执行期的临时对象清理，不影响原有 HTTP API 输出文件。"
        ),
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
                "task_id": {"type": "string"},
                "rebuild": {"type": "boolean"},
                "package_object_key": {
                    "type": "string",
                    "description": "可选结果包 object key；未提供时复用评估任务默认输出路径。",
                },
                "cleanup_on_completion": {
                    "type": "boolean",
                    "description": "为 true 时把结果包登记为当前 workflow 临时对象，并在 workflow 结束时删除；默认不清理，也不影响 HTTP API 已有结果文件。",
                },
            },
            "required": ["task_id"],
        },
        capability_tags=("service.model.evaluation", "resource.package", "artifact.output"),
    ),
    handler=_yolox_evaluation_package_handler,
)