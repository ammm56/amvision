"""Workflow 节点输出目录解析和文件写入。"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal
from uuid import uuid4

from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.filesystem.atomic_files import (
    replace_path_with_retry,
)
from backend.service.infrastructure.filesystem.windows_paths import to_filesystem_path


OUTPUT_TARGET_OBJECT_STORE = "object-store"
OUTPUT_TARGET_FILESYSTEM = "filesystem"
OutputTargetKind = Literal["object-store", "filesystem"]


@dataclass(frozen=True)
class WorkflowOutputDirectory:
    """描述节点参数解析后的输出目录。"""

    kind: OutputTargetKind
    object_key_prefix: str | None = None
    filesystem_path: Path | None = None


@dataclass(frozen=True)
class WorkflowOutputFile:
    """描述节点写入完成后的文件引用。"""

    kind: OutputTargetKind
    object_key: str | None = None
    local_path: Path | None = None

    def to_payload(self) -> dict[str, object]:
        """构造可放入节点输出的稳定引用。"""

        if self.kind == OUTPUT_TARGET_OBJECT_STORE:
            return {
                "kind": OUTPUT_TARGET_OBJECT_STORE,
                "object_key": str(self.object_key or ""),
            }
        return {
            "kind": OUTPUT_TARGET_FILESYSTEM,
            "local_path": str(self.local_path or ""),
        }


def resolve_optional_output_directory(value: object) -> WorkflowOutputDirectory | None:
    """解析可选输出目录；相对路径走 ObjectStore，绝对路径走本机文件系统。"""

    if not isinstance(value, str) or not value.strip():
        return None
    raw_value = os.path.expanduser(value.strip())
    native_path = Path(raw_value)
    if native_path.is_absolute():
        try:
            resolved_path = native_path.resolve(strict=False)
        except OSError as error:
            raise InvalidRequestError(
                "系统输出目录无法解析",
                details={"output_dir": value},
            ) from error
        return WorkflowOutputDirectory(
            kind=OUTPUT_TARGET_FILESYSTEM,
            filesystem_path=resolved_path,
        )

    windows_path = PureWindowsPath(raw_value)
    posix_path = PurePosixPath(raw_value.replace("\\", "/"))
    if windows_path.drive or windows_path.root or posix_path.is_absolute():
        raise InvalidRequestError(
            "output_dir 必须是当前系统可解析的绝对路径或 ObjectStore 相对路径",
            details={"output_dir": value},
        )
    if ".." in posix_path.parts:
        raise InvalidRequestError(
            "ObjectStore 输出目录不能包含父目录引用",
            details={"output_dir": value},
        )
    cleaned_parts = tuple(part for part in posix_path.parts if part not in {"", "."})
    if not cleaned_parts:
        return None
    return WorkflowOutputDirectory(
        kind=OUTPUT_TARGET_OBJECT_STORE,
        object_key_prefix=PurePosixPath(*cleaned_parts).as_posix(),
    )


def write_output_bytes(
    request: object,
    *,
    output_directory: WorkflowOutputDirectory,
    file_name: str,
    content: bytes,
) -> WorkflowOutputFile:
    """按输出目录类型原子写入文件，并返回对应引用。"""

    normalized_file_name = _normalize_file_name(file_name)
    if output_directory.kind == OUTPUT_TARGET_OBJECT_STORE:
        from backend.nodes.runtime_support import require_dataset_storage

        object_key_prefix = str(output_directory.object_key_prefix or "")
        object_key = f"{object_key_prefix}/{normalized_file_name}"
        require_dataset_storage(request).write_bytes(object_key, content)
        return WorkflowOutputFile(
            kind=OUTPUT_TARGET_OBJECT_STORE,
            object_key=object_key,
        )

    directory_path = output_directory.filesystem_path
    if directory_path is None:
        raise InvalidRequestError("系统输出目录缺少有效路径")
    target_path = directory_path / normalized_file_name
    _write_filesystem_bytes_atomically(target_path, content)
    return WorkflowOutputFile(
        kind=OUTPUT_TARGET_FILESYSTEM,
        local_path=target_path,
    )


def _normalize_file_name(file_name: str) -> str:
    """校验输出文件名，禁止文件名再次携带目录层级。"""

    normalized_name = file_name.strip() if isinstance(file_name, str) else ""
    if (
        not normalized_name
        or normalized_name in {".", ".."}
        or PurePosixPath(normalized_name).name != normalized_name
        or PureWindowsPath(normalized_name).name != normalized_name
    ):
        raise InvalidRequestError(
            "输出文件名不合法",
            details={"file_name": file_name},
        )
    return normalized_name


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
            "无法写入系统输出目录",
            details={"local_path": str(target_path)},
        ) from error


def _sync_directory_after_replace(directory: Path) -> None:
    """在支持目录 fsync 的系统上持久化原子替换后的目录项。"""

    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
