"""YOLO 主线 classification 单图推理实现。"""

from __future__ import annotations

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
from backend.service.application.runtime.classification_runtime_contracts import (
    ClassificationPredictionCategory,
    ClassificationPredictionExecutionResult,
    ClassificationPredictionRequest,
    ClassificationRuntimeSessionInfo,
    ClassificationRuntimeTensorSpec,
)
from backend.service.application.runtime.detection_runtime_support import (
    enable_pytorch_cuda_inference_fast_path,
    import_onnxruntime_module,
    load_prediction_image,
    require_inference_imports,
    resolve_execution_device_name,
    resolve_onnxruntime_providers,
)
from backend.service.application.runtime.yolox_runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class PyTorchYoloPrimaryClassificationRuntimeSession:
    """已经加载完成并可重复推理的 PyTorch YOLO 主线 classification 会话。"""

    model_type = "yolo-primary"
    model_label = "YOLO primary"
    task_type = "classification"

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
        """初始化 PyTorch classification 会话。"""

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
    ) -> "PyTorchYoloPrimaryClassificationRuntimeSession":
        """加载一套 PyTorch classification 会话。"""

        if runtime_target.runtime_backend != "pytorch":
            raise InvalidRequestError(
                f"当前 {cls.model_label} classification predictor 仅支持 pytorch runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(
                f"当前 {cls.model_label} classification predictor 收到了错误的 task_type",
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
        enable_pytorch_cuda_inference_fast_path(
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

    def predict(self, request: ClassificationPredictionRequest) -> ClassificationPredictionExecutionResult:
        """执行一次 PyTorch classification 预测。"""

        top_k = _resolve_top_k(request=request, class_count=len(self.runtime_target.labels))

        decode_started_at = perf_counter()
        image = load_prediction_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = round((perf_counter() - decode_started_at) * 1000, 3)

        preprocess_started_at = perf_counter()
        input_tensor = _preprocess_classification_image(
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

        postprocess_started_at = perf_counter()
        probabilities, logits = _normalize_pytorch_classification_outputs(
            outputs=outputs,
            np_module=self.imports.np,
        )
        categories = _build_classification_categories(
            np_module=self.imports.np,
            probabilities=probabilities,
            logits=logits,
            labels=self.runtime_target.labels,
            top_k=top_k,
        )
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = None
        if request.save_result_image:
            preview_image_bytes = _render_classification_preview_image(
                cv2_module=self.imports.cv2,
                image=image,
                categories=categories,
            )

        output_dtype = "float16" if self.runtime_precision == "fp16" else "float32"
        return ClassificationPredictionExecutionResult(
            categories=categories,
            top_category=categories[0] if categories else None,
            latency_ms=round(latency_ms, 3),
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=ClassificationRuntimeSessionInfo(
                backend_name=self.runtime_target.runtime_backend,
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=ClassificationRuntimeTensorSpec(
                    name="images",
                    shape=(1, 3, self.runtime_target.input_size[0], self.runtime_target.input_size[1]),
                    dtype=output_dtype,
                ),
                output_spec=ClassificationRuntimeTensorSpec(
                    name="probabilities",
                    shape=(1, len(self.runtime_target.labels)),
                    dtype=output_dtype,
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
                    "top_k": top_k,
                    "class_count": len(self.runtime_target.labels),
                    "logits_available": logits is not None,
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                },
            ),
        )


class OnnxRuntimeYoloPrimaryClassificationRuntimeSession:
    """已经加载完成并可重复推理的 ONNXRuntime YOLO 主线 classification 会话。"""

    model_type = "yolo-primary"
    model_label = "YOLO primary"
    task_type = "classification"

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
        """初始化 ONNXRuntime classification 会话。"""

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
    ) -> "OnnxRuntimeYoloPrimaryClassificationRuntimeSession":
        """加载一套 ONNXRuntime classification 会话。"""

        if runtime_target.runtime_backend != "onnxruntime":
            raise InvalidRequestError(
                f"当前 {cls.model_label} classification predictor 仅支持 onnxruntime runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(
                f"当前 {cls.model_label} classification predictor 收到了错误的 task_type",
                details={"task_type": runtime_target.task_type},
            )
        if runtime_target.runtime_precision != "fp32":
            raise InvalidRequestError(
                "当前 classification onnxruntime session 仅支持 fp32 precision",
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

    def predict(self, request: ClassificationPredictionRequest) -> ClassificationPredictionExecutionResult:
        """执行一次 ONNXRuntime classification 预测。"""

        top_k = _resolve_top_k(request=request, class_count=len(self.runtime_target.labels))

        decode_started_at = perf_counter()
        image = load_prediction_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = round((perf_counter() - decode_started_at) * 1000, 3)

        preprocess_started_at = perf_counter()
        input_tensor = _preprocess_classification_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            image=image,
            input_size=self.runtime_target.input_size,
        )
        input_tensor = self.imports.np.expand_dims(input_tensor, axis=0).astype(
            self.imports.np.float32,
            copy=False,
        )
        preprocess_ms = round((perf_counter() - preprocess_started_at) * 1000, 3)

        infer_started_at = perf_counter()
        outputs = self.session.run(
            list(self.output_names),
            {self.input_name: input_tensor},
        )
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        postprocess_started_at = perf_counter()
        probabilities, logits = _normalize_onnxruntime_classification_outputs(
            outputs=outputs,
            np_module=self.imports.np,
        )
        categories = _build_classification_categories(
            np_module=self.imports.np,
            probabilities=probabilities,
            logits=logits,
            labels=self.runtime_target.labels,
            top_k=top_k,
        )
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = None
        if request.save_result_image:
            preview_image_bytes = _render_classification_preview_image(
                cv2_module=self.imports.cv2,
                image=image,
                categories=categories,
            )

        return ClassificationPredictionExecutionResult(
            categories=categories,
            top_category=categories[0] if categories else None,
            latency_ms=round(latency_ms, 3),
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=ClassificationRuntimeSessionInfo(
                backend_name=self.runtime_target.runtime_backend,
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=ClassificationRuntimeTensorSpec(
                    name=self.input_name,
                    shape=(1, 3, self.runtime_target.input_size[0], self.runtime_target.input_size[1]),
                    dtype="float32",
                ),
                output_spec=ClassificationRuntimeTensorSpec(
                    name=self.output_names[0] if self.output_names else "probabilities",
                    shape=(1, len(self.runtime_target.labels)),
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
                    "top_k": top_k,
                    "class_count": len(self.runtime_target.labels),
                    "logits_available": logits is not None,
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                    "provider_names": list(self.session.get_providers()),
                    "output_names": list(self.output_names),
                },
            ),
        )


def _preprocess_classification_image(
    *,
    cv2_module: Any,
    np_module: Any,
    image: Any,
    input_size: tuple[int, int],
) -> Any:
    """按 classification 规则把图片缩放为 CHW 浮点张量。"""

    target_height, target_width = input_size
    resized_image = cv2_module.resize(
        image,
        (int(target_width), int(target_height)),
        interpolation=cv2_module.INTER_LINEAR,
    )
    tensor = resized_image[:, :, ::-1].transpose(2, 0, 1)
    tensor = np_module.ascontiguousarray(tensor, dtype=np_module.float32)
    return tensor / 255.0


def _normalize_pytorch_classification_outputs(
    *,
    outputs: object,
    np_module: Any,
) -> tuple[Any, Any | None]:
    """把 PyTorch classification 输出归一为 probabilities/logits。"""

    if isinstance(outputs, list | tuple):
        if len(outputs) >= 2:
            probabilities = _tensor_to_numpy_array(outputs[0], np_module=np_module)
            logits = _tensor_to_numpy_array(outputs[1], np_module=np_module)
            return _ensure_probability_array(probabilities, np_module=np_module), logits
        if outputs:
            outputs = outputs[0]
    normalized = _tensor_to_numpy_array(outputs, np_module=np_module)
    return _ensure_probability_array(normalized, np_module=np_module), None


def _normalize_onnxruntime_classification_outputs(
    *,
    outputs: object,
    np_module: Any,
) -> tuple[Any, Any | None]:
    """把 ONNXRuntime classification 输出归一为 probabilities/logits。"""

    if not isinstance(outputs, list) or not outputs:
        raise InvalidRequestError("onnxruntime classification 推理输出为空")
    probabilities = _ensure_probability_array(outputs[0], np_module=np_module)
    logits = None
    if len(outputs) >= 2:
        logits = _tensor_to_numpy_array(outputs[1], np_module=np_module)
    return probabilities, logits


def _tensor_to_numpy_array(value: object, *, np_module: Any) -> Any:
    """把 tensor 或数组统一转换为二维 NumPy 数组。"""

    normalized = value
    if hasattr(normalized, "detach"):
        normalized = normalized.detach()
    if hasattr(normalized, "cpu"):
        normalized = normalized.cpu()
    if hasattr(normalized, "numpy"):
        normalized = normalized.numpy()
    array = np_module.asarray(normalized, dtype=np_module.float32)
    if array.ndim == 1:
        array = np_module.expand_dims(array, axis=0)
    if array.ndim != 2:
        raise InvalidRequestError(
            "classification 推理输出维度不合法",
            details={"shape": list(array.shape)},
        )
    return array


def _ensure_probability_array(prediction_array: object, *, np_module: Any) -> Any:
    """把原始 classification 输出归一为概率数组。"""

    probabilities = _tensor_to_numpy_array(prediction_array, np_module=np_module)
    row_sums = probabilities.sum(axis=1, keepdims=True)
    if (
        float(np_module.min(probabilities)) < 0.0
        or float(np_module.max(probabilities)) > 1.0
        or not bool(np_module.allclose(row_sums, 1.0, rtol=1e-3, atol=1e-3))
    ):
        shifted = probabilities - probabilities.max(axis=1, keepdims=True)
        exp_values = np_module.exp(shifted)
        probabilities = exp_values / np_module.maximum(exp_values.sum(axis=1, keepdims=True), 1e-12)
    return probabilities


def _build_classification_categories(
    *,
    np_module: Any,
    probabilities: Any,
    logits: Any | None,
    labels: tuple[str, ...],
    top_k: int,
) -> tuple[ClassificationPredictionCategory, ...]:
    """把 probabilities/logits 转换成平台 classification 结果。"""

    if int(probabilities.shape[0]) <= 0:
        return ()
    probability_row = probabilities[0]
    logit_row = logits[0] if logits is not None and int(logits.shape[0]) > 0 else None
    sorted_indices = np_module.argsort(probability_row)[::-1]
    categories: list[ClassificationPredictionCategory] = []
    for class_id in sorted_indices[:top_k].tolist():
        resolved_class_id = int(class_id)
        class_name = labels[resolved_class_id] if 0 <= resolved_class_id < len(labels) else None
        logit_value = None if logit_row is None else float(logit_row[resolved_class_id])
        categories.append(
            ClassificationPredictionCategory(
                class_id=resolved_class_id,
                class_name=class_name,
                probability=round(float(probability_row[resolved_class_id]), 6),
                logit=round(logit_value, 6) if logit_value is not None else None,
            )
        )
    return tuple(categories)


def _render_classification_preview_image(
    *,
    cv2_module: Any,
    image: Any,
    categories: tuple[ClassificationPredictionCategory, ...],
) -> bytes:
    """把 classification top-k 结果叠加到原图并编码为 JPEG。"""

    preview = image.copy()
    overlay_lines = categories or (
        ClassificationPredictionCategory(
            class_id=-1,
            class_name="no-result",
            probability=0.0,
        ),
    )
    for line_index, category in enumerate(overlay_lines, start=1):
        label = category.class_name or str(category.class_id)
        text = f"top{line_index} {label}: {category.probability:.3f}"
        cv2_module.putText(
            preview,
            text,
            (12, 24 * line_index),
            cv2_module.FONT_HERSHEY_SIMPLEX,
            0.6,
            (40, 180, 120),
            2,
            cv2_module.LINE_AA,
        )
    success, encoded = cv2_module.imencode(".jpg", preview)
    if success is not True:
        raise InvalidRequestError("classification 预测预览图编码失败")
    return bytes(encoded.tobytes())


def _resolve_top_k(*, request: ClassificationPredictionRequest, class_count: int) -> int:
    """返回当前请求实际使用的 top-k 值。"""

    if request.top_k <= 0:
        raise InvalidRequestError("top_k 必须大于 0", details={"top_k": request.top_k})
    return min(int(request.top_k), int(class_count))


def _require_primary_model_type(model_type: str, model_label: str) -> str:
    """返回当前主线 predictor 允许使用的正式模型分类。"""

    normalized_model_type = model_type.strip().lower()
    if not normalized_model_type or normalized_model_type == "yolo-primary":
        raise ServiceConfigurationError(
            f"当前 {model_label} classification predictor 缺少正式 model_type 配置",
            details={"model_type": model_type},
        )
    return normalized_model_type
