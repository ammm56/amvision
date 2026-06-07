"""本地目录扫描节点。"""

from __future__ import annotations

import time
from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._local_io_node_support import (
    build_directory_file_record,
    resolve_local_directory_path_from_request,
)
from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.nodes.core_nodes._service_node_support import (
    get_optional_bool_parameter,
    get_optional_int_parameter,
    get_optional_str_parameter,
    get_optional_str_tuple_parameter,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _directory_scan_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """扫描本地目录并返回文件记录列表。"""

    directory_path = resolve_local_directory_path_from_request(
        request,
        parameter_name="directory_path",
    )
    recursive = bool(get_optional_bool_parameter(request, "recursive") or False)
    include_hidden = bool(get_optional_bool_parameter(request, "include_hidden") or False)
    glob_pattern = get_optional_str_parameter(request, "glob_pattern") or "*"
    extensions = _read_extensions(request)
    sort_by = _read_sort_by(request.parameters.get("sort_by"))
    descending = bool(get_optional_bool_parameter(request, "descending") or False)
    limit = _read_optional_limit(request)
    min_stable_age_seconds = _read_min_stable_age_seconds(
        request.parameters.get("min_stable_age_seconds")
    )
    dedupe_by = _read_dedupe_by(request.parameters.get("dedupe_by"))

    raw_records = [
        build_directory_file_record(file_path)
        for file_path in _list_directory_files(
            directory_path=directory_path,
            recursive=recursive,
            include_hidden=include_hidden,
            glob_pattern=glob_pattern,
            extensions=extensions,
        )
    ]
    records, unstable_skipped_count = _filter_unstable_records(
        raw_records,
        min_stable_age_seconds=min_stable_age_seconds,
        current_time_seconds=time.time(),
    )
    records = _sort_records(records, sort_by=sort_by, descending=descending)
    records, deduped_count = _dedupe_records(records, dedupe_by=dedupe_by)
    if limit is not None:
        records = records[:limit]
    return {
        "files": build_value_payload(records),
        "summary": build_value_payload(
            {
                "directory_path": str(directory_path),
                "raw_count": len(raw_records),
                "count": len(records),
                "recursive": recursive,
                "include_hidden": include_hidden,
                "glob_pattern": glob_pattern,
                "extensions": list(extensions),
                "sort_by": sort_by,
                "descending": descending,
                "limit": limit,
                "min_stable_age_seconds": min_stable_age_seconds,
                "unstable_skipped_count": unstable_skipped_count,
                "dedupe_by": dedupe_by,
                "deduped_count": deduped_count,
            }
        ),
    }


def _list_directory_files(
    *,
    directory_path: Path,
    recursive: bool,
    include_hidden: bool,
    glob_pattern: str,
    extensions: tuple[str, ...],
) -> list[Path]:
    """列出符合条件的文件。"""

    path_iterable = directory_path.rglob(glob_pattern) if recursive else directory_path.glob(glob_pattern)
    file_paths: list[Path] = []
    for file_path in path_iterable:
        if not file_path.is_file():
            continue
        if not include_hidden and any(part.startswith(".") for part in file_path.relative_to(directory_path).parts):
            continue
        if extensions and file_path.suffix.lower() not in extensions:
            continue
        file_paths.append(file_path.resolve())
    return file_paths


def _sort_records(
    records: list[dict[str, object]],
    *,
    sort_by: str,
    descending: bool,
) -> list[dict[str, object]]:
    """按指定字段排序扫描记录。"""

    if sort_by == "modified_time":
        return sorted(
            records,
            key=lambda item: (
                int(item.get("modified_time_epoch_ms", 0)),
                str(item["path"]).lower(),
            ),
            reverse=descending,
        )
    return sorted(records, key=lambda item: str(item["path"]).lower(), reverse=descending)


def _filter_unstable_records(
    records: list[dict[str, object]],
    *,
    min_stable_age_seconds: float,
    current_time_seconds: float,
) -> tuple[list[dict[str, object]], int]:
    """过滤掉最近仍在变化、尚未达到稳定期的文件。"""

    if min_stable_age_seconds <= 0:
        return list(records), 0
    kept_records: list[dict[str, object]] = []
    skipped_count = 0
    stable_before_epoch_ms = int(
        round((current_time_seconds - min_stable_age_seconds) * 1000)
    )
    for record in records:
        modified_time_epoch_ms = record.get("modified_time_epoch_ms")
        if (
            isinstance(modified_time_epoch_ms, int)
            and modified_time_epoch_ms > stable_before_epoch_ms
        ):
            skipped_count += 1
            continue
        kept_records.append(record)
    return kept_records, skipped_count


def _dedupe_records(
    records: list[dict[str, object]],
    *,
    dedupe_by: str,
) -> tuple[list[dict[str, object]], int]:
    """按指定策略对目录扫描记录去重。"""

    if dedupe_by == "none":
        return list(records), 0
    seen_keys: set[str] = set()
    deduped_records: list[dict[str, object]] = []
    deduped_count = 0
    for record in records:
        dedupe_key = _build_dedupe_key(record, dedupe_by=dedupe_by)
        if dedupe_key in seen_keys:
            deduped_count += 1
            continue
        seen_keys.add(dedupe_key)
        deduped_records.append(record)
    return deduped_records, deduped_count


def _build_dedupe_key(record: dict[str, object], *, dedupe_by: str) -> str:
    """构造目录扫描去重键。"""

    record_path = str(record.get("path") or "").strip().lower()
    file_name = str(record.get("file_name") or "").strip().lower()
    size_bytes = record.get("size_bytes")
    if dedupe_by == "path":
        return record_path
    if dedupe_by == "file_name":
        return file_name
    return f"{file_name}::{size_bytes}"


def _read_extensions(request: WorkflowNodeExecutionRequest) -> tuple[str, ...]:
    """读取扩展名过滤参数。"""

    raw_extensions = get_optional_str_tuple_parameter(request, "extensions")
    if raw_extensions is None:
        return ()
    normalized_extensions: list[str] = []
    for extension in raw_extensions:
        normalized_extension = extension.lower()
        if not normalized_extension.startswith("."):
            normalized_extension = f".{normalized_extension}"
        normalized_extensions.append(normalized_extension)
    return tuple(normalized_extensions)


def _read_sort_by(raw_value: object) -> str:
    """读取排序字段。"""

    if raw_value is None:
        return "name"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("directory-scan 的 sort_by 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"name", "modified_time"}:
        raise InvalidRequestError("directory-scan 的 sort_by 仅支持 name 或 modified_time")
    return normalized_value


def _read_optional_limit(request: WorkflowNodeExecutionRequest) -> int | None:
    """读取可选数量上限。"""

    limit = get_optional_int_parameter(request, "limit")
    if limit is None:
        return None
    if limit <= 0:
        raise InvalidRequestError("directory-scan 的 limit 必须大于 0")
    return limit


def _read_min_stable_age_seconds(raw_value: object) -> float:
    """读取文件最小稳定期。"""

    if raw_value is None:
        return 0.0
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(
            "directory-scan 的 min_stable_age_seconds 必须是数值"
        )
    normalized_value = float(raw_value)
    if normalized_value < 0:
        raise InvalidRequestError(
            "directory-scan 的 min_stable_age_seconds 不能小于 0"
        )
    return normalized_value


def _read_dedupe_by(raw_value: object) -> str:
    """读取目录扫描去重策略。"""

    if raw_value is None:
        return "none"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("directory-scan 的 dedupe_by 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {
        "none",
        "path",
        "file_name",
        "file_name_and_size",
    }:
        raise InvalidRequestError(
            "directory-scan 的 dedupe_by 仅支持 none、path、file_name 或 file_name_and_size"
        )
    return normalized_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.directory-scan",
        display_name="Directory Scan",
        category="io.input",
        description="扫描本地目录并输出文件记录列表，适合单帧工业批处理的本地输入准备。",
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
                name="files",
                display_name="Files",
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
                "directory_path": {"type": "string", "title": "目录路径"},
                "recursive": {"type": "boolean", "title": "递归扫描", "default": False},
                "include_hidden": {"type": "boolean", "title": "包含隐藏文件", "default": False},
                "glob_pattern": {"type": "string", "title": "Glob 模式", "default": "*"},
                "extensions": {
                    "type": "array",
                    "title": "扩展名过滤",
                    "items": {"type": "string"},
                },
                "sort_by": {
                    "type": "string",
                    "title": "排序字段",
                    "enum": ["name", "modified_time"],
                    "default": "name",
                },
                "descending": {"type": "boolean", "title": "倒序", "default": False},
                "limit": {"type": "integer", "title": "数量上限", "minimum": 1},
                "min_stable_age_seconds": {
                    "type": "number",
                    "title": "最小稳定期秒数",
                    "minimum": 0,
                    "default": 0,
                },
                "dedupe_by": {
                    "type": "string",
                    "title": "去重策略",
                    "enum": ["none", "path", "file_name", "file_name_and_size"],
                    "default": "none",
                },
            },
        },
        capability_tags=("io.input", "filesystem.scan", "inspection.batch-input"),
    ),
    handler=_directory_scan_handler,
)
