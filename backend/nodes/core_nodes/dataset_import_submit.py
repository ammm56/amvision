"""数据集导入 service node。"""

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
    get_optional_dict_parameter,
    get_optional_str_parameter,
    overlay_parameters_from_object_input,
    require_str_parameter,
    require_workflow_service_node_runtime,
    resolve_created_by,
)
from backend.service.application.datasets.dataset_import import DatasetImportRequest
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.workers.datasets.dataset_import_queue_worker import DATASET_IMPORT_QUEUE_NAME


def _dataset_import_submit_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """调用现有 DatasetImport 提交服务并入队。"""

    request = overlay_parameters_from_object_input(request)
    runtime_context = require_workflow_service_node_runtime(request)
    package_payload = _require_dataset_package_payload(request.input_values.get("package"))
    project_id = require_str_parameter(request, "project_id")
    dataset_id = require_str_parameter(request, "dataset_id")
    created_by = resolve_created_by(request)
    metadata = get_optional_dict_parameter(request, "metadata")
    if created_by is not None:
        metadata = {**metadata, "principal_id": created_by}

    import_service = runtime_context.build_dataset_import_service()
    submitted_import = import_service.submit_dataset_import(
        DatasetImportRequest(
            project_id=project_id,
            dataset_id=dataset_id,
            package_file_name=package_payload["package_file_name"],
            package_bytes=package_payload["package_bytes"],
            format_type=get_optional_str_parameter(request, "format_type"),
            task_type=get_optional_str_parameter(request, "task_type") or "detection",
            split_strategy=get_optional_str_parameter(request, "split_strategy"),
            class_map=_read_class_map_parameter(request),
            metadata=metadata,
        )
    )
    queue_task = runtime_context.require_queue_backend().enqueue(
        queue_name=DATASET_IMPORT_QUEUE_NAME,
        payload={"dataset_import_id": submitted_import.dataset_import_id},
        metadata={
            "project_id": project_id,
            "dataset_id": dataset_id,
        },
    )
    queued_import = import_service.mark_dataset_import_queued(
        submitted_import.dataset_import_id,
        queue_name=queue_task.queue_name,
        queue_task_id=queue_task.task_id,
    )
    return build_response_body_output(
        {
            "dataset_import_id": queued_import.dataset_import_id,
            "task_id": _read_optional_text(queued_import.metadata, "task_id"),
            "status": queued_import.status,
            "upload_state": _read_optional_text(queued_import.metadata, "upload_state") or "uploaded",
            "processing_state": _read_optional_text(queued_import.metadata, "processing_state") or "queued",
            "package_size": _read_optional_int(queued_import.metadata, "package_size") or 0,
            "package_path": queued_import.package_path,
            "staging_path": queued_import.staging_path,
            "queue_name": queue_task.queue_name,
            "queue_task_id": queue_task.task_id,
        }
    )


def _require_dataset_package_payload(payload: object) -> dict[str, object]:
    """校验并规范化数据集上传 payload。

    参数：
    - payload：待校验的上传 payload。

    返回：
    - dict[str, object]：规范化后的数据集上传 payload。
    """

    if not isinstance(payload, dict):
        raise InvalidRequestError("DatasetImport 节点要求 package payload 必须是对象")
    package_file_name = payload.get("package_file_name")
    package_bytes = payload.get("package_bytes")
    if not isinstance(package_file_name, str) or not package_file_name.strip():
        raise InvalidRequestError("DatasetImport 节点要求 package_file_name 必须是非空字符串")
    normalized_package_bytes = _normalize_binary_payload(package_bytes)
    if not normalized_package_bytes:
        raise InvalidRequestError("DatasetImport 节点要求 package_bytes 必须是非空二进制内容")
    normalized_payload: dict[str, object] = {
        "package_file_name": package_file_name.strip(),
        "package_bytes": normalized_package_bytes,
    }
    media_type = payload.get("media_type")
    if isinstance(media_type, str) and media_type.strip():
        normalized_payload["media_type"] = media_type.strip()
    return normalized_payload


def _normalize_binary_payload(value: object) -> bytes:
    """把上传 payload 中的二进制值规范化为 bytes。"""

    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    return b""


def _read_class_map_parameter(request: WorkflowNodeExecutionRequest) -> dict[str, str]:
    """读取并校验类别映射参数。"""

    class_map = get_optional_dict_parameter(request, "class_map")
    normalized_class_map: dict[str, str] = {}
    for key, value in class_map.items():
        if not isinstance(key, str) or not key.strip():
            raise InvalidRequestError(
                "参数 class_map 的每个键都必须是非空字符串",
                details={"node_id": request.node_id, "parameter": "class_map"},
            )
        if not isinstance(value, str) or not value.strip():
            raise InvalidRequestError(
                "参数 class_map 的每个值都必须是非空字符串",
                details={"node_id": request.node_id, "parameter": "class_map"},
            )
        normalized_class_map[key.strip()] = value.strip()
    return normalized_class_map


def _read_optional_text(metadata: dict[str, object], key: str) -> str | None:
    """从导入元数据中读取可选文本字段。"""

    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _read_optional_int(metadata: dict[str, object], key: str) -> int | None:
    """从导入元数据中读取可选整数字段。"""

    value = metadata.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.service.dataset-import.submit",
        display_name="Submit Dataset Import",
        category="service.dataset.import",
        description="按现有 DatasetImport API 的上传语义直接提交一个数据集导入任务。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="package",
                display_name="Package",
                payload_type_id="dataset-package.v1",
            ),
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
                "format_type": {"type": "string"},
                "task_type": {"type": "string"},
                "split_strategy": {"type": "string"},
                "class_map": {"type": "object"},
                "metadata": {"type": "object"},
                "created_by": {"type": "string"},
            },
            "required": ["project_id", "dataset_id"],
        },
        capability_tags=("service.dataset.import", "task.submit", "multipart.upload"),
    ),
    handler=_dataset_import_submit_handler,
)