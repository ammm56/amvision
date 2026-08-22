"""恢复 Conversion 文件发布与数据库登记之间的中断窗口。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from backend.service.application.conversions.publication import (
    write_conversion_publication_state,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class ConversionPublicationReconcileResult:
    """描述一次 publication 恢复扫描结果。"""

    scanned: int = 0
    repaired_registered: int = 0
    reclaimed_orphans: int = 0
    unresolved: int = 0


class ConversionPublicationReconciler:
    """按 DB 真相修复 marker，并回收已终止任务的无登记产物。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        minimum_orphan_age_seconds: float = 3600.0,
    ) -> None:
        """初始化 publication 恢复器。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.minimum_orphan_age_seconds = max(
            0.0,
            float(minimum_orphan_age_seconds),
        )

    def reconcile_once(self) -> ConversionPublicationReconcileResult:
        """扫描全部未完成 publication 记录并执行安全恢复。"""

        scanned = 0
        repaired_registered = 0
        reclaimed_orphans = 0
        unresolved = 0
        for publication_object_key in self._list_publication_object_keys():
            raw_record = self.dataset_storage.read_json(publication_object_key)
            if not isinstance(raw_record, dict):
                unresolved += 1
                continue
            state = raw_record.get("state")
            if state not in {"publishing", "published_pending_registration"}:
                continue
            scanned += 1
            task_id = raw_record.get("conversion_task_id")
            final_builds_object_key = raw_record.get("final_builds_object_key")
            if not isinstance(task_id, str) or not isinstance(
                final_builds_object_key,
                str,
            ):
                unresolved += 1
                continue
            if not self._has_valid_publication_scope(
                publication_object_key=publication_object_key,
                task_id=task_id,
                final_builds_object_key=final_builds_object_key,
            ):
                unresolved += 1
                continue
            task_state, model_build_ids = self._read_database_state(task_id)
            if model_build_ids:
                write_conversion_publication_state(
                    dataset_storage=self.dataset_storage,
                    publication_object_key=publication_object_key,
                    state="registered",
                    payload={"model_build_ids": list(model_build_ids)},
                )
                repaired_registered += 1
                continue
            if not self._is_safe_orphan(
                task_state=task_state,
                created_at=raw_record.get("created_at"),
            ):
                unresolved += 1
                continue
            self.dataset_storage.delete_tree(final_builds_object_key)
            write_conversion_publication_state(
                dataset_storage=self.dataset_storage,
                publication_object_key=publication_object_key,
                state="orphan_reclaimed",
                payload={"task_state": task_state},
            )
            reclaimed_orphans += 1
        return ConversionPublicationReconcileResult(
            scanned=scanned,
            repaired_registered=repaired_registered,
            reclaimed_orphans=reclaimed_orphans,
            unresolved=unresolved,
        )

    def _read_database_state(
        self,
        task_id: str,
    ) -> tuple[str | None, tuple[str, ...]]:
        """读取 Task 状态和同一 conversion 已登记的全部 build id。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            task = unit_of_work.tasks.get_task(task_id)
            builds = unit_of_work.models.list_model_builds_by_conversion_task_id(
                task_id
            )
            return (
                task.state if task is not None else None,
                tuple(build.model_build_id for build in builds),
            )
        finally:
            unit_of_work.close()

    def _is_safe_orphan(
        self,
        *,
        task_state: str | None,
        created_at: object,
    ) -> bool:
        """仅把无 DB build 且任务已终止或已删除的旧 publication 视为孤儿。"""

        if task_state not in {None, "failed", "timed_out", "cancelled"}:
            return False
        if not isinstance(created_at, str):
            return False
        try:
            created_time = datetime.fromisoformat(created_at)
        except ValueError:
            return False
        if created_time.tzinfo is None:
            created_time = created_time.replace(tzinfo=timezone.utc)
        age_seconds = (
            datetime.now(timezone.utc) - created_time.astimezone(timezone.utc)
        ).total_seconds()
        return age_seconds >= self.minimum_orphan_age_seconds

    @staticmethod
    def _has_valid_publication_scope(
        *,
        publication_object_key: str,
        task_id: str,
        final_builds_object_key: str,
    ) -> bool:
        """确认 marker 只能描述其所属 conversion Task 的固定发布目录。"""

        publication_parts = PurePosixPath(publication_object_key).parts
        if len(publication_parts) != 6:
            return False
        if publication_parts[:2] != ("task-runs", "conversion"):
            return False
        if publication_parts[2] != task_id:
            return False
        if publication_parts[3] != "attempts" or not publication_parts[4]:
            return False
        if publication_parts[5:] != ("publication.json",):
            return False
        expected_builds_key = (
            f"task-runs/conversion/{task_id}/artifacts/builds"
        )
        return PurePosixPath(final_builds_object_key).as_posix() == expected_builds_key

    def _list_publication_object_keys(self) -> tuple[str, ...]:
        """列出本地 ObjectStore 中全部 conversion publication 记录。"""

        root = self.dataset_storage.resolve("task-runs/conversion")
        if not root.is_dir():
            return ()
        publication_paths = sorted(root.glob("*/attempts/*/publication.json"))
        return tuple(self._to_object_key(path) for path in publication_paths)

    def _to_object_key(self, path: Path) -> str:
        """把 ObjectStore 绝对路径转换为稳定 POSIX object key。"""

        return path.resolve().relative_to(
            self.dataset_storage.root_dir.resolve()
        ).as_posix()


__all__ = [
    "ConversionPublicationReconcileResult",
    "ConversionPublicationReconciler",
]
