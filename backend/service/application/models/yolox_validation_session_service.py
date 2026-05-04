"""YOLOX 人工验证 session 应用服务。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath
from uuid import uuid4

from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.runtime.yolox_predictor import (
    PyTorchYoloXPredictor,
    YoloXPredictionRequest,
)
from backend.service.application.runtime.yolox_runtime_target import (
    RuntimeTargetResolveRequest,
    RuntimeTargetSnapshot,
    SqlAlchemyYoloXRuntimeTargetResolver,
    resolve_local_file_path,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.shared.yolox_runtime_contracts import YoloXRuntimeSessionInfo


_VALIDATION_SESSION_STATUS_READY = "ready"
_VALIDATION_RUNTIME_BACKEND = "pytorch"
_DEFAULT_SCORE_THRESHOLD = 0.3
_DEFAULT_NMS_THRESHOLD = 0.65
_DEFAULT_INPUT_SIZE = (640, 640)


@dataclass(frozen=True)
class YoloXValidationSessionCreateRequest:
    """描述一次 validation session 创建请求。

    字段：
    - project_id：所属 Project id。
    - model_version_id：验证使用的 ModelVersion id。
    - runtime_profile_id：可选 runtime profile id；当前仅回传，不参与实际加载。
    - runtime_backend：可选 runtime backend；当前仅支持 pytorch。
    - device_name：可选 device 名称；当前支持 cpu 或 cuda:<index>。
    - score_threshold：默认预测阈值。
    - save_result_image：默认是否输出预览图。
    - extra_options：附加运行时选项。
    """

    project_id: str
    model_version_id: str
    runtime_profile_id: str | None = None
    runtime_backend: str | None = None
    device_name: str | None = None
    score_threshold: float | None = None
    save_result_image: bool = True
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXValidationSessionPredictRequest:
    """描述一次 validation session 预测请求。

    字段：
    - input_uri：输入图片 URI 或本地 object key。
    - input_file_id：保留字段；当前最小实现暂不支持。
    - score_threshold：本次预测覆盖的阈值。
    - save_result_image：本次预测是否输出预览图。
    - extra_options：附加运行时选项。
    """

    input_uri: str | None = None
    input_file_id: str | None = None
    score_threshold: float | None = None
    save_result_image: bool | None = None
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXValidationDetection:
    """描述单条人工验证 detection 结果。"""

    bbox_xyxy: tuple[float, float, float, float]
    score: float
    class_id: int
    class_name: str | None = None


@dataclass(frozen=True)
class YoloXValidationPredictionSummary:
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
class YoloXValidationSessionView:
    """描述 validation session 当前视图。"""

    session_id: str
    project_id: str
    model_id: str
    model_version_id: str
    model_name: str
    model_scale: str
    source_kind: str
    status: str
    runtime_profile_id: str | None
    runtime_backend: str
    device_name: str
    score_threshold: float
    save_result_image: bool
    input_size: tuple[int, int]
    labels: tuple[str, ...]
    checkpoint_file_id: str
    checkpoint_storage_uri: str
    labels_storage_uri: str | None
    extra_options: dict[str, object]
    created_at: str
    updated_at: str
    created_by: str | None = None
    last_prediction: YoloXValidationPredictionSummary | None = None


@dataclass(frozen=True)
class YoloXValidationPredictionView:
    """描述一次人工验证预测结果视图。"""

    prediction_id: str
    session_id: str
    created_at: str
    input_uri: str | None
    input_file_id: str | None
    score_threshold: float
    save_result_image: bool
    detections: tuple[YoloXValidationDetection, ...]
    preview_image_uri: str | None
    raw_result_uri: str
    latency_ms: float | None
    image_width: int
    image_height: int
    labels: tuple[str, ...]
    runtime_session_info: YoloXRuntimeSessionInfo


@dataclass(frozen=True)
class _YoloXValidationPredictionExecution:
    """描述底层推理执行产出的中间结果。"""

    detections: tuple[YoloXValidationDetection, ...]
    latency_ms: float | None
    image_width: int
    image_height: int
    preview_image_bytes: bytes | None
    runtime_session_info: YoloXRuntimeSessionInfo


class LocalYoloXValidationSessionService:
    """管理 YOLOX 人工验证 session 的本地实现。"""

    def __init__(self, *, session_factory: SessionFactory, dataset_storage: LocalDatasetStorage) -> None:
        """初始化 validation session 服务。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：本地文件存储服务。
        """

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage

    def create_session(
        self,
        request: YoloXValidationSessionCreateRequest,
        *,
        created_by: str | None,
    ) -> YoloXValidationSessionView:
        """创建一个新的 validation session。"""

        runtime_target = SqlAlchemyYoloXRuntimeTargetResolver(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
        ).resolve_target(
            RuntimeTargetResolveRequest(
                project_id=request.project_id,
                model_version_id=request.model_version_id,
                runtime_profile_id=request.runtime_profile_id,
                runtime_backend=_normalize_runtime_backend(request.runtime_backend),
                device_name=_normalize_device_name(request.device_name, request.extra_options),
            )
        )
        score_threshold = _resolve_probability(
            value=request.score_threshold,
            field_name="score_threshold",
            default=_DEFAULT_SCORE_THRESHOLD,
        )
        session_id = f"validation-session-{uuid4().hex}"
        now = _now_isoformat()
        session = YoloXValidationSessionView(
            session_id=session_id,
            project_id=request.project_id,
            model_id=runtime_target.model_id,
            model_version_id=runtime_target.model_version_id,
            model_name=runtime_target.model_name,
            model_scale=runtime_target.model_scale,
            source_kind=runtime_target.source_kind,
            status=_VALIDATION_SESSION_STATUS_READY,
            runtime_profile_id=runtime_target.runtime_profile_id,
            runtime_backend=runtime_target.runtime_backend,
            device_name=runtime_target.device_name,
            score_threshold=score_threshold,
            save_result_image=bool(request.save_result_image),
            input_size=runtime_target.input_size,
            labels=runtime_target.labels,
            checkpoint_file_id=runtime_target.checkpoint_file_id,
            checkpoint_storage_uri=runtime_target.checkpoint_storage_uri,
            labels_storage_uri=runtime_target.labels_storage_uri,
            extra_options=_normalize_extra_options(request.extra_options),
            created_at=now,
            updated_at=now,
            created_by=_normalize_optional_str(created_by),
        )
        self._write_session(session)
        return session

    def get_session(self, session_id: str) -> YoloXValidationSessionView:
        """读取指定 validation session。"""

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
        request: YoloXValidationSessionPredictRequest,
    ) -> YoloXValidationPredictionView:
        """对指定 validation session 执行一次单图预测。"""

        session = self.get_session(session_id)
        if request.input_file_id is not None:
            raise InvalidRequestError(
                "当前 validation session 暂不支持 input_file_id，请改用 input_uri",
                details={"session_id": session_id, "input_file_id": request.input_file_id},
            )
        input_uri = _normalize_optional_str(request.input_uri)
        if input_uri is None:
            raise InvalidRequestError("predict 请求必须提供 input_uri")

        score_threshold = _resolve_probability(
            value=request.score_threshold,
            field_name="score_threshold",
            default=session.score_threshold,
        )
        save_result_image = session.save_result_image if request.save_result_image is None else bool(request.save_result_image)
        merged_extra_options = dict(session.extra_options)
        merged_extra_options.update(_normalize_extra_options(request.extra_options))

        execution = _run_yolox_validation_prediction(
            dataset_storage=self.dataset_storage,
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
            "input_file_id": None,
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

        summary = YoloXValidationPredictionSummary(
            prediction_id=prediction_id,
            created_at=created_at,
            input_uri=input_uri,
            input_file_id=None,
            detection_count=len(execution.detections),
            preview_image_uri=preview_image_uri,
            raw_result_uri=raw_result_uri,
            latency_ms=execution.latency_ms,
        )
        self._write_session(
            replace(
                session,
                updated_at=created_at,
                last_prediction=summary,
            )
        )

        return YoloXValidationPredictionView(
            prediction_id=prediction_id,
            session_id=session.session_id,
            created_at=created_at,
            input_uri=input_uri,
            input_file_id=None,
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

    def _write_session(self, session: YoloXValidationSessionView) -> None:
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


def _run_yolox_validation_prediction(
    *,
    dataset_storage: LocalDatasetStorage,
    session: YoloXValidationSessionView,
    input_uri: str,
    score_threshold: float,
    save_result_image: bool,
    extra_options: dict[str, object],
) -> _YoloXValidationPredictionExecution:
    """执行一次最小 YOLOX PyTorch 单图预测。"""

    execution = PyTorchYoloXPredictor(dataset_storage=dataset_storage).predict(
        runtime_target=_build_runtime_target_from_session(
            session=session,
            dataset_storage=dataset_storage,
        ),
        request=YoloXPredictionRequest(
            input_uri=input_uri,
            score_threshold=score_threshold,
            save_result_image=save_result_image,
            extra_options=dict(extra_options),
        ),
    )
    return _YoloXValidationPredictionExecution(
        detections=tuple(
            YoloXValidationDetection(
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


def _build_runtime_target_from_session(
    *,
    session: YoloXValidationSessionView,
    dataset_storage: LocalDatasetStorage,
) -> RuntimeTargetSnapshot:
    """把 validation session 视图转换为运行时快照。"""

    return RuntimeTargetSnapshot(
        project_id=session.project_id,
        model_id=session.model_id,
        model_version_id=session.model_version_id,
        model_build_id=None,
        model_name=session.model_name,
        model_scale=session.model_scale,
        task_type="object-detection",
        source_kind=session.source_kind,
        runtime_profile_id=session.runtime_profile_id,
        runtime_backend=session.runtime_backend,
        device_name=session.device_name,
        input_size=session.input_size,
        labels=session.labels,
        runtime_artifact_file_id=session.checkpoint_file_id,
        runtime_artifact_storage_uri=session.checkpoint_storage_uri,
        runtime_artifact_path=resolve_local_file_path(
            dataset_storage=dataset_storage,
            storage_uri=session.checkpoint_storage_uri,
            field_name="checkpoint_storage_uri",
        ),
        runtime_artifact_file_type="yolox-checkpoint",
        checkpoint_file_id=session.checkpoint_file_id,
        checkpoint_storage_uri=session.checkpoint_storage_uri,
        checkpoint_path=resolve_local_file_path(
            dataset_storage=dataset_storage,
            storage_uri=session.checkpoint_storage_uri,
            field_name="checkpoint_storage_uri",
        ),
        labels_storage_uri=session.labels_storage_uri,
    )


def _build_detection_records(
    *,
    np_module: Any,
    predictions: Any,
    resize_ratio: float,
    labels: tuple[str, ...],
    image_width: int,
    image_height: int,
) -> tuple[YoloXValidationDetection, ...]:
    """把 YOLOX postprocess 输出归一成 detection 记录。"""

    if not isinstance(predictions, list) or not predictions:
        return ()
    prediction_tensor = predictions[0]
    if prediction_tensor is None:
        return ()

    prediction_array = prediction_tensor.detach().cpu().numpy()
    detections: list[YoloXValidationDetection] = []
    for prediction in prediction_array:
        if len(prediction) < 7:
            continue
        bbox = prediction[:4] / max(resize_ratio, 1e-8)
        x1 = float(max(0.0, min(float(bbox[0]), float(image_width))))
        y1 = float(max(0.0, min(float(bbox[1]), float(image_height))))
        x2 = float(max(0.0, min(float(bbox[2]), float(image_width))))
        y2 = float(max(0.0, min(float(bbox[3]), float(image_height))))
        class_id = int(prediction[6])
        class_name = labels[class_id] if 0 <= class_id < len(labels) else None
        score = float(prediction[4] * prediction[5])
        detections.append(
            YoloXValidationDetection(
                bbox_xyxy=(round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)),
                score=round(score, 6),
                class_id=class_id,
                class_name=class_name,
            )
        )

    detections.sort(key=lambda item: item.score, reverse=True)
    return tuple(detections)


def _preprocess_image(
    *,
    cv2_module: Any,
    np_module: Any,
    image: Any,
    input_size: tuple[int, int],
) -> tuple[Any, float]:
    """按 YOLOX 预处理规则构造输入张量。"""

    target_height, target_width = input_size
    source_height, source_width = int(image.shape[0]), int(image.shape[1])
    resize_ratio = min(target_height / source_height, target_width / source_width)
    resized_width = max(1, int(round(source_width * resize_ratio)))
    resized_height = max(1, int(round(source_height * resize_ratio)))
    resized_image = cv2_module.resize(image, (resized_width, resized_height), interpolation=cv2_module.INTER_LINEAR)
    padded_image = np_module.full((target_height, target_width, 3), 114, dtype=np_module.uint8)
    padded_image[:resized_height, :resized_width] = resized_image
    tensor = padded_image[:, :, ::-1].transpose(2, 0, 1)
    return np_module.ascontiguousarray(tensor, dtype=np_module.float32), float(resize_ratio)


def _render_preview_image(
    *,
    cv2_module: Any,
    image: Any,
    detections: tuple[YoloXValidationDetection, ...],
) -> bytes:
    """把 detection 结果叠加到原图并编码为 JPEG。"""

    preview = image.copy()
    for detection in detections:
        x1, y1, x2, y2 = (int(round(value)) for value in detection.bbox_xyxy)
        color = _select_detection_color(detection.class_id)
        cv2_module.rectangle(preview, (x1, y1), (x2, y2), color, 2)
        label_text = (
            f"{detection.class_name}:{detection.score:.2f}"
            if detection.class_name is not None
            else f"{detection.class_id}:{detection.score:.2f}"
        )
        text_origin_y = y1 - 6 if y1 > 18 else y1 + 18
        cv2_module.putText(
            preview,
            label_text,
            (x1, text_origin_y),
            cv2_module.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
            cv2_module.LINE_AA,
        )

    success, encoded = cv2_module.imencode(".jpg", preview)
    if success is not True:
        raise InvalidRequestError("预测预览图编码失败")
    return bytes(encoded.tobytes())


def _select_detection_color(class_id: int) -> tuple[int, int, int]:
    """根据类别 id 返回稳定的框颜色。"""

    palette = (
        (40, 110, 240),
        (40, 180, 120),
        (240, 170, 40),
        (210, 80, 80),
    )
    return palette[class_id % len(palette)]


def _resolve_execution_device_name(*, torch_module: Any, requested_device_name: str) -> str:
    """校验并返回本次预测实际使用的 device。"""

    if requested_device_name == "cpu":
        return "cpu"
    if requested_device_name == "cuda":
        requested_device_name = "cuda:0"
    if requested_device_name.startswith("cuda:"):
        if not torch_module.cuda.is_available():
            raise InvalidRequestError(
                "当前运行环境没有可用 GPU，不能使用 CUDA validation session",
                details={"device_name": requested_device_name},
            )
        raw_index = requested_device_name.split(":", 1)[1]
        if not raw_index.isdigit():
            raise InvalidRequestError(
                "device_name 必须是 cpu、cuda 或 cuda:<index>",
                details={"device_name": requested_device_name},
            )
        device_index = int(raw_index)
        available_count = int(torch_module.cuda.device_count())
        if device_index >= available_count:
            raise InvalidRequestError(
                "指定的 CUDA device 超出了本机可用 GPU 范围",
                details={
                    "device_name": requested_device_name,
                    "available_gpu_count": available_count,
                },
            )
        return requested_device_name
    raise InvalidRequestError(
        "device_name 必须是 cpu、cuda 或 cuda:<index>",
        details={"device_name": requested_device_name},
    )


def _resolve_labels(
    *,
    dataset_storage: LocalDatasetStorage,
    model_version: ModelVersion,
    labels_file: ModelFile | None,
) -> tuple[str, ...]:
    """优先从 labels 文件，其次从 metadata 中解析类别名。"""

    if labels_file is not None:
        labels_path = _resolve_local_file_path(
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

    metadata_labels = model_version.metadata.get("category_names")
    if isinstance(metadata_labels, list):
        labels = tuple(item.strip() for item in metadata_labels if isinstance(item, str) and item.strip())
        if labels:
            return labels

    raise InvalidRequestError(
        "当前 ModelVersion 缺少可用 labels 信息，无法创建 validation session",
        details={"model_version_id": model_version.model_version_id},
    )


def _resolve_input_size(model_version: ModelVersion) -> tuple[int, int]:
    """从 ModelVersion metadata 中解析验证输入尺寸。"""

    for candidate in (
        model_version.metadata.get("input_size"),
        _read_nested_value(model_version.metadata, "training_config", "input_size"),
    ):
        if isinstance(candidate, list) and len(candidate) == 2 and all(isinstance(item, int) for item in candidate):
            resolved = (int(candidate[0]), int(candidate[1]))
            if resolved[0] > 0 and resolved[1] > 0:
                return resolved
    return _DEFAULT_INPUT_SIZE


def _require_model_file(
    *,
    model_files: list[ModelFile],
    file_type: str,
    model_version_id: str,
) -> ModelFile:
    """查找指定类型的 ModelFile；不存在时抛错。"""

    model_file = _find_model_file(model_files=model_files, file_type=file_type)
    if model_file is None:
        raise InvalidRequestError(
            "当前 ModelVersion 缺少 validation 所需文件",
            details={"model_version_id": model_version_id, "file_type": file_type},
        )
    return model_file


def _find_model_file(*, model_files: list[ModelFile], file_type: str) -> ModelFile | None:
    """返回首个匹配 file_type 的 ModelFile。"""

    for model_file in model_files:
        if model_file.file_type == file_type:
            return model_file
    return None


def _resolve_local_file_path(
    *,
    dataset_storage: LocalDatasetStorage,
    storage_uri: str,
    field_name: str,
) -> Path:
    """把 object key、本地绝对路径或 file URI 解析为本地绝对路径。"""

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


def _serialize_session(session: YoloXValidationSessionView) -> dict[str, object]:
    """把 session 视图转换为可落盘 JSON 的字典。"""

    return {
        "session_id": session.session_id,
        "project_id": session.project_id,
        "model_id": session.model_id,
        "model_version_id": session.model_version_id,
        "model_name": session.model_name,
        "model_scale": session.model_scale,
        "source_kind": session.source_kind,
        "status": session.status,
        "runtime_profile_id": session.runtime_profile_id,
        "runtime_backend": session.runtime_backend,
        "device_name": session.device_name,
        "score_threshold": session.score_threshold,
        "save_result_image": session.save_result_image,
        "input_size": [session.input_size[0], session.input_size[1]],
        "labels": list(session.labels),
        "checkpoint_file_id": session.checkpoint_file_id,
        "checkpoint_storage_uri": session.checkpoint_storage_uri,
        "labels_storage_uri": session.labels_storage_uri,
        "extra_options": dict(session.extra_options),
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "created_by": session.created_by,
        "last_prediction": _serialize_prediction_summary(session.last_prediction),
    }


def _build_session_from_payload(payload: dict[str, object]) -> YoloXValidationSessionView:
    """从 session JSON 载荷恢复 session 视图。"""

    raw_input_size = payload.get("input_size")
    if (
        not isinstance(raw_input_size, list)
        or len(raw_input_size) != 2
        or not all(isinstance(item, int) for item in raw_input_size)
    ):
        raise ResourceNotFoundError("validation session 的 input_size 无效")

    return YoloXValidationSessionView(
        session_id=_require_payload_str(payload, "session_id"),
        project_id=_require_payload_str(payload, "project_id"),
        model_id=_require_payload_str(payload, "model_id"),
        model_version_id=_require_payload_str(payload, "model_version_id"),
        model_name=_require_payload_str(payload, "model_name"),
        model_scale=_require_payload_str(payload, "model_scale"),
        source_kind=_require_payload_str(payload, "source_kind"),
        status=_require_payload_str(payload, "status"),
        runtime_profile_id=_read_payload_optional_str(payload, "runtime_profile_id"),
        runtime_backend=_require_payload_str(payload, "runtime_backend"),
        device_name=_require_payload_str(payload, "device_name"),
        score_threshold=float(payload.get("score_threshold", _DEFAULT_SCORE_THRESHOLD)),
        save_result_image=bool(payload.get("save_result_image", True)),
        input_size=(int(raw_input_size[0]), int(raw_input_size[1])),
        labels=tuple(_read_str_list(payload.get("labels"))),
        checkpoint_file_id=_require_payload_str(payload, "checkpoint_file_id"),
        checkpoint_storage_uri=_require_payload_str(payload, "checkpoint_storage_uri"),
        labels_storage_uri=_read_payload_optional_str(payload, "labels_storage_uri"),
        extra_options=_normalize_extra_options(payload.get("extra_options")),
        created_at=_require_payload_str(payload, "created_at"),
        updated_at=_require_payload_str(payload, "updated_at"),
        created_by=_read_payload_optional_str(payload, "created_by"),
        last_prediction=_build_prediction_summary_from_payload(payload.get("last_prediction")),
    )


def _serialize_prediction_summary(
    summary: YoloXValidationPredictionSummary | None,
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


def _build_prediction_summary_from_payload(
    payload: object,
) -> YoloXValidationPredictionSummary | None:
    """从 JSON 载荷恢复预测摘要。"""

    if not isinstance(payload, dict):
        return None
    raw_detection_count = payload.get("detection_count", 0)
    detection_count = raw_detection_count if isinstance(raw_detection_count, int) else 0
    raw_latency_ms = payload.get("latency_ms")
    latency_ms = float(raw_latency_ms) if isinstance(raw_latency_ms, int | float) else None
    return YoloXValidationPredictionSummary(
        prediction_id=_require_payload_str(payload, "prediction_id"),
        created_at=_require_payload_str(payload, "created_at"),
        input_uri=_read_payload_optional_str(payload, "input_uri"),
        input_file_id=_read_payload_optional_str(payload, "input_file_id"),
        detection_count=detection_count,
        preview_image_uri=_read_payload_optional_str(payload, "preview_image_uri"),
        raw_result_uri=_read_payload_optional_str(payload, "raw_result_uri"),
        latency_ms=latency_ms,
    )


def _serialize_detection(detection: YoloXValidationDetection) -> dict[str, object]:
    """把 detection 记录转换为 JSON 字典。"""

    return {
        "bbox_xyxy": list(detection.bbox_xyxy),
        "score": detection.score,
        "class_id": detection.class_id,
        "class_name": detection.class_name,
    }


def _serialize_runtime_session_info(session_info: YoloXRuntimeSessionInfo) -> dict[str, object]:
    """把 runtime session info 转换为 JSON 字典。"""

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


def _normalize_runtime_backend(runtime_backend: str | None) -> str:
    """归一化 runtime backend；当前仅支持 pytorch。"""

    normalized_backend = _normalize_optional_str(runtime_backend) or _VALIDATION_RUNTIME_BACKEND
    if normalized_backend != _VALIDATION_RUNTIME_BACKEND:
        raise InvalidRequestError(
            "当前 validation session 仅支持 pytorch runtime_backend",
            details={"runtime_backend": normalized_backend},
        )
    return normalized_backend


def _normalize_device_name(device_name: str | None, extra_options: dict[str, object]) -> str:
    """归一化 validation session 默认 device 名称。"""

    if isinstance(extra_options.get("device"), str) and str(extra_options["device"]).strip():
        requested = str(extra_options["device"]).strip()
    else:
        requested = _normalize_optional_str(device_name) or "cpu"
    if requested == "cuda":
        return "cuda:0"
    return requested


def _normalize_extra_options(extra_options: object) -> dict[str, object]:
    """把 extra_options 归一成普通字典。"""

    if not isinstance(extra_options, dict):
        return {}
    return {str(key): value for key, value in extra_options.items()}


def _normalize_optional_str(value: str | None) -> str | None:
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


def _read_nested_value(payload: dict[str, object], parent_key: str, child_key: str) -> object:
    """从嵌套字典中读取某个可选字段。"""

    parent_value = payload.get(parent_key)
    if isinstance(parent_value, dict):
        return parent_value.get(child_key)
    return None


def _now_isoformat() -> str:
    """返回带时区的当前 UTC ISO 时间字符串。"""

    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()