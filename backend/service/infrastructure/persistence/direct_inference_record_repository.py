"""同步推理显式保存记录的 SQLAlchemy 仓储实现。"""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.service.infrastructure.persistence.direct_inference_record_orm import (
    DirectInferenceRecord,
)


class SqlAlchemyDirectInferenceRecordRepository:
    """封装同步推理保存记录的数据库读写操作，事务提交由 Unit of Work 控制。"""

    def __init__(self, session: Session) -> None:
        """初始化同步推理保存记录仓储。

        参数：
        - session：当前请求级 SQLAlchemy Session。
        """

        self.session = session

    def get(self, record_id: str) -> DirectInferenceRecord | None:
        """按主键查询一条同步推理保存记录。"""

        return self.session.get(DirectInferenceRecord, record_id)

    def get_by_request_id(
        self,
        project_id: str,
        request_id: str,
    ) -> DirectInferenceRecord | None:
        """按 Project id 与 request_id 幂等查询已保存记录。"""

        statement = select(DirectInferenceRecord).where(
            DirectInferenceRecord.project_id == project_id,
            DirectInferenceRecord.request_id == request_id,
        )
        return self.session.execute(statement).scalar_one_or_none()

    def list(
        self,
        project_id: str,
        *,
        task_type: str | None = None,
        deployment_instance_id: str | None = None,
        request_id: str | None = None,
        q: str | None = None,
    ) -> list[DirectInferenceRecord]:
        """按公开筛选条件列出同步推理保存记录并按创建时间倒序排列。"""

        statement = select(DirectInferenceRecord).where(
            DirectInferenceRecord.project_id == project_id
        )
        if task_type:
            statement = statement.where(DirectInferenceRecord.task_type == task_type)
        if deployment_instance_id:
            statement = statement.where(
                DirectInferenceRecord.deployment_instance_id == deployment_instance_id
            )
        if request_id:
            statement = statement.where(DirectInferenceRecord.request_id == request_id)
        rows = list(
            self.session.scalars(
                statement.order_by(
                    desc(DirectInferenceRecord.created_at),
                    desc(DirectInferenceRecord.record_id),
                )
            )
        )
        keyword = q.strip().casefold() if isinstance(q, str) and q.strip() else ""
        if not keyword:
            return rows
        return [
            row
            for row in rows
            if keyword in row.record_id.casefold()
            or keyword in row.request_id.casefold()
            or keyword in row.input_label.casefold()
            or keyword in row.deployment_display_name.casefold()
            or keyword in row.deployment_instance_id.casefold()
        ]

    def add(self, record: DirectInferenceRecord) -> DirectInferenceRecord:
        """登记一条新的同步推理保存记录。"""

        self.session.add(record)
        return record

    def delete(self, record: DirectInferenceRecord) -> None:
        """从数据库会话中移除指定同步推理保存记录。"""

        self.session.delete(record)
