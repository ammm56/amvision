"""Workflow 资源物理删除的本地存储暂存与恢复工具。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from backend.service.application.errors import PersistenceOperationError
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


WORKFLOW_RESOURCE_DELETION_STAGING_ROOT = "workflows/runtime/resource-deletion-staging"
_MANIFEST_NAME = "manifest.json"
_MANIFEST_FORMAT = "amvision.workflow-resource-deletion-manifest.v1"


@dataclass(frozen=True)
class WorkflowResourceDeletionStaging:
    """描述一次已经写入 manifest 的资源删除暂存。"""

    operation_id: str
    resource_kind: str
    resource_id: str
    staging_root: str
    paths: tuple[tuple[str, str], ...]
    metadata: dict[str, object]


def stage_workflow_resource_storage(
    *,
    dataset_storage: LocalDatasetStorage,
    operation_id: str,
    resource_kind: str,
    resource_id: str,
    source_paths: tuple[str, ...],
    metadata: dict[str, object] | None = None,
) -> WorkflowResourceDeletionStaging:
    """先落盘删除计划，再把存在的精确资源目录移入暂存区。"""

    normalized_operation_id = _require_text(operation_id, "operation_id")
    normalized_resource_kind = _require_text(resource_kind, "resource_kind")
    normalized_resource_id = _require_text(resource_id, "resource_id")
    staging_root = (
        f"{WORKFLOW_RESOURCE_DELETION_STAGING_ROOT}/{normalized_operation_id}"
    )
    if dataset_storage.resolve(staging_root).exists():
        raise PersistenceOperationError(
            "Workflow 资源删除暂存目录已存在",
            details={"staging_root": staging_root},
        )

    existing_sources = _collect_existing_source_paths(
        dataset_storage=dataset_storage,
        source_paths=source_paths,
    )
    planned_paths = tuple(
        (
            source_path,
            (f"{staging_root}/items/{index:04d}/{PurePosixPath(source_path).name}"),
        )
        for index, source_path in enumerate(existing_sources)
    )
    normalized_metadata = dict(metadata or {})
    dataset_storage.write_json(
        f"{staging_root}/{_MANIFEST_NAME}",
        {
            "format_id": _MANIFEST_FORMAT,
            "operation_id": normalized_operation_id,
            "resource_kind": normalized_resource_kind,
            "resource_id": normalized_resource_id,
            "paths": [
                {"source": source, "destination": destination}
                for source, destination in planned_paths
            ],
            "metadata": normalized_metadata,
        },
    )
    moved_paths: list[tuple[str, str]] = []
    try:
        for source_path, destination_path in planned_paths:
            dataset_storage.move_tree(source_path, destination_path)
            moved_paths.append((source_path, destination_path))
    except Exception:
        _restore_paths(dataset_storage=dataset_storage, paths=tuple(moved_paths))
        dataset_storage.delete_tree(staging_root)
        raise
    return WorkflowResourceDeletionStaging(
        operation_id=normalized_operation_id,
        resource_kind=normalized_resource_kind,
        resource_id=normalized_resource_id,
        staging_root=staging_root,
        paths=planned_paths,
        metadata=normalized_metadata,
    )


def restore_staged_workflow_resource_storage(
    *,
    dataset_storage: LocalDatasetStorage,
    staging: WorkflowResourceDeletionStaging,
) -> None:
    """按逆序恢复已经移动的资源目录，并删除暂存目录。"""

    _restore_paths(dataset_storage=dataset_storage, paths=staging.paths)
    dataset_storage.delete_tree(staging.staging_root)


def finalize_staged_workflow_resource_storage(
    *,
    dataset_storage: LocalDatasetStorage,
    staging: WorkflowResourceDeletionStaging,
) -> str | None:
    """删除已经提交的暂存目录；失败时返回待启动恢复的目录。"""

    try:
        dataset_storage.delete_tree(staging.staging_root)
    except OSError:
        return staging.staging_root
    if dataset_storage.resolve(staging.staging_root).exists():
        return staging.staging_root
    return None


def list_staged_workflow_resource_storage(
    *,
    dataset_storage: LocalDatasetStorage,
    resource_kind: str | None = None,
) -> tuple[WorkflowResourceDeletionStaging, ...]:
    """读取全部有效暂存 manifest，可按资源类型过滤。"""

    normalized_kind = resource_kind.strip() if resource_kind is not None else None
    staging_parent = dataset_storage.resolve(WORKFLOW_RESOURCE_DELETION_STAGING_ROOT)
    if not staging_parent.is_dir():
        return ()
    items: list[WorkflowResourceDeletionStaging] = []
    for child in sorted(staging_parent.iterdir(), key=lambda path: path.name):
        if not child.is_dir():
            continue
        staging_root = f"{WORKFLOW_RESOURCE_DELETION_STAGING_ROOT}/{child.name}"
        manifest_path = dataset_storage.resolve(f"{staging_root}/{_MANIFEST_NAME}")
        if not manifest_path.is_file():
            # manifest 原子写入前不移动任何权威目录，孤立空目录可直接清理。
            dataset_storage.delete_tree(staging_root)
            continue
        payload = dataset_storage.read_json(f"{staging_root}/{_MANIFEST_NAME}")
        staging = _parse_manifest(staging_root=staging_root, payload=payload)
        if normalized_kind is None or staging.resource_kind == normalized_kind:
            items.append(staging)
    return tuple(items)


def _parse_manifest(
    *,
    staging_root: str,
    payload: object,
) -> WorkflowResourceDeletionStaging:
    """校验并解析一份删除暂存 manifest。"""

    if not isinstance(payload, dict) or payload.get("format_id") != _MANIFEST_FORMAT:
        raise PersistenceOperationError(
            "Workflow 资源删除暂存 manifest 格式无效",
            details={"staging_root": staging_root},
        )
    operation_id = _require_text(payload.get("operation_id"), "operation_id")
    resource_kind = _require_text(payload.get("resource_kind"), "resource_kind")
    resource_id = _require_text(payload.get("resource_id"), "resource_id")
    raw_paths = payload.get("paths")
    if not isinstance(raw_paths, list):
        raise PersistenceOperationError("Workflow 资源删除 manifest.paths 格式无效")
    paths: list[tuple[str, str]] = []
    for raw_path in raw_paths:
        if not isinstance(raw_path, dict):
            raise PersistenceOperationError("Workflow 资源删除 manifest 路径项无效")
        source = _require_text(raw_path.get("source"), "source")
        destination = _require_text(raw_path.get("destination"), "destination")
        if not destination.startswith(f"{staging_root}/items/"):
            raise PersistenceOperationError(
                "Workflow 资源删除 manifest 暂存路径越界",
                details={"destination": destination},
            )
        paths.append((source, destination))
    raw_metadata = payload.get("metadata", {})
    if not isinstance(raw_metadata, dict):
        raise PersistenceOperationError("Workflow 资源删除 manifest.metadata 格式无效")
    return WorkflowResourceDeletionStaging(
        operation_id=operation_id,
        resource_kind=resource_kind,
        resource_id=resource_id,
        staging_root=staging_root,
        paths=tuple(paths),
        metadata=dict(raw_metadata),
    )


def _collect_existing_source_paths(
    *,
    dataset_storage: LocalDatasetStorage,
    source_paths: tuple[str, ...],
) -> tuple[str, ...]:
    """保留存在且互不嵌套的精确对象路径。"""

    candidates: set[str] = set()
    for value in source_paths:
        source_path = _require_text(value, "source_path").replace("\\", "/").strip("/")
        resolved = dataset_storage.resolve(source_path)
        if resolved.exists():
            candidates.add(source_path)
    existing: list[str] = []
    for source_path in sorted(
        candidates,
        key=lambda item: (len(PurePosixPath(item).parts), item),
    ):
        if any(
            source_path == parent or source_path.startswith(f"{parent}/")
            for parent in existing
        ):
            continue
        existing.append(source_path)
    return tuple(existing)


def _restore_paths(
    *,
    dataset_storage: LocalDatasetStorage,
    paths: tuple[tuple[str, str], ...],
) -> None:
    """只恢复确实已经移动的目录，拒绝覆盖新数据。"""

    for source_path, destination_path in reversed(paths):
        if not dataset_storage.resolve(destination_path).exists():
            continue
        if dataset_storage.resolve(source_path).exists():
            raise PersistenceOperationError(
                "Workflow 资源删除恢复时源路径与暂存路径同时存在",
                details={
                    "source_path": source_path,
                    "destination_path": destination_path,
                },
            )
        dataset_storage.move_tree(destination_path, source_path)


def _require_text(value: object, field_name: str) -> str:
    """读取非空文本字段。"""

    normalized = str(value or "").strip()
    if not normalized:
        raise PersistenceOperationError(f"Workflow 资源删除 {field_name} 不能为空")
    return normalized
