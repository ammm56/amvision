"""TaskRecord、TaskAttempt 与 TaskEvent 仓储协议定义。"""

from __future__ import annotations

from typing import Protocol

from backend.service.domain.tasks.task_records import TaskAttempt, TaskEvent, TaskRecord


class TaskRepository(Protocol):
    """描述统一任务记录的持久化边界。

    该仓储负责 TaskRecord、TaskAttempt、TaskEvent 三类对象的保存与读取。
    """

    def save_task(self, task_record: TaskRecord) -> None:
        """保存一个 TaskRecord。

        参数：
        - task_record：要保存的 TaskRecord。
        """

        ...

    def get_task(self, task_id: str) -> TaskRecord | None:
        """按 id 读取一个 TaskRecord。

        参数：
        - task_id：任务 id。

        返回：
        - 读取到的 TaskRecord；不存在时返回 None。
        """

        ...

    def get_visible_task(
        self,
        task_id: str,
        visible_project_ids: tuple[str, ...],
    ) -> TaskRecord | None:
        """按 id 和 Project 可见范围读取 TaskRecord。

        ``visible_project_ids`` 为空表示不限制。受限主体访问其他 Project 的
        task 与 task 不存在使用相同的 None 结果，避免资源归属探测。
        """

        ...

    def list_tasks(self, project_id: str) -> tuple[TaskRecord, ...]:
        """按 Project id 列出任务记录。

        参数：
        - project_id：所属 Project id。

        返回：
        - 当前 Project 下的 TaskRecord 列表。
        """

        ...

    def delete_task(self, task_id: str) -> bool:
        """按 id 删除一个 TaskRecord。

        参数：
        - task_id：任务 id。

        返回：
        - 当任务存在且已删除时返回 True；否则返回 False。
        """

        ...

    def save_task_attempt(self, task_attempt: TaskAttempt) -> None:
        """保存一个 TaskAttempt。

        参数：
        - task_attempt：要保存的 TaskAttempt。
        """

        ...

    def get_task_attempt(self, attempt_id: str) -> TaskAttempt | None:
        """按 id 读取一个 TaskAttempt。

        参数：
        - attempt_id：执行尝试 id。

        返回：
        - 读取到的 TaskAttempt；不存在时返回 None。
        """

        ...

    def get_task_attempt_by_number(
        self,
        task_id: str,
        attempt_no: int,
    ) -> TaskAttempt | None:
        """按 Task id 和 attempt_no 读取唯一执行尝试。"""

        ...

    def try_create_task_attempt(self, task_attempt: TaskAttempt) -> bool:
        """原子创建执行尝试；同一 Task/attempt_no 已存在时返回 False。"""

        ...

    def try_reclaim_running_task_attempt(
        self,
        task_attempt: TaskAttempt,
        *,
        expected_worker_id: str | None,
        expected_heartbeat_at: str | None,
    ) -> bool:
        """按旧 owner/heartbeat CAS 接管 lease 恢复后的 running attempt。"""

        ...

    def try_heartbeat_running_task_attempt(
        self,
        *,
        attempt_id: str,
        worker_id: str,
        heartbeat_at: str,
    ) -> bool:
        """仅由当前 owner 刷新 running attempt heartbeat。"""

        ...

    def try_finish_running_task_attempt(
        self,
        task_attempt: TaskAttempt,
        *,
        expected_worker_id: str | None = None,
        expected_heartbeat_at: str | None = None,
    ) -> bool:
        """仅当指定执行尝试仍为 running 时原子写入终态。"""

        ...

    def list_task_attempts(self, task_id: str) -> tuple[TaskAttempt, ...]:
        """按 TaskRecord id 列出执行尝试。

        参数：
        - task_id：所属任务 id。

        返回：
        - 当前任务下的 TaskAttempt 列表。
        """

        ...

    def save_task_event(self, task_event: TaskEvent) -> None:
        """保存一个 TaskEvent。

        参数：
        - task_event：要保存的 TaskEvent。
        """

        ...

    def get_task_event(self, event_id: str) -> TaskEvent | None:
        """按 id 读取一个 TaskEvent。

        参数：
        - event_id：事件 id。

        返回：
        - 读取到的 TaskEvent；不存在时返回 None。
        """

        ...

    def list_task_events(
        self,
        task_id: str,
        *,
        event_type: str | None = None,
        after_created_at: str | None = None,
        after_cursor: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[TaskEvent, ...]:
        """按 TaskRecord id 列出事件记录。

        参数：
        - task_id：所属任务 id。
        - event_type：可选事件类型。
        - after_created_at：可选时间游标。
        - after_cursor：可选 ``created_at|event_id`` 复合游标。
        - offset：结果偏移量。
        - limit：最大返回数量；None 表示不限制。

        返回：
        - 当前任务下的 TaskEvent 列表。
        """

        ...
