"""Project 级 summary 聚合与事件发布辅助。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from backend.service.application.errors import InvalidRequestError
from backend.service.application.events import InMemoryServiceEventBus, ServiceEvent
from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


PROJECT_SUMMARY_EVENT_TYPE = "projects.summary.updated"
PROJECT_SUMMARY_SNAPSHOT_EVENT_TYPE = "projects.summary.snapshot"
PROJECT_SUMMARY_TOPIC_WORKFLOW_PREVIEW_RUNS = "workflows.preview-runs"
PROJECT_SUMMARY_TOPIC_WORKFLOW_RUNS = "workflows.runs"
PROJECT_SUMMARY_TOPIC_WORKFLOW_APP_RUNTIMES = "workflows.app-runtimes"
PROJECT_SUMMARY_TOPIC_DEPLOYMENTS = "deployments"

_SUPPORTED_PROJECT_SUMMARY_TOPICS = (
    PROJECT_SUMMARY_TOPIC_WORKFLOW_PREVIEW_RUNS,
    PROJECT_SUMMARY_TOPIC_WORKFLOW_RUNS,
    PROJECT_SUMMARY_TOPIC_WORKFLOW_APP_RUNTIMES,
    PROJECT_SUMMARY_TOPIC_DEPLOYMENTS,
)
_PROJECT_SUMMARY_PREVIEW_EVENT_TYPES = frozenset(
    {
        "preview.started",
        "preview.succeeded",
        "preview.failed",
        "preview.cancelled",
        "preview.timed_out",
    }
)
_PROJECT_SUMMARY_RUNTIME_EVENT_TYPES = frozenset(
    {
        "runtime.created",
        "runtime.started",
        "runtime.stopped",
        "runtime.restarted",
        "runtime.failed",
        "runtime.heartbeat_timed_out",
        "runtime.heartbeat_recovered",
    }
)


@dataclass(frozen=True)
class ProjectWorkflowSummarySnapshot:
    """描述 Project 下 workflow 相关资源的聚合摘要。

    字段：
    - template_total：模板总数。
    - application_total：流程应用总数。
    - preview_run_total：preview run 总数。
    - preview_run_state_counts：preview run 状态计数字典。
    - workflow_run_total：WorkflowRun 总数。
    - workflow_run_state_counts：WorkflowRun 状态计数字典。
    - app_runtime_total：WorkflowAppRuntime 总数。
    - app_runtime_observed_state_counts：WorkflowAppRuntime observed_state 计数字典。
    """

    template_total: int = 0
    application_total: int = 0
    preview_run_total: int = 0
    preview_run_state_counts: dict[str, int] = field(default_factory=dict)
    workflow_run_total: int = 0
    workflow_run_state_counts: dict[str, int] = field(default_factory=dict)
    app_runtime_total: int = 0
    app_runtime_observed_state_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectDeploymentSummarySnapshot:
    """描述 Project 下 deployment 相关资源的聚合摘要。

    字段：
    - deployment_instance_total：DeploymentInstance 总数。
    - deployment_status_counts：DeploymentInstance status 计数字典。
    """

    deployment_instance_total: int = 0
    deployment_status_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectSummarySnapshot:
    """描述一个 Project 当前可公开的聚合摘要快照。

    字段：
    - project_id：所属 Project id。
    - generated_at：当前聚合快照生成时间。
    - workflows：workflow 相关聚合摘要。
    - deployments：deployment 相关聚合摘要。
    """

    project_id: str
    generated_at: str
    workflows: ProjectWorkflowSummarySnapshot = field(default_factory=ProjectWorkflowSummarySnapshot)
    deployments: ProjectDeploymentSummarySnapshot = field(default_factory=ProjectDeploymentSummarySnapshot)


class ProjectSummaryService:
    """按 Project 读取当前工作台可用的最小聚合摘要。"""

    def __init__(self, *, session_factory: SessionFactory, dataset_storage: LocalDatasetStorage) -> None:
        """初始化 ProjectSummaryService。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：本地文件存储。
        """

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage

    def get_project_summary(self, project_id: str) -> ProjectSummarySnapshot:
        """读取一个 Project 的当前聚合摘要。

        参数：
        - project_id：目标 Project id。

        返回：
        - ProjectSummarySnapshot：当前项目级聚合快照。
        """

        normalized_project_id = project_id.strip()
        if not normalized_project_id:
            raise InvalidRequestError("project_id 不能为空")

        workflow_service = LocalWorkflowJsonService(dataset_storage=self.dataset_storage)
        templates = workflow_service.list_templates(project_id=normalized_project_id)
        applications = workflow_service.list_applications(project_id=normalized_project_id)

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            preview_runs = unit_of_work.workflow_runtime.list_preview_runs(normalized_project_id)
            workflow_runs = unit_of_work.workflow_runtime.list_workflow_runs(normalized_project_id)
            app_runtimes = unit_of_work.workflow_runtime.list_workflow_app_runtimes(normalized_project_id)
            deployments = unit_of_work.deployments.list_deployment_instances(normalized_project_id)
        finally:
            unit_of_work.close()

        return ProjectSummarySnapshot(
            project_id=normalized_project_id,
            generated_at=_now_isoformat(),
            workflows=ProjectWorkflowSummarySnapshot(
                template_total=len(templates),
                application_total=len(applications),
                preview_run_total=len(preview_runs),
                preview_run_state_counts=_build_counter(item.state for item in preview_runs),
                workflow_run_total=len(workflow_runs),
                workflow_run_state_counts=_build_counter(item.state for item in workflow_runs),
                app_runtime_total=len(app_runtimes),
                app_runtime_observed_state_counts=_build_counter(item.observed_state for item in app_runtimes),
            ),
            deployments=ProjectDeploymentSummarySnapshot(
                deployment_instance_total=len(deployments),
                deployment_status_counts=_build_counter(item.status for item in deployments),
            ),
        )


def get_supported_project_summary_topics() -> tuple[str, ...]:
    """返回当前支持的 projects.events topic 列表。"""

    return _SUPPORTED_PROJECT_SUMMARY_TOPICS


def normalize_project_summary_topic(raw_topic: str | None) -> str | None:
    """把 projects.events 的 topic 查询参数规范化为稳定值。"""

    if raw_topic is None:
        return None
    topic = raw_topic.strip()
    if not topic:
        return None
    if topic not in _SUPPORTED_PROJECT_SUMMARY_TOPICS:
        raise ValueError("topic_invalid")
    return topic


def should_publish_project_summary_for_preview_event(event_type: str) -> bool:
    """判断 preview run 事件是否需要触发项目级聚合更新。"""

    return event_type in _PROJECT_SUMMARY_PREVIEW_EVENT_TYPES


def should_publish_project_summary_for_workflow_run_event(event_type: str) -> bool:
    """判断 WorkflowRun 事件是否需要触发项目级聚合更新。"""

    return event_type.startswith("run.")


def should_publish_project_summary_for_runtime_event(event_type: str) -> bool:
    """判断 WorkflowAppRuntime 事件是否需要触发项目级聚合更新。"""

    return event_type in _PROJECT_SUMMARY_RUNTIME_EVENT_TYPES


def should_publish_project_summary_for_deployment_event(event_type: str) -> bool:
    """判断 deployment 事件是否需要触发项目级聚合更新。"""

    return event_type.startswith("deployment.")


def serialize_project_summary(snapshot: ProjectSummarySnapshot) -> dict[str, object]:
    """把 ProjectSummarySnapshot 转成稳定 JSON 字典。"""

    return {
        "project_id": snapshot.project_id,
        "generated_at": snapshot.generated_at,
        "workflows": {
            "template_total": snapshot.workflows.template_total,
            "application_total": snapshot.workflows.application_total,
            "preview_run_total": snapshot.workflows.preview_run_total,
            "preview_run_state_counts": dict(snapshot.workflows.preview_run_state_counts),
            "workflow_run_total": snapshot.workflows.workflow_run_total,
            "workflow_run_state_counts": dict(snapshot.workflows.workflow_run_state_counts),
            "app_runtime_total": snapshot.workflows.app_runtime_total,
            "app_runtime_observed_state_counts": dict(snapshot.workflows.app_runtime_observed_state_counts),
        },
        "deployments": {
            "deployment_instance_total": snapshot.deployments.deployment_instance_total,
            "deployment_status_counts": dict(snapshot.deployments.deployment_status_counts),
        },
    }


def build_project_summary_payload(
    snapshot: ProjectSummarySnapshot,
    *,
    topic: str | None = None,
    source_stream: str | None = None,
    source_resource_kind: str | None = None,
    source_resource_id: str | None = None,
) -> dict[str, object]:
    """构造 projects.events 使用的稳定 payload。"""

    payload = serialize_project_summary(snapshot)
    if topic is not None:
        payload["topic"] = topic
    if source_stream is not None:
        payload["source_stream"] = source_stream
    if source_resource_kind is not None:
        payload["source_resource_kind"] = source_resource_kind
    if source_resource_id is not None:
        payload["source_resource_id"] = source_resource_id
    return payload


def publish_project_summary_event(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    service_event_bus: InMemoryServiceEventBus | None,
    project_id: str,
    topic: str,
    source_stream: str,
    source_resource_kind: str,
    source_resource_id: str,
) -> None:
    """重新聚合一个 Project summary 并发布到统一 service_event_bus。"""

    if service_event_bus is None:
        return
    summary = ProjectSummaryService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    ).get_project_summary(project_id)
    service_event_bus.publish(
        ServiceEvent(
            stream="projects.events",
            resource_kind="project",
            resource_id=summary.project_id,
            event_type=PROJECT_SUMMARY_EVENT_TYPE,
            occurred_at=summary.generated_at,
            cursor=summary.generated_at,
            payload=build_project_summary_payload(
                summary,
                topic=topic,
                source_stream=source_stream,
                source_resource_kind=source_resource_kind,
                source_resource_id=source_resource_id,
            ),
        )
    )


def _build_counter(values: object) -> dict[str, int]:
    """把状态值序列规范化为按 key 排序的计数字典。"""

    counter = Counter(
        item.strip()
        for item in values
        if isinstance(item, str) and item.strip()
    )
    return {key: counter[key] for key in sorted(counter)}


def _now_isoformat() -> str:
    """返回当前 UTC 时间的 ISO8601 字符串。"""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")