"""统一任务应用服务。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
from typing import Literal
from uuid import uuid4

from backend.service.application.events.event_bus import ServiceEvent
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
)
from backend.service.application.project_mutation import ProjectMutationAdmissionService
from backend.service.application.tasks.queue_outbox import build_queue_outbox_message
from backend.service.domain.tasks.task_records import (
    TaskAttempt,
    TaskAttemptState,
    TaskEvent,
    TaskEventType,
    TaskRecord,
    TaskRecordState,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


@dataclass(frozen=True)
class CreateTaskRequest:
    """描述一次创建 TaskRecord 的请求。

    字段：
    - project_id：所属 Project id。
    - task_kind：任务类型，例如 dataset-import、training。
    - display_name：用于界面展示的任务名。
    - created_by：提交任务的主体 id。
    - parent_task_id：父任务 id。
    - task_spec：任务规格快照。
    - resource_profile_id：关联的 ResourceProfile id。
    - worker_pool：目标 worker pool 名称。
    - metadata：附加元数据。
    - state：初始任务状态。
    - task_id：可选的显式任务 id；为空时自动生成。
    - created_at：可选的显式创建时间；为空时自动生成。
    """

    project_id: str
    task_kind: str
    display_name: str = ""
    created_by: str | None = None
    parent_task_id: str | None = None
    task_spec: dict[str, object] = field(default_factory=dict)
    resource_profile_id: str | None = None
    worker_pool: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    state: TaskRecordState = "queued"
    task_id: str | None = None
    created_at: str | None = None
    queue_submission: TaskQueueSubmission | None = None


@dataclass(frozen=True)
class TaskQueueSubmission:
    """描述与 TaskRecord 同事务提交的稳定队列消息。"""

    queue_name: str
    payload: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    message_id: str | None = None


TaskAttemptClaimOutcome = Literal[
    "acquired",
    "finalization_recovery",
    "duplicate_running",
    "duplicate_finished",
    "task_finished",
    "obsolete_attempt",
]


@dataclass(frozen=True)
class TaskAttemptClaim:
    """描述持久任务 worker 对一次执行尝试的原子领取结果。"""

    outcome: TaskAttemptClaimOutcome
    task: TaskRecord
    attempt: TaskAttempt | None = None

    @property
    def acquired(self) -> bool:
        """返回当前 worker 是否取得执行权。"""

        return self.outcome in {"acquired", "finalization_recovery"}


@dataclass(frozen=True)
class AppendTaskEventRequest:
    """描述一次追加 TaskEvent 的请求。

    字段：
    - task_id：所属任务 id。
    - attempt_id：关联的 TaskAttempt id。
    - event_type：事件类型。
    - message：事件消息。
    - payload：事件负载。
    - event_id：可选的显式事件 id；为空时自动生成。
    - created_at：可选的显式事件时间；为空时自动生成。
    """

    task_id: str
    attempt_id: str | None = None
    event_type: TaskEventType = "log"
    message: str = ""
    payload: dict[str, object] = field(default_factory=dict)
    event_id: str | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class TaskQueryFilters:
    """描述公开查询接口使用的任务筛选条件。

    字段：
    - project_id：所属 Project id。
    - task_kind：任务类型。
    - state：任务状态。
    - worker_pool：worker pool 名称。
    - created_by：提交主体 id。
    - parent_task_id：父任务 id。
    - dataset_id：task_spec 中记录的 Dataset id。
    - source_import_id：task_spec 或 metadata 中记录的 DatasetImport id。
    - limit：最大返回数量；为空时返回全部匹配结果。
    """

    project_id: str
    task_kind: str | None = None
    state: TaskRecordState | None = None
    worker_pool: str | None = None
    created_by: str | None = None
    parent_task_id: str | None = None
    dataset_id: str | None = None
    source_import_id: str | None = None
    limit: int | None = 100


@dataclass(frozen=True)
class TaskEventQueryFilters:
    """描述任务事件查询与订阅使用的筛选条件。

    字段：
    - task_id：所属任务 id。
    - event_type：事件类型。
    - after_created_at：只返回晚于该时间的事件。
    - after_cursor：只返回晚于 ``created_at|event_id`` 游标的事件。
    - offset：结果偏移量。
    - limit：最大返回数量。
    """

    task_id: str
    event_type: TaskEventType | None = None
    after_created_at: str | None = None
    after_cursor: str | None = None
    offset: int = 0
    limit: int = 100


@dataclass(frozen=True)
class TaskDetail:
    """描述任务详情查询结果。

    字段：
    - task：任务主记录。
    - events：任务事件列表。
    """

    task: TaskRecord
    events: tuple[TaskEvent, ...] = ()


class SqlAlchemyTaskService:
    """使用 SQLAlchemy Repository 与 Unit of Work 实现最小 tasks 服务。"""

    def __init__(self, session_factory: SessionFactory) -> None:
        """初始化 tasks 服务。

        参数：
        - session_factory：数据库会话工厂。
        """

        self.session_factory = session_factory
        self.service_event_bus = getattr(session_factory, "service_event_bus", None)
        self.project_mutations = ProjectMutationAdmissionService(session_factory)

    def create_task(self, request: CreateTaskRequest) -> TaskRecord:
        """创建一条新的 TaskRecord。

        参数：
        - request：创建任务请求。

        返回：
        - 已创建的 TaskRecord。
        """

        self._validate_create_request(request)
        created_at = request.created_at or self._now_iso()
        task_id = request.task_id or self._next_id("task")
        queue_message_id: str | None = None
        task_metadata = dict(request.metadata)
        queue_message = None
        if request.queue_submission is not None:
            queue_message_id = request.queue_submission.message_id or (
                f"queue-message-{task_id}"
            )
            queue_payload = dict(request.queue_submission.payload)
            payload_task_id = queue_payload.setdefault("task_id", task_id)
            if payload_task_id != task_id:
                raise InvalidRequestError(
                    "队列消息 task_id 与待创建任务不一致",
                    details={
                        "task_id": task_id,
                        "queue_payload_task_id": payload_task_id,
                    },
                )
            payload_attempt_no = queue_payload.setdefault("attempt_no", 1)
            if (
                isinstance(payload_attempt_no, bool)
                or not isinstance(payload_attempt_no, int)
                or payload_attempt_no != 1
            ):
                raise InvalidRequestError(
                    "新任务队列消息 attempt_no 必须为 1",
                    details={
                        "task_id": task_id,
                        "queue_payload_attempt_no": payload_attempt_no,
                    },
                )
            queue_message = build_queue_outbox_message(
                message_id=queue_message_id,
                queue_name=request.queue_submission.queue_name,
                payload=queue_payload,
                metadata=request.queue_submission.metadata,
                created_at=created_at,
            )
            task_metadata.update(
                {
                    "queue_name": queue_message.queue_name,
                    "queue_task_id": queue_message.message_id,
                }
            )
        task_record = TaskRecord(
            task_id=task_id,
            task_kind=request.task_kind,
            project_id=request.project_id,
            display_name=request.display_name,
            created_by=request.created_by,
            created_at=created_at,
            parent_task_id=request.parent_task_id,
            task_spec=dict(request.task_spec),
            resource_profile_id=request.resource_profile_id,
            worker_pool=request.worker_pool,
            metadata=task_metadata,
            state=request.state,
        )
        created_event_payload: dict[str, object] = {"state": request.state}
        if queue_message is not None:
            created_event_payload["metadata"] = {
                "queue_name": queue_message.queue_name,
                "queue_task_id": queue_message.message_id,
            }
        created_event = TaskEvent(
            event_id=self._next_id("task-event"),
            task_id=task_id,
            event_type="status",
            created_at=created_at,
            message="task created",
            payload=created_event_payload,
        )

        with self.project_mutations.operation(
            project_id=request.project_id,
            mutation_kind="task-create",
            resource_id=task_id,
        ):
            with self._open_unit_of_work() as unit_of_work:
                existing_task = unit_of_work.tasks.get_task(task_id)
                if existing_task is not None:
                    raise InvalidRequestError(
                        "任务 id 已存在",
                        details={"task_id": task_id},
                    )
                unit_of_work.tasks.save_task(task_record)
                unit_of_work.tasks.save_task_event(created_event)
                if queue_message is not None:
                    unit_of_work.queue_outbox.add_message(queue_message)
                unit_of_work.commit()

        self._publish_task_event(created_event)

        return task_record

    def get_task(self, task_id: str, *, include_events: bool = False) -> TaskDetail:
        """读取一条任务记录及其可选事件。"""

        with self._open_unit_of_work() as unit_of_work:
            task_record = unit_of_work.tasks.get_task(task_id)
            if task_record is None:
                raise ResourceNotFoundError(
                    "找不到指定的任务",
                    details={"task_id": task_id},
                )
            events = (
                unit_of_work.tasks.list_task_events(task_id) if include_events else ()
            )

        return TaskDetail(task=task_record, events=events)

    def start_task_attempt(
        self,
        *,
        task_id: str,
        attempt_no: int,
        worker_id: str | None = None,
        process_id: int | None = None,
        metadata: dict[str, object] | None = None,
    ) -> TaskAttempt:
        """创建正式运行中的 TaskAttempt，或补全 worker 已领取的同一次尝试。"""

        if attempt_no <= 0:
            raise InvalidRequestError("attempt_no 必须大于 0")
        started_at = self._now_iso()
        with self._open_unit_of_work() as unit_of_work:
            if unit_of_work.tasks.get_task(task_id) is None:
                raise ResourceNotFoundError(
                    "找不到指定的任务",
                    details={"task_id": task_id},
                )
            existing_attempt = unit_of_work.tasks.get_task_attempt_by_number(
                task_id,
                attempt_no,
            )
            if existing_attempt is not None:
                if existing_attempt.state != "running":
                    raise InvalidRequestError(
                        "当前 TaskAttempt 已经结束，不能重新开始",
                        details={
                            "task_id": task_id,
                            "attempt_no": attempt_no,
                            "state": existing_attempt.state,
                        },
                    )
                if "queue_message_id" in existing_attempt.metadata:
                    # Queue wrapper 已用 lease owner + heartbeat 管理此 Attempt。
                    # 业务 service 只能复用它，不能通过普通 save 覆盖 owner，
                    # 否则 lease 恢复接管与旧 worker 会互相破坏 fencing。
                    return existing_attempt
                attempt = replace(
                    existing_attempt,
                    worker_id=worker_id or existing_attempt.worker_id,
                    process_id=(
                        process_id
                        if process_id is not None
                        else existing_attempt.process_id
                    ),
                    heartbeat_at=started_at,
                    metadata={
                        **existing_attempt.metadata,
                        **dict(metadata or {}),
                    },
                )
                unit_of_work.tasks.save_task_attempt(attempt)
                unit_of_work.commit()
                return attempt

            attempt = TaskAttempt(
                attempt_id=self._build_task_attempt_id(task_id, attempt_no),
                task_id=task_id,
                attempt_no=attempt_no,
                worker_id=worker_id,
                process_id=process_id,
                state="running",
                started_at=started_at,
                heartbeat_at=started_at,
                metadata=dict(metadata or {}),
            )
            if not unit_of_work.tasks.try_create_task_attempt(attempt):
                existing_attempt = unit_of_work.tasks.get_task_attempt_by_number(
                    task_id,
                    attempt_no,
                )
                if existing_attempt is None:
                    raise InvalidRequestError(
                        "TaskAttempt 并发创建失败且无法读取胜出记录",
                        details={"task_id": task_id, "attempt_no": attempt_no},
                    )
                if existing_attempt.state != "running":
                    raise InvalidRequestError(
                        "当前 TaskAttempt 已经结束，不能重新开始",
                        details={
                            "task_id": task_id,
                            "attempt_no": attempt_no,
                            "state": existing_attempt.state,
                        },
                    )
                attempt = existing_attempt
            unit_of_work.commit()
        return attempt

    def claim_task_attempt(
        self,
        *,
        task_id: str,
        attempt_no: int,
        worker_id: str,
        queue_name: str,
        queue_message_id: str,
        queue_attempt_count: int,
        queue_leased_at: str,
        lease_recovery_count: int = 0,
    ) -> TaskAttemptClaim:
        """以 ``task_id + attempt_no`` 为键原子领取持久任务执行权。"""

        if not task_id.strip():
            raise InvalidRequestError("领取 TaskAttempt 时 task_id 不能为空")
        if attempt_no <= 0:
            raise InvalidRequestError("领取 TaskAttempt 时 attempt_no 必须大于 0")
        if not worker_id.strip():
            raise InvalidRequestError("领取 TaskAttempt 时 worker_id 不能为空")
        if queue_attempt_count <= 0:
            raise InvalidRequestError("领取 TaskAttempt 时 queue_attempt_count 必须大于 0")
        if not queue_leased_at.strip():
            raise InvalidRequestError("领取 TaskAttempt 时 queue_leased_at 不能为空")
        if lease_recovery_count < 0:
            raise InvalidRequestError("领取 TaskAttempt 时 lease_recovery_count 不能小于 0")

        started_at = self._now_iso()
        with self._open_unit_of_work() as unit_of_work:
            task_record = unit_of_work.tasks.get_task(task_id)
            if task_record is None:
                raise ResourceNotFoundError(
                    "找不到队列消息对应的任务",
                    details={"task_id": task_id},
                )
            existing_attempt = unit_of_work.tasks.get_task_attempt_by_number(
                task_id,
                attempt_no,
            )
            task_attempts = unit_of_work.tasks.list_task_attempts(task_id)
            if existing_attempt is None:
                # SQLite 的两次 SELECT 之间可能刚好有并发事务提交。此时第一次按
                # attempt_no 查询为空，而随后列表查询已经看见胜出的记录；优先复用
                # 列表快照，不能把同一轮次误判为 obsolete。
                existing_attempt = next(
                    (
                        item
                        for item in task_attempts
                        if item.attempt_no == attempt_no
                    ),
                    None,
                )
            latest_attempt_no = max(
                (item.attempt_no for item in task_attempts),
                default=0,
            )
            if existing_attempt is not None:
                if attempt_no < latest_attempt_no:
                    return TaskAttemptClaim(
                        outcome="obsolete_attempt",
                        task=task_record,
                        attempt=existing_attempt,
                    )
                recovered_attempt = self._try_reclaim_recovered_attempt(
                    unit_of_work=unit_of_work,
                    task_record=task_record,
                    existing_attempt=existing_attempt,
                    worker_id=worker_id,
                    queue_name=queue_name,
                    queue_message_id=queue_message_id,
                    queue_attempt_count=queue_attempt_count,
                    lease_recovery_count=lease_recovery_count,
                    heartbeat_at=queue_leased_at,
                )
                if recovered_attempt is not None:
                    return recovered_attempt
                if self._is_finalization_recovery(
                    task_record=task_record,
                    existing_attempt=existing_attempt,
                    queue_message_id=queue_message_id,
                    queue_attempt_count=queue_attempt_count,
                    lease_recovery_count=lease_recovery_count,
                ):
                    return TaskAttemptClaim(
                        outcome="finalization_recovery",
                        task=task_record,
                        attempt=existing_attempt,
                    )
                outcome: TaskAttemptClaimOutcome = (
                    "duplicate_running"
                    if existing_attempt.state == "running"
                    else "duplicate_finished"
                )
                return TaskAttemptClaim(
                    outcome=outcome,
                    task=task_record,
                    attempt=existing_attempt,
                )

            if task_record.state in {
                "succeeded",
                "failed",
                "timed_out",
                "cancelled",
            }:
                return TaskAttemptClaim(
                    outcome="task_finished",
                    task=task_record,
                )
            expected_attempt_no = latest_attempt_no + 1
            if attempt_no < expected_attempt_no:
                return TaskAttemptClaim(
                    outcome="obsolete_attempt",
                    task=task_record,
                )
            if attempt_no > expected_attempt_no:
                raise InvalidRequestError(
                    "队列消息 attempt_no 与任务当前轮次不连续",
                    details={
                        "task_id": task_id,
                        "attempt_no": attempt_no,
                        "expected_attempt_no": expected_attempt_no,
                    },
                )

            candidate = TaskAttempt(
                attempt_id=self._build_task_attempt_id(task_id, attempt_no),
                task_id=task_id,
                attempt_no=attempt_no,
                worker_id=worker_id,
                state="running",
                started_at=started_at,
                heartbeat_at=queue_leased_at,
                metadata={
                    "operation_kind": "queue-consumption",
                    "queue_name": queue_name,
                    "queue_message_id": queue_message_id,
                    "queue_attempt_count": queue_attempt_count,
                    "lease_recovery_count": lease_recovery_count,
                },
            )
            if unit_of_work.tasks.try_create_task_attempt(candidate):
                unit_of_work.commit()
                return TaskAttemptClaim(
                    outcome="acquired",
                    task=task_record,
                    attempt=candidate,
                )

            existing_attempt = unit_of_work.tasks.get_task_attempt_by_number(
                task_id,
                attempt_no,
            )
            if existing_attempt is None:
                raise InvalidRequestError(
                    "TaskAttempt 并发领取失败且无法读取胜出记录",
                    details={"task_id": task_id, "attempt_no": attempt_no},
                )
            return TaskAttemptClaim(
                outcome=(
                    "duplicate_running"
                    if existing_attempt.state == "running"
                    else "duplicate_finished"
                ),
                task=task_record,
                attempt=existing_attempt,
            )

    def finish_task_attempt(
        self,
        *,
        attempt_id: str,
        state: TaskAttemptState,
        exit_code: int | None = None,
        result: dict[str, object] | None = None,
        error_message: str | None = None,
        metadata: dict[str, object] | None = None,
        expected_worker_id: str | None = None,
        expected_heartbeat_at: str | None = None,
    ) -> TaskAttempt:
        """以成功、失败、超时或取消状态结束 TaskAttempt。"""

        if state == "running":
            raise InvalidRequestError("结束 TaskAttempt 时 state 不能是 running")
        with self._open_unit_of_work() as unit_of_work:
            attempt = unit_of_work.tasks.get_task_attempt(attempt_id)
            if attempt is None:
                raise ResourceNotFoundError(
                    "找不到指定的 TaskAttempt",
                    details={"attempt_id": attempt_id},
                )
            if attempt.state != "running":
                return attempt
            finished_at = self._now_iso()
            updated_attempt = replace(
                attempt,
                state=state,
                heartbeat_at=finished_at,
                ended_at=finished_at,
                exit_code=exit_code,
                result=dict(result or {}),
                error_message=error_message,
                metadata={**attempt.metadata, **dict(metadata or {})},
            )
            if not unit_of_work.tasks.try_finish_running_task_attempt(
                updated_attempt,
                expected_worker_id=expected_worker_id,
                expected_heartbeat_at=expected_heartbeat_at,
            ):
                concurrently_finished = unit_of_work.tasks.get_task_attempt(attempt_id)
                if concurrently_finished is None:
                    raise ResourceNotFoundError(
                        "结束 TaskAttempt 时记录已经不存在",
                        details={"attempt_id": attempt_id},
                    )
                return concurrently_finished
            unit_of_work.commit()
        return updated_attempt

    def heartbeat_task_attempt(
        self,
        *,
        attempt_id: str,
        worker_id: str,
        heartbeat_at: str,
    ) -> bool:
        """仅由当前 queue lease owner 刷新 running TaskAttempt heartbeat。"""

        with self._open_unit_of_work() as unit_of_work:
            refreshed = unit_of_work.tasks.try_heartbeat_running_task_attempt(
                attempt_id=attempt_id,
                worker_id=worker_id,
                heartbeat_at=heartbeat_at,
            )
            if refreshed:
                unit_of_work.commit()
            return refreshed

    def list_task_attempts(self, task_id: str) -> tuple[TaskAttempt, ...]:
        """按 attempt_no 返回任务的全部正式执行尝试。"""

        with self._open_unit_of_work() as unit_of_work:
            if unit_of_work.tasks.get_task(task_id) is None:
                raise ResourceNotFoundError(
                    "找不到指定的任务",
                    details={"task_id": task_id},
                )
            return unit_of_work.tasks.list_task_attempts(task_id)

    def get_next_task_attempt_no(self, task_id: str) -> int:
        """返回当前 Task 下一条队列消息应使用的 attempt_no。"""

        attempts = self.list_task_attempts(task_id)
        return max((attempt.attempt_no for attempt in attempts), default=0) + 1

    def get_visible_task(
        self,
        task_id: str,
        *,
        visible_project_ids: tuple[str, ...],
        include_events: bool = False,
    ) -> TaskDetail:
        """在 Repository 查询阶段按 Project 可见范围读取任务。"""

        with self._open_unit_of_work() as unit_of_work:
            task_record = unit_of_work.tasks.get_visible_task(
                task_id,
                visible_project_ids,
            )
            if task_record is None:
                raise ResourceNotFoundError(
                    "找不到指定的任务",
                    details={"task_id": task_id},
                )
            events = (
                unit_of_work.tasks.list_task_events(task_id) if include_events else ()
            )

        return TaskDetail(task=task_record, events=events)

    def list_tasks(self, filters: TaskQueryFilters) -> tuple[TaskRecord, ...]:
        """按筛选条件返回任务列表。"""

        if not filters.project_id.strip():
            raise InvalidRequestError("查询任务列表时 project_id 不能为空")
        if filters.limit is not None and filters.limit <= 0:
            raise InvalidRequestError("limit 必须大于 0")

        with self._open_unit_of_work() as unit_of_work:
            tasks = unit_of_work.tasks.list_tasks(filters.project_id)

        matched_tasks = [
            task for task in tasks if self._task_matches_filters(task, filters)
        ]
        matched_tasks.sort(
            key=lambda task: (task.created_at, task.task_id), reverse=True
        )
        if filters.limit is None:
            return tuple(matched_tasks)
        return tuple(matched_tasks[: filters.limit])

    def list_task_events(self, filters: TaskEventQueryFilters) -> tuple[TaskEvent, ...]:
        """按筛选条件返回任务事件列表。"""

        if not filters.task_id.strip():
            raise InvalidRequestError("查询任务事件时 task_id 不能为空")
        if filters.offset < 0:
            raise InvalidRequestError("offset 不能小于 0")
        if filters.limit <= 0:
            raise InvalidRequestError("limit 必须大于 0")

        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.tasks.list_task_events(
                filters.task_id,
                event_type=filters.event_type,
                after_created_at=filters.after_created_at,
                after_cursor=filters.after_cursor,
                offset=filters.offset,
                limit=filters.limit,
            )

    def append_task_event(self, request: AppendTaskEventRequest) -> TaskDetail:
        """为指定任务追加一条事件，并同步更新任务快照。

        参数：
        - request：待追加的任务事件请求。

        返回：
        - TaskDetail：更新后的任务快照，以及只包含本次新追加事件的 events；不返回历史事件。
        """

        if not request.task_id.strip():
            raise InvalidRequestError("追加任务事件时 task_id 不能为空")

        task_event = TaskEvent(
            event_id=request.event_id or self._next_id("task-event"),
            task_id=request.task_id,
            attempt_id=request.attempt_id,
            event_type=request.event_type,
            created_at=request.created_at or self._now_iso(),
            message=request.message,
            payload=dict(request.payload),
        )

        with self._open_unit_of_work() as unit_of_work:
            task_record = unit_of_work.tasks.get_task(request.task_id)
            if task_record is None:
                raise ResourceNotFoundError(
                    "找不到指定的任务",
                    details={"task_id": request.task_id},
                )
            updated_task = self._apply_event(
                task_record=task_record, task_event=task_event
            )
            unit_of_work.tasks.save_task(updated_task)
            unit_of_work.tasks.save_task_event(task_event)
            unit_of_work.commit()

        self._publish_task_event(task_event)

        return TaskDetail(task=updated_task, events=(task_event,))

    def cancel_task(
        self, task_id: str, *, cancelled_by: str | None = None
    ) -> TaskDetail:
        """取消一条尚未结束的任务。"""

        current_task = self.get_task(task_id).task
        if current_task.state == "cancelled":
            return TaskDetail(task=current_task, events=())
        if current_task.state in {"succeeded", "failed"}:
            raise InvalidRequestError(
                "当前任务已经结束，不能取消",
                details={"task_id": task_id, "state": current_task.state},
            )

        return self.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="task cancelled",
                payload={
                    "state": "cancelled",
                    "finished_at": self._now_iso(),
                    "metadata": {"cancelled_by": cancelled_by} if cancelled_by else {},
                },
            )
        )

    def update_task_metadata(
        self, task_id: str, metadata: dict[str, object]
    ) -> TaskRecord:
        """整体替换指定任务的 metadata 字段并持久化。

        参数：
        - task_id：任务 id。
        - metadata：新的完整 metadata 字典。

        返回：
        - 更新后的 TaskRecord。
        """

        with self._open_unit_of_work() as unit_of_work:
            task_record = unit_of_work.tasks.get_task(task_id)
            if task_record is None:
                raise ResourceNotFoundError(
                    "找不到指定的任务",
                    details={"task_id": task_id},
                )
            updated_task = replace(task_record, metadata=dict(metadata))
            unit_of_work.tasks.save_task(updated_task)
            unit_of_work.commit()
        return updated_task

    def update_task_spec_and_metadata(
        self,
        task_id: str,
        *,
        task_spec: dict[str, object],
        metadata: dict[str, object],
    ) -> TaskRecord:
        """整体替换指定任务的 task_spec 与 metadata 字段并持久化。

        参数：
        - task_id：任务 id。
        - task_spec：新的完整 task_spec 字典。
        - metadata：新的完整 metadata 字典。

        返回：
        - 更新后的 TaskRecord。
        """

        with self._open_unit_of_work() as unit_of_work:
            task_record = unit_of_work.tasks.get_task(task_id)
            if task_record is None:
                raise ResourceNotFoundError(
                    "找不到指定的任务",
                    details={"task_id": task_id},
                )
            updated_task = replace(
                task_record,
                task_spec=dict(task_spec),
                metadata=dict(metadata),
            )
            unit_of_work.tasks.save_task(updated_task)
            unit_of_work.commit()
        return updated_task

    def delete_task(self, task_id: str) -> None:
        """删除一条任务记录及其关联尝试、事件。

        参数：
        - task_id：任务 id。
        """

        with self._open_unit_of_work() as unit_of_work:
            task_record = unit_of_work.tasks.get_task(task_id)
            if task_record is None:
                raise ResourceNotFoundError(
                    "找不到指定的任务",
                    details={"task_id": task_id},
                )
            unit_of_work.tasks.delete_task(task_id)
            unit_of_work.commit()

    def _validate_create_request(self, request: CreateTaskRequest) -> None:
        """校验创建任务请求。"""

        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not request.task_kind.strip():
            raise InvalidRequestError("task_kind 不能为空")

    def _task_matches_filters(
        self, task_record: TaskRecord, filters: TaskQueryFilters
    ) -> bool:
        """判断任务是否满足筛选条件。"""

        if filters.task_kind is not None and task_record.task_kind != filters.task_kind:
            return False
        if filters.state is not None and task_record.state != filters.state:
            return False
        if (
            filters.worker_pool is not None
            and task_record.worker_pool != filters.worker_pool
        ):
            return False
        if (
            filters.created_by is not None
            and task_record.created_by != filters.created_by
        ):
            return False
        if (
            filters.parent_task_id is not None
            and task_record.parent_task_id != filters.parent_task_id
        ):
            return False
        if (
            filters.dataset_id is not None
            and task_record.task_spec.get("dataset_id") != filters.dataset_id
        ):
            return False
        if filters.source_import_id is not None:
            source_import_id = task_record.task_spec.get("dataset_import_id")
            if source_import_id is None:
                source_import_id = task_record.metadata.get("source_import_id")
            if source_import_id != filters.source_import_id:
                return False

        return True

    def _apply_event(
        self, *, task_record: TaskRecord, task_event: TaskEvent
    ) -> TaskRecord:
        """根据 TaskEvent 更新 TaskRecord 快照。"""

        payload = dict(task_event.payload)
        metadata = dict(task_record.metadata)
        progress = dict(task_record.progress)
        result = dict(task_record.result)
        state = task_record.state
        error_message = task_record.error_message
        started_at = task_record.started_at
        finished_at = task_record.finished_at
        current_attempt_no = task_record.current_attempt_no

        metadata_patch = payload.get("metadata")
        if isinstance(metadata_patch, dict):
            metadata.update(metadata_patch)

        progress_patch = payload.get("progress")
        if isinstance(progress_patch, dict):
            progress.update(progress_patch)
        elif task_event.event_type == "progress":
            progress.update(
                {
                    str(key): value
                    for key, value in payload.items()
                    if key
                    not in {
                        "state",
                        "metadata",
                        "result",
                        "error_message",
                        "finished_at",
                        "started_at",
                        "attempt_no",
                    }
                }
            )

        result_patch = payload.get("result")
        if isinstance(result_patch, dict):
            result.update(result_patch)
        elif task_event.event_type == "result":
            result.update(
                {
                    str(key): value
                    for key, value in payload.items()
                    if key
                    not in {
                        "state",
                        "metadata",
                        "progress",
                        "error_message",
                        "finished_at",
                        "started_at",
                        "attempt_no",
                    }
                }
            )

        payload_state = payload.get("state")
        if isinstance(payload_state, str):
            state = payload_state
        elif task_event.event_type == "progress" and task_record.state == "queued":
            state = "running"

        if "error_message" in payload:
            payload_error_message = payload.get("error_message")
            if payload_error_message is None or isinstance(payload_error_message, str):
                error_message = payload_error_message

        payload_attempt_no = payload.get("attempt_no")
        if isinstance(payload_attempt_no, int):
            current_attempt_no = payload_attempt_no

        payload_started_at = payload.get("started_at")
        if isinstance(payload_started_at, str):
            started_at = payload_started_at
        elif state == "running" and started_at is None:
            started_at = task_event.created_at

        if "finished_at" in payload:
            payload_finished_at = payload.get("finished_at")
            if payload_finished_at is None or isinstance(payload_finished_at, str):
                finished_at = payload_finished_at
        elif state in {"succeeded", "failed", "timed_out", "cancelled"}:
            finished_at = finished_at or task_event.created_at

        return replace(
            task_record,
            metadata=metadata,
            progress=progress,
            result=result,
            state=state,
            error_message=error_message,
            current_attempt_no=current_attempt_no,
            started_at=started_at,
            finished_at=finished_at,
        )

    def _publish_task_event(self, task_event: TaskEvent) -> None:
        """把 TaskEvent 发布到服务内事件总线。

        参数：
        - task_event：要发布的任务事件。
        """

        if self.service_event_bus is None:
            return

        self.service_event_bus.publish(
            ServiceEvent(
                stream="tasks.events",
                resource_kind="task",
                resource_id=task_event.task_id,
                event_type=task_event.event_type,
                event_version="v1",
                occurred_at=task_event.created_at,
                cursor=f"{task_event.created_at}|{task_event.event_id}",
                payload={
                    "event_id": task_event.event_id,
                    "task_id": task_event.task_id,
                    "attempt_id": task_event.attempt_id,
                    "message": task_event.message,
                    "data": dict(task_event.payload),
                },
            )
        )

    @contextmanager
    def _open_unit_of_work(self) -> Iterator[SqlAlchemyUnitOfWork]:
        """创建并管理一个请求级 Unit of Work。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            yield unit_of_work
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.close()

    def _now_iso(self) -> str:
        """返回当前 UTC 时间的 ISO 格式字符串。"""

        return datetime.now(timezone.utc).isoformat()

    def _next_id(self, prefix: str) -> str:
        """生成一个带前缀的新对象 id。"""

        return f"{prefix}-{uuid4().hex[:12]}"

    def _build_task_attempt_id(self, task_id: str, attempt_no: int) -> str:
        """按 Task id 与轮次生成跨 worker 稳定的 TaskAttempt id。"""

        digest = hashlib.sha256(f"{task_id}:{attempt_no}".encode("utf-8")).hexdigest()
        return f"task-attempt-{digest[:32]}"

    def _try_reclaim_recovered_attempt(
        self,
        *,
        unit_of_work: SqlAlchemyUnitOfWork,
        task_record: TaskRecord,
        existing_attempt: TaskAttempt,
        worker_id: str,
        queue_name: str,
        queue_message_id: str,
        queue_attempt_count: int,
        lease_recovery_count: int,
        heartbeat_at: str,
    ) -> TaskAttemptClaim | None:
        """只允许同一 queue message 在 lease 恢复后接管原 running attempt。"""

        if existing_attempt.state != "running" or lease_recovery_count <= 0:
            return None
        previous_message_id = existing_attempt.metadata.get("queue_message_id")
        previous_queue_attempt_count = existing_attempt.metadata.get(
            "queue_attempt_count"
        )
        if (
            previous_message_id != queue_message_id
            or isinstance(previous_queue_attempt_count, bool)
            or not isinstance(previous_queue_attempt_count, int)
            or queue_attempt_count <= previous_queue_attempt_count
        ):
            return None
        reclaimed_attempt = replace(
            existing_attempt,
            worker_id=worker_id,
            heartbeat_at=heartbeat_at,
            metadata={
                **existing_attempt.metadata,
                "operation_kind": "queue-consumption",
                "queue_name": queue_name,
                "queue_message_id": queue_message_id,
                "queue_attempt_count": queue_attempt_count,
                "lease_recovery_count": lease_recovery_count,
            },
        )
        if not unit_of_work.tasks.try_reclaim_running_task_attempt(
            reclaimed_attempt,
            expected_worker_id=existing_attempt.worker_id,
            expected_heartbeat_at=existing_attempt.heartbeat_at,
        ):
            return None
        if task_record.state in {
            "succeeded",
            "failed",
            "timed_out",
            "cancelled",
        }:
            # 业务终态已经发布但 worker 尚未结束 Attempt/提交 queue ACK 时，
            # recovery 只补齐 Attempt，不再重新进入训练、转换或验证 service。
            # 先通过上面的 lease CAS 取得 owner，再以同一 owner 完成终态，
            # 旧 worker 无法覆盖这次回收。
            finished_at = self._now_iso()
            finished_attempt = replace(
                reclaimed_attempt,
                state=task_record.state,
                heartbeat_at=finished_at,
                ended_at=finished_at,
                exit_code=0 if task_record.state == "succeeded" else 1,
                result={"task_result": dict(task_record.result)},
                error_message=task_record.error_message,
                metadata={
                    **reclaimed_attempt.metadata,
                    "finalized_from_terminal_task": True,
                },
            )
            if not unit_of_work.tasks.try_finish_running_task_attempt(
                finished_attempt,
                expected_worker_id=reclaimed_attempt.worker_id,
                expected_heartbeat_at=reclaimed_attempt.heartbeat_at,
            ):
                raise InvalidRequestError(
                    "恢复消息无法补齐已结束任务的 TaskAttempt",
                    details={
                        "task_id": task_record.task_id,
                        "attempt_id": existing_attempt.attempt_id,
                    },
                )
            unit_of_work.commit()
            return TaskAttemptClaim(
                outcome="task_finished",
                task=task_record,
                attempt=finished_attempt,
            )
        unit_of_work.commit()
        return TaskAttemptClaim(
            outcome="acquired",
            task=task_record,
            attempt=reclaimed_attempt,
        )

    @staticmethod
    def _is_finalization_recovery(
        *,
        task_record: TaskRecord,
        existing_attempt: TaskAttempt,
        queue_message_id: str,
        queue_attempt_count: int,
        lease_recovery_count: int,
    ) -> bool:
        """识别 Attempt 已结束但 Task 最终发布尚未完成的 crash 窗口。"""

        if (
            existing_attempt.state == "running"
            or task_record.state not in {"queued", "running"}
            or lease_recovery_count <= 0
        ):
            return False
        previous_message_id = existing_attempt.metadata.get("queue_message_id")
        previous_queue_attempt_count = existing_attempt.metadata.get(
            "queue_attempt_count"
        )
        return (
            previous_message_id == queue_message_id
            and not isinstance(previous_queue_attempt_count, bool)
            and isinstance(previous_queue_attempt_count, int)
            and queue_attempt_count > previous_queue_attempt_count
        )
