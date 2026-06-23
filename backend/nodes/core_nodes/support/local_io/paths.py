"""本地路径解析 helper。"""

from __future__ import annotations

from pathlib import Path

from backend.nodes.core_nodes.support.logic import require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def resolve_local_file_path_from_request(
    request: WorkflowNodeExecutionRequest,
    *,
    parameter_name: str,
    input_name: str = "path",
    description: str,
) -> Path:
    """从节点参数或 value 输入解析本地文件路径。"""

    raw_value = _read_optional_path_input(request, input_name=input_name)
    if raw_value is None:
        raw_value = request.parameters.get(parameter_name)
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(
            f"{description}路径必须是非空字符串",
            details={"node_id": request.node_id, "parameter_name": parameter_name},
        )
    resolved_path = Path(raw_value.strip()).expanduser().resolve()
    if not resolved_path.is_file():
        raise InvalidRequestError(
            f"{description}不存在",
            details={"node_id": request.node_id, "local_path": str(resolved_path)},
        )
    return resolved_path


def resolve_local_directory_path_from_request(
    request: WorkflowNodeExecutionRequest,
    *,
    parameter_name: str,
    input_name: str = "path",
) -> Path:
    """从节点参数或 value 输入解析本地目录路径。"""

    raw_value = _read_optional_path_input(request, input_name=input_name)
    if raw_value is None:
        raw_value = request.parameters.get(parameter_name)
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(
            "目录路径必须是非空字符串",
            details={"node_id": request.node_id, "parameter_name": parameter_name},
        )
    resolved_path = Path(raw_value.strip()).expanduser().resolve()
    if not resolved_path.is_dir():
        raise InvalidRequestError(
            "本地目录不存在",
            details={"node_id": request.node_id, "directory_path": str(resolved_path)},
        )
    return resolved_path


def resolve_local_output_file_path(
    request: WorkflowNodeExecutionRequest,
    *,
    parameter_name: str,
    input_name: str = "path",
    overwrite: bool,
    description: str,
) -> Path:
    """从节点参数或 value 输入解析本地输出文件路径。"""

    resolved_path = resolve_local_path_value_from_request(
        request,
        parameter_name=parameter_name,
        input_name=input_name,
        description=description,
    )
    if resolved_path.exists() and not overwrite:
        raise InvalidRequestError(
            f"{description}已存在，且当前节点未允许覆盖",
            details={"node_id": request.node_id, "local_path": str(resolved_path)},
        )
    return resolved_path


def resolve_local_path_value_from_request(
    request: WorkflowNodeExecutionRequest,
    *,
    parameter_name: str,
    input_name: str = "path",
    description: str,
) -> Path:
    """从节点参数或 value 输入解析本地路径值，但不检查路径是否已存在。"""

    raw_value = _read_optional_path_input(request, input_name=input_name)
    if raw_value is None:
        raw_value = request.parameters.get(parameter_name)
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(
            f"{description}路径必须是非空字符串",
            details={"node_id": request.node_id, "parameter_name": parameter_name},
        )
    return Path(raw_value.strip()).expanduser().resolve()


def _read_optional_path_input(
    request: WorkflowNodeExecutionRequest,
    *,
    input_name: str,
) -> str | None:
    """读取可选 value.v1 路径输入。"""

    raw_payload = request.input_values.get(input_name)
    if raw_payload is None:
        return None
    raw_value = require_value_payload(raw_payload, field_name=input_name)["value"]
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(
            f"{input_name} 输入必须是非空字符串",
            details={"node_id": request.node_id, "input_name": input_name},
        )
    return raw_value.strip()
