"""Project summary 的数据库聚合读模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ProjectDatabaseSummary:
    """保存一个 Project 的轻量数据库状态计数。

    属性：
    - import_status_counts：DatasetImport 按 status 的数量。
    - export_status_counts：DatasetExport 按 status 的数量。
    - task_state_counts_by_kind：TaskRecord 按 task_kind、state 的数量。
    - preview_run_state_counts：WorkflowPreviewRun 按 state 的数量。
    - workflow_run_state_counts：WorkflowRun 按 state 的数量。
    - app_runtime_observed_state_counts：WorkflowAppRuntime 按 observed_state 的数量。
    - deployment_status_counts：DeploymentInstance 按 status 的数量。
    """

    import_status_counts: dict[str, int] = field(default_factory=dict)
    export_status_counts: dict[str, int] = field(default_factory=dict)
    task_state_counts_by_kind: dict[str, dict[str, int]] = field(default_factory=dict)
    preview_run_state_counts: dict[str, int] = field(default_factory=dict)
    workflow_run_state_counts: dict[str, int] = field(default_factory=dict)
    app_runtime_observed_state_counts: dict[str, int] = field(default_factory=dict)
    deployment_status_counts: dict[str, int] = field(default_factory=dict)


class ProjectSummaryRepository(Protocol):
    """定义 Project summary 所需的只读聚合查询。"""

    def get_database_summary(self, project_id: str) -> ProjectDatabaseSummary:
        """返回一个 Project 的数据库聚合计数。"""

        ...
