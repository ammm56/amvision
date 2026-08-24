"""统一任务应用服务。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import logging
from typing import Literal
from uuid import NAMESPACE_URL, uuid4, uuid5

from backend.service.application.events.event_bus import ServiceEvent
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
)
from backend.service.application.project_mutation import ProjectMutationAdmissionService
from backend.service.application.conversions.task_kinds import CONVERSION_TASK_KINDS
from backend.service.application.tasks.queue_outbox import (
    build_queue_outbox_message,
    build_task_resume_queue_message_id,
)
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


LOGGER = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class ResumeTaskRequest:
    """描述 Task 恢复与队列 outbox 原子提交请求。"""

    task_id: str
    expected_states: tuple[TaskRecordState, ...]
    expected_current_attempt_no: int
    queue_submission: TaskQueueSubmission
    expected_checkpoint_object_key: str | None = None
    progress_patch: dict[str, object] = field(default_factory=dict)
    result_patch: dict[str, object] = field(default_factory=dict)
    metadata_patch: dict[str, object] = field(default_factory=dict)
    message: str = "task resume queued"
    event_type: TaskEventType = "status"
    event_id: str | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class ResumeTaskSubmission:
    """描述已经原子持久化的 Task 恢复和队列引用。"""

    task: TaskRecord
    event: TaskEvent
    queue_name: str
    queue_task_id: str


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

        return self.outcome == "acquired"


@dataclass(frozen=True)
class TaskExecutionFinalization:
    """描述 Task 与当前 TaskAttempt 经统一 finalizer 收敛后的结果。"""

    task: TaskRecord
    attempt: TaskAttempt
    event: TaskEvent | None = None


@dataclass(frozen=True)
class TaskExecutionFence:
    """描述运行中 TaskAttempt 的 queue lease 写入边界。"""

    attempt_id: str
    worker_id: str
    heartbeat_at: str | None
    queue_message_id: str
    queue_attempt_count: int


@dataclass(frozen=True)
class ConversionPublicationReservation:
    """描述由当前 Conversion Attempt 持有的数据库发布 reservation。"""

    task_id: str
    attempt_no: int
    publication_state: str
    publication_token: str
    publication_updated_at: str


@dataclass(frozen=True)
class ConversionPublicationCommitPayload:
    """描述 Conversion 业务记录已暂存后需要一并提交的 Task 结果。"""

    business_result: object
    task_result: dict[str, object]
    attempt_result: dict[str, object]
    event_message: str
    event_payload: dict[str, object]


def read_task_execution_fence(
    metadata: dict[str, object],
) -> TaskExecutionFence | None:
    """从同进程执行元数据中严格读取 TaskAttempt queue fence。"""

    payload = metadata.get("task_execution_fence")
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise InvalidRequestError("task_execution_fence 必须是对象")
    attempt_id = payload.get("attempt_id")
    worker_id = payload.get("worker_id")
    queue_message_id = payload.get("queue_message_id")
    queue_attempt_count = payload.get("queue_attempt_count")
    if not isinstance(attempt_id, str) or not attempt_id.strip():
        raise InvalidRequestError("task_execution_fence 缺少 attempt_id")
    if not isinstance(worker_id, str) or not worker_id.strip():
        raise InvalidRequestError("task_execution_fence 缺少 worker_id")
    if not isinstance(queue_message_id, str) or not queue_message_id.strip():
        raise InvalidRequestError("task_execution_fence 缺少 queue_message_id")
    if (
        isinstance(queue_attempt_count, bool)
        or not isinstance(queue_attempt_count, int)
        or queue_attempt_count <= 0
    ):
        raise InvalidRequestError("task_execution_fence 缺少有效 queue_attempt_count")
    return TaskExecutionFence(
        attempt_id=attempt_id.strip(),
        worker_id=worker_id.strip(),
        heartbeat_at=None,
        queue_message_id=queue_message_id.strip(),
        queue_attempt_count=queue_attempt_count,
    )


@dataclass(frozen=True)
class RecordTaskProgressRequest:
    """描述一次带 Attempt fence 的运行中进度 patch。"""

    task_id: str
    fence: TaskExecutionFence
    progress: dict[str, object] = field(default_factory=dict)
    result: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    event_type: TaskEventType = "progress"
    event_payload: dict[str, object] = field(default_factory=dict)
    message: str = "task progress updated"
    event_id: str | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class TaskStateCommandRequest:
    """描述一次显式 Task 状态命令及其字段级 patch。"""

    task_id: str
    target_state: TaskRecordState
    expected_states: tuple[TaskRecordState, ...]
    expected_current_attempt_no: int
    target_current_attempt_no: int | None = None
    attempt_id: str | None = None
    fence: TaskExecutionFence | None = None
    progress_patch: dict[str, object] = field(default_factory=dict)
    result_patch: dict[str, object] = field(default_factory=dict)
    metadata_patch: dict[str, object] = field(default_factory=dict)
    error_message: str | None = None
    message: str = ""
    event_type: TaskEventType = "status"
    event_id: str | None = None
    created_at: str | None = None


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

    def resume_task_with_outbox(
        self,
        request: ResumeTaskRequest,
    ) -> ResumeTaskSubmission:
        """以 CAS 将 Task 恢复为 queued，并在同一事务写入队列 outbox。"""

        if not request.task_id.strip():
            raise InvalidRequestError("恢复 Task 时 task_id 不能为空")
        if not request.expected_states or not set(request.expected_states) <= {
            "paused",
            "failed",
        }:
            raise InvalidRequestError("恢复 Task 只接受 paused/failed 预期状态")
        if request.expected_current_attempt_no < 0:
            raise InvalidRequestError(
                "恢复 Task 时 expected_current_attempt_no 不能小于 0"
            )

        created_at = request.created_at or self._now_iso()
        next_attempt_no = request.expected_current_attempt_no + 1
        queue_payload = dict(request.queue_submission.payload)
        payload_task_id = queue_payload.setdefault("task_id", request.task_id)
        if payload_task_id != request.task_id:
            raise InvalidRequestError(
                "恢复队列消息 task_id 与 Task 不一致",
                details={
                    "task_id": request.task_id,
                    "queue_payload_task_id": payload_task_id,
                },
            )
        payload_attempt_no = queue_payload.setdefault("attempt_no", next_attempt_no)
        if (
            isinstance(payload_attempt_no, bool)
            or not isinstance(payload_attempt_no, int)
            or payload_attempt_no != next_attempt_no
        ):
            raise InvalidRequestError(
                "恢复队列消息 attempt_no 与 Task 下一轮次不一致",
                details={
                    "task_id": request.task_id,
                    "expected_attempt_no": next_attempt_no,
                    "queue_payload_attempt_no": payload_attempt_no,
                },
            )

        queue_message_id = request.queue_submission.message_id or (
            build_task_resume_queue_message_id(
                task_id=request.task_id,
                attempt_no=next_attempt_no,
            )
        )
        queue_message = build_queue_outbox_message(
            message_id=queue_message_id,
            queue_name=request.queue_submission.queue_name,
            payload=queue_payload,
            metadata=request.queue_submission.metadata,
            created_at=created_at,
        )
        initial_task = self.get_task(request.task_id).task
        with self.project_mutations.operation(
            project_id=initial_task.project_id,
            mutation_kind="task-resume",
            resource_id=request.task_id,
        ):
            with self._open_unit_of_work() as unit_of_work:
                task_record = unit_of_work.tasks.get_task(request.task_id)
                if task_record is None:
                    raise ResourceNotFoundError(
                        "找不到指定的任务",
                        details={"task_id": request.task_id},
                    )
                if request.expected_checkpoint_object_key is not None:
                    checkpoint_references = self._collect_checkpoint_references(
                        task_record
                    )
                    if (
                        request.expected_checkpoint_object_key
                        not in checkpoint_references
                    ):
                        raise InvalidRequestError(
                            "Task 的可恢复 checkpoint 已发生变化",
                            details={
                                "task_id": request.task_id,
                                "expected_checkpoint_object_key": (
                                    request.expected_checkpoint_object_key
                                ),
                            },
                        )
                progress = {
                    **task_record.progress,
                    **dict(request.progress_patch),
                }
                result = {
                    **task_record.result,
                    **dict(request.result_patch),
                    "queue_name": queue_message.queue_name,
                    "queue_task_id": queue_message.message_id,
                }
                metadata = {
                    **task_record.metadata,
                    **dict(request.metadata_patch),
                    "queue_name": queue_message.queue_name,
                    "queue_task_id": queue_message.message_id,
                }
                updated_task = replace(
                    task_record,
                    state="queued",
                    finished_at=None,
                    error_message=None,
                    progress=progress,
                    result=result,
                    metadata=metadata,
                )
                if not unit_of_work.tasks.try_transition_task(
                    request.task_id,
                    expected_states=request.expected_states,
                    expected_current_attempt_no=request.expected_current_attempt_no,
                    field_patch={
                        "state": "queued",
                        "finished_at": None,
                        "error_message": None,
                        "progress_json": progress,
                        "result_json": result,
                        "metadata_json": metadata,
                    },
                ):
                    raise InvalidRequestError(
                        "Task 已由其他命令推进，恢复请求未生效",
                        details={
                            "task_id": request.task_id,
                            "expected_states": list(request.expected_states),
                            "expected_current_attempt_no": (
                                request.expected_current_attempt_no
                            ),
                        },
                    )
                event = TaskEvent(
                    event_id=request.event_id
                    or self._build_command_event_id(
                        request.task_id,
                        next_attempt_no,
                        "resume-queued",
                    ),
                    task_id=request.task_id,
                    event_type=request.event_type,
                    created_at=created_at,
                    message=request.message,
                    payload={
                        "state": "queued",
                        "attempt_no": next_attempt_no,
                        "progress": dict(request.progress_patch),
                        "result": {
                            **dict(request.result_patch),
                            "queue_name": queue_message.queue_name,
                            "queue_task_id": queue_message.message_id,
                        },
                        "metadata": {
                            **dict(request.metadata_patch),
                            "queue_name": queue_message.queue_name,
                            "queue_task_id": queue_message.message_id,
                        },
                        "error_message": None,
                        "finished_at": None,
                    },
                )
                unit_of_work.tasks.save_task_event(event)
                unit_of_work.queue_outbox.add_message(queue_message)
                unit_of_work.commit()

        self._publish_task_event(event)
        return ResumeTaskSubmission(
            task=updated_task,
            event=event,
            queue_name=queue_message.queue_name,
            queue_task_id=queue_message.message_id,
        )

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
            task_record = unit_of_work.tasks.get_task(task_id)
            if task_record is None:
                raise ResourceNotFoundError(
                    "找不到指定的任务",
                    details={"task_id": task_id},
                )
            resolved_metadata = dict(metadata or {})
            if task_record.task_kind in CONVERSION_TASK_KINDS:
                from backend.service.application.conversions.deadline_policy import (
                    resolve_conversion_deadline_policy,
                    validate_conversion_attempt_deadline_metadata,
                )

                resolved_metadata.update(
                    resolve_conversion_deadline_policy(
                        task_record.task_spec
                    ).to_attempt_metadata(started_at=started_at)
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
                    if task_record.task_kind in CONVERSION_TASK_KINDS:
                        validate_conversion_attempt_deadline_metadata(
                            existing_attempt.metadata
                        )
                    return existing_attempt
                if task_record.task_kind in CONVERSION_TASK_KINDS:
                    validate_conversion_attempt_deadline_metadata(
                        existing_attempt.metadata
                    )
                    for key in (
                        "deadline_at",
                        "timeout_seconds",
                        "timeout_policy_source",
                        "timeout_target_formats",
                        "timeout_applied_override",
                    ):
                        resolved_metadata.pop(key, None)
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
                        **resolved_metadata,
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
                metadata=resolved_metadata,
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

    def claim_task_execution(
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
        queue_metadata: dict[str, object] | None = None,
    ) -> TaskAttemptClaim:
        """原子创建 Attempt、推进 Task 并记录唯一 started 事件。"""

        if not task_id.strip():
            raise InvalidRequestError("领取 TaskAttempt 时 task_id 不能为空")
        if attempt_no <= 0:
            raise InvalidRequestError("领取 TaskAttempt 时 attempt_no 必须大于 0")
        if not worker_id.strip():
            raise InvalidRequestError("领取 TaskAttempt 时 worker_id 不能为空")
        if queue_attempt_count <= 0:
            raise InvalidRequestError(
                "领取 TaskAttempt 时 queue_attempt_count 必须大于 0"
            )
        if not queue_leased_at.strip():
            raise InvalidRequestError("领取 TaskAttempt 时 queue_leased_at 不能为空")
        if lease_recovery_count < 0:
            raise InvalidRequestError(
                "领取 TaskAttempt 时 lease_recovery_count 不能小于 0"
            )

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
                    (item for item in task_attempts if item.attempt_no == attempt_no),
                    None,
                )
            latest_attempt_no = max(
                (item.attempt_no for item in task_attempts), default=0
            )
            if existing_attempt is not None:
                if task_record.task_kind in CONVERSION_TASK_KINDS:
                    from backend.service.application.conversions.deadline_policy import (
                        validate_conversion_attempt_deadline_metadata,
                    )

                    validate_conversion_attempt_deadline_metadata(
                        existing_attempt.metadata
                    )
                if attempt_no < task_record.current_attempt_no:
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
                if (
                    existing_attempt.state != "running"
                    and task_record.current_attempt_no == attempt_no
                    and task_record.state == existing_attempt.state
                ):
                    return TaskAttemptClaim(
                        outcome="finalization_recovery",
                        task=task_record,
                        attempt=existing_attempt,
                    )
                if existing_attempt.state != "running":
                    raise InvalidRequestError(
                        "Task 与 TaskAttempt 终态不一致，需要人工维护",
                        details={
                            "task_id": task_id,
                            "task_state": task_record.state,
                            "task_current_attempt_no": task_record.current_attempt_no,
                            "attempt_id": existing_attempt.attempt_id,
                            "attempt_state": existing_attempt.state,
                            "attempt_no": existing_attempt.attempt_no,
                        },
                    )
                if (
                    task_record.state != "running"
                    or task_record.current_attempt_no != attempt_no
                ):
                    # SQLite 并发读取可能在同一事务内看到新 Attempt、但仍持有
                    # claim 前的 Task 快照。结束当前读事务后从独立 Session 重读，
                    # 只把已经完整提交的 claim 识别为重复投递。
                    unit_of_work.rollback()
                    fresh_task = self.get_task(task_id).task
                    fresh_attempt = next(
                        (
                            item
                            for item in self.list_task_attempts(task_id)
                            if item.attempt_no == attempt_no
                        ),
                        None,
                    )
                    if (
                        fresh_attempt is not None
                        and fresh_attempt.state == "running"
                        and fresh_task.state == "running"
                        and fresh_task.current_attempt_no == attempt_no
                    ):
                        return TaskAttemptClaim(
                            outcome="duplicate_running",
                            task=fresh_task,
                            attempt=fresh_attempt,
                        )
                    raise InvalidRequestError(
                        "running TaskAttempt 与 Task 执行身份不一致",
                        details={
                            "task_id": task_id,
                            "task_state": task_record.state,
                            "task_current_attempt_no": task_record.current_attempt_no,
                            "attempt_no": attempt_no,
                        },
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

            if task_record.state != "queued":
                return TaskAttemptClaim(
                    outcome="task_finished",
                    task=task_record,
                )
            if latest_attempt_no != task_record.current_attempt_no:
                raise InvalidRequestError(
                    "Task 当前轮次与已持久化 Attempt 不一致",
                    details={
                        "task_id": task_id,
                        "current_attempt_no": task_record.current_attempt_no,
                        "latest_attempt_no": latest_attempt_no,
                    },
                )
            expected_attempt_no = task_record.current_attempt_no + 1
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

            attempt_metadata: dict[str, object] = {
                "operation_kind": "queue-consumption",
                "queue_name": queue_name,
                "queue_message_id": queue_message_id,
                "queue_attempt_count": queue_attempt_count,
                "lease_recovery_count": lease_recovery_count,
            }
            if task_record.task_kind in CONVERSION_TASK_KINDS:
                from backend.service.application.conversions.deadline_policy import (
                    resolve_conversion_deadline_policy,
                    validate_queue_conversion_target_formats,
                )

                deadline_policy = resolve_conversion_deadline_policy(
                    task_record.task_spec
                )
                validate_queue_conversion_target_formats(
                    policy=deadline_policy,
                    queue_metadata=queue_metadata,
                )
                attempt_metadata.update(
                    deadline_policy.to_attempt_metadata(started_at=started_at)
                )
            candidate = TaskAttempt(
                attempt_id=self._build_task_attempt_id(task_id, attempt_no),
                task_id=task_id,
                attempt_no=attempt_no,
                worker_id=worker_id,
                state="running",
                started_at=started_at,
                heartbeat_at=queue_leased_at,
                metadata=attempt_metadata,
            )
            updated_task = replace(
                task_record,
                state="running",
                current_attempt_no=attempt_no,
                started_at=task_record.started_at or started_at,
                finished_at=None,
                error_message=None,
            )
            if not unit_of_work.tasks.try_transition_task(
                task_id,
                expected_states=("queued",),
                expected_current_attempt_no=task_record.current_attempt_no,
                field_patch={
                    "state": "running",
                    "current_attempt_no": attempt_no,
                    "started_at": updated_task.started_at,
                    "finished_at": None,
                    "error_message": None,
                },
            ):
                unit_of_work.rollback()
                unit_of_work.session.expire_all()
                winning_task = unit_of_work.tasks.get_task(task_id)
                winning_attempt = unit_of_work.tasks.get_task_attempt_by_number(
                    task_id,
                    attempt_no,
                )
                if winning_task is None or winning_attempt is None:
                    raise InvalidRequestError(
                        "Task 执行权已被其他命令取得",
                        details={"task_id": task_id, "attempt_no": attempt_no},
                    )
                return TaskAttemptClaim(
                    outcome=(
                        "duplicate_running"
                        if winning_attempt.state == "running"
                        else "duplicate_finished"
                    ),
                    task=winning_task,
                    attempt=winning_attempt,
                )
            if not unit_of_work.tasks.try_create_task_attempt(candidate):
                raise InvalidRequestError(
                    "Task CAS 成功但 TaskAttempt 创建失败",
                    details={"task_id": task_id, "attempt_no": attempt_no},
                )
            started_event = TaskEvent(
                event_id=self._build_command_event_id(
                    task_id,
                    attempt_no,
                    "running",
                ),
                task_id=task_id,
                attempt_id=candidate.attempt_id,
                event_type="status",
                created_at=started_at,
                message="task execution started",
                payload={
                    "state": "running",
                    "attempt_no": attempt_no,
                    "started_at": updated_task.started_at,
                },
            )
            unit_of_work.tasks.save_task_event(started_event)
            unit_of_work.commit()
            self._publish_task_event(started_event)
            return TaskAttemptClaim(
                outcome="acquired",
                task=updated_task,
                attempt=candidate,
            )

    def begin_conversion_publication(
        self,
        *,
        task_id: str,
        fence: TaskExecutionFence,
        publication_token: str,
        updated_at: str | None = None,
    ) -> ConversionPublicationReservation:
        """为当前 Conversion Attempt 原子取得数据库 publication reservation。"""

        normalized_token = publication_token.strip()
        if not normalized_token or len(normalized_token) > 64:
            raise InvalidRequestError("Conversion publication token 不合法")
        resolved_updated_at = updated_at or self._now_iso()
        with self._open_unit_of_work() as unit_of_work:
            task_record = unit_of_work.tasks.get_task(task_id)
            if task_record is None:
                raise ResourceNotFoundError(
                    "找不到指定的任务",
                    details={"task_id": task_id},
                )
            if task_record.task_kind not in CONVERSION_TASK_KINDS:
                raise InvalidRequestError(
                    "只有 Conversion Task 可以取得 publication reservation",
                    details={"task_id": task_id, "task_kind": task_record.task_kind},
                )
            attempt = unit_of_work.tasks.get_task_attempt(fence.attempt_id)
            self._validate_running_attempt_fence(
                task_record=task_record,
                attempt=attempt,
                fence=fence,
            )
            assert attempt is not None
            if task_record.publication_state is not None:
                if (
                    task_record.publication_state == "reserved"
                    and task_record.publication_attempt_no == attempt.attempt_no
                    and task_record.publication_token == normalized_token
                    and task_record.publication_updated_at is not None
                ):
                    return ConversionPublicationReservation(
                        task_id=task_id,
                        attempt_no=attempt.attempt_no,
                        publication_state="reserved",
                        publication_token=normalized_token,
                        publication_updated_at=task_record.publication_updated_at,
                    )
                raise InvalidRequestError(
                    "Conversion publication 已由其他提交者保留",
                    details={
                        "task_id": task_id,
                        "publication_state": task_record.publication_state,
                        "publication_attempt_no": task_record.publication_attempt_no,
                    },
                )
            if not unit_of_work.tasks.try_begin_conversion_publication(
                task_id,
                expected_current_attempt_no=attempt.attempt_no,
                publication_token=normalized_token,
                publication_updated_at=resolved_updated_at,
            ):
                raise InvalidRequestError(
                    "Conversion publication reservation CAS 失败",
                    details={"task_id": task_id, "attempt_no": attempt.attempt_no},
                )
            unit_of_work.commit()
        return ConversionPublicationReservation(
            task_id=task_id,
            attempt_no=attempt.attempt_no,
            publication_state="reserved",
            publication_token=normalized_token,
            publication_updated_at=resolved_updated_at,
        )

    def transition_conversion_publication(
        self,
        *,
        task_id: str,
        attempt_no: int,
        publication_token: str,
        expected_state: str,
        target_state: str,
        updated_at: str | None = None,
    ) -> ConversionPublicationReservation:
        """按 token、Attempt 与当前状态 fence 推进内部 publication 状态。"""

        allowed_transitions = {
            "reserved": {"published", "aborted"},
            "published": {"registered"},
        }
        if target_state not in allowed_transitions.get(expected_state, set()):
            raise InvalidRequestError(
                "Conversion publication 状态转换不合法",
                details={
                    "expected_state": expected_state,
                    "target_state": target_state,
                },
            )
        normalized_token = publication_token.strip()
        if not normalized_token or len(normalized_token) > 64 or attempt_no <= 0:
            raise InvalidRequestError("Conversion publication fence 不合法")
        resolved_updated_at = updated_at or self._now_iso()
        with self._open_unit_of_work() as unit_of_work:
            task_record = unit_of_work.tasks.get_task(task_id)
            if task_record is None:
                raise ResourceNotFoundError(
                    "找不到指定的任务",
                    details={"task_id": task_id},
                )
            if (
                task_record.publication_state == target_state
                and task_record.publication_attempt_no == attempt_no
                and task_record.publication_token == normalized_token
                and task_record.publication_updated_at is not None
            ):
                return ConversionPublicationReservation(
                    task_id=task_id,
                    attempt_no=attempt_no,
                    publication_state=target_state,
                    publication_token=normalized_token,
                    publication_updated_at=task_record.publication_updated_at,
                )
            if not unit_of_work.tasks.try_transition_conversion_publication(
                task_id,
                expected_task_states=("running",),
                expected_current_attempt_no=attempt_no,
                expected_publication_state=expected_state,
                publication_token=normalized_token,
                target_publication_state=target_state,
                publication_updated_at=resolved_updated_at,
            ):
                raise InvalidRequestError(
                    "Conversion publication 状态 CAS 失败",
                    details={
                        "task_id": task_id,
                        "attempt_no": attempt_no,
                        "expected_state": expected_state,
                        "target_state": target_state,
                    },
                )
            unit_of_work.commit()
        return ConversionPublicationReservation(
            task_id=task_id,
            attempt_no=attempt_no,
            publication_state=target_state,
            publication_token=normalized_token,
            publication_updated_at=resolved_updated_at,
        )

    def require_conversion_publication_reservation(
        self,
        *,
        task_id: str,
        fence: TaskExecutionFence,
        publication_token: str,
    ) -> ConversionPublicationReservation:
        """在原子 rename 前重新核验 reservation 与当前 Attempt owner。"""

        normalized_token = publication_token.strip()
        with self._open_unit_of_work() as unit_of_work:
            task_record = unit_of_work.tasks.get_task(task_id)
            if task_record is None:
                raise ResourceNotFoundError(
                    "找不到指定的任务",
                    details={"task_id": task_id},
                )
            attempt = unit_of_work.tasks.get_task_attempt(fence.attempt_id)
            self._validate_running_attempt_fence(
                task_record=task_record,
                attempt=attempt,
                fence=fence,
            )
            assert attempt is not None
            if (
                task_record.publication_state != "reserved"
                or task_record.publication_token != normalized_token
                or task_record.publication_attempt_no != attempt.attempt_no
                or task_record.publication_updated_at is None
            ):
                raise InvalidRequestError(
                    "Conversion publication reservation 已失效",
                    details={
                        "task_id": task_id,
                        "attempt_no": attempt.attempt_no,
                        "publication_state": task_record.publication_state,
                    },
                )
            return ConversionPublicationReservation(
                task_id=task_id,
                attempt_no=attempt.attempt_no,
                publication_state="reserved",
                publication_token=normalized_token,
                publication_updated_at=task_record.publication_updated_at,
            )

    def complete_conversion_publication(
        self,
        *,
        task_id: str,
        fence: TaskExecutionFence,
        publication_token: str,
        stage_business_records: Callable[
            [SqlAlchemyUnitOfWork], ConversionPublicationCommitPayload
        ],
    ) -> ConversionPublicationCommitPayload:
        """单 UoW 登记业务记录、Task/Attempt 成功和 registered reservation。"""

        normalized_token = publication_token.strip()
        finished_at = self._now_iso()
        with self._open_unit_of_work() as unit_of_work:
            task_record = unit_of_work.tasks.get_task(task_id)
            if task_record is None:
                raise ResourceNotFoundError(
                    "找不到指定的任务",
                    details={"task_id": task_id},
                )
            attempt = unit_of_work.tasks.get_task_attempt(fence.attempt_id)
            self._validate_running_attempt_fence(
                task_record=task_record,
                attempt=attempt,
                fence=fence,
            )
            assert attempt is not None
            if (
                task_record.task_kind not in CONVERSION_TASK_KINDS
                or task_record.publication_state != "published"
                or task_record.publication_token != normalized_token
                or task_record.publication_attempt_no != attempt.attempt_no
            ):
                raise InvalidRequestError(
                    "Conversion publication 尚未进入可登记状态",
                    details={
                        "task_id": task_id,
                        "publication_state": task_record.publication_state,
                    },
                )
            completion = stage_business_records(unit_of_work)
            if not unit_of_work.tasks.try_complete_conversion_publication(
                task_id,
                expected_current_attempt_no=attempt.attempt_no,
                publication_token=normalized_token,
                publication_updated_at=finished_at,
                finished_at=finished_at,
                progress={"stage": "succeeded", "percent": 100.0},
                result=completion.task_result,
            ):
                raise InvalidRequestError(
                    "Conversion publication 与 Task 成功终态 CAS 失败",
                    details={"task_id": task_id},
                )
            finished_attempt = replace(
                attempt,
                state="succeeded",
                heartbeat_at=finished_at,
                ended_at=finished_at,
                exit_code=0,
                result=dict(completion.attempt_result),
                error_message=None,
                metadata={
                    **attempt.metadata,
                    "publication_token": normalized_token,
                },
            )
            if not unit_of_work.tasks.try_finish_running_task_attempt(
                finished_attempt,
                expected_worker_id=attempt.worker_id,
                expected_heartbeat_at=attempt.heartbeat_at,
            ):
                raise InvalidRequestError(
                    "Conversion TaskAttempt 成功终态 CAS 失败",
                    details={"attempt_id": attempt.attempt_id},
                )
            terminal_event = TaskEvent(
                event_id=self._build_command_event_id(
                    task_id,
                    attempt.attempt_no,
                    "succeeded",
                ),
                task_id=task_id,
                attempt_id=attempt.attempt_id,
                event_type="result",
                created_at=finished_at,
                message=completion.event_message,
                payload={
                    **completion.event_payload,
                    "state": "succeeded",
                    "finished_at": finished_at,
                    "attempt_no": attempt.attempt_no,
                },
            )
            unit_of_work.tasks.save_task_event(terminal_event)
            unit_of_work.commit()
        self._publish_task_event(terminal_event)
        return completion

    def finalize_task_execution_attempt(
        self,
        *,
        attempt_id: str,
        attempt_outcome: TaskAttemptState,
        result: dict[str, object] | None,
        error_message: str | None,
        metadata: dict[str, object] | None,
        expected_worker_id: str,
        expected_heartbeat_at: str | None,
        expected_queue_message_id: str,
        expected_queue_attempt_count: int,
        exit_code: int | None = None,
        progress: dict[str, object] | None = None,
        event_type: TaskEventType = "result",
        message: str | None = None,
        event_id: str | None = None,
        finished_at: str | None = None,
    ) -> TaskExecutionFinalization:
        """在一个事务中核验 lease fence 并收敛 Task/Attempt 终态。"""

        if attempt_outcome == "running":
            raise InvalidRequestError("TaskAttempt finalizer 不接受 running 结果")
        if not expected_worker_id.strip():
            raise InvalidRequestError("TaskAttempt finalizer 缺少 worker fence")
        if expected_heartbeat_at is not None and not expected_heartbeat_at.strip():
            raise InvalidRequestError("TaskAttempt finalizer heartbeat fence 不合法")
        if not expected_queue_message_id.strip() or expected_queue_attempt_count <= 0:
            raise InvalidRequestError("TaskAttempt finalizer 缺少 queue lease fence")

        event: TaskEvent | None = None
        with self._open_unit_of_work() as unit_of_work:
            attempt = unit_of_work.tasks.get_task_attempt(attempt_id)
            if attempt is None:
                raise ResourceNotFoundError(
                    "找不到指定的 TaskAttempt",
                    details={"attempt_id": attempt_id},
                )
            task_record = unit_of_work.tasks.get_task(attempt.task_id)
            if task_record is None:
                raise ResourceNotFoundError(
                    "找不到 TaskAttempt 对应的任务",
                    details={"attempt_id": attempt_id, "task_id": attempt.task_id},
                )
            if attempt.state != "running":
                if (
                    attempt.state != attempt_outcome
                    or task_record.current_attempt_no != attempt.attempt_no
                    or task_record.state != attempt.state
                ):
                    raise InvalidRequestError(
                        "TaskAttempt 已由其他终态命令收敛",
                        details={
                            "attempt_id": attempt_id,
                            "attempt_state": attempt.state,
                            "requested_state": attempt_outcome,
                            "task_state": task_record.state,
                        },
                    )
                # 终态 Attempt 的 heartbeat 已更新为结束时刻；重复 queue ack 只需
                # 核验不可变 Worker/queue 身份，不再用运行期 heartbeat 拒绝幂等确认。
                self._validate_attempt_lease_fence(
                    attempt=attempt,
                    expected_worker_id=expected_worker_id,
                    expected_heartbeat_at=None,
                    expected_queue_message_id=expected_queue_message_id,
                    expected_queue_attempt_count=expected_queue_attempt_count,
                )
                return TaskExecutionFinalization(task=task_record, attempt=attempt)

            self._validate_attempt_lease_fence(
                attempt=attempt,
                expected_worker_id=expected_worker_id,
                expected_heartbeat_at=expected_heartbeat_at,
                expected_queue_message_id=expected_queue_message_id,
                expected_queue_attempt_count=expected_queue_attempt_count,
            )
            if (
                attempt_outcome == "succeeded"
                and task_record.task_kind in CONVERSION_TASK_KINDS
                and task_record.publication_state != "registered"
            ):
                raise InvalidRequestError(
                    "Conversion 必须完成 publication 登记后才能进入成功终态",
                    details={
                        "task_id": task_record.task_id,
                        "publication_state": task_record.publication_state,
                    },
                )

            resolved_finished_at = finished_at or self._now_iso()
            updated_attempt = replace(
                attempt,
                state=attempt_outcome,
                heartbeat_at=attempt.heartbeat_at,
                ended_at=resolved_finished_at,
                exit_code=exit_code,
                result=dict(result or {}),
                error_message=error_message,
                metadata={**attempt.metadata, **dict(metadata or {})},
            )
            if not unit_of_work.tasks.try_finish_running_task_attempt(
                updated_attempt,
                expected_worker_id=expected_worker_id,
                expected_heartbeat_at=attempt.heartbeat_at,
            ):
                raise InvalidRequestError(
                    "当前 Worker 已失去 TaskAttempt 终态写入权",
                    details={"attempt_id": attempt_id},
                )

            # Queue ack 阶段可能再次提交同一 finalizer；匹配终态只返回既有事实。
            if (
                task_record.state == attempt_outcome
                and task_record.current_attempt_no == attempt.attempt_no
            ):
                unit_of_work.commit()
                return TaskExecutionFinalization(
                    task=task_record,
                    attempt=updated_attempt,
                )
            if (
                task_record.state != "running"
                or task_record.current_attempt_no != attempt.attempt_no
            ):
                raise InvalidRequestError(
                    "Task 已由竞争命令推进，不能提交当前 Attempt 终态",
                    details={
                        "task_id": task_record.task_id,
                        "task_state": task_record.state,
                        "task_current_attempt_no": task_record.current_attempt_no,
                        "attempt_no": attempt.attempt_no,
                    },
                )

            result_payload = {**task_record.result, **dict(result or {})}
            progress_payload = {**task_record.progress, **dict(progress or {})}
            metadata_payload = {**task_record.metadata, **dict(metadata or {})}
            updated_task = replace(
                task_record,
                state=attempt_outcome,
                finished_at=resolved_finished_at,
                progress=progress_payload,
                result=result_payload,
                error_message=error_message,
                metadata=metadata_payload,
            )
            if not unit_of_work.tasks.try_transition_task(
                task_record.task_id,
                expected_states=("running",),
                expected_current_attempt_no=attempt.attempt_no,
                field_patch={
                    "state": attempt_outcome,
                    "finished_at": resolved_finished_at,
                    "progress_json": progress_payload,
                    "result_json": result_payload,
                    "error_message": error_message,
                    "metadata_json": metadata_payload,
                },
            ):
                raise InvalidRequestError(
                    "Task 终态 CAS 失败",
                    details={
                        "task_id": task_record.task_id,
                        "attempt_no": attempt.attempt_no,
                    },
                )
            event = TaskEvent(
                event_id=event_id
                or self._build_command_event_id(
                    task_record.task_id,
                    attempt.attempt_no,
                    attempt_outcome,
                ),
                task_id=task_record.task_id,
                attempt_id=attempt.attempt_id,
                event_type=event_type,
                created_at=resolved_finished_at,
                message=message or f"task execution {attempt_outcome}",
                payload={
                    "state": attempt_outcome,
                    "attempt_no": attempt.attempt_no,
                    "finished_at": resolved_finished_at,
                    "progress": progress_payload,
                    "result": result_payload,
                    "error_message": error_message,
                    "metadata": dict(metadata or {}),
                },
            )
            unit_of_work.tasks.save_task_event(event)
            unit_of_work.commit()

        if event is not None:
            self._publish_task_event(event)
        return TaskExecutionFinalization(
            task=updated_task,
            attempt=updated_attempt,
            event=event,
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

    def record_task_progress(
        self,
        request: RecordTaskProgressRequest,
    ) -> TaskDetail:
        """在当前 Attempt lease fence 内原子 patch Task 进度并追加事件。"""

        if not request.task_id.strip():
            raise InvalidRequestError("记录任务进度时 task_id 不能为空")
        if not request.progress and not request.result and not request.metadata:
            raise InvalidRequestError("记录任务进度时至少需要一个字段 patch")

        created_at = request.created_at or self._now_iso()
        event = TaskEvent(
            event_id=request.event_id or self._next_id("task-event"),
            task_id=request.task_id,
            attempt_id=request.fence.attempt_id,
            event_type=request.event_type,
            created_at=created_at,
            message=request.message,
            payload={
                **dict(request.event_payload),
                "progress": dict(request.progress),
                "result": dict(request.result),
                "metadata": dict(request.metadata),
            },
        )
        with self._open_unit_of_work() as unit_of_work:
            task_record = unit_of_work.tasks.get_task(request.task_id)
            if task_record is None:
                raise ResourceNotFoundError(
                    "找不到指定的任务",
                    details={"task_id": request.task_id},
                )
            attempt = unit_of_work.tasks.get_task_attempt(request.fence.attempt_id)
            self._validate_running_attempt_fence(
                task_record=task_record,
                attempt=attempt,
                fence=request.fence,
            )
            updated_progress = {**task_record.progress, **dict(request.progress)}
            updated_result = {**task_record.result, **dict(request.result)}
            updated_metadata = {**task_record.metadata, **dict(request.metadata)}
            updated_task = replace(
                task_record,
                progress=updated_progress,
                result=updated_result,
                metadata=updated_metadata,
            )
            if not unit_of_work.tasks.try_transition_task(
                request.task_id,
                expected_states=("running",),
                expected_current_attempt_no=attempt.attempt_no,
                field_patch={
                    "progress_json": updated_progress,
                    "result_json": updated_result,
                    "metadata_json": updated_metadata,
                },
            ):
                raise InvalidRequestError(
                    "Task 已由其他命令推进，进度未写入",
                    details={
                        "task_id": request.task_id,
                        "attempt_id": attempt.attempt_id,
                    },
                )
            unit_of_work.tasks.save_task_event(event)
            unit_of_work.commit()

        self._publish_task_event(event)
        return TaskDetail(task=updated_task, events=(event,))

    def record_task_progress_event(
        self,
        request: AppendTaskEventRequest,
        *,
        fence: TaskExecutionFence,
    ) -> TaskDetail:
        """把现有进度事件 DTO 映射为带 queue fence 的字段级 patch。"""

        payload = dict(request.payload)
        if "state" in payload:
            raise InvalidRequestError("进度事件不能携带 Task state")
        progress = payload.get("progress")
        result = payload.get("result")
        metadata = payload.get("metadata")
        return self.record_task_progress(
            RecordTaskProgressRequest(
                task_id=request.task_id,
                fence=fence,
                progress=dict(progress) if isinstance(progress, dict) else {},
                result=dict(result) if isinstance(result, dict) else {},
                metadata=dict(metadata) if isinstance(metadata, dict) else {},
                event_type=request.event_type,
                event_payload=payload,
                message=request.message,
                event_id=request.event_id,
                created_at=request.created_at,
            )
        )

    def execute_task_state_command(
        self,
        request: TaskStateCommandRequest,
    ) -> TaskDetail:
        """按显式状态矩阵和 attempt_no CAS 执行 Task 状态命令。"""

        if not request.task_id.strip():
            raise InvalidRequestError("执行 Task 状态命令时 task_id 不能为空")
        if not request.expected_states:
            raise InvalidRequestError("Task 状态命令 expected_states 不能为空")
        created_at = request.created_at or self._now_iso()
        terminal_states = {
            "paused",
            "succeeded",
            "failed",
            "timed_out",
            "cancelled",
        }
        allowed_transitions: dict[TaskRecordState, set[TaskRecordState]] = {
            "queued": {"queued", "running", "cancelled"},
            "running": {
                "running",
                "paused",
                "succeeded",
                "failed",
                "timed_out",
                "cancelled",
            },
            "paused": {"paused", "queued", "cancelled"},
            "succeeded": {"succeeded"},
            "failed": {"failed", "queued", "cancelled"},
            "timed_out": {"timed_out"},
            "cancelled": {"cancelled"},
        }
        with self._open_unit_of_work() as unit_of_work:
            task_record = unit_of_work.tasks.get_task(request.task_id)
            if task_record is None:
                raise ResourceNotFoundError(
                    "找不到指定的任务",
                    details={"task_id": request.task_id},
                )
            if request.fence is not None:
                attempt = unit_of_work.tasks.get_task_attempt(request.fence.attempt_id)
                self._validate_running_attempt_fence(
                    task_record=task_record,
                    attempt=attempt,
                    fence=request.fence,
                )
            if (
                task_record.state == request.target_state
                and request.target_state in terminal_states
                and task_record.current_attempt_no
                == request.expected_current_attempt_no
            ):
                return TaskDetail(task=task_record, events=())
            if request.target_state not in allowed_transitions[task_record.state]:
                raise InvalidRequestError(
                    "Task 状态转换不合法",
                    details={
                        "task_id": request.task_id,
                        "current_state": task_record.state,
                        "target_state": request.target_state,
                    },
                )

            progress = {**task_record.progress, **dict(request.progress_patch)}
            result = {**task_record.result, **dict(request.result_patch)}
            metadata = {**task_record.metadata, **dict(request.metadata_patch)}
            started_at = task_record.started_at
            finished_at = task_record.finished_at
            target_current_attempt_no = request.target_current_attempt_no
            if target_current_attempt_no is None:
                target_current_attempt_no = task_record.current_attempt_no
            if request.target_state == "running":
                allowed_attempt_numbers = {
                    task_record.current_attempt_no,
                    task_record.current_attempt_no + 1,
                }
                if target_current_attempt_no not in allowed_attempt_numbers:
                    raise InvalidRequestError(
                        "running Task 轮次只能保持不变或严格递增 1",
                        details={
                            "task_id": request.task_id,
                            "current_attempt_no": task_record.current_attempt_no,
                            "target_current_attempt_no": target_current_attempt_no,
                        },
                    )
            elif target_current_attempt_no != task_record.current_attempt_no:
                raise InvalidRequestError(
                    "非 running Task 状态命令不能推进执行轮次",
                    details={
                        "task_id": request.task_id,
                        "current_attempt_no": task_record.current_attempt_no,
                        "target_current_attempt_no": target_current_attempt_no,
                    },
                )
            if request.target_state == "running":
                started_at = started_at or created_at
                finished_at = None
            elif request.target_state == "queued":
                finished_at = None
            elif request.target_state in terminal_states:
                finished_at = created_at
            updated_task = replace(
                task_record,
                state=request.target_state,
                current_attempt_no=target_current_attempt_no,
                progress=progress,
                result=result,
                metadata=metadata,
                error_message=request.error_message,
                started_at=started_at,
                finished_at=finished_at,
            )
            if not unit_of_work.tasks.try_transition_task(
                request.task_id,
                expected_states=request.expected_states,
                expected_current_attempt_no=request.expected_current_attempt_no,
                field_patch={
                    "state": request.target_state,
                    "current_attempt_no": target_current_attempt_no,
                    "progress_json": progress,
                    "result_json": result,
                    "metadata_json": metadata,
                    "error_message": request.error_message,
                    "started_at": started_at,
                    "finished_at": finished_at,
                },
            ):
                raise InvalidRequestError(
                    "Task 已由其他命令推进，状态命令未生效",
                    details={
                        "task_id": request.task_id,
                        "expected_states": list(request.expected_states),
                        "expected_current_attempt_no": (
                            request.expected_current_attempt_no
                        ),
                    },
                )
            event_id = request.event_id
            if event_id is None and request.target_state in terminal_states:
                event_id = self._build_command_event_id(
                    request.task_id,
                    target_current_attempt_no,
                    request.target_state,
                )
            event = TaskEvent(
                event_id=event_id or self._next_id("task-event"),
                task_id=request.task_id,
                attempt_id=request.attempt_id,
                event_type=request.event_type,
                created_at=created_at,
                message=request.message
                or f"task state changed to {request.target_state}",
                payload={
                    "state": request.target_state,
                    "attempt_no": target_current_attempt_no,
                    "progress": dict(request.progress_patch),
                    "result": dict(request.result_patch),
                    "metadata": dict(request.metadata_patch),
                    "error_message": request.error_message,
                    "started_at": started_at,
                    "finished_at": finished_at,
                },
            )
            unit_of_work.tasks.save_task_event(event)
            unit_of_work.commit()

        self._publish_task_event(event)
        return TaskDetail(task=updated_task, events=(event,))

    def execute_task_state_event_command(
        self,
        request: AppendTaskEventRequest,
        *,
        fence: TaskExecutionFence | None = None,
    ) -> TaskDetail:
        """把状态命令模块构造的事件 DTO 映射为显式 Task 状态命令。"""

        payload = dict(request.payload)
        target_state = payload.get("state")
        if not isinstance(target_state, str) or target_state not in {
            "queued",
            "running",
            "paused",
            "succeeded",
            "failed",
            "timed_out",
            "cancelled",
        }:
            raise InvalidRequestError("Task 状态事件缺少合法 state")
        progress_patch = payload.get("progress")
        result_patch = payload.get("result")
        metadata_patch = payload.get("metadata")
        error_message = payload.get("error_message")
        if error_message is not None and not isinstance(error_message, str):
            raise InvalidRequestError("Task 状态事件 error_message 必须是字符串或 null")
        command_created_at = request.created_at
        if command_created_at is None:
            for timestamp_field in ("finished_at", "started_at"):
                timestamp_value = payload.get(timestamp_field)
                if isinstance(timestamp_value, str) and timestamp_value:
                    command_created_at = timestamp_value
                    break
        normalized_progress = (
            dict(progress_patch) if isinstance(progress_patch, dict) else {}
        )
        normalized_result = (
            dict(result_patch) if isinstance(result_patch, dict) else {}
        )
        normalized_metadata = (
            dict(metadata_patch) if isinstance(metadata_patch, dict) else {}
        )
        if fence is not None and target_state in {
            "paused",
            "succeeded",
            "failed",
            "timed_out",
            "cancelled",
        }:
            finalization = self.finalize_task_execution_attempt(
                attempt_id=fence.attempt_id,
                attempt_outcome=target_state,
                result=normalized_result,
                error_message=error_message,
                metadata=normalized_metadata,
                expected_worker_id=fence.worker_id,
                expected_heartbeat_at=fence.heartbeat_at,
                expected_queue_message_id=fence.queue_message_id,
                expected_queue_attempt_count=fence.queue_attempt_count,
                progress=normalized_progress,
                event_type=request.event_type,
                message=request.message,
                event_id=request.event_id,
                finished_at=command_created_at,
            )
            return TaskDetail(
                task=finalization.task,
                events=(
                    (finalization.event,) if finalization.event is not None else ()
                ),
            )
        if fence is not None and target_state == "running":
            observation_payload = {
                key: value
                for key, value in payload.items()
                if key
                not in {
                    "state",
                    "attempt_no",
                    "started_at",
                    "finished_at",
                    "error_message",
                    "progress",
                    "result",
                    "metadata",
                }
            }
            if normalized_progress or normalized_result or normalized_metadata:
                return self.record_task_progress(
                    RecordTaskProgressRequest(
                        task_id=request.task_id,
                        fence=fence,
                        progress=normalized_progress,
                        result=normalized_result,
                        metadata=normalized_metadata,
                        event_type="progress",
                        event_payload=observation_payload,
                        message=request.message or "task execution initialized",
                        event_id=request.event_id,
                        created_at=command_created_at,
                    )
                )
            return self.append_task_attempt_event(
                AppendTaskEventRequest(
                    task_id=request.task_id,
                    attempt_id=fence.attempt_id,
                    event_type="log",
                    message=request.message or "task execution initialized",
                    payload=observation_payload,
                    event_id=request.event_id,
                    created_at=command_created_at,
                ),
                fence=fence,
            )
        task_record = self.get_task(request.task_id).task
        target_current_attempt_no: int | None = None
        payload_attempt_no = payload.get("attempt_no")
        if target_state == "running" and payload_attempt_no is not None:
            if isinstance(payload_attempt_no, bool) or not isinstance(
                payload_attempt_no, int
            ):
                raise InvalidRequestError("running Task 状态事件 attempt_no 必须是整数")
            target_current_attempt_no = payload_attempt_no
        return self.execute_task_state_command(
            TaskStateCommandRequest(
                task_id=request.task_id,
                target_state=target_state,
                expected_states=(task_record.state,),
                expected_current_attempt_no=task_record.current_attempt_no,
                target_current_attempt_no=target_current_attempt_no,
                attempt_id=request.attempt_id,
                fence=fence,
                progress_patch=normalized_progress,
                result_patch=normalized_result,
                metadata_patch=normalized_metadata,
                error_message=error_message,
                message=request.message,
                event_type=request.event_type,
                event_id=request.event_id,
                created_at=command_created_at,
            )
        )

    def execute_task_patch_event_command(
        self,
        request: AppendTaskEventRequest,
        *,
        expected_states: tuple[TaskRecordState, ...],
        expected_current_attempt_no: int,
    ) -> TaskDetail:
        """按 Task state/attempt_no CAS patch 字段并追加不改变状态的事件。"""

        if "state" in request.payload:
            raise InvalidRequestError("Task 字段 patch 事件不能携带 state")
        payload = dict(request.payload)
        progress_patch = payload.get("progress")
        result_patch = payload.get("result")
        metadata_patch = payload.get("metadata")
        created_at = request.created_at or self._now_iso()
        event = TaskEvent(
            event_id=request.event_id or self._next_id("task-event"),
            task_id=request.task_id,
            attempt_id=request.attempt_id,
            event_type=request.event_type,
            created_at=created_at,
            message=request.message,
            payload=payload,
        )
        with self._open_unit_of_work() as unit_of_work:
            task_record = unit_of_work.tasks.get_task(request.task_id)
            if task_record is None:
                raise ResourceNotFoundError(
                    "找不到指定的任务",
                    details={"task_id": request.task_id},
                )
            progress = {
                **task_record.progress,
                **(dict(progress_patch) if isinstance(progress_patch, dict) else {}),
            }
            result = {
                **task_record.result,
                **(dict(result_patch) if isinstance(result_patch, dict) else {}),
            }
            metadata = {
                **task_record.metadata,
                **(dict(metadata_patch) if isinstance(metadata_patch, dict) else {}),
            }
            updated_task = replace(
                task_record,
                progress=progress,
                result=result,
                metadata=metadata,
            )
            if not unit_of_work.tasks.try_transition_task(
                request.task_id,
                expected_states=expected_states,
                expected_current_attempt_no=expected_current_attempt_no,
                field_patch={
                    "progress_json": progress,
                    "result_json": result,
                    "metadata_json": metadata,
                },
            ):
                raise InvalidRequestError(
                    "Task 已由其他命令推进，字段 patch 未生效",
                    details={
                        "task_id": request.task_id,
                        "expected_states": list(expected_states),
                        "expected_current_attempt_no": expected_current_attempt_no,
                    },
                )
            unit_of_work.tasks.save_task_event(event)
            unit_of_work.commit()

        self._publish_task_event(event)
        return TaskDetail(task=updated_task, events=(event,))

    def validate_task_execution_fence(
        self,
        *,
        task_id: str,
        fence: TaskExecutionFence,
    ) -> TaskAttempt:
        """核验并返回当前 queue lease fence 对应的运行 Attempt。"""

        with self._open_unit_of_work() as unit_of_work:
            task_record = unit_of_work.tasks.get_task(task_id)
            if task_record is None:
                raise ResourceNotFoundError(
                    "找不到指定的任务",
                    details={"task_id": task_id},
                )
            attempt = unit_of_work.tasks.get_task_attempt(fence.attempt_id)
            self._validate_running_attempt_fence(
                task_record=task_record,
                attempt=attempt,
                fence=fence,
            )
            if attempt is None:  # pragma: no cover - validator 已覆盖
                raise RuntimeError("TaskAttempt fence 校验后缺少 Attempt")
            return attempt

    def append_task_attempt_event(
        self,
        request: AppendTaskEventRequest,
        *,
        fence: TaskExecutionFence,
    ) -> TaskDetail:
        """在当前 Attempt lease fence 内追加不改变 Task 快照的运行事件。"""

        if request.attempt_id != fence.attempt_id:
            raise InvalidRequestError("Attempt 事件的 attempt_id 与 fence 不一致")
        if "state" in request.payload:
            raise InvalidRequestError("普通 Attempt 事件不能携带 state")
        event = TaskEvent(
            event_id=request.event_id or self._next_id("task-event"),
            task_id=request.task_id,
            attempt_id=fence.attempt_id,
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
            attempt = unit_of_work.tasks.get_task_attempt(fence.attempt_id)
            self._validate_running_attempt_fence(
                task_record=task_record,
                attempt=attempt,
                fence=fence,
            )
            unit_of_work.tasks.save_task_event(event)
            unit_of_work.commit()

        self._publish_task_event(event)
        return TaskDetail(task=task_record, events=(event,))

    def append_task_event(self, request: AppendTaskEventRequest) -> TaskDetail:
        """为指定任务追加一条不改变 Task 快照的普通事件。

        参数：
        - request：待追加的任务事件请求。

        返回：
        - TaskDetail：更新后的任务快照，以及只包含本次新追加事件的 events；不返回历史事件。
        """

        if not request.task_id.strip():
            raise InvalidRequestError("追加任务事件时 task_id 不能为空")
        reserved_fields = {
            "state",
            "attempt_no",
            "started_at",
            "finished_at",
            "error_message",
            "progress",
            "result",
            "metadata",
        }
        invalid_fields = reserved_fields.intersection(request.payload)
        if invalid_fields:
            raise InvalidRequestError(
                "普通 TaskEvent 不能修改 Task 快照",
                details={"reserved_fields": sorted(invalid_fields)},
            )

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
            unit_of_work.tasks.save_task_event(task_event)
            unit_of_work.commit()

        self._publish_task_event(task_event)

        return TaskDetail(task=task_record, events=(task_event,))

    def cancel_task(
        self, task_id: str, *, cancelled_by: str | None = None
    ) -> TaskDetail:
        """通过 Task CAS 取消任务，并同步结束当前 running Attempt。"""

        event: TaskEvent | None = None
        with self._open_unit_of_work() as unit_of_work:
            current_task = unit_of_work.tasks.get_task(task_id)
            if current_task is None:
                raise ResourceNotFoundError(
                    "找不到指定的任务",
                    details={"task_id": task_id},
                )
            if current_task.state == "cancelled":
                return TaskDetail(task=current_task, events=())
            if current_task.state in {"succeeded", "failed", "timed_out"}:
                raise InvalidRequestError(
                    "当前任务已经结束，不能取消",
                    details={"task_id": task_id, "state": current_task.state},
                )
            if current_task.publication_state is not None:
                raise InvalidRequestError(
                    "Conversion 已进入发布提交阶段，不能取消",
                    details={
                        "task_id": task_id,
                        "publication_state": current_task.publication_state,
                    },
                )

            cancelled_at = self._now_iso()
            if current_task.state == "running":
                attempt = unit_of_work.tasks.get_task_attempt_by_number(
                    task_id,
                    current_task.current_attempt_no,
                )
                if attempt is None or attempt.state != "running":
                    raise InvalidRequestError(
                        "running Task 缺少对应的 running TaskAttempt",
                        details={
                            "task_id": task_id,
                            "attempt_no": current_task.current_attempt_no,
                        },
                    )
                cancelled_attempt = replace(
                    attempt,
                    state="cancelled",
                    heartbeat_at=cancelled_at,
                    ended_at=cancelled_at,
                    exit_code=1,
                    error_message="task cancelled",
                    metadata={
                        **attempt.metadata,
                        **(
                            {"cancelled_by": cancelled_by}
                            if cancelled_by is not None
                            else {}
                        ),
                    },
                )
                if not unit_of_work.tasks.try_finish_running_task_attempt(
                    cancelled_attempt
                ):
                    raise InvalidRequestError(
                        "TaskAttempt 已由其他终态命令结束",
                        details={"attempt_id": attempt.attempt_id},
                    )

            metadata = dict(current_task.metadata)
            if cancelled_by is not None:
                metadata["cancelled_by"] = cancelled_by
            updated_task = replace(
                current_task,
                state="cancelled",
                finished_at=cancelled_at,
                error_message=None,
                metadata=metadata,
            )
            if not unit_of_work.tasks.try_transition_task(
                task_id,
                expected_states=(current_task.state,),
                expected_current_attempt_no=current_task.current_attempt_no,
                field_patch={
                    "state": "cancelled",
                    "finished_at": cancelled_at,
                    "error_message": None,
                    "metadata_json": metadata,
                },
                require_publication_unreserved=True,
            ):
                raise InvalidRequestError(
                    "Task 已由其他命令推进，取消未生效",
                    details={"task_id": task_id},
                )
            event = TaskEvent(
                event_id=self._build_command_event_id(
                    task_id,
                    current_task.current_attempt_no,
                    "cancelled",
                ),
                task_id=task_id,
                attempt_id=(
                    attempt.attempt_id if current_task.state == "running" else None
                ),
                event_type="status",
                created_at=cancelled_at,
                message="task cancelled",
                payload={
                    "state": "cancelled",
                    "finished_at": cancelled_at,
                    "metadata": (
                        {"cancelled_by": cancelled_by}
                        if cancelled_by is not None
                        else {}
                    ),
                },
            )
            unit_of_work.tasks.save_task_event(event)
            unit_of_work.commit()

        self._publish_task_event(event)
        return TaskDetail(task=updated_task, events=(event,))

    def update_task_metadata(
        self,
        task_id: str,
        metadata: dict[str, object],
        *,
        expected_states: tuple[TaskRecordState, ...],
        expected_current_attempt_no: int,
    ) -> TaskRecord:
        """按 Task 状态与 Attempt 轮次 CAS 替换 metadata。

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
            if not unit_of_work.tasks.try_transition_task(
                task_id,
                expected_states=expected_states,
                expected_current_attempt_no=expected_current_attempt_no,
                field_patch={"metadata_json": updated_task.metadata},
            ):
                raise InvalidRequestError(
                    "Task 已由其他命令推进，metadata 未写入",
                    details={
                        "task_id": task_id,
                        "expected_states": list(expected_states),
                        "expected_current_attempt_no": expected_current_attempt_no,
                        "actual_state": task_record.state,
                        "actual_current_attempt_no": task_record.current_attempt_no,
                    },
                )
            unit_of_work.commit()
        return updated_task

    def update_task_spec_and_metadata(
        self,
        task_id: str,
        *,
        task_spec: dict[str, object],
        metadata: dict[str, object],
        expected_states: tuple[TaskRecordState, ...],
        expected_current_attempt_no: int,
        fence: TaskExecutionFence | None = None,
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
            if fence is not None:
                attempt = unit_of_work.tasks.get_task_attempt(fence.attempt_id)
                self._validate_running_attempt_fence(
                    task_record=task_record,
                    attempt=attempt,
                    fence=fence,
                )
            if not unit_of_work.tasks.try_transition_task(
                task_id,
                expected_states=expected_states,
                expected_current_attempt_no=expected_current_attempt_no,
                field_patch={
                    "task_spec_json": updated_task.task_spec,
                    "metadata_json": updated_task.metadata,
                },
            ):
                raise InvalidRequestError(
                    "Task 已由其他命令推进，task_spec/metadata 未写入",
                    details={"task_id": task_id},
                )
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

    def _publish_task_event(self, task_event: TaskEvent) -> None:
        """把 TaskEvent 发布到服务内事件总线。

        参数：
        - task_event：要发布的任务事件。
        """

        if self.service_event_bus is None:
            return

        try:
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
        except Exception:
            # 数据库中的 TaskEvent 是权威记录；进程内通知失败不能把已经提交的
            # Task 命令伪装成失败，订阅方可通过持久 cursor 补读。
            LOGGER.exception(
                "TaskEvent 已持久化，但服务内事件总线发布失败",
                extra={
                    "task_id": task_event.task_id,
                    "event_id": task_event.event_id,
                    "event_type": task_event.event_type,
                },
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

    def _build_command_event_id(
        self,
        task_id: str,
        attempt_no: int,
        command: str,
    ) -> str:
        """生成不受原始 task id 长度影响的幂等命令事件 id。"""

        identity = f"task:{task_id}:attempt:{attempt_no}:command:{command}"
        return f"task-event-{uuid5(NAMESPACE_URL, identity).hex}"

    @staticmethod
    def _collect_checkpoint_references(task_record: TaskRecord) -> set[str]:
        """收集 Task 当前快照中的显式 checkpoint object key。"""

        references: set[str] = set()
        pending: list[object] = [task_record.result, task_record.metadata]
        checkpoint_fields = {
            "checkpoint_object_key",
            "latest_checkpoint_object_key",
            "resume_checkpoint_object_key",
        }
        while pending:
            value = pending.pop()
            if not isinstance(value, dict):
                continue
            for key, item in value.items():
                if key in checkpoint_fields and isinstance(item, str) and item:
                    references.add(item)
                elif isinstance(item, dict):
                    pending.append(item)
        return references

    @staticmethod
    def _validate_attempt_lease_fence(
        *,
        attempt: TaskAttempt,
        expected_worker_id: str,
        expected_heartbeat_at: str | None,
        expected_queue_message_id: str,
        expected_queue_attempt_count: int,
    ) -> None:
        """核验 finalizer 调用者仍持有当前 queue lease。"""

        actual_queue_attempt_count = attempt.metadata.get("queue_attempt_count")
        if (
            attempt.worker_id != expected_worker_id
            or attempt.metadata.get("queue_message_id") != expected_queue_message_id
            or isinstance(actual_queue_attempt_count, bool)
            or actual_queue_attempt_count != expected_queue_attempt_count
            or (
                expected_heartbeat_at is not None
                and attempt.heartbeat_at != expected_heartbeat_at
            )
        ):
            raise InvalidRequestError(
                "当前 Worker 已失去 TaskAttempt lease 所有权",
                details={
                    "attempt_id": attempt.attempt_id,
                    "expected_worker_id": expected_worker_id,
                    "actual_worker_id": attempt.worker_id,
                    "expected_heartbeat_at": expected_heartbeat_at,
                    "actual_heartbeat_at": attempt.heartbeat_at,
                    "expected_queue_message_id": expected_queue_message_id,
                    "actual_queue_message_id": attempt.metadata.get("queue_message_id"),
                    "expected_queue_attempt_count": expected_queue_attempt_count,
                    "actual_queue_attempt_count": actual_queue_attempt_count,
                },
            )

    @classmethod
    def _validate_running_attempt_fence(
        cls,
        *,
        task_record: TaskRecord,
        attempt: TaskAttempt | None,
        fence: TaskExecutionFence,
    ) -> None:
        """校验运行事件来自 Task 当前 Attempt 的准确 queue lease。"""

        if attempt is None or attempt.task_id != task_record.task_id:
            raise InvalidRequestError(
                "TaskAttempt fence 不属于当前任务",
                details={
                    "task_id": task_record.task_id,
                    "attempt_id": fence.attempt_id,
                },
            )
        if (
            task_record.state != "running"
            or attempt.state != "running"
            or task_record.current_attempt_no != attempt.attempt_no
        ):
            raise InvalidRequestError(
                "Task 或 TaskAttempt 已不处于当前运行态",
                details={
                    "task_id": task_record.task_id,
                    "task_state": task_record.state,
                    "task_current_attempt_no": task_record.current_attempt_no,
                    "attempt_id": attempt.attempt_id,
                    "attempt_state": attempt.state,
                    "attempt_no": attempt.attempt_no,
                },
            )
        actual_queue_attempt_count = attempt.metadata.get("queue_attempt_count")
        fence_mismatch = (
            attempt.worker_id != fence.worker_id
            or attempt.metadata.get("queue_message_id") != fence.queue_message_id
            or isinstance(actual_queue_attempt_count, bool)
            or actual_queue_attempt_count != fence.queue_attempt_count
            or (
                fence.heartbeat_at is not None
                and attempt.heartbeat_at != fence.heartbeat_at
            )
        )
        if fence_mismatch:
            raise InvalidRequestError(
                "当前 Worker 已失去 TaskAttempt lease 所有权",
                details={
                    "attempt_id": attempt.attempt_id,
                    "expected_worker_id": fence.worker_id,
                    "actual_worker_id": attempt.worker_id,
                    "expected_heartbeat_at": fence.heartbeat_at,
                    "actual_heartbeat_at": attempt.heartbeat_at,
                    "expected_queue_message_id": fence.queue_message_id,
                    "actual_queue_message_id": attempt.metadata.get("queue_message_id"),
                    "expected_queue_attempt_count": fence.queue_attempt_count,
                    "actual_queue_attempt_count": actual_queue_attempt_count,
                },
            )

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
