"""生产结果文件保留清理节点。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from functools import partial
import os
from pathlib import Path, PurePosixPath
import stat
from time import monotonic
from typing import cast

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodeParameterInputBinding,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.runtime_support import require_dataset_storage
from backend.nodes.save_locations import (
    SAVE_LOCATION_FILESYSTEM,
    SAVE_LOCATION_OBJECT_STORE,
    resolve_required_save_location_from_request,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.ports.object_store import (
    RetentionDeleteState,
    RetentionObjectMetadata,
    RetentionObjectStore,
)
from backend.service.application.runtime.io import try_acquire_path_write_locks
from backend.service.application.runtime.io.storage_retention import (
    RetentionPolicy,
    RetentionUnit,
    StorageRetentionOptions,
    calculate_retention_cutoff,
    execute_storage_retention,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from backend.service.infrastructure.filesystem.retention_files import (
    delete_empty_local_retention_directories,
    delete_local_retention_file_if_version,
    iter_local_retention_pages,
)


_SUPPORTED_POLICIES = {"age", "count", "age-and-count"}
_SUPPORTED_UNITS = {"day", "month", "year"}
_WINDOWS_REPARSE_POINT = 0x0400
_PAGE_SIZE = 512
_TARGET_COORDINATION_NAME = ".amvision-retention-cleanup-operation"


def _storage_retention_cleanup_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """扫描指定结果目录，并按显式策略执行一次有界清理。"""

    started_at = monotonic()
    options = _read_options(request)
    save_location = resolve_required_save_location_from_request(
        request,
        scope="directory",
        parameter_name="target_directory",
        input_name="target_directory",
    )
    current_time = datetime.now().astimezone()
    if save_location.kind == SAVE_LOCATION_FILESYSTEM:
        target_path = _require_filesystem_target(
            request,
            save_location.filesystem_path,
            lexical_target=save_location.lexical_filesystem_path,
        )
        target_directory = str(target_path)
        if not target_path.exists():
            return {
                "result": build_value_payload(
                    _build_empty_result(
                        options=options,
                        target_directory=target_directory,
                        location_kind=SAVE_LOCATION_FILESYSTEM,
                        state="target_not_found",
                        duration_ms=_elapsed_milliseconds(started_at),
                        current_time=current_time,
                    )
                )
            }
        if not target_path.is_dir():
            raise InvalidRequestError("Storage Retention Cleanup 目标必须是目录")
        recursive = _read_bool(request, "recursive", default=True)
        iter_pages = partial(
            iter_local_retention_pages,
            target_path,
            recursive=recursive,
            page_size=_PAGE_SIZE,
        )
        delete_item = _build_filesystem_delete(request, target_path=target_path)
        delete_empty = partial(
            delete_empty_local_retention_directories,
            target_path,
            recursive=recursive,
        )
        coordination_path = target_path / _TARGET_COORDINATION_NAME
        location_kind = SAVE_LOCATION_FILESYSTEM
    else:
        target_directory = str(save_location.object_key or "")
        storage = _require_retention_object_store(request)
        _validate_object_store_target(
            request,
            storage=storage,
            target_directory=target_directory,
        )
        if not storage.retention_prefix_exists(target_directory):
            return {
                "result": build_value_payload(
                    _build_empty_result(
                        options=options,
                        target_directory=target_directory,
                        location_kind=SAVE_LOCATION_OBJECT_STORE,
                        state="target_not_found",
                        duration_ms=_elapsed_milliseconds(started_at),
                        current_time=current_time,
                    )
                )
            }
        recursive = _read_bool(request, "recursive", default=True)
        iter_pages = partial(
            storage.iter_retention_object_pages,
            target_directory,
            recursive=recursive,
            page_size=_PAGE_SIZE,
        )
        delete_item = _build_object_store_delete(request, storage=storage)
        delete_empty = partial(
            storage.delete_empty_retention_prefixes,
            target_directory,
            recursive=recursive,
        )
        resolve = getattr(storage, "resolve", None)
        if not callable(resolve):
            raise ServiceConfigurationError(
                "当前 ObjectStore 不支持本机清理操作协调",
                details={"node_id": request.node_id},
            )
        coordination_path = resolve(target_directory) / _TARGET_COORDINATION_NAME
        location_kind = SAVE_LOCATION_OBJECT_STORE

    try:
        with try_acquire_path_write_locks(
            request,
            (coordination_path,),
        ) as target_lock_acquired:
            if not target_lock_acquired:
                payload = _build_empty_result(
                    options=options,
                    target_directory=target_directory,
                    location_kind=location_kind,
                    state="target_locked",
                    duration_ms=_elapsed_milliseconds(started_at),
                    current_time=current_time,
                )
                payload["has_more"] = True
                payload["target_lock_conflict"] = True
                return {"result": build_value_payload(payload)}
            result = execute_storage_retention(
                options=options,
                current_time=current_time,
                iter_pages=iter_pages,
                delete_item=delete_item,
                delete_empty_directories=delete_empty,
            )
    except OSError as error:
        raise InvalidRequestError(
            "Storage Retention Cleanup 无法扫描或删除目标目录",
            details={
                "node_id": request.node_id,
                "target_directory": target_directory,
                "error_type": type(error).__name__,
            },
        ) from error
    payload = _build_result_payload(
        options=options,
        target_directory=target_directory,
        location_kind=location_kind,
        result=result,
    )
    return {"result": build_value_payload(payload)}


def _read_options(request: WorkflowNodeExecutionRequest) -> StorageRetentionOptions:
    """严格读取节点参数并按策略校验必填组合。"""

    policy = _read_choice(
        request.parameters.get("retention_policy", "age"),
        field_name="retention_policy",
        supported_values=_SUPPORTED_POLICIES,
    )
    retention_value = _read_optional_positive_int(request, "retention_value")
    retention_unit = _read_optional_choice(
        request.parameters.get("retention_unit"),
        field_name="retention_unit",
        supported_values=_SUPPORTED_UNITS,
    )
    max_file_count = _read_optional_positive_int(request, "max_file_count")
    if policy in {"age", "age-and-count"} and (
        retention_value is None or retention_unit is None
    ):
        raise InvalidRequestError(
            "时间保留策略必须配置 retention_value 和 retention_unit"
        )
    if policy in {"count", "age-and-count"} and max_file_count is None:
        raise InvalidRequestError("数量保留策略必须配置 max_file_count")
    include_patterns = _read_include_patterns(
        request.parameters.get("include_patterns")
    )
    return StorageRetentionOptions(
        retention_policy=cast(RetentionPolicy, policy),
        retention_value=retention_value,
        retention_unit=cast(RetentionUnit | None, retention_unit),
        max_file_count=max_file_count,
        include_patterns=include_patterns,
        delete_limit=_read_positive_int(request, "delete_limit", default=1000),
        dry_run=_read_bool(request, "dry_run", default=True),
        delete_empty_directories=_read_bool(
            request,
            "delete_empty_directories",
            default=False,
        ),
    )


def _require_filesystem_target(
    request: WorkflowNodeExecutionRequest,
    raw_target: Path | None,
    *,
    lexical_target: Path | None = None,
) -> Path:
    """规范化本机目标并拒绝过宽根目录和 reparse point。"""

    if raw_target is None:
        raise InvalidRequestError("Storage Retention Cleanup 缺少本机目标路径")
    unresolved_target = lexical_target or raw_target
    try:
        unresolved_stat = unresolved_target.lstat()
    except FileNotFoundError:
        unresolved_stat = None
    if unresolved_stat is not None and (
        stat.S_ISLNK(unresolved_stat.st_mode)
        or bool(
            int(getattr(unresolved_stat, "st_file_attributes", 0))
            & _WINDOWS_REPARSE_POINT
        )
    ):
        raise InvalidRequestError(
            "Storage Retention Cleanup 目标不能是符号链接或 reparse point"
        )
    target_path = raw_target.resolve(strict=False)
    storage = require_dataset_storage(request)
    repository_root = Path(__file__).resolve().parents[6]
    protected_paths = {
        Path(target_path.anchor).resolve(strict=False),
        Path.home().resolve(strict=False),
        repository_root.resolve(strict=False),
        storage.root_dir.resolve(strict=False),
        storage.root_dir.parent.resolve(strict=False),
    }
    normalized_target = os.path.normcase(os.path.normpath(str(target_path)))
    normalized_protected = {
        os.path.normcase(os.path.normpath(str(path))) for path in protected_paths
    }
    if normalized_target in normalized_protected:
        raise InvalidRequestError(
            "Storage Retention Cleanup 拒绝清理受保护的宽范围目录",
            details={"target_directory": str(target_path)},
        )
    if target_path.exists():
        target_stat = target_path.stat(follow_symlinks=False)
        if stat.S_ISLNK(target_stat.st_mode) or bool(
            int(getattr(target_stat, "st_file_attributes", 0)) & _WINDOWS_REPARSE_POINT
        ):
            raise InvalidRequestError(
                "Storage Retention Cleanup 目标不能是符号链接或 reparse point"
            )
    return target_path


def _validate_object_store_target(
    request: WorkflowNodeExecutionRequest,
    *,
    storage: RetentionObjectStore,
    target_directory: str,
) -> None:
    """限制相对目标只能位于当前 App 结果域且不能经链接逃逸。"""

    project_id = _require_execution_metadata_text(request, "project_id")
    application_id = _require_execution_metadata_text(request, "application_id")
    target_parts = PurePosixPath(target_directory).parts
    expected_prefix = (
        "projects",
        project_id,
        "results",
        "workflow-applications",
        application_id,
    )
    if target_parts[: len(expected_prefix)] != expected_prefix:
        raise InvalidRequestError(
            "Storage Retention Cleanup 的 ObjectStore 目标不属于当前 Workflow App 结果域",
            details={
                "target_directory": target_directory,
                "required_prefix": PurePosixPath(*expected_prefix).as_posix(),
            },
        )
    resolve = getattr(storage, "resolve", None)
    storage_root = getattr(storage, "root_dir", None)
    if not callable(resolve) or not isinstance(storage_root, Path):
        raise ServiceConfigurationError(
            "当前 ObjectStore 不支持本机清理路径校验",
            details={"node_id": request.node_id},
        )
    lexical_root = Path(os.path.abspath(storage_root))
    lexical_target = Path(os.path.abspath(resolve(target_directory)))
    try:
        relative_target = lexical_target.relative_to(lexical_root)
    except ValueError as error:
        raise InvalidRequestError(
            "Storage Retention Cleanup 的 ObjectStore 目标超出存储根目录"
        ) from error
    current_path = lexical_root
    for part in relative_target.parts:
        current_path /= part
        try:
            current_stat = current_path.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(current_stat.st_mode) or bool(
            int(getattr(current_stat, "st_file_attributes", 0))
            & _WINDOWS_REPARSE_POINT
        ):
            raise InvalidRequestError(
                "Storage Retention Cleanup 的 ObjectStore 目标不能经过符号链接或 reparse point"
            )
    resolved_root = lexical_root.resolve(strict=False)
    resolved_target = lexical_target.resolve(strict=False)
    if not resolved_target.is_relative_to(resolved_root):
        raise InvalidRequestError(
            "Storage Retention Cleanup 的 ObjectStore 目标超出存储根目录"
        )


def _require_retention_object_store(
    request: WorkflowNodeExecutionRequest,
) -> RetentionObjectStore:
    """读取并校验 ObjectStore 保留清理可选能力。"""

    storage = require_dataset_storage(request)
    if not isinstance(storage, RetentionObjectStore):
        raise ServiceConfigurationError(
            "当前 ObjectStore 不支持保留清理能力",
            details={"node_id": request.node_id},
        )
    return storage


def _build_filesystem_delete(
    request: WorkflowNodeExecutionRequest,
    *,
    target_path: Path,
) -> Callable[[RetentionObjectMetadata], RetentionDeleteState]:
    """构造带非等待跨进程锁的本机条件删除函数。"""

    def delete_item(item: RetentionObjectMetadata) -> RetentionDeleteState:
        item_path = target_path.joinpath(*PurePosixPath(item.object_key).parts)
        with try_acquire_path_write_locks(request, (item_path,)) as acquired:
            if not acquired:
                return "locked"
            return delete_local_retention_file_if_version(
                item_path,
                expected_version=item.version,
            )

    return delete_item


def _build_object_store_delete(
    request: WorkflowNodeExecutionRequest,
    *,
    storage: RetentionObjectStore,
) -> Callable[[RetentionObjectMetadata], RetentionDeleteState]:
    """构造 ObjectStore 版本条件删除函数。"""

    resolve = getattr(storage, "resolve", None)

    def delete_item(item: RetentionObjectMetadata) -> RetentionDeleteState:
        if callable(resolve):
            item_path = resolve(item.object_key)
            with try_acquire_path_write_locks(request, (item_path,)) as acquired:
                if not acquired:
                    return "locked"
                return storage.delete_retention_object_if_version(
                    item.object_key,
                    expected_version=item.version,
                )
        return storage.delete_retention_object_if_version(
            item.object_key,
            expected_version=item.version,
        )

    return delete_item


def _build_result_payload(
    *,
    options: StorageRetentionOptions,
    target_directory: str,
    location_kind: str,
    result: object,
) -> dict[str, object]:
    """把策略结果转换为公开版本化 payload。"""

    payload = _build_empty_result(
        options=options,
        target_directory=target_directory,
        location_kind=location_kind,
        state=str(getattr(result, "state")),
        duration_ms=int(getattr(result, "duration_ms")),
    )
    cutoff_time = getattr(result, "cutoff_time")
    if isinstance(cutoff_time, datetime):
        payload["cutoff_time"] = cutoff_time.isoformat()
    for field_name in (
        "scanned_file_count",
        "matched_file_count",
        "eligible_file_count",
        "deleted_file_count",
        "deleted_size_bytes",
        "skipped_changed_count",
        "skipped_locked_count",
        "skipped_missing_count",
        "failed_file_count",
        "has_more",
    ):
        payload[field_name] = getattr(result, field_name)
    return payload


def _build_empty_result(
    *,
    options: StorageRetentionOptions,
    target_directory: str,
    location_kind: str,
    state: str,
    duration_ms: int,
    current_time: datetime | None = None,
) -> dict[str, object]:
    """构造目标不存在和正常结果共用的稳定字段。"""

    payload: dict[str, object] = {
        "format_id": "amvision.storage-retention-cleanup-result.v1",
        "state": state,
        "target_directory": target_directory,
        "location_kind": location_kind,
        "retention_policy": options.retention_policy,
        "dry_run": options.dry_run,
        "scanned_file_count": 0,
        "matched_file_count": 0,
        "eligible_file_count": 0,
        "deleted_file_count": 0,
        "deleted_size_bytes": 0,
        "skipped_changed_count": 0,
        "skipped_locked_count": 0,
        "skipped_missing_count": 0,
        "failed_file_count": 0,
        "has_more": False,
        "duration_ms": duration_ms,
    }
    if options.retention_policy in {"age", "age-and-count"}:
        payload["retention_value"] = int(options.retention_value or 0)
        payload["retention_unit"] = str(options.retention_unit or "")
        if current_time is not None and options.retention_unit is not None:
            payload["cutoff_time"] = calculate_retention_cutoff(
                current_time,
                retention_value=int(options.retention_value or 0),
                retention_unit=options.retention_unit,
            ).isoformat()
    if options.retention_policy in {"count", "age-and-count"}:
        payload["max_file_count"] = int(options.max_file_count or 0)
    return payload


def _read_include_patterns(raw_value: object) -> tuple[str, ...]:
    """读取只允许匹配文件名的非空 pattern 列表。"""

    if raw_value is None:
        return ("*",)
    if not isinstance(raw_value, (list, tuple)):
        raise InvalidRequestError("include_patterns 必须是字符串数组")
    patterns: list[str] = []
    for item in raw_value:
        pattern = item.strip() if isinstance(item, str) else ""
        if not pattern or "/" in pattern or "\\" in pattern:
            raise InvalidRequestError("include_patterns 只能包含非空文件名匹配模式")
        if pattern not in patterns:
            patterns.append(pattern)
    if not patterns:
        raise InvalidRequestError("include_patterns 不能为空")
    return tuple(patterns)


def _read_bool(
    request: WorkflowNodeExecutionRequest,
    field_name: str,
    *,
    default: bool,
) -> bool:
    """严格读取布尔参数。"""

    value = request.parameters.get(field_name, default)
    if not isinstance(value, bool):
        raise InvalidRequestError(f"{field_name} 必须是 boolean")
    return value


def _read_positive_int(
    request: WorkflowNodeExecutionRequest,
    field_name: str,
    *,
    default: int,
) -> int:
    """读取带默认值的正整数参数。"""

    value = request.parameters.get(field_name, default)
    return _require_positive_int(value, field_name=field_name)


def _read_optional_positive_int(
    request: WorkflowNodeExecutionRequest,
    field_name: str,
) -> int | None:
    """读取可选正整数参数。"""

    value = request.parameters.get(field_name)
    if value is None:
        return None
    return _require_positive_int(value, field_name=field_name)


def _require_positive_int(value: object, *, field_name: str) -> int:
    """校验一个值是非 boolean 的正整数。"""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRequestError(f"{field_name} 必须是大于 0 的整数")
    return value


def _read_choice(
    value: object,
    *,
    field_name: str,
    supported_values: set[str],
) -> str:
    """读取必填枚举文本。"""

    normalized_value = value.strip().lower() if isinstance(value, str) else ""
    if normalized_value not in supported_values:
        raise InvalidRequestError(
            f"{field_name} 仅支持 {', '.join(sorted(supported_values))}"
        )
    return normalized_value


def _read_optional_choice(
    value: object,
    *,
    field_name: str,
    supported_values: set[str],
) -> str | None:
    """读取可选枚举文本。"""

    if value is None:
        return None
    return _read_choice(
        value,
        field_name=field_name,
        supported_values=supported_values,
    )


def _require_execution_metadata_text(
    request: WorkflowNodeExecutionRequest,
    field_name: str,
) -> str:
    """读取当前 Workflow App 作用域标识。"""

    value = request.execution_metadata.get(field_name)
    normalized_value = value.strip() if isinstance(value, str) else ""
    if not normalized_value:
        raise ServiceConfigurationError(
            f"Storage Retention Cleanup 缺少 {field_name} 执行上下文",
            details={"node_id": request.node_id},
        )
    return normalized_value


def _elapsed_milliseconds(started_at: float) -> int:
    """计算目标不存在等快速路径耗时。"""

    return max(0, int(round((monotonic() - started_at) * 1_000)))


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.storage-retention-cleanup",
        display_name="Storage Retention Cleanup",
        category="core.io.file",
        description="按时间、最大文件数量或两者组合清理生产结果目录。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="target_directory",
                display_name="Target Directory",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "target_directory": {
                    "type": "string",
                    "title": "目标目录",
                    "x-amvision-ui": {"order": 10},
                },
                "retention_policy": {
                    "type": "string",
                    "title": "保留策略",
                    "enum": ["age", "count", "age-and-count"],
                    "default": "age",
                    "x-amvision-ui": {"order": 20},
                },
                "retention_value": {
                    "type": "integer",
                    "title": "保留时间数量",
                    "minimum": 1,
                    "x-amvision-ui": {"order": 30},
                },
                "retention_unit": {
                    "type": "string",
                    "title": "保留时间单位",
                    "enum": ["day", "month", "year"],
                    "x-amvision-ui": {"order": 40},
                },
                "max_file_count": {
                    "type": "integer",
                    "title": "最大文件数量",
                    "minimum": 1,
                    "x-amvision-ui": {"order": 50},
                },
                "recursive": {
                    "type": "boolean",
                    "title": "递归处理子目录",
                    "default": True,
                    "x-amvision-ui": {"order": 60},
                },
                "include_patterns": {
                    "type": "array",
                    "title": "文件名匹配",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "default": ["*"],
                    "x-amvision-ui": {"order": 70},
                },
                "delete_empty_directories": {
                    "type": "boolean",
                    "title": "删除空子目录",
                    "default": False,
                    "x-amvision-ui": {"order": 80},
                },
                "delete_limit": {
                    "type": "integer",
                    "title": "单次删除上限",
                    "minimum": 1,
                    "default": 1000,
                    "x-amvision-ui": {"order": 90},
                },
                "dry_run": {
                    "type": "boolean",
                    "title": "仅检查不删除",
                    "default": True,
                    "x-amvision-ui": {"order": 100},
                },
            },
            "required": [
                "target_directory",
                "retention_policy",
                "recursive",
                "include_patterns",
                "delete_empty_directories",
                "delete_limit",
                "dry_run",
            ],
            "allOf": [
                {
                    "if": {
                        "properties": {
                            "retention_policy": {"enum": ["age", "age-and-count"]}
                        }
                    },
                    "then": {"required": ["retention_value", "retention_unit"]},
                },
                {
                    "if": {
                        "properties": {
                            "retention_policy": {"enum": ["count", "age-and-count"]}
                        }
                    },
                    "then": {"required": ["max_file_count"]},
                },
            ],
        },
        parameter_input_bindings=(
            NodeParameterInputBinding(
                parameter_name="target_directory",
                input_port_name="target_directory",
            ),
        ),
        capability_tags=("io.output", "filesystem.cleanup", "retention.cleanup"),
    ),
    handler=_storage_retention_cleanup_handler,
)
