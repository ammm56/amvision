"""YOLOv8 segmentation TensorRT runtime session。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.runtime.predictors.yolov8.segmentation.backend import (
    ensure_yolov8_segmentation_cuda_success,
    get_yolov8_segmentation_tensorrt_logger,
    import_yolov8_segmentation_tensorrt_module,
    list_yolov8_segmentation_tensorrt_output_names,
    normalize_yolov8_segmentation_outputs_for_backend,
    normalize_yolov8_segmentation_tensor_shape,
    release_yolov8_segmentation_cuda_resource,
    require_yolov8_segmentation_cuda_imports,
    resolve_yolov8_segmentation_cuda_device_index,
    resolve_yolov8_segmentation_cuda_runtime_device_name,
    resolve_yolov8_segmentation_tensorrt_dtype_name,
    resolve_yolov8_segmentation_tensorrt_io_tensor_name,
)
from backend.service.application.runtime.predictors.yolov8.segmentation.buffer import (
    build_yolov8_segmentation_numpy_array_from_host_pointer,
    resolve_yolov8_segmentation_numpy_dtype,
    resolve_yolov8_segmentation_tensor_byte_size,
)
from backend.service.application.runtime.predictors.yolov8.segmentation.contracts import (
    YoloV8SegmentationPredictionExecutionResult,
    YoloV8SegmentationPredictionRequest,
    YoloV8SegmentationRuntimeSessionInfo,
    YoloV8SegmentationRuntimeTensorSpec,
)
from backend.service.application.runtime.predictors.yolov8.segmentation.io import (
    load_yolov8_segmentation_prediction_image,
    preprocess_yolov8_segmentation_image,
)
from backend.service.application.runtime.predictors.yolov8.segmentation.postprocess import (
    build_yolov8_segmentation_runtime_instances,
)
from backend.service.application.runtime.predictors.yolov8.segmentation.preview import (
    render_yolov8_segmentation_preview_image_if_requested,
)
from backend.service.application.runtime.predictors.yolov8.segmentation.timing import (
    is_yolov8_segmentation_debugger_attached,
    measure_yolov8_segmentation_cuda_event_elapsed_ms,
    measure_yolov8_segmentation_elapsed_ms,
    measure_yolov8_segmentation_stage_elapsed_ms,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.settings import get_backend_service_settings


class TensorRTYoloV8SegmentationRuntimeSession:
    """已经加载完成并可重复推理的 TensorRT YOLOv8 segmentation 会话。"""

    model_type = "yolov8"
    model_label = "YOLOv8"
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
        """初始化 TensorRT YOLOv8 segmentation 会话。"""

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
    ) -> "TensorRTYoloV8SegmentationRuntimeSession":
        """加载一套 TensorRT YOLOv8 segmentation 会话。"""

        if runtime_target.runtime_backend != "tensorrt":
            raise InvalidRequestError(
                "当前 YOLOv8 segmentation predictor 仅支持 tensorrt runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(
                "当前 YOLOv8 segmentation predictor 收到了错误的 task_type",
                details={"task_type": runtime_target.task_type},
            )

        imports = require_yolov8_segmentation_cuda_imports()
        tensorrt_module = import_yolov8_segmentation_tensorrt_module()
        device_name = resolve_yolov8_segmentation_cuda_runtime_device_name(
            cudart_module=imports.cudart,
            requested_device_name=runtime_target.device_name,
        )
        ensure_yolov8_segmentation_cuda_success(
            imports.cudart.cudaSetDevice(resolve_yolov8_segmentation_cuda_device_index(device_name)),
            operation_name="TensorRT segmentation runtime 切换 CUDA device",
            details={"device_name": device_name},
        )
        logger = get_yolov8_segmentation_tensorrt_logger(
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

        stream = ensure_yolov8_segmentation_cuda_success(
            imports.cudart.cudaStreamCreate(),
            operation_name="TensorRT segmentation runtime 创建复用 CUDA stream",
            details={"device_name": device_name},
        )[0]
        execute_start_event = ensure_yolov8_segmentation_cuda_success(
            imports.cudart.cudaEventCreate(),
            operation_name="TensorRT segmentation runtime 创建执行起点 event",
            details={"device_name": device_name},
        )[0]
        execute_end_event = ensure_yolov8_segmentation_cuda_success(
            imports.cudart.cudaEventCreate(),
            operation_name="TensorRT segmentation runtime 创建执行终点 event",
            details={"device_name": device_name},
        )[0]
        input_name = resolve_yolov8_segmentation_tensorrt_io_tensor_name(
            engine=engine,
            tensorrt_module=tensorrt_module,
            io_mode=tensorrt_module.TensorIOMode.INPUT,
            fallback="images",
        )
        prediction_name, proto_name = _resolve_yolov8_segmentation_output_names(
            engine=engine,
            tensorrt_module=tensorrt_module,
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
            input_dtype_name=resolve_yolov8_segmentation_tensorrt_dtype_name(
                tensorrt_module=tensorrt_module,
                tensor_dtype=engine.get_tensor_dtype(input_name),
                fallback="float32",
            ),
            prediction_dtype_name=resolve_yolov8_segmentation_tensorrt_dtype_name(
                tensorrt_module=tensorrt_module,
                tensor_dtype=engine.get_tensor_dtype(prediction_name),
                fallback="float32",
            ),
            proto_dtype_name=resolve_yolov8_segmentation_tensorrt_dtype_name(
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

    def predict(
        self,
        request: YoloV8SegmentationPredictionRequest,
    ) -> YoloV8SegmentationPredictionExecutionResult:
        """执行一次 TensorRT YOLOv8 segmentation 预测。"""

        decode_started_at = perf_counter()
        image = load_yolov8_segmentation_prediction_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = measure_yolov8_segmentation_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=decode_started_at,
        )

        preprocess_started_at = perf_counter()
        input_tensor, letterbox_transform = preprocess_yolov8_segmentation_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            image=image,
            input_size=self.runtime_target.input_size,
        )
        input_array = self.imports.np.expand_dims(input_tensor, axis=0).astype(
            resolve_yolov8_segmentation_numpy_dtype(
                np_module=self.imports.np,
                dtype_name=self.input_dtype_name,
            ),
            copy=False,
        )
        requested_input_shape = tuple(int(dim) for dim in input_array.shape)
        preprocess_ms = measure_yolov8_segmentation_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=preprocess_started_at,
        )

        infer_started_at = perf_counter()
        device_index = resolve_yolov8_segmentation_cuda_device_index(self.device_name)
        set_device_started_at = perf_counter()
        ensure_yolov8_segmentation_cuda_success(
            self.imports.cudart.cudaSetDevice(device_index),
            operation_name="TensorRT segmentation runtime 绑定 CUDA device",
            details={"device_name": self.device_name},
        )
        infer_set_device_ms = measure_yolov8_segmentation_elapsed_ms(set_device_started_at)

        prepare_io_started_at = perf_counter()
        self._set_or_validate_input_shape(requested_input_shape)
        resolved_prediction_shape = self._resolve_output_shape(
            tensor_name=self.prediction_name,
            label="prediction",
        )
        resolved_proto_shape = self._resolve_output_shape(
            tensor_name=self.proto_name,
            label="proto",
        )
        prediction_array, proto_array = self._ensure_io_buffers(
            input_array=input_array,
            resolved_prediction_shape=resolved_prediction_shape,
            resolved_proto_shape=resolved_proto_shape,
        )
        infer_prepare_io_ms = measure_yolov8_segmentation_elapsed_ms(prepare_io_started_at)

        enqueue_h2d_started_at = perf_counter()
        ensure_yolov8_segmentation_cuda_success(
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
        infer_enqueue_h2d_ms = measure_yolov8_segmentation_elapsed_ms(enqueue_h2d_started_at)

        bind_tensor_started_at = perf_counter()
        self._bind_io_tensor_addresses()
        infer_bind_tensor_ms = measure_yolov8_segmentation_elapsed_ms(bind_tensor_started_at)

        execute_enqueue_started_at = perf_counter()
        ensure_yolov8_segmentation_cuda_success(
            self.imports.cudart.cudaEventRecord(self.execute_start_event, self.stream),
            operation_name="TensorRT segmentation runtime 记录执行起点 event",
            details={"device_name": self.device_name},
        )
        if self.context.execute_async_v3(stream_handle=self.stream) is not True:
            raise ServiceConfigurationError(
                "TensorRT segmentation execution context 执行推理失败",
                details={"model_build_id": self.runtime_target.model_build_id},
            )
        ensure_yolov8_segmentation_cuda_success(
            self.imports.cudart.cudaEventRecord(self.execute_end_event, self.stream),
            operation_name="TensorRT segmentation runtime 记录执行终点 event",
            details={"device_name": self.device_name},
        )
        infer_execute_enqueue_ms = measure_yolov8_segmentation_elapsed_ms(execute_enqueue_started_at)

        enqueue_d2h_started_at = perf_counter()
        self._copy_outputs_to_host(
            prediction_array=prediction_array,
            proto_array=proto_array,
        )
        infer_enqueue_d2h_host_ms = measure_yolov8_segmentation_elapsed_ms(enqueue_d2h_started_at)

        output_ready_wait_started_at = perf_counter()
        ensure_yolov8_segmentation_cuda_success(
            self.imports.cudart.cudaStreamSynchronize(self.stream),
            operation_name="TensorRT segmentation runtime 同步 CUDA stream",
            details={"device_name": self.device_name},
        )
        infer_output_ready_wait_ms = measure_yolov8_segmentation_elapsed_ms(output_ready_wait_started_at)
        infer_execute_gpu_ms = measure_yolov8_segmentation_cuda_event_elapsed_ms(
            cudart_module=self.imports.cudart,
            start_event=self.execute_start_event,
            end_event=self.execute_end_event,
            device_name=self.device_name,
        )
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        postprocess_started_at = perf_counter()
        normalized_prediction_array, normalized_proto_array = (
            normalize_yolov8_segmentation_outputs_for_backend(
                outputs=(prediction_array, proto_array),
                np_module=self.imports.np,
            )
        )
        instances = build_yolov8_segmentation_runtime_instances(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            prediction_array=normalized_prediction_array,
            proto_array=normalized_proto_array,
            labels=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            mask_threshold=request.mask_threshold,
            letterbox_transform=letterbox_transform,
        )
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = render_yolov8_segmentation_preview_image_if_requested(
            cv2_module=self.imports.cv2,
            image=image,
            instances=instances,
            save_result_image=request.save_result_image,
        )
        image_height = int(image.shape[0])
        image_width = int(image.shape[1])

        return YoloV8SegmentationPredictionExecutionResult(
            instances=instances,
            latency_ms=round(latency_ms, 3),
            preview_image_bytes=preview_image_bytes,
            image_width=image_width,
            image_height=image_height,
            runtime_session_info=YoloV8SegmentationRuntimeSessionInfo(
                backend_name=self.runtime_target.runtime_backend,
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=YoloV8SegmentationRuntimeTensorSpec(
                    name=self.input_name,
                    shape=requested_input_shape,
                    dtype=self.input_dtype_name,
                ),
                output_specs=(
                    YoloV8SegmentationRuntimeTensorSpec(
                        name=self.prediction_name,
                        shape=resolved_prediction_shape,
                        dtype=self.prediction_dtype_name,
                    ),
                    YoloV8SegmentationRuntimeTensorSpec(
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
                    "debugger_attached": is_yolov8_segmentation_debugger_attached(),
                    **self.describe_memory_usage(),
                },
            ),
        )

    def close(self) -> None:
        """释放 TensorRT segmentation session 持有的 CUDA 资源。"""

        try:
            release_yolov8_segmentation_cuda_resource(
                self.imports.cudart.cudaSetDevice(
                    resolve_yolov8_segmentation_cuda_device_index(self.device_name)
                )
            )
        except Exception:
            return
        if self.input_device_ptr is not None:
            release_yolov8_segmentation_cuda_resource(
                self.imports.cudart.cudaFree(self.input_device_ptr)
            )
            self.input_device_ptr = None
            self.input_capacity_bytes = 0
        if self.prediction_device_ptr is not None:
            release_yolov8_segmentation_cuda_resource(
                self.imports.cudart.cudaFree(self.prediction_device_ptr)
            )
            self.prediction_device_ptr = None
            self.prediction_capacity_bytes = 0
        if self.proto_device_ptr is not None:
            release_yolov8_segmentation_cuda_resource(
                self.imports.cudart.cudaFree(self.proto_device_ptr)
            )
            self.proto_device_ptr = None
            self.proto_capacity_bytes = 0
        if self.prediction_host_ptr is not None:
            release_yolov8_segmentation_cuda_resource(
                self.imports.cudart.cudaFreeHost(self.prediction_host_ptr)
            )
            self.prediction_host_ptr = None
            self.prediction_host_capacity_bytes = 0
            self.prediction_host_array = None
        if self.proto_host_ptr is not None:
            release_yolov8_segmentation_cuda_resource(
                self.imports.cudart.cudaFreeHost(self.proto_host_ptr)
            )
            self.proto_host_ptr = None
            self.proto_host_capacity_bytes = 0
            self.proto_host_array = None
        self.prediction_host_memory_kind = "pageable"
        self.proto_host_memory_kind = "pageable"
        if self.stream is not None:
            release_yolov8_segmentation_cuda_resource(self.imports.cudart.cudaStreamDestroy(self.stream))
            self.stream = None
        if self.execute_start_event is not None:
            release_yolov8_segmentation_cuda_resource(
                self.imports.cudart.cudaEventDestroy(self.execute_start_event)
            )
            self.execute_start_event = None
        if self.execute_end_event is not None:
            release_yolov8_segmentation_cuda_resource(
                self.imports.cudart.cudaEventDestroy(self.execute_end_event)
            )
            self.execute_end_event = None
        self.prediction_host_array = None
        self.proto_host_array = None

    def describe_memory_usage(self) -> dict[str, object]:
        """返回当前 TensorRT segmentation session 的输出 host buffer 占用快照。"""

        return {
            "prediction_host_memory_kind": self.prediction_host_memory_kind,
            "prediction_host_buffer_bytes": _array_nbytes(self.prediction_host_array),
            "prediction_host_pinned_bytes": self._pinned_bytes(
                host_memory_kind=self.prediction_host_memory_kind,
                host_ptr=self.prediction_host_ptr,
                host_capacity_bytes=self.prediction_host_capacity_bytes,
            ),
            "proto_host_memory_kind": self.proto_host_memory_kind,
            "proto_host_buffer_bytes": _array_nbytes(self.proto_host_array),
            "proto_host_pinned_bytes": self._pinned_bytes(
                host_memory_kind=self.proto_host_memory_kind,
                host_ptr=self.proto_host_ptr,
                host_capacity_bytes=self.proto_host_capacity_bytes,
            ),
            "output_host_pinned_enabled": self.pinned_output_buffer_enabled,
            "output_host_pinned_max_bytes": self.pinned_output_buffer_max_bytes,
        }

    def _set_or_validate_input_shape(self, requested_input_shape: tuple[int, ...]) -> None:
        """设置或校验 TensorRT execution context 输入 shape。"""

        engine_input_shape = normalize_yolov8_segmentation_tensor_shape(
            self.engine.get_tensor_shape(self.input_name)
        )
        if any(dim < 0 for dim in engine_input_shape):
            shape_set_result = self.context.set_input_shape(self.input_name, requested_input_shape)
            if shape_set_result is not True:
                raise ServiceConfigurationError(
                    "TensorRT segmentation execution context 设置输入 shape 失败",
                    details={
                        "input_name": self.input_name,
                        "requested_input_shape": list(requested_input_shape),
                    },
                )
        elif engine_input_shape != requested_input_shape:
            raise InvalidRequestError(
                "TensorRT segmentation engine 输入尺寸与 runtime input_size 不一致",
                details={
                    "engine_input_shape": list(engine_input_shape),
                    "requested_input_shape": list(requested_input_shape),
                    "model_build_id": self.runtime_target.model_build_id,
                },
            )

    def _resolve_output_shape(self, *, tensor_name: str, label: str) -> tuple[int, ...]:
        """读取 TensorRT 输出 shape 并校验为正整数。"""

        resolved_shape = normalize_yolov8_segmentation_tensor_shape(
            self.context.get_tensor_shape(tensor_name)
        )
        if not resolved_shape or any(dim <= 0 for dim in resolved_shape):
            raise ServiceConfigurationError(
                f"TensorRT segmentation execution context 返回了无效 {label} shape",
                details={
                    "output_name": tensor_name,
                    "output_shape": list(resolved_shape),
                    "model_build_id": self.runtime_target.model_build_id,
                },
            )
        return resolved_shape

    def _bind_io_tensor_addresses(self) -> None:
        """把输入和两个输出 tensor address 绑定到 TensorRT context。"""

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

    def _copy_outputs_to_host(self, *, prediction_array: Any, proto_array: Any) -> None:
        """把 TensorRT prediction/proto 两个输出从显存拷回主存。"""

        ensure_yolov8_segmentation_cuda_success(
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
        ensure_yolov8_segmentation_cuda_success(
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

    def _ensure_io_buffers(
        self,
        *,
        input_array: Any,
        resolved_prediction_shape: tuple[int, ...],
        resolved_proto_shape: tuple[int, ...],
    ) -> tuple[Any, Any]:
        """按当前输入输出尺寸复用或扩容 TensorRT I/O 缓冲。"""

        prediction_dtype = resolve_yolov8_segmentation_numpy_dtype(
            np_module=self.imports.np,
            dtype_name=self.prediction_dtype_name,
        )
        proto_dtype = resolve_yolov8_segmentation_numpy_dtype(
            np_module=self.imports.np,
            dtype_name=self.proto_dtype_name,
        )
        input_nbytes = int(input_array.nbytes)
        prediction_nbytes = resolve_yolov8_segmentation_tensor_byte_size(
            np_module=self.imports.np,
            shape=resolved_prediction_shape,
            dtype=prediction_dtype,
        )
        proto_nbytes = resolve_yolov8_segmentation_tensor_byte_size(
            np_module=self.imports.np,
            shape=resolved_proto_shape,
            dtype=proto_dtype,
        )

        self.input_device_ptr, self.input_capacity_bytes = self._ensure_device_buffer(
            current_ptr=self.input_device_ptr,
            current_capacity_bytes=self.input_capacity_bytes,
            required_bytes=input_nbytes,
            label="输入",
        )
        self.prediction_device_ptr, self.prediction_capacity_bytes = self._ensure_device_buffer(
            current_ptr=self.prediction_device_ptr,
            current_capacity_bytes=self.prediction_capacity_bytes,
            required_bytes=prediction_nbytes,
            label="prediction 输出",
        )
        self.proto_device_ptr, self.proto_capacity_bytes = self._ensure_device_buffer(
            current_ptr=self.proto_device_ptr,
            current_capacity_bytes=self.proto_capacity_bytes,
            required_bytes=proto_nbytes,
            label="proto 输出",
        )
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

    def _ensure_device_buffer(
        self,
        *,
        current_ptr: int | None,
        current_capacity_bytes: int,
        required_bytes: int,
        label: str,
    ) -> tuple[int, int]:
        """按需扩容单个 TensorRT device buffer。"""

        if current_ptr is not None and required_bytes <= current_capacity_bytes:
            return current_ptr, current_capacity_bytes
        if current_ptr is not None:
            release_yolov8_segmentation_cuda_resource(self.imports.cudart.cudaFree(current_ptr))
        device_ptr = ensure_yolov8_segmentation_cuda_success(
            self.imports.cudart.cudaMalloc(required_bytes),
            operation_name=f"TensorRT segmentation runtime 分配复用{label}显存",
            details={"byte_size": required_bytes},
        )[0]
        return int(device_ptr), int(required_bytes)

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

        if self._should_use_pinned_output_buffer(nbytes):
            return self._ensure_pinned_host_buffer(
                nbytes=nbytes,
                resolved_shape=resolved_shape,
                dtype=dtype,
                host_ptr_attr=host_ptr_attr,
                host_capacity_attr=host_capacity_attr,
                host_array_attr=host_array_attr,
                host_memory_kind_attr=host_memory_kind_attr,
                label=label,
            )
        return self._ensure_pageable_host_buffer(
            resolved_shape=resolved_shape,
            dtype=dtype,
            host_ptr_attr=host_ptr_attr,
            host_capacity_attr=host_capacity_attr,
            host_array_attr=host_array_attr,
            host_memory_kind_attr=host_memory_kind_attr,
        )

    def _ensure_pinned_host_buffer(
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
        """返回可复用的 pinned 输出主存数组。"""

        host_ptr = getattr(self, host_ptr_attr, None)
        host_capacity = int(getattr(self, host_capacity_attr, 0))
        host_array = getattr(self, host_array_attr, None)
        host_memory_kind = str(getattr(self, host_memory_kind_attr, "pageable"))
        if host_ptr is None or nbytes > host_capacity:
            if host_ptr is not None:
                release_yolov8_segmentation_cuda_resource(self.imports.cudart.cudaFreeHost(host_ptr))
            host_ptr = ensure_yolov8_segmentation_cuda_success(
                self.imports.cudart.cudaMallocHost(nbytes),
                operation_name=f"TensorRT segmentation runtime 分配 pinned {label} 输出主存",
                details={"byte_size": nbytes},
            )[0]
            setattr(self, host_ptr_attr, int(host_ptr))
            setattr(self, host_capacity_attr, int(nbytes))
            host_array = None
        if _host_array_needs_rebuild(
            host_array=host_array,
            host_memory_kind=host_memory_kind,
            expected_kind="pinned",
            resolved_shape=resolved_shape,
            dtype=dtype,
        ):
            host_array = build_yolov8_segmentation_numpy_array_from_host_pointer(
                np_module=self.imports.np,
                host_ptr=int(host_ptr),
                byte_size=nbytes,
                dtype=dtype,
                shape=resolved_shape,
            )
        setattr(self, host_array_attr, host_array)
        setattr(self, host_memory_kind_attr, "pinned")
        return host_array

    def _ensure_pageable_host_buffer(
        self,
        *,
        resolved_shape: tuple[int, ...],
        dtype: Any,
        host_ptr_attr: str,
        host_capacity_attr: str,
        host_array_attr: str,
        host_memory_kind_attr: str,
    ) -> Any:
        """返回可复用的 pageable 输出主存数组。"""

        host_ptr = getattr(self, host_ptr_attr, None)
        if host_ptr is not None:
            release_yolov8_segmentation_cuda_resource(self.imports.cudart.cudaFreeHost(host_ptr))
            setattr(self, host_ptr_attr, None)
            setattr(self, host_capacity_attr, 0)
            setattr(self, host_array_attr, None)
        host_array = getattr(self, host_array_attr, None)
        host_memory_kind = str(getattr(self, host_memory_kind_attr, "pageable"))
        if _host_array_needs_rebuild(
            host_array=host_array,
            host_memory_kind=host_memory_kind,
            expected_kind="pageable",
            resolved_shape=resolved_shape,
            dtype=dtype,
        ):
            host_array = self.imports.np.empty(resolved_shape, dtype=dtype)
        setattr(self, host_array_attr, host_array)
        setattr(self, host_memory_kind_attr, "pageable")
        return host_array

    def _should_use_pinned_output_buffer(self, output_nbytes: int) -> bool:
        """判断当前输出 host buffer 是否应该使用 pinned memory。"""

        if not self.pinned_output_buffer_enabled:
            return False
        if int(output_nbytes) <= 0:
            return False
        return int(output_nbytes) <= int(self.pinned_output_buffer_max_bytes)

    @staticmethod
    def _pinned_bytes(
        *,
        host_memory_kind: str,
        host_ptr: int | None,
        host_capacity_bytes: int,
    ) -> int:
        """返回 pinned host buffer 已占用的容量。"""

        if host_memory_kind != "pinned" or host_ptr is None:
            return 0
        return int(host_capacity_bytes)


def _resolve_yolov8_segmentation_output_names(
    *,
    engine: Any,
    tensorrt_module: Any,
) -> tuple[str, str]:
    """从 TensorRT engine 中解析 prediction/proto 输出名称。"""

    output_names = list_yolov8_segmentation_tensorrt_output_names(
        engine=engine,
        tensorrt_module=tensorrt_module,
    )
    if len(output_names) < 2:
        raise ServiceConfigurationError(
            "TensorRT segmentation engine 至少需要 prediction 和 proto 两个输出",
            details={"output_names": output_names},
        )
    prediction_name = "predictions" if "predictions" in output_names else output_names[0]
    remaining_names = [name for name in output_names if name != prediction_name]
    proto_name = "proto" if "proto" in remaining_names else remaining_names[0]
    return prediction_name, proto_name


def _host_array_needs_rebuild(
    *,
    host_array: Any,
    host_memory_kind: str,
    expected_kind: str,
    resolved_shape: tuple[int, ...],
    dtype: Any,
) -> bool:
    """判断 host array 是否需要按当前 shape 或 dtype 重建。"""

    if host_array is None:
        return True
    if host_memory_kind != expected_kind:
        return True
    if tuple(int(dim) for dim in host_array.shape) != resolved_shape:
        return True
    return host_array.dtype != dtype


def _array_nbytes(array: Any | None) -> int:
    """返回 NumPy array 占用字节数，空数组返回 0。"""

    if array is None:
        return 0
    return int(array.nbytes)


__all__ = ["TensorRTYoloV8SegmentationRuntimeSession"]
