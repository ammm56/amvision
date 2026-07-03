"""system 路由请求和响应 schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.service.api.rest.v1.routes.projects.schemas import ProjectCatalogItemResponse


class SystemCurrentPrincipalContract(BaseModel):
    """描述 system/bootstrap 使用的当前主体摘要。"""

    principal_id: str = Field(description="主体 id")
    principal_type: str = Field(description="主体类型")
    project_ids: list[str] = Field(default_factory=list, description="当前主体的 Project 可见范围；为空表示全部 Project")
    scopes: list[str] = Field(default_factory=list, description="当前主体持有的 scopes")
    username: str | None = Field(default=None, description="用户名")
    display_name: str | None = Field(default=None, description="展示名称")
    auth_source: str | None = Field(default=None, description="当前鉴权来源")
    auth_provider_id: str | None = Field(default=None, description="账号 provider id")
    auth_provider_kind: str | None = Field(default=None, description="账号 provider 类型")
    auth_credential_kind: str | None = Field(default=None, description="凭据类型")
    auth_credential_id: str | None = Field(default=None, description="凭据 id")
    auth_session_id: str | None = Field(default=None, description="登录会话 id")
    auth_token_id: str | None = Field(default=None, description="长期 token id")
    auth_token_name: str | None = Field(default=None, description="长期 token 名称")


class SystemAuthProviderContract(BaseModel):
    """描述 system/bootstrap 中公开的账号 provider 目录项。"""

    provider_id: str = Field(description="provider id")
    provider_kind: str = Field(description="provider 类型")
    display_name: str = Field(description="展示名称")
    enabled: bool = Field(description="是否启用")
    login_mode: str = Field(description="登录模式")
    supports_password_login: bool = Field(description="是否支持密码登录")
    supports_refresh: bool = Field(description="是否支持 refresh")
    supports_bootstrap_admin: bool = Field(description="是否支持 bootstrap-admin")
    supports_user_management: bool = Field(description="是否支持用户管理")
    supports_long_lived_tokens: bool = Field(description="是否支持长期调用 token")
    issuer_url: str | None = Field(default=None, description="可选 issuer 地址")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class DatasetExportCapabilityContract(BaseModel):
    """描述前端需要读取的数据集导出格式能力。"""

    implemented_formats: list[str] = Field(default_factory=list, description="当前已实现并可用的格式")
    default_format: str = Field(description="当前默认导出格式")
    format_types_by_task_type: dict[str, list[str]] = Field(
        default_factory=dict,
        description="按 task_type 汇总的已实现导出格式列表",
    )


class DatasetImportCapabilityContract(BaseModel):
    """描述前端需要读取的数据集导入能力。"""

    implemented_task_types: list[str] = Field(default_factory=list, description="当前已实现并可用的导入任务类型")
    format_types_by_task_type: dict[str, list[str]] = Field(
        default_factory=dict,
        description="按 task_type 汇总的已实现导入格式列表",
    )


class SystemBootstrapCapabilitiesContract(BaseModel):
    """描述 system/bootstrap 返回的关键能力摘要。"""

    project_bootstrap_enabled: bool = Field(description="是否支持 Project 初始化接口")
    dataset_import: DatasetImportCapabilityContract = Field(description="数据集导入能力")
    dataset_export: DatasetExportCapabilityContract = Field(description="数据集导出格式能力")
    project_summary_topics: list[str] = Field(default_factory=list, description="projects.events 支持的 topic 列表")
    platform_model_types_by_task_type: dict[str, list[str]] = Field(
        default_factory=dict,
        description="按 task_type 汇总的平台模型分类列表",
    )


class SystemBootstrapResponse(BaseModel):
    """描述前端首屏初始化需要的聚合响应。"""

    auth_mode: str | None = Field(default=None, description="当前鉴权模式")
    bearer_auth_enabled: bool = Field(description="是否启用 Bearer token 鉴权")
    websocket_query_token_enabled: bool = Field(description="WebSocket 是否允许 access_token 查询参数")
    current_user: SystemCurrentPrincipalContract | None = Field(default=None, description="当前已登录主体；未登录时为空")
    providers: list[SystemAuthProviderContract] = Field(default_factory=list, description="公开可发现的账号 provider 列表")
    visible_projects: list[ProjectCatalogItemResponse] = Field(
        default_factory=list,
        description="当前主体当前可访问的 Project 列表；每个元素通过 project_source 标记来自配置目录还是本地磁盘",
    )
    capabilities: SystemBootstrapCapabilitiesContract = Field(description="前端需要读取的关键能力摘要")
    devices: dict[str, object] = Field(default_factory=dict, description="设备与推理运行时摘要")


class SystemDiagnosticsResponse(BaseModel):
    """描述设置页使用的只读系统诊断摘要。

    字段：
    - generated_at：诊断摘要生成时间。
    - request_id：当前请求 id。
    - about：应用版本、构建和许可证摘要。
    - system：操作系统、路径、磁盘、CPU 和内存摘要。
    - python_runtime：Python 解释器、环境和关键依赖摘要。
    - devices：GPU、CUDA、OpenVINO、TensorRT、ONNX Runtime 和 NPU 可用性摘要。
    - services：backend-service、worker、WebSocket、ZeroMQ、数据库和本地运行组件摘要。
    """

    generated_at: str = Field(description="诊断摘要生成时间")
    request_id: str = Field(description="当前请求 id")
    about: dict[str, object] = Field(default_factory=dict, description="应用版本、构建和许可证摘要")
    system: dict[str, object] = Field(default_factory=dict, description="操作系统、路径、磁盘、CPU 和内存摘要")
    python_runtime: dict[str, object] = Field(default_factory=dict, description="Python 解释器、环境和关键依赖摘要")
    devices: dict[str, object] = Field(default_factory=dict, description="设备与推理运行时摘要")
    services: dict[str, object] = Field(default_factory=dict, description="服务组件运行摘要")


class SystemConfigResponse(BaseModel):
    """描述前端读取的 backend-service 统一配置快照。"""

    format_id: str = Field(
        default="amvision.backend-service-config.v1",
        description="配置快照格式 id",
    )
    config: dict[str, object] = Field(default_factory=dict, description="当前进程已解析并合并后的配置")
    metadata: dict[str, object] = Field(default_factory=dict, description="配置快照附加信息")
