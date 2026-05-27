"""YOLO 主线 segmentation 单图推理实现。"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.yolo_primary_detection_model import (
    load_yolo_primary_checkpoint,
)
from backend.service.application.models.yolo_primary_detection_training import (
    _require_training_imports,
)
from backend.service.application.models.yolo_primary_model_configs import (
    build_yolo_primary_model,
)
from backend.service.application.runtime.detection_runtime_support import (
    batched_nms_indices,
    import_onnxruntime_module,
    load_prediction_image,
    preprocess_image,
    render_preview_image,
    require_inference_imports,
    resolve_execution_device_name,
    resolve_onnxruntime_providers,
)
from backend.service.application.runtime.segmentation_runtime_contracts import (
    SegmentationPredictionExecutionResult,
    SegmentationPredictionInstance,
    SegmentationPredictionRequest,
    SegmentationRuntimeSessionInfo,
    SegmentationRuntimeTensorSpec,
)
from backend.service.application.runtime.yolox_runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class _SegmentationPostprocessResult:
    """描述单张图片经过后处理后的候选结果。"""

    boxes_xyxy: Any
    scores: Any
    class_ids: Any
    mask_coefficients: Any


class PyTorchYoloPrimarySegmentationRuntimeSession:
    """已经加载完成并可重复推理的 PyTorch YOLO 主线 segmentation 会话。"""

    model_type = "yolo-primary"
    model_label = "YOLO primary"
    task_type = "segmentation"

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
        """初始化 PyTorch segmentation 会话。"""

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
    ) -> "PyTorchYoloPrimarySegmentationRuntimeSession":
        """加载一套 PyTorch segmentation 会话。"""

        if runtime_target.runtime_backend != "pytorch":
            raise InvalidRequestError(
                f"当前 {cls.model_label} segmentation predictor 仅支持 pytorch runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(
                f"当前 {cls.model_label} segmentation predictor 收到了错误的 task_type",
                details={"task_type": runtime_target.task_type},
            )
        imports = _require_training_imports()
        model = build_yolo_primary_model(
            model_type=_require_primary_model_type(cls.model_type, cls.model_label),
            task_type=cls.task_type,
            model_scale=runtime_target.model_scale,
            num_classes=len(runtime_target.labels),
        )
        load_yolo_primary_checkpoint(
            imports=imports,
            model=model,
            checkpoint_path=runtime_target.runtime_artifact_path,
        )
        device_name = resolve_execution_device_name(
            torch_module=imports.torch,
            requested_device_name=runtime_target.device_name,
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

    def predict(self, request: SegmentationPredictionRequest) -> SegmentationPredictionExecutionResult:
        """执行一次 PyTorch segmentation 预测。"""

        decode_started_at = perf_counter()
        image = load_prediction_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = round((perf_counter() - decode_started_at) * 1000, 3)

        preprocess_started_at = perf_counter()
        input_tensor, resize_ratio = preprocess_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            image=image,
            input_size=self.runtime_target.input_size,
        )
        input_tensor = self.imports.torch.from_numpy(input_tensor).unsqueeze(0).to(self.device_name)
        input_tensor = input_tensor.float()
        if self.runtime_precision == "fp16":
            input_tensor = input_tensor.half()
        preprocess_ms = round((perf_counter() - preprocess_started_at) * 1000, 3)

        infer_started_at = perf_counter()
        inference_mode = getattr(self.imports.torch, "inference_mode", None)
        if callable(inference_mode):
            with inference_mode():
                outputs = self.model(input_tensor)
        else:
            with self.imports.torch.no_grad():
                outputs = self.model(input_tensor)
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        prediction_array, proto_array = _normalize_segmentation_outputs(
            outputs=outputs,
            np_module=self.imports.np,
        )
        postprocess_started_at = perf_counter()
        instances = _build_segmentation_instances(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            prediction_array=prediction_array,
            proto_array=proto_array,
            labels=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            mask_threshold=request.mask_threshold,
            resize_ratio=resize_ratio,
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
            input_size=self.runtime_target.input_size,
        )
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = None
        if request.save_result_image:
            preview_detections = tuple(
                _as_preview_detection(instance)
                for instance in instances
            )
            preview_image_bytes = render_preview_image(
                cv2_module=self.imports.cv2,
                image=image,
                detections=preview_detections,
            )

        return SegmentationPredictionExecutionResult(
            instances=instances,
            latency_ms=round(latency_ms, 3),
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=SegmentationRuntimeSessionInfo(
                backend_name=self.runtime_target.runtime_backend,
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=SegmentationRuntimeTensorSpec(
                    name="images",
                    shape=(1, 3, self.runtime_target.input_size[0], self.runtime_target.input_size[1]),
                    dtype="float16" if self.runtime_precision == "fp16" else "float32",
                ),
                output_specs=(
                    SegmentationRuntimeTensorSpec(
                        name="predictions",
                        shape=tuple(int(item) for item in prediction_array.shape),
                        dtype="float16" if self.runtime_precision == "fp16" else "float32",
                    ),
                    SegmentationRuntimeTensorSpec(
                        name="proto",
                        shape=tuple(int(item) for item in proto_array.shape),
                        dtype="float16" if self.runtime_precision == "fp16" else "float32",
                    ),
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
                    "mask_threshold": request.mask_threshold,
                    "class_count": len(self.runtime_target.labels),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                },
            ),
        )


class OnnxRuntimeYoloPrimarySegmentationRuntimeSession:
    """已经加载完成并可重复推理的 ONNXRuntime YOLO 主线 segmentation 会话。"""

    model_type = "yolo-primary"
    model_label = "YOLO primary"
    task_type = "segmentation"

    def __init__(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        imports: Any,
        session: Any,
        device_name: str,
        input_name: str,
        output_names: tuple[str, ...],
    ) -> None:
        """初始化 ONNXRuntime segmentation 会话。"""

        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.session = session
        self.device_name = device_name
        self.input_name = input_name
        self.output_names = output_names

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
    ) -> "OnnxRuntimeYoloPrimarySegmentationRuntimeSession":
        """加载一套 ONNXRuntime segmentation 会话。"""

        if runtime_target.runtime_backend != "onnxruntime":
            raise InvalidRequestError(
                f"当前 {cls.model_label} segmentation predictor 仅支持 onnxruntime runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(
                f"当前 {cls.model_label} segmentation predictor 收到了错误的 task_type",
                details={"task_type": runtime_target.task_type},
            )
        if runtime_target.runtime_precision != "fp32":
            raise InvalidRequestError(
                "当前 segmentation onnxruntime session 仅支持 fp32 precision",
                details={"runtime_precision": runtime_target.runtime_precision},
            )
        imports = require_inference_imports()
        onnxruntime_module = import_onnxruntime_module()
        providers = resolve_onnxruntime_providers(
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
            output_names=tuple(item.name for item in session.get_outputs()),
        )

    def predict(self, request: SegmentationPredictionRequest) -> SegmentationPredictionExecutionResult:
        """执行一次 ONNXRuntime segmentation 预测。"""

        decode_started_at = perf_counter()
        image = load_prediction_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = round((perf_counter() - decode_started_at) * 1000, 3)

        preprocess_started_at = perf_counter()
        input_tensor, resize_ratio = preprocess_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            image=image,
            input_size=self.runtime_target.input_size,
        )
        input_tensor = self.imports.np.expand_dims(input_tensor, axis=0).astype(self.imports.np.float32, copy=False)
        preprocess_ms = round((perf_counter() - preprocess_started_at) * 1000, 3)

        infer_started_at = perf_counter()
        outputs = self.session.run(
            list(self.output_names),
            {self.input_name: input_tensor},
        )
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        prediction_array, proto_array = _normalize_segmentation_outputs(
            outputs=outputs,
            np_module=self.imports.np,
        )
        postprocess_started_at = perf_counter()
        instances = _build_segmentation_instances(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            prediction_array=prediction_array,
            proto_array=proto_array,
            labels=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            mask_threshold=request.mask_threshold,
            resize_ratio=resize_ratio,
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
            input_size=self.runtime_target.input_size,
        )
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = None
        if request.save_result_image:
            preview_detections = tuple(
                _as_preview_detection(instance)
                for instance in instances
            )
            preview_image_bytes = render_preview_image(
                cv2_module=self.imports.cv2,
                image=image,
                detections=preview_detections,
            )

        return SegmentationPredictionExecutionResult(
            instances=instances,
            latency_ms=round(latency_ms, 3),
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=SegmentationRuntimeSessionInfo(
                backend_name=self.runtime_target.runtime_backend,
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=SegmentationRuntimeTensorSpec(
                    name=self.input_name,
                    shape=(1, 3, self.runtime_target.input_size[0], self.runtime_target.input_size[1]),
                    dtype="float32",
                ),
                output_specs=tuple(
                    SegmentationRuntimeTensorSpec(
                        name=self.output_names[index] if index < len(self.output_names) else f"output-{index}",
                        shape=tuple(int(item) for item in array.shape),
                        dtype="float32",
                    )
                    for index, array in enumerate((prediction_array, proto_array))
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
                    "mask_threshold": request.mask_threshold,
                    "class_count": len(self.runtime_target.labels),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                    "provider_names": list(self.session.get_providers()),
                    "output_names": list(self.output_names),
                },
            ),
        )


def _normalize_segmentation_outputs(
    *,
    outputs: object,
    np_module: Any,
) -> tuple[Any, Any]:
    """把 segmentation 推理输出归一为 prediction/proto 两个数组。"""

    if not isinstance(outputs, list | tuple) or len(outputs) < 2:
        raise InvalidRequestError("segmentation 推理输出缺少 prediction/proto 双输出")
    prediction_array = np_module.asarray(outputs[0], dtype=np_module.float32)
    proto_array = np_module.asarray(outputs[1], dtype=np_module.float32)
    if prediction_array.ndim == 2:
        prediction_array = np_module.expand_dims(prediction_array, axis=0)
    if proto_array.ndim == 3:
        proto_array = np_module.expand_dims(proto_array, axis=0)
    if prediction_array.ndim < 3:
        raise InvalidRequestError("segmentation prediction 输出维度不合法", details={"shape": list(prediction_array.shape)})
    if proto_array.ndim != 4:
        raise InvalidRequestError("segmentation proto 输出维度不合法", details={"shape": list(proto_array.shape)})
    return prediction_array, proto_array


def _build_segmentation_instances(
    *,
    cv2_module: Any,
    np_module: Any,
    prediction_array: Any,
    proto_array: Any,
    labels: tuple[str, ...],
    score_threshold: float,
    mask_threshold: float,
    resize_ratio: float,
    image_width: int,
    image_height: int,
    input_size: tuple[int, int],
) -> tuple[SegmentationPredictionInstance, ...]:
    """把 segmentation 输出数组转换成平台实例记录。"""

    postprocess_results = _postprocess_segmentation_prediction_array(
        prediction_array=prediction_array,
        np_module=np_module,
        num_classes=len(labels),
        score_threshold=score_threshold,
    )
    if not postprocess_results:
        return ()
    proto = proto_array[0]
    resized_height = min(int(round(image_height * resize_ratio)), int(input_size[0]))
    resized_width = min(int(round(image_width * resize_ratio)), int(input_size[1]))
    instances: list[SegmentationPredictionInstance] = []
    prediction = postprocess_results[0]
    if prediction is None:
        return ()
    masks = _decode_segmentation_masks(
        cv2_module=cv2_module,
        np_module=np_module,
        proto=proto,
        mask_coefficients=prediction.mask_coefficients,
        input_size=input_size,
        resized_width=resized_width,
        resized_height=resized_height,
        image_width=image_width,
        image_height=image_height,
        mask_threshold=mask_threshold,
    )
    for bbox, score, class_id, binary_mask in zip(
        prediction.boxes_xyxy,
        prediction.scores,
        prediction.class_ids,
        masks,
        strict=True,
    ):
        scaled_bbox = bbox / max(resize_ratio, 1e-8)
        x1 = float(max(0.0, min(float(scaled_bbox[0]), float(image_width))))
        y1 = float(max(0.0, min(float(scaled_bbox[1]), float(image_height))))
        x2 = float(max(0.0, min(float(scaled_bbox[2]), float(image_width))))
        y2 = float(max(0.0, min(float(scaled_bbox[3]), float(image_height))))
        resolved_class_id = int(class_id)
        class_name = labels[resolved_class_id] if 0 <= resolved_class_id < len(labels) else None
        segments = _extract_mask_segments(cv2_module=cv2_module, binary_mask=binary_mask)
        mask_area = float(np_module.count_nonzero(binary_mask))
        instances.append(
            SegmentationPredictionInstance(
                bbox_xyxy=(round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)),
                score=round(float(score), 6),
                class_id=resolved_class_id,
                class_name=class_name,
                segments=segments,
                mask_area=round(mask_area, 3),
            )
        )
    instances.sort(key=lambda item: item.score, reverse=True)
    return tuple(instances)


def _postprocess_segmentation_prediction_array(
    *,
    prediction_array: Any,
    np_module: Any,
    num_classes: int,
    score_threshold: float,
) -> list[_SegmentationPostprocessResult | None]:
    """执行 segmentation 输出的阈值过滤与 NMS。"""

    normalized_prediction = np_module.asarray(prediction_array, dtype=np_module.float32)
    if normalized_prediction.ndim == 2:
        normalized_prediction = np_module.expand_dims(normalized_prediction, axis=0)
    if normalized_prediction.ndim < 3:
        raise InvalidRequestError("segmentation 推理输出维度不合法", details={"shape": list(normalized_prediction.shape)})
    if int(normalized_prediction.shape[2]) <= 4 + num_classes:
        raise InvalidRequestError(
            "segmentation 推理输出通道数不足",
            details={"channel_count": int(normalized_prediction.shape[2]), "required_min_channels": 5 + num_classes},
        )

    results: list[_SegmentationPostprocessResult | None] = []
    for image_prediction in normalized_prediction:
        boxes = image_prediction[:, :4]
        class_scores = image_prediction[:, 4 : 4 + num_classes]
        mask_coefficients = image_prediction[:, 4 + num_classes :]
        if int(boxes.shape[0]) <= 0:
            results.append(None)
            continue
        best_scores = np_module.max(class_scores, axis=1)
        best_class_ids = np_module.argmax(class_scores, axis=1).astype(np_module.int32, copy=False)
        keep_mask = best_scores >= score_threshold
        boxes = boxes[keep_mask]
        best_scores = best_scores[keep_mask]
        best_class_ids = best_class_ids[keep_mask]
        mask_coefficients = mask_coefficients[keep_mask]
        if int(boxes.shape[0]) <= 0:
            results.append(None)
            continue
        keep_indices = batched_nms_indices(
            boxes=boxes,
            scores=best_scores,
            class_ids=best_class_ids,
            nms_threshold=0.65,
            np_module=np_module,
        )
        if int(keep_indices.size) <= 0:
            results.append(None)
            continue
        results.append(
            _SegmentationPostprocessResult(
                boxes_xyxy=boxes[keep_indices],
                scores=best_scores[keep_indices],
                class_ids=best_class_ids[keep_indices],
                mask_coefficients=mask_coefficients[keep_indices],
            )
        )
    return results


def _decode_segmentation_masks(
    *,
    cv2_module: Any,
    np_module: Any,
    proto: Any,
    mask_coefficients: Any,
    input_size: tuple[int, int],
    resized_width: int,
    resized_height: int,
    image_width: int,
    image_height: int,
    mask_threshold: float,
) -> list[Any]:
    """根据 proto 与 mask coeff 解码实例 mask。"""

    proto_features = proto.reshape(int(proto.shape[0]), -1)
    mask_logits = mask_coefficients @ proto_features
    mask_logits = mask_logits.reshape(int(mask_coefficients.shape[0]), int(proto.shape[1]), int(proto.shape[2]))
    masks: list[Any] = []
    for mask_logit in mask_logits:
        probability_mask = 1.0 / (1.0 + np_module.exp(-mask_logit))
        resized_mask = cv2_module.resize(
            probability_mask,
            (int(input_size[1]), int(input_size[0])),
            interpolation=cv2_module.INTER_LINEAR,
        )
        cropped_mask = resized_mask[:resized_height, :resized_width]
        restored_mask = cv2_module.resize(
            cropped_mask,
            (int(image_width), int(image_height)),
            interpolation=cv2_module.INTER_LINEAR,
        )
        binary_mask = (restored_mask >= mask_threshold).astype(np_module.uint8)
        masks.append(binary_mask)
    return masks


def _extract_mask_segments(*, cv2_module: Any, binary_mask: Any) -> tuple[tuple[tuple[float, float], ...], ...]:
    """从二值 mask 中提取多边形轮廓。"""

    contours, _hierarchy = cv2_module.findContours(
        binary_mask,
        cv2_module.RETR_EXTERNAL,
        cv2_module.CHAIN_APPROX_SIMPLE,
    )
    segments: list[tuple[tuple[float, float], ...]] = []
    for contour in contours:
        if contour is None or len(contour) < 3:
            continue
        flattened = contour.reshape(-1, 2)
        segments.append(
            tuple((round(float(point[0]), 3), round(float(point[1]), 3)) for point in flattened)
        )
    return tuple(segments)


def _as_preview_detection(instance: SegmentationPredictionInstance):
    """把 segmentation 实例转换为预览绘制用 detection 记录。"""

    from backend.service.application.runtime.detection_runtime_contracts import DetectionPredictionDetection

    return DetectionPredictionDetection(
        bbox_xyxy=instance.bbox_xyxy,
        score=instance.score,
        class_id=instance.class_id,
        class_name=instance.class_name,
    )


def _require_primary_model_type(model_type: str, model_label: str) -> str:
    """返回当前主线 predictor 允许使用的正式模型分类。"""

    normalized_model_type = model_type.strip().lower()
    if not normalized_model_type or normalized_model_type == "yolo-primary":
        raise ServiceConfigurationError(
            f"当前 {model_label} segmentation predictor 缺少正式 model_type 配置",
            details={"model_type": model_type},
        )
    return normalized_model_type
