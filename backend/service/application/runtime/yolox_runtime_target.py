"""YOLOX 运行时目标解析服务。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.models.yolox_model_service import SqlAlchemyYoloXModelService
from backend.service.domain.files.model_file import ModelFile
from backend.service.domain.files.yolox_file_types import (
    YOLOX_CHECKPOINT_FILE,
    YOLOX_LABEL_MAP_FILE,
    YOLOX_ONNX_FILE,
    YOLOX_OPENVINO_IR_FILE,
    YOLOX_TENSORRT_ENGINE_FILE,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


_DEFAULT_RUNTIME_BACKEND = "pytorch"
_DEFAULT_DEVICE_NAME = "cpu"
_DEFAULT_INPUT_SIZE = (640, 640)
_SUPPORTED_RUNTIME_BACKENDS = frozenset({"pytorch", "onnxruntime", "openvino", "tensorrt"})
_MODEL_BUILD_FILE_TYPE_MAP = {
    "onnx": YOLOX_ONNX_FILE,
    "openvino-ir": YOLOX_OPENVINO_IR_FILE,
    "tensorrt-engine": YOLOX_TENSORRT_ENGINE_FILE,
}
_MODEL_BUILD_RUNTIME_BACKEND_MAP = {
    "onnx": "onnxruntime",
    "openvino-ir": "openvino",
    "tensorrt-engine": "tensorrt",
}


@dataclass(frozen=True)
class RuntimeTargetResolveRequest:
    """描述一次 RuntimeTargetSnapshot 解析请求。

    字段：
    - project_id：所属 Project id。
    - model_version_id：直接绑定的 ModelVersion id。
    - model_build_id：直接绑定的 ModelBuild id。
    - runtime_profile_id：可选 RuntimeProfile id。
    - runtime_backend：运行时 backend；直接绑定 ModelVersion 时默认 pytorch，绑定 ModelBuild 时默认按 build_format 推导。
    - device_name：默认 device 名称。
    """

    project_id: str
    model_version_id: str | None = None
    model_build_id: str | None = None
    runtime_profile_id: str | None = None
    runtime_backend: str | None = None
    device_name: str | None = None


@dataclass(frozen=True)
class RuntimeTargetSnapshot:
    """描述一次已经固化到执行边界的运行时快照。

    字段：
    - project_id：所属 Project id。
    - model_id：关联 Model id。
    - model_version_id：执行使用的 ModelVersion id。
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
    - runtime_artifact_file_id：当前执行实际消费的文件 id。
    - runtime_artifact_storage_uri：当前执行实际消费的文件存储 URI。
    - runtime_artifact_path：当前执行实际消费的本地绝对路径。
    - runtime_artifact_file_type：当前执行实际消费的文件类型。
    - checkpoint_file_id：来源 ModelVersion 的 checkpoint 文件 id。
    - checkpoint_storage_uri：来源 ModelVersion 的 checkpoint 存储 URI。
    - checkpoint_path：来源 ModelVersion 的 checkpoint 本地绝对路径。
    - labels_storage_uri：labels 文件存储 URI。
    """

    project_id: str
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
    runtime_artifact_file_id: str
    runtime_artifact_storage_uri: str
    runtime_artifact_path: Path
    runtime_artifact_file_type: str
    checkpoint_file_id: str | None = None
    checkpoint_storage_uri: str | None = None
    checkpoint_path: Path | None = None
    labels_storage_uri: str | None = None


def serialize_runtime_target_snapshot(snapshot: RuntimeTargetSnapshot) -> dict[str, object]:
    """把 RuntimeTargetSnapshot 序列化为可持久化字典。

    参数：
    - snapshot：待持久化的运行时快照。

    返回：
    - dict[str, object]：可写入 metadata 或 task_spec 的快照字典。
    """

    return {
        "project_id": snapshot.project_id,
        "model_id": snapshot.model_id,
        "model_version_id": snapshot.model_version_id,
        "model_build_id": snapshot.model_build_id,
        "model_name": snapshot.model_name,
        "model_scale": snapshot.model_scale,
        "task_type": snapshot.task_type,
        "source_kind": snapshot.source_kind,
        "runtime_profile_id": snapshot.runtime_profile_id,
        "runtime_backend": snapshot.runtime_backend,
        "device_name": snapshot.device_name,
        "input_size": [snapshot.input_size[0], snapshot.input_size[1]],
        "labels": list(snapshot.labels),
        "runtime_artifact_file_id": snapshot.runtime_artifact_file_id,
        "runtime_artifact_storage_uri": snapshot.runtime_artifact_storage_uri,
        "runtime_artifact_file_type": snapshot.runtime_artifact_file_type,
        "checkpoint_file_id": snapshot.checkpoint_file_id,
        "checkpoint_storage_uri": snapshot.checkpoint_storage_uri,
        "labels_storage_uri": snapshot.labels_storage_uri,
    }


def deserialize_runtime_target_snapshot(
    *,
    payload: object,
    dataset_storage: LocalDatasetStorage,
) -> RuntimeTargetSnapshot:
    """把持久化字典反解析为 RuntimeTargetSnapshot。

    参数：
    - payload：持久化的快照字典。
    - dataset_storage：本地文件存储服务。

    返回：
    - RuntimeTargetSnapshot：可直接供 predictor 或 evaluator 消费的快照。
    """

    if not isinstance(payload, dict):
        raise InvalidRequestError("runtime_target_snapshot 格式不合法")

    runtime_artifact_storage_uri = _require_payload_str(payload, "runtime_artifact_storage_uri")
    labels_storage_uri = _read_payload_optional_str(payload, "labels_storage_uri")
    runtime_artifact_path = resolve_local_file_path(
        dataset_storage=dataset_storage,
        storage_uri=runtime_artifact_storage_uri,
        field_name="runtime_artifact_storage_uri",
    )
    checkpoint_storage_uri = _read_payload_optional_str(payload, "checkpoint_storage_uri")
    checkpoint_path = None
    if checkpoint_storage_uri is not None:
        checkpoint_path = resolve_local_file_path(
            dataset_storage=dataset_storage,
            storage_uri=checkpoint_storage_uri,
            field_name="checkpoint_storage_uri",
        )
    if labels_storage_uri is not None:
        resolve_local_file_path(
            dataset_storage=dataset_storage,
            storage_uri=labels_storage_uri,
            field_name="labels_storage_uri",
        )

    return RuntimeTargetSnapshot(
        project_id=_require_payload_str(payload, "project_id"),
        model_id=_require_payload_str(payload, "model_id"),
        model_version_id=_require_payload_str(payload, "model_version_id"),
        model_build_id=_read_payload_optional_str(payload, "model_build_id"),
        model_name=_require_payload_str(payload, "model_name"),
        model_scale=_require_payload_str(payload, "model_scale"),
        task_type=_require_payload_str(payload, "task_type"),
        source_kind=_require_payload_str(payload, "source_kind"),
        runtime_profile_id=_read_payload_optional_str(payload, "runtime_profile_id"),
        runtime_backend=normalize_runtime_backend(_require_payload_str(payload, "runtime_backend")),
        device_name=normalize_device_name(_require_payload_str(payload, "device_name")),
        input_size=_require_payload_input_size(payload),
        labels=_require_payload_labels(payload),
        runtime_artifact_file_id=_require_payload_str(payload, "runtime_artifact_file_id"),
        runtime_artifact_storage_uri=runtime_artifact_storage_uri,
        runtime_artifact_path=runtime_artifact_path,
        runtime_artifact_file_type=_require_payload_str(payload, "runtime_artifact_file_type"),
        checkpoint_file_id=_read_payload_optional_str(payload, "checkpoint_file_id"),
        checkpoint_storage_uri=checkpoint_storage_uri,
        checkpoint_path=checkpoint_path,
        labels_storage_uri=labels_storage_uri,
    )


class SqlAlchemyYoloXRuntimeTargetResolver:
    """解析 ModelVersion 或 ModelBuild 对应的运行时快照。"""

    def __init__(self, *, session_factory: SessionFactory, dataset_storage: LocalDatasetStorage) -> None:
        """初始化运行时快照解析服务。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：本地文件存储服务。
        """

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage

    def resolve_target(self, request: RuntimeTargetResolveRequest) -> RuntimeTargetSnapshot:
        """解析一次运行时快照。

        参数：
        - request：解析请求。

        返回：
        - RuntimeTargetSnapshot：供 predictor 或 evaluator 消费的运行时快照。
        """

        if not request.project_id.strip():
            raise InvalidRequestError("project_id 不能为空")
        if not _normalize_optional_str(request.model_version_id) and not _normalize_optional_str(request.model_build_id):
            raise InvalidRequestError("model_version_id 和 model_build_id 至少需要提供一个")

        model_service = SqlAlchemyYoloXModelService(session_factory=self.session_factory)
        model_build = None
        if _normalize_optional_str(request.model_build_id) is not None:
            model_build = model_service.get_model_build(_normalize_optional_str(request.model_build_id) or "")
            if model_build is None:
                raise ResourceNotFoundError(
                    "指定的 ModelBuild 不存在",
                    details={"model_build_id": request.model_build_id},
                )

        resolved_model_version_id = _normalize_optional_str(request.model_version_id)
        if model_build is not None:
            resolved_model_version_id = model_build.source_model_version_id
            if (
                _normalize_optional_str(request.model_version_id) is not None
                and _normalize_optional_str(request.model_version_id) != resolved_model_version_id
            ):
                raise InvalidRequestError(
                    "model_build_id 与 model_version_id 不匹配",
                    details={
                        "model_build_id": model_build.model_build_id,
                        "model_version_id": request.model_version_id,
                        "source_model_version_id": resolved_model_version_id,
                    },
                )
            if (
                _normalize_optional_str(request.runtime_profile_id) is not None
                and model_build.runtime_profile_id is not None
                and _normalize_optional_str(request.runtime_profile_id) != model_build.runtime_profile_id
            ):
                raise InvalidRequestError(
                    "runtime_profile_id 与 ModelBuild 记录不一致",
                    details={
                        "runtime_profile_id": request.runtime_profile_id,
                        "model_build_runtime_profile_id": model_build.runtime_profile_id,
                        "model_build_id": model_build.model_build_id,
                    },
                )

        model_version = model_service.get_model_version(resolved_model_version_id or "")
        if model_version is None:
            raise ResourceNotFoundError(
                "指定的 ModelVersion 不存在",
                details={"model_version_id": resolved_model_version_id},
            )
        model = model_service.get_model(model_version.model_id)
        if model is None:
            raise ResourceNotFoundError(
                "指定 ModelVersion 对应的 Model 不存在",
                details={"model_version_id": model_version.model_version_id},
            )
        if model.project_id is not None and model.project_id != request.project_id:
            raise InvalidRequestError(
                "project_id 与模型所属 Project 不一致",
                details={
                    "project_id": request.project_id,
                    "model_project_id": model.project_id,
                    "model_version_id": model_version.model_version_id,
                },
            )

        model_files = model_service.list_model_files(model_version_id=model_version.model_version_id)
        checkpoint_file = find_model_file(model_files=model_files, file_type=YOLOX_CHECKPOINT_FILE)
        labels_file = find_model_file(model_files=model_files, file_type=YOLOX_LABEL_MAP_FILE)
        if model_build is None:
            runtime_artifact_file = require_model_file(
                model_files=model_files,
                file_type=YOLOX_CHECKPOINT_FILE,
                owner_kind="ModelVersion",
                owner_id=model_version.model_version_id,
                missing_message="当前 ModelVersion 缺少运行时所需文件",
            )
        else:
            runtime_artifact_file = require_model_file(
                model_files=model_service.list_model_files(model_build_id=model_build.model_build_id),
                file_type=resolve_model_build_file_type(model_build.build_format),
                owner_kind="ModelBuild",
                owner_id=model_build.model_build_id,
                missing_message="当前 ModelBuild 缺少运行时所需文件",
            )
        runtime_artifact_path = resolve_local_file_path(
            dataset_storage=self.dataset_storage,
            storage_uri=runtime_artifact_file.storage_uri,
            field_name="runtime_artifact_storage_uri",
        )
        checkpoint_path = None
        checkpoint_storage_uri = checkpoint_file.storage_uri if checkpoint_file is not None else None
        if checkpoint_storage_uri is not None:
            checkpoint_path = resolve_local_file_path(
                dataset_storage=self.dataset_storage,
                storage_uri=checkpoint_storage_uri,
                field_name="checkpoint_storage_uri",
            )
        labels_storage_uri = labels_file.storage_uri if labels_file is not None else None
        if labels_storage_uri is not None:
            resolve_local_file_path(
                dataset_storage=self.dataset_storage,
                storage_uri=labels_storage_uri,
                field_name="labels_storage_uri",
            )

        return RuntimeTargetSnapshot(
            project_id=request.project_id,
            model_id=model.model_id,
            model_version_id=model_version.model_version_id,
            model_build_id=model_build.model_build_id if model_build is not None else None,
            model_name=model.model_name,
            model_scale=model.model_scale,
            task_type=model.task_type,
            source_kind=model_version.source_kind,
            runtime_profile_id=_normalize_optional_str(request.runtime_profile_id)
            or (model_build.runtime_profile_id if model_build is not None else None),
            runtime_backend=resolve_runtime_backend(
                runtime_backend=request.runtime_backend,
                model_build_format=model_build.build_format if model_build is not None else None,
            ),
            device_name=normalize_device_name(request.device_name),
            input_size=resolve_input_size(model_version.metadata),
            labels=resolve_labels(
                dataset_storage=self.dataset_storage,
                model_version_metadata=model_version.metadata,
                model_version_id=model_version.model_version_id,
                labels_file=labels_file,
            ),
            runtime_artifact_file_id=runtime_artifact_file.file_id,
            runtime_artifact_storage_uri=runtime_artifact_file.storage_uri,
            runtime_artifact_path=runtime_artifact_path,
            runtime_artifact_file_type=runtime_artifact_file.file_type,
            checkpoint_file_id=checkpoint_file.file_id if checkpoint_file is not None else None,
            checkpoint_storage_uri=checkpoint_storage_uri,
            checkpoint_path=checkpoint_path,
            labels_storage_uri=labels_storage_uri,
        )


def find_model_file(*, model_files: list[ModelFile], file_type: str) -> ModelFile | None:
    """返回首个匹配 file_type 的 ModelFile。

    参数：
    - model_files：待扫描的 ModelFile 列表。
    - file_type：目标文件类型。

    返回：
    - ModelFile | None：首个匹配文件；不存在时返回 None。
    """

    for model_file in model_files:
        if model_file.file_type == file_type:
            return model_file
    return None


def require_model_file(
    *,
    model_files: list[ModelFile],
    file_type: str,
    owner_kind: str,
    owner_id: str,
    missing_message: str,
) -> ModelFile:
    """查找指定类型的 ModelFile；不存在时抛错。

    参数：
    - model_files：待扫描的 ModelFile 列表。
    - file_type：目标文件类型。
    - owner_kind：所属对象类型。
    - owner_id：所属对象 id。
    - missing_message：文件缺失时使用的错误消息。

    返回：
    - ModelFile：匹配到的文件对象。
    """

    model_file = find_model_file(model_files=model_files, file_type=file_type)
    if model_file is None:
        raise InvalidRequestError(
            missing_message,
            details={"owner_kind": owner_kind, "owner_id": owner_id, "file_type": file_type},
        )
    return model_file


def resolve_labels(
    *,
    dataset_storage: LocalDatasetStorage,
    model_version_metadata: dict[str, object],
    model_version_id: str,
    labels_file: ModelFile | None,
) -> tuple[str, ...]:
    """优先从 labels 文件，其次从 metadata 中解析类别名。

    参数：
    - dataset_storage：本地文件存储服务。
    - model_version_metadata：ModelVersion metadata。
    - model_version_id：所属 ModelVersion id。
    - labels_file：可选 labels 文件。

    返回：
    - tuple[str, ...]：解析后的类别列表。
    """

    if labels_file is not None:
        labels_path = resolve_local_file_path(
            dataset_storage=dataset_storage,
            storage_uri=labels_file.storage_uri,
            field_name="labels_storage_uri",
        )
        labels = tuple(
            line.strip()
            for line in labels_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if labels:
            return labels

    metadata_labels = model_version_metadata.get("category_names")
    if isinstance(metadata_labels, list):
        labels = tuple(item.strip() for item in metadata_labels if isinstance(item, str) and item.strip())
        if labels:
            return labels

    raise InvalidRequestError(
        "当前 ModelVersion 缺少可用 labels 信息",
        details={"model_version_id": model_version_id},
    )


def resolve_input_size(model_version_metadata: dict[str, object]) -> tuple[int, int]:
    """从 ModelVersion metadata 中解析输入尺寸。

    参数：
    - model_version_metadata：ModelVersion metadata。

    返回：
    - tuple[int, int]：解析后的输入尺寸；缺省时回退到默认值。
    """

    for candidate in (
        model_version_metadata.get("input_size"),
        _read_nested_value(model_version_metadata, "training_config", "input_size"),
    ):
        if isinstance(candidate, list) and len(candidate) == 2 and all(isinstance(item, int) for item in candidate):
            resolved = (int(candidate[0]), int(candidate[1]))
            if resolved[0] > 0 and resolved[1] > 0:
                return resolved
    return _DEFAULT_INPUT_SIZE


def resolve_local_file_path(
    *,
    dataset_storage: LocalDatasetStorage,
    storage_uri: str,
    field_name: str,
) -> Path:
    """把 object key、本地绝对路径或 file URI 解析为本地绝对路径。

    参数：
    - dataset_storage：本地文件存储服务。
    - storage_uri：待解析的文件位置。
    - field_name：错误消息中使用的字段名。

    返回：
    - Path：解析后的本地绝对路径。
    """

    parsed = urlparse(storage_uri)
    if parsed.scheme == "file":
        raw_path = unquote(parsed.path)
        if raw_path.startswith("/") and len(raw_path) >= 3 and raw_path[2] == ":":
            raw_path = raw_path[1:]
        resolved_path = Path(raw_path)
    elif parsed.scheme and len(parsed.scheme) > 1:
        raise InvalidRequestError(
            f"{field_name} 当前只支持本地文件路径或 object key",
            details={field_name: storage_uri},
        )
    else:
        candidate_path = Path(storage_uri)
        resolved_path = candidate_path if candidate_path.is_absolute() else dataset_storage.resolve(storage_uri)

    if not resolved_path.is_file():
        raise InvalidRequestError(
            f"{field_name} 对应的本地文件不存在",
            details={field_name: storage_uri, "resolved_path": resolved_path.as_posix()},
        )
    return resolved_path


def normalize_runtime_backend(runtime_backend: str | None) -> str:
    """归一化运行时 backend。

    参数：
    - runtime_backend：原始 backend 值。

    返回：
    - str：归一后的 backend 名称。
    """

    normalized_backend = _normalize_optional_str(runtime_backend) or _DEFAULT_RUNTIME_BACKEND
    if normalized_backend not in _SUPPORTED_RUNTIME_BACKENDS:
        raise InvalidRequestError(
            "runtime_backend 不受支持",
            details={"runtime_backend": normalized_backend},
        )
    return normalized_backend


def resolve_runtime_backend(*, runtime_backend: str | None, model_build_format: str | None) -> str:
    """根据绑定对象类型解析最终 runtime backend。"""

    normalized_backend = _normalize_optional_str(runtime_backend)
    if model_build_format is None:
        resolved_backend = normalized_backend or _DEFAULT_RUNTIME_BACKEND
        if resolved_backend != _DEFAULT_RUNTIME_BACKEND:
            raise InvalidRequestError(
                "直接绑定 ModelVersion 时当前仅支持 pytorch backend",
                details={"runtime_backend": resolved_backend},
            )
        return resolved_backend

    expected_backend = resolve_model_build_runtime_backend(model_build_format)
    if normalized_backend is not None and normalize_runtime_backend(normalized_backend) != expected_backend:
        raise InvalidRequestError(
            "runtime_backend 与 ModelBuild build_format 不一致",
            details={
                "runtime_backend": normalized_backend,
                "build_format": model_build_format,
                "expected_runtime_backend": expected_backend,
            },
        )
    return expected_backend


def resolve_model_build_file_type(build_format: str) -> str:
    """把 ModelBuild 的 build_format 映射为运行时文件类型。"""

    if build_format not in _MODEL_BUILD_FILE_TYPE_MAP:
        raise InvalidRequestError(
            "不支持的 ModelBuild build_format",
            details={"build_format": build_format},
        )
    return _MODEL_BUILD_FILE_TYPE_MAP[build_format]


def resolve_model_build_runtime_backend(build_format: str) -> str:
    """把 ModelBuild 的 build_format 映射为默认 runtime backend。"""

    if build_format not in _MODEL_BUILD_RUNTIME_BACKEND_MAP:
        raise InvalidRequestError(
            "不支持的 ModelBuild build_format",
            details={"build_format": build_format},
        )
    return _MODEL_BUILD_RUNTIME_BACKEND_MAP[build_format]


def normalize_device_name(device_name: str | None) -> str:
    """归一化默认 device 名称。

    参数：
    - device_name：原始 device 值。

    返回：
    - str：归一后的 device 名称。
    """

    normalized_device = _normalize_optional_str(device_name) or _DEFAULT_DEVICE_NAME
    if normalized_device == "cuda":
        return "cuda:0"
    if normalized_device == "cpu" or normalized_device.startswith("cuda:"):
        return normalized_device
    raise InvalidRequestError(
        "device_name 必须是 cpu、cuda 或 cuda:<index>",
        details={"device_name": normalized_device},
    )


def _normalize_optional_str(value: str | None) -> str | None:
    """把可选字符串去空白后返回。"""

    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _require_payload_str(payload: dict[str, object], key: str) -> str:
    """从快照字典中读取必填字符串字段。"""

    value = _read_payload_optional_str(payload, key)
    if value is None:
        raise InvalidRequestError(
            "runtime_target_snapshot 缺少必填字符串字段",
            details={"field": key},
        )
    return value


def _read_payload_optional_str(payload: dict[str, object], key: str) -> str | None:
    """从快照字典中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _require_payload_input_size(payload: dict[str, object]) -> tuple[int, int]:
    """从快照字典中读取必填输入尺寸。"""

    value = payload.get("input_size")
    if not isinstance(value, list) or len(value) != 2 or not all(isinstance(item, int) for item in value):
        raise InvalidRequestError(
            "runtime_target_snapshot 的 input_size 不合法",
            details={"input_size": value},
        )
    resolved = (int(value[0]), int(value[1]))
    if resolved[0] <= 0 or resolved[1] <= 0:
        raise InvalidRequestError(
            "runtime_target_snapshot 的 input_size 必须大于 0",
            details={"input_size": value},
        )
    return resolved


def _require_payload_labels(payload: dict[str, object]) -> tuple[str, ...]:
    """从快照字典中读取必填类别列表。"""

    value = payload.get("labels")
    if not isinstance(value, list):
        raise InvalidRequestError("runtime_target_snapshot 的 labels 不合法")
    labels = tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
    if not labels:
        raise InvalidRequestError("runtime_target_snapshot 缺少有效 labels")
    return labels


def _read_nested_value(payload: dict[str, object], parent_key: str, child_key: str) -> object:
    """从嵌套字典中读取某个可选字段。"""

    parent_value = payload.get(parent_key)
    if isinstance(parent_value, dict):
        return parent_value.get(child_key)
    return None
