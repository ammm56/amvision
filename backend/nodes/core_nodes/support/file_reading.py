"""显式文件读取节点共享实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.file_payloads import require_file_ref_payload
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.ports.object_store import ObjectStore
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


DEFAULT_FILE_READ_MAX_BYTES = 1024 * 1024


def read_file_bytes(
    request: WorkflowNodeExecutionRequest,
    *,
    default_max_bytes: int = DEFAULT_FILE_READ_MAX_BYTES,
) -> tuple[dict[str, object], bytes]:
    """按不可变 identity 和显式大小上限读取单文件内容。"""

    payload = require_file_ref_payload(request.input_values.get("file"))
    max_bytes = request.parameters.get("max_bytes", default_max_bytes)
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise InvalidRequestError("文件读取节点的 max_bytes 必须是正整数")
    content_length = int(payload["content_length"])
    if content_length > max_bytes:
        raise InvalidRequestError(
            "文件内容超过节点读取上限",
            details={"content_length": content_length, "max_bytes": max_bytes},
        )
    object_store = request.execution_metadata.get("dataset_storage")
    if not isinstance(object_store, ObjectStore):
        raise ServiceConfigurationError("文件读取节点缺少 ObjectStore")
    with object_store.open_read_snapshot(
        str(payload["object_key"]),
        expected_version=str(payload["immutable_version"]),
        expected_checksum=str(payload["checksum"]),
    ) as snapshot:
        if snapshot.metadata.content_length != content_length:
            raise InvalidRequestError("file-ref content_length 与 ObjectStore 不一致")
        content = snapshot.stream.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise InvalidRequestError(
            "文件内容超过节点读取上限",
            details={"max_bytes": max_bytes},
        )
    return payload, content


__all__ = ["DEFAULT_FILE_READ_MAX_BYTES", "read_file_bytes"]
