"""classification 人工验证 session 应用服务。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import PurePosixPath
from uuid import uuid4

from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.project_public_files import resolve_public_project_file_reference
from backend.service.application.runtime.classification_model_runtime import (
    DefaultClassificationModelRuntime,
)
from backend.service.application.runtime.classification_runtime_contracts import (
    ClassificationPredictionCategory,
    ClassificationPredictionRequest,
    ClassificationRuntimeSessionInfo,
    ClassificationRuntimeTensorSpec,
)
from backend.service.application.runtime.yolo11_runtime_target import (
    SqlAlchemyYolo11RuntimeTargetResolver,
)
from backend.service.application.runtime.yolo26_runtime_target import (
    SqlAlchemyYolo26RuntimeTargetResolver,
)
from backend.service.application.runtime.yolov8_runtime_target import (
    SqlAlchemyYoloV8RuntimeTargetResolver,
)
from backend.service.application.runtime.yolox_runtime_target import (
    RuntimeTargetResolveRequest,
    RuntimeTargetSnapshot,
    normalize_device_name as normalize_runtime_target_device_name,
    normalize_runtime_backend as normalize_runtime_target_backend,
    resolve_local_file_path,
    resolve_runtime_precision,
)
from backend.service.domain.files.classification_model_file_types import (
    YOLO_PRIMARY_CLASSIFICATION_FILE_TYPES,
)
from backend.service.domain.models.model_task_types import CLASSIFICATION_TASK_TYPE
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


_VALIDATION_SESSION_STATUS_READY = "ready"
_VALIDATION_RUNTIME_BACKEND = "pytorch"
_SUPPORTED_VALIDATION_RUNTIME_BACKENDS = frozenset({"pytorch", "onnxruntime", "openvino", "tensorrt"})
_DEFAULT_TOP_K = 5
_DEFAULT_INPUT_SIZE = (224, 224)
_SUPPORTED_CLASSIFICATION_MODEL_TYPES = ("yolov8", "yolo11", "yolo26")


@dataclass(frozen=True)
class ClassificationValidationSessionCreateRequest:
    project_id: str
    model_type: str
    model_version_id: str
    runtime_profile_id: str | None = None
    runtime_backend: str | None = None
    device_name: str | None = None
    top_k: int | None = None
    save_result_image: bool = True
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ClassificationValidationSessionPredictRequest:
    input_uri: str | None = None
    input_file_id: str | None = None
    top_k: int | None = None
    save_result_image: bool | None = None
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ClassificationValidationPredictionSummary:
    prediction_id: str
    created_at: str
    input_uri: str | None
    input_file_id: str | None
    category_count: int
    preview_image_uri: str | None = None
    raw_result_uri: str | None = None
    latency_ms: float | None = None


@dataclass(frozen=True)
class ClassificationValidationSessionView:
    session_id: str
    project_id: str
    model_type: str
    model_id: str
    model_version_id: str
    model_name: str
    model_scale: str
    source_kind: str
    status: str
    model_build_id: str | None
    runtime_profile_id: str | None
    runtime_backend: str
    device_name: str
    runtime_precision: str
    top_k: int
    save_result_image: bool
    input_size: tuple[int, int]
    labels: tuple[str, ...]
    runtime_artifact_file_id: str
    runtime_artifact_storage_uri: str
    runtime_artifact_file_type: str
    checkpoint_file_id: str | None
    checkpoint_storage_uri: str | None
    extra_options: dict[str, object]
    created_at: str
    updated_at: str
    created_by: str | None = None
    last_prediction: ClassificationValidationPredictionSummary | None = None


@dataclass(frozen=True)
class ClassificationValidationPredictionView:
    prediction_id: str
    session_id: str
    created_at: str
    input_uri: str | None
    input_file_id: str | None
    top_k: int
    save_result_image: bool
    categories: tuple[ClassificationPredictionCategory, ...]
    top_category: ClassificationPredictionCategory | None
    preview_image_uri: str | None
    raw_result_uri: str
    latency_ms: float | None
    image_width: int
    image_height: int
    labels: tuple[str, ...]
    runtime_session_info: ClassificationRuntimeSessionInfo


class LocalClassificationValidationSessionService:
    """管理 classification 人工验证 session 的本地实现。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        classification_runtime: DefaultClassificationModelRuntime | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.classification_runtime = classification_runtime or DefaultClassificationModelRuntime()

    def create_session(
        self,
        request: ClassificationValidationSessionCreateRequest,
        *,
        created_by: str | None,
    ) -> ClassificationValidationSessionView:
        normalized_model_type = _normalize_model_type(request.model_type)
        normalized_runtime_backend = _normalize_runtime_backend(request.runtime_backend)
        resolver = _build_runtime_target_resolver(
            model_type=normalized_model_type,
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
        )
        runtime_target = resolver.resolve_target(
            RuntimeTargetResolveRequest(
                project_id=request.project_id,
                model_version_id=request.model_version_id,
                runtime_profile_id=request.runtime_profile_id,
                runtime_backend=normalized_runtime_backend,
                device_name=_normalize_device_name(
                    request.device_name,
                    runtime_backend=normalized_runtime_backend,
                ),
            )
        )
        if runtime_target.model_type != normalized_model_type:
            raise InvalidRequestError(
                "请求中的 model_type 与 ModelVersion 绑定模型不匹配",
                details={
                    "requested_model_type": normalized_model_type,
                    "resolved_model_type": runtime_target.model_type,
                    "model_version_id": request.model_version_id,
                },
            )

        top_k = _resolve_positive_int(request.top_k, field_name="top_k", default=_DEFAULT_TOP_K)
        runtime_artifact_file_id = _require_non_empty_str(
            runtime_target.runtime_artifact_file_id,
            field_name="runtime_artifact_file_id",
        )
        runtime_artifact_storage_uri = _require_non_empty_str(
            runtime_target.runtime_artifact_storage_uri,
            field_name="runtime_artifact_storage_uri",
        )
        runtime_artifact_file_type = _require_non_empty_str(
            runtime_target.runtime_artifact_file_type,
            field_name="runtime_artifact_file_type",
        )
        session_id = f"validation-session-{uuid4().hex}"
        now = _now_isoformat()
        session = ClassificationValidationSessionView(
            session_id=session_id,
            project_id=request.project_id,
            model_type=runtime_target.model_type,
            model_id=runtime_target.model_id,
            model_version_id=runtime_target.model_version_id,
            model_name=runtime_target.model_name,
            model_scale=runtime_target.model_scale,
            source_kind=runtime_target.source_kind,
            status=_VALIDATION_SESSION_STATUS_READY,
            model_build_id=runtime_target.model_build_id,
            runtime_profile_id=runtime_target.runtime_profile_id,
            runtime_backend=runtime_target.runtime_backend,
            device_name=runtime_target.device_name,
            runtime_precision=runtime_target.runtime_precision,
            top_k=top_k,
            save_result_image=bool(request.save_result_image),
            input_size=runtime_target.input_size,
            labels=runtime_target.labels,
            runtime_artifact_file_id=runtime_artifact_file_id,
            runtime_artifact_storage_uri=runtime_artifact_storage_uri,
            runtime_artifact_file_type=runtime_artifact_file_type,
            checkpoint_file_id=_normalize_optional_str(runtime_target.checkpoint_file_id),
            checkpoint_storage_uri=_normalize_optional_str(runtime_target.checkpoint_storage_uri),
            extra_options=_normalize_extra_options(request.extra_options),
            created_at=now,
            updated_at=now,
            created_by=_normalize_optional_str(created_by),
        )
        self._write_session(session)
        return session

    def get_session(self, session_id: str) -> ClassificationValidationSessionView:
        session_path = self._session_path(session_id)
        if not self.dataset_storage.resolve(session_path).is_file():
            raise ResourceNotFoundError("指定的 validation session 不存在", details={"session_id": session_id})
        payload = self.dataset_storage.read_json(session_path)
        if not isinstance(payload, dict):
            raise ResourceNotFoundError("指定的 validation session 数据损坏", details={"session_id": session_id})
        return _build_session_from_payload(payload)

    def predict(
        self,
        session_id: str,
        request: ClassificationValidationSessionPredictRequest,
    ) -> ClassificationValidationPredictionView:
        session = self.get_session(session_id)
        input_uri = _normalize_optional_str(request.input_uri)
        input_file_id = _normalize_optional_str(request.input_file_id)
        if input_uri is not None and input_file_id is not None:
            raise InvalidRequestError(
                "input_uri 和 input_file_id 只能提供一个",
                details={"session_id": session_id, "input_uri": input_uri, "input_file_id": input_file_id},
            )
        resolved_input_file_id = input_file_id
        if input_file_id is not None:
            reference = resolve_public_project_file_reference(
                dataset_storage=self.dataset_storage,
                file_id=input_file_id,
                expected_project_id=session.project_id,
                field_name="input_file_id",
            )
            input_uri = reference.object_key
        if input_uri is None:
            raise InvalidRequestError("predict 请求必须提供 input_uri 或 input_file_id")

        top_k = _resolve_positive_int(request.top_k, field_name="top_k", default=session.top_k)
        save_result_image = (
            session.save_result_image if request.save_result_image is None else bool(request.save_result_image)
        )
        merged_extra_options = dict(session.extra_options)
        merged_extra_options.update(_normalize_extra_options(request.extra_options))

        execution = self._run_classification_validation_prediction(
            session=session,
            input_uri=input_uri,
            top_k=top_k,
            save_result_image=save_result_image,
        )

        prediction_id = f"prediction-{uuid4().hex}"
        created_at = _now_isoformat()
        prediction_output_dir = self._prediction_output_dir(session_id, prediction_id)
        raw_result_uri = str(prediction_output_dir / "raw-result.json")
        preview_image_uri: str | None = None
        if save_result_image and execution.preview_image_bytes is not None:
            preview_image_uri = str(prediction_output_dir / "preview.jpg")
            self.dataset_storage.write_bytes(preview_image_uri, execution.preview_image_bytes)

        raw_result_payload = {
            "prediction_id": prediction_id,
            "session_id": session.session_id,
            "created_at": created_at,
            "input_uri": input_uri,
            "input_file_id": resolved_input_file_id,
            "top_k": top_k,
            "save_result_image": save_result_image,
            "latency_ms": execution.latency_ms,
            "image_width": execution.image_width,
            "image_height": execution.image_height,
            "labels": list(session.labels),
            "categories": [_serialize_category(c) for c in execution.categories],
            "top_category": _serialize_category(execution.top_category) if execution.top_category else None,
            "runtime_session_info": _serialize_runtime_session_info(execution.runtime_session_info),
            "preview_image_uri": preview_image_uri,
        }
        self.dataset_storage.write_json(raw_result_uri, raw_result_payload)

        summary = ClassificationValidationPredictionSummary(
            prediction_id=prediction_id,
            created_at=created_at,
            input_uri=input_uri,
            input_file_id=resolved_input_file_id,
            category_count=len(execution.categories),
            preview_image_uri=preview_image_uri,
            raw_result_uri=raw_result_uri,
            latency_ms=execution.latency_ms,
        )
        self._write_session(replace(session, updated_at=created_at, last_prediction=summary))

        return ClassificationValidationPredictionView(
            prediction_id=prediction_id,
            session_id=session.session_id,
            created_at=created_at,
            input_uri=input_uri,
            input_file_id=resolved_input_file_id,
            top_k=top_k,
            save_result_image=save_result_image,
            categories=execution.categories,
            top_category=execution.top_category,
            preview_image_uri=preview_image_uri,
            raw_result_uri=raw_result_uri,
            latency_ms=execution.latency_ms,
            image_width=execution.image_width,
            image_height=execution.image_height,
            labels=session.labels,
            runtime_session_info=execution.runtime_session_info,
        )

    def _run_classification_validation_prediction(
        self,
        *,
        session: ClassificationValidationSessionView,
        input_uri: str,
        top_k: int,
        save_result_image: bool,
    ) -> ClassificationPredictionExecutionResult:
        runtime_target = _build_runtime_target_from_session(session=session, dataset_storage=self.dataset_storage)
        runtime_session = self.classification_runtime.load_session(
            dataset_storage=self.dataset_storage,
            runtime_target=runtime_target,
        )
        return runtime_session.predict(
            ClassificationPredictionRequest(
                input_uri=input_uri,
                top_k=top_k,
                save_result_image=save_result_image,
            )
        )

    def _write_session(self, session: ClassificationValidationSessionView) -> None:
        self.dataset_storage.write_json(self._session_path(session.session_id), _serialize_session(session))

    @staticmethod
    def _session_path(session_id: str) -> str:
        return str(PurePosixPath("runtime") / "validation-sessions-classification" / session_id / "session.json")

    @staticmethod
    def _prediction_output_dir(session_id: str, prediction_id: str) -> PurePosixPath:
        return PurePosixPath("runtime") / "validation-sessions-classification" / session_id / "predictions" / prediction_id


def _build_runtime_target_resolver(
    *,
    model_type: str,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
):
    resolver_factory_map = {
        "yolov8": SqlAlchemyYoloV8RuntimeTargetResolver,
        "yolo11": SqlAlchemyYolo11RuntimeTargetResolver,
        "yolo26": SqlAlchemyYolo26RuntimeTargetResolver,
    }
    resolver_factory = resolver_factory_map.get(model_type)
    if resolver_factory is None:
        raise InvalidRequestError(
            "当前 classification validation session 不支持指定模型分类",
            details={"model_type": model_type, "supported_model_types": list(_SUPPORTED_CLASSIFICATION_MODEL_TYPES)},
        )
    return resolver_factory(session_factory=session_factory, dataset_storage=dataset_storage)


def _build_runtime_target_from_session(
    *,
    session: ClassificationValidationSessionView,
    dataset_storage: LocalDatasetStorage,
) -> RuntimeTargetSnapshot:
    runtime_artifact_path = resolve_local_file_path(
        dataset_storage=dataset_storage,
        storage_uri=session.runtime_artifact_storage_uri,
        field_name="runtime_artifact_storage_uri",
    )
    checkpoint_path = None
    if session.checkpoint_storage_uri is not None:
        checkpoint_path = resolve_local_file_path(
            dataset_storage=dataset_storage,
            storage_uri=session.checkpoint_storage_uri,
            field_name="checkpoint_storage_uri",
        )
    return RuntimeTargetSnapshot(
        project_id=session.project_id,
        model_id=session.model_id,
        model_type=session.model_type,
        model_version_id=session.model_version_id,
        model_build_id=session.model_build_id,
        model_name=session.model_name,
        model_scale=session.model_scale,
        task_type=CLASSIFICATION_TASK_TYPE,
        source_kind=session.source_kind,
        runtime_profile_id=session.runtime_profile_id,
        runtime_backend=session.runtime_backend,
        device_name=session.device_name,
        runtime_precision=session.runtime_precision,
        input_size=session.input_size,
        labels=session.labels,
        runtime_artifact_file_id=session.runtime_artifact_file_id,
        runtime_artifact_storage_uri=session.runtime_artifact_storage_uri,
        runtime_artifact_path=runtime_artifact_path,
        runtime_artifact_file_type=session.runtime_artifact_file_type,
        checkpoint_file_id=session.checkpoint_file_id,
        checkpoint_storage_uri=session.checkpoint_storage_uri,
        checkpoint_path=checkpoint_path,
        labels_storage_uri=None,
    )


def _serialize_category(category: ClassificationPredictionCategory) -> dict[str, object]:
    return {
        "class_id": category.class_id,
        "class_name": category.class_name,
        "probability": category.probability,
        "logit": category.logit,
    }


def _serialize_runtime_session_info(session_info: ClassificationRuntimeSessionInfo) -> dict[str, object]:
    return {
        "backend_name": session_info.backend_name,
        "model_uri": session_info.model_uri,
        "device_name": session_info.device_name,
        "input_spec": {
            "name": session_info.input_spec.name,
            "shape": list(session_info.input_spec.shape),
            "dtype": session_info.input_spec.dtype,
        },
        "output_spec": {
            "name": session_info.output_spec.name,
            "shape": list(session_info.output_spec.shape),
            "dtype": session_info.output_spec.dtype,
        },
        "metadata": dict(session_info.metadata),
    }


def _serialize_session(session: ClassificationValidationSessionView) -> dict[str, object]:
    return {
        "session_id": session.session_id,
        "project_id": session.project_id,
        "model_type": session.model_type,
        "model_id": session.model_id,
        "model_version_id": session.model_version_id,
        "model_name": session.model_name,
        "model_scale": session.model_scale,
        "source_kind": session.source_kind,
        "status": session.status,
        "model_build_id": session.model_build_id,
        "runtime_profile_id": session.runtime_profile_id,
        "runtime_backend": session.runtime_backend,
        "device_name": session.device_name,
        "runtime_precision": session.runtime_precision,
        "top_k": session.top_k,
        "save_result_image": session.save_result_image,
        "input_size": [session.input_size[0], session.input_size[1]],
        "labels": list(session.labels),
        "runtime_artifact_file_id": session.runtime_artifact_file_id,
        "runtime_artifact_storage_uri": session.runtime_artifact_storage_uri,
        "runtime_artifact_file_type": session.runtime_artifact_file_type,
        "checkpoint_file_id": session.checkpoint_file_id,
        "checkpoint_storage_uri": session.checkpoint_storage_uri,
        "extra_options": dict(session.extra_options),
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "created_by": session.created_by,
        "last_prediction": _serialize_prediction_summary(session.last_prediction),
    }


def _serialize_prediction_summary(summary: ClassificationValidationPredictionSummary | None) -> dict[str, object] | None:
    if summary is None:
        return None
    return {
        "prediction_id": summary.prediction_id,
        "created_at": summary.created_at,
        "input_uri": summary.input_uri,
        "input_file_id": summary.input_file_id,
        "category_count": summary.category_count,
        "preview_image_uri": summary.preview_image_uri,
        "raw_result_uri": summary.raw_result_uri,
        "latency_ms": summary.latency_ms,
    }


def _build_session_from_payload(payload: dict[str, object]) -> ClassificationValidationSessionView:
    raw_input_size = payload.get("input_size")
    if not isinstance(raw_input_size, list) or len(raw_input_size) != 2 or not all(isinstance(item, int) for item in raw_input_size):
        raise ResourceNotFoundError("validation session 的 input_size 无效")
    runtime_backend = _require_payload_str(payload, "runtime_backend")
    device_name = _require_payload_str(payload, "device_name")
    model_type = _read_payload_optional_str(payload, "model_type") or "yolov8"
    runtime_artifact_file_id = (
        _read_payload_optional_str(payload, "runtime_artifact_file_id")
        or _require_payload_str(payload, "checkpoint_file_id")
    )
    runtime_artifact_storage_uri = (
        _read_payload_optional_str(payload, "runtime_artifact_storage_uri")
        or _require_payload_str(payload, "checkpoint_storage_uri")
    )
    runtime_artifact_file_type = (
        _read_payload_optional_str(payload, "runtime_artifact_file_type")
        or YOLO_PRIMARY_CLASSIFICATION_FILE_TYPES.checkpoint_file_type
    )
    return ClassificationValidationSessionView(
        session_id=_require_payload_str(payload, "session_id"),
        project_id=_require_payload_str(payload, "project_id"),
        model_type=_normalize_model_type(model_type),
        model_id=_require_payload_str(payload, "model_id"),
        model_version_id=_require_payload_str(payload, "model_version_id"),
        model_name=_require_payload_str(payload, "model_name"),
        model_scale=_require_payload_str(payload, "model_scale"),
        source_kind=_require_payload_str(payload, "source_kind"),
        status=_require_payload_str(payload, "status"),
        model_build_id=_read_payload_optional_str(payload, "model_build_id"),
        runtime_profile_id=_read_payload_optional_str(payload, "runtime_profile_id"),
        runtime_backend=runtime_backend,
        device_name=device_name,
        runtime_precision=resolve_runtime_precision(
            runtime_precision=_read_payload_optional_str(payload, "runtime_precision"),
            runtime_backend=runtime_backend,
            device_name=device_name,
        ),
        top_k=int(payload.get("top_k", _DEFAULT_TOP_K)),
        save_result_image=bool(payload.get("save_result_image", True)),
        input_size=(int(raw_input_size[0]), int(raw_input_size[1])),
        labels=tuple(_read_str_list(payload.get("labels"))),
        runtime_artifact_file_id=runtime_artifact_file_id,
        runtime_artifact_storage_uri=runtime_artifact_storage_uri,
        runtime_artifact_file_type=runtime_artifact_file_type,
        checkpoint_file_id=_read_payload_optional_str(payload, "checkpoint_file_id"),
        checkpoint_storage_uri=_read_payload_optional_str(payload, "checkpoint_storage_uri"),
        extra_options=_normalize_extra_options(payload.get("extra_options")),
        created_at=_require_payload_str(payload, "created_at"),
        updated_at=_require_payload_str(payload, "updated_at"),
        created_by=_read_payload_optional_str(payload, "created_by"),
        last_prediction=_build_prediction_summary_from_payload(payload.get("last_prediction")),
    )


def _build_prediction_summary_from_payload(payload: object) -> ClassificationValidationPredictionSummary | None:
    if not isinstance(payload, dict):
        return None
    raw_count = payload.get("category_count", 0)
    category_count = raw_count if isinstance(raw_count, int) else 0
    raw_latency = payload.get("latency_ms")
    latency_ms = float(raw_latency) if isinstance(raw_latency, int | float) else None
    return ClassificationValidationPredictionSummary(
        prediction_id=_require_payload_str(payload, "prediction_id"),
        created_at=_require_payload_str(payload, "created_at"),
        input_uri=_read_payload_optional_str(payload, "input_uri"),
        input_file_id=_read_payload_optional_str(payload, "input_file_id"),
        category_count=category_count,
        preview_image_uri=_read_payload_optional_str(payload, "preview_image_uri"),
        raw_result_uri=_read_payload_optional_str(payload, "raw_result_uri"),
        latency_ms=latency_ms,
    )


# -- helpers --

def _normalize_model_type(model_type: str | None) -> str:
    normalized = _normalize_optional_str(model_type)
    if normalized is None:
        raise InvalidRequestError("model_type 不能为空")
    if normalized not in _SUPPORTED_CLASSIFICATION_MODEL_TYPES:
        raise InvalidRequestError(
            "当前 classification validation session 不支持指定模型分类",
            details={"model_type": normalized, "supported_model_types": list(_SUPPORTED_CLASSIFICATION_MODEL_TYPES)},
        )
    return normalized


def _normalize_runtime_backend(runtime_backend: str | None) -> str:
    normalized = normalize_runtime_target_backend(
        _normalize_optional_str(runtime_backend) or _VALIDATION_RUNTIME_BACKEND
    )
    if normalized not in _SUPPORTED_VALIDATION_RUNTIME_BACKENDS:
        raise InvalidRequestError(
            "当前 classification validation session 不支持指定 runtime_backend",
            details={
                "runtime_backend": normalized,
                "supported_runtime_backends": sorted(_SUPPORTED_VALIDATION_RUNTIME_BACKENDS),
            },
        )
    return normalized


def _normalize_device_name(device_name: str | None, *, runtime_backend: str) -> str:
    return normalize_runtime_target_device_name(
        _normalize_optional_str(device_name),
        runtime_backend=runtime_backend,
    )


def _normalize_extra_options(extra_options: object) -> dict[str, object]:
    if not isinstance(extra_options, dict):
        return {}
    return {str(key): value for key, value in extra_options.items()}


def _normalize_optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _resolve_positive_int(value: object, *, field_name: str, default: int) -> int:
    resolved = int(value) if isinstance(value, int | float) else default
    if resolved <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0", details={field_name: resolved})
    return resolved


def _require_non_empty_str(value: str | None, *, field_name: str) -> str:
    normalized = _normalize_optional_str(value)
    if normalized is not None:
        return normalized
    raise InvalidRequestError("validation session 缺少必要模型文件引用", details={"field": field_name})


def _require_payload_str(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ResourceNotFoundError("validation session 数据缺少必要字段", details={"field": key})


def _read_payload_optional_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _read_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _now_isoformat() -> str:
    return datetime.now(timezone.utc).isoformat()
