"""本地输入输出类 core 节点共享 helper。"""

from __future__ import annotations

import io
from datetime import UTC, datetime
import json
from pathlib import Path

from PIL import Image

from backend.nodes.core_nodes._logic_node_support import (
    build_value_payload,
    require_value_payload,
)
from backend.nodes.runtime_support import infer_media_type, infer_media_type_from_image_bytes
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
    resolved_path = Path(raw_value.strip()).expanduser().resolve()
    return resolved_path


def resolve_value_or_result_input(
    request: WorkflowNodeExecutionRequest,
    *,
    value_input_name: str = "value",
    result_input_name: str = "result",
    alarm_input_name: str = "alarm",
) -> tuple[object, str]:
    """读取 value、result-record 或 alarm-record 输入，且要求三选一。"""

    value_input = request.input_values.get(value_input_name)
    result_input = request.input_values.get(result_input_name)
    alarm_input = request.input_values.get(alarm_input_name)
    provided_count = sum(
        1
        for item in (value_input, result_input, alarm_input)
        if item is not None
    )
    if provided_count != 1:
        raise InvalidRequestError(
            "节点要求三选一提供 value、result 或 alarm 输入",
            details={
                "node_id": request.node_id,
                "value_input_name": value_input_name,
                "result_input_name": result_input_name,
                "alarm_input_name": alarm_input_name,
            },
        )
    if value_input is not None:
        return require_value_payload(value_input, field_name=value_input_name)["value"], "value"
    if result_input is not None:
        if not isinstance(result_input, dict):
            raise InvalidRequestError(
                "result 输入必须是对象",
                details={"node_id": request.node_id, "input_name": result_input_name},
            )
        return json.loads(json.dumps(result_input, ensure_ascii=False)), "result-record"
    if not isinstance(alarm_input, dict):
        raise InvalidRequestError(
            "alarm 输入必须是对象",
            details={"node_id": request.node_id, "input_name": alarm_input_name},
        )
    return json.loads(json.dumps(alarm_input, ensure_ascii=False)), "alarm-record"


def build_local_file_summary(
    *,
    local_path: Path,
    extra_fields: dict[str, object] | None = None,
) -> dict[str, object]:
    """构造本地文件输出摘要。"""

    summary: dict[str, object] = {
        "local_path": str(local_path),
        "file_name": local_path.name,
    }
    if local_path.exists():
        stat_result = local_path.stat()
        summary["size_bytes"] = stat_result.st_size
        summary["modified_time_iso"] = _build_iso_timestamp(stat_result.st_mtime)
    if extra_fields:
        summary.update(extra_fields)
    return build_value_payload(summary)


def build_directory_file_record(file_path: Path) -> dict[str, object]:
    """把文件路径规范化为目录扫描记录。"""

    stat_result = file_path.stat()
    return {
        "path": str(file_path),
        "file_name": file_path.name,
        "extension": file_path.suffix.lower(),
        "size_bytes": stat_result.st_size,
        "modified_time_epoch_ms": int(round(stat_result.st_mtime * 1000)),
        "modified_time_iso": _build_iso_timestamp(stat_result.st_mtime),
    }


def require_file_record_list(
    payload: object,
    *,
    field_name: str,
    node_id: str,
) -> list[dict[str, object]]:
    """读取并规范化文件记录列表。"""

    raw_items = require_value_payload(payload, field_name=field_name)["value"]
    if not isinstance(raw_items, list):
        raise InvalidRequestError(
            f"{field_name} payload 中的 value 必须是数组",
            details={"node_id": node_id, "field_name": field_name},
        )
    normalized_records: list[dict[str, object]] = []
    for item_index, raw_item in enumerate(raw_items, start=1):
        if isinstance(raw_item, str) and raw_item.strip():
            file_path = Path(raw_item.strip()).expanduser().resolve()
            normalized_records.append({"path": str(file_path), "file_name": file_path.name})
            continue
        if isinstance(raw_item, dict):
            raw_path = raw_item.get("path")
            if isinstance(raw_path, str) and raw_path.strip():
                file_path = Path(raw_path.strip()).expanduser().resolve()
                normalized_record = dict(raw_item)
                normalized_record["path"] = str(file_path)
                normalized_record.setdefault("file_name", file_path.name)
                normalized_record.setdefault("extension", file_path.suffix.lower())
                normalized_records.append(normalized_record)
                continue
        raise InvalidRequestError(
            f"{field_name} 数组项必须是路径字符串或包含 path 的对象",
            details={"node_id": node_id, "field_name": field_name, "item_index": item_index},
        )
    return normalized_records


def read_local_image_file(file_path: Path) -> tuple[bytes, str, int, int]:
    """读取本地图像文件并返回字节、媒体类型和尺寸。"""

    image_bytes = file_path.read_bytes()
    if not image_bytes:
        raise InvalidRequestError(
            "本地图像文件不能为空",
            details={"local_path": str(file_path)},
        )
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            width, height = image.size
    except Exception as exc:  # noqa: BLE001
        raise InvalidRequestError(
            "本地图像文件不是有效图片",
            details={"local_path": str(file_path)},
        ) from exc
    if width <= 0 or height <= 0:
        raise InvalidRequestError(
            "本地图像文件宽高无效",
            details={"local_path": str(file_path)},
        )
    media_type = infer_media_type_from_image_bytes(image_bytes)
    if media_type == "image/png":
        media_type = infer_media_type(file_path.name)
    return image_bytes, media_type, width, height


def flatten_mapping_for_csv(value: object) -> dict[str, str]:
    """把 JSON 安全值扁平化为 CSV 可写的一行字符串字典。"""

    normalized_value = json.loads(json.dumps(value, ensure_ascii=False))
    flattened: dict[str, str] = {}
    _flatten_value_for_csv(
        value=normalized_value,
        target=flattened,
        prefix="",
    )
    return flattened


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


def _build_iso_timestamp(timestamp_seconds: float) -> str:
    """把时间戳转换为 UTC ISO 文本。"""

    return datetime.fromtimestamp(timestamp_seconds, tz=UTC).isoformat()


def _flatten_value_for_csv(
    *,
    value: object,
    target: dict[str, str],
    prefix: str,
) -> None:
    """递归展开 CSV 行字段。"""

    if isinstance(value, dict):
        for key, item in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            _flatten_value_for_csv(value=item, target=target, prefix=next_prefix)
        return
    if isinstance(value, list):
        target[prefix or "value"] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return
    target[prefix or "value"] = "" if value is None else str(value)
