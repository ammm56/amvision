"""批量异步推理任务与单图子项的 SQLAlchemy 仓储实现。"""

from __future__ import annotations

from sqlalchemy import asc, desc, select
from sqlalchemy.orm import Session

from backend.service.infrastructure.persistence.batch_inference_task_orm import (
    BatchInferenceTaskItemRecord,
    BatchInferenceTaskRecord,
)


class SqlAlchemyBatchInferenceTaskRepository:
    """封装批量推理任务与单图子项的数据库读写操作。"""

    def __init__(self, session: Session) -> None:
        """初始化批量推理仓储。

        参数：
        - session：当前请求级 SQLAlchemy Session。
        """

        self.session = session

    def get(self, batch_task_id: str) -> BatchInferenceTaskRecord | None:
        """按主键查询批量推理任务。"""

        return self.session.get(BatchInferenceTaskRecord, batch_task_id)

    def get_item(self, batch_task_id: str, item_id: str) -> BatchInferenceTaskItemRecord | None:
        """按批量任务 id 与子项 id 查询单张图像子项。"""

        statement = select(BatchInferenceTaskItemRecord).where(
            BatchInferenceTaskItemRecord.batch_task_id == batch_task_id,
            BatchInferenceTaskItemRecord.item_id == item_id,
        )
        return self.session.execute(statement).scalar_one_or_none()

    def list(
        self,
        project_id: str,
        *,
        task_type: str | None = None,
        state: str | None = None,
        deployment_instance_id: str | None = None,
        q: str | None = None,
    ) -> list[BatchInferenceTaskRecord]:
        """按公开筛选条件列出批量推理任务并按创建时间倒序排列。"""

        statement = select(BatchInferenceTaskRecord).where(
            BatchInferenceTaskRecord.project_id == project_id
        )
        if task_type:
            statement = statement.where(BatchInferenceTaskRecord.task_type == task_type)
        if state:
            statement = statement.where(BatchInferenceTaskRecord.state == state)
        if deployment_instance_id:
            statement = statement.where(
                BatchInferenceTaskRecord.deployment_instance_id == deployment_instance_id
            )
        rows = list(
            self.session.scalars(
                statement.order_by(
                    desc(BatchInferenceTaskRecord.created_at),
                    desc(BatchInferenceTaskRecord.batch_task_id),
                )
            )
        )
        keyword = q.strip().casefold() if isinstance(q, str) and q.strip() else ""
        if not keyword:
            return rows
        return [
            row
            for row in rows
            if keyword in row.batch_task_id.casefold()
            or keyword in row.display_name.casefold()
            or keyword in row.deployment_display_name.casefold()
            or keyword in row.deployment_instance_id.casefold()
        ]

    def list_items(
        self,
        batch_task_id: str,
        *,
        state: str | None = None,
        q: str | None = None,
    ) -> list[BatchInferenceTaskItemRecord]:
        """按序号列出批量推理任务下的图像子项。"""

        statement = select(BatchInferenceTaskItemRecord).where(
            BatchInferenceTaskItemRecord.batch_task_id == batch_task_id
        )
        if state:
            statement = statement.where(BatchInferenceTaskItemRecord.state == state)
        rows = list(
            self.session.scalars(
                statement.order_by(
                    asc(BatchInferenceTaskItemRecord.sequence_no),
                    asc(BatchInferenceTaskItemRecord.item_id),
                )
            )
        )
        keyword = q.strip().casefold() if isinstance(q, str) and q.strip() else ""
        if not keyword:
            return rows
        return [
            row
            for row in rows
            if keyword in row.input_label.casefold()
            or keyword in row.item_id.casefold()
            or (row.sample_id is not None and keyword in row.sample_id.casefold())
        ]

    def add_task(
        self,
        task: BatchInferenceTaskRecord,
        items: list[BatchInferenceTaskItemRecord],
    ) -> BatchInferenceTaskRecord:
        """创建批量推理主任务及其全部子项记录。"""

        self.session.add(task)
        for item in items:
            self.session.add(item)
        return task

    def delete_task(self, task: BatchInferenceTaskRecord) -> None:
        """从数据库会话中移除指定批量推理主任务（级联清理子项）。"""

        self.session.delete(task)
