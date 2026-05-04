"""YOLOX 部署实例应用服务。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError, ServiceConfigurationError
from backend.service.application.runtime.yolox_runtime_target import (
    RuntimeTargetResolveRequest,
    RuntimeTargetSnapshot,
    SqlAlchemyYoloXRuntimeTargetResolver,
    deserialize_runtime_target_snapshot,
    serialize_runtime_target_snapshot,
)
from backend.service.domain.deployments.deployment_instance import DeploymentInstance
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


_ACTIVE_DEPLOYMENT_STATUS = "active"
_RUNTIME_TARGET_SNAPSHOT_METADATA_KEY = "runtime_target_snapshot"


@dataclass(frozen=True)
class YoloXDeploymentInstanceCreateRequest:
    """描述一次 DeploymentInstance 创建请求。

    字段：
    - project_id：所属 Project id。
    - model_version_id：直接绑定的 ModelVersion id。
    - model_build_id：直接绑定的 ModelBuild id。
    - runtime_profile_id：可选 RuntimeProfile id。
    - runtime_backend：运行时 backend；当前仅支持 pytorch。
    - device_name：默认 device 名称。
    - display_name：可选展示名称。
    - metadata：附加元数据。
    """

    project_id: str
    model_version_id: str | None = None
    model_build_id: str | None = None
    runtime_profile_id: str | None = None
    runtime_backend: str | None = None
    device_name: str | None = None
    display_name: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXDeploymentInstanceView:
    """描述 DeploymentInstance 对外视图。

    字段：
    - deployment_instance_id：DeploymentInstance id。
    - project_id：所属 Project id。
    - display_name：展示名称。
    - status：部署实例状态。
    - model_id：关联 Model id。
    - model_version_id：绑定的 ModelVersion id。
    - model_build_id：绑定的 ModelBuild id。
    - model_name：模型名。
    - model_scale：模型 scale。
    - task_type：任务类型。
    - source_kind：ModelVersion 来源类型。
    - runtime_profile_id：RuntimeProfile id。
    - runtime_backend：运行时 backend。
    - device_name：默认 device 名称。
    - input_size：输入尺寸。
    - labels：类别列表。
    - created_at：创建时间。
    - updated_at：最后更新时间。
    - created_by：创建主体 id。
    - metadata：附加元数据。
    """

    deployment_instance_id: str
    project_id: str
    display_name: str
    status: str
    model_id: str
    model_version_id: str
    model_build_id: str | None
    model_name: str
    model_scale: str
    task_type: str
    source_kind: str
    runtime_profile_id: str | None
    runtime_backend: str
    device_name: str
    input_size: tuple[int, int]
    labels: tuple[str, ...]
    created_at: str
    updated_at: str
    created_by: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class SqlAlchemyYoloXDeploymentService:
    """使用 SQLAlchemy 和本地文件存储实现最小 DeploymentInstance 服务。"""

    def __init__(self, *, session_factory: SessionFactory, dataset_storage: LocalDatasetStorage) -> None:
        """初始化部署实例服务。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：本地文件存储服务。
        """

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage

    def create_deployment_instance(
        self,
        request: YoloXDeploymentInstanceCreateRequest,
        *,
        created_by: str | None,
    ) -> YoloXDeploymentInstanceView:
        """创建一个最小 DeploymentInstance。"""

        self._validate_create_request(request)
        runtime_target = self._resolve_create_target(request)
        now = _now_isoformat()
        deployment_instance = DeploymentInstance(
            deployment_instance_id=f"deployment-instance-{uuid4().hex}",
            project_id=request.project_id,
            model_id=runtime_target.model_id,
            model_version_id=runtime_target.model_version_id,
            model_build_id=runtime_target.model_build_id,
            runtime_profile_id=runtime_target.runtime_profile_id,
            runtime_backend=runtime_target.runtime_backend,
            device_name=runtime_target.device_name,
            status=_ACTIVE_DEPLOYMENT_STATUS,
            display_name=request.display_name.strip() or runtime_target.model_name,
            created_at=now,
            updated_at=now,
            created_by=_normalize_optional_str(created_by),
            metadata=self._build_internal_metadata(
                user_metadata=request.metadata,
                runtime_target=runtime_target,
            ),
        )
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.deployments.save_deployment_instance(deployment_instance)
            unit_of_work.commit()

        return self._build_view(deployment_instance, runtime_target)

    def get_deployment_instance(self, deployment_instance_id: str) -> YoloXDeploymentInstanceView:
        """按 id 读取 DeploymentInstance。"""

        deployment_instance = self._require_deployment_instance(deployment_instance_id)
        return self._build_view(
            deployment_instance,
            self._resolve_target_from_instance(deployment_instance),
        )

    def list_deployment_instances(
        self,
        *,
        project_id: str,
        model_version_id: str | None = None,
        model_build_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> tuple[YoloXDeploymentInstanceView, ...]:
        """按公开筛选条件列出 DeploymentInstance。"""

        if not project_id.strip():
            raise InvalidRequestError("查询部署实例列表时 project_id 不能为空")
        if limit <= 0:
            raise InvalidRequestError("limit 必须大于 0")

        with self._open_unit_of_work() as unit_of_work:
            deployment_instances = unit_of_work.deployments.list_deployment_instances(project_id)

        matched = []
        for deployment_instance in deployment_instances:
            if model_version_id is not None and deployment_instance.model_version_id != model_version_id:
                continue
            if model_build_id is not None and deployment_instance.model_build_id != model_build_id:
                continue
            if status is not None and deployment_instance.status != status:
                continue
            matched.append(
                self._build_view(
                    deployment_instance,
                    self._resolve_target_from_instance(deployment_instance),
                )
            )
        return tuple(matched[:limit])

    def resolve_inference_target(self, deployment_instance_id: str) -> RuntimeTargetSnapshot:
        """把 DeploymentInstance 解析为内部推理快照。"""

        deployment_instance = self._require_deployment_instance(deployment_instance_id)
        return self._resolve_target_from_instance(deployment_instance)

    def _validate_create_request(self, request: YoloXDeploymentInstanceCreateRequest) -> None:
        """校验 DeploymentInstance 创建请求。"""

        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not _normalize_optional_str(request.model_version_id) and not _normalize_optional_str(request.model_build_id):
            raise InvalidRequestError("model_version_id 和 model_build_id 至少需要提供一个")

    def _resolve_create_target(
        self,
        request: YoloXDeploymentInstanceCreateRequest,
    ) -> RuntimeTargetSnapshot:
        """根据创建请求解析 DeploymentInstance 对应的运行时快照。"""

        return SqlAlchemyYoloXRuntimeTargetResolver(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
        ).resolve_target(
            RuntimeTargetResolveRequest(
                project_id=request.project_id,
                model_version_id=request.model_version_id,
                model_build_id=request.model_build_id,
                runtime_profile_id=request.runtime_profile_id,
                runtime_backend=request.runtime_backend,
                device_name=request.device_name,
            )
        )

    def _require_deployment_instance(self, deployment_instance_id: str) -> DeploymentInstance:
        """按 id 读取并校验 DeploymentInstance。"""

        with self._open_unit_of_work() as unit_of_work:
            deployment_instance = unit_of_work.deployments.get_deployment_instance(deployment_instance_id)
        if deployment_instance is None:
            raise ResourceNotFoundError(
                "找不到指定的 DeploymentInstance",
                details={"deployment_instance_id": deployment_instance_id},
            )
        return deployment_instance

    def _resolve_target_from_instance(
        self,
        deployment_instance: DeploymentInstance,
    ) -> RuntimeTargetSnapshot:
        """根据已保存的 DeploymentInstance 解析运行时快照。"""

        payload = deployment_instance.metadata.get(_RUNTIME_TARGET_SNAPSHOT_METADATA_KEY)
        try:
            return deserialize_runtime_target_snapshot(
                payload=payload,
                dataset_storage=self.dataset_storage,
            )
        except InvalidRequestError as error:
            raise ServiceConfigurationError(
                "DeploymentInstance 缺少合法的 runtime_target_snapshot",
                details={"deployment_instance_id": deployment_instance.deployment_instance_id},
            ) from error

    def _build_internal_metadata(
        self,
        *,
        user_metadata: object,
        runtime_target: RuntimeTargetSnapshot,
    ) -> dict[str, object]:
        """合并用户 metadata 与内部运行时快照。"""

        normalized_metadata = _normalize_metadata(user_metadata)
        normalized_metadata[_RUNTIME_TARGET_SNAPSHOT_METADATA_KEY] = serialize_runtime_target_snapshot(runtime_target)
        return normalized_metadata

    @staticmethod
    def _build_public_metadata(metadata: object) -> dict[str, object]:
        """过滤仅用于内部执行的 metadata 字段。"""

        normalized_metadata = _normalize_metadata(metadata)
        normalized_metadata.pop(_RUNTIME_TARGET_SNAPSHOT_METADATA_KEY, None)
        return normalized_metadata

    @staticmethod
    def _build_view(
        deployment_instance: DeploymentInstance,
        runtime_target: RuntimeTargetSnapshot,
    ) -> YoloXDeploymentInstanceView:
        """把 DeploymentInstance 转换为公开视图。"""

        return YoloXDeploymentInstanceView(
            deployment_instance_id=deployment_instance.deployment_instance_id,
            project_id=deployment_instance.project_id,
            display_name=deployment_instance.display_name,
            status=deployment_instance.status,
            model_id=deployment_instance.model_id,
            model_version_id=deployment_instance.model_version_id,
            model_build_id=deployment_instance.model_build_id,
            model_name=runtime_target.model_name,
            model_scale=runtime_target.model_scale,
            task_type=runtime_target.task_type,
            source_kind=runtime_target.source_kind,
            runtime_profile_id=runtime_target.runtime_profile_id,
            runtime_backend=runtime_target.runtime_backend,
            device_name=runtime_target.device_name,
            input_size=runtime_target.input_size,
            labels=runtime_target.labels,
            created_at=deployment_instance.created_at,
            updated_at=deployment_instance.updated_at,
            created_by=deployment_instance.created_by,
            metadata=SqlAlchemyYoloXDeploymentService._build_public_metadata(deployment_instance.metadata),
        )

    @contextmanager
    def _open_unit_of_work(self) -> Iterator[SqlAlchemyUnitOfWork]:
        """返回一个新的 Unit of Work 并在退出时关闭会话。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            yield unit_of_work
        finally:
            unit_of_work.close()


def _normalize_optional_str(value: str | None) -> str | None:
    """把可选字符串去空白后返回。"""

    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _normalize_metadata(metadata: object) -> dict[str, object]:
    """把 metadata 归一为普通字典。"""

    if not isinstance(metadata, dict):
        return {}
    return {str(key): value for key, value in metadata.items()}


def _now_isoformat() -> str:
    """返回带时区的当前 UTC ISO 时间字符串。"""

    return datetime.now(timezone.utc).isoformat()