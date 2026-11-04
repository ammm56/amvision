"""SDK 配置选择目录：只读资源身份，避免在列表请求中载入运行配置。"""

from sqlalchemy import func, literal, select, union_all
from sqlalchemy.orm import Session

from backend.service.application.errors import InvalidRequestError
from .deployment_orm import DeploymentInstanceRecord as Deployment
from .workflow_runtime_orm import WorkflowAppRuntimeRecord as Runtime
from .workflow_trigger_source_orm import WorkflowTriggerSourceRecord as Trigger

SDK_RESOURCE_LIMIT = 10_000


class ProjectSdkResourceRepository:
    """限制每类导出容量，并以稳定身份排序分页。"""

    def __init__(self, session: Session):
        """保存当前数据库会话。"""
        self.session = session

    def validate_capacity(self, project_id: str) -> None:
        """完整导出超限时明确拒绝，不能截断后声称导出了全部。"""
        for kind, model in (
            ("Runtime", Runtime),
            ("Trigger", Trigger),
            ("Deployment", Deployment),
        ):
            total = (
                self.session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.project_id == project_id)
                )
                or 0
            )
            if total > SDK_RESOURCE_LIMIT:
                raise InvalidRequestError(
                    f"{kind} 资源超过单项目导出上限 {SDK_RESOURCE_LIMIT}，请拆分项目后导出",
                    details={"kind": kind, "total": total, "limit": SDK_RESOURCE_LIMIT},
                )

    def page(self, project_id: str, offset: int, limit: int) -> tuple[list[dict], int]:
        """返回窄字段目录与总量；后台自动运行的目录触发源不占选择项。"""
        self.validate_capacity(project_id)
        statements = []
        for kind, model, identifier in (
            ("runtime", Runtime, Runtime.workflow_runtime_id),
            ("trigger", Trigger, Trigger.trigger_source_id),
            ("deployment", Deployment, Deployment.deployment_instance_id),
        ):
            statement = select(
                identifier.label("id"),
                func.coalesce(func.nullif(model.display_name, ""), identifier).label(
                    "name"
                ),
                literal(kind).label("kind"),
                (
                    Trigger.workflow_runtime_id if kind == "trigger" else literal(None)
                ).label("runtime_id"),
            ).where(model.project_id == project_id)
            if kind == "trigger":
                statement = statement.where(
                    Trigger.trigger_kind.in_(("zeromq-topic", "local-shared-memory"))
                )
            statements.append(statement)
        source = union_all(*statements).subquery()
        total = int(self.session.scalar(select(func.count()).select_from(source)) or 0)
        rows = self.session.execute(
            select(source)
            .order_by(source.c.kind, source.c.id)
            .offset(offset)
            .limit(limit)
        ).mappings()
        return [dict(row) for row in rows], total
