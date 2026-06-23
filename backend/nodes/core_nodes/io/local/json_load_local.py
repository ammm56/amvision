"""本地 JSON 读取节点。"""

from __future__ import annotations

import json

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.local_io import (
    build_local_file_summary,
    resolve_local_path_value_from_request,
)
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _json_load_local_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """从本地 JSON 文件读取值，并支持缺失或坏文件回退。"""

    local_path = resolve_local_path_value_from_request(
        request,
        parameter_name="local_path",
        description="本地 JSON 输入文件",
    )
    default_value = request.parameters.get("default_value")
    if not local_path.exists():
        if _read_allow_missing(request.parameters.get("allow_missing")):
            return _build_default_response(
                local_path=local_path,
                default_value=default_value,
                default_reason="missing-file",
            )
        raise InvalidRequestError(
            "本地 JSON 输入文件不存在",
            details={"node_id": request.node_id, "local_path": str(local_path)},
        )
    if not local_path.is_file():
        raise InvalidRequestError(
            "本地 JSON 输入路径不是文件",
            details={"node_id": request.node_id, "local_path": str(local_path)},
        )
    try:
        file_text = local_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        if _read_allow_invalid_json(request.parameters.get("allow_invalid_json")):
            return _build_default_response(
                local_path=local_path,
                default_value=default_value,
                default_reason="invalid-encoding",
            )
        raise InvalidRequestError(
            "本地 JSON 输入文件不是有效 UTF-8 文本",
            details={"node_id": request.node_id, "local_path": str(local_path)},
        ) from exc
    except OSError as exc:
        raise InvalidRequestError(
            "本地 JSON 输入文件读取失败",
            details={"node_id": request.node_id, "local_path": str(local_path)},
        ) from exc
    if not file_text.strip():
        if _read_allow_invalid_json(request.parameters.get("allow_invalid_json")):
            return _build_default_response(
                local_path=local_path,
                default_value=default_value,
                default_reason="empty-file",
            )
        raise InvalidRequestError(
            "本地 JSON 输入文件不能为空",
            details={"node_id": request.node_id, "local_path": str(local_path)},
        )
    try:
        loaded_value = json.loads(file_text)
    except json.JSONDecodeError as exc:
        if _read_allow_invalid_json(request.parameters.get("allow_invalid_json")):
            return _build_default_response(
                local_path=local_path,
                default_value=default_value,
                default_reason="invalid-json",
            )
        raise InvalidRequestError(
            "本地 JSON 输入文件不是有效 JSON",
            details={
                "node_id": request.node_id,
                "local_path": str(local_path),
                "line": exc.lineno,
                "column": exc.colno,
            },
        ) from exc
    return {
        "value": build_value_payload(loaded_value),
        "summary": build_local_file_summary(
            local_path=local_path,
            extra_fields={
                "loaded_from_default": False,
                "default_reason": None,
                "value_type": _describe_value_type(loaded_value),
            },
        ),
    }


def _build_default_response(
    *,
    local_path,
    default_value: object,
    default_reason: str,
) -> dict[str, object]:
    """构造默认值回退输出。"""

    summary_payload = build_local_file_summary(
        local_path=local_path,
        extra_fields={
            "loaded_from_default": True,
            "default_reason": default_reason,
            "value_type": _describe_value_type(default_value),
        },
    )
    return {
        "value": build_value_payload(default_value),
        "summary": summary_payload,
    }


def _read_allow_missing(raw_value: object) -> bool:
    """读取是否允许文件缺失。"""

    if raw_value is None:
        return False
    if not isinstance(raw_value, bool):
        raise InvalidRequestError("json-load-local 的 allow_missing 必须是布尔值")
    return raw_value


def _read_allow_invalid_json(raw_value: object) -> bool:
    """读取是否允许坏 JSON 回退默认值。"""

    if raw_value is None:
        return False
    if not isinstance(raw_value, bool):
        raise InvalidRequestError("json-load-local 的 allow_invalid_json 必须是布尔值")
    return raw_value


def _describe_value_type(value: object) -> str:
    """输出已加载值的简单类型说明。"""

    if value is None:
        return "null"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.json-load-local",
        display_name="Load Local JSON",
        category="io.input",
        description="读取本地 JSON 文件并输出 value.v1，适合目录轮询 cursor、本地配置和结果归档索引恢复。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="path",
                display_name="Path",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "local_path": {"type": "string", "title": "本地 JSON 路径"},
                "allow_missing": {"type": "boolean", "title": "允许文件缺失", "default": False},
                "allow_invalid_json": {
                    "type": "boolean",
                    "title": "允许坏 JSON 回退默认值",
                    "default": False,
                },
                "default_value": {"title": "默认值"},
            },
        },
        capability_tags=("io.input", "json.load", "inspection.polling.state"),
    ),
    handler=_json_load_local_handler,
)
