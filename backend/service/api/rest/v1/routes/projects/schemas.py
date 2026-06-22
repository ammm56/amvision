"""Project REST 请求与响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ProjectSource = Literal["configured", "local_disk"]


class ProjectWorkflowSummaryResponse(BaseModel):
    """描述 Project 下 workflow 聚合摘要响应。"""

    template_total: int = Field(description="模板总数")
    application_total: int = Field(description="流程应用总数")
    preview_run_total: int = Field(description="preview run 总数")
    preview_run_state_counts: dict[str, int] = Field(
        default_factory=dict, description="preview run 状态计数字典"
    )
    workflow_run_total: int = Field(description="WorkflowRun 总数")
    workflow_run_state_counts: dict[str, int] = Field(
        default_factory=dict, description="WorkflowRun 状态计数字典"
    )
    app_runtime_total: int = Field(description="WorkflowAppRuntime 总数")
    app_runtime_observed_state_counts: dict[str, int] = Field(
        default_factory=dict,
        description="WorkflowAppRuntime observed_state 计数字典",
    )


class ProjectDeploymentSummaryResponse(BaseModel):
    """描述 Project 下 deployment 聚合摘要响应。"""

    deployment_instance_total: int = Field(description="DeploymentInstance 总数")
    deployment_status_counts: dict[str, int] = Field(
        default_factory=dict, description="DeploymentInstance status 计数字典"
    )


class ProjectDatasetInventoryResponse(BaseModel):
    """描述 Project 下的数据集目录库存摘要。"""

    dataset_total: int = Field(description="Project datasets 目录下的数据集总数")


class ProjectStatusSummaryResponse(BaseModel):
    """描述某一类 Project 资源的总数与状态分布。"""

    total: int = Field(description="资源总数")
    status_counts: dict[str, int] = Field(default_factory=dict, description="状态计数字典")


class ProjectSummaryResponse(BaseModel):
    """描述工作台可直接消费的项目级聚合摘要响应。"""

    project_id: str = Field(description="所属 Project id")
    generated_at: str = Field(description="聚合快照生成时间")
    datasets: ProjectDatasetInventoryResponse = Field(description="数据集目录聚合摘要")
    imports: ProjectStatusSummaryResponse = Field(description="数据集导入聚合摘要")
    exports: ProjectStatusSummaryResponse = Field(description="数据集导出聚合摘要")
    training: ProjectStatusSummaryResponse = Field(description="训练任务聚合摘要")
    validation: ProjectStatusSummaryResponse = Field(description="人工验证 session 聚合摘要")
    evaluation: ProjectStatusSummaryResponse = Field(description="评估任务聚合摘要")
    conversion: ProjectStatusSummaryResponse = Field(description="转换任务聚合摘要")
    inference: ProjectStatusSummaryResponse = Field(description="推理任务聚合摘要")
    workflows: ProjectWorkflowSummaryResponse = Field(description="workflow 相关聚合摘要")
    deployments: ProjectDeploymentSummaryResponse = Field(
        description="deployment 相关聚合摘要"
    )


class ProjectCatalogItemResponse(BaseModel):
    """描述前端可直接消费的 Project 目录项响应。

    字段：
    - project_id：Project id。
    - display_name：展示名称。
    - description：项目说明。
    - metadata：附加元数据。
    - project_source：Project 来源。
    - storage_prefix：Project 在本地 ObjectStore 中的固定前缀。
    - summary：可选聚合摘要；仅当请求显式要求时返回。
    """

    project_id: str = Field(description="Project id")
    display_name: str = Field(description="展示名称")
    description: str | None = Field(default=None, description="项目说明")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")
    project_source: ProjectSource = Field(
        description="Project 来源；configured 表示配置项，local_disk 表示本地目录"
    )
    storage_prefix: str = Field(description="Project 对应的本地 ObjectStore 前缀")
    summary: ProjectSummaryResponse | None = Field(default=None, description="可选聚合摘要")


class ProjectObjectMetadataResponse(BaseModel):
    """描述 Project 内对象文件的读取元数据。

    字段：
    - project_id：所属 Project id。
    - file_id：公开文件稳定 id，可用于 input_file_id 等调用面。
    - object_key：本地 ObjectStore 相对路径。
    - file_name：文件名。
    - media_type：推断出的媒体类型。
    - size_bytes：文件字节大小。
    - last_modified_at：最近修改时间。
    - content_url：内联读取 URL。
    - download_url：下载 URL。
    """

    project_id: str = Field(description="所属 Project id")
    file_id: str = Field(description="公开文件稳定 id")
    object_key: str = Field(description="本地 ObjectStore 相对路径")
    file_name: str = Field(description="文件名")
    media_type: str = Field(description="推断出的媒体类型")
    size_bytes: int = Field(description="文件字节大小")
    last_modified_at: str = Field(description="最近修改时间")
    content_url: str = Field(description="内联读取 URL")
    download_url: str = Field(description="下载 URL")


class ProjectBootstrapRequestBody(BaseModel):
    """描述 Project 初始化请求体。

    字段：
    - project_id：Project id，同时也是磁盘目录名。
    - display_name：可选展示名称。
    - description：可选项目说明。
    - metadata：附加元数据。
    """

    project_id: str = Field(description="Project id，同时也是磁盘目录名")
    display_name: str | None = Field(default=None, description="可选展示名称")
    description: str | None = Field(default=None, description="可选项目说明")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")

