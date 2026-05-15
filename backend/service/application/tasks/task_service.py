"""统一任务应用服务。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from uuid import uuid4

from backend.service.application.events.event_bus import ServiceEvent
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.domain.tasks.task_records import TaskEvent, TaskEventType, TaskRecord, TaskRecordState
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
    - limit：最大返回数量。
    """

    project_id: str
    task_kind: str | None = None
    state: TaskRecordState | None = None
    worker_pool: str | None = None
    created_by: str | None = None
    parent_task_id: str | None = None
    dataset_id: str | None = None
    source_import_id: str | None = None
    limit: int = 100


@dataclass(frozen=True)
class TaskEventQueryFilters:
    """描述任务事件查询与订阅使用的筛选条件。

    字段：
    - task_id：所属任务 id。
    - event_type：事件类型。
    - after_created_at：只返回晚于该时间的事件。
    - limit：最大返回数量。
    """

    task_id: str
    event_type: TaskEventType | None = None
    after_created_at: str | None = None
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
            metadata=dict(request.metadata),
            state=request.state,
        )
        created_event = TaskEvent(
            event_id=self._next_id("task-event"),
            task_id=task_id,
            event_type="status",
            created_at=created_at,
            message="task created",
            payload={"state": request.state},
        )

        with self._open_unit_of_work() as unit_of_work:
            existing_task = unit_of_work.tasks.get_task(task_id)
            if existing_task is not None:
                raise InvalidRequestError(
                    "任务 id 已存在",
                    details={"task_id": task_id},
                )
            unit_of_work.tasks.save_task(task_record)
            unit_of_work.tasks.save_task_event(created_event)
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
            events = unit_of_work.tasks.list_task_events(task_id) if include_events else ()

        return TaskDetail(task=task_record, events=events)

    def list_tasks(self, filters: TaskQueryFilters) -> tuple[TaskRecord, ...]:
        """按筛选条件返回任务列表。"""

        if not filters.project_id.strip():
            raise InvalidRequestError("查询任务列表时 project_id 不能为空")
        if filters.limit <= 0:
            raise InvalidRequestError("limit 必须大于 0")

        with self._open_unit_of_work() as unit_of_work:
            tasks = unit_of_work.tasks.list_tasks(filters.project_id)

        matched_tasks = [task for task in tasks if self._task_matches_filters(task, filters)]
        matched_tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
        return tuple(matched_tasks[: filters.limit])

    def list_task_events(self, filters: TaskEventQueryFilters) -> tuple[TaskEvent, ...]:
        """按筛选条件返回任务事件列表。"""

        if not filters.task_id.strip():
            raise InvalidRequestError("查询任务事件时 task_id 不能为空")
        if filters.limit <= 0:
            raise InvalidRequestError("limit 必须大于 0")

        with self._open_unit_of_work() as unit_of_work:
            events = unit_of_work.tasks.list_task_events(filters.task_id)

        matched_events = [event for event in events if self._event_matches_filters(event, filters)]
        matched_events.sort(key=lambda event: (event.created_at, event.event_id))
        return tuple(matched_events[: filters.limit])

    def append_task_event(self, request: AppendTaskEventRequest) -> TaskDetail:
        """为指定任务追加一条事件，并同步更新任务快照。"""

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
            updated_task = self._apply_event(task_record=task_record, task_event=task_event)
            unit_of_work.tasks.save_task(updated_task)
            unit_of_work.tasks.save_task_event(task_event)
            unit_of_work.commit()

        self._publish_task_event(task_event)

        return TaskDetail(task=updated_task, events=(task_event,))

    def cancel_task(self, task_id: str, *, cancelled_by: str | None = None) -> TaskDetail:
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

    def _validate_create_request(self, request: CreateTaskRequest) -> None:
        """校验创建任务请求。"""

        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not request.task_kind.strip():
            raise InvalidRequestError("task_kind 不能为空")

    def _task_matches_filters(self, task_record: TaskRecord, filters: TaskQueryFilters) -> bool:
        """判断任务是否满足筛选条件。"""

        if filters.task_kind is not None and task_record.task_kind != filters.task_kind:
            return False
        if filters.state is not None and task_record.state != filters.state:
            return False
        if filters.worker_pool is not None and task_record.worker_pool != filters.worker_pool:
            return False
        if filters.created_by is not None and task_record.created_by != filters.created_by:
            return False
        if filters.parent_task_id is not None and task_record.parent_task_id != filters.parent_task_id:
            return False
        if filters.dataset_id is not None and task_record.task_spec.get("dataset_id") != filters.dataset_id:
            return False
        if filters.source_import_id is not None:
            source_import_id = task_record.task_spec.get("dataset_import_id")
            if source_import_id is None:
                source_import_id = task_record.metadata.get("source_import_id")
            if source_import_id != filters.source_import_id:
                return False

        return True

    def _event_matches_filters(self, task_event: TaskEvent, filters: TaskEventQueryFilters) -> bool:
        """判断事件是否满足筛选条件。"""

        if filters.event_type is not None and task_event.event_type != filters.event_type:
            return False
        if filters.after_created_at is not None and task_event.created_at <= filters.after_created_at:
            return False

        return True

    def _apply_event(self, *, task_record: TaskRecord, task_event: TaskEvent) -> TaskRecord:
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
                    if key not in {"state", "metadata", "result", "error_message", "finished_at", "started_at", "attempt_no"}
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
                    if key not in {"state", "metadata", "progress", "error_message", "finished_at", "started_at", "attempt_no"}
                }
            )

        payload_state = payload.get("state")
        if isinstance(payload_state, str):
            state = payload_state
        elif task_event.event_type == "progress" and task_record.state == "queued":
            state = "running"

        payload_error_message = payload.get("error_message")
        if isinstance(payload_error_message, str):
            error_message = payload_error_message

        payload_attempt_no = payload.get("attempt_no")
        if isinstance(payload_attempt_no, int):
            current_attempt_no = payload_attempt_no

        payload_started_at = payload.get("started_at")
        if isinstance(payload_started_at, str):
            started_at = payload_started_at
        elif state == "running" and started_at is None:
            started_at = task_event.created_at

        payload_finished_at = payload.get("finished_at")
        if isinstance(payload_finished_at, str):
            finished_at = payload_finished_at
        elif state in {"succeeded", "failed", "cancelled"}:
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