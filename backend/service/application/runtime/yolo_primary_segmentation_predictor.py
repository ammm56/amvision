"""YOLO 主线 segmentation 单图推理实现。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.model_type_support import (
    normalize_optional_platform_model_type,
)
from backend.service.application.models.yolo_primary_detection_model import (
    load_yolo_primary_checkpoint,
)
from backend.service.application.models.yolo_primary_detection_training import (
    _require_training_imports,
)
from backend.service.application.models.yolo_core_common.postprocess import (
    build_segmentation_postprocess_instances,
    normalize_segmentation_outputs,
)
from backend.service.application.models.yolo_primary_model_configs import (
    build_yolo_primary_model,
)
from backend.service.application.runtime.support.detection import (
    batched_nms_indices,
    build_openvino_compile_properties,
    ensure_cuda_success,
    enable_pytorch_cuda_inference_fast_path,
    get_tensorrt_logger,
    import_onnxruntime_module,
    import_openvino_module,
    import_tensorrt_module,
    load_prediction_image,
    measure_cuda_event_elapsed_ms,
    normalize_tensor_shape,
    preprocess_image,
    render_preview_image,
    require_cuda_inference_imports,
    require_inference_imports,
    resolve_cuda_device_index,
    resolve_cuda_runtime_device_name,
    resolve_execution_device_name,
    resolve_numpy_dtype,
    resolve_onnxruntime_providers,
    resolve_openvino_compiled_runtime_precision,
    resolve_openvino_device_name,
    resolve_openvino_port_dtype,
    resolve_openvino_port_name,
    resolve_tensorrt_dtype_name,
    resolve_tensorrt_io_tensor_name,
)
from backend.service.application.runtime.segmentation_runtime_contracts import (
    SegmentationPredictionExecutionResult,
    SegmentationPredictionInstance,
    SegmentationPredictionRequest,
    SegmentationRuntimeSessionInfo,
    SegmentationRuntimeTensorSpec,
)
from backend.service.application.runtime.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.settings import get_backend_service_settings
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

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

        prediction_array, proto_array = normalize_segmentation_outputs(
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

        prediction_array, proto_array = normalize_segmentation_outputs(
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


class OpenVINOYoloPrimarySegmentationRuntimeSession:
    """已经加载完成并可重复推理的 OpenVINO YOLO 主线 segmentation 会话。"""

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
        output_names: tuple[str, str],
        input_port: Any,
        prediction_port: Any,
        proto_port: Any,
        compiled_device_name: str,
        compiled_runtime_precision: str,
    ) -> None:
        """初始化 OpenVINO segmentation 会话。"""

        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.session = session
        self.device_name = device_name
        self.input_name = input_name
        self.output_names = output_names
        self.input_port = input_port
        self.prediction_port = prediction_port
        self.proto_port = proto_port
        self.compiled_device_name = compiled_device_name
        self.compiled_runtime_precision = compiled_runtime_precision

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
    ) -> "OpenVINOYoloPrimarySegmentationRuntimeSession":
        """加载一套 OpenVINO segmentation 会话。"""

        if runtime_target.runtime_backend != "openvino":
            raise InvalidRequestError(
                f"当前 {cls.model_label} segmentation predictor 仅支持 openvino runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(
                f"当前 {cls.model_label} segmentation predictor 收到了错误的 task_type",
                details={"task_type": runtime_target.task_type},
            )

        imports = require_inference_imports()
        openvino_module = import_openvino_module()
        compiled_device_name = resolve_openvino_device_name(
            requested_device_name=runtime_target.device_name,
        )
        compile_properties = build_openvino_compile_properties(
            openvino_module=openvino_module,
            runtime_precision=runtime_target.runtime_precision,
            requested_device_name=runtime_target.device_name,
        )
        session = openvino_module.Core().compile_model(
            str(runtime_target.runtime_artifact_path),
            compiled_device_name,
            compile_properties,
        )
        input_port = session.input(0)
        prediction_port = session.output(0)
        proto_port = session.output(1)
        return cls(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            imports=imports,
            session=session,
            device_name=runtime_target.device_name,
            input_name=resolve_openvino_port_name(input_port, fallback="images"),
            output_names=(
                resolve_openvino_port_name(prediction_port, fallback="predictions"),
                resolve_openvino_port_name(proto_port, fallback="proto"),
            ),
            input_port=input_port,
            prediction_port=prediction_port,
            proto_port=proto_port,
            compiled_device_name=compiled_device_name,
            compiled_runtime_precision=resolve_openvino_compiled_runtime_precision(
                session=session,
                fallback_precision=runtime_target.runtime_precision,
            ),
        )

    def predict(self, request: SegmentationPredictionRequest) -> SegmentationPredictionExecutionResult:
        """执行一次 OpenVINO segmentation 预测。"""

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
        outputs = self.session.infer_new_request({self.input_port: input_tensor})
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        raw_prediction = outputs.get(self.prediction_port)
        if raw_prediction is None:
            raw_prediction = outputs.get(self.output_names[0])
        raw_proto = outputs.get(self.proto_port)
        if raw_proto is None:
            raw_proto = outputs.get(self.output_names[1])
        if raw_prediction is None or raw_proto is None:
            raise InvalidRequestError("openvino segmentation 推理输出缺少 prediction 或 proto")

        prediction_array, proto_array = normalize_segmentation_outputs(
            outputs=(raw_prediction, raw_proto),
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
                    dtype=resolve_openvino_port_dtype(self.input_port, fallback="float32"),
                ),
                output_specs=(
                    SegmentationRuntimeTensorSpec(
                        name=self.output_names[0],
                        shape=tuple(int(item) for item in prediction_array.shape),
                        dtype=resolve_openvino_port_dtype(self.prediction_port, fallback="float32"),
                    ),
                    SegmentationRuntimeTensorSpec(
                        name=self.output_names[1],
                        shape=tuple(int(item) for item in proto_array.shape),
                        dtype=resolve_openvino_port_dtype(self.proto_port, fallback="float32"),
                    ),
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
                    "compiled_device_name": self.compiled_device_name,
                    "compiled_runtime_precision": self.compiled_runtime_precision,
                },
            ),
        )


class TensorRTYoloPrimarySegmentationRuntimeSession:
    """已经加载完成并可重复推理的 TensorRT YOLO 主线 segmentation 会话。"""

    model_type = "yolo-primary"
    model_label = "YOLO primary"
    task_type = "segmentation"

    def __init__(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        imports: Any,
        tensorrt_module: Any,
        logger: Any,
        runtime: Any,
        engine: Any,
        context: Any,
        device_name: str,
        input_name: str,
        prediction_name: str,
        proto_name: str,
        input_dtype_name: str,
        prediction_dtype_name: str,
        proto_dtype_name: str,
        stream: Any,
        execute_start_event: Any,
        execute_end_event: Any,
        pinned_output_buffer_enabled: bool | None = None,
        pinned_output_buffer_max_bytes: int | None = None,
    ) -> None:
        """初始化 TensorRT segmentation 会话。"""

        deployment_settings = get_backend_service_settings().deployment_process_supervisor
        if pinned_output_buffer_enabled is None:
            pinned_output_buffer_enabled = bool(
                deployment_settings.tensorrt_pinned_output_buffer_enabled
            )
        if pinned_output_buffer_max_bytes is None:
            pinned_output_buffer_max_bytes = int(
                deployment_settings.tensorrt_pinned_output_buffer_max_bytes
            )
        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.tensorrt_module = tensorrt_module
        self.logger = logger
        self.runtime = runtime
        self.engine = engine
        self.context = context
        self.device_name = device_name
        self.input_name = input_name
        self.prediction_name = prediction_name
        self.proto_name = proto_name
        self.input_dtype_name = input_dtype_name
        self.prediction_dtype_name = prediction_dtype_name
        self.proto_dtype_name = proto_dtype_name
        self.stream = stream
        self.execute_start_event = execute_start_event
        self.execute_end_event = execute_end_event
        self.pinned_output_buffer_enabled = bool(pinned_output_buffer_enabled)
        self.pinned_output_buffer_max_bytes = max(0, int(pinned_output_buffer_max_bytes))
        self.input_device_ptr: int | None = None
        self.prediction_device_ptr: int | None = None
        self.proto_device_ptr: int | None = None
        self.input_capacity_bytes = 0
        self.prediction_capacity_bytes = 0
        self.proto_capacity_bytes = 0
        self.prediction_host_ptr: int | None = None
        self.proto_host_ptr: int | None = None
        self.prediction_host_capacity_bytes = 0
        self.proto_host_capacity_bytes = 0
        self.prediction_host_memory_kind = "pageable"
        self.proto_host_memory_kind = "pageable"
        self.prediction_host_array: Any | None = None
        self.proto_host_array: Any | None = None

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        pinned_output_buffer_enabled: bool | None = None,
        pinned_output_buffer_max_bytes: int | None = None,
    ) -> "TensorRTYoloPrimarySegmentationRuntimeSession":
        """加载一套 TensorRT segmentation 会话。"""

        if runtime_target.runtime_backend != "tensorrt":
            raise InvalidRequestError(
                f"当前 {cls.model_label} segmentation predictor 仅支持 tensorrt runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(
                f"当前 {cls.model_label} segmentation predictor 收到了错误的 task_type",
                details={"task_type": runtime_target.task_type},
            )

        imports = require_cuda_inference_imports()
        tensorrt_module = import_tensorrt_module()
        device_name = resolve_cuda_runtime_device_name(
            cudart_module=imports.cudart,
            requested_device_name=runtime_target.device_name,
        )
        ensure_cuda_success(
            imports.cudart.cudaSetDevice(resolve_cuda_device_index(device_name)),
            operation_name="TensorRT segmentation runtime 切换 CUDA device",
            details={"device_name": device_name},
        )
        logger = get_tensorrt_logger(
            tensorrt_module=tensorrt_module,
            severity=tensorrt_module.Logger.WARNING,
        )
        runtime = tensorrt_module.Runtime(logger)
        engine = runtime.deserialize_cuda_engine(runtime_target.runtime_artifact_path.read_bytes())
        if engine is None:
            raise ServiceConfigurationError(
                "TensorRT segmentation engine 反序列化失败",
                details={"model_build_id": runtime_target.model_build_id},
            )
        context = engine.create_execution_context()
        if context is None:
            raise ServiceConfigurationError(
                "TensorRT segmentation engine 无法创建 execution context",
                details={"model_build_id": runtime_target.model_build_id},
            )
        stream = ensure_cuda_success(
            imports.cudart.cudaStreamCreate(),
            operation_name="TensorRT segmentation runtime 创建复用 CUDA stream",
            details={"device_name": device_name},
        )[0]
        execute_start_event = ensure_cuda_success(
            imports.cudart.cudaEventCreate(),
            operation_name="TensorRT segmentation runtime 创建执行起点 event",
            details={"device_name": device_name},
        )[0]
        execute_end_event = ensure_cuda_success(
            imports.cudart.cudaEventCreate(),
            operation_name="TensorRT segmentation runtime 创建执行终点 event",
            details={"device_name": device_name},
        )[0]
        input_name = resolve_tensorrt_io_tensor_name(
            engine=engine,
            tensorrt_module=tensorrt_module,
            io_mode=tensorrt_module.TensorIOMode.INPUT,
            fallback="images",
        )
        prediction_name = resolve_tensorrt_io_tensor_name(
            engine=engine,
            tensorrt_module=tensorrt_module,
            io_mode=tensorrt_module.TensorIOMode.OUTPUT,
            fallback="predictions",
        )
        output_names = _list_tensorrt_output_names(engine, tensorrt_module=tensorrt_module)
        if len(output_names) < 1:
            raise ServiceConfigurationError("TensorRT segmentation engine 缺少输出")
        prediction_name = output_names[0] if any(name == "predictions" for name in output_names) else output_names[0]
        proto_name = (
            output_names[1]
            if len(output_names) >= 2
            else _resolve_proto_output_name(
                engine=engine,
                tensorrt_module=tensorrt_module,
                exclude_name=prediction_name,
                fallback="proto",
            )
        )
        return cls(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            imports=imports,
            tensorrt_module=tensorrt_module,
            logger=logger,
            runtime=runtime,
            engine=engine,
            context=context,
            device_name=device_name,
            input_name=input_name,
            prediction_name=prediction_name,
            proto_name=proto_name,
            input_dtype_name=resolve_tensorrt_dtype_name(
                tensorrt_module=tensorrt_module,
                tensor_dtype=engine.get_tensor_dtype(input_name),
                fallback="float32",
            ),
            prediction_dtype_name=resolve_tensorrt_dtype_name(
                tensorrt_module=tensorrt_module,
                tensor_dtype=engine.get_tensor_dtype(prediction_name),
                fallback="float32",
            ),
            proto_dtype_name=resolve_tensorrt_dtype_name(
                tensorrt_module=tensorrt_module,
                tensor_dtype=engine.get_tensor_dtype(proto_name),
                fallback="float32",
            ),
            stream=stream,
            execute_start_event=execute_start_event,
            execute_end_event=execute_end_event,
            pinned_output_buffer_enabled=pinned_output_buffer_enabled,
            pinned_output_buffer_max_bytes=pinned_output_buffer_max_bytes,
        )

    def predict(self, request: SegmentationPredictionRequest) -> SegmentationPredictionExecutionResult:
        """执行一次 TensorRT segmentation 预测。"""

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
        input_array = self.imports.np.expand_dims(input_tensor, axis=0).astype(
            resolve_numpy_dtype(np_module=self.imports.np, dtype_name=self.input_dtype_name),
            copy=False,
        )
        requested_input_shape = tuple(int(dim) for dim in input_array.shape)
        preprocess_ms = round((perf_counter() - preprocess_started_at) * 1000, 3)

        infer_started_at = perf_counter()
        ensure_cuda_success(
            self.imports.cudart.cudaSetDevice(resolve_cuda_device_index(self.device_name)),
            operation_name="TensorRT segmentation runtime 绑定 CUDA device",
            details={"device_name": self.device_name},
        )
        engine_input_shape = normalize_tensor_shape(self.engine.get_tensor_shape(self.input_name))
        if any(dim < 0 for dim in engine_input_shape):
            shape_set_result = self.context.set_input_shape(self.input_name, requested_input_shape)
            if shape_set_result is not True:
                raise ServiceConfigurationError(
                    "TensorRT segmentation execution context 设置输入 shape 失败",
                    details={"input_name": self.input_name, "requested_input_shape": list(requested_input_shape)},
                )
        elif engine_input_shape != requested_input_shape:
            raise InvalidRequestError(
                "TensorRT segmentation engine 输入尺寸与 runtime input_size 不一致",
                details={
                    "engine_input_shape": list(engine_input_shape),
                    "requested_input_shape": list(requested_input_shape),
                },
            )
        resolved_prediction_shape = normalize_tensor_shape(self.context.get_tensor_shape(self.prediction_name))
        resolved_proto_shape = normalize_tensor_shape(self.context.get_tensor_shape(self.proto_name))
        if not resolved_prediction_shape or any(dim <= 0 for dim in resolved_prediction_shape):
            raise ServiceConfigurationError(
                "TensorRT segmentation execution context 返回了无效 prediction shape",
                details={"output_name": self.prediction_name, "output_shape": list(resolved_prediction_shape)},
            )
        if not resolved_proto_shape or any(dim <= 0 for dim in resolved_proto_shape):
            raise ServiceConfigurationError(
                "TensorRT segmentation execution context 返回了无效 proto shape",
                details={"output_name": self.proto_name, "output_shape": list(resolved_proto_shape)},
            )

        prediction_array, proto_array = self._ensure_io_buffers(
            input_array=input_array,
            resolved_prediction_shape=resolved_prediction_shape,
            resolved_proto_shape=resolved_proto_shape,
        )
        ensure_cuda_success(
            self.imports.cudart.cudaMemcpyAsync(
                self.input_device_ptr,
                int(input_array.ctypes.data),
                int(input_array.nbytes),
                self.imports.cudart.cudaMemcpyKind.cudaMemcpyHostToDevice,
                self.stream,
            ),
            operation_name="TensorRT segmentation runtime 拷贝输入到显存",
            details={"input_name": self.input_name, "byte_size": int(input_array.nbytes)},
        )
        if self.context.set_tensor_address(self.input_name, int(self.input_device_ptr)) is not True:
            raise ServiceConfigurationError(
                "TensorRT segmentation execution context 绑定输入张量失败",
                details={"input_name": self.input_name},
            )
        if self.context.set_tensor_address(self.prediction_name, int(self.prediction_device_ptr)) is not True:
            raise ServiceConfigurationError(
                "TensorRT segmentation execution context 绑定 prediction 输出张量失败",
                details={"output_name": self.prediction_name},
            )
        if self.context.set_tensor_address(self.proto_name, int(self.proto_device_ptr)) is not True:
            raise ServiceConfigurationError(
                "TensorRT segmentation execution context 绑定 proto 输出张量失败",
                details={"output_name": self.proto_name},
            )
        ensure_cuda_success(
            self.imports.cudart.cudaEventRecord(self.execute_start_event, self.stream),
            operation_name="TensorRT segmentation runtime 记录执行起点 event",
            details={"device_name": self.device_name},
        )
        if self.context.execute_async_v3(stream_handle=self.stream) is not True:
            raise ServiceConfigurationError(
                "TensorRT segmentation execution context 执行推理失败",
                details={"model_build_id": self.runtime_target.model_build_id},
            )
        ensure_cuda_success(
            self.imports.cudart.cudaEventRecord(self.execute_end_event, self.stream),
            operation_name="TensorRT segmentation runtime 记录执行终点 event",
            details={"device_name": self.device_name},
        )
        ensure_cuda_success(
            self.imports.cudart.cudaMemcpyAsync(
                int(prediction_array.ctypes.data),
                self.prediction_device_ptr,
                int(prediction_array.nbytes),
                self.imports.cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost,
                self.stream,
            ),
            operation_name="TensorRT segmentation runtime 拷贝 prediction 到主存",
            details={"output_name": self.prediction_name, "byte_size": int(prediction_array.nbytes)},
        )
        ensure_cuda_success(
            self.imports.cudart.cudaMemcpyAsync(
                int(proto_array.ctypes.data),
                self.proto_device_ptr,
                int(proto_array.nbytes),
                self.imports.cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost,
                self.stream,
            ),
            operation_name="TensorRT segmentation runtime 拷贝 proto 到主存",
            details={"output_name": self.proto_name, "byte_size": int(proto_array.nbytes)},
        )
        ensure_cuda_success(
            self.imports.cudart.cudaStreamSynchronize(self.stream),
            operation_name="TensorRT segmentation runtime 同步 CUDA stream",
            details={"device_name": self.device_name},
        )
        infer_execute_gpu_ms = measure_cuda_event_elapsed_ms(
            cudart_module=self.imports.cudart,
            start_event=self.execute_start_event,
            end_event=self.execute_end_event,
            device_name=self.device_name,
        )
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        normalized_prediction_array, normalized_proto_array = normalize_segmentation_outputs(
            outputs=(prediction_array, proto_array),
            np_module=self.imports.np,
        )
        postprocess_started_at = perf_counter()
        instances = _build_segmentation_instances(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            prediction_array=normalized_prediction_array,
            proto_array=normalized_proto_array,
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
                    shape=requested_input_shape,
                    dtype=self.input_dtype_name,
                ),
                output_specs=(
                    SegmentationRuntimeTensorSpec(
                        name=self.prediction_name,
                        shape=resolved_prediction_shape,
                        dtype=self.prediction_dtype_name,
                    ),
                    SegmentationRuntimeTensorSpec(
                        name=self.proto_name,
                        shape=resolved_proto_shape,
                        dtype=self.proto_dtype_name,
                    ),
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
                    "infer_execute_gpu_ms": infer_execute_gpu_ms,
                    **self.describe_memory_usage(),
                },
            ),
        )

    def close(self) -> None:
        """释放 TensorRT segmentation session 持有的 CUDA 资源。"""

        try:
            ensure_cuda_success(
                self.imports.cudart.cudaSetDevice(resolve_cuda_device_index(self.device_name)),
                operation_name="TensorRT segmentation runtime 清理前绑定 CUDA device",
                details={"device_name": self.device_name},
            )
        except Exception:
            return
        if self.input_device_ptr is not None:
            self.imports.cudart.cudaFree(self.input_device_ptr)
            self.input_device_ptr = None
            self.input_capacity_bytes = 0
        if self.prediction_device_ptr is not None:
            self.imports.cudart.cudaFree(self.prediction_device_ptr)
            self.prediction_device_ptr = None
            self.prediction_capacity_bytes = 0
        if self.proto_device_ptr is not None:
            self.imports.cudart.cudaFree(self.proto_device_ptr)
            self.proto_device_ptr = None
            self.proto_capacity_bytes = 0
        if self.prediction_host_ptr is not None:
            self.imports.cudart.cudaFreeHost(self.prediction_host_ptr)
            self.prediction_host_ptr = None
            self.prediction_host_capacity_bytes = 0
            self.prediction_host_array = None
        if self.proto_host_ptr is not None:
            self.imports.cudart.cudaFreeHost(self.proto_host_ptr)
            self.proto_host_ptr = None
            self.proto_host_capacity_bytes = 0
            self.proto_host_array = None
        self.prediction_host_memory_kind = "pageable"
        self.proto_host_memory_kind = "pageable"
        if self.stream is not None:
            self.imports.cudart.cudaStreamDestroy(self.stream)
            self.stream = None
        if self.execute_start_event is not None:
            self.imports.cudart.cudaEventDestroy(self.execute_start_event)
            self.execute_start_event = None
        if self.execute_end_event is not None:
            self.imports.cudart.cudaEventDestroy(self.execute_end_event)
            self.execute_end_event = None
        self.prediction_host_array = None
        self.proto_host_array = None

    def describe_memory_usage(self) -> dict[str, object]:
        """返回当前 TensorRT segmentation session 的输出 host buffer 占用快照。"""

        prediction_host_buffer_bytes = 0
        if self.prediction_host_array is not None:
            prediction_host_buffer_bytes = int(self.prediction_host_array.nbytes)
        prediction_host_pinned_bytes = 0
        if self.prediction_host_memory_kind == "pinned" and self.prediction_host_ptr is not None:
            prediction_host_pinned_bytes = int(self.prediction_host_capacity_bytes)
        proto_host_buffer_bytes = 0
        if self.proto_host_array is not None:
            proto_host_buffer_bytes = int(self.proto_host_array.nbytes)
        proto_host_pinned_bytes = 0
        if self.proto_host_memory_kind == "pinned" and self.proto_host_ptr is not None:
            proto_host_pinned_bytes = int(self.proto_host_capacity_bytes)
        return {
            "prediction_host_memory_kind": self.prediction_host_memory_kind,
            "prediction_host_buffer_bytes": prediction_host_buffer_bytes,
            "prediction_host_pinned_bytes": prediction_host_pinned_bytes,
            "proto_host_memory_kind": self.proto_host_memory_kind,
            "proto_host_buffer_bytes": proto_host_buffer_bytes,
            "proto_host_pinned_bytes": proto_host_pinned_bytes,
            "output_host_pinned_enabled": self.pinned_output_buffer_enabled,
            "output_host_pinned_max_bytes": self.pinned_output_buffer_max_bytes,
        }

    def _ensure_io_buffers(
        self,
        *,
        input_array: Any,
        resolved_prediction_shape: tuple[int, ...],
        resolved_proto_shape: tuple[int, ...],
    ) -> tuple[Any, Any]:
        """按当前输入输出尺寸复用或扩容 TensorRT I/O 缓冲。"""

        prediction_dtype = resolve_numpy_dtype(
            np_module=self.imports.np,
            dtype_name=self.prediction_dtype_name,
        )
        proto_dtype = resolve_numpy_dtype(
            np_module=self.imports.np,
            dtype_name=self.proto_dtype_name,
        )
        input_nbytes = int(input_array.nbytes)
        prediction_nbytes = int(self.imports.np.empty(resolved_prediction_shape, dtype=prediction_dtype).nbytes)
        proto_nbytes = int(self.imports.np.empty(resolved_proto_shape, dtype=proto_dtype).nbytes)

        if self.input_device_ptr is None or input_nbytes > self.input_capacity_bytes:
            if self.input_device_ptr is not None:
                self.imports.cudart.cudaFree(self.input_device_ptr)
            self.input_device_ptr = ensure_cuda_success(
                self.imports.cudart.cudaMalloc(input_nbytes),
                operation_name="TensorRT segmentation runtime 分配复用输入显存",
                details={"byte_size": input_nbytes},
            )[0]
            self.input_capacity_bytes = input_nbytes

        if self.prediction_device_ptr is None or prediction_nbytes > self.prediction_capacity_bytes:
            if self.prediction_device_ptr is not None:
                self.imports.cudart.cudaFree(self.prediction_device_ptr)
            self.prediction_device_ptr = ensure_cuda_success(
                self.imports.cudart.cudaMalloc(prediction_nbytes),
                operation_name="TensorRT segmentation runtime 分配复用 prediction 输出显存",
                details={"byte_size": prediction_nbytes},
            )[0]
            self.prediction_capacity_bytes = prediction_nbytes

        if self.proto_device_ptr is None or proto_nbytes > self.proto_capacity_bytes:
            if self.proto_device_ptr is not None:
                self.imports.cudart.cudaFree(self.proto_device_ptr)
            self.proto_device_ptr = ensure_cuda_success(
                self.imports.cudart.cudaMalloc(proto_nbytes),
                operation_name="TensorRT segmentation runtime 分配复用 proto 输出显存",
                details={"byte_size": proto_nbytes},
            )[0]
            self.proto_capacity_bytes = proto_nbytes

        prediction_array = self._ensure_host_buffer(
            nbytes=prediction_nbytes,
            resolved_shape=resolved_prediction_shape,
            dtype=prediction_dtype,
            host_ptr_attr="prediction_host_ptr",
            host_capacity_attr="prediction_host_capacity_bytes",
            host_array_attr="prediction_host_array",
            host_memory_kind_attr="prediction_host_memory_kind",
            label="prediction",
        )
        proto_array = self._ensure_host_buffer(
            nbytes=proto_nbytes,
            resolved_shape=resolved_proto_shape,
            dtype=proto_dtype,
            host_ptr_attr="proto_host_ptr",
            host_capacity_attr="proto_host_capacity_bytes",
            host_array_attr="proto_host_array",
            host_memory_kind_attr="proto_host_memory_kind",
            label="proto",
        )
        return prediction_array, proto_array

    def _ensure_host_buffer(
        self,
        *,
        nbytes: int,
        resolved_shape: tuple[int, ...],
        dtype: Any,
        host_ptr_attr: str,
        host_capacity_attr: str,
        host_array_attr: str,
        host_memory_kind_attr: str,
        label: str,
    ) -> Any:
        """为单个输出分配或复用主存 host buffer。"""

        host_ptr = getattr(self, host_ptr_attr, None)
        host_capacity = getattr(self, host_capacity_attr, 0)
        host_array = getattr(self, host_array_attr, None)
        host_memory_kind = getattr(self, host_memory_kind_attr, "pageable")

        if self._should_use_pinned_output_buffer(nbytes):
            if host_ptr is None or nbytes > host_capacity:
                if host_ptr is not None:
                    self.imports.cudart.cudaFreeHost(host_ptr)
                host_ptr = ensure_cuda_success(
                    self.imports.cudart.cudaMallocHost(nbytes),
                    operation_name=f"TensorRT segmentation runtime 分配 pinned {label} 输出主存",
                    details={"byte_size": nbytes},
                )[0]
                setattr(self, host_ptr_attr, host_ptr)
                setattr(self, host_capacity_attr, nbytes)
                setattr(self, host_array_attr, None)
                host_array = None
                host_memory_kind = "pageable"
            if (
                host_array is None
                or host_memory_kind != "pinned"
                or tuple(int(dim) for dim in host_array.shape) != resolved_shape
                or host_array.dtype != dtype
            ):
                host_array = self.imports.np.ctypeslib.as_array(
                    (self.imports.np.ctypeslib.as_ctypes_type(dtype) * int(self.imports.np.prod(resolved_shape))).from_address(int(host_ptr))
                ).reshape(resolved_shape)
            host_memory_kind = "pinned"
        else:
            if host_ptr is not None:
                self.imports.cudart.cudaFreeHost(host_ptr)
                host_ptr = None
                setattr(self, host_ptr_attr, None)
                setattr(self, host_capacity_attr, 0)
                setattr(self, host_array_attr, None)
                host_array = None
                host_memory_kind = "pageable"
            if (
                host_array is None
                or host_memory_kind != "pageable"
                or tuple(int(dim) for dim in host_array.shape) != resolved_shape
                or host_array.dtype != dtype
            ):
                host_array = self.imports.np.empty(resolved_shape, dtype=dtype)
            host_memory_kind = "pageable"

        setattr(self, host_array_attr, host_array)
        setattr(self, host_memory_kind_attr, host_memory_kind)
        return host_array

    def _should_use_pinned_output_buffer(self, output_nbytes: int) -> bool:
        """判断当前输出 host buffer 是否应该使用 pinned memory。"""

        if not self.pinned_output_buffer_enabled:
            return False
        if output_nbytes <= 0:
            return False
        return output_nbytes <= self.pinned_output_buffer_max_bytes


def _list_tensorrt_output_names(engine: Any, *, tensorrt_module: Any) -> list[str]:
    """列出 TensorRT engine 的所有输出张量名称。"""

    names: list[str] = []
    for index in range(int(engine.num_io_tensors)):
        name = engine.get_tensor_name(index)
        if engine.get_tensor_mode(name) == tensorrt_module.TensorIOMode.OUTPUT:
            names.append(name)
    return names


def _resolve_proto_output_name(
    *,
    engine: Any,
    tensorrt_module: Any,
    exclude_name: str,
    fallback: str,
) -> str:
    """在 TensorRT engine 输出中解析 proto 张量名称。"""

    fallback_name = fallback
    for index in range(int(engine.num_io_tensors)):
        name = engine.get_tensor_name(index)
        if engine.get_tensor_mode(name) == tensorrt_module.TensorIOMode.OUTPUT and name != exclude_name:
            return name
    if fallback_name != exclude_name:
        return fallback_name
    raise ServiceConfigurationError(
        "TensorRT segmentation engine 缺少 proto 输出张量",
        details={"exclude_name": exclude_name},
    )


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

    common_instances = build_segmentation_postprocess_instances(
        cv2_module=cv2_module,
        np_module=np_module,
        prediction_array=prediction_array,
        proto_array=proto_array,
        labels=labels,
        score_threshold=score_threshold,
        nms_threshold=0.65,
        mask_threshold=mask_threshold,
        resize_ratio=resize_ratio,
        image_width=image_width,
        image_height=image_height,
        input_size=input_size,
        nms_indices_func=batched_nms_indices,
    )
    return tuple(
        SegmentationPredictionInstance(
            bbox_xyxy=instance.bbox_xyxy,
            score=instance.score,
            class_id=instance.class_id,
            class_name=instance.class_name,
            segments=instance.segments,
            mask_area=instance.mask_area,
        )
        for instance in common_instances
    )


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

    normalized_model_type = normalize_optional_platform_model_type(model_type)
    if not normalized_model_type or normalized_model_type == "yolo-primary":
        raise ServiceConfigurationError(
            f"当前 {model_label} segmentation predictor 缺少正式 model_type 配置",
            details={"model_type": model_type},
        )
    return normalized_model_type
