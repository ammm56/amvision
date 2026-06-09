"""目录 TriggerSource 共享 helper。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from pathlib import PurePosixPath
from typing import Literal

from backend.contracts.workflows import build_workflow_trigger_source_storage_dir
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)


DirectorySortBy = Literal["name", "modified_time"]
DirectoryDedupeBy = Literal["path", "file_name", "file_name_and_size"]


@dataclass(frozen=True)
class DirectoryPollTriggerConfig:
    """描述 directory-poll TriggerSource 的最终运行配置。"""

    directory_path: Path
    recursive: bool
    include_hidden: bool
    glob_pattern: str
    extensions: tuple[str, ...]
    sort_by: DirectorySortBy
    descending: bool
    dedupe_by: DirectoryDedupeBy
    batch_size: int
    scan_interval_seconds: float
    min_stable_age_seconds: float
    checkpoint_path: Path
    persist_checkpoint: bool


@dataclass(frozen=True)
class DirectoryWatchTriggerConfig:
    """描述 directory-watch TriggerSource 的最终运行配置。"""

    scan_config: DirectoryPollTriggerConfig
    watch_debounce_ms: int
    watch_step_ms: int
    watch_timeout_ms: int
    force_polling: bool | None
    poll_delay_ms: int
    ignore_permission_denied: bool


def parse_directory_poll_trigger_config(
    *,
    trigger_source: WorkflowTriggerSource,
    dataset_storage_root_dir: Path,
) -> DirectoryPollTriggerConfig:
    """把 TriggerSource 配置解析为目录轮询运行配置。"""

    transport_config = dict(trigger_source.transport_config)
    directory_path = _read_required_directory_path(
        transport_config.get("directory_path"),
        "transport_config.directory_path",
    )
    checkpoint_path = _build_default_checkpoint_path(
        dataset_storage_root_dir=dataset_storage_root_dir,
        trigger_source_id=trigger_source.trigger_source_id,
        checkpoint_file_name="directory-poll-checkpoint.json",
    )
    return DirectoryPollTriggerConfig(
        directory_path=directory_path,
        recursive=_read_bool(
            transport_config.get("recursive"),
            "transport_config.recursive",
            default_value=False,
        ),
        include_hidden=_read_bool(
            transport_config.get("include_hidden"),
            "transport_config.include_hidden",
            default_value=False,
        ),
        glob_pattern=_read_text(
            transport_config.get("glob_pattern"),
            "transport_config.glob_pattern",
            default_value="*",
        ),
        extensions=_read_extensions(transport_config.get("extensions")),
        sort_by=_read_sort_by(transport_config.get("sort_by")),
        descending=_read_bool(
            transport_config.get("descending"),
            "transport_config.descending",
            default_value=False,
        ),
        dedupe_by=_read_dedupe_by(transport_config.get("dedupe_by")),
        batch_size=_read_positive_int(
            transport_config.get("batch_size"),
            "transport_config.batch_size",
            default_value=1,
        ),
        scan_interval_seconds=_read_positive_float(
            transport_config.get("scan_interval_seconds"),
            "transport_config.scan_interval_seconds",
            default_value=1.0,
        ),
        min_stable_age_seconds=_read_non_negative_float(
            transport_config.get("min_stable_age_seconds"),
            "transport_config.min_stable_age_seconds",
            default_value=1.0,
        ),
        checkpoint_path=checkpoint_path,
        persist_checkpoint=_read_bool(
            transport_config.get("persist_checkpoint"),
            "transport_config.persist_checkpoint",
            default_value=True,
        ),
    )


def parse_directory_watch_trigger_config(
    *,
    trigger_source: WorkflowTriggerSource,
    dataset_storage_root_dir: Path,
) -> DirectoryWatchTriggerConfig:
    """把 TriggerSource 配置解析为目录监听运行配置。"""

    transport_config = dict(trigger_source.transport_config)
    base_scan_config = parse_directory_poll_trigger_config(
        trigger_source=trigger_source,
        dataset_storage_root_dir=dataset_storage_root_dir,
    )
    scan_config = DirectoryPollTriggerConfig(
        directory_path=base_scan_config.directory_path,
        recursive=base_scan_config.recursive,
        include_hidden=base_scan_config.include_hidden,
        glob_pattern=base_scan_config.glob_pattern,
        extensions=base_scan_config.extensions,
        sort_by=base_scan_config.sort_by,
        descending=base_scan_config.descending,
        dedupe_by=base_scan_config.dedupe_by,
        batch_size=base_scan_config.batch_size,
        scan_interval_seconds=base_scan_config.scan_interval_seconds,
        min_stable_age_seconds=base_scan_config.min_stable_age_seconds,
        checkpoint_path=build_directory_watch_checkpoint_path(
            dataset_storage_root_dir=dataset_storage_root_dir,
            trigger_source_id=trigger_source.trigger_source_id,
        ),
        persist_checkpoint=base_scan_config.persist_checkpoint,
    )
    return DirectoryWatchTriggerConfig(
        scan_config=scan_config,
        watch_debounce_ms=_read_positive_int(
            transport_config.get("watch_debounce_ms"),
            "transport_config.watch_debounce_ms",
            default_value=200,
        ),
        watch_step_ms=_read_positive_int(
            transport_config.get("watch_step_ms"),
            "transport_config.watch_step_ms",
            default_value=50,
        ),
        watch_timeout_ms=_read_positive_int(
            transport_config.get("watch_timeout_ms"),
            "transport_config.watch_timeout_ms",
            default_value=500,
        ),
        force_polling=_read_optional_bool(
            transport_config.get("force_polling"),
            "transport_config.force_polling",
        ),
        poll_delay_ms=_read_positive_int(
            transport_config.get("poll_delay_ms"),
            "transport_config.poll_delay_ms",
            default_value=300,
        ),
        ignore_permission_denied=_read_bool(
            transport_config.get("ignore_permission_denied"),
            "transport_config.ignore_permission_denied",
            default_value=True,
        ),
    )


def scan_directory_records(
    config: DirectoryPollTriggerConfig,
    *,
    current_time_seconds: float,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """执行一次目录扫描并返回规范化文件记录与摘要。"""

    raw_records = [
        build_directory_file_record(file_path)
        for file_path in _list_directory_files(config)
    ]
    records, unstable_skipped_count = _filter_unstable_records(
        raw_records,
        min_stable_age_seconds=config.min_stable_age_seconds,
        current_time_seconds=current_time_seconds,
    )
    records = _sort_records(
        records,
        sort_by=config.sort_by,
        descending=config.descending,
    )
    records, deduped_count = _dedupe_records(records, dedupe_by=config.dedupe_by)
    return records, {
        "directory_path": str(config.directory_path),
        "raw_count": len(raw_records),
        "visible_count": len(records),
        "recursive": config.recursive,
        "include_hidden": config.include_hidden,
        "glob_pattern": config.glob_pattern,
        "extensions": list(config.extensions),
        "sort_by": config.sort_by,
        "descending": config.descending,
        "dedupe_by": config.dedupe_by,
        "batch_size": config.batch_size,
        "scan_interval_seconds": config.scan_interval_seconds,
        "min_stable_age_seconds": config.min_stable_age_seconds,
        "unstable_skipped_count": unstable_skipped_count,
        "deduped_count": deduped_count,
    }


def build_directory_file_record(file_path: Path) -> dict[str, object]:
    """把目录中文件规范化为稳定 file record。"""

    stat_result = file_path.stat()
    return {
        "path": str(file_path.resolve()),
        "file_name": file_path.name,
        "extension": file_path.suffix.lower(),
        "size_bytes": stat_result.st_size,
        "modified_time_epoch_ms": int(round(stat_result.st_mtime * 1000)),
        "modified_time_iso": _build_iso_timestamp(stat_result.st_mtime),
    }


def build_record_identity_key(
    record: dict[str, object],
    *,
    dedupe_by: DirectoryDedupeBy,
) -> str:
    """按指定去重策略构造文件身份键。"""

    record_path = str(record.get("path") or "").strip().lower()
    file_name = str(record.get("file_name") or "").strip().lower()
    size_bytes = record.get("size_bytes")
    if dedupe_by == "path":
        return record_path
    if dedupe_by == "file_name":
        return file_name
    return f"{file_name}::{size_bytes}"


def build_checkpoint_path(
    dataset_storage_root_dir: Path,
    trigger_source_id: str,
) -> Path:
    """构造 TriggerSource 默认 checkpoint 文件路径。"""

    return _build_default_checkpoint_path(
        dataset_storage_root_dir=dataset_storage_root_dir,
        trigger_source_id=trigger_source_id,
        checkpoint_file_name="directory-poll-checkpoint.json",
    )


def build_directory_watch_checkpoint_path(
    dataset_storage_root_dir: Path,
    trigger_source_id: str,
) -> Path:
    """构造 directory-watch 默认 checkpoint 文件路径。"""

    return _build_default_checkpoint_path(
        dataset_storage_root_dir=dataset_storage_root_dir,
        trigger_source_id=trigger_source_id,
        checkpoint_file_name="directory-watch-checkpoint.json",
    )


def matches_directory_candidate_path(
    file_path: Path,
    *,
    directory_path: Path,
    recursive: bool,
    include_hidden: bool,
    glob_pattern: str,
    extensions: tuple[str, ...],
) -> bool:
    """判断一个路径是否满足目录触发配置的静态筛选条件。"""

    try:
        normalized_path = file_path.resolve()
        relative_path = normalized_path.relative_to(directory_path)
    except ValueError:
        return False
    if not recursive and len(relative_path.parts) > 1:
        return False
    if not include_hidden and any(part.startswith(".") for part in relative_path.parts):
        return False
    if extensions and normalized_path.suffix.lower() not in extensions:
        return False
    return PurePosixPath(relative_path.as_posix()).match(glob_pattern)


def _build_default_checkpoint_path(
    *,
    dataset_storage_root_dir: Path,
    trigger_source_id: str,
    checkpoint_file_name: str,
) -> Path:
    """构造目录 TriggerSource 默认 checkpoint 路径。"""

    return (
        dataset_storage_root_dir
        / build_workflow_trigger_source_storage_dir(trigger_source_id)
        / "state"
        / checkpoint_file_name
    ).resolve()


def _list_directory_files(config: DirectoryPollTriggerConfig) -> list[Path]:
    """列出目录中符合条件的候选文件。"""

    path_iterable = (
        config.directory_path.rglob(config.glob_pattern)
        if config.recursive
        else config.directory_path.glob(config.glob_pattern)
    )
    file_paths: list[Path] = []
    for file_path in path_iterable:
        if not file_path.is_file():
            continue
        if not matches_directory_candidate_path(
            file_path,
            directory_path=config.directory_path,
            recursive=config.recursive,
            include_hidden=config.include_hidden,
            glob_pattern=config.glob_pattern,
            extensions=config.extensions,
        ):
            continue
        file_paths.append(file_path.resolve())
    return file_paths


def _filter_unstable_records(
    records: list[dict[str, object]],
    *,
    min_stable_age_seconds: float,
    current_time_seconds: float,
) -> tuple[list[dict[str, object]], int]:
    """过滤仍处于写入变化期的文件。"""

    if min_stable_age_seconds <= 0:
        return list(records), 0
    stable_before_epoch_ms = int(
        round((current_time_seconds - min_stable_age_seconds) * 1000)
    )
    kept_records: list[dict[str, object]] = []
    skipped_count = 0
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


def _sort_records(
    records: list[dict[str, object]],
    *,
    sort_by: DirectorySortBy,
    descending: bool,
) -> list[dict[str, object]]:
    """按稳定顺序排序目录记录。"""

    if sort_by == "modified_time":
        return sorted(
            records,
            key=lambda item: (
                int(item.get("modified_time_epoch_ms", 0)),
                str(item.get("path") or "").lower(),
            ),
            reverse=descending,
        )
    return sorted(
        records,
        key=lambda item: str(item.get("path") or "").lower(),
        reverse=descending,
    )


def _dedupe_records(
    records: list[dict[str, object]],
    *,
    dedupe_by: DirectoryDedupeBy,
) -> tuple[list[dict[str, object]], int]:
    """按文件身份键对扫描结果去重。"""

    seen_keys: set[str] = set()
    deduped_records: list[dict[str, object]] = []
    deduped_count = 0
    for record in records:
        identity_key = build_record_identity_key(record, dedupe_by=dedupe_by)
        if identity_key in seen_keys:
            deduped_count += 1
            continue
        seen_keys.add(identity_key)
        deduped_records.append(record)
    return deduped_records, deduped_count


def _read_required_directory_path(raw_value: object, field_name: str) -> Path:
    """读取必填本地目录路径。"""

    normalized_text = _read_text(raw_value, field_name, default_value=None)
    if normalized_text is None:
        raise InvalidRequestError(f"{field_name} 必须是非空字符串")
    directory_path = Path(normalized_text).expanduser().resolve()
    if not directory_path.is_dir():
        raise InvalidRequestError(
            f"{field_name} 指向的目录不存在",
            details={"field_name": field_name, "directory_path": str(directory_path)},
        )
    return directory_path


def _read_extensions(raw_value: object) -> tuple[str, ...]:
    """读取扩展名过滤列表。"""

    if raw_value is None:
        return ()
    if not isinstance(raw_value, list):
        raise InvalidRequestError("transport_config.extensions 必须是字符串数组")
    normalized_extensions: list[str] = []
    for item_index, item_value in enumerate(raw_value, start=1):
        if not isinstance(item_value, str) or not item_value.strip():
            raise InvalidRequestError(
                "transport_config.extensions 必须全部是非空字符串",
                details={"item_index": item_index},
            )
        normalized_extension = item_value.strip().lower()
        if not normalized_extension.startswith("."):
            normalized_extension = f".{normalized_extension}"
        normalized_extensions.append(normalized_extension)
    return tuple(normalized_extensions)


def _read_sort_by(raw_value: object) -> DirectorySortBy:
    """读取目录排序字段。"""

    if raw_value is None:
        return "modified_time"
    normalized_value = _read_text(
        raw_value,
        "transport_config.sort_by",
        default_value=None,
    )
    if normalized_value not in {"name", "modified_time"}:
        raise InvalidRequestError(
            "transport_config.sort_by 仅支持 name 或 modified_time"
        )
    return normalized_value


def _read_dedupe_by(raw_value: object) -> DirectoryDedupeBy:
    """读取目录去重策略。"""

    if raw_value is None:
        return "path"
    normalized_value = _read_text(
        raw_value,
        "transport_config.dedupe_by",
        default_value=None,
    )
    if normalized_value not in {"path", "file_name", "file_name_and_size"}:
        raise InvalidRequestError(
            "transport_config.dedupe_by 仅支持 path、file_name 或 file_name_and_size"
        )
    return normalized_value


def _read_bool(raw_value: object, field_name: str, *, default_value: bool) -> bool:
    """读取布尔配置。"""

    if raw_value is None:
        return default_value
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{field_name} 必须是布尔值")
    return raw_value


def _read_optional_bool(raw_value: object, field_name: str) -> bool | None:
    """读取可选布尔配置。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{field_name} 必须是布尔值")
    return raw_value


def _read_text(
    raw_value: object,
    field_name: str,
    *,
    default_value: str | None,
) -> str | None:
    """读取可选文本配置。"""

    if raw_value is None:
        return default_value
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{field_name} 必须是非空字符串")
    return raw_value.strip()


def _read_positive_int(
    raw_value: object,
    field_name: str,
    *,
    default_value: int,
) -> int:
    """读取正整数配置。"""

    if raw_value is None:
        return default_value
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{field_name} 必须是整数")
    if raw_value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return raw_value


def _read_positive_float(
    raw_value: object,
    field_name: str,
    *,
    default_value: float,
) -> float:
    """读取正浮点配置。"""

    if raw_value is None:
        return default_value
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是数值")
    normalized_value = float(raw_value)
    if normalized_value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return normalized_value


def _read_non_negative_float(
    raw_value: object,
    field_name: str,
    *,
    default_value: float,
) -> float:
    """读取非负浮点配置。"""

    if raw_value is None:
        return default_value
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是数值")
    normalized_value = float(raw_value)
    if normalized_value < 0:
        raise InvalidRequestError(f"{field_name} 不能小于 0")
    return normalized_value


def _build_iso_timestamp(timestamp_seconds: float) -> str:
    """把时间戳转换为 UTC ISO 文本。"""

    return datetime.fromtimestamp(timestamp_seconds, tz=UTC).isoformat()
