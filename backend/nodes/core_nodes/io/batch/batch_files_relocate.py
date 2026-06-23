"""批次文件归档节点。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.local_io import (
    build_directory_file_record,
    require_file_record_list,
    resolve_local_path_value_from_request,
)
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


NODE_NAME = "batch-files-relocate"


def _batch_files_relocate_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """把批次文件移动或复制到目标目录。"""

    file_records = require_file_record_list(
        request.input_values.get("files"),
        field_name="files",
        node_id=request.node_id,
    )
    mode = _read_mode(request.parameters.get("mode"))
    conflict_policy = _read_conflict_policy(request.parameters.get("conflict_policy"))
    preserve_subdirectories = _read_bool_parameter(
        request.parameters.get("preserve_subdirectories"),
        field_name="preserve_subdirectories",
        default_value=False,
    )
    dry_run = _read_bool_parameter(
        request.parameters.get("dry_run"),
        field_name="dry_run",
        default_value=False,
    )
    target_directory = resolve_local_path_value_from_request(
        request,
        parameter_name="target_directory",
        description="批次文件归档目标目录",
    )
    source_root = _resolve_source_root(
        file_records=file_records,
        parameter_value=request.parameters.get("source_root"),
        preserve_subdirectories=preserve_subdirectories,
    )
    if not dry_run:
        target_directory.mkdir(parents=True, exist_ok=True)

    relocated_files: list[dict[str, object]] = []
    mapping_items: list[dict[str, object]] = []
    relocated_count = 0
    skipped_count = 0
    for file_record in file_records:
        mapping_item, relocated_record = _relocate_single_file(
            file_record=file_record,
            target_directory=target_directory,
            source_root=source_root,
            mode=mode,
            conflict_policy=conflict_policy,
            preserve_subdirectories=preserve_subdirectories,
            dry_run=dry_run,
        )
        mapping_items.append(mapping_item)
        if relocated_record is not None:
            relocated_files.append(relocated_record)
        if str(mapping_item["status"]).startswith("relocated"):
            relocated_count += 1
        else:
            skipped_count += 1

    return {
        "files": build_value_payload(relocated_files),
        "mappings": build_value_payload(mapping_items),
        "summary": build_value_payload(
            {
                "mode": mode,
                "conflict_policy": conflict_policy,
                "preserve_subdirectories": preserve_subdirectories,
                "dry_run": dry_run,
                "target_directory": str(target_directory),
                "source_root": str(source_root) if source_root is not None else None,
                "count": len(file_records),
                "relocated_count": relocated_count,
                "skipped_count": skipped_count,
                "items": mapping_items,
            }
        ),
    }


def _relocate_single_file(
    *,
    file_record: dict[str, object],
    target_directory: Path,
    source_root: Path | None,
    mode: str,
    conflict_policy: str,
    preserve_subdirectories: bool,
    dry_run: bool,
) -> tuple[dict[str, object], dict[str, object] | None]:
    """处理单个文件的归档。"""

    source_path_value = file_record.get("path")
    if not isinstance(source_path_value, str) or not source_path_value.strip():
        raise InvalidRequestError("batch-files-relocate 的 files 项缺少有效 path")
    source_path = Path(source_path_value).expanduser().resolve()
    if not source_path.is_file():
        raise InvalidRequestError(
            "batch-files-relocate 只能处理已存在的本地文件",
            details={"source_path": str(source_path)},
        )

    destination_directory = target_directory
    if preserve_subdirectories and source_root is not None:
        try:
            relative_parent = source_path.parent.relative_to(source_root)
        except ValueError as exc:
            raise InvalidRequestError(
                "batch-files-relocate 的 source_root 必须覆盖全部 source 文件",
                details={"source_path": str(source_path), "source_root": str(source_root)},
            ) from exc
        destination_directory = target_directory / relative_parent
    destination_path = destination_directory / source_path.name
    if destination_path == source_path:
        relocated_record = build_directory_file_record(source_path)
        return (
            {
                "source_path": str(source_path),
                "target_path": str(destination_path),
                "status": "skipped.same-path",
            },
            relocated_record,
        )
    resolved_destination_path, status = _resolve_destination_path(
        source_path=source_path,
        destination_path=destination_path,
        conflict_policy=conflict_policy,
    )
    if status == "skipped.existing":
        return (
            {
                "source_path": str(source_path),
                "target_path": str(resolved_destination_path),
                "status": status,
            },
            build_directory_file_record(resolved_destination_path),
        )
    if not dry_run:
        resolved_destination_path.parent.mkdir(parents=True, exist_ok=True)
        if mode == "copy":
            shutil.copy2(source_path, resolved_destination_path)
        else:
            shutil.move(str(source_path), str(resolved_destination_path))
    relocated_record = (
        build_directory_file_record(resolved_destination_path)
        if not dry_run
        else {
            "path": str(resolved_destination_path),
            "file_name": resolved_destination_path.name,
            "extension": resolved_destination_path.suffix.lower(),
        }
    )
    final_status = f"relocated.{mode}"
    if status == "renamed":
        final_status = f"relocated.{mode}.renamed"
    return (
        {
            "source_path": str(source_path),
            "target_path": str(resolved_destination_path),
            "status": final_status,
        },
        relocated_record,
    )


def _resolve_destination_path(
    *,
    source_path: Path,
    destination_path: Path,
    conflict_policy: str,
) -> tuple[Path, str]:
    """按冲突策略解析目标文件路径。"""

    if not destination_path.exists():
        return destination_path, "ready"
    if not destination_path.is_file():
        raise InvalidRequestError(
            "batch-files-relocate 目标路径已存在且不是文件",
            details={"target_path": str(destination_path)},
        )
    if conflict_policy == "error":
        raise InvalidRequestError(
            "batch-files-relocate 目标文件已存在",
            details={"source_path": str(source_path), "target_path": str(destination_path)},
        )
    if conflict_policy == "skip":
        return destination_path, "skipped.existing"
    if conflict_policy == "overwrite":
        if destination_path.is_file():
            destination_path.unlink()
        return destination_path, "overwritten"
    return _build_renamed_destination_path(destination_path), "renamed"


def _build_renamed_destination_path(destination_path: Path) -> Path:
    """为冲突文件生成带序号的新路径。"""

    suffix = destination_path.suffix
    base_name = destination_path.name[: -len(suffix)] if suffix else destination_path.name
    candidate_index = 2
    while True:
        candidate_path = destination_path.with_name(
            f"{base_name}__{candidate_index}{suffix}"
        )
        if not candidate_path.exists():
            return candidate_path
        candidate_index += 1


def _resolve_source_root(
    *,
    file_records: list[dict[str, object]],
    parameter_value: object,
    preserve_subdirectories: bool,
) -> Path | None:
    """解析可选 source_root。"""

    if not preserve_subdirectories:
        return None
    if parameter_value is not None:
        if not isinstance(parameter_value, str) or not parameter_value.strip():
            raise InvalidRequestError("batch-files-relocate 的 source_root 必须是非空字符串")
        return Path(parameter_value.strip()).expanduser().resolve()
    source_parent_paths = [
        str(Path(str(file_record["path"])).expanduser().resolve().parent)
        for file_record in file_records
    ]
    if not source_parent_paths:
        return None
    common_path = source_parent_paths[0]
    if len(source_parent_paths) > 1:
        common_path = os.path.commonpath(source_parent_paths)
    return Path(common_path).resolve()


def _read_mode(raw_value: object) -> str:
    """读取移动/复制模式。"""

    if raw_value is None:
        return "copy"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("batch-files-relocate 的 mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"copy", "move"}:
        raise InvalidRequestError("batch-files-relocate 的 mode 仅支持 copy 或 move")
    return normalized_value


def _read_conflict_policy(raw_value: object) -> str:
    """读取冲突策略。"""

    if raw_value is None:
        return "rename"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("batch-files-relocate 的 conflict_policy 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"error", "skip", "overwrite", "rename"}:
        raise InvalidRequestError(
            "batch-files-relocate 的 conflict_policy 仅支持 error、skip、overwrite 或 rename"
        )
    return normalized_value


def _read_bool_parameter(
    raw_value: object,
    *,
    field_name: str,
    default_value: bool,
) -> bool:
    """读取布尔参数。"""

    if raw_value is None:
        return default_value
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"batch-files-relocate 的 {field_name} 必须是布尔值")
    return raw_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.batch-files-relocate",
        display_name="Batch Files Relocate",
        category="io.output",
        description="把当前批次文件复制或移动到 processed/archive/failed/quarantine 等目标目录，并输出目标文件列表与映射摘要。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="files",
                display_name="Files",
                payload_type_id="value.v1",
            ),
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
                name="mappings",
                display_name="Mappings",
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
                "target_directory": {"type": "string", "title": "目标目录"},
                "source_root": {"type": "string", "title": "源根目录"},
                "mode": {
                    "type": "string",
                    "title": "归档模式",
                    "enum": ["copy", "move"],
                    "default": "copy",
                },
                "conflict_policy": {
                    "type": "string",
                    "title": "冲突策略",
                    "enum": ["error", "skip", "overwrite", "rename"],
                    "default": "rename",
                },
                "preserve_subdirectories": {
                    "type": "boolean",
                    "title": "保留子目录结构",
                    "default": False,
                },
                "dry_run": {
                    "type": "boolean",
                    "title": "仅预演不落盘",
                    "default": False,
                },
            },
        },
        capability_tags=("io.output", "filesystem.relocate", "inspection.batch-output"),
    ),
    handler=_batch_files_relocate_handler,
)
