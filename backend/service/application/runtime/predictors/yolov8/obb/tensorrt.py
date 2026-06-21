"""YOLOv8 OBB TensorRT runtime session。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.runtime.predictors.yolov8.obb.backend import (
    ensure_yolov8_obb_cuda_success,
    get_yolov8_obb_tensorrt_logger,
    import_yolov8_obb_tensorrt_module,
    normalize_yolov8_obb_outputs_for_backend,
    normalize_yolov8_obb_tensor_shape,
    release_yolov8_obb_cuda_resource,
    require_yolov8_obb_cuda_imports,
    resolve_yolov8_obb_cuda_device_index,
    resolve_yolov8_obb_cuda_runtime_device_name,
    resolve_yolov8_obb_tensorrt_dtype_name,
    resolve_yolov8_obb_tensorrt_io_tensor_name,
)
from backend.service.application.runtime.predictors.yolov8.obb.buffer import (
    build_yolov8_obb_numpy_array_from_host_pointer,
    resolve_yolov8_obb_numpy_dtype,
    resolve_yolov8_obb_tensor_byte_size,
)
from backend.service.application.runtime.predictors.yolov8.obb.contracts import (
    YoloV8ObbPredictionExecutionResult,
    YoloV8ObbPredictionRequest,
    YoloV8ObbRuntimeSessionInfo,
    YoloV8ObbRuntimeTensorSpec,
)
from backend.service.application.runtime.predictors.yolov8.obb.io import (
    load_yolov8_obb_prediction_image,
    preprocess_yolov8_obb_image,
)
from backend.service.application.runtime.predictors.yolov8.obb.postprocess import (
    build_yolov8_obb_runtime_instances,
)
from backend.service.application.runtime.predictors.yolov8.obb.preview import (
    render_yolov8_obb_preview_image_if_requested,
)
from backend.service.application.runtime.predictors.yolov8.obb.timing import (
    is_yolov8_obb_debugger_attached,
    measure_yolov8_obb_cuda_event_elapsed_ms,
    measure_yolov8_obb_stage_elapsed_ms,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.settings import get_backend_service_settings


class TensorRTYoloV8ObbRuntimeSession:
    """已经加载完成并可重复推理的 TensorRT YOLOv8 OBB 会话。"""

    model_type = "yolov8"
    model_label = "YOLOv8"
    task_type = "obb"

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
        """初始化 TensorRT YOLOv8 OBB 会话。"""

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
    ) -> "TensorRTYoloV8ObbRuntimeSession":
        """加载一套 TensorRT YOLOv8 OBB 会话。"""

        if runtime_target.runtime_backend != "tensorrt":
            raise InvalidRequestError(
                "当前 YOLOv8 OBB predictor 仅支持 tensorrt runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(
                "当前 YOLOv8 OBB predictor 收到了错误的 task_type",
                details={"task_type": runtime_target.task_type},
            )
        imports = require_yolov8_obb_cuda_imports()
        tensorrt_module = import_yolov8_obb_tensorrt_module()
        device_name = resolve_yolov8_obb_cuda_runtime_device_name(
            cudart_module=imports.cudart,
            requested_device_name=runtime_target.device_name,
        )
        ensure_yolov8_obb_cuda_success(
            imports.cudart.cudaSetDevice(resolve_yolov8_obb_cuda_device_index(device_name)),
            operation_name="TensorRT OBB runtime 切换 CUDA device",
            details={"device_name": device_name},
        )
        logger = get_yolov8_obb_tensorrt_logger(
            tensorrt_module=tensorrt_module,
            severity=tensorrt_module.Logger.WARNING,
        )
        runtime = tensorrt_module.Runtime(logger)
        engine = runtime.deserialize_cuda_engine(runtime_target.runtime_artifact_path.read_bytes())
        if engine is None:
            raise ServiceConfigurationError(
                "TensorRT OBB engine 反序列化失败",
                details={"model_build_id": runtime_target.model_build_id},
            )
        context = engine.create_execution_context()
        if context is None:
            raise ServiceConfigurationError(
                "TensorRT OBB engine 无法创建 execution context",
                details={"model_build_id": runtime_target.model_build_id},
            )
        stream = ensure_yolov8_obb_cuda_success(
            imports.cudart.cudaStreamCreate(),
            operation_name="TensorRT OBB runtime 创建复用 CUDA stream",
            details={"device_name": device_name},
        )[0]
        execute_start_event = ensure_yolov8_obb_cuda_success(
            imports.cudart.cudaEventCreate(),
            operation_name="TensorRT OBB runtime 创建执行起点 event",
            details={"device_name": device_name},
        )[0]
        execute_end_event = ensure_yolov8_obb_cuda_success(
            imports.cudart.cudaEventCreate(),
            operation_name="TensorRT OBB runtime 创建执行终点 event",
            details={"device_name": device_name},
        )[0]
        input_name = resolve_yolov8_obb_tensorrt_io_tensor_name(
            engine=engine,
            tensorrt_module=tensorrt_module,
            io_mode=tensorrt_module.TensorIOMode.INPUT,
            fallback="images",
        )
        output_name = resolve_yolov8_obb_tensorrt_io_tensor_name(
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
            input_dtype_name=resolve_yolov8_obb_tensorrt_dtype_name(
                tensorrt_module=tensorrt_module,
                tensor_dtype=engine.get_tensor_dtype(input_name),
                fallback="float32",
            ),
            output_dtype_name=resolve_yolov8_obb_tensorrt_dtype_name(
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

    def predict(self, request: YoloV8ObbPredictionRequest) -> YoloV8ObbPredictionExecutionResult:
        """执行一次 TensorRT YOLOv8 OBB 预测。"""

        decode_started_at = perf_counter()
        image = load_yolov8_obb_prediction_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = measure_yolov8_obb_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=decode_started_at,
        )
        preprocess_started_at = perf_counter()
        input_tensor, resize_ratio = preprocess_yolov8_obb_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            image=image,
            input_size=self.runtime_target.input_size,
        )
        input_array = self.imports.np.expand_dims(input_tensor, axis=0).astype(
            resolve_yolov8_obb_numpy_dtype(
                np_module=self.imports.np,
                dtype_name=self.input_dtype_name,
            ),
            copy=False,
        )
        requested_input_shape = tuple(int(dim) for dim in input_array.shape)
        preprocess_ms = measure_yolov8_obb_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=preprocess_started_at,
        )

        infer_started_at = perf_counter()
        ensure_yolov8_obb_cuda_success(
            self.imports.cudart.cudaSetDevice(resolve_yolov8_obb_cuda_device_index(self.device_name)),
            operation_name="TensorRT OBB runtime 绑定 CUDA device",
            details={"device_name": self.device_name},
        )
        self._set_or_validate_input_shape(requested_input_shape)
        resolved_output_shape = self._resolve_output_shape()
        output_array = self._ensure_io_buffers(
            input_array=input_array,
            resolved_output_shape=resolved_output_shape,
        )
        ensure_yolov8_obb_cuda_success(
            self.imports.cudart.cudaMemcpyAsync(
                self.input_device_ptr,
                int(input_array.ctypes.data),
                int(input_array.nbytes),
                self.imports.cudart.cudaMemcpyKind.cudaMemcpyHostToDevice,
                self.stream,
            ),
            operation_name="TensorRT OBB runtime 拷贝输入到显存",
            details={"input_name": self.input_name, "byte_size": int(input_array.nbytes)},
        )
        self._bind_io_tensor_addresses()
        ensure_yolov8_obb_cuda_success(
            self.imports.cudart.cudaEventRecord(self.execute_start_event, self.stream),
            operation_name="TensorRT OBB runtime 记录执行起点 event",
            details={"device_name": self.device_name},
        )
        if self.context.execute_async_v3(stream_handle=self.stream) is not True:
            raise ServiceConfigurationError(
                "TensorRT OBB execution context 执行推理失败",
                details={"model_build_id": self.runtime_target.model_build_id},
            )
        ensure_yolov8_obb_cuda_success(
            self.imports.cudart.cudaEventRecord(self.execute_end_event, self.stream),
            operation_name="TensorRT OBB runtime 记录执行终点 event",
            details={"device_name": self.device_name},
        )
        ensure_yolov8_obb_cuda_success(
            self.imports.cudart.cudaMemcpyAsync(
                int(output_array.ctypes.data),
                self.output_device_ptr,
                int(output_array.nbytes),
                self.imports.cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost,
                self.stream,
            ),
            operation_name="TensorRT OBB runtime 拷贝输出到主存",
            details={"output_name": self.output_name, "byte_size": int(output_array.nbytes)},
        )
        ensure_yolov8_obb_cuda_success(
            self.imports.cudart.cudaStreamSynchronize(self.stream),
            operation_name="TensorRT OBB runtime 同步 CUDA stream",
            details={"device_name": self.device_name},
        )
        infer_execute_gpu_ms = measure_yolov8_obb_cuda_event_elapsed_ms(
            cudart_module=self.imports.cudart,
            start_event=self.execute_start_event,
            end_event=self.execute_end_event,
            device_name=self.device_name,
        )
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        postprocess_started_at = perf_counter()
        prediction_array = normalize_yolov8_obb_outputs_for_backend(
            outputs=[output_array],
            np_module=self.imports.np,
        )
        instances = build_yolov8_obb_runtime_instances(
            np_module=self.imports.np,
            prediction_array=prediction_array,
            labels=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            resize_ratio=resize_ratio,
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
        )
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms
        preview_image_bytes = render_yolov8_obb_preview_image_if_requested(
            cv2_module=self.imports.cv2,
            image=image,
            instances=instances,
            save_result_image=request.save_result_image,
        )
        return YoloV8ObbPredictionExecutionResult(
            instances=instances,
            latency_ms=round(latency_ms, 3),
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=YoloV8ObbRuntimeSessionInfo(
                backend_name=self.runtime_target.runtime_backend,
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=YoloV8ObbRuntimeTensorSpec(
                    name=self.input_name,
                    shape=requested_input_shape,
                    dtype=self.input_dtype_name,
                ),
                output_specs=(
                    YoloV8ObbRuntimeTensorSpec(
                        name=self.output_name,
                        shape=resolved_output_shape,
                        dtype=self.output_dtype_name,
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
                    "class_count": len(self.runtime_target.labels),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                    "infer_execute_gpu_ms": infer_execute_gpu_ms,
                    "tensorrt_version": str(self.tensorrt_module.__version__),
                    "engine_file_bytes": self.runtime_target.runtime_artifact_path.stat().st_size,
                    "debugger_attached": is_yolov8_obb_debugger_attached(),
                    **self.describe_memory_usage(),
                },
            ),
        )

    def close(self) -> None:
        """释放 TensorRT OBB session 持有的 CUDA 资源。"""

        try:
            release_yolov8_obb_cuda_resource(
                self.imports.cudart.cudaSetDevice(
                    resolve_yolov8_obb_cuda_device_index(self.device_name)
                )
            )
        except Exception:
            return
        if self.input_device_ptr is not None:
            release_yolov8_obb_cuda_resource(self.imports.cudart.cudaFree(self.input_device_ptr))
            self.input_device_ptr = None
            self.input_capacity_bytes = 0
        if self.output_device_ptr is not None:
            release_yolov8_obb_cuda_resource(self.imports.cudart.cudaFree(self.output_device_ptr))
            self.output_device_ptr = None
            self.output_capacity_bytes = 0
        if self.output_host_ptr is not None:
            release_yolov8_obb_cuda_resource(self.imports.cudart.cudaFreeHost(self.output_host_ptr))
            self.output_host_ptr = None
            self.output_host_capacity_bytes = 0
            self.output_host_array = None
        self.output_host_memory_kind = "pageable"
        if self.stream is not None:
            release_yolov8_obb_cuda_resource(self.imports.cudart.cudaStreamDestroy(self.stream))
            self.stream = None
        if self.execute_start_event is not None:
            release_yolov8_obb_cuda_resource(self.imports.cudart.cudaEventDestroy(self.execute_start_event))
            self.execute_start_event = None
        if self.execute_end_event is not None:
            release_yolov8_obb_cuda_resource(self.imports.cudart.cudaEventDestroy(self.execute_end_event))
            self.execute_end_event = None
        self.output_host_array = None

    def describe_memory_usage(self) -> dict[str, object]:
        """返回当前 TensorRT OBB session 的输出 host buffer 占用快照。"""

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

    def _set_or_validate_input_shape(self, requested_input_shape: tuple[int, ...]) -> None:
        """设置或校验 TensorRT execution context 输入 shape。"""

        engine_input_shape = normalize_yolov8_obb_tensor_shape(
            self.engine.get_tensor_shape(self.input_name)
        )
        if any(dim < 0 for dim in engine_input_shape):
            shape_set_result = self.context.set_input_shape(self.input_name, requested_input_shape)
            if shape_set_result is not True:
                raise ServiceConfigurationError(
                    "TensorRT OBB execution context 设置输入 shape 失败",
                    details={"requested_input_shape": list(requested_input_shape)},
                )
        elif engine_input_shape != requested_input_shape:
            raise InvalidRequestError(
                "TensorRT OBB engine 输入尺寸与 runtime input_size 不一致",
                details={
                    "engine_input_shape": list(engine_input_shape),
                    "requested_input_shape": list(requested_input_shape),
                },
            )

    def _resolve_output_shape(self) -> tuple[int, ...]:
        """读取 TensorRT 输出 shape 并校验为正整数。"""

        resolved_output_shape = normalize_yolov8_obb_tensor_shape(
            self.context.get_tensor_shape(self.output_name)
        )
        if not resolved_output_shape or any(dim <= 0 for dim in resolved_output_shape):
            raise ServiceConfigurationError(
                "TensorRT OBB execution context 返回了无效输出 shape",
                details={"output_name": self.output_name, "output_shape": list(resolved_output_shape)},
            )
        return resolved_output_shape

    def _bind_io_tensor_addresses(self) -> None:
        """把输入和输出 tensor address 绑定到 TensorRT context。"""

        if self.context.set_tensor_address(self.input_name, int(self.input_device_ptr)) is not True:
            raise ServiceConfigurationError("TensorRT OBB execution context 绑定输入张量失败")
        if self.context.set_tensor_address(self.output_name, int(self.output_device_ptr)) is not True:
            raise ServiceConfigurationError("TensorRT OBB execution context 绑定输出张量失败")

    def _ensure_io_buffers(self, *, input_array: Any, resolved_output_shape: tuple[int, ...]) -> Any:
        """按当前输入输出尺寸复用或扩容 TensorRT I/O 缓冲。"""

        output_dtype = resolve_yolov8_obb_numpy_dtype(
            np_module=self.imports.np,
            dtype_name=self.output_dtype_name,
        )
        input_nbytes = int(input_array.nbytes)
        output_nbytes = resolve_yolov8_obb_tensor_byte_size(
            np_module=self.imports.np,
            shape=resolved_output_shape,
            dtype=output_dtype,
        )
        self.input_device_ptr, self.input_capacity_bytes = self._ensure_device_buffer(
            current_ptr=self.input_device_ptr,
            current_capacity_bytes=self.input_capacity_bytes,
            required_bytes=input_nbytes,
            label="输入",
        )
        self.output_device_ptr, self.output_capacity_bytes = self._ensure_device_buffer(
            current_ptr=self.output_device_ptr,
            current_capacity_bytes=self.output_capacity_bytes,
            required_bytes=output_nbytes,
            label="输出",
        )
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
            release_yolov8_obb_cuda_resource(self.imports.cudart.cudaFree(current_ptr))
        device_ptr = ensure_yolov8_obb_cuda_success(
            self.imports.cudart.cudaMalloc(required_bytes),
            operation_name=f"TensorRT OBB runtime 分配复用{label}显存",
            details={"byte_size": required_bytes},
        )[0]
        return int(device_ptr), int(required_bytes)

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
                release_yolov8_obb_cuda_resource(self.imports.cudart.cudaFreeHost(self.output_host_ptr))
            self.output_host_ptr = ensure_yolov8_obb_cuda_success(
                self.imports.cudart.cudaMallocHost(output_nbytes),
                operation_name="TensorRT OBB runtime 分配 pinned 输出主存",
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
            self.output_host_array = build_yolov8_obb_numpy_array_from_host_pointer(
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
            release_yolov8_obb_cuda_resource(self.imports.cudart.cudaFreeHost(self.output_host_ptr))
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
        if int(output_nbytes) <= 0:
            return False
        return int(output_nbytes) <= int(self.pinned_output_buffer_max_bytes)


__all__ = ["TensorRTYoloV8ObbRuntimeSession"]
