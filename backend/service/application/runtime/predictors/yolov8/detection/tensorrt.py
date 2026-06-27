"""YOLOv8 detection TensorRT runtime session。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.postprocess.detection_postprocess import (
    DETECTION_POSTPROCESS_MODE_NMS,
)
from backend.service.application.models.yolov8_core.postprocess import (
    build_yolov8_detection_records,
)
from backend.service.application.runtime.predictors.yolov8.detection.backend import (
    ensure_yolov8_detection_cuda_success,
    get_yolov8_detection_tensorrt_logger,
    import_yolov8_detection_tensorrt_module,
    normalize_yolov8_detection_tensor_shape,
    normalize_yolov8_detection_tensorrt_outputs,
    release_yolov8_detection_cuda_resource,
    require_yolov8_detection_cuda_imports,
    resolve_yolov8_detection_cuda_device_index,
    resolve_yolov8_detection_cuda_runtime_device_name,
    resolve_yolov8_detection_tensorrt_dtype_name,
    resolve_yolov8_detection_tensorrt_io_tensor_name,
)
from backend.service.application.runtime.predictors.yolov8.detection.buffer import (
    build_yolov8_detection_numpy_array_from_host_pointer,
    resolve_yolov8_detection_numpy_dtype,
    resolve_yolov8_detection_tensor_byte_size,
)
from backend.service.application.runtime.predictors.yolov8.detection.contracts import (
    DEFAULT_YOLOV8_DETECTION_NMS_THRESHOLD,
    YoloV8DetectionPredictionExecutionResult,
    YoloV8DetectionPredictionRequest,
    YoloV8DetectionRuntimeSessionInfo,
    YoloV8DetectionRuntimeTensorSpec,
    resolve_yolov8_detection_probability,
)
from backend.service.application.runtime.predictors.yolov8.detection.io import (
    load_yolov8_detection_prediction_image,
    preprocess_yolov8_detection_image,
)
from backend.service.application.runtime.predictors.yolov8.detection.preview import (
    render_yolov8_detection_preview_image_if_requested,
)
from backend.service.application.runtime.predictors.yolov8.detection.timing import (
    is_yolov8_detection_debugger_attached,
    measure_yolov8_detection_cuda_event_elapsed_ms,
    measure_yolov8_detection_elapsed_ms,
    measure_yolov8_detection_stage_elapsed_ms,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.settings import get_backend_service_settings


class TensorRTYoloV8RuntimeSession:
    """已经加载完成并可重复推理的 TensorRT YOLOv8 detection 会话。"""

    model_type = "yolov8"
    model_label = "YOLOv8"

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
        output_name: str,
        input_dtype_name: str,
        output_dtype_name: str,
        stream: Any,
        execute_start_event: Any,
        execute_end_event: Any,
        pinned_output_buffer_enabled: bool | None = None,
        pinned_output_buffer_max_bytes: int | None = None,
    ) -> None:
        """初始化 TensorRT YOLOv8 detection 会话。"""

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
        self.output_name = output_name
        self.input_dtype_name = input_dtype_name
        self.output_dtype_name = output_dtype_name
        self.stream = stream
        self.execute_start_event = execute_start_event
        self.execute_end_event = execute_end_event
        self.pinned_output_buffer_enabled = bool(pinned_output_buffer_enabled)
        self.pinned_output_buffer_max_bytes = max(0, int(pinned_output_buffer_max_bytes))
        self.input_device_ptr: int | None = None
        self.output_device_ptr: int | None = None
        self.input_capacity_bytes = 0
        self.output_capacity_bytes = 0
        self.output_host_ptr: int | None = None
        self.output_host_capacity_bytes = 0
        self.output_host_memory_kind = "pageable"
        self.output_host_array: Any | None = None

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        pinned_output_buffer_enabled: bool | None = None,
        pinned_output_buffer_max_bytes: int | None = None,
    ) -> "TensorRTYoloV8RuntimeSession":
        """加载一套 TensorRT YOLOv8 detection 会话。"""

        if runtime_target.runtime_backend != "tensorrt":
            raise InvalidRequestError(
                "当前 YOLOv8 detection predictor 仅支持 tensorrt runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
            )

        imports = require_yolov8_detection_cuda_imports()
        tensorrt_module = import_yolov8_detection_tensorrt_module()
        device_name = resolve_yolov8_detection_cuda_runtime_device_name(
            cudart_module=imports.cudart,
            requested_device_name=runtime_target.device_name,
        )
        ensure_yolov8_detection_cuda_success(
            imports.cudart.cudaSetDevice(resolve_yolov8_detection_cuda_device_index(device_name)),
            operation_name="TensorRT runtime 切换 CUDA device",
            details={"device_name": device_name},
        )
        logger = get_yolov8_detection_tensorrt_logger(
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
        stream = ensure_yolov8_detection_cuda_success(
            imports.cudart.cudaStreamCreate(),
            operation_name="TensorRT runtime 创建复用 CUDA stream",
            details={"device_name": device_name},
        )[0]
        execute_start_event = ensure_yolov8_detection_cuda_success(
            imports.cudart.cudaEventCreate(),
            operation_name="TensorRT runtime 创建执行起点 event",
            details={"device_name": device_name},
        )[0]
        execute_end_event = ensure_yolov8_detection_cuda_success(
            imports.cudart.cudaEventCreate(),
            operation_name="TensorRT runtime 创建执行终点 event",
            details={"device_name": device_name},
        )[0]
        input_name = resolve_yolov8_detection_tensorrt_io_tensor_name(
            engine=engine,
            tensorrt_module=tensorrt_module,
            io_mode=tensorrt_module.TensorIOMode.INPUT,
            fallback="images",
        )
        output_name = resolve_yolov8_detection_tensorrt_io_tensor_name(
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
            input_dtype_name=resolve_yolov8_detection_tensorrt_dtype_name(
                tensorrt_module=tensorrt_module,
                tensor_dtype=engine.get_tensor_dtype(input_name),
                fallback="float32",
            ),
            output_dtype_name=resolve_yolov8_detection_tensorrt_dtype_name(
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

    def close(self) -> None:
        """释放 TensorRT session 持有的 CUDA 资源。"""

        try:
            release_yolov8_detection_cuda_resource(
                self.imports.cudart.cudaSetDevice(
                    resolve_yolov8_detection_cuda_device_index(self.device_name)
                )
            )
        except Exception:
            return
        if self.input_device_ptr is not None:
            release_yolov8_detection_cuda_resource(self.imports.cudart.cudaFree(self.input_device_ptr))
            self.input_device_ptr = None
            self.input_capacity_bytes = 0
        if self.output_device_ptr is not None:
            release_yolov8_detection_cuda_resource(self.imports.cudart.cudaFree(self.output_device_ptr))
            self.output_device_ptr = None
            self.output_capacity_bytes = 0
        if self.output_host_ptr is not None:
            release_yolov8_detection_cuda_resource(self.imports.cudart.cudaFreeHost(self.output_host_ptr))
            self.output_host_ptr = None
            self.output_host_capacity_bytes = 0
            self.output_host_array = None
        self.output_host_memory_kind = "pageable"
        if self.stream is not None:
            release_yolov8_detection_cuda_resource(self.imports.cudart.cudaStreamDestroy(self.stream))
            self.stream = None
        if self.execute_start_event is not None:
            release_yolov8_detection_cuda_resource(
                self.imports.cudart.cudaEventDestroy(self.execute_start_event)
            )
            self.execute_start_event = None
        if self.execute_end_event is not None:
            release_yolov8_detection_cuda_resource(
                self.imports.cudart.cudaEventDestroy(self.execute_end_event)
            )
            self.execute_end_event = None
        self.output_host_array = None

    def describe_memory_usage(self) -> dict[str, object]:
        """返回当前 TensorRT session 的输出 host buffer 占用快照。"""

        output_host_buffer_bytes = 0
        if self.output_host_array is not None:
            output_host_buffer_bytes = int(self.output_host_array.nbytes)
        output_host_pinned_bytes = 0
        if self.output_host_memory_kind == "pinned" and self.output_host_ptr is not None:
            output_host_pinned_bytes = int(self.output_host_capacity_bytes)
        return {
            "output_host_memory_kind": self.output_host_memory_kind,
            "output_host_buffer_bytes": output_host_buffer_bytes,
            "output_host_pinned_bytes": output_host_pinned_bytes,
            "output_host_pinned_enabled": self.pinned_output_buffer_enabled,
            "output_host_pinned_max_bytes": self.pinned_output_buffer_max_bytes,
        }

    def predict(
        self,
        request: YoloV8DetectionPredictionRequest,
    ) -> YoloV8DetectionPredictionExecutionResult:
        """执行一次 TensorRT YOLOv8 detection 预测。"""

        decode_started_at = perf_counter()
        image = load_yolov8_detection_prediction_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = measure_yolov8_detection_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=decode_started_at,
        )

        preprocess_started_at = perf_counter()
        input_tensor, letterbox_transform = preprocess_yolov8_detection_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            image=image,
            input_size=self.runtime_target.input_size,
        )
        input_array = self.imports.np.expand_dims(input_tensor, axis=0).astype(
            resolve_yolov8_detection_numpy_dtype(
                np_module=self.imports.np,
                dtype_name=self.input_dtype_name,
            ),
            copy=False,
        )
        requested_input_shape = tuple(int(dim) for dim in input_array.shape)
        preprocess_ms = round((perf_counter() - preprocess_started_at) * 1000, 3)

        nms_threshold = resolve_yolov8_detection_probability(
            value=request.extra_options.get("nms_threshold"),
            field_name="nms_threshold",
            default=DEFAULT_YOLOV8_DETECTION_NMS_THRESHOLD,
        )

        infer_started_at = perf_counter()
        device_index = resolve_yolov8_detection_cuda_device_index(self.device_name)
        set_device_started_at = perf_counter()
        ensure_yolov8_detection_cuda_success(
            self.imports.cudart.cudaSetDevice(device_index),
            operation_name="TensorRT runtime 绑定 CUDA device",
            details={"device_name": self.device_name},
        )
        infer_set_device_ms = measure_yolov8_detection_elapsed_ms(set_device_started_at)

        prepare_io_started_at = perf_counter()
        engine_input_shape = normalize_yolov8_detection_tensor_shape(
            self.engine.get_tensor_shape(self.input_name)
        )
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

        resolved_output_shape = normalize_yolov8_detection_tensor_shape(
            self.context.get_tensor_shape(self.output_name)
        )
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
        infer_prepare_io_ms = measure_yolov8_detection_elapsed_ms(prepare_io_started_at)

        enqueue_h2d_started_at = perf_counter()
        ensure_yolov8_detection_cuda_success(
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
        infer_enqueue_h2d_ms = measure_yolov8_detection_elapsed_ms(enqueue_h2d_started_at)

        bind_tensor_started_at = perf_counter()
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
        infer_bind_tensor_ms = measure_yolov8_detection_elapsed_ms(bind_tensor_started_at)

        execute_enqueue_started_at = perf_counter()
        ensure_yolov8_detection_cuda_success(
            self.imports.cudart.cudaEventRecord(self.execute_start_event, self.stream),
            operation_name="TensorRT runtime 记录执行起点 event",
            details={"device_name": self.device_name},
        )
        if self.context.execute_async_v3(stream_handle=self.stream) is not True:
            raise ServiceConfigurationError(
                "TensorRT execution context 执行推理失败",
                details={"model_build_id": self.runtime_target.model_build_id},
            )
        ensure_yolov8_detection_cuda_success(
            self.imports.cudart.cudaEventRecord(self.execute_end_event, self.stream),
            operation_name="TensorRT runtime 记录执行终点 event",
            details={"device_name": self.device_name},
        )
        infer_execute_enqueue_ms = measure_yolov8_detection_elapsed_ms(execute_enqueue_started_at)

        enqueue_d2h_started_at = perf_counter()
        ensure_yolov8_detection_cuda_success(
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
        infer_enqueue_d2h_host_ms = measure_yolov8_detection_elapsed_ms(enqueue_d2h_started_at)

        output_ready_wait_started_at = perf_counter()
        ensure_yolov8_detection_cuda_success(
            self.imports.cudart.cudaStreamSynchronize(self.stream),
            operation_name="TensorRT runtime 同步 CUDA stream",
            details={"device_name": self.device_name},
        )
        infer_output_ready_wait_ms = measure_yolov8_detection_elapsed_ms(output_ready_wait_started_at)
        infer_execute_gpu_ms = measure_yolov8_detection_cuda_event_elapsed_ms(
            cudart_module=self.imports.cudart,
            start_event=self.execute_start_event,
            end_event=self.execute_end_event,
            device_name=self.device_name,
        )
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        image_height = int(image.shape[0])
        image_width = int(image.shape[1])

        postprocess_started_at = perf_counter()
        prediction_array = normalize_yolov8_detection_tensorrt_outputs(
            output_array=output_array,
            imports=self.imports,
        )
        detections = build_yolov8_detection_records(
            np_module=self.imports.np,
            prediction_array=prediction_array,
            labels=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            nms_threshold=nms_threshold,
            letterbox_transform=letterbox_transform,
        )
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = render_yolov8_detection_preview_image_if_requested(
            cv2_module=self.imports.cv2,
            image=image,
            detections=detections,
            save_result_image=request.save_result_image,
        )

        return YoloV8DetectionPredictionExecutionResult(
            detections=detections,
            latency_ms=round(latency_ms, 3),
            image_width=image_width,
            image_height=image_height,
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=YoloV8DetectionRuntimeSessionInfo(
                backend_name=self.runtime_target.runtime_backend,
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=YoloV8DetectionRuntimeTensorSpec(
                    name=self.input_name,
                    shape=requested_input_shape,
                    dtype=self.input_dtype_name,
                ),
                output_spec=YoloV8DetectionRuntimeTensorSpec(
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
                    "nms_threshold": nms_threshold,
                    "postprocess_mode": DETECTION_POSTPROCESS_MODE_NMS,
                    "max_detections": None,
                    "class_count": len(self.runtime_target.labels),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                    "infer_set_device_ms": infer_set_device_ms,
                    "infer_prepare_io_ms": infer_prepare_io_ms,
                    "infer_enqueue_h2d_ms": infer_enqueue_h2d_ms,
                    "infer_bind_tensor_ms": infer_bind_tensor_ms,
                    "infer_execute_enqueue_ms": infer_execute_enqueue_ms,
                    "infer_execute_gpu_ms": infer_execute_gpu_ms,
                    "infer_enqueue_d2h_host_ms": infer_enqueue_d2h_host_ms,
                    "infer_output_ready_wait_ms": infer_output_ready_wait_ms,
                    "tensorrt_version": str(self.tensorrt_module.__version__),
                    "compiled_runtime_precision": self.runtime_target.runtime_precision,
                    "engine_file_bytes": self.runtime_target.runtime_artifact_path.stat().st_size,
                    "debugger_attached": is_yolov8_detection_debugger_attached(),
                    **self.describe_memory_usage(),
                },
            ),
        )

    def _ensure_io_buffers(
        self,
        *,
        input_array: Any,
        resolved_output_shape: tuple[int, ...],
    ) -> Any:
        """按当前输入输出尺寸复用或扩容 TensorRT I/O 缓冲。"""

        output_dtype = resolve_yolov8_detection_numpy_dtype(
            np_module=self.imports.np,
            dtype_name=self.output_dtype_name,
        )
        input_nbytes = int(input_array.nbytes)
        output_nbytes = resolve_yolov8_detection_tensor_byte_size(
            np_module=self.imports.np,
            shape=resolved_output_shape,
            dtype=output_dtype,
        )
        if self.input_device_ptr is None or input_nbytes > self.input_capacity_bytes:
            if self.input_device_ptr is not None:
                release_yolov8_detection_cuda_resource(
                    self.imports.cudart.cudaFree(self.input_device_ptr)
                )
            self.input_device_ptr = ensure_yolov8_detection_cuda_success(
                self.imports.cudart.cudaMalloc(input_nbytes),
                operation_name="TensorRT runtime 分配复用输入显存",
                details={"byte_size": input_nbytes},
            )[0]
            self.input_capacity_bytes = input_nbytes
        if self.output_device_ptr is None or output_nbytes > self.output_capacity_bytes:
            if self.output_device_ptr is not None:
                release_yolov8_detection_cuda_resource(
                    self.imports.cudart.cudaFree(self.output_device_ptr)
                )
            self.output_device_ptr = ensure_yolov8_detection_cuda_success(
                self.imports.cudart.cudaMalloc(output_nbytes),
                operation_name="TensorRT runtime 分配复用输出显存",
                details={"byte_size": output_nbytes},
            )[0]
            self.output_capacity_bytes = output_nbytes
        if self._should_use_pinned_output_buffer(output_nbytes):
            return self._ensure_pinned_output_array(
                output_nbytes=output_nbytes,
                output_dtype=output_dtype,
                resolved_output_shape=resolved_output_shape,
            )
        return self._ensure_pageable_output_array(
            output_dtype=output_dtype,
            resolved_output_shape=resolved_output_shape,
        )

    def _ensure_pinned_output_array(
        self,
        *,
        output_nbytes: int,
        output_dtype: Any,
        resolved_output_shape: tuple[int, ...],
    ) -> Any:
        """返回可复用的 pinned 输出主存数组。"""

        if self.output_host_ptr is None or output_nbytes > self.output_host_capacity_bytes:
            if self.output_host_ptr is not None:
                release_yolov8_detection_cuda_resource(
                    self.imports.cudart.cudaFreeHost(self.output_host_ptr)
                )
            self.output_host_ptr = ensure_yolov8_detection_cuda_success(
                self.imports.cudart.cudaMallocHost(output_nbytes),
                operation_name="TensorRT runtime 分配 pinned 输出主存",
                details={"byte_size": output_nbytes},
            )[0]
            self.output_host_capacity_bytes = output_nbytes
            self.output_host_array = None
        if (
            self.output_host_array is None
            or self.output_host_memory_kind != "pinned"
            or tuple(int(dim) for dim in self.output_host_array.shape) != resolved_output_shape
            or self.output_host_array.dtype != output_dtype
        ):
            self.output_host_array = build_yolov8_detection_numpy_array_from_host_pointer(
                np_module=self.imports.np,
                host_ptr=int(self.output_host_ptr),
                byte_size=output_nbytes,
                dtype=output_dtype,
                shape=resolved_output_shape,
            )
        self.output_host_memory_kind = "pinned"
        return self.output_host_array

    def _ensure_pageable_output_array(
        self,
        *,
        output_dtype: Any,
        resolved_output_shape: tuple[int, ...],
    ) -> Any:
        """返回可复用的 pageable 输出主存数组。"""

        if self.output_host_ptr is not None:
            release_yolov8_detection_cuda_resource(self.imports.cudart.cudaFreeHost(self.output_host_ptr))
            self.output_host_ptr = None
            self.output_host_capacity_bytes = 0
            self.output_host_array = None
        if (
            self.output_host_array is None
            or self.output_host_memory_kind != "pageable"
            or tuple(int(dim) for dim in self.output_host_array.shape) != resolved_output_shape
            or self.output_host_array.dtype != output_dtype
        ):
            self.output_host_array = self.imports.np.empty(resolved_output_shape, dtype=output_dtype)
        self.output_host_memory_kind = "pageable"
        return self.output_host_array

    def _should_use_pinned_output_buffer(self, output_nbytes: int) -> bool:
        """判断当前输出 host buffer 是否应该使用 pinned memory。"""

        if not self.pinned_output_buffer_enabled:
            return False
        return int(output_nbytes) <= int(self.pinned_output_buffer_max_bytes)


__all__ = ["TensorRTYoloV8RuntimeSession"]
