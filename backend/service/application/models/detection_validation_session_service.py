"""detection 人工验证 session 应用服务。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import PurePosixPath
from uuid import uuid4

from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.project_public_files import resolve_public_project_file_reference
from backend.service.application.runtime.detection_model_runtime import (
    DefaultDetectionModelRuntime,
)
from backend.service.application.runtime.detection_runtime_contracts import (
    DetectionPredictionRequest,
    DetectionRuntimeSessionInfo,
    DetectionRuntimeTensorSpec,
)
from backend.service.application.runtime.yolo11_runtime_target import (
    SqlAlchemyYolo11RuntimeTargetResolver,
)
from backend.service.application.runtime.yolo26_runtime_target import (
    SqlAlchemyYolo26RuntimeTargetResolver,
)
from backend.service.application.runtime.rfdetr_runtime_target import (
    SqlAlchemyRfdetrRuntimeTargetResolver,
)
from backend.service.application.runtime.yolov8_runtime_target import (
    SqlAlchemyYoloV8RuntimeTargetResolver,
)
from backend.service.application.runtime.yolox_runtime_target import (
    RuntimeTargetResolveRequest,
    RuntimeTargetSnapshot,
    SqlAlchemyYoloXRuntimeTargetResolver,
    normalize_device_name as normalize_runtime_target_device_name,
    normalize_runtime_backend as normalize_runtime_target_backend,
    resolve_local_file_path,
    resolve_runtime_precision,
)
from backend.service.domain.files.detection_model_file_types import (
    DetectionModelFileTypes,
    YOLO11_DETECTION_FILE_TYPES,
    YOLO26_DETECTION_FILE_TYPES,
    YOLOV8_DETECTION_FILE_TYPES,
    YOLOX_DETECTION_FILE_TYPES,
)
from backend.service.application.models.rfdetr_model_service import RFDETR_DETECTION_FILE_TYPES
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


_VALIDATION_SESSION_STATUS_READY = "ready"
_VALIDATION_RUNTIME_BACKEND = "pytorch"
_SUPPORTED_VALIDATION_RUNTIME_BACKENDS = frozenset({"pytorch", "onnxruntime", "openvino", "tensorrt"})
_DEFAULT_SCORE_THRESHOLD = 0.3
_DEFAULT_INPUT_SIZE = (640, 640)
_SUPPORTED_DETECTION_MODEL_TYPES = ("yolox", "yolov8", "yolo11", "yolo26", "rfdetr")


@dataclass(frozen=True)
class DetectionValidationSessionCreateRequest:
    """描述一次 detection validation session 创建请求。"""

    project_id: str
    model_type: str
    model_version_id: str
    runtime_profile_id: str | None = None
    runtime_backend: str | None = None
    device_name: str | None = None
    score_threshold: float | None = None
    save_result_image: bool = True
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectionValidationSessionPredictRequest:
    """描述一次 detection validation session 预测请求。"""

    input_uri: str | None = None
    input_file_id: str | None = None
    score_threshold: float | None = None
    save_result_image: bool | None = None
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectionValidationDetection:
    """描述单条人工验证 detection 结果。"""

    bbox_xyxy: tuple[float, float, float, float]
    score: float
    class_id: int
    class_name: str | None = None


@dataclass(frozen=True)
class DetectionValidationPredictionSummary:
    """描述 session 最近一次预测摘要。"""

    prediction_id: str
    created_at: str
    input_uri: str | None
    input_file_id: str | None
    detection_count: int
    preview_image_uri: str | None = None
    raw_result_uri: str | None = None
    latency_ms: float | None = None


@dataclass(frozen=True)
class DetectionValidationSessionView:
    """描述 detection validation session 当前视图。"""

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
    save_result_image: bool
    input_size: tuple[int, int]
    labels: tuple[str, ...]
    runtime_artifact_file_id: str
    runtime_artifact_storage_uri: str
    runtime_artifact_file_type: str
    checkpoint_file_id: str | None
    checkpoint_storage_uri: str | None
    labels_storage_uri: str | None
    extra_options: dict[str, object]
    created_at: str
    updated_at: str
    created_by: str | None = None
    last_prediction: DetectionValidationPredictionSummary | None = None


@dataclass(frozen=True)
class DetectionValidationPredictionView:
    """描述一次人工验证预测结果视图。"""

    prediction_id: str
    session_id: str
    created_at: str
    input_uri: str | None
    input_file_id: str | None
    score_threshold: float
    save_result_image: bool
    detections: tuple[DetectionValidationDetection, ...]
    preview_image_uri: str | None
    raw_result_uri: str
    latency_ms: float | None
    image_width: int
    image_height: int
    labels: tuple[str, ...]
    runtime_session_info: DetectionRuntimeSessionInfo


@dataclass(frozen=True)
class _DetectionValidationPredictionExecution:
    """描述底层推理执行产出的中间结果。"""

    detections: tuple[DetectionValidationDetection, ...]
    latency_ms: float | None
    image_width: int
    image_height: int
    preview_image_bytes: bytes | None
    runtime_session_info: DetectionRuntimeSessionInfo


class LocalDetectionValidationSessionService:
    """管理 detection 人工验证 session 的本地实现。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        detection_runtime: DefaultDetectionModelRuntime | None = None,
    ) -> None:
        """初始化 validation session 服务。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.detection_runtime = detection_runtime or DefaultDetectionModelRuntime()

    def create_session(
        self,
        request: DetectionValidationSessionCreateRequest,
        *,
        created_by: str | None,
    ) -> DetectionValidationSessionView:
        """创建一个新的 detection validation session。"""

        normalized_model_type = _normalize_model_type(request.model_type)
        normalized_runtime_backend = _normalize_runtime_backend(request.runtime_backend)
        runtime_target = _build_runtime_target_resolver(
            model_type=normalized_model_type,
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
        ).resolve_target(
            RuntimeTargetResolveRequest(
                project_id=request.project_id,
                model_version_id=request.model_version_id,
                runtime_profile_id=request.runtime_profile_id,
                runtime_backend=normalized_runtime_backend,
                device_name=_normalize_device_name(
                    request.device_name,
                    normalized_runtime_backend,
                    request.extra_options,
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

        score_threshold = _resolve_probability(
            value=request.score_threshold,
            field_name="score_threshold",
            default=_DEFAULT_SCORE_THRESHOLD,
        )
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
        session = DetectionValidationSessionView(
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
            save_result_image=bool(request.save_result_image),
            input_size=runtime_target.input_size,
            labels=runtime_target.labels,
            runtime_artifact_file_id=runtime_artifact_file_id,
            runtime_artifact_storage_uri=runtime_artifact_storage_uri,
            runtime_artifact_file_type=runtime_artifact_file_type,
            checkpoint_file_id=_normalize_optional_str(runtime_target.checkpoint_file_id),
            checkpoint_storage_uri=_normalize_optional_str(runtime_target.checkpoint_storage_uri),
            labels_storage_uri=runtime_target.labels_storage_uri,
            extra_options=_normalize_extra_options(request.extra_options),
            created_at=now,
            updated_at=now,
            created_by=_normalize_optional_str(created_by),
        )
        self._write_session(session)
        return session

    def get_session(self, session_id: str) -> DetectionValidationSessionView:
        """读取指定 detection validation session。"""

        session_path = self._session_path(session_id)
        if not self.dataset_storage.resolve(session_path).is_file():
            raise ResourceNotFoundError(
                "指定的 validation session 不存在",
                details={"session_id": session_id},
            )

        payload = self.dataset_storage.read_json(session_path)
        if not isinstance(payload, dict):
            raise ResourceNotFoundError(
                "指定的 validation session 数据损坏",
                details={"session_id": session_id},
            )
        return _build_session_from_payload(payload)

    def predict(
        self,
        session_id: str,
        request: DetectionValidationSessionPredictRequest,
    ) -> DetectionValidationPredictionView:
        """对指定 detection validation session 执行一次单图预测。"""

        session = self.get_session(session_id)
        input_uri = _normalize_optional_str(request.input_uri)
        input_file_id = _normalize_optional_str(request.input_file_id)
        if input_uri is not None and input_file_id is not None:
            raise InvalidRequestError(
                "input_uri 和 input_file_id 只能提供一个",
                details={
                    "session_id": session_id,
                    "input_uri": input_uri,
                    "input_file_id": input_file_id,
                },
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

        score_threshold = _resolve_probability(
            value=request.score_threshold,
            field_name="score_threshold",
            default=session.score_threshold,
        )
        save_result_image = session.save_result_image if request.save_result_image is None else bool(request.save_result_image)
        merged_extra_options = dict(session.extra_options)
        merged_extra_options.update(_normalize_extra_options(request.extra_options))

        execution = self._run_detection_validation_prediction(
            session=session,
            input_uri=input_uri,
            score_threshold=score_threshold,
            save_result_image=save_result_image,
            extra_options=merged_extra_options,
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
            "score_threshold": score_threshold,
            "save_result_image": save_result_image,
            "latency_ms": execution.latency_ms,
            "image_width": execution.image_width,
            "image_height": execution.image_height,
            "labels": list(session.labels),
            "detections": [_serialize_detection(detection) for detection in execution.detections],
            "runtime_session_info": _serialize_runtime_session_info(execution.runtime_session_info),
            "preview_image_uri": preview_image_uri,
        }
        self.dataset_storage.write_json(raw_result_uri, raw_result_payload)

        summary = DetectionValidationPredictionSummary(
            prediction_id=prediction_id,
            created_at=created_at,
            input_uri=input_uri,
            input_file_id=resolved_input_file_id,
            detection_count=len(execution.detections),
            preview_image_uri=preview_image_uri,
            raw_result_uri=raw_result_uri,
            latency_ms=execution.latency_ms,
        )
        self._write_session(replace(session, updated_at=created_at, last_prediction=summary))

        return DetectionValidationPredictionView(
            prediction_id=prediction_id,
            session_id=session.session_id,
            created_at=created_at,
            input_uri=input_uri,
            input_file_id=resolved_input_file_id,
            score_threshold=score_threshold,
            save_result_image=save_result_image,
            detections=execution.detections,
            preview_image_uri=preview_image_uri,
            raw_result_uri=raw_result_uri,
            latency_ms=execution.latency_ms,
            image_width=execution.image_width,
            image_height=execution.image_height,
            labels=session.labels,
            runtime_session_info=execution.runtime_session_info,
        )

    def _run_detection_validation_prediction(
        self,
        *,
        session: DetectionValidationSessionView,
        input_uri: str,
        score_threshold: float,
        save_result_image: bool,
        extra_options: dict[str, object],
    ) -> _DetectionValidationPredictionExecution:
        """执行一次最小 detection 单图预测。"""

        runtime_target = _build_runtime_target_from_session(
            session=session,
            dataset_storage=self.dataset_storage,
        )
        runtime_session = self.detection_runtime.load_session(
            dataset_storage=self.dataset_storage,
            runtime_target=runtime_target,
        )
        execution = runtime_session.predict(
            DetectionPredictionRequest(
                input_uri=input_uri,
                score_threshold=score_threshold,
                save_result_image=save_result_image,
                extra_options=dict(extra_options),
            )
        )
        return _DetectionValidationPredictionExecution(
            detections=tuple(
                DetectionValidationDetection(
                    bbox_xyxy=detection.bbox_xyxy,
                    score=detection.score,
                    class_id=detection.class_id,
                    class_name=detection.class_name,
                )
                for detection in execution.detections
            ),
            latency_ms=execution.latency_ms,
            image_width=execution.image_width,
            image_height=execution.image_height,
            preview_image_bytes=execution.preview_image_bytes,
            runtime_session_info=execution.runtime_session_info,
        )

    def _write_session(self, session: DetectionValidationSessionView) -> None:
        """把 session 当前视图写入本地文件。"""

        self.dataset_storage.write_json(self._session_path(session.session_id), _serialize_session(session))

    @staticmethod
    def _session_path(session_id: str) -> str:
        """返回 session JSON 的相对路径。"""

        return str(PurePosixPath("runtime") / "validation-sessions" / session_id / "session.json")

    @staticmethod
    def _prediction_output_dir(session_id: str, prediction_id: str) -> PurePosixPath:
        """返回某次预测输出目录的相对路径。"""

        return PurePosixPath("runtime") / "validation-sessions" / session_id / "predictions" / prediction_id


def _build_runtime_target_resolver(
    *,
    model_type: str,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> SqlAlchemyYoloXRuntimeTargetResolver:
    """按模型分类构造 runtime target resolver。"""

    resolver_factory_map = {
        "yolox": SqlAlchemyYoloXRuntimeTargetResolver,
        "yolov8": SqlAlchemyYoloV8RuntimeTargetResolver,
        "yolo11": SqlAlchemyYolo11RuntimeTargetResolver,
        "yolo26": SqlAlchemyYolo26RuntimeTargetResolver,
        "rfdetr": SqlAlchemyRfdetrRuntimeTargetResolver,
    }
    resolver_factory = resolver_factory_map.get(model_type)
    if resolver_factory is None:
        raise InvalidRequestError(
            "当前 detection validation session 不支持指定模型分类",
            details={
                "model_type": model_type,
                "supported_model_types": list(_SUPPORTED_DETECTION_MODEL_TYPES),
            },
        )
    return resolver_factory(session_factory=session_factory, dataset_storage=dataset_storage)


def _build_runtime_target_from_session(
    *,
    session: DetectionValidationSessionView,
    dataset_storage: LocalDatasetStorage,
) -> RuntimeTargetSnapshot:
    """把 validation session 视图转换为运行时快照。"""

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
        task_type=DETECTION_TASK_TYPE,
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
        labels_storage_uri=session.labels_storage_uri,
    )


def _resolve_detection_file_types(model_type: str) -> DetectionModelFileTypes:
    """按模型分类返回 detection 文件类型集合。"""

    file_types_map = {
        "yolox": YOLOX_DETECTION_FILE_TYPES,
        "yolov8": YOLOV8_DETECTION_FILE_TYPES,
        "yolo11": YOLO11_DETECTION_FILE_TYPES,
        "yolo26": YOLO26_DETECTION_FILE_TYPES,
        "rfdetr": RFDETR_DETECTION_FILE_TYPES,
    }
    file_types = file_types_map.get(model_type)
    if file_types is None:
        raise InvalidRequestError(
            "当前 detection validation session 不支持指定模型分类",
            details={
                "model_type": model_type,
                "supported_model_types": list(_SUPPORTED_DETECTION_MODEL_TYPES),
            },
        )
    return file_types


def _serialize_session(session: DetectionValidationSessionView) -> dict[str, object]:
    """把 session 视图转换为可落盘 JSON 的字典。"""

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
        "score_threshold": session.score_threshold,
        "save_result_image": session.save_result_image,
        "input_size": [session.input_size[0], session.input_size[1]],
        "labels": list(session.labels),
        "runtime_artifact_file_id": session.runtime_artifact_file_id,
        "runtime_artifact_storage_uri": session.runtime_artifact_storage_uri,
        "runtime_artifact_file_type": session.runtime_artifact_file_type,
        "checkpoint_file_id": session.checkpoint_file_id,
        "checkpoint_storage_uri": session.checkpoint_storage_uri,
        "labels_storage_uri": session.labels_storage_uri,
        "extra_options": dict(session.extra_options),
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "created_by": session.created_by,
        "last_prediction": _serialize_prediction_summary(session.last_prediction),
    }


def _build_session_from_payload(payload: dict[str, object]) -> DetectionValidationSessionView:
    """从 session JSON 载荷恢复 session 视图。"""

    raw_input_size = payload.get("input_size")
    if (
        not isinstance(raw_input_size, list)
        or len(raw_input_size) != 2
        or not all(isinstance(item, int) for item in raw_input_size)
    ):
        raise ResourceNotFoundError("validation session 的 input_size 无效")

    runtime_backend = _require_payload_str(payload, "runtime_backend")
    device_name = _require_payload_str(payload, "device_name")
    model_type = _read_payload_optional_str(payload, "model_type") or "yolox"
    checkpoint_file_id = _read_payload_optional_str(payload, "checkpoint_file_id")
    checkpoint_storage_uri = _read_payload_optional_str(payload, "checkpoint_storage_uri")
    runtime_artifact_file_id = _read_payload_optional_str(payload, "runtime_artifact_file_id") or checkpoint_file_id
    runtime_artifact_storage_uri = _read_payload_optional_str(payload, "runtime_artifact_storage_uri") or checkpoint_storage_uri
    if runtime_artifact_file_id is None or runtime_artifact_storage_uri is None:
        raise ResourceNotFoundError("validation session 数据缺少必要字段", details={"field": "runtime_artifact"})
    runtime_artifact_file_type = (
        _read_payload_optional_str(payload, "runtime_artifact_file_type")
        or _resolve_detection_file_types(model_type).checkpoint_file_type
    )

    return DetectionValidationSessionView(
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
        score_threshold=float(payload.get("score_threshold", _DEFAULT_SCORE_THRESHOLD)),
        save_result_image=bool(payload.get("save_result_image", True)),
        input_size=(int(raw_input_size[0]), int(raw_input_size[1])),
        labels=tuple(_read_str_list(payload.get("labels"))),
        runtime_artifact_file_id=runtime_artifact_file_id,
        runtime_artifact_storage_uri=runtime_artifact_storage_uri,
        runtime_artifact_file_type=runtime_artifact_file_type,
        checkpoint_file_id=checkpoint_file_id,
        checkpoint_storage_uri=checkpoint_storage_uri,
        labels_storage_uri=_read_payload_optional_str(payload, "labels_storage_uri"),
        extra_options=_normalize_extra_options(payload.get("extra_options")),
        created_at=_require_payload_str(payload, "created_at"),
        updated_at=_require_payload_str(payload, "updated_at"),
        created_by=_read_payload_optional_str(payload, "created_by"),
        last_prediction=_build_prediction_summary_from_payload(payload.get("last_prediction")),
    )


def _serialize_prediction_summary(
    summary: DetectionValidationPredictionSummary | None,
) -> dict[str, object] | None:
    """把预测摘要转换为可序列化字典。"""

    if summary is None:
        return None
    return {
        "prediction_id": summary.prediction_id,
        "created_at": summary.created_at,
        "input_uri": summary.input_uri,
        "input_file_id": summary.input_file_id,
        "detection_count": summary.detection_count,
        "preview_image_uri": summary.preview_image_uri,
        "raw_result_uri": summary.raw_result_uri,
        "latency_ms": summary.latency_ms,
    }


def _build_prediction_summary_from_payload(payload: object) -> DetectionValidationPredictionSummary | None:
    """从 JSON 载荷恢复预测摘要。"""

    if not isinstance(payload, dict):
        return None
    raw_detection_count = payload.get("detection_count", 0)
    detection_count = raw_detection_count if isinstance(raw_detection_count, int) else 0
    raw_latency_ms = payload.get("latency_ms")
    latency_ms = float(raw_latency_ms) if isinstance(raw_latency_ms, int | float) else None
    return DetectionValidationPredictionSummary(
        prediction_id=_require_payload_str(payload, "prediction_id"),
        created_at=_require_payload_str(payload, "created_at"),
        input_uri=_read_payload_optional_str(payload, "input_uri"),
        input_file_id=_read_payload_optional_str(payload, "input_file_id"),
        detection_count=detection_count,
        preview_image_uri=_read_payload_optional_str(payload, "preview_image_uri"),
        raw_result_uri=_read_payload_optional_str(payload, "raw_result_uri"),
        latency_ms=latency_ms,
    )


def _serialize_detection(detection: DetectionValidationDetection) -> dict[str, object]:
    """把 detection 记录转换为 JSON 字典。"""

    return {
        "bbox_xyxy": list(detection.bbox_xyxy),
        "score": detection.score,
        "class_id": detection.class_id,
        "class_name": detection.class_name,
    }


def _serialize_runtime_tensor_spec(spec: DetectionRuntimeTensorSpec) -> dict[str, object]:
    """把 runtime 张量规格转换为 JSON 字典。"""

    return {
        "name": spec.name,
        "shape": list(spec.shape),
        "dtype": spec.dtype,
    }


def _serialize_runtime_session_info(session_info: DetectionRuntimeSessionInfo) -> dict[str, object]:
    """把 runtime session info 转换为 JSON 字典。"""

    return {
        "backend_name": session_info.backend_name,
        "model_uri": session_info.model_uri,
        "device_name": session_info.device_name,
        "input_spec": _serialize_runtime_tensor_spec(session_info.input_spec),
        "output_spec": _serialize_runtime_tensor_spec(session_info.output_spec),
        "metadata": dict(session_info.metadata),
    }


def _normalize_model_type(model_type: str | None) -> str:
    """归一化 detection 模型分类。"""

    normalized_model_type = _normalize_optional_str(model_type)
    if normalized_model_type is None:
        raise InvalidRequestError("model_type 不能为空")
    normalized_model_type = normalized_model_type.lower()
    if normalized_model_type not in _SUPPORTED_DETECTION_MODEL_TYPES:
        raise InvalidRequestError(
            "当前 detection validation session 不支持指定模型分类",
            details={
                "model_type": normalized_model_type,
                "supported_model_types": list(_SUPPORTED_DETECTION_MODEL_TYPES),
            },
        )
    return normalized_model_type


def _normalize_runtime_backend(runtime_backend: str | None) -> str:
    """归一化 detection validation session 的 runtime backend。"""

    normalized_backend = normalize_runtime_target_backend(
        _normalize_optional_str(runtime_backend) or _VALIDATION_RUNTIME_BACKEND
    )
    if normalized_backend not in _SUPPORTED_VALIDATION_RUNTIME_BACKENDS:
        raise InvalidRequestError(
            "当前 detection validation session 不支持指定 runtime_backend",
            details={
                "runtime_backend": normalized_backend,
                "supported_runtime_backends": sorted(_SUPPORTED_VALIDATION_RUNTIME_BACKENDS),
            },
        )
    return normalized_backend


def _normalize_device_name(
    device_name: str | None,
    runtime_backend: str,
    extra_options: dict[str, object],
) -> str:
    """归一化 validation session 默认 device 名称。"""

    if isinstance(extra_options.get("device"), str) and str(extra_options["device"]).strip():
        requested = str(extra_options["device"]).strip()
    else:
        requested = _normalize_optional_str(device_name)
    return normalize_runtime_target_device_name(requested, runtime_backend=runtime_backend)


def _normalize_extra_options(extra_options: object) -> dict[str, object]:
    """把 extra_options 归一成普通字典。"""

    if not isinstance(extra_options, dict):
        return {}
    return {str(key): value for key, value in extra_options.items()}


def _normalize_optional_str(value: object) -> str | None:
    """把可选字符串去空白后返回。"""

    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _resolve_probability(*, value: object, field_name: str, default: float) -> float:
    """解析并校验概率型浮点值。"""

    resolved_value = float(value) if isinstance(value, int | float) else default
    if resolved_value < 0 or resolved_value > 1:
        raise InvalidRequestError(
            f"{field_name} 必须位于 0 到 1 之间",
            details={field_name: resolved_value},
        )
    return resolved_value


def _require_non_empty_str(value: str | None, *, field_name: str) -> str:
    """要求给定值是非空字符串。"""

    normalized_value = _normalize_optional_str(value)
    if normalized_value is not None:
        return normalized_value
    raise InvalidRequestError(
        "validation session 缺少必要模型文件引用",
        details={"field": field_name},
    )


def _require_payload_str(payload: dict[str, object], key: str) -> str:
    """从 JSON 载荷中读取必填字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ResourceNotFoundError(
        "validation session 数据缺少必要字段",
        details={"field": key},
    )


def _read_payload_optional_str(payload: dict[str, object], key: str) -> str | None:
    """从 JSON 载荷中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _read_str_list(value: object) -> list[str]:
    """把 JSON 载荷中的字符串列表归一成 list[str]。"""

    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _now_isoformat() -> str:
    """返回带时区的当前 UTC ISO 时间字符串。"""

    return datetime.now(timezone.utc).isoformat()
