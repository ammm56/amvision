"""Workflow Application 持久化写操作协调服务。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator, Literal
import uuid

from backend.service.application.errors import (
    PersistenceOperationError,
    ResourceConflictError,
    ResourceInUseError,
    ResourceNotFoundError,
    WorkflowRecoveryRequiredError,
)
from backend.service.application.workflows.documents.storage import (
    build_application_object_key,
    normalize_identifier,
)
from backend.service.application.workflows.lifecycle_resource_keys import (
    build_workflow_project_lifecycle_resource_key,
    is_project_mutation_lifecycle_resource_key,
    is_workflow_project_lifecycle_resource_key,
    is_workflow_lifecycle_resource_key,
)
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowApplicationLifecycle,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


WorkflowApplicationOperation = Literal["saving", "publishing", "deleting"]


@dataclass(frozen=True)
class WorkflowApplicationLifecycleRecoveryResult:
    """描述启动期 Application 写操作状态门收敛结果。"""

    scanned_operations: int
    recovered_operations: int


class WorkflowApplicationLifecycleService:
    """用短数据库事务串行同一 Application 的持久化写操作。

    文件读写在 claim 事务提交后执行。操作结束再用 generation 和
    operation_id 做一次短 CAS，避免过期进程覆盖新状态。
    """

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage | None,
    ) -> None:
        """初始化 Application lifecycle 服务。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage

    @contextmanager
    def operation(
        self,
        *,
        project_id: str,
        application_id: str,
        operation: WorkflowApplicationOperation,
        allow_deleted: bool = False,
        deleted_on_success: bool | None = None,
    ) -> Iterator[WorkflowApplicationLifecycle]:
        """占用状态门，在成功或失败时以短事务释放。"""

        claim = self.acquire(
            project_id=project_id,
            application_id=application_id,
            operation=operation,
            allow_deleted=allow_deleted,
        )
        try:
            yield claim
        except WorkflowRecoveryRequiredError:
            # 持久 journal 回滚失败时必须保留 claim，启动恢复完成前禁止新写。
            raise
        except Exception:
            # 文件 I/O 可能已经部分完成；按 application.json 的实际存在性
            # 收敛 tombstone。释放失败时保留原始业务异常，残留 claim 由启动恢复处理。
            try:
                self.complete(
                    claim,
                    deleted=self._application_is_deleted(
                        project_id=claim.project_id,
                        application_id=claim.application_id,
                    ),
                )
            except Exception:  # noqa: BLE001 - 不覆盖原始异常
                pass
            raise
        target_deleted = (
            claim.deleted if deleted_on_success is None else deleted_on_success
        )
        self.complete(claim, deleted=target_deleted)

    def acquire(
        self,
        *,
        project_id: str,
        application_id: str,
        operation: WorkflowApplicationOperation,
        allow_deleted: bool = False,
    ) -> WorkflowApplicationLifecycle:
        """以 generation CAS 立即占用写操作；满载时直接返回冲突。"""

        normalized_project_id = normalize_identifier(project_id, "project_id")
        normalized_application_id = normalize_identifier(
            application_id,
            "application_id",
            allow_reserved_application_id=is_workflow_lifecycle_resource_key(
                application_id
            ),
        )
        project_sentinel_key = build_workflow_project_lifecycle_resource_key(
            project_id=normalized_project_id
        )
        if normalized_application_id == project_sentinel_key:
            raise ResourceConflictError(
                "Project mutation sentinel 只能由 Project 删除流程直接占用",
                details={"project_id": normalized_project_id},
            )
        self._ensure_lifecycle(
            project_id=normalized_project_id,
            application_id=project_sentinel_key,
        )
        initial_lifecycle = self._build_initial_lifecycle(
            project_id=normalized_project_id,
            application_id=normalized_application_id,
        )
        operation_id = f"workflow-application-operation-{uuid.uuid4().hex}"
        updated_at = _now_isoformat()
        with self._open_unit_of_work() as unit_of_work:
            sentinel_touched = (
                unit_of_work.workflow_runtime.touch_workflow_project_lifecycle_sentinel(
                    project_id=normalized_project_id,
                    sentinel_resource_key=project_sentinel_key,
                    updated_at=updated_at,
                )
            )
            if not sentinel_touched:
                sentinel = (
                    unit_of_work.workflow_runtime.get_workflow_application_lifecycle(
                        normalized_project_id,
                        project_sentinel_key,
                    )
                )
                if sentinel is not None and sentinel.deleted:
                    raise ResourceNotFoundError(
                        "请求的 Project 已删除",
                        details={"project_id": normalized_project_id},
                    )
                raise ResourceConflictError(
                    "Project 正在删除，暂不能执行写操作",
                    details={
                        "project_id": normalized_project_id,
                        "current_operation": None
                        if sentinel is None
                        else sentinel.state,
                    },
                )
            lifecycle = (
                unit_of_work.workflow_runtime.get_workflow_application_lifecycle(
                    normalized_project_id,
                    normalized_application_id,
                )
            )
            if lifecycle is None:
                unit_of_work.workflow_runtime.add_workflow_application_lifecycle(
                    initial_lifecycle
                )
                unit_of_work.flush()
                lifecycle = initial_lifecycle
            if lifecycle.deleted and not allow_deleted:
                raise ResourceNotFoundError(
                    "请求的 workflow application 不存在",
                    details={
                        "project_id": normalized_project_id,
                        "application_id": normalized_application_id,
                    },
                )
            claimed = (
                unit_of_work.workflow_runtime.try_claim_workflow_application_lifecycle(
                    project_id=normalized_project_id,
                    application_id=normalized_application_id,
                    expected_generation=lifecycle.generation,
                    operation_state=operation,
                    operation_id=operation_id,
                    updated_at=updated_at,
                    allow_deleted=allow_deleted,
                )
            )
            unit_of_work.commit()
        if not claimed:
            current = self.get(
                project_id=normalized_project_id,
                application_id=normalized_application_id,
            )
            raise ResourceConflictError(
                "Workflow Application 正在执行其他写操作",
                details={
                    "project_id": normalized_project_id,
                    "application_id": normalized_application_id,
                    "requested_operation": operation,
                    "current_operation": current.state,
                    "generation": current.generation,
                },
            )
        return WorkflowApplicationLifecycle(
            project_id=normalized_project_id,
            application_id=normalized_application_id,
            state=operation,
            generation=lifecycle.generation + 1,
            operation_id=operation_id,
            updated_at=updated_at,
            deleted=lifecycle.deleted,
        )

    def acquire_project_deletion(
        self,
        *,
        project_id: str,
    ) -> WorkflowApplicationLifecycle:
        """原子占用 Project sentinel，并拒绝已有的持久 mutation claim。"""

        normalized_project_id = normalize_identifier(project_id, "project_id")
        sentinel_resource_key = build_workflow_project_lifecycle_resource_key(
            project_id=normalized_project_id
        )
        self._ensure_lifecycle(
            project_id=normalized_project_id,
            application_id=sentinel_resource_key,
        )
        operation_id = f"project-deletion-{uuid.uuid4().hex}"
        updated_at = _now_isoformat()
        with self._open_unit_of_work() as unit_of_work:
            claimed = unit_of_work.workflow_runtime.try_claim_workflow_project_deletion_sentinel(
                project_id=normalized_project_id,
                sentinel_resource_key=sentinel_resource_key,
                operation_id=operation_id,
                updated_at=updated_at,
            )
            if not claimed:
                sentinel = (
                    unit_of_work.workflow_runtime.get_workflow_application_lifecycle(
                        normalized_project_id,
                        sentinel_resource_key,
                    )
                )
                if sentinel is not None and sentinel.deleted:
                    raise ResourceNotFoundError(
                        "请求的 Project 已删除",
                        details={"project_id": normalized_project_id},
                    )
                raise ResourceConflictError(
                    "Project 已有删除操作正在执行",
                    details={
                        "project_id": normalized_project_id,
                        "current_operation": None
                        if sentinel is None
                        else sentinel.state,
                    },
                )
            sentinel = unit_of_work.workflow_runtime.get_workflow_application_lifecycle(
                normalized_project_id,
                sentinel_resource_key,
            )
            if sentinel is None:
                raise PersistenceOperationError(
                    "Project mutation sentinel 写入后无法回读"
                )
            active_claims = (
                unit_of_work.workflow_runtime.list_claimed_workflow_project_resources(
                    project_id=normalized_project_id,
                    sentinel_resource_key=sentinel_resource_key,
                )
            )
            if active_claims:
                raise ResourceInUseError(
                    "Project 仍有写操作正在执行，当前不能删除",
                    details={
                        "project_id": normalized_project_id,
                        "claims": [
                            {
                                "resource_key": item.application_id,
                                "state": item.state,
                                "operation_id": item.operation_id,
                            }
                            for item in active_claims
                        ],
                    },
                )
            unit_of_work.commit()
        return sentinel

    def list_project_deletion_claims(
        self,
    ) -> tuple[WorkflowApplicationLifecycle, ...]:
        """列出启动恢复需要处理的 Project 删除 sentinel claim。"""

        with self._open_unit_of_work() as unit_of_work:
            lifecycles = unit_of_work.workflow_runtime.list_claimed_workflow_application_lifecycles()
        return tuple(
            item
            for item in lifecycles
            if is_workflow_project_lifecycle_resource_key(
                project_id=item.project_id,
                resource_key=item.application_id,
            )
            and item.state == "deleting"
        )

    def complete(
        self,
        claim: WorkflowApplicationLifecycle,
        *,
        deleted: bool,
    ) -> None:
        """仅由当前 operation 完成状态门，过期完成会返回冲突。"""

        if claim.state == "idle" or claim.operation_id is None:
            raise ResourceConflictError("Workflow Application lifecycle claim 无效")
        with self._open_unit_of_work() as unit_of_work:
            completed = (
                unit_of_work.workflow_runtime.complete_workflow_application_lifecycle(
                    project_id=claim.project_id,
                    application_id=claim.application_id,
                    expected_generation=claim.generation,
                    operation_state=claim.state,
                    operation_id=claim.operation_id,
                    updated_at=_now_isoformat(),
                    deleted=deleted,
                )
            )
            unit_of_work.commit()
        if not completed:
            raise ResourceConflictError(
                "Workflow Application 写操作已被新 generation 取代",
                details={
                    "project_id": claim.project_id,
                    "application_id": claim.application_id,
                    "operation_id": claim.operation_id,
                    "generation": claim.generation,
                },
            )

    def delete_idle_temporary_resource(
        self,
        claim: WorkflowApplicationLifecycle,
    ) -> None:
        """尽力删除已释放的一次性 mutation claim；Project 删除可并发接管。"""

        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.delete_idle_workflow_application_lifecycle(
                project_id=claim.project_id,
                application_id=claim.application_id,
                expected_generation=claim.generation,
            )
            unit_of_work.commit()

    def get(
        self, *, project_id: str, application_id: str
    ) -> WorkflowApplicationLifecycle:
        """读取 lifecycle；调用方应先确保记录存在。"""

        with self._open_unit_of_work() as unit_of_work:
            lifecycle = (
                unit_of_work.workflow_runtime.get_workflow_application_lifecycle(
                    project_id,
                    application_id,
                )
            )
        if lifecycle is None:
            raise ResourceNotFoundError(
                "Workflow Application lifecycle 不存在",
                details={
                    "project_id": project_id,
                    "application_id": application_id,
                },
            )
        return lifecycle

    def recover_interrupted_operations(
        self,
    ) -> WorkflowApplicationLifecycleRecoveryResult:
        """启动期按草稿文件实际存在性收敛未完成 claim。

        此方法只在 API 开始接收请求前运行，不执行等待、轮询或后台重试。
        """

        with self._open_unit_of_work() as unit_of_work:
            lifecycles = unit_of_work.workflow_runtime.list_claimed_workflow_application_lifecycles()
        recoverable_lifecycles = tuple(
            lifecycle
            for lifecycle in lifecycles
            if not is_workflow_project_lifecycle_resource_key(
                project_id=lifecycle.project_id,
                resource_key=lifecycle.application_id,
            )
        )
        recovered = 0
        for lifecycle in recoverable_lifecycles:
            if is_workflow_lifecycle_resource_key(lifecycle.application_id):
                deleted = False
            else:
                dataset_storage = self._require_dataset_storage()
                object_key = build_application_object_key(
                    project_id=lifecycle.project_id,
                    application_id=lifecycle.application_id,
                )
                deleted = not dataset_storage.resolve(object_key).is_file()
            self.complete(lifecycle, deleted=deleted)
            if is_project_mutation_lifecycle_resource_key(lifecycle.application_id):
                self.delete_idle_temporary_resource(lifecycle)
            recovered += 1
        return WorkflowApplicationLifecycleRecoveryResult(
            scanned_operations=len(recoverable_lifecycles),
            recovered_operations=recovered,
        )

    def _build_initial_lifecycle(
        self,
        *,
        project_id: str,
        application_id: str,
    ) -> WorkflowApplicationLifecycle:
        """构建尚未写入数据库的 lifecycle 初始值。"""

        reserved_resource = is_workflow_lifecycle_resource_key(application_id)
        deleted = False
        if not reserved_resource:
            object_key = build_application_object_key(
                project_id=project_id,
                application_id=application_id,
            )
            deleted = not self._require_dataset_storage().resolve(object_key).is_file()
        return WorkflowApplicationLifecycle(
            project_id=project_id,
            application_id=application_id,
            updated_at=_now_isoformat(),
            deleted=deleted,
        )

    def _ensure_lifecycle(
        self,
        *,
        project_id: str,
        application_id: str,
    ) -> WorkflowApplicationLifecycle:
        """为旧文件型 Application 懒创建 lifecycle 或返回并发创建结果。"""

        with self._open_unit_of_work() as unit_of_work:
            existing = unit_of_work.workflow_runtime.get_workflow_application_lifecycle(
                project_id,
                application_id,
            )
        if existing is not None:
            return existing
        lifecycle = self._build_initial_lifecycle(
            project_id=project_id,
            application_id=application_id,
        )
        try:
            with self._open_unit_of_work() as unit_of_work:
                unit_of_work.workflow_runtime.add_workflow_application_lifecycle(
                    lifecycle
                )
                unit_of_work.commit()
            return lifecycle
        except PersistenceOperationError:
            # 复合主键冲突表示另一进程已完成相同的懒创建；回读唯一结果。
            return self.get(project_id=project_id, application_id=application_id)

    def _application_is_deleted(
        self,
        *,
        project_id: str,
        application_id: str,
    ) -> bool:
        """按规范草稿文件实际存在性判断 tombstone。"""

        if is_workflow_lifecycle_resource_key(application_id):
            return False

        object_key = build_application_object_key(
            project_id=project_id,
            application_id=application_id,
        )
        return not self._require_dataset_storage().resolve(object_key).is_file()

    def _require_dataset_storage(self) -> LocalDatasetStorage:
        """返回文档型 Application 所需存储；保留资源操作不需要此依赖。"""

        if self.dataset_storage is None:
            raise PersistenceOperationError(
                "文档型 Workflow Application lifecycle 缺少本地对象存储"
            )
        return self.dataset_storage

    @contextmanager
    def _open_unit_of_work(self) -> Iterator[SqlAlchemyUnitOfWork]:
        """打开一次短事务 Unit of Work。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            yield unit_of_work
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.close()


def _now_isoformat() -> str:
    """返回 UTC ISO-8601 时间。"""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
