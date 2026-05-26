"""图片保存节点。"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.runtime_support import copy_image_payload, require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.infrastructure.object_store.object_key_layout import (
    build_project_workflow_application_results_dir,
)


def _image_save_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把输入图片复制到目标 object key。"""

    overwrite = bool(request.parameters.get("overwrite", True))
    saved_payload = copy_image_payload(
        request,
        source_payload=require_image_payload(request.input_values.get("image")),
        object_key=_resolve_object_key_template(request, request.parameters.get("object_key")),
        overwrite=overwrite,
        variant_name="saved",
    )
    return {"image": saved_payload}


def _resolve_object_key_template(
    request: WorkflowNodeExecutionRequest,
    raw_object_key: object,
) -> str | None:
    """解析 image-save 的 object_key 模板。"""

    if not isinstance(raw_object_key, str) or not raw_object_key.strip():
        return None

    normalized_object_key = raw_object_key.strip()
    try:
        return normalized_object_key.format(**_build_object_key_format_context(request))
    except KeyError as exc:
        raise InvalidRequestError(
            "image-save object_key 模板包含不支持的占位符",
            details={"node_id": request.node_id, "placeholder": exc.args[0]},
        ) from exc


def _build_object_key_format_context(request: WorkflowNodeExecutionRequest) -> dict[str, str]:
    """构建 image-save object_key 模板可用的占位符上下文。

    参数：
    - request：当前节点执行请求。

    返回：
    - dict[str, str]：可用于 format 的占位符映射。
    """

    workflow_run_id = str(request.execution_metadata.get("workflow_run_id") or "default-run")
    context = {
        "workflow_run_id": workflow_run_id,
        "timestamp": datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"),
        "node_id": request.node_id,
    }
    project_id = _read_optional_execution_metadata_text(request, key="project_id")
    if project_id is not None:
        context["project_id"] = project_id
    application_id = _read_optional_execution_metadata_text(request, key="application_id")
    if application_id is not None:
        context["application_id"] = application_id
    if project_id is not None and application_id is not None:
        context["workflow_app_result_dir"] = build_project_workflow_application_results_dir(
            project_id=project_id,
            application_id=application_id,
            workflow_run_id=workflow_run_id,
        )
    return context


def _read_optional_execution_metadata_text(
    request: WorkflowNodeExecutionRequest,
    *,
    key: str,
) -> str | None:
    """读取 execution_metadata 中的可选文本字段。

    参数：
    - request：当前节点执行请求。
    - key：目标字段名称。

    返回：
    - str | None：规范化后的文本值；缺失或为空时返回 None。
    """

    raw_value = request.execution_metadata.get(key)
    if not isinstance(raw_value, str):
        return None
    normalized_value = raw_value.strip()
    return normalized_value or None


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.image-save",
        display_name="Save Image",
        category="io.output",
        description="把图片引用复制到指定 object key，供后续节点或外部接口复用。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "object_key": {"type": "string"},
                "overwrite": {"type": "boolean"},
            },
        },
        capability_tags=("io.output", "image.persist"),
    ),
    handler=_image_save_handler,
)