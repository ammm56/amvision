"""YOLOX 模型应用服务接口定义。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Protocol
from urllib.parse import urlparse
from uuid import uuid4

from backend.contracts.files.yolox_model_files import YoloXFileNamingContext, build_default_file_name
from backend.service.domain.files.model_file import ModelFile
from backend.service.domain.files.yolox_file_types import (
    YOLOX_CHECKPOINT_FILE,
    YOLOX_LABEL_MAP_FILE,
    YOLOX_ONNX_FILE,
    YOLOX_OPENVINO_IR_FILE,
    YOLOX_TENSORRT_ENGINE_FILE,
    YOLOX_TRAINING_METRICS_FILE,
)
from backend.service.domain.models.model_records import Model, ModelBuild, ModelVersion
from backend.service.domain.models.yolox_model_spec import DEFAULT_YOLOX_MODEL_SPEC, YoloXModelSpec
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


@dataclass(frozen=True)
class YoloXPretrainedRegistrationRequest:
    """描述一次预置预训练模型登记请求。

    字段：
    - project_id：所属项目 id。
    - model_name：登记到平台的模型名。
    - storage_uri：预训练模型在磁盘或对象存储中的现成位置。
    - model_scale：模型 scale。
    - task_type：任务类型。
    - labels_file_id：类别映射文件 id。
    - metadata：附加元数据。
    """

    project_id: str
    model_name: str
    storage_uri: str
    model_scale: str
    task_type: str = "detection"
    labels_file_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXTrainingOutputRegistration:
    """描述训练输出登记请求。

    字段：
    - project_id：所属项目 id。
    - training_task_id：训练任务 id。
    - model_name：登记到平台的模型名。
    - model_scale：模型 scale。
    - dataset_version_id：训练使用的 DatasetVersion id。
    - checkpoint_file_id：checkpoint 文件 id。
    - checkpoint_file_uri：checkpoint 文件存储 URI。
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
    checkpoint_file_uri: str | None = None
    labels_file_id: str | None = None
    labels_file_uri: str | None = None
    metrics_file_id: str | None = None
    metrics_file_uri: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXBuildRegistration:
    """描述模型 build 登记请求。

    字段：
    - project_id：所属项目 id。
    - source_model_version_id：来源 ModelVersion id。
    - build_format：build 格式。
    - build_file_id：build 文件 id。
    - build_file_uri：build 文件 URI。
    - runtime_profile_id：目标 RuntimeProfile id。
    - conversion_task_id：来源转换任务 id。
    - metadata：附加元数据。
    """

    project_id: str
    source_model_version_id: str
    build_format: str
    build_file_id: str
    build_file_uri: str | None = None
    runtime_profile_id: str | None = None
    conversion_task_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class YoloXModelService(Protocol):
    """YOLOX 模型登记接口。"""

    def register_pretrained(self, request: YoloXPretrainedRegistrationRequest) -> str:
        """登记预置预训练模型并返回模型版本 id。

        参数：
        - request：预置预训练模型登记请求。

        返回：
        - 新登记的 ModelVersion id。
        """

        ...

    def register_training_output(self, request: YoloXTrainingOutputRegistration) -> str:
        """登记训练输出并返回新的模型版本 id。

        参数：
        - request：训练输出登记请求。

        返回：
        - 新登记的 ModelVersion id。
        """

        ...

    def register_build(self, request: YoloXBuildRegistration) -> str:
        """登记模型 build 并返回新的 ModelBuild id。

        参数：
        - request：模型 build 登记请求。

        返回：
        - 新登记的 ModelBuild id。
        """

        ...


class SqlAlchemyYoloXModelService:
    """使用 SQLAlchemy Repository 与 Unit of Work 实现 YOLOX 模型登记。"""

    def __init__(
        self,
        session_factory: SessionFactory,
        spec: YoloXModelSpec = DEFAULT_YOLOX_MODEL_SPEC,
    ) -> None:
        """初始化基于 SQLAlchemy 的模型登记服务。

        参数：
        - session_factory：用于创建数据库会话的工厂。
        - spec：当前使用的 YOLOX 模型规格。
        """

        self.session_factory = session_factory
        self.spec = spec

    def register_pretrained(self, request: YoloXPretrainedRegistrationRequest) -> str:
        """登记预置预训练模型并返回模型版本 id。

        参数：
        - request：预置预训练模型登记请求。

        返回：
        - 新登记的 ModelVersion id。
        """

        with self._open_unit_of_work() as unit_of_work:
            model = self._ensure_model(
                unit_of_work=unit_of_work,
                project_id=request.project_id,
                model_name=request.model_name,
                model_scale=request.model_scale,
                task_type=request.task_type,
                labels_file_id=request.labels_file_id,
                metadata=request.metadata,
            )
            model_version_id = self._next_id("model-version")
            checkpoint_file = self._create_model_file(
                unit_of_work=unit_of_work,
                file_id=self._next_id("model-file"),
                project_id=request.project_id,
                model_id=model.model_id,
                model_version_id=model_version_id,
                file_type=YOLOX_CHECKPOINT_FILE,
                logical_name=build_default_file_name(
                    YoloXFileNamingContext(
                        project_id=request.project_id,
                        model_name=request.model_name,
                        model_scale=request.model_scale,
                        source_version=model_version_id,
                        file_kind=YOLOX_CHECKPOINT_FILE,
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
                metadata=request.metadata,
            )
            unit_of_work.models.save_model_version(model_version)
            unit_of_work.commit()

            return model_version_id

    def register_training_output(self, request: YoloXTrainingOutputRegistration) -> str:
        """登记训练输出并返回新的模型版本 id。

        参数：
        - request：训练输出登记请求。

        返回：
        - 新登记的 ModelVersion id。
        """

        with self._open_unit_of_work() as unit_of_work:
            model = self._ensure_model(
                unit_of_work=unit_of_work,
                project_id=request.project_id,
                model_name=request.model_name,
                model_scale=request.model_scale,
                task_type="detection",
                labels_file_id=request.labels_file_id,
                metadata=request.metadata,
            )
            model_version_id = self._next_id("model-version")
            file_ids = self._register_training_files(
                unit_of_work=unit_of_work,
                model_id=model.model_id,
                model_name=request.model_name,
                model_scale=request.model_scale,
                project_id=request.project_id,
                model_version_id=model_version_id,
                checkpoint_file_id=request.checkpoint_file_id,
                checkpoint_file_uri=request.checkpoint_file_uri,
                labels_file_id=request.labels_file_id,
                labels_file_uri=request.labels_file_uri,
                metrics_file_id=request.metrics_file_id,
                metrics_file_uri=request.metrics_file_uri,
            )
            model_version = ModelVersion(
                model_version_id=model_version_id,
                model_id=model.model_id,
                source_kind="training-output",
                dataset_version_id=request.dataset_version_id,
                training_task_id=request.training_task_id,
                file_ids=file_ids,
                metadata=request.metadata,
            )
            unit_of_work.models.save_model_version(model_version)
            unit_of_work.commit()

            return model_version_id

    def register_build(self, request: YoloXBuildRegistration) -> str:
        """登记模型 build 并返回新的 ModelBuild id。

        参数：
        - request：模型 build 登记请求。

        返回：
        - 新登记的 ModelBuild id。
        """

        with self._open_unit_of_work() as unit_of_work:
            source_version = unit_of_work.models.get_model_version(request.source_model_version_id)
            if source_version is None:
                raise ValueError(f"未知的 ModelVersion: {request.source_model_version_id}")

            model = unit_of_work.models.get_model(source_version.model_id)
            if model is None:
                raise ValueError(f"未知的 Model: {source_version.model_id}")

            model_build_id = self._next_id("model-build")
            build_file = self._create_model_file(
                unit_of_work=unit_of_work,
                file_id=request.build_file_id,
                project_id=request.project_id,
                model_id=model.model_id,
                model_build_id=model_build_id,
                file_type=self._resolve_build_file_type(request.build_format),
                logical_name=build_default_file_name(
                    YoloXFileNamingContext(
                        project_id=request.project_id,
                        model_name=model.model_name,
                        model_scale=model.model_scale,
                        source_version=source_version.model_version_id,
                        file_kind=request.build_format,
                        suffix=self._guess_suffix(request.build_file_uri or request.build_file_id),
                    )
                ),
                storage_uri=request.build_file_uri or f"registered://{request.build_file_id}",
                metadata={"build_format": request.build_format},
            )
            model_build = ModelBuild(
                model_build_id=model_build_id,
                model_id=model.model_id,
                source_model_version_id=request.source_model_version_id,
                build_format=request.build_format,
                runtime_profile_id=request.runtime_profile_id,
                conversion_task_id=request.conversion_task_id,
                file_ids=(build_file.file_id,),
                metadata=request.metadata,
            )
            unit_of_work.models.save_model_build(model_build)
            unit_of_work.commit()

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

    def get_model_version(self, model_version_id: str) -> ModelVersion | None:
        """按 id 读取 ModelVersion。

        参数：
        - model_version_id：ModelVersion id。

        返回：
        - 对应的 ModelVersion；不存在时返回 None。
        """

        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.models.get_model_version(model_version_id)

    def get_model_build(self, model_build_id: str) -> ModelBuild | None:
        """按 id 读取 ModelBuild。

        参数：
        - model_build_id：ModelBuild id。

        返回：
        - 对应的 ModelBuild；不存在时返回 None。
        """

        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.models.get_model_build(model_build_id)

    def get_model_file(self, file_id: str) -> ModelFile | None:
        """按 id 读取 ModelFile。

        参数：
        - file_id：ModelFile id。

        返回：
        - 对应的 ModelFile；不存在时返回 None。
        """

        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.model_files.get_model_file(file_id)

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

    def _ensure_model(
        self,
        *,
        unit_of_work: SqlAlchemyUnitOfWork,
        project_id: str,
        model_name: str,
        model_scale: str,
        task_type: str,
        labels_file_id: str | None,
        metadata: dict[str, object],
    ) -> Model:
        """确保数据库中存在对应的 Model 对象。

        参数：
        - unit_of_work：当前请求级 Unit of Work。
        - project_id：所属项目 id。
        - model_name：模型名。
        - model_scale：模型 scale。
        - task_type：任务类型。
        - labels_file_id：标签文件 id。
        - metadata：附加元数据。

        返回：
        - 已存在或新建的 Model。
        """

        model = unit_of_work.models.find_model(
            project_id=project_id,
            model_name=model_name,
            model_scale=model_scale,
            task_type=task_type,
        )
        if model is not None:
            return model

        model = Model(
            model_id=self._next_id("model"),
            project_id=project_id,
            model_name=model_name,
            model_type=self.spec.model_name,
            task_type=task_type,
            model_scale=model_scale,
            labels_file_id=labels_file_id,
            metadata=metadata,
        )
        unit_of_work.models.save_model(model)

        return model

    def _register_training_files(
        self,
        *,
        unit_of_work: SqlAlchemyUnitOfWork,
        model_id: str,
        model_name: str,
        model_scale: str,
        project_id: str,
        model_version_id: str,
        checkpoint_file_id: str,
        checkpoint_file_uri: str | None,
        labels_file_id: str | None,
        labels_file_uri: str | None,
        metrics_file_id: str | None,
        metrics_file_uri: str | None,
    ) -> tuple[str, ...]:
        """为训练输出创建最小 ModelFile 记录。

        参数：
        - model_id：所属 Model id。
        - model_name：模型名。
        - model_scale：模型 scale。
        - project_id：所属项目 id。
        - model_version_id：目标 ModelVersion id。
        - checkpoint_file_id：checkpoint 文件 id。
        - checkpoint_file_uri：checkpoint 文件存储 URI。
        - labels_file_id：标签文件 id。
        - labels_file_uri：标签文件存储 URI。
        - metrics_file_id：指标文件 id。
        - metrics_file_uri：指标文件存储 URI。

        返回：
        - 生成或登记的文件 id 列表。
        """

        registered_files = (
            (
                checkpoint_file_id,
                YOLOX_CHECKPOINT_FILE,
                checkpoint_file_uri or f"registered://{checkpoint_file_id}",
                build_default_file_name(
                    YoloXFileNamingContext(
                        project_id=project_id,
                        model_name=model_name,
                        model_scale=model_scale,
                        source_version=model_version_id,
                        file_kind=YOLOX_CHECKPOINT_FILE,
                        suffix="pth",
                    )
                ),
            ),
            (
                labels_file_id,
                YOLOX_LABEL_MAP_FILE,
                (
                    labels_file_uri or f"registered://{labels_file_id}"
                    if labels_file_id is not None
                    else None
                ),
                "labels.json",
            ),
            (
                metrics_file_id,
                YOLOX_TRAINING_METRICS_FILE,
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
                model_id=model_id,
                model_version_id=model_version_id,
                file_type=file_type,
                logical_name=logical_name,
                storage_uri=storage_uri,
            )
            file_ids.append(file_id)

        return tuple(file_ids)

    def _create_model_file(
        self,
        *,
        unit_of_work: SqlAlchemyUnitOfWork,
        file_id: str,
        project_id: str,
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
        - project_id：所属项目 id。
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

        build_file_type_map = {
            "onnx": YOLOX_ONNX_FILE,
            "openvino-ir": YOLOX_OPENVINO_IR_FILE,
            "tensorrt-engine": YOLOX_TENSORRT_ENGINE_FILE,
        }
        if build_format not in build_file_type_map:
            raise ValueError(f"不支持的 build 格式: {build_format}")

        return build_file_type_map[build_format]

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