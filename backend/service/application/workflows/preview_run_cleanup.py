"""preview run snapshot 目录的 staging cleanup 辅助。"""

from __future__ import annotations

from backend.contracts.workflows.resource_semantics import (
    build_workflow_preview_run_cleanup_staging_dir,
    build_workflow_preview_run_storage_dir,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


def stage_preview_run_storage_for_cleanup(
    *,
    dataset_storage: LocalDatasetStorage,
    preview_run_id: str,
) -> str | None:
    """把 preview run 目录搬到 cleanup staging 区。

    参数：
    - dataset_storage：本地 ObjectStore。
    - preview_run_id：目标 preview run id。

    返回：
    - str | None：存在 snapshot 目录时返回 staging 目录；不存在时返回 None。
    """

    source_dir = build_workflow_preview_run_storage_dir(preview_run_id)
    source_path = dataset_storage.resolve(source_dir)
    if not source_path.exists():
        return None

    staging_dir = build_workflow_preview_run_cleanup_staging_dir(preview_run_id)
    dataset_storage.delete_tree(staging_dir)
    dataset_storage.move_tree(source_dir, staging_dir)
    return staging_dir


def restore_staged_preview_run_storage(
    *,
    dataset_storage: LocalDatasetStorage,
    preview_run_id: str,
    staging_dir: str | None,
) -> None:
    """把 staging 区里的 preview run 目录恢复回原始位置。

    参数：
    - dataset_storage：本地 ObjectStore。
    - preview_run_id：目标 preview run id。
    - staging_dir：当前 staging 目录；为空时直接返回。
    """

    if staging_dir is None:
        return
    staging_path = dataset_storage.resolve(staging_dir)
    if not staging_path.exists():
        return
    dataset_storage.move_tree(staging_dir, build_workflow_preview_run_storage_dir(preview_run_id))


def finalize_staged_preview_run_storage(
    *,
    dataset_storage: LocalDatasetStorage,
    staging_dir: str | None,
) -> str | None:
    """删除 preview run staging 目录；失败时返回待后续清理的目录。

    参数：
    - dataset_storage：本地 ObjectStore。
    - staging_dir：当前 staging 目录；为空时直接返回 None。

    返回：
    - str | None：删除失败时返回 staging 目录，否则返回 None。
    """

    if staging_dir is None:
        return None
    try:
        dataset_storage.delete_tree(staging_dir)
    except OSError:
        return staging_dir
    return None