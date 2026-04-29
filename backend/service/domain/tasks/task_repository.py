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

    def list_tasks(self, project_id: str) -> tuple[TaskRecord, ...]:
        """按 Project id 列出任务记录。

        参数：
        - project_id：所属 Project id。

        返回：
        - 当前 Project 下的 TaskRecord 列表。
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

    def list_task_events(self, task_id: str) -> tuple[TaskEvent, ...]:
        """按 TaskRecord id 列出事件记录。

        参数：
        - task_id：所属任务 id。

        返回：
        - 当前任务下的 TaskEvent 列表。
        """

        ...