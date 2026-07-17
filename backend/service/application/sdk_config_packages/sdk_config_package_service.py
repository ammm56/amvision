"""生成现场 SDK 使用的 config_*.json 配置包。"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO

from backend.service.application.deployments.deployment_instance_service import (
    DeploymentInstanceView,
    SqlAlchemyDeploymentInstanceService,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.workflows.workflow_runtime_records import WorkflowAppRuntime
from backend.service.domain.workflows.workflow_trigger_source_records import WorkflowTriggerSource
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


_PACKAGE_FORMAT_ID = "amvision.sdk-config-package.v1"
_DEFAULT_HTTP_TIMEOUT_SECONDS = 240
_DEFAULT_INVOKE_TIMEOUT_SECONDS = 30
_DEFAULT_EVENT_LIMIT = 20
_DEFAULT_EVENT_PREVIEW_COUNT = 5
_DEFAULT_ACCESS_TOKEN_PLACEHOLDER = "<replace-with-user-token>"
_DEFAULT_MODEL_MEDIA_TYPE = "image/jpeg"
_DEFAULT_MODEL_FILE_NAME = "image.jpg"
_SUPPORTED_MODEL_RUNTIME_MODES = {"sync", "async"}


@dataclass(frozen=True)
class SdkConfigPackageBuildRequest:
    """描述一次 SDK 配置包生成请求。

    字段：
    - project_id：当前要导出配置的 Project id。
    - base_api_url：写入 SDK 配置的 backend-service 根地址。
    - include_access_token：是否把当前请求 token 写入配置。
    - access_token：当前请求 token；未选择写入时会被忽略。
    - model_runtime_modes：模型 deployment 要生成的 runtime_mode 列表。
    - include_disabled_trigger_sources：是否导出已创建但未启用的 TriggerSource。
    """

    project_id: str
    base_api_url: str
    include_access_token: bool = True
    access_token: str | None = None
    model_runtime_modes: tuple[str, ...] = ("sync",)
    include_disabled_trigger_sources: bool = True


@dataclass(frozen=True)
class SdkConfigPackageFile:
    """描述 zip 中的一个文件。

    字段：
    - path：zip 内相对路径。
    - kind：文件类型。
    - content：文件内容。
    - count：当前文件包含的主要配置数量。
    - runtime_key：workflow 配置文件对应的 runtime key。
    - trigger_source_count：workflow 配置文件内的 TriggerSource 数量。
    """

    path: str
    kind: str
    content: str
    count: int = 0
    runtime_key: str | None = None
    trigger_source_count: int = 0


@dataclass(frozen=True)
class SdkConfigPackagePlan:
    """描述一次配置包生成结果。

    字段：
    - project_id：当前 Project id。
    - generated_at：生成时间，使用 ISO 8601。
    - timestamp：文件名使用的时间戳。
    - package_name：zip 文件名。
    - base_api_url：配置里的 backend-service 根地址。
    - contains_access_token：配置中是否包含真实 token。
    - files：准备写入 zip 的文件列表。
    - warnings：生成过程发现的提示。
    - workflow_runtime_count：导出的 WorkflowAppRuntime 数量。
    - trigger_source_count：导出的 TriggerSource 数量。
    - model_deployment_count：导出的模型 deployment key 数量。
    """

    project_id: str
    generated_at: str
    timestamp: str
    package_name: str
    base_api_url: str
    contains_access_token: bool
    files: tuple[SdkConfigPackageFile, ...]
    warnings: tuple[str, ...] = ()
    workflow_runtime_count: int = 0
    trigger_source_count: int = 0
    model_deployment_count: int = 0


class SdkConfigPackageService:
    """按当前 Project 的实际资源生成 SDK config_*.json 配置包。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
    ) -> None:
        """初始化配置包服务。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：本地文件存储，用于解析 DeploymentInstance 运行时快照。
        """

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage

    def build_plan(self, request: SdkConfigPackageBuildRequest) -> SdkConfigPackagePlan:
        """生成配置包计划，供 preview 和 download 共用。

        参数：
        - request：配置包生成请求。

        返回：
        - SdkConfigPackagePlan：文件清单、摘要和 warning。
        """

        normalized_request = _normalize_request(request)
        resources = self._load_project_resources(normalized_request.project_id)
        builder = _SdkConfigPackageBuilder(normalized_request)
        return builder.build(resources)

    def build_zip_bytes(self, plan: SdkConfigPackagePlan) -> bytes:
        """把配置包计划写成 zip bytes。

        参数：
        - plan：已经构造好的配置包计划。

        返回：
        - bytes：zip 文件内容。
        """

        if not plan.files:
            raise InvalidRequestError(
                "当前 Project 没有可导出的 SDK 配置",
                details={"project_id": plan.project_id},
            )

        buffer = BytesIO()
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in plan.files:
                archive.writestr(item.path, item.content)
            archive.writestr("manifest.json", _to_pretty_json(_build_manifest(plan)))
            archive.writestr("README.md", _build_package_readme(plan))
        return buffer.getvalue()

    def _load_project_resources(self, project_id: str) -> "_ProjectSdkConfigResources":
        """读取当前 Project 下配置包需要的资源。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            runtimes = unit_of_work.workflow_runtime.list_workflow_app_runtimes(project_id)
            trigger_sources = unit_of_work.workflow_trigger_sources.list_trigger_sources(project_id)
        finally:
            unit_of_work.close()

        deployment_service = SqlAlchemyDeploymentInstanceService(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
        )
        deployments = deployment_service.list_deployment_instances(
            project_id=project_id,
            limit=10_000,
        )
        return _ProjectSdkConfigResources(
            runtimes=runtimes,
            trigger_sources=trigger_sources,
            deployments=deployments,
            application_display_names={
                runtime.workflow_runtime_id: name
                for runtime in runtimes
                if (
                    name := _read_runtime_application_display_name(
                        self.dataset_storage,
                        runtime,
                    )
                )
            },
        )


@dataclass(frozen=True)
class _ProjectSdkConfigResources:
    """配置包生成时需要的 Project 资源集合。"""

    runtimes: tuple[WorkflowAppRuntime, ...]
    trigger_sources: tuple[WorkflowTriggerSource, ...]
    deployments: tuple[DeploymentInstanceView, ...]
    application_display_names: dict[str, str]


class _SdkConfigPackageBuilder:
    """把 Project 资源转换成 SDK 配置文件。"""

    def __init__(self, request: SdkConfigPackageBuildRequest) -> None:
        self.request = request
        self.generated_at = datetime.now(timezone.utc)
        self.timestamp = self.generated_at.strftime("%Y%m%d%H%M%S")
        self.warnings: list[str] = []
        self.used_keys: dict[str, int] = {}

    def build(self, resources: _ProjectSdkConfigResources) -> SdkConfigPackagePlan:
        """构建完整配置包计划。"""

        files: list[SdkConfigPackageFile] = []
        trigger_sources_by_runtime = self._group_trigger_sources(resources.trigger_sources)
        for runtime in sorted(resources.runtimes, key=lambda item: item.workflow_runtime_id):
            workflow_file = self._build_workflow_file(
                runtime=runtime,
                trigger_sources=trigger_sources_by_runtime.get(runtime.workflow_runtime_id, ()),
                application_display_name=resources.application_display_names.get(
                    runtime.workflow_runtime_id
                ),
            )
            files.append(workflow_file)

        model_file = self._build_model_deployment_file(resources.deployments)
        if model_file is not None:
            files.append(model_file)

        workflow_runtime_count = len(resources.runtimes)
        trigger_source_count = sum(
            item.trigger_source_count for item in files if item.kind == "workflow-runtime"
        )
        model_deployment_count = sum(
            item.count for item in files if item.kind == "model-deployments"
        )
        if not files:
            self.warnings.append("当前 Project 没有可导出的 SDK 配置。")

        package_name = f"amvision_sdk_configs_{_safe_file_part(self.request.project_id)}_{self.timestamp}.zip"
        return SdkConfigPackagePlan(
            project_id=self.request.project_id,
            generated_at=self.generated_at.isoformat().replace("+00:00", "Z"),
            timestamp=self.timestamp,
            package_name=package_name,
            base_api_url=self.request.base_api_url,
            contains_access_token=self.request.include_access_token and bool(self.request.access_token),
            files=tuple(files),
            warnings=tuple(self.warnings),
            workflow_runtime_count=workflow_runtime_count,
            trigger_source_count=trigger_source_count,
            model_deployment_count=model_deployment_count,
        )

    def _group_trigger_sources(
        self,
        trigger_sources: tuple[WorkflowTriggerSource, ...],
    ) -> dict[str, tuple[WorkflowTriggerSource, ...]]:
        """按 workflow_runtime_id 归组 TriggerSource。"""

        grouped: dict[str, list[WorkflowTriggerSource]] = {}
        for trigger_source in trigger_sources:
            if not self.request.include_disabled_trigger_sources and not trigger_source.enabled:
                continue
            if trigger_source.trigger_kind != "zeromq-topic":
                self.warnings.append(
                    f"TriggerSource {trigger_source.trigger_source_id} 不是 ZeroMQ 类型，当前 Console 配置包已跳过。"
                )
                continue
            grouped.setdefault(trigger_source.workflow_runtime_id, []).append(trigger_source)
        return {
            runtime_id: tuple(sorted(items, key=lambda item: item.trigger_source_id))
            for runtime_id, items in grouped.items()
        }

    def _build_workflow_file(
        self,
        *,
        runtime: WorkflowAppRuntime,
        trigger_sources: tuple[WorkflowTriggerSource, ...],
        application_display_name: str | None,
    ) -> SdkConfigPackageFile:
        """构建单个 WorkflowAppRuntime 对应的配置文件。"""

        runtime_key = self._unique_key(
            _build_runtime_key(runtime, application_display_name=application_display_name),
            fallback="workflow_runtime",
        )
        payload = {
            "backend": self._build_backend_config(),
            "runtime": {
                "name": runtime_key,
                "workflow_runtime_id": runtime.workflow_runtime_id,
            },
            "invoke": {
                "image_path": "",
                "image_input_binding": "request_image_base64",
                "timeout_seconds": _DEFAULT_INVOKE_TIMEOUT_SECONDS,
                "event_limit": _DEFAULT_EVENT_LIMIT,
                "event_preview_count": _DEFAULT_EVENT_PREVIEW_COUNT,
                "source": "amvision-workflows-console",
                "sync_scenario": "sync-invoke",
                "async_scenario": "async-run",
                "use_direct_input_bindings": False,
            },
            "trigger_sources": [
                self._build_trigger_source_config(trigger_source)
                for trigger_source in trigger_sources
            ],
            "model_deployments": [],
        }
        path = f"Config/config_workflow_{_safe_file_part(runtime_key)}_{self.timestamp}.json"
        return SdkConfigPackageFile(
            path=path,
            kind="workflow-runtime",
            content=_to_pretty_json(payload),
            count=1,
            runtime_key=runtime_key,
            trigger_source_count=len(trigger_sources),
        )

    def _build_trigger_source_config(
        self,
        trigger_source: WorkflowTriggerSource,
    ) -> dict[str, object]:
        """构建 Console 调用 TriggerSource 所需的最小配置。"""

        trigger_key = self._unique_key(
            _build_trigger_source_key(trigger_source),
            fallback="trigger_source",
        )
        bind_endpoint = _read_optional_text(trigger_source.transport_config, "bind_endpoint") or ""
        if not bind_endpoint:
            self.warnings.append(
                f"TriggerSource {trigger_source.trigger_source_id} 缺少 bind_endpoint。"
            )
        default_input_binding = (
            _read_optional_text(trigger_source.transport_config, "default_input_binding")
            or _infer_default_input_binding(trigger_source)
            or "request_image_ref"
        )
        return {
            "name": trigger_key,
            "trigger_source_id": trigger_source.trigger_source_id,
            "zero_mq": {
                "bind_endpoint": bind_endpoint,
                "default_input_binding": default_input_binding,
                "timeout_seconds": trigger_source.reply_timeout_seconds or 5,
            },
        }

    def _build_model_deployment_file(
        self,
        deployments: tuple[DeploymentInstanceView, ...],
    ) -> SdkConfigPackageFile | None:
        """构建模型 deployment 配置文件。"""

        model_deployments: list[dict[str, object]] = []
        for deployment in sorted(deployments, key=lambda item: item.deployment_instance_id):
            for runtime_mode in self.request.model_runtime_modes:
                model_deployments.append(
                    self._build_model_deployment_config(deployment, runtime_mode=runtime_mode)
                )
        if not model_deployments:
            return None

        payload = {
            "backend": self._build_backend_config(),
            "model_deployments": model_deployments,
        }
        return SdkConfigPackageFile(
            path=f"Config/config_model_deployment_{self.timestamp}.json",
            kind="model-deployments",
            content=_to_pretty_json(payload),
            count=len(model_deployments),
        )

    def _build_model_deployment_config(
        self,
        deployment: DeploymentInstanceView,
        *,
        runtime_mode: str,
    ) -> dict[str, object]:
        """构建单个模型 deployment 调用配置。"""

        base_key = _build_model_deployment_key(deployment)
        key = self._unique_key(base_key, fallback="model_deployment")
        config: dict[str, object] = {
            "name": key,
            "task_type": deployment.task_type,
            "deployment_instance_id": deployment.deployment_instance_id,
            "runtime_mode": runtime_mode,
            "input_transport_mode": "memory",
            "score_threshold": _read_float(deployment.metadata, "score_threshold", 0.3),
            "save_result_image": False,
            "return_preview_image_base64": False,
            "default_image_path": "",
            "default_file_name": _DEFAULT_MODEL_FILE_NAME,
            "default_media_type": _DEFAULT_MODEL_MEDIA_TYPE,
        }
        if deployment.task_type == "classification":
            config["top_k"] = 5
        if deployment.task_type == "segmentation":
            config["mask_threshold"] = 0.5
        if deployment.task_type == "pose":
            config["keypoint_confidence_threshold"] = 0.3
        return config

    def _build_backend_config(self) -> dict[str, object]:
        """构建所有配置文件共用的 backend 节点。"""

        return {
            "base_api_url": self.request.base_api_url,
            "access_token": self.request.access_token
            if self.request.include_access_token and self.request.access_token
            else _DEFAULT_ACCESS_TOKEN_PLACEHOLDER,
            "project_id": self.request.project_id,
            "http_timeout_seconds": _DEFAULT_HTTP_TIMEOUT_SECONDS,
        }

    def _unique_key(self, value: str, *, fallback: str) -> str:
        """生成 zip 内唯一的配置 key。"""

        base_key = _display_key(value, fallback=fallback)
        candidate = base_key
        suffix = 2
        while candidate.casefold() in self.used_keys:
            candidate = f"{base_key}_{suffix}"
            suffix += 1
        self.used_keys[candidate.casefold()] = 1
        return candidate


def _normalize_request(
    request: SdkConfigPackageBuildRequest,
) -> SdkConfigPackageBuildRequest:
    """校验并规范化配置包生成请求。"""

    project_id = request.project_id.strip()
    if not project_id:
        raise InvalidRequestError("project_id 不能为空")
    base_api_url = request.base_api_url.strip().rstrip("/")
    if not base_api_url:
        raise InvalidRequestError("base_api_url 不能为空")

    runtime_modes: list[str] = []
    for runtime_mode in request.model_runtime_modes or ("sync",):
        normalized_mode = runtime_mode.strip().lower()
        if normalized_mode not in _SUPPORTED_MODEL_RUNTIME_MODES:
            raise InvalidRequestError(
                "model_runtime_modes 只能包含 sync 或 async",
                details={"runtime_mode": runtime_mode},
            )
        if normalized_mode not in runtime_modes:
            runtime_modes.append(normalized_mode)
    if not runtime_modes:
        runtime_modes.append("sync")

    return SdkConfigPackageBuildRequest(
        project_id=project_id,
        base_api_url=base_api_url,
        include_access_token=bool(request.include_access_token),
        access_token=request.access_token.strip() if request.access_token else None,
        model_runtime_modes=tuple(runtime_modes),
        include_disabled_trigger_sources=bool(request.include_disabled_trigger_sources),
    )


def _build_manifest(plan: SdkConfigPackagePlan) -> dict[str, object]:
    """构建 zip 顶层 manifest.json。"""

    return {
        "format_id": _PACKAGE_FORMAT_ID,
        "generated_at": plan.generated_at,
        "project_id": plan.project_id,
        "base_api_url": plan.base_api_url,
        "contains_access_token": plan.contains_access_token,
        "workflow_runtime_count": plan.workflow_runtime_count,
        "trigger_source_count": plan.trigger_source_count,
        "model_deployment_count": plan.model_deployment_count,
        "files": [
            {
                "path": item.path,
                "kind": item.kind,
                "count": item.count,
                "runtime_key": item.runtime_key,
                "trigger_source_count": item.trigger_source_count,
            }
            for item in plan.files
        ],
        "warnings": list(plan.warnings),
    }


def _build_package_readme(plan: SdkConfigPackagePlan) -> str:
    """构建 zip 内 README.md。"""

    token_note = (
        "本包已包含当前请求的 access token。"
        if plan.contains_access_token
        else "本包未包含真实 access token，请在 Config/config_*.json 中替换 backend.access_token。"
    )
    return "\n".join(
        [
            "# Amvision SDK 配置包",
            "",
            f"- Project id：`{plan.project_id}`",
            f"- 生成时间：`{plan.generated_at}`",
            f"- backend-service：`{plan.base_api_url}`",
            f"- {token_note}",
            "",
            "## 使用方式",
            "",
            "1. 将 `Config/` 目录复制到 `Amvision.Workflows.Console` 程序目录。",
            "2. 按现场 token、endpoint 或图片路径修改对应 `config_*.json`。",
            "3. 默认使用 `runtime.name`、`trigger_sources[].name` 或 `model_deployments[].name` 调用；.NET SDK 也提供明确的 `ById` 方法按对应资源 id 调用。",
            "",
        ]
    )


def _to_pretty_json(payload: object) -> str:
    """把配置对象序列化为稳定可读的 JSON。"""

    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _build_runtime_key(
    runtime: WorkflowAppRuntime,
    *,
    application_display_name: str | None,
) -> str:
    """优先使用前端维护的 WorkflowAppRuntime 展示名称。"""

    if application_display_name and application_display_name.strip():
        return application_display_name.strip()
    if runtime.display_name and runtime.display_name.strip():
        return runtime.display_name.strip()
    return runtime.workflow_runtime_id


def _read_runtime_application_display_name(
    dataset_storage: LocalDatasetStorage,
    runtime: WorkflowAppRuntime,
) -> str | None:
    """从 runtime 固化的 application snapshot 读取用户维护的应用名称。"""

    try:
        payload = dataset_storage.read_json(runtime.application_snapshot_object_key)
    except (OSError, ValueError, InvalidRequestError):
        return None
    if not isinstance(payload, dict):
        return None
    display_name = payload.get("display_name")
    if isinstance(display_name, str) and display_name.strip():
        return display_name.strip()
    application = payload.get("application")
    if isinstance(application, dict):
        nested_display_name = application.get("display_name")
        if isinstance(nested_display_name, str) and nested_display_name.strip():
            return nested_display_name.strip()
    return None


def _build_trigger_source_key(trigger_source: WorkflowTriggerSource) -> str:
    """优先使用前端维护的 TriggerSource 展示名称。"""

    if trigger_source.display_name and trigger_source.display_name.strip():
        return trigger_source.display_name.strip()
    return trigger_source.trigger_source_id


def _build_model_deployment_key(deployment: DeploymentInstanceView) -> str:
    """优先使用前端维护的 DeploymentInstance 展示名称。"""

    return (
        deployment.display_name.strip()
        or deployment.model_name.strip()
        or deployment.deployment_instance_id
    )


def _display_key(value: str, *, fallback: str) -> str:
    """保留用户可读名称，仅清理会破坏 JSON key 查找的控制字符。"""

    normalized = re.sub(r"[\x00-\x1f\x7f]+", " ", value).strip()
    return normalized or fallback


def _safe_file_part(value: str) -> str:
    """把 Project id 转换成安全文件名片段。"""

    normalized = re.sub(r"[^0-9A-Za-z_.-]+", "_", value.strip()).strip("._-")
    return normalized or "project"


def _read_optional_text(payload: dict[str, object], key: str) -> str | None:
    """从字典读取可选字符串。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _read_float(payload: dict[str, object], key: str, default: float) -> float:
    """从字典读取可选 float。"""

    value = payload.get(key)
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _infer_default_input_binding(trigger_source: WorkflowTriggerSource) -> str | None:
    """从 input_binding_mapping 推断 ZeroMQ 默认图片输入 binding。"""

    mapping = trigger_source.input_binding_mapping
    if "request_image_ref" in mapping:
        return "request_image_ref"
    if "request_image_base64" in mapping:
        return "request_image_base64"
    for binding_id in mapping:
        if isinstance(binding_id, str) and binding_id.strip():
            return binding_id.strip()
    return None
