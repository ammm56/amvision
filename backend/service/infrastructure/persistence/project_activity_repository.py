"""项目概览的有界读取；不载入任务结果、图像或执行快照。"""

from sqlalchemy import func, literal, select, union_all
from sqlalchemy.orm import Session

from .dataset_orm import DatasetVersionRecord as Dataset
from .dataset_import_orm import DatasetImportRecord as Import
from .model_orm import ModelRecord as Model, ModelVersionRecord as Version
from .task_orm import TaskRecordEntity as Task
from .deployment_orm import (
    DeploymentInstanceRecord as Deployment,
    DeploymentRuntimeStateRecord as Mode,
)
from .workflow_runtime_orm import (
    WorkflowAppRuntimeRecord as Runtime,
    WorkflowAppVersionRecord as AppVersion,
)
from .workflow_trigger_source_orm import WorkflowTriggerSourceRecord as Trigger


class ProjectActivityRepository:
    """组合各类资源的窄字段查询，先过滤权限，再排序和分页。"""

    def __init__(self, session: Session):
        """保存当前只读会话。"""
        self.session = session

    def resource_names(self, project_id: str, blockers) -> dict[tuple[str, str], str]:
        """按类别分批读取阻止删除的友好名称，不加载执行结果或运行配置。"""
        names = {}
        for kind, model, identifier in (
            ("task", Task, Task.task_id),
            ("workflow_runtime", Runtime, Runtime.workflow_runtime_id),
            ("deployment", Deployment, Deployment.deployment_instance_id),
            ("trigger_source", Trigger, Trigger.trigger_source_id),
        ):
            ids = [item.resource_id for item in blockers if item.resource_kind == kind]
            for start in range(0, len(ids), 400):
                for resource_id, name in self.session.execute(
                    select(identifier, model.display_name).where(
                        model.project_id == project_id,
                        identifier.in_(ids[start : start + 400]),
                    )
                ):
                    names[kind, resource_id] = name or resource_id
        return names

    def recent(
        self,
        project_id: str,
        *,
        access: dict[str, bool],
        offset: int,
        limit: int,
        q: str = "",
        kind: str = "",
        matching_applications: tuple[str, ...] = (),
    ) -> tuple[list[dict], int]:
        """读取最近资源更新；未知日期保持空，不用请求时间补齐。"""
        statements = []

        def add(
            group, table, identifier, name, state, timestamp, item_kind, target=None
        ):
            """建立各方言均支持的统一投影。"""
            if access.get(group) and (not kind or kind == group):
                statements.append(
                    select(
                        identifier.label("resource_id"),
                        name.label("name"),
                        state.label("state"),
                        func.coalesce(timestamp, "").label("occurred_at"),
                        (
                            literal(item_kind)
                            if isinstance(item_kind, str)
                            else item_kind
                        ).label("kind"),
                        (target if target is not None else identifier).label(
                            "target_id"
                        ),
                    )
                    .select_from(table)
                    .where(table.project_id == project_id)
                )

        add(
            "tasks",
            Task,
            Task.task_id,
            Task.display_name,
            Task.state,
            func.coalesce(Task.finished_at, Task.started_at, Task.created_at),
            Task.task_kind,
        )
        add(
            "runtimes",
            Runtime,
            Runtime.workflow_runtime_id,
            Runtime.display_name,
            Runtime.observed_state,
            Runtime.updated_at,
            "runtime",
        )
        add(
            "deployments",
            Deployment,
            Deployment.deployment_instance_id,
            Deployment.display_name,
            Deployment.status,
            Deployment.updated_at,
            "deployment",
        )
        add(
            "apps",
            AppVersion,
            AppVersion.workflow_app_version_id,
            AppVersion.display_version,
            AppVersion.state,
            func.coalesce(AppVersion.completed_at, AppVersion.created_at),
            "app-version",
            AppVersion.application_id,
        )
        # 导入记录可被单独清理；版本本身仍必须保留在最近资源中。
        imported_at = (
            select(func.max(Import.created_at))
            .where(Import.dataset_version_id == Dataset.dataset_version_id)
            .correlate(Dataset)
            .scalar_subquery()
        )
        add(
            "datasets",
            Dataset,
            Dataset.dataset_version_id,
            func.coalesce(
                Dataset.metadata_json["display_name"].as_string(), Dataset.dataset_id
            ),
            literal("available"),
            func.coalesce(
                Dataset.metadata_json["updated_at"].as_string(),
                Dataset.metadata_json["created_at"].as_string(),
                imported_at,
            ),
            "dataset-version",
            Dataset.dataset_id,
        )
        if access.get("models") and (not kind or kind == "models"):
            trained_at = (
                select(func.max(Task.finished_at))
                .where(Task.task_id == Version.training_task_id)
                .correlate(Version)
                .scalar_subquery()
            )
            statements.append(
                select(
                    Version.model_version_id.label("resource_id"),
                    Model.model_name.label("name"),
                    literal("available").label("state"),
                    func.coalesce(
                        Version.metadata_json["updated_at"].as_string(),
                        Version.metadata_json["created_at"].as_string(),
                        trained_at,
                        "",
                    ).label("occurred_at"),
                    literal("model-version").label("kind"),
                    Model.model_id.label("target_id"),
                )
                .join(Model, Model.model_id == Version.model_id)
                .where(Model.project_id == project_id)
            )
        if not statements:
            return [], 0
        source = union_all(*statements).subquery()
        predicate = (
            (
                source.c.name.icontains(q, autoescape=True)
                | source.c.resource_id.icontains(q, autoescape=True)
            )
            if q
            else literal(True)
        )
        if q and matching_applications:
            predicate = predicate | (
                (source.c.kind == "app-version")
                & source.c.target_id.in_(matching_applications)
            )
        total = int(
            self.session.scalar(
                select(func.count()).select_from(source).where(predicate)
            )
            or 0
        )
        rows = self.session.execute(
            select(source)
            .where(predicate)
            .order_by(source.c.occurred_at.desc(), source.c.kind, source.c.resource_id)
            .offset(offset)
            .limit(limit)
        ).mappings()
        return [dict(row) for row in rows], total

    def active(
        self, project_id: str, access: dict[str, bool], limit: int = 5
    ) -> list[dict]:
        """按任务、Runtime、部署模式分别限量，保留真实阶段与进度。"""
        items = []
        if access.get("tasks"):
            statement = (
                select(
                    Task.task_id.label("resource_id"),
                    Task.display_name.label("name"),
                    Task.task_kind.label("kind"),
                    Task.state,
                    Task.started_at.label("occurred_at"),
                    Task.progress_json.label("progress"),
                )
                .where(
                    Task.project_id == project_id,
                    Task.state.in_(("queued", "running", "cancelling")),
                )
                .order_by(Task.created_at.desc(), Task.task_id)
                .limit(limit)
            )
            items.extend(
                dict(row) for row in self.session.execute(statement).mappings()
            )
        if access.get("runtimes"):
            statement = (
                select(
                    Runtime.workflow_runtime_id.label("resource_id"),
                    Runtime.display_name.label("name"),
                    literal("runtime").label("kind"),
                    Runtime.observed_state.label("state"),
                    Runtime.updated_at.label("occurred_at"),
                )
                .where(
                    Runtime.project_id == project_id,
                    Runtime.observed_state.in_(
                        ("running", "starting", "stopping", "degraded")
                    ),
                )
                .order_by(Runtime.updated_at.desc(), Runtime.workflow_runtime_id)
                .limit(limit)
            )
            items.extend(
                dict(row) for row in self.session.execute(statement).mappings()
            )
        if access.get("deployments"):
            statement = (
                select(
                    Deployment.deployment_instance_id.label("resource_id"),
                    Deployment.display_name.label("name"),
                    literal("deployment").label("kind"),
                    Mode.observed_state.label("state"),
                    Mode.runtime_mode,
                    Mode.updated_at.label("occurred_at"),
                )
                .join(
                    Mode,
                    Deployment.deployment_instance_id == Mode.deployment_instance_id,
                )
                .where(
                    Deployment.project_id == project_id,
                    Mode.observed_state.in_(
                        ("running", "starting", "stopping", "ready", "degraded")
                    ),
                )
                .order_by(
                    Mode.updated_at.desc(),
                    Deployment.deployment_instance_id,
                    Mode.runtime_mode,
                )
                .limit(limit)
            )
            items.extend(
                dict(row) for row in self.session.execute(statement).mappings()
            )
        for item in items:
            progress = item.get("progress")
            if isinstance(progress, dict):
                item["progress"] = {
                    key: progress[key]
                    for key in ("stage", "percent")
                    if key in progress
                }
        return items
