"""数据集导出 service node。"""

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
    get_optional_str_tuple_parameter,
    overlay_parameters_from_object_input,
    require_str_parameter,
    require_workflow_service_node_runtime,
    resolve_created_by,
    resolve_display_name,
)
from backend.service.application.datasets.dataset_export import DatasetExportRequest
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _dataset_export_submit_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """调用现有 DatasetExport 任务提交服务。"""

    request = overlay_parameters_from_object_input(request)
    runtime_context = require_workflow_service_node_runtime(request)
    submission = runtime_context.build_dataset_export_task_service().submit_export_task(
        DatasetExportRequest(
            project_id=require_str_parameter(request, "project_id"),
            dataset_id=require_str_parameter(request, "dataset_id"),
            dataset_version_id=require_str_parameter(request, "dataset_version_id"),
            format_id=require_str_parameter(request, "format_id"),
            output_object_prefix=get_optional_str_parameter(request, "output_object_prefix") or "",
            category_names=get_optional_str_tuple_parameter(request, "category_names") or (),
            include_test_split=get_optional_bool_parameter(request, "include_test_split")
            if get_optional_bool_parameter(request, "include_test_split") is not None
            else True,
        ),
        created_by=resolve_created_by(request),
        display_name=resolve_display_name(request),
    )
    return build_response_body_output(submission)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.service.dataset-export.submit",
        display_name="Submit Dataset Export",
        category="service.dataset.export",
        description="按现有 DatasetExport API 的公开参数直接提交一个导出任务。",
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
                "project_id": {"type": "string"},
                "dataset_id": {"type": "string"},
                "dataset_version_id": {"type": "string"},
                "format_id": {"type": "string"},
                "output_object_prefix": {"type": "string"},
                "category_names": {"type": "array", "items": {"type": "string"}},
                "include_test_split": {"type": "boolean"},
                "display_name": {"type": "string"},
                "created_by": {"type": "string"},
            },
            "required": ["project_id", "dataset_id", "dataset_version_id", "format_id"],
        },
        capability_tags=("service.dataset.export", "task.submit"),
    ),
    handler=_dataset_export_submit_handler,
)