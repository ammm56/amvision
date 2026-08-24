"""通用模型登记服务接口定义。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Protocol
from urllib.parse import urlparse
from uuid import uuid4

from backend.contracts.files.yolox_model_files import (
    YoloXFileNamingContext,
    build_default_file_name,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.project_mutation import ProjectMutationAdmissionService
from backend.service.domain.files.detection_model_file_types import (
    DetectionModelFileTypes,
    YOLOX_DETECTION_FILE_TYPES,
)
from backend.service.domain.files.model_file import ModelFile
from backend.service.domain.models.model_records import (
    PLATFORM_BASE_MODEL_SCOPE,
    PROJECT_MODEL_SCOPE,
    Model,
    ModelBuild,
    ModelScopeKind,
    ModelVersion,
)
from backend.service.domain.models.model_artifact_provenance import (
    attach_model_artifact_provenance,
)
from backend.service.domain.models.model_input_spec import (
    ModelInputSpec,
    SpatialSize,
    build_platform_model_input_spec,
    resolve_yolo_default_spatial_size,
)
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE
from backend.service.domain.models.yolox_model_spec import (
    DEFAULT_YOLOX_MODEL_SPEC,
    YoloXModelSpec,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


_MODEL_BUILD_RUNTIME_BACKEND_BY_FORMAT = {
    "onnx": "onnxruntime",
    "onnx-optimized": "onnxruntime",
    "openvino-ir": "openvino",
    "tensorrt-engine": "tensorrt",
    "rknn": "rknn",
}
_MODEL_BUILD_RUNTIME_PRECISIONS_BY_FORMAT = {
    "onnx": frozenset({"fp32"}),
    "onnx-optimized": frozenset({"fp32"}),
    "openvino-ir": frozenset({"fp32", "fp16"}),
    "tensorrt-engine": frozenset({"fp32", "fp16"}),
    "rknn": frozenset({"fp32"}),
}
_MODEL_INPUT_CONTRACT_TYPES = frozenset(
    {"yolov8", "yolo11", "yolo26", "yolox", "rfdetr"}
)


@dataclass(frozen=True)
class PretrainedRegistrationRequest:
    """描述一次预置预训练模型登记请求。

    字段：
    - model_name：登记到平台的模型名。
    - storage_uri：预训练模型在磁盘或对象存储中的现成位置。
    - model_version_id：可选的稳定 ModelVersion id。
    - checkpoint_file_id：可选的稳定 checkpoint 文件 id。
    - model_scale：模型 scale。
    - task_type：任务类型。
    - metadata：附加元数据。
    """

    model_name: str
    storage_uri: str
    model_scale: str
    model_version_id: str | None = None
    checkpoint_file_id: str | None = None
    task_type: str = DETECTION_TASK_TYPE
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TrainingOutputRegistration:
    """描述训练输出登记请求。

    字段：
    - project_id：所属项目 id。
    - training_task_id：训练任务 id。
    - model_version_id：可选的目标 ModelVersion id；用于把训练输出更新到现有版本。
    - model_name：登记到平台的模型名。
    - model_scale：模型 scale。
    - dataset_version_id：训练使用的 DatasetVersion id。
    - parent_version_id：warm start 或 lineage 对应的父 ModelVersion id。
    - checkpoint_file_id：checkpoint 文件 id。
    - checkpoint_file_uri：checkpoint 文件存储 URI。
    - task_type：任务分类。
    - labels_file_id：标签文件 id。
    - labels_file_uri：标签文件存储 URI。
    - metrics_file_id：指标文件 id。
    - metrics_file_uri：指标文件存储 URI。
    - metadata：附加元数据。
    """

    project_id: str
    training_task_id: str
    model_name: str
    model_scale: str
    dataset_version_id: str
    checkpoint_file_id: str
    task_type: str = DETECTION_TASK_TYPE
    model_version_id: str | None = None
    parent_version_id: str | None = None
    checkpoint_file_uri: str | None = None
    labels_file_id: str | None = None
    labels_file_uri: str | None = None
    metrics_file_id: str | None = None
    metrics_file_uri: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelBuildRegistration:
    """描述模型 build 登记请求。

    字段：
    - project_id：所属项目 id。
    - source_model_version_id：来源 ModelVersion id。
    - build_format：build 格式。
    - runtime_backend：部署运行 backend。
    - runtime_precision：部署运行 precision。
    - build_file_id：build 文件 id。
    - build_file_uri：build 文件 URI。
    - runtime_profile_id：目标 RuntimeProfile id。
    - conversion_task_id：来源转换任务 id。
    - metadata：附加元数据。
    """

    project_id: str
    source_model_version_id: str
    build_format: str
    runtime_backend: str
    runtime_precision: str
    build_file_id: str
    build_file_uri: str | None = None
    runtime_profile_id: str | None = None
    conversion_task_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PlatformBaseModelFileView:
    """描述平台基础模型查询结果中的文件条目。

    字段：
    - file_id：文件记录 id。
    - project_id：所属 Project id；平台基础模型文件时为空。
    - scope_kind：文件所属模型作用域类型。
    - model_id：所属 Model id。
    - model_version_id：所属 ModelVersion id。
    - model_build_id：所属 ModelBuild id。
    - file_type：文件类型。
    - logical_name：文件逻辑名。
    - storage_uri：文件存储 URI。
    - metadata：附加元数据。
    """

    file_id: str
    project_id: str | None
    scope_kind: ModelScopeKind
    model_id: str
    model_version_id: str | None
    model_build_id: str | None
    file_type: str
    logical_name: str
    storage_uri: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PlatformBaseModelVersionSummaryView:
    """描述平台基础模型列表中的版本摘要。

    字段：
    - model_version_id：ModelVersion id。
    - source_kind：版本来源类型。
    - dataset_version_id：关联 DatasetVersion id。
    - training_task_id：关联训练任务 id。
    - parent_version_id：父 ModelVersion id。
    - file_ids：关联文件 id 列表。
    - metadata：附加元数据。
    - checkpoint_file_id：checkpoint 文件 id。
    - checkpoint_storage_uri：checkpoint 存储 URI。
    - catalog_manifest_object_key：预训练目录 manifest object key。
    """

    model_version_id: str
    source_kind: str
    dataset_version_id: str | None
    training_task_id: str | None
    parent_version_id: str | None
    file_ids: tuple[str, ...]
    metadata: dict[str, object] = field(default_factory=dict)
    checkpoint_file_id: str | None = None
    checkpoint_storage_uri: str | None = None
    catalog_manifest_object_key: str | None = None


@dataclass(frozen=True)
class PlatformBaseModelVersionDetailView:
    """描述平台基础模型详情中的版本条目。

    字段：
    - model_version_id：ModelVersion id。
    - source_kind：版本来源类型。
    - dataset_version_id：关联 DatasetVersion id。
    - training_task_id：关联训练任务 id。
    - parent_version_id：父 ModelVersion id。
    - file_ids：关联文件 id 列表。
    - metadata：附加元数据。
    - checkpoint_file_id：checkpoint 文件 id。
    - checkpoint_storage_uri：checkpoint 存储 URI。
    - catalog_manifest_object_key：预训练目录 manifest object key。
    - files：当前版本关联的文件明细。
    """

    model_version_id: str
    source_kind: str
    dataset_version_id: str | None
    training_task_id: str | None
    parent_version_id: str | None
    file_ids: tuple[str, ...]
    metadata: dict[str, object] = field(default_factory=dict)
    checkpoint_file_id: str | None = None
    checkpoint_storage_uri: str | None = None
    catalog_manifest_object_key: str | None = None
    files: tuple[PlatformBaseModelFileView, ...] = ()


@dataclass(frozen=True)
class PlatformBaseModelBuildView:
    """描述平台基础模型详情中的构建条目。

    字段：
    - model_build_id：ModelBuild id。
    - source_model_version_id：来源 ModelVersion id。
    - build_format：构建格式。
    - runtime_backend：部署运行 backend。
    - runtime_precision：部署运行 precision。
    - runtime_profile_id：目标 RuntimeProfile id。
    - conversion_task_id：来源转换任务 id。
    - file_ids：关联文件 id 列表。
    - metadata：附加元数据。
    - files：当前构建关联的文件明细。
    """

    model_build_id: str
    source_model_version_id: str
    build_format: str
    runtime_backend: str
    runtime_precision: str
    runtime_profile_id: str | None
    conversion_task_id: str | None
    file_ids: tuple[str, ...]
    metadata: dict[str, object] = field(default_factory=dict)
    files: tuple[PlatformBaseModelFileView, ...] = ()


@dataclass(frozen=True)
class PlatformBaseModelSummaryView:
    """描述平台基础模型列表项。

    字段：
    - model_id：Model id。
    - project_id：所属 Project id；平台基础模型时为空。
    - scope_kind：模型作用域类型。
    - model_name：模型名。
    - model_type：模型类型名称。
    - task_type：任务类型。
    - model_scale：模型 scale。
    - labels_file_id：标签文件 id。
    - metadata：附加元数据。
    - version_count：关联 ModelVersion 数量。
    - build_count：关联 ModelBuild 数量。
    - available_versions：可用于 warm start 的版本摘要列表。
    """

    model_id: str
    project_id: str | None
    scope_kind: ModelScopeKind
    model_name: str
    model_type: str
    task_type: str
    model_scale: str
    labels_file_id: str | None
    metadata: dict[str, object] = field(default_factory=dict)
    version_count: int = 0
    build_count: int = 0
    available_versions: tuple[PlatformBaseModelVersionSummaryView, ...] = ()


@dataclass(frozen=True)
class PlatformBaseModelDetailView:
    """描述平台基础模型详情。

    字段：
    - model_id：Model id。
    - project_id：所属 Project id；平台基础模型时为空。
    - scope_kind：模型作用域类型。
    - model_name：模型名。
    - model_type：模型类型名称。
    - task_type：任务类型。
    - model_scale：模型 scale。
    - labels_file_id：标签文件 id。
    - metadata：附加元数据。
    - version_count：关联 ModelVersion 数量。
    - build_count：关联 ModelBuild 数量。
    - available_versions：可用于 warm start 的版本摘要列表。
    - versions：完整版本明细。
    - builds：完整构建明细。
    """

    model_id: str
    project_id: str | None
    scope_kind: ModelScopeKind
    model_name: str
    model_type: str
    task_type: str
    model_scale: str
    labels_file_id: str | None
    metadata: dict[str, object] = field(default_factory=dict)
    version_count: int = 0
    build_count: int = 0
    available_versions: tuple[PlatformBaseModelVersionSummaryView, ...] = ()
    versions: tuple[PlatformBaseModelVersionDetailView, ...] = ()
    builds: tuple[PlatformBaseModelBuildView, ...] = ()


class ModelService(Protocol):
    """通用模型登记接口。"""

    def register_pretrained(self, request: PretrainedRegistrationRequest) -> str:
        """登记预置预训练模型并返回模型版本 id。

        参数：
        - request：预置预训练模型登记请求。

        返回：
        - 新登记的 ModelVersion id。
        """

        ...

    def register_training_output(self, request: TrainingOutputRegistration) -> str:
        """登记训练输出并返回新的模型版本 id。

        参数：
        - request：训练输出登记请求。

        返回：
        - 新登记的 ModelVersion id。
        """

        ...

    def register_build(self, request: ModelBuildRegistration) -> str:
        """登记模型 build 并返回新的 ModelBuild id。

        参数：
        - request：模型 build 登记请求。

        返回：
        - 新登记的 ModelBuild id。
        """

        ...

    def register_builds(
        self,
        requests: tuple[ModelBuildRegistration, ...],
    ) -> tuple[str, ...]:
        """在一个 Unit of Work 中登记同一次 conversion 的全部 build。"""

        ...

    def list_model_builds_by_conversion_task_id(
        self,
        conversion_task_id: str,
    ) -> tuple[ModelBuild, ...]:
        """读取同一 conversion 已原子登记的全部 build。"""

        ...


class SqlAlchemyModelService:
    """使用 SQLAlchemy Repository 与 Unit of Work 实现通用模型登记。"""

    def __init__(
        self,
        session_factory: SessionFactory,
        spec: YoloXModelSpec = DEFAULT_YOLOX_MODEL_SPEC,
        file_types: DetectionModelFileTypes = YOLOX_DETECTION_FILE_TYPES,
    ) -> None:
        """初始化基于 SQLAlchemy 的模型登记服务。

        参数：
        - session_factory：用于创建数据库会话的工厂。
        - spec：当前使用的模型规格。
        - file_types：当前 detection 模型分类使用的文件类型集合。
        """

        self.session_factory = session_factory
        self.spec = spec
        self.file_types = file_types
        self.project_mutations = ProjectMutationAdmissionService(session_factory)

    def register_pretrained(self, request: PretrainedRegistrationRequest) -> str:
        """登记预置预训练模型并返回模型版本 id。

        参数：
        - request：预置预训练模型登记请求。

        返回：
        - 新登记的 ModelVersion id。
        """

        self._validate_task_type(request.task_type)
        self._validate_model_scale(request.model_scale)
        with self._open_unit_of_work() as unit_of_work:
            model_version_id = request.model_version_id or self._next_id(
                "model-version"
            )
            checkpoint_file_id = request.checkpoint_file_id or self._next_id(
                "model-file"
            )
            pretrained_metadata = self._build_pretrained_metadata(
                request.metadata,
                task_type=request.task_type,
                model_scale=request.model_scale,
            )
            model = self._ensure_model(
                unit_of_work=unit_of_work,
                project_id=None,
                scope_kind=PLATFORM_BASE_MODEL_SCOPE,
                model_name=request.model_name,
                model_scale=request.model_scale,
                task_type=request.task_type,
                labels_file_id=None,
                metadata=pretrained_metadata,
            )
            checkpoint_file = self._create_model_file(
                unit_of_work=unit_of_work,
                file_id=checkpoint_file_id,
                project_id=None,
                scope_kind=PLATFORM_BASE_MODEL_SCOPE,
                model_id=model.model_id,
                model_version_id=model_version_id,
                file_type=self.file_types.checkpoint_file_type,
                logical_name=build_default_file_name(
                    YoloXFileNamingContext(
                        model_name=request.model_name,
                        model_scale=request.model_scale,
                        source_version=model_version_id,
                        file_kind=self.file_types.checkpoint_file_type,
                        suffix=self._guess_suffix(request.storage_uri),
                    )
                ),
                storage_uri=request.storage_uri,
                metadata={"source_kind": "pretrained-reference"},
            )
            model_version = ModelVersion(
                model_version_id=model_version_id,
                model_id=model.model_id,
                source_kind="pretrained-reference",
                file_ids=(checkpoint_file.file_id,),
                metadata=pretrained_metadata,
            )
            unit_of_work.models.save_model_version(model_version)
            unit_of_work.commit()

            return model_version_id

    def register_training_output(self, request: TrainingOutputRegistration) -> str:
        """在 Project 删除边界内登记训练输出。"""

        resource_id = (
            request.model_version_id
            or request.checkpoint_file_id
            or request.training_task_id
        )
        with self.project_mutations.operation(
            project_id=request.project_id,
            mutation_kind="model-training-output",
            resource_id=resource_id,
        ):
            return self._register_training_output(request)

    def _register_training_output(self, request: TrainingOutputRegistration) -> str:
        """登记训练输出并返回新的模型版本 id。

        参数：
        - request：训练输出登记请求。

        返回：
        - 新登记的 ModelVersion id。
        """

        self._validate_model_scale(request.model_scale)
        with self._open_unit_of_work() as unit_of_work:
            self._validate_task_type(request.task_type)
            model_version_id = request.model_version_id or self._next_id(
                "model-version"
            )
            normalized_training_metadata = self._normalize_yolo_version_input_metadata(
                request.metadata,
                task_type=request.task_type,
                allow_default=False,
            )
            training_metadata = attach_model_artifact_provenance(
                normalized_training_metadata,
                artifact_kind="training-output",
                trace={
                    "model_version_id": model_version_id,
                    "training_task_id": request.training_task_id,
                    "dataset_version_id": request.dataset_version_id,
                },
            )
            model = self._ensure_model(
                unit_of_work=unit_of_work,
                project_id=request.project_id,
                scope_kind=PROJECT_MODEL_SCOPE,
                model_name=request.model_name,
                model_scale=request.model_scale,
                task_type=request.task_type,
                labels_file_id=request.labels_file_id,
                metadata=training_metadata,
            )
            self._validate_parent_model_version(
                unit_of_work=unit_of_work,
                parent_version_id=request.parent_version_id,
                model_version_id=model_version_id,
                project_id=request.project_id,
            )
            file_ids = self._register_training_files(
                unit_of_work=unit_of_work,
                model_id=model.model_id,
                model_name=request.model_name,
                model_scale=request.model_scale,
                project_id=request.project_id,
                scope_kind=PROJECT_MODEL_SCOPE,
                model_version_id=model_version_id,
                checkpoint_file_id=request.checkpoint_file_id,
                checkpoint_file_uri=request.checkpoint_file_uri,
                labels_file_id=request.labels_file_id,
                labels_file_uri=request.labels_file_uri,
                metrics_file_id=request.metrics_file_id,
                metrics_file_uri=request.metrics_file_uri,
                provenance_trace={
                    "model_version_id": model_version_id,
                    "training_task_id": request.training_task_id,
                    "dataset_version_id": request.dataset_version_id,
                },
            )
            model_version = ModelVersion(
                model_version_id=model_version_id,
                model_id=model.model_id,
                source_kind="training-output",
                dataset_version_id=request.dataset_version_id,
                training_task_id=request.training_task_id,
                parent_version_id=request.parent_version_id,
                file_ids=file_ids,
                metadata=training_metadata,
            )
            unit_of_work.models.save_model_version(model_version)
            unit_of_work.commit()

            return model_version_id

    def register_build(self, request: ModelBuildRegistration) -> str:
        """在 Project 删除边界内登记转换 build。"""

        return self.register_builds((request,))[0]

    def register_builds(
        self,
        requests: tuple[ModelBuildRegistration, ...],
    ) -> tuple[str, ...]:
        """在 Project 删除边界内原子登记一批 ModelBuild/ModelFile。"""

        if not requests:
            return ()
        project_ids = {request.project_id for request in requests}
        if len(project_ids) != 1:
            raise InvalidRequestError(
                "同一批模型 build 必须属于同一个 Project",
                details={"project_ids": sorted(project_ids)},
            )
        project_id = requests[0].project_id
        mutation_resource_id = (
            requests[0].conversion_task_id or requests[0].build_file_id
        )
        with self.project_mutations.operation(
            project_id=project_id,
            mutation_kind="model-build",
            resource_id=mutation_resource_id,
        ):
            with self._open_unit_of_work() as unit_of_work:
                model_build_ids = tuple(
                    self._stage_build(
                        unit_of_work=unit_of_work,
                        request=request,
                    )
                    for request in requests
                )
                unit_of_work.commit()
                return model_build_ids

    def stage_builds(
        self,
        *,
        unit_of_work: SqlAlchemyUnitOfWork,
        requests: tuple[ModelBuildRegistration, ...],
    ) -> tuple[str, ...]:
        """在调用方持有的 Unit of Work 中暂存整批 ModelBuild/ModelFile。"""

        if not requests:
            return ()
        project_ids = {request.project_id for request in requests}
        if len(project_ids) != 1:
            raise InvalidRequestError("同一批模型 build 必须属于同一个 Project")
        return tuple(
            self._stage_build(unit_of_work=unit_of_work, request=request)
            for request in requests
        )

    def _stage_build(
        self,
        *,
        unit_of_work: SqlAlchemyUnitOfWork,
        request: ModelBuildRegistration,
    ) -> str:
        """在现有 Unit of Work 中暂存一个 ModelBuild 和对应 ModelFile。

        参数：
        - unit_of_work：承载整批 build 的 Unit of Work。
        - request：模型 build 登记请求。

        返回：
        - 暂存的 ModelBuild id。
        """

        build_format = request.build_format.strip().lower()
        self._validate_build_format(build_format)
        runtime_backend = self._validate_build_runtime_backend(
            build_format=build_format,
            runtime_backend=request.runtime_backend,
        )
        runtime_precision = self._validate_build_runtime_precision(
            build_format=build_format,
            runtime_precision=request.runtime_precision,
        )
        source_version = unit_of_work.models.get_visible_model_version(
            request.source_model_version_id,
            (request.project_id,),
        )
        if source_version is None:
            raise ValueError(
                f"未知的 ModelVersion: {request.source_model_version_id}"
            )

        model = unit_of_work.models.get_visible_model(
            source_version.model_id,
            (request.project_id,),
        )
        if model is None:
            raise ValueError(f"未知的 Model: {source_version.model_id}")

        model_build_id = self._next_id("model-build")
        normalized_build_metadata = self._normalize_yolo_build_input_metadata(
            source_version_metadata=source_version.metadata,
            build_metadata=request.metadata,
        )
        build_metadata = attach_model_artifact_provenance(
            self._strip_deprecated_build_runtime_metadata(
                normalized_build_metadata
            ),
            artifact_kind="converted-model",
            trace={
                "model_build_id": model_build_id,
                "source_model_version_id": request.source_model_version_id,
                "conversion_task_id": request.conversion_task_id,
                "build_format": build_format,
            },
        )
        build_file = self._create_model_file(
            unit_of_work=unit_of_work,
            file_id=request.build_file_id,
            project_id=model.project_id,
            scope_kind=model.scope_kind,
            model_id=model.model_id,
            model_build_id=model_build_id,
            file_type=self._resolve_build_file_type(build_format),
            logical_name=build_default_file_name(
                YoloXFileNamingContext(
                    model_name=model.model_name,
                    model_scale=model.model_scale,
                    source_version=source_version.model_version_id,
                    file_kind=build_format,
                    suffix=self._guess_suffix(
                        request.build_file_uri or request.build_file_id
                    ),
                )
            ),
            storage_uri=request.build_file_uri
            or f"registered://{request.build_file_id}",
            metadata=attach_model_artifact_provenance(
                {"build_format": build_format},
                artifact_kind="converted-model-file",
                trace={
                    "model_build_id": model_build_id,
                    "source_model_version_id": request.source_model_version_id,
                    "conversion_task_id": request.conversion_task_id,
                    "build_format": build_format,
                },
            ),
        )
        model_build = ModelBuild(
            model_build_id=model_build_id,
            model_id=model.model_id,
            source_model_version_id=request.source_model_version_id,
            build_format=build_format,
            runtime_backend=runtime_backend,
            runtime_precision=runtime_precision,
            runtime_profile_id=request.runtime_profile_id,
            conversion_task_id=request.conversion_task_id,
            file_ids=(build_file.file_id,),
            metadata=build_metadata,
        )
        unit_of_work.models.save_model_build(model_build)
        return model_build_id

    def get_model(self, model_id: str) -> Model | None:
        """按 id 读取 Model。

        参数：
        - model_id：Model id。

        返回：
        - 对应的 Model；不存在时返回 None。
        """

        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.models.get_model(model_id)

    def get_visible_model(
        self,
        model_id: str,
        *,
        visible_project_ids: tuple[str, ...],
    ) -> Model | None:
        """按 Project 可见范围读取 Model；平台基础模型始终可见。"""

        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.models.get_visible_model(
                model_id,
                visible_project_ids,
            )

    def get_model_version(self, model_version_id: str) -> ModelVersion | None:
        """按 id 读取 ModelVersion。

        参数：
        - model_version_id：ModelVersion id。

        返回：
        - 对应的 ModelVersion；不存在时返回 None。
        """

        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.models.get_model_version(model_version_id)

    def get_visible_model_version(
        self,
        model_version_id: str,
        *,
        visible_project_ids: tuple[str, ...],
    ) -> ModelVersion | None:
        """按所属 Model 的 Project 可见范围读取 ModelVersion。"""

        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.models.get_visible_model_version(
                model_version_id,
                visible_project_ids,
            )

    def get_model_build(self, model_build_id: str) -> ModelBuild | None:
        """按 id 读取 ModelBuild。

        参数：
        - model_build_id：ModelBuild id。

        返回：
        - 对应的 ModelBuild；不存在时返回 None。
        """

        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.models.get_model_build(model_build_id)

    def list_model_builds_by_conversion_task_id(
        self,
        conversion_task_id: str,
    ) -> tuple[ModelBuild, ...]:
        """按 conversion task id 读取已经原子提交的全部 build。"""

        if not conversion_task_id.strip():
            raise InvalidRequestError("conversion_task_id 不能为空")
        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.models.list_model_builds_by_conversion_task_id(
                conversion_task_id
            )

    def get_visible_model_build(
        self,
        model_build_id: str,
        *,
        visible_project_ids: tuple[str, ...],
    ) -> ModelBuild | None:
        """按所属 Model 的 Project 可见范围读取 ModelBuild。"""

        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.models.get_visible_model_build(
                model_build_id,
                visible_project_ids,
            )

    def get_model_file(self, file_id: str) -> ModelFile | None:
        """按 id 读取 ModelFile。

        参数：
        - file_id：ModelFile id。

        返回：
        - 对应的 ModelFile；不存在时返回 None。
        """

        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.model_files.get_model_file(file_id)

    def get_visible_model_file(
        self,
        file_id: str,
        *,
        visible_project_ids: tuple[str, ...],
    ) -> ModelFile | None:
        """按 Project 可见范围读取 ModelFile；平台基础模型文件始终可见。"""

        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.model_files.get_visible_model_file(
                file_id,
                visible_project_ids,
            )

    def list_model_files(
        self,
        *,
        model_version_id: str | None = None,
        model_build_id: str | None = None,
    ) -> tuple[ModelFile, ...]:
        """按模型版本或 build 列出关联文件。

        参数：
        - model_version_id：需要筛选的 ModelVersion id。
        - model_build_id：需要筛选的 ModelBuild id。

        返回：
        - 过滤后的 ModelFile 列表。
        """

        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.model_files.list_model_files(
                model_version_id=model_version_id,
                model_build_id=model_build_id,
            )

    def list_visible_model_files(
        self,
        *,
        visible_project_ids: tuple[str, ...],
        model_version_id: str | None = None,
        model_build_id: str | None = None,
    ) -> tuple[ModelFile, ...]:
        """按关联资源和 Project 可见范围列出 ModelFile。"""

        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.model_files.list_visible_model_files(
                visible_project_ids=visible_project_ids,
                model_version_id=model_version_id,
                model_build_id=model_build_id,
            )

    def list_platform_base_models(
        self,
        *,
        model_name: str | None = None,
        model_scale: str | None = None,
        task_type: str | None = None,
        limit: int = 100,
    ) -> tuple[PlatformBaseModelSummaryView, ...]:
        """列出平台基础模型摘要。

        参数：
        - model_name：模型名筛选；为空时不过滤。
        - model_scale：模型 scale 筛选；为空时不过滤。
        - task_type：任务类型筛选；为空时不过滤。
        - limit：最大返回数量。

        返回：
        - 平台基础模型摘要列表。
        """

        with self._open_unit_of_work() as unit_of_work:
            models = unit_of_work.models.list_models(
                scope_kind=PLATFORM_BASE_MODEL_SCOPE,
                model_name=model_name,
                model_scale=model_scale,
                task_type=task_type,
                limit=limit,
            )
            return tuple(
                self._build_platform_base_model_summary(
                    unit_of_work=unit_of_work,
                    model=model,
                )
                for model in models
            )

    def list_deployment_source_models(
        self,
        *,
        project_id: str,
        task_type: str | None = None,
        limit: int = 100,
    ) -> tuple[PlatformBaseModelSummaryView, ...]:
        """列出部署页可选择的模型来源。

        参数：
        - project_id：当前 Project id。
        - task_type：任务类型筛选；为空时不过滤。
        - limit：最大返回数量。

        返回：
        - 当前 Project 已训练模型和平台预训练模型摘要。
        """

        with self._open_unit_of_work() as unit_of_work:
            models = unit_of_work.models.list_models(
                task_type=task_type,
                limit=None,
            )
            visible_models = tuple(
                model
                for model in models
                if (
                    (
                        model.scope_kind == PROJECT_MODEL_SCOPE
                        and model.project_id == project_id
                    )
                    or model.scope_kind == PLATFORM_BASE_MODEL_SCOPE
                )
            )
            summaries = tuple(
                self._build_platform_base_model_summary(
                    unit_of_work=unit_of_work,
                    model=model,
                )
                for model in visible_models
            )
            deployable_summaries = tuple(
                summary
                for summary in summaries
                if summary.version_count > 0 or summary.build_count > 0
            )

            return tuple(
                sorted(deployable_summaries, key=self._deployment_source_sort_key)[
                    :limit
                ]
            )

    def get_platform_base_model_detail(
        self, model_id: str
    ) -> PlatformBaseModelDetailView | None:
        """按 id 读取单个平台基础模型详情。

        参数：
        - model_id：目标 Model id。

        返回：
        - 平台基础模型详情；不存在或不是平台基础模型时返回 None。
        """

        with self._open_unit_of_work() as unit_of_work:
            model = unit_of_work.models.get_model(model_id)
            if model is None or model.scope_kind != PLATFORM_BASE_MODEL_SCOPE:
                return None

            versions = unit_of_work.models.list_model_versions(model.model_id)
            builds = unit_of_work.models.list_model_builds(model.model_id)
            available_versions = tuple(
                self._build_platform_base_model_version_summary(
                    unit_of_work=unit_of_work,
                    model_version=model_version,
                )
                for model_version in versions
            )
            version_details = tuple(
                self._build_platform_base_model_version_detail(
                    unit_of_work=unit_of_work,
                    model_version=model_version,
                )
                for model_version in versions
            )
            build_details = tuple(
                self._build_platform_base_model_build_view(
                    unit_of_work=unit_of_work,
                    model_build=model_build,
                )
                for model_build in builds
            )
            return PlatformBaseModelDetailView(
                model_id=model.model_id,
                project_id=model.project_id,
                scope_kind=model.scope_kind,
                model_name=model.model_name,
                model_type=model.model_type,
                task_type=model.task_type,
                model_scale=model.model_scale,
                labels_file_id=model.labels_file_id,
                metadata=dict(model.metadata),
                version_count=len(versions),
                build_count=len(builds),
                available_versions=available_versions,
                versions=version_details,
                builds=build_details,
            )

    def get_deployment_source_model_detail(
        self,
        *,
        project_id: str,
        model_id: str,
    ) -> PlatformBaseModelDetailView | None:
        """读取部署页可选择的单个模型来源详情。

        参数：
        - project_id：当前 Project id。
        - model_id：目标 Model id。

        返回：
        - 模型来源详情；不属于当前 Project 且不是平台预训练模型时返回 None。
        """

        with self._open_unit_of_work() as unit_of_work:
            model = unit_of_work.models.get_visible_model(
                model_id,
                (project_id,),
            )
            if model is None:
                return None
            if (
                model.scope_kind == PROJECT_MODEL_SCOPE
                and model.project_id != project_id
            ):
                return None
            if (
                model.scope_kind != PROJECT_MODEL_SCOPE
                and model.scope_kind != PLATFORM_BASE_MODEL_SCOPE
            ):
                return None

            versions = unit_of_work.models.list_model_versions(model.model_id)
            builds = unit_of_work.models.list_model_builds(model.model_id)
            if not versions and not builds:
                return None

            available_versions = tuple(
                self._build_platform_base_model_version_summary(
                    unit_of_work=unit_of_work,
                    model_version=model_version,
                )
                for model_version in versions
            )
            version_details = tuple(
                self._build_platform_base_model_version_detail(
                    unit_of_work=unit_of_work,
                    model_version=model_version,
                )
                for model_version in versions
            )
            build_details = tuple(
                self._build_platform_base_model_build_view(
                    unit_of_work=unit_of_work,
                    model_build=model_build,
                )
                for model_build in builds
            )
            return PlatformBaseModelDetailView(
                model_id=model.model_id,
                project_id=model.project_id,
                scope_kind=model.scope_kind,
                model_name=model.model_name,
                model_type=model.model_type,
                task_type=model.task_type,
                model_scale=model.model_scale,
                labels_file_id=model.labels_file_id,
                metadata=dict(model.metadata),
                version_count=len(versions),
                build_count=len(builds),
                available_versions=available_versions,
                versions=version_details,
                builds=build_details,
            )

    def _ensure_model(
        self,
        *,
        unit_of_work: SqlAlchemyUnitOfWork,
        project_id: str | None,
        scope_kind: ModelScopeKind,
        model_name: str,
        model_scale: str,
        task_type: str,
        labels_file_id: str | None,
        metadata: dict[str, object],
    ) -> Model:
        """确保数据库中存在对应的 Model 对象。

            参数：
            - unit_of_work：当前请求级 Unit of Work。
        - project_id：所属项目 id；平台基础模型时为空。
            - scope_kind：模型作用域类型。
            - model_name：模型名。
            - model_scale：模型 scale。
            - task_type：任务类型。
            - labels_file_id：标签文件 id。
            - metadata：附加元数据。

            返回：
            - 已存在或新建的 Model。
        """

        self._validate_task_type(task_type)
        self._validate_model_scale(model_scale)
        model = unit_of_work.models.find_model(
            project_id=project_id,
            scope_kind=scope_kind,
            model_name=model_name,
            model_scale=model_scale,
            task_type=task_type,
        )
        if model is not None:
            return model

        model = Model(
            model_id=self._next_id("model"),
            project_id=project_id,
            scope_kind=scope_kind,
            model_name=model_name,
            model_type=self.spec.model_name,
            task_type=task_type,
            model_scale=model_scale,
            labels_file_id=labels_file_id,
            metadata=metadata,
        )
        unit_of_work.models.save_model(model)

        return model

    @staticmethod
    def _validate_parent_model_version(
        *,
        unit_of_work: SqlAlchemyUnitOfWork,
        parent_version_id: str | None,
        model_version_id: str,
        project_id: str,
    ) -> None:
        """校验 warm start 父版本存在且不是当前待创建版本。"""

        if parent_version_id is None:
            return
        if parent_version_id == model_version_id:
            raise ValueError("父 ModelVersion 不能与当前 ModelVersion 相同")
        parent_version = unit_of_work.models.get_visible_model_version(
            parent_version_id,
            (project_id,),
        )
        if parent_version is None:
            raise ValueError(f"未知的父 ModelVersion: {parent_version_id}")

    def _validate_task_type(self, task_type: str) -> None:
        """校验传入任务类型是否被当前规格支持。"""

        if not self.spec.supports_task_type(task_type):
            raise ValueError(f"不支持的任务类型: {task_type}")

    def _validate_model_scale(self, model_scale: str) -> None:
        """校验传入模型 scale 是否被当前规格支持。"""

        if not self.spec.supports_model_scale(model_scale):
            raise ValueError(f"不支持的 model_scale: {model_scale}")

    def _validate_build_format(self, build_format: str) -> None:
        """校验传入 build 格式是否被当前规格支持。"""

        if not self.spec.supports_build_format(build_format):
            raise ValueError(f"不支持的 build 格式: {build_format}")

    def _validate_build_runtime_backend(
        self, *, build_format: str, runtime_backend: str
    ) -> str:
        """校验 ModelBuild runtime backend 与 build_format 是否一致。"""

        normalized_backend = runtime_backend.strip().lower()
        expected_backend = _MODEL_BUILD_RUNTIME_BACKEND_BY_FORMAT.get(build_format)
        if expected_backend is None:
            raise InvalidRequestError(
                "不支持的 ModelBuild build_format",
                details={"build_format": build_format},
            )
        if normalized_backend != expected_backend:
            raise InvalidRequestError(
                "ModelBuild runtime_backend 与 build_format 不一致",
                details={
                    "build_format": build_format,
                    "runtime_backend": runtime_backend,
                    "expected_runtime_backend": expected_backend,
                },
            )
        return normalized_backend

    def _validate_build_runtime_precision(
        self, *, build_format: str, runtime_precision: str
    ) -> str:
        """校验 ModelBuild runtime precision 是否被 build_format 支持。"""

        normalized_precision = runtime_precision.strip().lower()
        supported_precisions = _MODEL_BUILD_RUNTIME_PRECISIONS_BY_FORMAT.get(
            build_format
        )
        if supported_precisions is None:
            raise InvalidRequestError(
                "不支持的 ModelBuild build_format",
                details={"build_format": build_format},
            )
        if normalized_precision not in supported_precisions:
            raise InvalidRequestError(
                "ModelBuild runtime_precision 与 build_format 不一致",
                details={
                    "build_format": build_format,
                    "runtime_precision": runtime_precision,
                    "supported_precisions": sorted(supported_precisions),
                },
            )
        return normalized_precision

    def _build_pretrained_metadata(
        self,
        metadata: dict[str, object],
        *,
        task_type: str,
        model_scale: str,
    ) -> dict[str, object]:
        """构建平台级预训练模型登记元数据。

        参数：
        - metadata：调用方传入的附加元数据。

        返回：
        - 已补齐平台级预训练标记的元数据。
        """

        pretrained_metadata = self._normalize_yolo_version_input_metadata(
            metadata,
            task_type=task_type,
            model_scale=model_scale,
            allow_default=True,
        )
        pretrained_metadata.setdefault("source_kind", "pretrained-reference")
        return pretrained_metadata

    def _normalize_yolo_version_input_metadata(
        self,
        metadata: dict[str, object],
        *,
        task_type: str,
        model_scale: str | None = None,
        allow_default: bool,
    ) -> dict[str, object]:
        """把平台模型 ModelVersion 输入信息收敛为唯一显式契约。"""

        normalized = dict(metadata)
        if self.spec.model_name not in _MODEL_INPUT_CONTRACT_TYPES:
            return normalized

        raw_input_size = normalized.get("input_size")
        if raw_input_size is None:
            training_config = normalized.get("training_config")
            if isinstance(training_config, dict):
                raw_input_size = training_config.get("input_size")
        if raw_input_size is None:
            if not allow_default:
                raise InvalidRequestError(
                    "训练输出缺少 input_size，无法登记 ModelVersion",
                    details={
                        "model_type": self.spec.model_name,
                        "task_type": task_type,
                    },
                )
            spatial_size = self._resolve_default_model_input_size(
                task_type=task_type,
                model_scale=model_scale,
            )
        else:
            spatial_size = self._parse_explicit_spatial_size(
                raw_input_size,
                field_name="input_size",
            )

        input_spec = build_platform_model_input_spec(
            model_type=self.spec.model_name,
            spatial_size=spatial_size,
            task_type=task_type,
        )
        normalized["input_size"] = spatial_size.to_payload()
        normalized["model_input_spec"] = input_spec.to_payload()
        training_config = normalized.get("training_config")
        if isinstance(training_config, dict):
            normalized_training_config = dict(training_config)
            normalized_training_config["input_size"] = spatial_size.to_payload()
            normalized["training_config"] = normalized_training_config
        return normalized

    def _resolve_default_model_input_size(
        self,
        *,
        task_type: str,
        model_scale: str | None,
    ) -> SpatialSize:
        """按模型原生配置解析预训练版本的默认输入尺寸。"""

        model_type = self.spec.model_name
        if model_type in {"yolov8", "yolo11", "yolo26"}:
            return resolve_yolo_default_spatial_size(task_type=task_type)
        if model_type == "yolox":
            return SpatialSize(width=640, height=640)
        if model_type == "rfdetr":
            if model_scale is None:
                raise InvalidRequestError(
                    "RF-DETR 预训练模型缺少 model_scale，无法解析输入尺寸",
                    details={"task_type": task_type},
                )
            from backend.service.application.models.rfdetr_core.factory import (
                resolve_rfdetr_full_core_default_input_size,
            )

            input_height, input_width = resolve_rfdetr_full_core_default_input_size(
                task_type=task_type,
                model_scale=model_scale,
            )
            return SpatialSize(width=input_width, height=input_height)
        raise InvalidRequestError(
            "模型类型缺少默认输入尺寸规则",
            details={"model_type": model_type, "task_type": task_type},
        )

    def _normalize_yolo_build_input_metadata(
        self,
        *,
        source_version_metadata: dict[str, object],
        build_metadata: dict[str, object],
    ) -> dict[str, object]:
        """继承并校验 ModelBuild 的实际输入张量契约。"""

        normalized = dict(build_metadata)
        if self.spec.model_name not in _MODEL_INPUT_CONTRACT_TYPES:
            return normalized
        try:
            input_spec = ModelInputSpec.from_payload(
                source_version_metadata.get("model_input_spec")
            )
        except ValueError as error:
            raise InvalidRequestError(
                "来源 ModelVersion 缺少有效 model_input_spec"
            ) from error

        actual_shape = self._read_build_input_shape(normalized)
        if actual_shape is not None:
            expected_shape = input_spec.tensor_shape
            if len(actual_shape) != 4 or any(
                actual > 0 and actual != expected
                for actual, expected in zip(actual_shape, expected_shape, strict=True)
            ):
                raise InvalidRequestError(
                    "ModelBuild 实际输入张量与来源 ModelVersion 不一致",
                    details={
                        "actual_input_shape": list(actual_shape),
                        "expected_input_shape": list(expected_shape),
                    },
                )
        normalized["input_size"] = input_spec.spatial_size.to_payload()
        normalized["model_input_spec"] = input_spec.to_payload()
        normalized["input_tensor"] = {
            "layout": input_spec.layout,
            "shape": list(actual_shape or input_spec.tensor_shape),
            "dtype": input_spec.dtype,
        }
        return normalized

    def _parse_explicit_spatial_size(
        self,
        value: object,
        *,
        field_name: str,
    ) -> SpatialSize:
        """解析公开 width/height 对象，不接受有顺序歧义的数组。"""

        try:
            return SpatialSize.from_payload(value, field_name=field_name)
        except ValueError as error:
            raise InvalidRequestError(str(error)) from error

    def _read_build_input_shape(
        self,
        metadata: dict[str, object],
    ) -> tuple[int, ...] | None:
        """读取转换器报告的 NCHW 输入形状。"""

        candidates = [metadata.get("input_shape"), metadata.get("tensor_shape")]
        input_tensor = metadata.get("input_tensor")
        if isinstance(input_tensor, dict):
            candidates.append(input_tensor.get("shape"))
        for value in candidates:
            if (
                isinstance(value, list | tuple)
                and value
                and all(
                    isinstance(item, int) and not isinstance(item, bool)
                    for item in value
                )
            ):
                return tuple(int(item) for item in value)
        return None

    def _build_platform_base_model_summary(
        self,
        *,
        unit_of_work: SqlAlchemyUnitOfWork,
        model: Model,
    ) -> PlatformBaseModelSummaryView:
        """构建平台基础模型摘要视图。"""

        versions = unit_of_work.models.list_model_versions(model.model_id)
        builds = unit_of_work.models.list_model_builds(model.model_id)
        available_versions = tuple(
            self._build_platform_base_model_version_summary(
                unit_of_work=unit_of_work,
                model_version=model_version,
            )
            for model_version in versions
        )
        return PlatformBaseModelSummaryView(
            model_id=model.model_id,
            project_id=model.project_id,
            scope_kind=model.scope_kind,
            model_name=model.model_name,
            model_type=model.model_type,
            task_type=model.task_type,
            model_scale=model.model_scale,
            labels_file_id=model.labels_file_id,
            metadata=dict(model.metadata),
            version_count=len(versions),
            build_count=len(builds),
            available_versions=available_versions,
        )

    def _build_platform_base_model_version_summary(
        self,
        *,
        unit_of_work: SqlAlchemyUnitOfWork,
        model_version: ModelVersion,
    ) -> PlatformBaseModelVersionSummaryView:
        """构建平台基础模型版本摘要视图。"""

        model_files = unit_of_work.model_files.list_model_files(
            model_version_id=model_version.model_version_id,
        )
        checkpoint_file = self._find_checkpoint_file(model_files)
        catalog_manifest_object_key = model_version.metadata.get(
            "catalog_manifest_object_key"
        )
        return PlatformBaseModelVersionSummaryView(
            model_version_id=model_version.model_version_id,
            source_kind=model_version.source_kind,
            dataset_version_id=model_version.dataset_version_id,
            training_task_id=model_version.training_task_id,
            parent_version_id=model_version.parent_version_id,
            file_ids=model_version.file_ids,
            metadata=dict(model_version.metadata),
            checkpoint_file_id=(
                checkpoint_file.file_id if checkpoint_file is not None else None
            ),
            checkpoint_storage_uri=(
                checkpoint_file.storage_uri if checkpoint_file is not None else None
            ),
            catalog_manifest_object_key=(
                catalog_manifest_object_key
                if isinstance(catalog_manifest_object_key, str)
                else None
            ),
        )

    def _build_platform_base_model_version_detail(
        self,
        *,
        unit_of_work: SqlAlchemyUnitOfWork,
        model_version: ModelVersion,
    ) -> PlatformBaseModelVersionDetailView:
        """构建平台基础模型版本详情视图。"""

        model_files = unit_of_work.model_files.list_model_files(
            model_version_id=model_version.model_version_id,
        )
        checkpoint_file = self._find_checkpoint_file(model_files)
        catalog_manifest_object_key = model_version.metadata.get(
            "catalog_manifest_object_key"
        )
        return PlatformBaseModelVersionDetailView(
            model_version_id=model_version.model_version_id,
            source_kind=model_version.source_kind,
            dataset_version_id=model_version.dataset_version_id,
            training_task_id=model_version.training_task_id,
            parent_version_id=model_version.parent_version_id,
            file_ids=model_version.file_ids,
            metadata=dict(model_version.metadata),
            checkpoint_file_id=(
                checkpoint_file.file_id if checkpoint_file is not None else None
            ),
            checkpoint_storage_uri=(
                checkpoint_file.storage_uri if checkpoint_file is not None else None
            ),
            catalog_manifest_object_key=(
                catalog_manifest_object_key
                if isinstance(catalog_manifest_object_key, str)
                else None
            ),
            files=tuple(
                self._build_platform_base_model_file_view(model_file)
                for model_file in model_files
            ),
        )

    def _build_platform_base_model_build_view(
        self,
        *,
        unit_of_work: SqlAlchemyUnitOfWork,
        model_build: ModelBuild,
    ) -> PlatformBaseModelBuildView:
        """构建平台基础模型构建详情视图。"""

        model_files = unit_of_work.model_files.list_model_files(
            model_build_id=model_build.model_build_id,
        )
        build_metadata = dict(model_build.metadata)
        return PlatformBaseModelBuildView(
            model_build_id=model_build.model_build_id,
            source_model_version_id=model_build.source_model_version_id,
            build_format=model_build.build_format,
            runtime_backend=model_build.runtime_backend,
            runtime_precision=model_build.runtime_precision,
            runtime_profile_id=model_build.runtime_profile_id,
            conversion_task_id=model_build.conversion_task_id,
            file_ids=model_build.file_ids,
            metadata=build_metadata,
            files=tuple(
                self._build_platform_base_model_file_view(model_file)
                for model_file in model_files
            ),
        )

    def _build_platform_base_model_file_view(
        self,
        model_file: ModelFile,
    ) -> PlatformBaseModelFileView:
        """构建平台基础模型文件视图。"""

        return PlatformBaseModelFileView(
            file_id=model_file.file_id,
            project_id=model_file.project_id,
            scope_kind=model_file.scope_kind,
            model_id=model_file.model_id,
            model_version_id=model_file.model_version_id,
            model_build_id=model_file.model_build_id,
            file_type=model_file.file_type,
            logical_name=model_file.logical_name,
            storage_uri=model_file.storage_uri,
            metadata=dict(model_file.metadata),
        )

    def _find_checkpoint_file(
        self,
        model_files: tuple[ModelFile, ...],
    ) -> ModelFile | None:
        """在文件列表中查找 checkpoint 文件。

        部署来源查询由通用 ``SqlAlchemyModelService`` 提供，列表中可能同时包含
        YOLOX、YOLOv8、YOLO11、YOLO26 和 RF-DETR 等模型。这里不能只按当前
        service 实例的默认文件类型判断，否则非默认模型已登记的 checkpoint 会被
        错误视为缺失。
        """

        for model_file in model_files:
            if model_file.file_type == self.file_types.checkpoint_file_type:
                return model_file

        for model_file in model_files:
            if self._is_checkpoint_file_type(model_file.file_type):
                return model_file

        return None

    @staticmethod
    def _is_checkpoint_file_type(file_type: str) -> bool:
        """判断通用模型文件类型是否表示训练 checkpoint。"""

        normalized_file_type = file_type.strip().lower()
        return normalized_file_type == "pytorch-checkpoint" or (
            normalized_file_type.endswith("-checkpoint")
        )

    def _deployment_source_sort_key(
        self, model: PlatformBaseModelSummaryView
    ) -> tuple[int, int, int, str, str]:
        """构建部署来源列表排序键。

        Project 内训练模型优先，其次优先有转换 build 的模型，最后按模型名稳定排序。
        """

        scope_order = 0 if model.scope_kind == PROJECT_MODEL_SCOPE else 1
        build_order = 0 if model.build_count > 0 else 1
        version_order = 0 if model.version_count > 0 else 1
        return (
            scope_order,
            build_order,
            version_order,
            model.model_name,
            model.model_id,
        )

    def _strip_deprecated_build_runtime_metadata(
        self,
        metadata: dict[str, object],
    ) -> dict[str, object]:
        """移除旧的构建运行时 metadata，避免和一等字段形成双来源。"""

        build_metadata = dict(metadata)
        for key in (
            "runtime_backend",
            "runtime_precision",
            "build_precision",
            "compress_to_fp16",
            "openvino_ir_precision",
            "tensorrt_engine_precision",
        ):
            build_metadata.pop(key, None)
        return build_metadata

    def _register_training_files(
        self,
        *,
        unit_of_work: SqlAlchemyUnitOfWork,
        model_id: str,
        model_name: str,
        model_scale: str,
        project_id: str,
        scope_kind: ModelScopeKind,
        model_version_id: str,
        checkpoint_file_id: str,
        checkpoint_file_uri: str | None,
        labels_file_id: str | None,
        labels_file_uri: str | None,
        metrics_file_id: str | None,
        metrics_file_uri: str | None,
        provenance_trace: dict[str, object],
    ) -> tuple[str, ...]:
        """为训练输出创建最小 ModelFile 记录。

        参数：
        - model_id：所属 Model id。
        - model_name：模型名。
        - model_scale：模型 scale。
        - project_id：所属项目 id。
        - scope_kind：文件所属模型作用域类型。
        - model_version_id：目标 ModelVersion id。
        - checkpoint_file_id：checkpoint 文件 id。
        - checkpoint_file_uri：checkpoint 文件存储 URI。
        - labels_file_id：标签文件 id。
        - labels_file_uri：标签文件存储 URI。
        - metrics_file_id：指标文件 id。
        - metrics_file_uri：指标文件存储 URI。
        - provenance_trace：训练输出来源追踪字段。

        返回：
        - 生成或登记的文件 id 列表。
        """

        registered_files = (
            (
                checkpoint_file_id,
                self.file_types.checkpoint_file_type,
                checkpoint_file_uri or f"registered://{checkpoint_file_id}",
                build_default_file_name(
                    YoloXFileNamingContext(
                        model_name=model_name,
                        model_scale=model_scale,
                        source_version=model_version_id,
                        file_kind=self.file_types.checkpoint_file_type,
                        suffix="pth",
                    )
                ),
            ),
            (
                labels_file_id,
                self.file_types.label_map_file_type,
                (
                    labels_file_uri or f"registered://{labels_file_id}"
                    if labels_file_id is not None
                    else None
                ),
                "labels.json",
            ),
            (
                metrics_file_id,
                self.file_types.training_metrics_file_type,
                (
                    metrics_file_uri or f"registered://{metrics_file_id}"
                    if metrics_file_id is not None
                    else None
                ),
                "metrics.json",
            ),
        )
        file_ids: list[str] = []
        for file_id, file_type, storage_uri, logical_name in registered_files:
            if file_id is None or storage_uri is None:
                continue
            self._create_model_file(
                unit_of_work=unit_of_work,
                file_id=file_id,
                project_id=project_id,
                scope_kind=scope_kind,
                model_id=model_id,
                model_version_id=model_version_id,
                file_type=file_type,
                logical_name=logical_name,
                storage_uri=storage_uri,
                metadata=attach_model_artifact_provenance(
                    {"artifact_role": file_type},
                    artifact_kind="training-output-file",
                    trace=provenance_trace,
                ),
            )
            file_ids.append(file_id)

        return tuple(file_ids)

    def _create_model_file(
        self,
        *,
        unit_of_work: SqlAlchemyUnitOfWork,
        file_id: str,
        project_id: str | None,
        scope_kind: ModelScopeKind,
        model_id: str,
        file_type: str,
        logical_name: str,
        storage_uri: str,
        model_version_id: str | None = None,
        model_build_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ModelFile:
        """创建并保存 ModelFile 记录。

            参数：
            - file_id：文件 id。
        - project_id：所属项目 id；平台基础模型文件时为空。
            - scope_kind：文件所属模型作用域类型。
            - model_id：所属 Model id。
            - file_type：文件类型。
            - logical_name：文件逻辑名。
            - storage_uri：文件存储 URI。
            - model_version_id：关联的 ModelVersion id。
            - model_build_id：关联的 ModelBuild id。
            - metadata：附加元数据。

            返回：
            - 新建或已存在的 ModelFile。
        """

        existing_file = unit_of_work.model_files.get_model_file(file_id)
        if existing_file is not None:
            return existing_file

        model_file = ModelFile(
            file_id=file_id,
            project_id=project_id,
            scope_kind=scope_kind,
            model_id=model_id,
            model_version_id=model_version_id,
            model_build_id=model_build_id,
            file_type=file_type,
            logical_name=logical_name,
            storage_uri=storage_uri,
            metadata=metadata or {},
        )
        unit_of_work.model_files.save_model_file(model_file)

        return model_file

    def _next_id(self, prefix: str) -> str:
        """生成随机对象 id。

        参数：
        - prefix：对象前缀。

        返回：
        - 新的对象 id。
        """

        return f"{prefix}-{uuid4().hex[:12]}"

    def _guess_suffix(self, uri: str) -> str:
        """从 URI 或文件 id 推断文件后缀。

        参数：
        - uri：文件 URI 或文件 id。

        返回：
        - 推断出的后缀名；无后缀时返回 bin。
        """

        parsed = urlparse(uri)
        suffix = PurePosixPath(parsed.path or uri).suffix.lstrip(".")

        return suffix or "bin"

    def _resolve_build_file_type(self, build_format: str) -> str:
        """把 build 格式映射到 ModelFile 类型。

        参数：
        - build_format：build 格式。

        返回：
        - 对应的 ModelFile 类型。
        """

        try:
            return self.file_types.resolve_build_file_type(build_format)
        except Exception as error:
            raise ValueError(f"不支持的 build 格式: {build_format}") from error

    @contextmanager
    def _open_unit_of_work(self) -> Iterator[SqlAlchemyUnitOfWork]:
        """创建并管理一个请求级 Unit of Work。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            yield unit_of_work
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.close()
