"""segmentation 人工验证 session 服务。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import PurePosixPath
from uuid import uuid4

from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.model_type_support import require_supported_platform_model_type
from backend.service.application.project_public_files import resolve_public_project_file_reference
from backend.service.application.runtime.tasks.segmentation_model_runtime import DefaultSegmentationModelRuntime
from backend.service.application.runtime.contracts.segmentation.prediction import (
    SegmentationPredictionInstance,
    SegmentationPredictionRequest,
    SegmentationRuntimeSessionInfo,
)
from backend.service.application.runtime.targets.yolo11 import SqlAlchemyYolo11RuntimeTargetResolver
from backend.service.application.runtime.targets.yolo26 import SqlAlchemyYolo26RuntimeTargetResolver
from backend.service.application.runtime.targets.rfdetr import SqlAlchemyRfdetrRuntimeTargetResolver
from backend.service.application.runtime.targets.yolov8 import SqlAlchemyYoloV8RuntimeTargetResolver
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetResolveRequest,
    RuntimeTargetSnapshot,
    normalize_device_name as normalize_runtime_target_device_name,
    normalize_runtime_backend as normalize_runtime_target_backend,
    resolve_local_file_path,
    resolve_runtime_precision,
)
from backend.service.domain.models.model_task_types import SEGMENTATION_TASK_TYPE
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


_VALIDATION_SESSION_STATUS_READY = "ready"
_VALIDATION_RUNTIME_BACKEND = "pytorch"
_SUPPORTED_VALIDATION_RUNTIME_BACKENDS = frozenset({"pytorch", "onnxruntime", "openvino", "tensorrt"})
_DEFAULT_SCORE_THRESHOLD = 0.3
_DEFAULT_MASK_THRESHOLD = 0.5
_DEFAULT_INPUT_SIZE = (640, 640)
@dataclass(frozen=True)
class SegmentationValidationSessionCreateRequest:
    project_id: str
    model_type: str
    model_version_id: str
    runtime_profile_id: str | None = None
    runtime_backend: str | None = None
    device_name: str | None = None
    score_threshold: float | None = None
    mask_threshold: float | None = None
    save_result_image: bool = True
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SegmentationValidationSessionPredictRequest:
    input_uri: str | None = None
    input_file_id: str | None = None
    score_threshold: float | None = None
    mask_threshold: float | None = None
    save_result_image: bool | None = None
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SegmentationValidationPredictionSummary:
    prediction_id: str
    created_at: str
    input_uri: str | None
    input_file_id: str | None
    instance_count: int
    preview_image_uri: str | None = None
    raw_result_uri: str | None = None
    latency_ms: float | None = None


@dataclass(frozen=True)
class SegmentationValidationSessionView:
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
    score_threshold: float
    mask_threshold: float
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
    last_prediction: SegmentationValidationPredictionSummary | None = None


@dataclass(frozen=True)
class SegmentationValidationPredictionView:
    prediction_id: str
    session_id: str
    created_at: str
    input_uri: str | None
    input_file_id: str | None
    score_threshold: float
    mask_threshold: float
    save_result_image: bool
    instances: tuple[SegmentationPredictionInstance, ...]
    preview_image_uri: str | None
    raw_result_uri: str
    latency_ms: float | None
    image_width: int
    image_height: int
    labels: tuple[str, ...]
    runtime_session_info: SegmentationRuntimeSessionInfo


class LocalSegmentationValidationSessionService:
    """管理 segmentation 人工验证 session 的本地实现。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        segmentation_runtime: DefaultSegmentationModelRuntime | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.segmentation_runtime = segmentation_runtime or DefaultSegmentationModelRuntime()

    def create_session(
        self,
        request: SegmentationValidationSessionCreateRequest,
        *,
        created_by: str | None,
    ) -> SegmentationValidationSessionView:
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
                details={"requested_model_type": normalized_model_type, "resolved_model_type": runtime_target.model_type, "model_version_id": request.model_version_id},
            )
        score_threshold = _resolve_probability(request.score_threshold, default=_DEFAULT_SCORE_THRESHOLD)
        mask_threshold = _resolve_probability(request.mask_threshold, default=_DEFAULT_MASK_THRESHOLD)
        runtime_artifact_file_id = _require_non_empty_str(runtime_target.runtime_artifact_file_id, field_name="runtime_artifact_file_id")
        runtime_artifact_storage_uri = _require_non_empty_str(runtime_target.runtime_artifact_storage_uri, field_name="runtime_artifact_storage_uri")
        runtime_artifact_file_type = _require_non_empty_str(runtime_target.runtime_artifact_file_type, field_name="runtime_artifact_file_type")
        session_id = f"validation-session-{uuid4().hex}"
        now = _now_isoformat()
        session = SegmentationValidationSessionView(
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
            score_threshold=score_threshold,
            mask_threshold=mask_threshold,
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

    def get_session(self, session_id: str) -> SegmentationValidationSessionView:
        session_path = self._session_path(session_id)
        if not self.dataset_storage.resolve(session_path).is_file():
            raise ResourceNotFoundError("指定的 validation session 不存在", details={"session_id": session_id})
        payload = self.dataset_storage.read_json(session_path)
        if not isinstance(payload, dict):
            raise ResourceNotFoundError("指定的 validation session 数据损坏", details={"session_id": session_id})
        return _build_session_from_payload(payload)

    def predict(self, session_id: str, request: SegmentationValidationSessionPredictRequest) -> SegmentationValidationPredictionView:
        session = self.get_session(session_id)
        input_uri = _normalize_optional_str(request.input_uri)
        input_file_id = _normalize_optional_str(request.input_file_id)
        if input_uri is not None and input_file_id is not None:
            raise InvalidRequestError("input_uri 和 input_file_id 只能提供一个", details={"session_id": session_id})
        resolved_input_file_id = input_file_id
        if input_file_id is not None:
            ref = resolve_public_project_file_reference(dataset_storage=self.dataset_storage, file_id=input_file_id, expected_project_id=session.project_id, field_name="input_file_id")
            input_uri = ref.object_key
        if input_uri is None:
            raise InvalidRequestError("predict 请求必须提供 input_uri 或 input_file_id")
        score_threshold = _resolve_probability(request.score_threshold, default=session.score_threshold)
        mask_threshold = _resolve_probability(request.mask_threshold, default=session.mask_threshold)
        save_result_image = session.save_result_image if request.save_result_image is None else bool(request.save_result_image)
        runtime_target = _build_runtime_target_from_session(session=session, dataset_storage=self.dataset_storage)
        runtime_session = self.segmentation_runtime.load_session(dataset_storage=self.dataset_storage, runtime_target=runtime_target)
        execution = runtime_session.predict(
            SegmentationPredictionRequest(
                input_uri=input_uri,
                score_threshold=score_threshold,
                mask_threshold=mask_threshold,
                save_result_image=save_result_image,
            )
        )
        prediction_id = f"prediction-{uuid4().hex}"
        created_at = _now_isoformat()
        output_dir = self._prediction_output_dir(session_id, prediction_id)
        raw_result_uri = str(output_dir / "raw-result.json")
        preview_image_uri: str | None = None
        if save_result_image and execution.preview_image_bytes is not None:
            preview_image_uri = str(output_dir / "preview.jpg")
            self.dataset_storage.write_bytes(preview_image_uri, execution.preview_image_bytes)
        raw_payload = {
            "prediction_id": prediction_id,
            "session_id": session.session_id,
            "created_at": created_at,
            "input_uri": input_uri,
            "input_file_id": resolved_input_file_id,
            "score_threshold": score_threshold,
            "mask_threshold": mask_threshold,
            "save_result_image": save_result_image,
            "latency_ms": execution.latency_ms,
            "image_width": execution.image_width,
            "image_height": execution.image_height,
            "labels": list(session.labels),
            "instances": [_serialize_instance(inst) for inst in execution.instances],
            "runtime_session_info": _serialize_runtime_info(execution.runtime_session_info),
            "preview_image_uri": preview_image_uri,
        }
        self.dataset_storage.write_json(raw_result_uri, raw_payload)
        summary = SegmentationValidationPredictionSummary(
            prediction_id=prediction_id,
            created_at=created_at,
            input_uri=input_uri,
            input_file_id=resolved_input_file_id,
            instance_count=len(execution.instances),
            preview_image_uri=preview_image_uri,
            raw_result_uri=raw_result_uri,
            latency_ms=execution.latency_ms,
        )
        self._write_session(replace(session, updated_at=created_at, last_prediction=summary))
        return SegmentationValidationPredictionView(
            prediction_id=prediction_id,
            session_id=session.session_id,
            created_at=created_at,
            input_uri=input_uri,
            input_file_id=resolved_input_file_id,
            score_threshold=score_threshold,
            mask_threshold=mask_threshold,
            save_result_image=save_result_image,
            instances=execution.instances,
            preview_image_uri=preview_image_uri,
            raw_result_uri=raw_result_uri,
            latency_ms=execution.latency_ms,
            image_width=execution.image_width,
            image_height=execution.image_height,
            labels=session.labels,
            runtime_session_info=execution.runtime_session_info,
        )

    def _write_session(self, session: SegmentationValidationSessionView) -> None:
        self.dataset_storage.write_json(self._session_path(session.session_id), _serialize_session(session))

    @staticmethod
    def _session_path(session_id: str) -> str:
        return str(PurePosixPath("runtime") / "validation-sessions-segmentation" / session_id / "session.json")

    @staticmethod
    def _prediction_output_dir(session_id: str, prediction_id: str) -> PurePosixPath:
        return PurePosixPath("runtime") / "validation-sessions-segmentation" / session_id / "predictions" / prediction_id


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
        "rfdetr": SqlAlchemyRfdetrRuntimeTargetResolver,
    }
    resolver_factory = resolver_factory_map.get(model_type)
    if resolver_factory is None:
        raise InvalidRequestError(
            "当前 segmentation validation session 不支持指定模型分类",
            details={
                "model_type": model_type,
                "supported_model_types": list(resolver_factory_map),
            },
        )
    return resolver_factory(session_factory=session_factory, dataset_storage=dataset_storage)


def _build_runtime_target_from_session(*, session: SegmentationValidationSessionView, dataset_storage: LocalDatasetStorage) -> RuntimeTargetSnapshot:
    runtime_artifact_path = resolve_local_file_path(dataset_storage=dataset_storage, storage_uri=session.runtime_artifact_storage_uri, field_name="runtime_artifact_storage_uri")
    checkpoint_path = None
    if session.checkpoint_storage_uri is not None:
        checkpoint_path = resolve_local_file_path(dataset_storage=dataset_storage, storage_uri=session.checkpoint_storage_uri, field_name="checkpoint_storage_uri")
    return RuntimeTargetSnapshot(
        project_id=session.project_id, model_id=session.model_id, model_type=session.model_type, model_version_id=session.model_version_id,
        model_build_id=session.model_build_id, model_name=session.model_name, model_scale=session.model_scale, task_type=SEGMENTATION_TASK_TYPE,
        source_kind=session.source_kind, runtime_profile_id=session.runtime_profile_id, runtime_backend=session.runtime_backend,
        device_name=session.device_name, runtime_precision=session.runtime_precision, input_size=session.input_size, labels=session.labels,
        runtime_artifact_file_id=session.runtime_artifact_file_id, runtime_artifact_storage_uri=session.runtime_artifact_storage_uri,
        runtime_artifact_path=runtime_artifact_path, runtime_artifact_file_type=session.runtime_artifact_file_type,
        checkpoint_file_id=session.checkpoint_file_id, checkpoint_storage_uri=session.checkpoint_storage_uri, checkpoint_path=checkpoint_path,
        labels_storage_uri=None,
    )


def _serialize_instance(inst: SegmentationPredictionInstance) -> dict[str, object]:
    return {"bbox_xyxy": list(inst.bbox_xyxy), "score": inst.score, "class_id": inst.class_id, "class_name": inst.class_name, "segments": inst.segments, "mask_area": inst.mask_area}


def _serialize_runtime_info(info: SegmentationRuntimeSessionInfo) -> dict[str, object]:
    return {
        "backend_name": info.backend_name, "model_uri": info.model_uri, "device_name": info.device_name,
        "input_spec": {"name": info.input_spec.name, "shape": list(info.input_spec.shape), "dtype": info.input_spec.dtype},
        "output_specs": [{"name": s.name, "shape": list(s.shape), "dtype": s.dtype} for s in info.output_specs],
        "metadata": dict(info.metadata),
    }


def _serialize_session(session: SegmentationValidationSessionView) -> dict[str, object]:
    return {
        "session_id": session.session_id, "project_id": session.project_id, "model_type": session.model_type,
        "model_id": session.model_id, "model_version_id": session.model_version_id, "model_name": session.model_name,
        "model_scale": session.model_scale, "source_kind": session.source_kind, "status": session.status,
        "model_build_id": session.model_build_id,
        "runtime_profile_id": session.runtime_profile_id, "runtime_backend": session.runtime_backend,
        "device_name": session.device_name, "runtime_precision": session.runtime_precision,
        "score_threshold": session.score_threshold, "mask_threshold": session.mask_threshold,
        "save_result_image": session.save_result_image, "input_size": list(session.input_size), "labels": list(session.labels),
        "runtime_artifact_file_id": session.runtime_artifact_file_id,
        "runtime_artifact_storage_uri": session.runtime_artifact_storage_uri,
        "runtime_artifact_file_type": session.runtime_artifact_file_type,
        "checkpoint_file_id": session.checkpoint_file_id, "checkpoint_storage_uri": session.checkpoint_storage_uri,
        "extra_options": dict(session.extra_options), "created_at": session.created_at, "updated_at": session.updated_at,
        "created_by": session.created_by, "last_prediction": _serialize_summary(session.last_prediction),
    }


def _serialize_summary(s: SegmentationValidationPredictionSummary | None) -> dict[str, object] | None:
    if s is None:
        return None
    return {"prediction_id": s.prediction_id, "created_at": s.created_at, "input_uri": s.input_uri, "input_file_id": s.input_file_id, "instance_count": s.instance_count, "preview_image_uri": s.preview_image_uri, "raw_result_uri": s.raw_result_uri, "latency_ms": s.latency_ms}


def _build_session_from_payload(payload: dict[str, object]) -> SegmentationValidationSessionView:
    raw_is = payload.get("input_size")
    if not isinstance(raw_is, list) or len(raw_is) != 2:
        raise ResourceNotFoundError("validation session 的 input_size 无效")
    rb = _require_payload_str(payload, "runtime_backend")
    dn = _require_payload_str(payload, "device_name")
    mt = _read_payload_optional_str(payload, "model_type") or "yolov8"
    runtime_artifact_file_id = _read_payload_optional_str(payload, "runtime_artifact_file_id") or _require_payload_str(payload, "checkpoint_file_id")
    runtime_artifact_storage_uri = _read_payload_optional_str(payload, "runtime_artifact_storage_uri") or _require_payload_str(payload, "checkpoint_storage_uri")
    runtime_artifact_file_type = _read_payload_optional_str(payload, "runtime_artifact_file_type") or "pytorch-checkpoint"
    return SegmentationValidationSessionView(
        session_id=_require_payload_str(payload, "session_id"), project_id=_require_payload_str(payload, "project_id"),
        model_type=_normalize_model_type(mt), model_id=_require_payload_str(payload, "model_id"),
        model_version_id=_require_payload_str(payload, "model_version_id"), model_name=_require_payload_str(payload, "model_name"),
        model_scale=_require_payload_str(payload, "model_scale"), source_kind=_require_payload_str(payload, "source_kind"),
        status=_require_payload_str(payload, "status"), model_build_id=_read_payload_optional_str(payload, "model_build_id"), runtime_profile_id=_read_payload_optional_str(payload, "runtime_profile_id"),
        runtime_backend=rb, device_name=dn,
        runtime_precision=resolve_runtime_precision(runtime_precision=_read_payload_optional_str(payload, "runtime_precision"), runtime_backend=rb, device_name=dn),
        score_threshold=float(payload.get("score_threshold", _DEFAULT_SCORE_THRESHOLD)),
        mask_threshold=float(payload.get("mask_threshold", _DEFAULT_MASK_THRESHOLD)),
        save_result_image=bool(payload.get("save_result_image", True)),
        input_size=(int(raw_is[0]), int(raw_is[1])), labels=tuple(_read_str_list(payload.get("labels"))),
        runtime_artifact_file_id=runtime_artifact_file_id,
        runtime_artifact_storage_uri=runtime_artifact_storage_uri,
        runtime_artifact_file_type=runtime_artifact_file_type,
        checkpoint_file_id=_read_payload_optional_str(payload, "checkpoint_file_id"),
        checkpoint_storage_uri=_read_payload_optional_str(payload, "checkpoint_storage_uri"),
        extra_options=_normalize_extra_options(payload.get("extra_options")),
        created_at=_require_payload_str(payload, "created_at"), updated_at=_require_payload_str(payload, "updated_at"),
        created_by=_read_payload_optional_str(payload, "created_by"),
        last_prediction=_build_summary_from_payload(payload.get("last_prediction")),
    )


def _build_summary_from_payload(p: object) -> SegmentationValidationPredictionSummary | None:
    if not isinstance(p, dict):
        return None
    rc = p.get("instance_count", 0)
    ic = rc if isinstance(rc, int) else 0
    rl = p.get("latency_ms")
    lm = float(rl) if isinstance(rl, int | float) else None
    return SegmentationValidationPredictionSummary(
        prediction_id=_require_payload_str(p, "prediction_id"), created_at=_require_payload_str(p, "created_at"),
        input_uri=_read_payload_optional_str(p, "input_uri"), input_file_id=_read_payload_optional_str(p, "input_file_id"),
        instance_count=ic, preview_image_uri=_read_payload_optional_str(p, "preview_image_uri"),
        raw_result_uri=_read_payload_optional_str(p, "raw_result_uri"), latency_ms=lm,
    )


def _normalize_model_type(mt: str | None) -> str:
    return require_supported_platform_model_type(
        task_type=SEGMENTATION_TASK_TYPE,
        model_type=mt,
        unsupported_message="当前 segmentation validation session 不支持指定模型分类",
        supported_details_key="supported_model_types",
    )


def _normalize_runtime_backend(rb: str | None) -> str:
    n = normalize_runtime_target_backend(_normalize_optional_str(rb) or _VALIDATION_RUNTIME_BACKEND)
    if n not in _SUPPORTED_VALIDATION_RUNTIME_BACKENDS:
        raise InvalidRequestError("当前 segmentation validation session 不支持指定 runtime_backend", details={"runtime_backend": n, "supported_runtime_backends": sorted(_SUPPORTED_VALIDATION_RUNTIME_BACKENDS)})
    return n


def _normalize_device_name(device_name: str | None, *, runtime_backend: str) -> str:
    return normalize_runtime_target_device_name(_normalize_optional_str(device_name), runtime_backend=runtime_backend)


def _normalize_extra_options(e: object) -> dict[str, object]:
    if not isinstance(e, dict):
        return {}
    return {str(k): v for k, v in e.items()}


def _normalize_optional_str(v: object) -> str | None:
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def _resolve_probability(v: object, *, default: float) -> float:
    r = float(v) if isinstance(v, int | float) else default
    if r < 0 or r > 1:
        raise InvalidRequestError("probability 必须位于 0 到 1 之间")
    return r


def _require_non_empty_str(v: str | None, *, field_name: str) -> str:
    n = _normalize_optional_str(v)
    if n is not None:
        return n
    raise InvalidRequestError("validation session 缺少必要模型文件引用", details={"field": field_name})


def _require_payload_str(payload: dict[str, object], key: str) -> str:
    v = payload.get(key)
    if isinstance(v, str) and v.strip():
        return v.strip()
    raise ResourceNotFoundError("validation session 数据缺少必要字段", details={"field": key})


def _read_payload_optional_str(payload: dict[str, object], key: str) -> str | None:
    v = payload.get(key)
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def _read_str_list(v: object) -> list[str]:
    if not isinstance(v, list):
        return []
    return [item.strip() for item in v if isinstance(item, str) and item.strip()]


def _now_isoformat() -> str:
    return datetime.now(timezone.utc).isoformat()
