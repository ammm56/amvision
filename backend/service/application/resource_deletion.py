"""统一资源删除编排：依赖预检、文件暂存、事务提交和失败重试。"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from backend.service.application.errors import (
    PersistenceOperationError,
    ResourceInUseError,
    ServiceError,
)
from backend.service.application.ports.queue import QueueBackend
from backend.service.application.project_mutation import ProjectMutationAdmissionService
from backend.service.application.resource_deletion_plan import (
    build_resource_deletion_plan,
    include_orphan_dataset_directory,
)
from backend.service.application.workflows.application_lifecycle import (
    WorkflowApplicationLifecycleService,
)
from backend.service.domain.resource_deletion import ResourceDeletionOperation
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowApplicationLifecycle,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


class ResourceDeletionService:
    """复用 Project mutation fence，在多进程写操作之间实施完整删除。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend | None = None,
    ) -> None:
        """注入与当前服务一致的数据库、文件根和持久队列。"""
        self.factory = session_factory
        self.storage = dataset_storage
        self.queue = queue_backend
        self.lifecycle = WorkflowApplicationLifecycleService(
            session_factory=session_factory, dataset_storage=dataset_storage
        )

    def delete(
        self,
        *,
        kind: str,
        resource_id: str,
        project_id: str,
        asynchronous: bool = False,
        orphan_dataset_id: str | None = None,
        expected_revision: str | None = None,
    ) -> str | None:
        """同步删除成功才返回；提交后的清理失败提供稳定操作 id。"""
        unit = self._unit()
        try:
            pending = next(
                (
                    op
                    for op in unit.resource_deletions.list_pending()
                    if op.plan.project_id == project_id
                    and op.plan.target.kind == kind
                    and op.plan.target.resource_id == resource_id
                ),
                None,
            )
        finally:
            unit.close()
        if pending is not None:
            if pending.state == "committed":
                if asynchronous:
                    return pending.plan.operation_id
                self._cleanup(pending)
                return
            raise ResourceInUseError(
                "资源已有删除操作等待恢复",
                details={"operation_id": pending.plan.operation_id},
            )

        claim = self.lifecycle.acquire_project_deletion(project_id=project_id)
        operation = None
        try:
            unit = self._unit()
            try:
                inventory = unit.resource_deletions.inventory()
            finally:
                unit.close()
            if orphan_dataset_id is not None:
                include_orphan_dataset_directory(
                    inventory,
                    project_id=project_id,
                    dataset_id=orphan_dataset_id,
                    kind=kind,
                    resource_id=resource_id,
                )
            plan = build_resource_deletion_plan(
                inventory=inventory,
                storage=self.storage,
                project_id=project_id,
                kind=kind,
                resource_id=resource_id,
                operation_id=claim.operation_id,
            )
            plan.claim = asdict(claim)
            if expected_revision and expected_revision != self._revision(plan):
                raise ResourceInUseError("删除范围已变化，请重新查看删除内容")
            plan.asynchronous = asynchronous
            operation = ResourceDeletionOperation(plan=plan, state="prepared")
            self._check_queue(operation)
            self._save(operation)
            for path in plan.paths:
                if self.storage.resolve_deletion_path(path.source).exists():
                    self.storage.move_tree(path.source, path.staged)
            self._check_queue(operation)
            unit = self._unit()
            try:
                # 同一 Project 的新资源登记/恢复被 sentinel 排除；终态执行器不再拥有写权限。
                unit.resource_deletions.delete_records(plan.records)
                committed = operation.model_copy(update={"state": "committed"})
                unit.resource_deletions.save(committed)
                if not unit.workflow_runtime.complete_workflow_application_lifecycle(
                    project_id=claim.project_id,
                    application_id=claim.application_id,
                    expected_generation=claim.generation,
                    operation_state=claim.state,
                    operation_id=claim.operation_id,
                    updated_at=datetime.now(timezone.utc).isoformat(),
                    deleted=False,
                ):
                    raise PersistenceOperationError("删除操作已失去 Project 写入权限")
                unit.commit()
                operation = committed
            except Exception:
                unit.rollback()
                raise
            finally:
                unit.close()
        except Exception as error:
            if operation is None:
                self.lifecycle.complete(claim, deleted=False)
            else:
                # 即便 commit 响应丢失，也按数据库的真实阶段决定恢复或继续清理。
                unit = self._unit()
                try:
                    persisted = unit.resource_deletions.get(operation.plan.operation_id)
                finally:
                    unit.close()
                if persisted is None or persisted.state == "prepared":
                    self._restore(operation)
            if isinstance(error, OSError):
                raise PersistenceOperationError(
                    "资源文件暂存失败，数据库记录已保留；解除文件占用或检查权限后重试",
                    details={"error_type": type(error).__name__, "phase": "staging"},
                ) from error
            raise
        if asynchronous:
            return operation.plan.operation_id
        self._cleanup(operation)
        return None

    @staticmethod
    def _revision(plan) -> str:
        """只对将删除的对象和原路径计算稳定摘要。"""
        from backend.service.application.deployments.package_import import content_hash
        return content_hash({"records": sorted((r.kind, r.resource_id) for r in plan.records), "paths": sorted(p.source for p in plan.paths)})

    def preview(self, *, kind: str, resource_id: str, project_id: str) -> dict:
        """读取与实际删除相同的范围，不占用或移动文件。"""
        unit = self._unit()
        try:
            inventory = unit.resource_deletions.inventory()
        finally:
            unit.close()
        plan = build_resource_deletion_plan(inventory=inventory, storage=self.storage, project_id=project_id, kind=kind, resource_id=resource_id, operation_id="preview")
        deleted = [{"kind": r.kind, "resource_id": r.resource_id} for r in plan.records if r.kind in {"model-version", "model-build"}]
        retained = []
        if kind == "deployment":
            instance = next(r for r in inventory["deployment"] if r["deployment_instance_id"] == resource_id)
            for rk, field in (("model-version", "model_version_id"), ("model-build", "model_build_id")):
                rid = instance.get(field)
                if rid and not any(r["resource_id"] == rid for r in deleted):
                    retained.append({"kind": rk, "resource_id": rid, "reason": "共享或被引用的导入产物，或本地训练/转换产物"})
        return {"revision": self._revision(plan), "deleted_models": deleted, "retained_models": retained}

    def recover(self) -> dict[str, int]:
        """启动时先恢复未提交删除，再完成已提交清理。"""
        unit = self._unit()
        try:
            operations = unit.resource_deletions.list_pending()
        finally:
            unit.close()
        restored = cleaned = failed = 0
        for operation in operations:
            if operation.state == "prepared":
                self._restore(operation)
                restored += 1
            else:
                try:
                    self._cleanup(operation)
                    cleaned += 1
                except ServiceError:
                    failed += 1
        return {"restored": restored, "cleaned": cleaned, "pending": failed}

    def retry(self, operation_id: str) -> None:
        """重试已提交的物理清理，不抢占尚在执行的暂存操作。"""
        unit = self._unit()
        try:
            operation = unit.resource_deletions.get(operation_id)
        finally:
            unit.close()
        if operation is None or operation.state in {"completed", "rolled_back"}:
            return
        if operation.state != "committed":
            raise ResourceInUseError("删除尚未提交，请等待执行或启动恢复")
        self._cleanup(operation)

    def _check_queue(self, operation: ResourceDeletionOperation) -> None:
        """任何关联 queued/leased 消息仍可产生文件，必须先结束执行。"""
        if self.queue is None:
            if any(ref.kind == "outbox" for ref in operation.plan.records):
                raise ResourceInUseError("删除任务需要绑定当前持久队列")
            return
        active = [
            message
            for message in self.queue.list_tasks_by_references(
                references=tuple(operation.plan.queue_references)
            )
            if message.status in {"queued", "leased"}
        ]
        if active:
            raise ResourceInUseError(
                "资源仍有活动队列消息",
                details={
                    "blockers": [
                        {
                            "resource_kind": "queue",
                            "resource_id": item.task_id,
                            "state": item.status,
                        }
                        for item in active
                    ]
                },
            )

    def _cleanup(self, operation: ResourceDeletionOperation) -> None:
        """按持久操作锁排除 HTTP 重试与 Worker 同时清理同一目录。"""
        with ProjectMutationAdmissionService(self.factory).operation(
            project_id=operation.plan.project_id,
            mutation_kind="resource-cleanup",
            resource_id=operation.plan.operation_id,
        ):
            unit = self._unit()
            try:
                latest = unit.resource_deletions.get(operation.plan.operation_id)
            finally:
                unit.close()
            if latest is not None and latest.state == "committed":
                self._cleanup_owned(latest)

    def _cleanup_owned(self, operation: ResourceDeletionOperation) -> None:
        """先清理外部消息，最后清理暂存和恢复记录；失败可重复执行。"""
        try:
            if self.queue is not None:
                self._check_queue(operation)
                self.queue.delete_tasks_by_references(
                    references=tuple(operation.plan.queue_references),
                    statuses=("completed", "failed"),
                )
            root = f"runtime/resource-deletion-staging/{operation.plan.operation_id}"
            self.storage.delete_tree(root)
            unit = self._unit()
            try:
                self._finish(unit, operation, "completed")
                unit.commit()
            finally:
                unit.close()
        except Exception as error:
            operation.error = str(error)
            self._save(operation)
            raise PersistenceOperationError(
                "数据库记录已删除，文件或队列清理尚未完成，可重试清理",
                details={
                    "operation_id": operation.plan.operation_id,
                    "cleanup_state": "pending",
                    "error_type": type(error).__name__,
                },
            ) from error

    def _restore(self, operation: ResourceDeletionOperation) -> None:
        """提交前失败逆序恢复；恢复不完整时保留数据库清单和写入门。"""
        for path in reversed(operation.plan.paths):
            if self.storage.resolve_deletion_path(path.staged).exists():
                if self.storage.resolve_deletion_path(path.source).exists():
                    raise PersistenceOperationError(
                        "删除恢复时原目录被重新创建",
                        details={"operation_id": operation.plan.operation_id},
                    )
                self.storage.move_tree(path.staged, path.source)
        self.storage.delete_tree(
            f"runtime/resource-deletion-staging/{operation.plan.operation_id}"
        )
        claim = WorkflowApplicationLifecycle(**operation.plan.claim)
        current = self.lifecycle.get(
            project_id=claim.project_id, application_id=claim.application_id
        )
        if current.operation_id == claim.operation_id and current.state == claim.state:
            self.lifecycle.complete(claim, deleted=False)
        unit = self._unit()
        try:
            self._finish(unit, operation, "rolled_back")
            unit.commit()
        finally:
            unit.close()

    def _save(self, operation: ResourceDeletionOperation) -> None:
        """原子保存删除阶段和错误。"""
        unit = self._unit()
        try:
            unit.resource_deletions.save(operation)
            unit.commit()
        finally:
            unit.close()

    @staticmethod
    def _finish(
        unit: SqlAlchemyUnitOfWork, operation: ResourceDeletionOperation, state: str
    ) -> None:
        """同步删除不留回执；异步只保留短期结果供前端准确判定。"""
        if operation.plan.asynchronous:
            receipt_plan = operation.plan.model_copy(
                update={"records": [], "paths": [], "queue_references": [], "claim": {}}
            )
            unit.resource_deletions.save(
                ResourceDeletionOperation(plan=receipt_plan, state=state)
            )
        else:
            unit.resource_deletions.remove(operation.plan.operation_id)

    def _unit(self) -> SqlAlchemyUnitOfWork:
        """创建短事务，磁盘 I/O 期间不持有数据库事务。"""
        return SqlAlchemyUnitOfWork(self.factory.create_session())
