"""YOLOv8 detection 单图推理实现。"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolox_detection_training import (
    _require_training_imports,
)
from backend.service.application.models.yolov8_detection_model import (
    build_yolov8_detection_model,
    load_yolov8_checkpoint,
)
from backend.service.application.runtime.yolox_predictor import (
    YoloXPredictionDetection,
    YoloXPredictionExecutionResult,
    YoloXPredictionRequest,
    _DEFAULT_NMS_THRESHOLD,
    _batched_nms_indices,
    _enable_pytorch_cuda_inference_fast_path,
    _import_onnxruntime_module,
    _load_prediction_image,
    _measure_stage_elapsed_ms,
    _normalize_onnxruntime_outputs,
    _prediction_to_numpy_array,
    _preprocess_image,
    _render_preview_image,
    _require_inference_imports,
    _resolve_execution_device_name,
    _resolve_onnxruntime_providers,
    _resolve_probability,
)
from backend.service.application.runtime.yolox_runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.shared.yolox_runtime_contracts import RuntimeTensorSpec, YoloXRuntimeSessionInfo


@dataclass(frozen=True)
class _YoloV8PostprocessResult:
    """描述单张图片经过后处理后的候选结果。"""

    boxes_xyxy: Any
    scores: Any
    class_ids: Any


class PyTorchYoloV8RuntimeSession:
    """已经加载完成并可重复推理的 PyTorch YOLOv8 会话。"""

    def __init__(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        imports: Any,
        model: Any,
        device_name: str,
        runtime_precision: str,
    ) -> None:
        """初始化 PyTorch YOLOv8 会话。"""

        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.model = model
        self.device_name = device_name
        self.runtime_precision = runtime_precision

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
    ) -> "PyTorchYoloV8RuntimeSession":
        """加载一套 PyTorch YOLOv8 会话。"""

        if runtime_target.runtime_backend != "pytorch":
            raise InvalidRequestError(
                "当前 YOLOv8 predictor 仅支持 pytorch runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
            )

        imports = _require_training_imports()
        model = build_yolov8_detection_model(
            model_scale=runtime_target.model_scale,
            num_classes=len(runtime_target.labels),
        )
        load_yolov8_checkpoint(
            imports=imports,
            model=model,
            checkpoint_path=runtime_target.runtime_artifact_path,
        )
        device_name = _resolve_execution_device_name(
            torch_module=imports.torch,
            requested_device_name=runtime_target.device_name,
        )
        _enable_pytorch_cuda_inference_fast_path(
            torch_module=imports.torch,
            device_name=device_name,
        )
        model.to(device_name)
        if runtime_target.runtime_precision == "fp16":
            model.half()
        model.eval()
        return cls(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            imports=imports,
            model=model,
            device_name=device_name,
            runtime_precision=runtime_target.runtime_precision,
        )

    def predict(self, request: YoloXPredictionRequest) -> YoloXPredictionExecutionResult:
        """执行一次 PyTorch YOLOv8 预测。"""

        decode_started_at = perf_counter()
        image = _load_prediction_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = _measure_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=decode_started_at,
        )

        preprocess_started_at = perf_counter()
        input_tensor, resize_ratio = _preprocess_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            image=image,
            input_size=self.runtime_target.input_size,
        )
        input_tensor = self.imports.torch.from_numpy(input_tensor).unsqueeze(0).to(self.device_name)
        input_tensor = input_tensor.float()
        if self.runtime_precision == "fp16":
            input_tensor = input_tensor.half()
        preprocess_ms = _measure_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=preprocess_started_at,
        )

        nms_threshold = _resolve_probability(
            value=request.extra_options.get("nms_threshold"),
            field_name="nms_threshold",
            default=_DEFAULT_NMS_THRESHOLD,
        )

        infer_started_at = perf_counter()
        inference_mode = getattr(self.imports.torch, "inference_mode", None)
        if callable(inference_mode):
            with inference_mode():
                outputs = self.model(input_tensor)
        else:
            with self.imports.torch.no_grad():
                outputs = self.model(input_tensor)
        infer_ms = _measure_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=infer_started_at,
        )

        image_height = int(image.shape[0])
        image_width = int(image.shape[1])

        postprocess_started_at = perf_counter()
        prediction_array = _prediction_to_numpy_array(
            prediction_tensor=outputs,
            np_module=self.imports.np,
        )
        detections = _build_yolov8_detection_records(
            np_module=self.imports.np,
            prediction_array=prediction_array,
            labels=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            nms_threshold=nms_threshold,
            resize_ratio=resize_ratio,
            image_width=image_width,
            image_height=image_height,
        )
        postprocess_ms = _measure_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=postprocess_started_at,
        )
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = None
        if request.save_result_image:
            preview_image_bytes = _render_preview_image(
                cv2_module=self.imports.cv2,
                image=image,
                detections=detections,
            )

        return YoloXPredictionExecutionResult(
            detections=detections,
            latency_ms=round(latency_ms, 3),
            image_width=image_width,
            image_height=image_height,
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=YoloXRuntimeSessionInfo(
                backend_name=self.runtime_target.runtime_backend,
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=RuntimeTensorSpec(
                    name="images",
                    shape=(1, 3, self.runtime_target.input_size[0], self.runtime_target.input_size[1]),
                    dtype="float16" if self.runtime_precision == "fp16" else "float32",
                ),
                output_spec=RuntimeTensorSpec(
                    name="predictions",
                    shape=(-1, 4 + len(self.runtime_target.labels)),
                    dtype="float16" if self.runtime_precision == "fp16" else "float32",
                ),
                metadata={
                    "model_version_id": self.runtime_target.model_version_id,
                    "model_build_id": self.runtime_target.model_build_id,
                    "runtime_precision": self.runtime_precision,
                    "runtime_execution_mode": describe_runtime_execution_mode(
                        runtime_backend=self.runtime_target.runtime_backend,
                        runtime_precision=self.runtime_precision,
                        device_name=self.device_name,
                    ),
                    "score_threshold": request.score_threshold,
                    "nms_threshold": nms_threshold,
                    "class_count": len(self.runtime_target.labels),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                },
            ),
        )


class OnnxRuntimeYoloV8RuntimeSession:
    """已经加载完成并可重复推理的 ONNXRuntime YOLOv8 会话。"""

    def __init__(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        imports: Any,
        session: Any,
        device_name: str,
        input_name: str,
        output_name: str,
    ) -> None:
        """初始化 ONNXRuntime YOLOv8 会话。"""

        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.session = session
        self.device_name = device_name
        self.input_name = input_name
        self.output_name = output_name

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
    ) -> "OnnxRuntimeYoloV8RuntimeSession":
        """加载一套 ONNXRuntime YOLOv8 会话。"""

        if runtime_target.runtime_backend != "onnxruntime":
            raise InvalidRequestError(
                "当前 YOLOv8 predictor 仅支持 onnxruntime runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
            )

        imports = _require_inference_imports()
        onnxruntime_module = _import_onnxruntime_module()
        providers = _resolve_onnxruntime_providers(
            onnxruntime_module=onnxruntime_module,
            requested_device_name=runtime_target.device_name,
        )
        session = onnxruntime_module.InferenceSession(
            str(runtime_target.runtime_artifact_path),
            providers=providers,
        )
        return cls(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            imports=imports,
            session=session,
            device_name=runtime_target.device_name,
            input_name=session.get_inputs()[0].name,
            output_name=session.get_outputs()[0].name,
        )

    def predict(self, request: YoloXPredictionRequest) -> YoloXPredictionExecutionResult:
        """执行一次 ONNXRuntime YOLOv8 预测。"""

        decode_started_at = perf_counter()
        image = _load_prediction_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = round((perf_counter() - decode_started_at) * 1000, 3)

        preprocess_started_at = perf_counter()
        input_tensor, resize_ratio = _preprocess_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            image=image,
            input_size=self.runtime_target.input_size,
        )
        input_tensor = self.imports.np.expand_dims(input_tensor, axis=0).astype(self.imports.np.float32, copy=False)
        preprocess_ms = round((perf_counter() - preprocess_started_at) * 1000, 3)

        nms_threshold = _resolve_probability(
            value=request.extra_options.get("nms_threshold"),
            field_name="nms_threshold",
            default=_DEFAULT_NMS_THRESHOLD,
        )

        infer_started_at = perf_counter()
        outputs = self.session.run(
            [self.output_name],
            {self.input_name: input_tensor},
        )
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        image_height = int(image.shape[0])
        image_width = int(image.shape[1])

        postprocess_started_at = perf_counter()
        prediction_array = _normalize_onnxruntime_outputs(outputs=outputs, imports=self.imports)
        detections = _build_yolov8_detection_records(
            np_module=self.imports.np,
            prediction_array=prediction_array,
            labels=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            nms_threshold=nms_threshold,
            resize_ratio=resize_ratio,
            image_width=image_width,
            image_height=image_height,
        )
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = None
        if request.save_result_image:
            preview_image_bytes = _render_preview_image(
                cv2_module=self.imports.cv2,
                image=image,
                detections=detections,
            )

        return YoloXPredictionExecutionResult(
            detections=detections,
            latency_ms=round(latency_ms, 3),
            image_width=image_width,
            image_height=image_height,
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=YoloXRuntimeSessionInfo(
                backend_name=self.runtime_target.runtime_backend,
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=RuntimeTensorSpec(
                    name=self.input_name,
                    shape=(1, 3, self.runtime_target.input_size[0], self.runtime_target.input_size[1]),
                    dtype="float32",
                ),
                output_spec=RuntimeTensorSpec(
                    name=self.output_name,
                    shape=(-1, 4 + len(self.runtime_target.labels)),
                    dtype="float32",
                ),
                metadata={
                    "model_version_id": self.runtime_target.model_version_id,
                    "model_build_id": self.runtime_target.model_build_id,
                    "runtime_precision": self.runtime_target.runtime_precision,
                    "runtime_execution_mode": describe_runtime_execution_mode(
                        runtime_backend=self.runtime_target.runtime_backend,
                        runtime_precision=self.runtime_target.runtime_precision,
                        device_name=self.device_name,
                    ),
                    "score_threshold": request.score_threshold,
                    "nms_threshold": nms_threshold,
                    "class_count": len(self.runtime_target.labels),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                    "provider_names": list(self.session.get_providers()),
                },
            ),
        )


def _build_yolov8_detection_records(
    *,
    np_module: Any,
    prediction_array: Any,
    labels: tuple[str, ...],
    score_threshold: float,
    nms_threshold: float,
    resize_ratio: float,
    image_width: int,
    image_height: int,
) -> tuple[YoloXPredictionDetection, ...]:
    """把 YOLOv8 输出数组转换成平台 detection 记录。"""

    postprocess_results = _postprocess_yolov8_prediction_array(
        prediction_array=prediction_array,
        np_module=np_module,
        num_classes=len(labels),
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
    )
    if not postprocess_results:
        return ()

    detections: list[YoloXPredictionDetection] = []
    prediction = postprocess_results[0]
    if prediction is None:
        return ()
    for bbox, score, class_id in zip(
        prediction.boxes_xyxy,
        prediction.scores,
        prediction.class_ids,
        strict=True,
    ):
        scaled_bbox = bbox / max(resize_ratio, 1e-8)
        x1 = float(max(0.0, min(float(scaled_bbox[0]), float(image_width))))
        y1 = float(max(0.0, min(float(scaled_bbox[1]), float(image_height))))
        x2 = float(max(0.0, min(float(scaled_bbox[2]), float(image_width))))
        y2 = float(max(0.0, min(float(scaled_bbox[3]), float(image_height))))
        resolved_class_id = int(class_id)
        class_name = labels[resolved_class_id] if 0 <= resolved_class_id < len(labels) else None
        detections.append(
            YoloXPredictionDetection(
                bbox_xyxy=(round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)),
                score=round(float(score), 6),
                class_id=resolved_class_id,
                class_name=class_name,
            )
        )
    detections.sort(key=lambda item: item.score, reverse=True)
    return tuple(detections)


def _postprocess_yolov8_prediction_array(
    *,
    prediction_array: Any,
    np_module: Any,
    num_classes: int,
    score_threshold: float,
    nms_threshold: float,
) -> list[_YoloV8PostprocessResult | None]:
    """执行 YOLOv8 输出的阈值过滤与 NMS。"""

    normalized_prediction = np_module.asarray(prediction_array, dtype=np_module.float32)
    if normalized_prediction.ndim == 2:
        normalized_prediction = np_module.expand_dims(normalized_prediction, axis=0)
    if normalized_prediction.ndim < 3:
        raise InvalidRequestError(
            "YOLOv8 推理输出维度不合法",
            details={"shape": list(normalized_prediction.shape)},
        )
    if int(normalized_prediction.shape[2]) < 4 + num_classes:
        raise InvalidRequestError(
            "YOLOv8 推理输出通道数不足",
            details={
                "channel_count": int(normalized_prediction.shape[2]),
                "required_channel_count": 4 + num_classes,
            },
        )

    results: list[_YoloV8PostprocessResult | None] = []
    for image_prediction in normalized_prediction:
        boxes = image_prediction[:, :4]
        class_scores = image_prediction[:, 4 : 4 + num_classes]
        if int(boxes.shape[0]) <= 0:
            results.append(None)
            continue
        best_scores = np_module.max(class_scores, axis=1)
        best_class_ids = np_module.argmax(class_scores, axis=1).astype(np_module.int32, copy=False)
        keep_mask = best_scores >= score_threshold
        boxes = boxes[keep_mask]
        best_scores = best_scores[keep_mask]
        best_class_ids = best_class_ids[keep_mask]
        if int(boxes.shape[0]) <= 0:
            results.append(None)
            continue
        keep_indices = _batched_nms_indices(
            boxes=boxes,
            scores=best_scores,
            class_ids=best_class_ids,
            nms_threshold=nms_threshold,
            np_module=np_module,
        )
        if int(keep_indices.size) <= 0:
            results.append(None)
            continue
        results.append(
            _YoloV8PostprocessResult(
                boxes_xyxy=boxes[keep_indices],
                scores=best_scores[keep_indices],
                class_ids=best_class_ids[keep_indices],
            )
        )
    return results
