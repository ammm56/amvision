"""Workflow 节点保存位置解析和原子文件写入。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
from typing import Literal
from uuid import uuid4

from backend.nodes.date_time_template import render_date_time_template
from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.object_store.object_key_layout import (
    build_project_workflow_application_results_dir,
)
from backend.service.infrastructure.filesystem.atomic_files import (
    publish_path_without_overwrite,
    replace_path_with_retry,
)
from backend.service.infrastructure.filesystem.windows_paths import to_filesystem_path


SAVE_LOCATION_OBJECT_STORE = "object-store"
SAVE_LOCATION_FILESYSTEM = "filesystem"
SaveLocationKind = Literal["object-store", "filesystem"]
SaveLocationScope = Literal["file", "directory"]
_MAX_INCREMENTED_FILE_SEQUENCE = 999_999


@dataclass(frozen=True)
class WorkflowSaveLocation:
    """描述节点参数解析后的保存位置。"""

    kind: SaveLocationKind
    scope: SaveLocationScope
    object_key: str | None = None
    filesystem_path: Path | None = None


@dataclass(frozen=True)
class WorkflowSavedFile:
    """描述节点写入完成后的文件引用。"""

    kind: SaveLocationKind
    object_key: str | None = None
    local_path: Path | None = None

    def to_payload(self) -> dict[str, object]:
        """构造可放入节点输出的稳定引用。"""

        if self.kind == SAVE_LOCATION_OBJECT_STORE:
            return {
                "kind": SAVE_LOCATION_OBJECT_STORE,
                "object_key": self.object_key or "",
            }
        return {
            "kind": SAVE_LOCATION_FILESYSTEM,
            "local_path": str(self.local_path or ""),
        }


def build_save_template_context(
    request: object,
    *,
    current_time: datetime | None = None,
) -> dict[str, str]:
    """构建所有 Save 节点共用的日期时间和 Workflow 上下文。"""

    execution_metadata = getattr(request, "execution_metadata", {})
    if not isinstance(execution_metadata, dict):
        execution_metadata = {}
    resolved_time = current_time or datetime.now().astimezone()
    workflow_run_id = str(execution_metadata.get("workflow_run_id") or "default-run")
    context = {
        "workflow_run_id": workflow_run_id,
        "timestamp": resolved_time.strftime("%Y%m%dT%H%M%S%f%z"),
        "node_id": str(getattr(request, "node_id", "") or "unknown-node"),
    }
    project_id = _read_optional_execution_metadata_text(
        execution_metadata,
        key="project_id",
    )
    application_id = _read_optional_execution_metadata_text(
        execution_metadata,
        key="application_id",
    )
    if project_id is not None:
        context["project_id"] = project_id
    if application_id is not None:
        context["application_id"] = application_id
    if project_id is not None and application_id is not None:
        context["workflow_app_result_dir"] = (
            build_project_workflow_application_results_dir(
                project_id=project_id,
                application_id=application_id,
                workflow_run_id=workflow_run_id,
            )
        )
    return context


def render_save_directory_template(
    request: object,
    value: object,
    *,
    node_label: str,
    current_time: datetime | None = None,
    context: dict[str, str] | None = None,
) -> str:
    """展开并校验 Save 节点的目录模板。"""

    template = value.strip() if isinstance(value, str) else ""
    if not template:
        raise InvalidRequestError(
            f"{node_label} 保存目录不能为空",
            details={
                "node_id": getattr(request, "node_id", None),
                "parameter_name": "save_directory",
            },
        )
    try:
        return render_date_time_template(
            template,
            current_time=current_time,
            context=context or build_save_template_context(request),
        )
    except InvalidRequestError as exc:
        exc.details.setdefault("node_id", getattr(request, "node_id", None))
        exc.details.setdefault("parameter_name", "save_directory")
        raise


def resolve_required_save_directory(
    request: object,
    value: object,
    *,
    node_label: str,
    current_time: datetime | None = None,
    context: dict[str, str] | None = None,
) -> tuple[str, WorkflowSaveLocation]:
    """展开目录模板并解析成 ObjectStore 或本机目录。"""

    rendered_directory = render_save_directory_template(
        request,
        value,
        node_label=node_label,
        current_time=current_time,
        context=context,
    )
    save_location = resolve_optional_save_location(
        rendered_directory,
        scope="directory",
    )
    if save_location is None:
        raise InvalidRequestError(
            f"{node_label} 保存目录不能为空",
            details={
                "node_id": getattr(request, "node_id", None),
                "parameter_name": "save_directory",
            },
        )
    return rendered_directory, save_location


def _read_optional_execution_metadata_text(
    execution_metadata: dict[str, object],
    *,
    key: str,
) -> str | None:
    """读取 execution_metadata 中的可选非空文本。"""

    raw_value = execution_metadata.get(key)
    if not isinstance(raw_value, str):
        return None
    normalized_value = raw_value.strip()
    return normalized_value or None


def resolve_save_location_path(
    request: object,
    *,
    save_location: WorkflowSaveLocation,
    file_name: str | None = None,
) -> tuple[Path, WorkflowSavedFile]:
    """把保存位置解析为当前 runtime 可写路径和稳定引用。"""

    target_name = _normalize_target_name(
        save_location=save_location, file_name=file_name
    )
    if save_location.kind == SAVE_LOCATION_OBJECT_STORE:
        from backend.nodes.runtime_support import require_dataset_storage

        base_key = str(save_location.object_key or "")
        object_key = (
            f"{base_key}/{target_name}" if target_name is not None else base_key
        )
        return (
            require_dataset_storage(request).resolve(object_key),
            WorkflowSavedFile(kind=SAVE_LOCATION_OBJECT_STORE, object_key=object_key),
        )

    base_path = save_location.filesystem_path
    if base_path is None:
        raise InvalidRequestError("系统保存位置缺少有效路径")
    target_path = base_path / target_name if target_name is not None else base_path
    return target_path, WorkflowSavedFile(
        kind=SAVE_LOCATION_FILESYSTEM, local_path=target_path
    )


def resolve_optional_save_location(
    value: object,
    *,
    scope: SaveLocationScope,
) -> WorkflowSaveLocation | None:
    """解析保存位置；相对路径走 ObjectStore，绝对路径走本机文件系统。"""

    if not isinstance(value, str) or not value.strip():
        return None
    raw_value = os.path.expanduser(value.strip())
    native_path = Path(raw_value)
    if native_path.is_absolute():
        try:
            resolved_path = native_path.resolve(strict=False)
        except OSError as error:
            raise InvalidRequestError(
                "系统保存位置无法解析",
                details={"save_location": value},
            ) from error
        return WorkflowSaveLocation(
            kind=SAVE_LOCATION_FILESYSTEM,
            scope=scope,
            filesystem_path=resolved_path,
        )

    windows_path = PureWindowsPath(raw_value)
    posix_path = PurePosixPath(raw_value.replace("\\", "/"))
    if windows_path.drive or windows_path.root or posix_path.is_absolute():
        raise InvalidRequestError(
            "save_location 必须是当前系统可解析的绝对路径或 ObjectStore 相对路径",
            details={"save_location": value},
        )
    if ".." in posix_path.parts:
        raise InvalidRequestError(
            "ObjectStore 保存位置不能包含父目录引用",
            details={"save_location": value},
        )
    cleaned_parts = tuple(part for part in posix_path.parts if part not in {"", "."})
    if not cleaned_parts:
        return None
    return WorkflowSaveLocation(
        kind=SAVE_LOCATION_OBJECT_STORE,
        scope=scope,
        object_key=PurePosixPath(*cleaned_parts).as_posix(),
    )


def resolve_required_save_location_from_request(
    request: object,
    *,
    scope: SaveLocationScope,
    parameter_name: str = "save_location",
    input_name: str = "save_location",
) -> WorkflowSaveLocation:
    """从可选 value 输入或节点参数读取必填保存位置。"""

    input_values = getattr(request, "input_values", {})
    parameters = getattr(request, "parameters", {})
    raw_value: object = None
    raw_payload = (
        input_values.get(input_name) if isinstance(input_values, dict) else None
    )
    if raw_payload is not None:
        from backend.nodes.core_nodes.support.logic import require_value_payload

        raw_value = require_value_payload(raw_payload, field_name=input_name)["value"]
    if raw_value is None and isinstance(parameters, dict):
        raw_value = parameters.get(parameter_name)
    save_location = resolve_optional_save_location(raw_value, scope=scope)
    if save_location is None:
        raise InvalidRequestError(
            "保存位置必须是非空字符串",
            details={
                "node_id": getattr(request, "node_id", None),
                "parameter_name": parameter_name,
            },
        )
    return save_location


def save_bytes(
    request: object,
    *,
    save_location: WorkflowSaveLocation,
    content: bytes,
    file_name: str | None = None,
    overwrite: bool = True,
    increment_on_conflict: bool = False,
) -> WorkflowSavedFile:
    """按保存位置类型原子写入文件，并返回对应引用。

    ``increment_on_conflict`` 只在 ``overwrite=False`` 时生效。它使用原子
    不覆盖创建保证多个 workflow/runtime 同时写入时不会选中同一个文件名。
    """

    if overwrite and increment_on_conflict:
        raise InvalidRequestError("覆盖保存和冲突自动编号不能同时启用")

    target_name = _normalize_target_name(
        save_location=save_location, file_name=file_name
    )

    if save_location.kind == SAVE_LOCATION_OBJECT_STORE:
        from backend.nodes.runtime_support import require_dataset_storage

        base_key = str(save_location.object_key or "")
        object_key = (
            f"{base_key}/{target_name}" if target_name is not None else base_key
        )
        storage = require_dataset_storage(request)
        if not overwrite and increment_on_conflict:
            object_key = _write_object_store_bytes_with_incremented_name(
                storage=storage,
                object_key=object_key,
                content=content,
            )
            return WorkflowSavedFile(
                kind=SAVE_LOCATION_OBJECT_STORE,
                object_key=object_key,
            )
        if not overwrite and storage.resolve(object_key).exists():
            raise InvalidRequestError(
                "保存目标已存在，且当前节点未允许覆盖",
                details={"object_key": object_key},
            )
        storage.write_bytes(object_key, content)
        return WorkflowSavedFile(kind=SAVE_LOCATION_OBJECT_STORE, object_key=object_key)

    base_path = save_location.filesystem_path
    if base_path is None:
        raise InvalidRequestError("系统保存位置缺少有效路径")
    target_path = base_path / target_name if target_name is not None else base_path
    if not overwrite and increment_on_conflict:
        target_path = _write_filesystem_bytes_with_incremented_name(
            target_path,
            content,
        )
        return WorkflowSavedFile(
            kind=SAVE_LOCATION_FILESYSTEM,
            local_path=target_path,
        )
    if not overwrite and target_path.exists():
        raise InvalidRequestError(
            "保存目标已存在，且当前节点未允许覆盖",
            details={"local_path": str(target_path)},
        )
    _write_filesystem_bytes_atomically(target_path, content)
    return WorkflowSavedFile(kind=SAVE_LOCATION_FILESYSTEM, local_path=target_path)


def save_file(
    request: object,
    *,
    save_location: WorkflowSaveLocation,
    source_path: Path,
    file_name: str | None = None,
    overwrite: bool = True,
    increment_on_conflict: bool = False,
) -> WorkflowSavedFile:
    """把现有文件流式复制到保存位置，并支持原子冲突自动编号。"""

    if overwrite and increment_on_conflict:
        raise InvalidRequestError("覆盖保存和冲突自动编号不能同时启用")

    target_name = _normalize_target_name(
        save_location=save_location, file_name=file_name
    )

    if save_location.kind == SAVE_LOCATION_OBJECT_STORE:
        from backend.nodes.runtime_support import require_dataset_storage

        base_key = str(save_location.object_key or "")
        object_key = (
            f"{base_key}/{target_name}" if target_name is not None else base_key
        )
        storage = require_dataset_storage(request)
        if not overwrite and increment_on_conflict:
            object_key = _copy_object_store_file_with_incremented_name(
                storage=storage,
                object_key=object_key,
                source_path=source_path,
            )
            return WorkflowSavedFile(
                kind=SAVE_LOCATION_OBJECT_STORE,
                object_key=object_key,
            )
        if not overwrite and storage.resolve(object_key).exists():
            raise InvalidRequestError(
                "保存目标已存在，且当前节点未允许覆盖",
                details={"object_key": object_key},
            )
        storage.copy_file(source_path, object_key)
        return WorkflowSavedFile(kind=SAVE_LOCATION_OBJECT_STORE, object_key=object_key)

    base_path = save_location.filesystem_path
    if base_path is None:
        raise InvalidRequestError("系统保存位置缺少有效路径")
    target_path = base_path / target_name if target_name is not None else base_path
    if not overwrite and increment_on_conflict:
        target_path = _copy_filesystem_file_with_incremented_name(
            source_path=source_path,
            target_path=target_path,
        )
        return WorkflowSavedFile(
            kind=SAVE_LOCATION_FILESYSTEM,
            local_path=target_path,
        )
    if not overwrite and target_path.exists():
        raise InvalidRequestError(
            "保存目标已存在，且当前节点未允许覆盖",
            details={"local_path": str(target_path)},
        )
    _copy_filesystem_file_atomically(source_path, target_path)
    return WorkflowSavedFile(kind=SAVE_LOCATION_FILESYSTEM, local_path=target_path)


def _normalize_file_name(file_name: str) -> str:
    """校验批量保存使用的文件名，禁止再次携带目录层级。"""

    normalized_name = file_name.strip() if isinstance(file_name, str) else ""
    if (
        not normalized_name
        or normalized_name in {".", ".."}
        or PurePosixPath(normalized_name).name != normalized_name
        or PureWindowsPath(normalized_name).name != normalized_name
    ):
        raise InvalidRequestError("保存文件名不合法", details={"file_name": file_name})
    return normalized_name


def _normalize_target_name(
    *,
    save_location: WorkflowSaveLocation,
    file_name: str | None,
) -> str | None:
    """校验文件型和目录型保存位置的目标文件名。"""

    target_name = _normalize_file_name(file_name) if file_name is not None else None
    if save_location.scope == "directory" and target_name is None:
        raise InvalidRequestError("目录保存位置必须提供文件名")
    if save_location.scope == "file" and target_name is not None:
        raise InvalidRequestError("文件保存位置不能再提供文件名")
    return target_name


def _write_filesystem_bytes_atomically(target_path: Path, content: bytes) -> None:
    """把 bytes 原子写入本机绝对路径。"""

    filesystem_target_path = to_filesystem_path(target_path)
    filesystem_target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = filesystem_target_path.with_name(
        f".{target_path.name}.{uuid4().hex[:12]}.tmp"
    )
    try:
        with temporary_path.open("wb") as output_stream:
            output_stream.write(content)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        replace_path_with_retry(temporary_path, filesystem_target_path)
        _sync_directory_after_replace(filesystem_target_path.parent)
    except OSError as error:
        temporary_path.unlink(missing_ok=True)
        raise InvalidRequestError(
            "无法写入系统保存位置",
            details={"local_path": str(target_path)},
        ) from error


def _write_object_store_bytes_with_incremented_name(
    *,
    storage: object,
    object_key: str,
    content: bytes,
) -> str:
    """在本地 ObjectStore 中原子选择可用文件名并写入 bytes。"""

    resolve = getattr(storage, "resolve", None)
    write_if_absent = getattr(storage, "write_bytes_if_absent", None)
    if not callable(resolve) or not callable(write_if_absent):
        raise InvalidRequestError("当前 ObjectStore 不支持原子冲突自动编号")
    object_path = PurePosixPath(object_key)
    for sequence in range(_MAX_INCREMENTED_FILE_SEQUENCE + 1):
        candidate_name = _build_incremented_file_name(object_path.name, sequence)
        candidate_key = (
            object_path.with_name(candidate_name).as_posix()
            if str(object_path.parent) != "."
            else candidate_name
        )
        if resolve(candidate_key).exists():
            continue
        if write_if_absent(candidate_key, content):
            return candidate_key
    raise InvalidRequestError(
        "保存目标自动编号已达到上限",
        details={"object_key": object_key},
    )


def _write_filesystem_bytes_with_incremented_name(
    target_path: Path,
    content: bytes,
) -> Path:
    """在本机目录中原子选择可用文件名并写入 bytes。"""

    for sequence in range(_MAX_INCREMENTED_FILE_SEQUENCE + 1):
        candidate_path = target_path.with_name(
            _build_incremented_file_name(target_path.name, sequence)
        )
        if candidate_path.exists():
            continue
        if _write_filesystem_bytes_atomically_if_absent(candidate_path, content):
            return candidate_path
    raise InvalidRequestError(
        "保存目标自动编号已达到上限",
        details={"local_path": str(target_path)},
    )


def _copy_object_store_file_with_incremented_name(
    *,
    storage: object,
    object_key: str,
    source_path: Path,
) -> str:
    """在 ObjectStore 中原子选择可用文件名并流式复制文件。"""

    resolve = getattr(storage, "resolve", None)
    copy_if_absent = getattr(storage, "copy_file_if_absent", None)
    if not callable(resolve) or not callable(copy_if_absent):
        raise InvalidRequestError("当前 ObjectStore 不支持原子文件冲突自动编号")
    object_path = PurePosixPath(object_key)
    for sequence in range(_MAX_INCREMENTED_FILE_SEQUENCE + 1):
        candidate_name = _build_incremented_file_name(object_path.name, sequence)
        candidate_key = (
            object_path.with_name(candidate_name).as_posix()
            if str(object_path.parent) != "."
            else candidate_name
        )
        if resolve(candidate_key).exists():
            continue
        if copy_if_absent(source_path, candidate_key):
            return candidate_key
    raise InvalidRequestError(
        "保存目标自动编号已达到上限",
        details={"object_key": object_key},
    )


def _copy_filesystem_file_with_incremented_name(
    *,
    source_path: Path,
    target_path: Path,
) -> Path:
    """在本机目录中原子选择可用文件名并流式复制文件。"""

    for sequence in range(_MAX_INCREMENTED_FILE_SEQUENCE + 1):
        candidate_path = target_path.with_name(
            _build_incremented_file_name(target_path.name, sequence)
        )
        if candidate_path.exists():
            continue
        if _copy_filesystem_file_atomically_if_absent(
            source_path=source_path,
            target_path=candidate_path,
        ):
            return candidate_path
    raise InvalidRequestError(
        "保存目标自动编号已达到上限",
        details={"local_path": str(target_path)},
    )


def _build_incremented_file_name(file_name: str, sequence: int) -> str:
    """构造原名或在最后一个扩展名前插入三位起始的数字序号。"""

    if sequence <= 0:
        return file_name
    file_path = PurePosixPath(file_name)
    suffix = file_path.suffix
    stem = file_name[: -len(suffix)] if suffix else file_name
    return f"{stem}_{sequence:03d}{suffix}"


def _write_filesystem_bytes_atomically_if_absent(
    target_path: Path,
    content: bytes,
) -> bool:
    """原子创建本机文件；目标已存在时保持不变并返回 False。"""

    filesystem_target_path = to_filesystem_path(target_path)
    filesystem_target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = filesystem_target_path.with_name(
        f".{target_path.name}.{uuid4().hex[:12]}.tmp"
    )
    try:
        with temporary_path.open("wb") as output_stream:
            output_stream.write(content)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        published = publish_path_without_overwrite(
            temporary_path,
            filesystem_target_path,
        )
        if published:
            _sync_directory_after_replace(filesystem_target_path.parent)
        return published
    except OSError as error:
        raise InvalidRequestError(
            "无法写入系统保存位置",
            details={"local_path": str(target_path)},
        ) from error
    finally:
        temporary_path.unlink(missing_ok=True)


def _copy_filesystem_file_atomically(source_path: Path, target_path: Path) -> None:
    """把现有文件流式复制到本机绝对路径并原子替换。"""

    filesystem_target_path = to_filesystem_path(target_path)
    filesystem_target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = filesystem_target_path.with_name(
        f".{target_path.name}.{uuid4().hex[:12]}.tmp"
    )
    try:
        with (
            source_path.open("rb") as source_stream,
            temporary_path.open("wb") as output_stream,
        ):
            shutil.copyfileobj(source_stream, output_stream, length=1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        replace_path_with_retry(temporary_path, filesystem_target_path)
        _sync_directory_after_replace(filesystem_target_path.parent)
    except OSError as error:
        temporary_path.unlink(missing_ok=True)
        raise InvalidRequestError(
            "无法写入系统保存位置",
            details={"local_path": str(target_path)},
        ) from error


def _copy_filesystem_file_atomically_if_absent(
    *,
    source_path: Path,
    target_path: Path,
) -> bool:
    """流式复制并原子创建本机文件，目标已存在时保持不变。"""

    filesystem_target_path = to_filesystem_path(target_path)
    filesystem_target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = filesystem_target_path.with_name(
        f".{target_path.name}.{uuid4().hex[:12]}.tmp"
    )
    try:
        with (
            source_path.open("rb") as source_stream,
            temporary_path.open("wb") as output_stream,
        ):
            shutil.copyfileobj(source_stream, output_stream, length=1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        published = publish_path_without_overwrite(
            temporary_path,
            filesystem_target_path,
        )
        if published:
            _sync_directory_after_replace(filesystem_target_path.parent)
        return published
    except OSError as error:
        raise InvalidRequestError(
            "无法写入系统保存位置",
            details={"local_path": str(target_path)},
        ) from error
    finally:
        temporary_path.unlink(missing_ok=True)


def _sync_directory_after_replace(directory: Path) -> None:
    """在支持目录 fsync 的系统上持久化原子替换后的目录项。"""

    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
