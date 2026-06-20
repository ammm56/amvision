"""YOLO 主线 detection 单图推理实现。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.model_type_support import (
    normalize_optional_platform_model_type,
)
from backend.service.application.models.detection_postprocess import (
    DEFAULT_END2END_MAX_DETECTIONS,
    DETECTION_POSTPROCESS_MODE_END2END_TOPK,
    DETECTION_POSTPROCESS_MODE_NMS,
    postprocess_detection_prediction_array,
)
from backend.service.application.models.yolo_primary_detection_model import (
    build_yolo_primary_detection_model,
    load_yolo_primary_checkpoint,
)
from backend.service.application.models.yolo_primary_model_configs import (
    get_yolo_primary_model_config,
)
from backend.service.application.models.yolo_primary_detection_training import (
    _require_training_imports,
)
from backend.service.application.models.yolov8_core.postprocess import (
    build_yolov8_detection_records,
    render_yolov8_detection_preview_image,
)
from backend.service.application.runtime.contracts.detection import (
    DetectionPredictionDetection,
    DetectionPredictionExecutionResult,
    DetectionPredictionRequest,
    DetectionRuntimeSessionInfo,
    DetectionRuntimeTensorSpec,
)
from backend.service.application.runtime.support.detection import (
    DEFAULT_DETECTION_NMS_THRESHOLD,
    OpenVINODetectionRuntimeSessionBase,
    TensorRTDetectionRuntimeSessionBase,
    build_openvino_compile_properties,
    enable_pytorch_cuda_inference_fast_path,
    ensure_cuda_success,
    get_tensorrt_logger,
    import_onnxruntime_module,
    import_openvino_module,
    import_tensorrt_module,
    load_prediction_image,
    measure_cuda_event_elapsed_ms,
    measure_stage_elapsed_ms,
    normalize_onnxruntime_outputs,
    normalize_openvino_outputs,
    normalize_tensor_shape,
    normalize_tensorrt_outputs,
    prediction_to_numpy_array,
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
    resolve_probability,
    resolve_tensorrt_dtype_name,
    resolve_tensorrt_io_tensor_name,
)
from backend.service.application.runtime.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class PyTorchYoloPrimaryRuntimeSession:
    """已经加载完成并可重复推理的 PyTorch YOLO 主线会话。"""

    model_type = "yolo-primary"
    model_label = "YOLO primary"

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
        """初始化 PyTorch YOLO 主线会话。"""

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
    ) -> "PyTorchYoloPrimaryRuntimeSession":
        """加载一套 PyTorch YOLO 主线会话。"""

        if runtime_target.runtime_backend != "pytorch":
            raise InvalidRequestError(
                f"当前 {cls.model_label} predictor 仅支持 pytorch runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
            )

        imports = _require_training_imports()
        model = build_yolo_primary_detection_model(
            model_type=_require_primary_model_type(cls.model_type, cls.model_label),
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

    def predict(self, request: DetectionPredictionRequest) -> DetectionPredictionExecutionResult:
        """执行一次 PyTorch YOLO 主线预测。"""

        decode_started_at = perf_counter()
        image = load_prediction_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = measure_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=decode_started_at,
        )

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
        preprocess_ms = measure_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=preprocess_started_at,
        )

        nms_threshold = resolve_probability(
            value=request.extra_options.get("nms_threshold"),
            field_name="nms_threshold",
            default=DEFAULT_DETECTION_NMS_THRESHOLD,
        )

        infer_started_at = perf_counter()
        inference_mode = getattr(self.imports.torch, "inference_mode", None)
        if callable(inference_mode):
            with inference_mode():
                outputs = self.model(input_tensor)
        else:
            with self.imports.torch.no_grad():
                outputs = self.model(input_tensor)
        infer_ms = measure_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=infer_started_at,
        )

        image_height = int(image.shape[0])
        image_width = int(image.shape[1])

        postprocess_started_at = perf_counter()
        prediction_array = prediction_to_numpy_array(
            prediction_tensor=outputs,
            np_module=self.imports.np,
        )
        
        postprocess_mode, max_detections = _resolve_yolo_primary_postprocess_strategy(
            model_type=self.runtime_target.model_type,
            is_end2end=bool(getattr(self.model, "end2end", False)),
        )
        detections = _build_yolo_primary_detection_records(
            model_type=self.runtime_target.model_type,
            np_module=self.imports.np,
            prediction_array=prediction_array,
            labels=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            nms_threshold=nms_threshold,
            resize_ratio=resize_ratio,
            image_width=image_width,
            image_height=image_height,
            postprocess_mode=postprocess_mode,
            max_detections=max_detections,
        )
        postprocess_ms = measure_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=postprocess_started_at,
        )
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = None
        if request.save_result_image:
            preview_image_bytes = _render_yolo_primary_detection_preview_image(
                model_type=self.runtime_target.model_type,
                cv2_module=self.imports.cv2,
                image=image,
                detections=detections,
            )

        return DetectionPredictionExecutionResult(
            detections=detections,
            latency_ms=round(latency_ms, 3),
            image_width=image_width,
            image_height=image_height,
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=DetectionRuntimeSessionInfo(
                backend_name=self.runtime_target.runtime_backend,
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=DetectionRuntimeTensorSpec(
                    name="images",
                    shape=(1, 3, self.runtime_target.input_size[0], self.runtime_target.input_size[1]),
                    dtype="float16" if self.runtime_precision == "fp16" else "float32",
                ),
                output_spec=DetectionRuntimeTensorSpec(
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
                    "nms_threshold": (
                        nms_threshold
                        if postprocess_mode == DETECTION_POSTPROCESS_MODE_NMS
                        else None
                    ),
                    "postprocess_mode": postprocess_mode,
                    "max_detections": max_detections,
                    "class_count": len(self.runtime_target.labels),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                },
            ),
        )


class OnnxRuntimeYoloPrimaryRuntimeSession:
    """已经加载完成并可重复推理的 ONNXRuntime YOLO 主线会话。"""

    model_type = "yolo-primary"
    model_label = "YOLO primary"

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
        """初始化 ONNXRuntime YOLO 主线会话。"""

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
    ) -> "OnnxRuntimeYoloPrimaryRuntimeSession":
        """加载一套 ONNXRuntime YOLO 主线会话。"""

        if runtime_target.runtime_backend != "onnxruntime":
            raise InvalidRequestError(
                f"当前 {cls.model_label} predictor 仅支持 onnxruntime runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
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
            output_name=session.get_outputs()[0].name,
        )

    def predict(self, request: DetectionPredictionRequest) -> DetectionPredictionExecutionResult:
        """执行一次 ONNXRuntime YOLO 主线预测。"""

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

        nms_threshold = resolve_probability(
            value=request.extra_options.get("nms_threshold"),
            field_name="nms_threshold",
            default=DEFAULT_DETECTION_NMS_THRESHOLD,
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
        prediction_array = normalize_onnxruntime_outputs(outputs=outputs, imports=self.imports)
        postprocess_mode, max_detections = _resolve_yolo_primary_postprocess_strategy(
            model_type=self.runtime_target.model_type,
        )
        detections = _build_yolo_primary_detection_records(
            model_type=self.runtime_target.model_type,
            np_module=self.imports.np,
            prediction_array=prediction_array,
            labels=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            nms_threshold=nms_threshold,
            resize_ratio=resize_ratio,
            image_width=image_width,
            image_height=image_height,
            postprocess_mode=postprocess_mode,
            max_detections=max_detections,
        )
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = None
        if request.save_result_image:
            preview_image_bytes = _render_yolo_primary_detection_preview_image(
                model_type=self.runtime_target.model_type,
                cv2_module=self.imports.cv2,
                image=image,
                detections=detections,
            )

        return DetectionPredictionExecutionResult(
            detections=detections,
            latency_ms=round(latency_ms, 3),
            image_width=image_width,
            image_height=image_height,
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=DetectionRuntimeSessionInfo(
                backend_name=self.runtime_target.runtime_backend,
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=DetectionRuntimeTensorSpec(
                    name=self.input_name,
                    shape=(1, 3, self.runtime_target.input_size[0], self.runtime_target.input_size[1]),
                    dtype="float32",
                ),
                output_spec=DetectionRuntimeTensorSpec(
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
                    "nms_threshold": (
                        nms_threshold
                        if postprocess_mode == DETECTION_POSTPROCESS_MODE_NMS
                        else None
                    ),
                    "postprocess_mode": postprocess_mode,
                    "max_detections": max_detections,
                    "class_count": len(self.runtime_target.labels),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                    "provider_names": list(self.session.get_providers()),
                },
            ),
        )


class OpenVINOYoloPrimaryRuntimeSession(OpenVINODetectionRuntimeSessionBase):
    """已经加载完成并可重复推理的 OpenVINO YOLO 主线会话。"""

    model_type = "yolo-primary"
    model_label = "YOLO primary"

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
    ) -> "OpenVINOYoloPrimaryRuntimeSession":
        """加载一套 OpenVINO YOLO 主线会话。"""

        if runtime_target.runtime_backend != "openvino":
            raise InvalidRequestError(
                f"当前 {cls.model_label} predictor 仅支持 openvino runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
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
        output_port = session.output(0)
        return cls(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            imports=imports,
            session=session,
            device_name=runtime_target.device_name,
            input_name=resolve_openvino_port_name(input_port, fallback="images"),
            output_name=resolve_openvino_port_name(output_port, fallback="predictions"),
            input_port=input_port,
            output_port=output_port,
            compiled_device_name=compiled_device_name,
            compiled_runtime_precision=resolve_openvino_compiled_runtime_precision(
                session=session,
                fallback_precision=runtime_target.runtime_precision,
            ),
        )

    def predict(self, request: DetectionPredictionRequest) -> DetectionPredictionExecutionResult:
        """执行一次 OpenVINO YOLO 主线预测。"""

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
        input_tensor = self.imports.np.expand_dims(input_tensor, axis=0).astype(
            self.imports.np.float32,
            copy=False,
        )
        preprocess_ms = round((perf_counter() - preprocess_started_at) * 1000, 3)

        nms_threshold = resolve_probability(
            value=request.extra_options.get("nms_threshold"),
            field_name="nms_threshold",
            default=DEFAULT_DETECTION_NMS_THRESHOLD,
        )

        infer_started_at = perf_counter()
        outputs = self.session.infer_new_request({self.input_port: input_tensor})
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        image_height = int(image.shape[0])
        image_width = int(image.shape[1])

        postprocess_started_at = perf_counter()
        prediction_array = normalize_openvino_outputs(
            outputs=outputs,
            output_port=self.output_port,
            output_name=self.output_name,
            imports=self.imports,
        )
        postprocess_mode, max_detections = _resolve_yolo_primary_postprocess_strategy(
            model_type=self.runtime_target.model_type,
        )
        detections = _build_yolo_primary_detection_records(
            model_type=self.runtime_target.model_type,
            np_module=self.imports.np,
            prediction_array=prediction_array,
            labels=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            nms_threshold=nms_threshold,
            resize_ratio=resize_ratio,
            image_width=image_width,
            image_height=image_height,
            postprocess_mode=postprocess_mode,
            max_detections=max_detections,
        )
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = None
        if request.save_result_image:
            preview_image_bytes = _render_yolo_primary_detection_preview_image(
                model_type=self.runtime_target.model_type,
                cv2_module=self.imports.cv2,
                image=image,
                detections=detections,
            )

        return DetectionPredictionExecutionResult(
            detections=detections,
            latency_ms=round(latency_ms, 3),
            image_width=image_width,
            image_height=image_height,
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=DetectionRuntimeSessionInfo(
                backend_name=self.runtime_target.runtime_backend,
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=DetectionRuntimeTensorSpec(
                    name=self.input_name,
                    shape=(1, 3, self.runtime_target.input_size[0], self.runtime_target.input_size[1]),
                    dtype=resolve_openvino_port_dtype(self.input_port, fallback="float32"),
                ),
                output_spec=DetectionRuntimeTensorSpec(
                    name=self.output_name,
                    shape=(-1, 4 + len(self.runtime_target.labels)),
                    dtype=resolve_openvino_port_dtype(self.output_port, fallback="float32"),
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
                    "nms_threshold": (
                        nms_threshold
                        if postprocess_mode == DETECTION_POSTPROCESS_MODE_NMS
                        else None
                    ),
                    "postprocess_mode": postprocess_mode,
                    "max_detections": max_detections,
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


class TensorRTYoloPrimaryRuntimeSession(TensorRTDetectionRuntimeSessionBase):
    """已经加载完成并可重复推理的 TensorRT YOLO 主线会话。"""

    model_type = "yolo-primary"
    model_label = "YOLO primary"

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        pinned_output_buffer_enabled: bool | None = None,
        pinned_output_buffer_max_bytes: int | None = None,
    ) -> "TensorRTYoloPrimaryRuntimeSession":
        """加载一套 TensorRT YOLO 主线会话。"""

        if runtime_target.runtime_backend != "tensorrt":
            raise InvalidRequestError(
                f"当前 {cls.model_label} predictor 仅支持 tensorrt runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
            )

        imports = require_cuda_inference_imports()
        tensorrt_module = import_tensorrt_module()
        device_name = resolve_cuda_runtime_device_name(
            cudart_module=imports.cudart,
            requested_device_name=runtime_target.device_name,
        )
        ensure_cuda_success(
            imports.cudart.cudaSetDevice(resolve_cuda_device_index(device_name)),
            operation_name="TensorRT runtime 切换 CUDA device",
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
                "TensorRT engine 反序列化失败",
                details={
                    "runtime_artifact_path": str(runtime_target.runtime_artifact_path),
                    "model_build_id": runtime_target.model_build_id,
                },
            )
        context = engine.create_execution_context()
        if context is None:
            raise ServiceConfigurationError(
                "TensorRT engine 无法创建 execution context",
                details={"model_build_id": runtime_target.model_build_id},
            )
        stream = ensure_cuda_success(
            imports.cudart.cudaStreamCreate(),
            operation_name="TensorRT runtime 创建复用 CUDA stream",
            details={"device_name": device_name},
        )[0]
        execute_start_event = ensure_cuda_success(
            imports.cudart.cudaEventCreate(),
            operation_name="TensorRT runtime 创建执行起点 event",
            details={"device_name": device_name},
        )[0]
        execute_end_event = ensure_cuda_success(
            imports.cudart.cudaEventCreate(),
            operation_name="TensorRT runtime 创建执行终点 event",
            details={"device_name": device_name},
        )[0]
        input_name = resolve_tensorrt_io_tensor_name(
            engine=engine,
            tensorrt_module=tensorrt_module,
            io_mode=tensorrt_module.TensorIOMode.INPUT,
            fallback="images",
        )
        output_name = resolve_tensorrt_io_tensor_name(
            engine=engine,
            tensorrt_module=tensorrt_module,
            io_mode=tensorrt_module.TensorIOMode.OUTPUT,
            fallback="predictions",
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
            output_name=output_name,
            input_dtype_name=resolve_tensorrt_dtype_name(
                tensorrt_module=tensorrt_module,
                tensor_dtype=engine.get_tensor_dtype(input_name),
                fallback="float32",
            ),
            output_dtype_name=resolve_tensorrt_dtype_name(
                tensorrt_module=tensorrt_module,
                tensor_dtype=engine.get_tensor_dtype(output_name),
                fallback="float32",
            ),
            stream=stream,
            execute_start_event=execute_start_event,
            execute_end_event=execute_end_event,
            pinned_output_buffer_enabled=pinned_output_buffer_enabled,
            pinned_output_buffer_max_bytes=pinned_output_buffer_max_bytes,
        )

    def predict(self, request: DetectionPredictionRequest) -> DetectionPredictionExecutionResult:
        """执行一次 TensorRT YOLO 主线预测。"""

        decode_started_at = perf_counter()
        image = load_prediction_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = measure_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=decode_started_at,
        )

        preprocess_started_at = perf_counter()
        input_tensor, resize_ratio = preprocess_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            image=image,
            input_size=self.runtime_target.input_size,
        )
        input_array = self.imports.np.expand_dims(input_tensor, axis=0).astype(
            resolve_numpy_dtype(
                np_module=self.imports.np,
                dtype_name=self.input_dtype_name,
            ),
            copy=False,
        )
        requested_input_shape = tuple(int(dim) for dim in input_array.shape)
        preprocess_ms = round((perf_counter() - preprocess_started_at) * 1000, 3)

        nms_threshold = resolve_probability(
            value=request.extra_options.get("nms_threshold"),
            field_name="nms_threshold",
            default=DEFAULT_DETECTION_NMS_THRESHOLD,
        )

        infer_started_at = perf_counter()
        device_index = resolve_cuda_device_index(self.device_name)
        ensure_cuda_success(
            self.imports.cudart.cudaSetDevice(device_index),
            operation_name="TensorRT runtime 绑定 CUDA device",
            details={"device_name": self.device_name},
        )
        engine_input_shape = normalize_tensor_shape(self.engine.get_tensor_shape(self.input_name))
        if any(dim < 0 for dim in engine_input_shape):
            shape_set_result = self.context.set_input_shape(self.input_name, requested_input_shape)
            if shape_set_result is not True:
                raise ServiceConfigurationError(
                    "TensorRT execution context 设置输入 shape 失败",
                    details={
                        "input_name": self.input_name,
                        "requested_input_shape": list(requested_input_shape),
                    },
                )
        elif engine_input_shape != requested_input_shape:
            raise InvalidRequestError(
                "TensorRT engine 输入尺寸与 deployment input_size 不一致",
                details={
                    "engine_input_shape": list(engine_input_shape),
                    "requested_input_shape": list(requested_input_shape),
                    "model_build_id": self.runtime_target.model_build_id,
                },
            )
        resolved_output_shape = normalize_tensor_shape(self.context.get_tensor_shape(self.output_name))
        if not resolved_output_shape or any(dim <= 0 for dim in resolved_output_shape):
            raise ServiceConfigurationError(
                "TensorRT execution context 返回了无效输出 shape",
                details={
                    "output_name": self.output_name,
                    "output_shape": list(resolved_output_shape),
                    "model_build_id": self.runtime_target.model_build_id,
                },
            )
        output_array = self._ensure_io_buffers(
            input_array=input_array,
            resolved_output_shape=resolved_output_shape,
        )
        ensure_cuda_success(
            self.imports.cudart.cudaMemcpyAsync(
                self.input_device_ptr,
                int(input_array.ctypes.data),
                int(input_array.nbytes),
                self.imports.cudart.cudaMemcpyKind.cudaMemcpyHostToDevice,
                self.stream,
            ),
            operation_name="TensorRT runtime 拷贝输入到显存",
            details={"input_name": self.input_name, "byte_size": int(input_array.nbytes)},
        )
        if self.context.set_tensor_address(self.input_name, int(self.input_device_ptr)) is not True:
            raise ServiceConfigurationError(
                "TensorRT execution context 绑定输入张量失败",
                details={"input_name": self.input_name},
            )
        if self.context.set_tensor_address(self.output_name, int(self.output_device_ptr)) is not True:
            raise ServiceConfigurationError(
                "TensorRT execution context 绑定输出张量失败",
                details={"output_name": self.output_name},
            )
        ensure_cuda_success(
            self.imports.cudart.cudaEventRecord(self.execute_start_event, self.stream),
            operation_name="TensorRT runtime 记录执行起点 event",
            details={"device_name": self.device_name},
        )
        if self.context.execute_async_v3(stream_handle=self.stream) is not True:
            raise ServiceConfigurationError(
                "TensorRT execution context 执行推理失败",
                details={"model_build_id": self.runtime_target.model_build_id},
            )
        ensure_cuda_success(
            self.imports.cudart.cudaEventRecord(self.execute_end_event, self.stream),
            operation_name="TensorRT runtime 记录执行终点 event",
            details={"device_name": self.device_name},
        )
        ensure_cuda_success(
            self.imports.cudart.cudaMemcpyAsync(
                int(output_array.ctypes.data),
                self.output_device_ptr,
                int(output_array.nbytes),
                self.imports.cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost,
                self.stream,
            ),
            operation_name="TensorRT runtime 拷贝输出到主存",
            details={"output_name": self.output_name, "byte_size": int(output_array.nbytes)},
        )
        ensure_cuda_success(
            self.imports.cudart.cudaStreamSynchronize(self.stream),
            operation_name="TensorRT runtime 同步 CUDA stream",
            details={"device_name": self.device_name},
        )
        infer_execute_gpu_ms = measure_cuda_event_elapsed_ms(
            cudart_module=self.imports.cudart,
            start_event=self.execute_start_event,
            end_event=self.execute_end_event,
            device_name=self.device_name,
        )
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        image_height = int(image.shape[0])
        image_width = int(image.shape[1])

        postprocess_started_at = perf_counter()
        prediction_array = normalize_tensorrt_outputs(
            output_array=output_array,
            imports=self.imports,
        )
        postprocess_mode, max_detections = _resolve_yolo_primary_postprocess_strategy(
            model_type=self.runtime_target.model_type,
        )
        detections = _build_yolo_primary_detection_records(
            model_type=self.runtime_target.model_type,
            np_module=self.imports.np,
            prediction_array=prediction_array,
            labels=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            nms_threshold=nms_threshold,
            resize_ratio=resize_ratio,
            image_width=image_width,
            image_height=image_height,
            postprocess_mode=postprocess_mode,
            max_detections=max_detections,
        )
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = None
        if request.save_result_image:
            preview_image_bytes = _render_yolo_primary_detection_preview_image(
                model_type=self.runtime_target.model_type,
                cv2_module=self.imports.cv2,
                image=image,
                detections=detections,
            )

        return DetectionPredictionExecutionResult(
            detections=detections,
            latency_ms=round(latency_ms, 3),
            image_width=image_width,
            image_height=image_height,
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=DetectionRuntimeSessionInfo(
                backend_name=self.runtime_target.runtime_backend,
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=DetectionRuntimeTensorSpec(
                    name=self.input_name,
                    shape=requested_input_shape,
                    dtype=self.input_dtype_name,
                ),
                output_spec=DetectionRuntimeTensorSpec(
                    name=self.output_name,
                    shape=resolved_output_shape,
                    dtype=self.output_dtype_name,
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
                    "nms_threshold": (
                        nms_threshold
                        if postprocess_mode == DETECTION_POSTPROCESS_MODE_NMS
                        else None
                    ),
                    "postprocess_mode": postprocess_mode,
                    "max_detections": max_detections,
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


def _build_yolo_primary_detection_records(
    *,
    model_type: str,
    np_module: Any,
    prediction_array: Any,
    labels: tuple[str, ...],
    score_threshold: float,
    nms_threshold: float,
    resize_ratio: float,
    image_width: int,
    image_height: int,
    postprocess_mode: str = DETECTION_POSTPROCESS_MODE_NMS,
    max_detections: int | None = None,
) -> tuple[DetectionPredictionDetection, ...]:
    """把 YOLO 主线输出数组转换成平台 detection 记录。"""

    if _require_primary_model_type(model_type, "YOLO primary") == "yolov8":
        return build_yolov8_detection_records(
            np_module=np_module,
            prediction_array=prediction_array,
            labels=labels,
            score_threshold=score_threshold,
            nms_threshold=nms_threshold,
            resize_ratio=resize_ratio,
            image_width=image_width,
            image_height=image_height,
        )

    postprocess_results = postprocess_detection_prediction_array(
        prediction_array=prediction_array,
        np_module=np_module,
        num_classes=len(labels),
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        postprocess_mode=postprocess_mode,
        max_detections=max_detections,
    )
    if not postprocess_results:
        return ()

    detections: list[DetectionPredictionDetection] = []
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
            DetectionPredictionDetection(
                bbox_xyxy=(round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)),
                score=round(float(score), 6),
                class_id=resolved_class_id,
                class_name=class_name,
            )
        )
    if postprocess_mode == DETECTION_POSTPROCESS_MODE_NMS:
        detections.sort(key=lambda item: item.score, reverse=True)
    return tuple(detections)


def _render_yolo_primary_detection_preview_image(
    *,
    model_type: str,
    cv2_module: Any,
    image: Any,
    detections: tuple[DetectionPredictionDetection, ...],
) -> bytes:
    """按模型类型渲染 detection 调试预览图。"""

    if _require_primary_model_type(model_type, "YOLO primary") == "yolov8":
        return render_yolov8_detection_preview_image(
            cv2_module=cv2_module,
            image=image,
            instances=detections,
        )
    return render_preview_image(
        cv2_module=cv2_module,
        image=image,
        detections=detections,
    )


def _resolve_yolo_primary_postprocess_strategy(
    *,
    model_type: str,
    is_end2end: bool | None = None,
) -> tuple[str, int | None]:
    """解析当前 YOLO 主线模型应使用的 detection 后处理策略。"""

    if is_end2end is None:
        resolved_model_type = _require_primary_model_type(model_type, "YOLO primary")
        model_config = get_yolo_primary_model_config(
            model_type=resolved_model_type,
            task_type="detection",
        )
        is_end2end = bool(model_config.get("end2end", False))
    if is_end2end:
        return DETECTION_POSTPROCESS_MODE_END2END_TOPK, DEFAULT_END2END_MAX_DETECTIONS
    return DETECTION_POSTPROCESS_MODE_NMS, None


def _require_primary_model_type(model_type: str, model_label: str) -> str:
    """返回当前主线 predictor 允许使用的正式模型分类。"""

    normalized_model_type = normalize_optional_platform_model_type(model_type)
    if not normalized_model_type or normalized_model_type == "yolo-primary":
        raise ServiceConfigurationError(
            f"当前 {model_label} predictor 缺少正式 model_type 配置",
            details={"model_type": model_type},
        )
    return normalized_model_type
