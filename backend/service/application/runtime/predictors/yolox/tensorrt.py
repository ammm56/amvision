"""YOLOX TensorRT runtime session。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.yolox_core.postprocess import (
    build_yolox_detection_records,
    postprocess_yolox_prediction_array,
)
from backend.service.application.runtime.predictors.yolox.backend import (
    YoloXCudaInferenceImports as _YoloXCudaInferenceImports,
    ensure_yolox_cuda_success as _ensure_cuda_success,
    get_yolox_tensorrt_logger as _get_tensorrt_logger,
    import_yolox_tensorrt_module as _import_tensorrt_module,
    normalize_yolox_tensor_shape as _normalize_tensor_shape,
    normalize_yolox_tensorrt_outputs as _normalize_tensorrt_outputs,
    release_yolox_cuda_resource as _release_cuda_resource,
    require_yolox_cuda_inference_imports as _require_cuda_inference_imports,
    resolve_yolox_cuda_device_index as _resolve_cuda_device_index,
    resolve_yolox_cuda_runtime_device_name as _resolve_cuda_runtime_device_name,
    resolve_yolox_tensorrt_dtype_name as _resolve_tensorrt_dtype_name,
    resolve_yolox_tensorrt_io_tensor_name as _resolve_tensorrt_io_tensor_name,
)
from backend.service.application.runtime.predictors.yolox.buffer import (
    build_yolox_numpy_array_from_host_pointer as _build_numpy_array_from_host_pointer,
    resolve_yolox_numpy_dtype as _resolve_numpy_dtype,
    resolve_yolox_tensor_byte_size as _resolve_tensor_byte_size,
)
from backend.service.application.runtime.predictors.yolox.contracts import (
    DEFAULT_YOLOX_NMS_THRESHOLD as _DEFAULT_NMS_THRESHOLD,
    RuntimeTensorSpec,
    YoloXPredictionDetection,
    YoloXPredictionExecutionResult,
    YoloXPredictionRequest,
    YoloXRuntimeSessionInfo,
    resolve_yolox_probability as _resolve_probability,
)
from backend.service.application.runtime.predictors.yolox.io import (
    load_yolox_prediction_image as _load_prediction_image,
    preprocess_yolox_image as _preprocess_image,
)
from backend.service.application.runtime.predictors.yolox.preview import (
    render_yolox_preview_image_if_requested,
)
from backend.service.application.runtime.predictors.yolox.timing import (
    is_yolox_debugger_attached as _is_debugger_attached,
    measure_yolox_cuda_event_elapsed_ms as _measure_cuda_event_elapsed_ms,
    measure_yolox_elapsed_ms as _measure_elapsed_ms,
    measure_yolox_stage_elapsed_ms as _measure_stage_elapsed_ms,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.settings import get_backend_service_settings


class TensorRTYoloXRuntimeSession:
    """描述一个已经加载完成并可重复推理的 TensorRT YOLOX 会话。

    属性：
    - dataset_storage：本地文件存储服务。
    - runtime_target：当前会话绑定的运行时快照。
    - imports：TensorRT 推理所需的依赖集合。
    - tensorrt_module：TensorRT 顶层模块。
    - logger：TensorRT logger。
    - runtime：TensorRT runtime 对象。
    - engine：已经反序列化的 TensorRT engine。
    - context：当前 engine 对应的 execution context。
    - device_name：当前执行 device 名称。
    - input_name：模型主输入张量名称。
    - output_name：模型主输出张量名称。
    - input_dtype_name：模型主输入张量 dtype 名称。
    - output_dtype_name：模型主输出张量 dtype 名称。
    - stream：当前 session 复用的 CUDA stream。
    - input_device_ptr：复用的输入显存指针。
    - output_device_ptr：复用的输出显存指针。
    - input_capacity_bytes：当前输入显存缓冲可容纳的字节数。
    - output_capacity_bytes：当前输出显存缓冲可容纳的字节数。
    - pinned_output_buffer_enabled：是否允许为输出 host buffer 启用 pinned memory。
    - pinned_output_buffer_max_bytes：允许使用 pinned output host buffer 的最大字节数。
    - output_host_ptr：当前 pinned 输出主存指针；pageable 模式下为 None。
    - output_host_capacity_bytes：当前 pinned 输出主存缓冲可容纳的字节数。
    - output_host_memory_kind：当前输出 host buffer 类型，只会是 pinned 或 pageable。
    - output_host_array：复用的输出主存 NumPy 视图。
    - execute_start_event：用于统计 TensorRT 纯 GPU 执行时间的 CUDA event。
    - execute_end_event：用于统计 TensorRT 纯 GPU 执行时间的 CUDA event。
    """

    def __init__(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        imports: _YoloXCudaInferenceImports,
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
        """初始化一个已加载完成的 TensorRT runtime session。

        参数：
        - dataset_storage：本地文件存储服务。
        - runtime_target：当前会话绑定的运行时快照。
        - imports：TensorRT 推理依赖集合。
        - tensorrt_module：TensorRT 顶层模块。
        - logger：TensorRT logger。
        - runtime：TensorRT runtime 对象。
        - engine：已经反序列化的 TensorRT engine。
        - context：当前 engine 对应的 execution context。
        - device_name：当前执行 device 名称。
        - input_name：模型主输入张量名称。
        - output_name：模型主输出张量名称。
        - input_dtype_name：模型主输入张量 dtype 名称。
        - output_dtype_name：模型主输出张量 dtype 名称。
        - stream：当前 session 复用的 CUDA stream。
        - execute_start_event：用于统计 TensorRT 纯 GPU 执行时间的 CUDA event。
        - execute_end_event：用于统计 TensorRT 纯 GPU 执行时间的 CUDA event。
        - pinned_output_buffer_enabled：是否允许为输出 host buffer 启用 pinned memory；None 表示读取统一配置默认值。
        - pinned_output_buffer_max_bytes：允许使用 pinned output host buffer 的最大字节数；None 表示读取统一配置默认值。
        """

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
    ) -> TensorRTYoloXRuntimeSession:
        """加载一次 TensorRT runtime session。

        参数：
        - dataset_storage：本地文件存储服务。
        - runtime_target：待加载的运行时快照。
        - pinned_output_buffer_enabled：是否允许为输出 host buffer 启用 pinned memory；None 表示读取统一配置默认值。
        - pinned_output_buffer_max_bytes：允许使用 pinned output host buffer 的最大字节数；None 表示读取统一配置默认值。

        返回：
        - TensorRTYoloXRuntimeSession：已完成 engine 加载的会话对象。
        """

        if runtime_target.runtime_backend != "tensorrt":
            raise InvalidRequestError(
                "当前 predictor 仅支持 tensorrt runtime_backend",
                details={
                    "runtime_backend": runtime_target.runtime_backend,
                    "model_build_id": runtime_target.model_build_id,
                },
            )

        imports = _require_cuda_inference_imports()
        tensorrt_module = _import_tensorrt_module()
        device_name = _resolve_cuda_runtime_device_name(
            cudart_module=imports.cudart,
            requested_device_name=runtime_target.device_name,
        )
        _ensure_cuda_success(
            imports.cudart.cudaSetDevice(_resolve_cuda_device_index(device_name)),
            operation_name="TensorRT runtime 切换 CUDA device",
            details={"device_name": device_name},
        )
        logger = _get_tensorrt_logger(
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
        stream = _ensure_cuda_success(
            imports.cudart.cudaStreamCreate(),
            operation_name="TensorRT runtime 创建复用 CUDA stream",
            details={"device_name": device_name},
        )[0]
        execute_start_event = _ensure_cuda_success(
            imports.cudart.cudaEventCreate(),
            operation_name="TensorRT runtime 创建执行起点 event",
            details={"device_name": device_name},
        )[0]
        execute_end_event = _ensure_cuda_success(
            imports.cudart.cudaEventCreate(),
            operation_name="TensorRT runtime 创建执行终点 event",
            details={"device_name": device_name},
        )[0]
        input_name = _resolve_tensorrt_io_tensor_name(
            engine=engine,
            tensorrt_module=tensorrt_module,
            io_mode=tensorrt_module.TensorIOMode.INPUT,
            fallback="images",
        )
        output_name = _resolve_tensorrt_io_tensor_name(
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
            input_dtype_name=_resolve_tensorrt_dtype_name(
                tensorrt_module=tensorrt_module,
                tensor_dtype=engine.get_tensor_dtype(input_name),
                fallback="float32",
            ),
            output_dtype_name=_resolve_tensorrt_dtype_name(
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
            _release_cuda_resource(
                self.imports.cudart.cudaSetDevice(_resolve_cuda_device_index(self.device_name))
            )
        except Exception:
            return
        if self.input_device_ptr is not None:
            _release_cuda_resource(self.imports.cudart.cudaFree(self.input_device_ptr))
            self.input_device_ptr = None
            self.input_capacity_bytes = 0
        if self.output_device_ptr is not None:
            _release_cuda_resource(self.imports.cudart.cudaFree(self.output_device_ptr))
            self.output_device_ptr = None
            self.output_capacity_bytes = 0
        if self.output_host_ptr is not None:
            _release_cuda_resource(self.imports.cudart.cudaFreeHost(self.output_host_ptr))
            self.output_host_ptr = None
            self.output_host_capacity_bytes = 0
            self.output_host_array = None
        self.output_host_memory_kind = "pageable"
        if self.stream is not None:
            _release_cuda_resource(self.imports.cudart.cudaStreamDestroy(self.stream))
            self.stream = None
        if self.execute_start_event is not None:
            _release_cuda_resource(self.imports.cudart.cudaEventDestroy(self.execute_start_event))
            self.execute_start_event = None
        if self.execute_end_event is not None:
            _release_cuda_resource(self.imports.cudart.cudaEventDestroy(self.execute_end_event))
            self.execute_end_event = None
        self.output_host_array = None

    def describe_memory_usage(self) -> dict[str, object]:
        """返回当前 TensorRT session 的输出 host buffer 占用快照。

        返回：
        - dict[str, object]：包含输出 host buffer 类型、总字节数和 pinned 字节数的快照。
        """

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

    def predict(self, request: YoloXPredictionRequest) -> YoloXPredictionExecutionResult:
        """使用当前常驻会话执行一次 TensorRT 单图预测。

        参数：
        - request：预测请求。

        返回：
        - YoloXPredictionExecutionResult：预测执行结果。
        """

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
        input_array = self.imports.np.expand_dims(input_tensor, axis=0).astype(
            _resolve_numpy_dtype(
                np_module=self.imports.np,
                dtype_name=self.input_dtype_name,
            ),
            copy=False,
        )
        requested_input_shape = tuple(int(dim) for dim in input_array.shape)
        preprocess_ms = round((perf_counter() - preprocess_started_at) * 1000, 3)

        nms_threshold = _resolve_probability(
            value=request.extra_options.get("nms_threshold"),
            field_name="nms_threshold",
            default=_DEFAULT_NMS_THRESHOLD,
        )

        infer_started_at = perf_counter()
        device_index = _resolve_cuda_device_index(self.device_name)
        set_device_started_at = perf_counter()
        _ensure_cuda_success(
            self.imports.cudart.cudaSetDevice(device_index),
            operation_name="TensorRT runtime 绑定 CUDA device",
            details={"device_name": self.device_name},
        )
        infer_set_device_ms = _measure_elapsed_ms(set_device_started_at)

        prepare_io_started_at = perf_counter()
        engine_input_shape = _normalize_tensor_shape(self.engine.get_tensor_shape(self.input_name))
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

        resolved_output_shape = _normalize_tensor_shape(self.context.get_tensor_shape(self.output_name))
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
        infer_prepare_io_ms = _measure_elapsed_ms(prepare_io_started_at)

        enqueue_h2d_started_at = perf_counter()
        _ensure_cuda_success(
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
        infer_enqueue_h2d_ms = _measure_elapsed_ms(enqueue_h2d_started_at)

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
        infer_bind_tensor_ms = _measure_elapsed_ms(bind_tensor_started_at)

        execute_enqueue_started_at = perf_counter()
        _ensure_cuda_success(
            self.imports.cudart.cudaEventRecord(self.execute_start_event, self.stream),
            operation_name="TensorRT runtime 记录执行起点 event",
            details={"device_name": self.device_name},
        )
        execute_result = self.context.execute_async_v3(stream_handle=self.stream)
        if execute_result is not True:
            raise ServiceConfigurationError(
                "TensorRT execution context 执行推理失败",
                details={"model_build_id": self.runtime_target.model_build_id},
            )
        _ensure_cuda_success(
            self.imports.cudart.cudaEventRecord(self.execute_end_event, self.stream),
            operation_name="TensorRT runtime 记录执行终点 event",
            details={"device_name": self.device_name},
        )
        infer_execute_enqueue_ms = _measure_elapsed_ms(execute_enqueue_started_at)

        enqueue_d2h_started_at = perf_counter()
        _ensure_cuda_success(
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
        infer_enqueue_d2h_host_ms = _measure_elapsed_ms(enqueue_d2h_started_at)

        output_ready_wait_started_at = perf_counter()
        _ensure_cuda_success(
            self.imports.cudart.cudaStreamSynchronize(self.stream),
            operation_name="TensorRT runtime 同步 CUDA stream",
            details={"device_name": self.device_name},
        )
        infer_output_ready_wait_ms = _measure_elapsed_ms(output_ready_wait_started_at)
        infer_execute_gpu_ms = _measure_cuda_event_elapsed_ms(
            cudart_module=self.imports.cudart,
            start_event=self.execute_start_event,
            end_event=self.execute_end_event,
            device_name=self.device_name,
        )
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        image_height = int(image.shape[0])
        image_width = int(image.shape[1])

        postprocess_started_at = perf_counter()
        predictions = postprocess_yolox_prediction_array(
            prediction_array=_normalize_tensorrt_outputs(
                output_array=output_array,
                imports=self.imports,
            ),
            np_module=self.imports.np,
            num_classes=len(self.runtime_target.labels),
            conf_thre=request.score_threshold,
            nms_thre=nms_threshold,
        )
        detections = build_yolox_detection_records(
            np_module=self.imports.np,
            predictions=predictions,
            resize_ratio=resize_ratio,
            labels=self.runtime_target.labels,
            image_width=image_width,
            image_height=image_height,
            detection_factory=YoloXPredictionDetection,
        )
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = render_yolox_preview_image_if_requested(
            cv2_module=self.imports.cv2,
            image=image,
            detections=detections,
            save_result_image=request.save_result_image,
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
                    shape=requested_input_shape,
                    dtype=self.input_dtype_name,
                ),
                output_spec=RuntimeTensorSpec(
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
                    "output_host_memory_kind": self.output_host_memory_kind,
                    "output_host_buffer_bytes": int(output_array.nbytes),
                    "output_host_pinned_enabled": self.pinned_output_buffer_enabled,
                    "output_host_pinned_max_bytes": self.pinned_output_buffer_max_bytes,
                    "tensorrt_version": str(self.tensorrt_module.__version__),
                    "compiled_runtime_precision": self.runtime_target.runtime_precision,
                    "engine_file_bytes": self.runtime_target.runtime_artifact_path.stat().st_size,
                    "debugger_attached": _is_debugger_attached(),
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

        output_dtype = _resolve_numpy_dtype(
            np_module=self.imports.np,
            dtype_name=self.output_dtype_name,
        )
        input_nbytes = int(input_array.nbytes)
        output_nbytes = _resolve_tensor_byte_size(
            np_module=self.imports.np,
            shape=resolved_output_shape,
            dtype=output_dtype,
        )
        if self.input_device_ptr is None or input_nbytes > self.input_capacity_bytes:
            if self.input_device_ptr is not None:
                _release_cuda_resource(self.imports.cudart.cudaFree(self.input_device_ptr))
            self.input_device_ptr = _ensure_cuda_success(
                self.imports.cudart.cudaMalloc(input_nbytes),
                operation_name="TensorRT runtime 分配复用输入显存",
                details={"byte_size": input_nbytes},
            )[0]
            self.input_capacity_bytes = input_nbytes
        if self.output_device_ptr is None or output_nbytes > self.output_capacity_bytes:
            if self.output_device_ptr is not None:
                _release_cuda_resource(self.imports.cudart.cudaFree(self.output_device_ptr))
            self.output_device_ptr = _ensure_cuda_success(
                self.imports.cudart.cudaMalloc(output_nbytes),
                operation_name="TensorRT runtime 分配复用输出显存",
                details={"byte_size": output_nbytes},
            )[0]
            self.output_capacity_bytes = output_nbytes
        if self._should_use_pinned_output_buffer(output_nbytes):
            if self.output_host_ptr is None or output_nbytes > self.output_host_capacity_bytes:
                if self.output_host_ptr is not None:
                    _release_cuda_resource(self.imports.cudart.cudaFreeHost(self.output_host_ptr))
                self.output_host_ptr = _ensure_cuda_success(
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
                self.output_host_array = _build_numpy_array_from_host_pointer(
                    np_module=self.imports.np,
                    host_ptr=int(self.output_host_ptr),
                    byte_size=output_nbytes,
                    dtype=output_dtype,
                    shape=resolved_output_shape,
                )
            self.output_host_memory_kind = "pinned"
            return self.output_host_array

        if self.output_host_ptr is not None:
            _release_cuda_resource(self.imports.cudart.cudaFreeHost(self.output_host_ptr))
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
        """判断当前输出 host buffer 是否应该使用 pinned memory。

        参数：
        - output_nbytes：当前输出张量需要的总字节数。

        返回：
        - bool：True 表示允许使用 pinned output host buffer；False 表示回退到 pageable memory。
        """

        if not self.pinned_output_buffer_enabled:
            return False
        return int(output_nbytes) <= int(self.pinned_output_buffer_max_bytes)
