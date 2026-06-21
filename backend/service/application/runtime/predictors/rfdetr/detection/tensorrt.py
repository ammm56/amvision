"""RF-DETR detection TensorRT runtime session。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.rfdetr_core.runtime import (
    build_rfdetr_runtime_postprocess_model,
    resolve_rfdetr_runtime_input_size,
    resolve_rfdetr_runtime_output_names,
)
from backend.service.application.runtime.contracts.detection.prediction import (
    DetectionPredictionExecutionResult,
    DetectionPredictionRequest,
    DetectionRuntimeTensorSpec,
)
from backend.service.application.runtime.predictors.rfdetr.detection.result import (
    build_rfdetr_detection_result,
    build_rfdetr_detections,
    postprocess_rfdetr_detection_outputs,
)
from backend.service.application.runtime.predictors.rfdetr.io import (
    build_rfdetr_input_array,
    load_rfdetr_runtime_input_image,
)
from backend.service.application.runtime.predictors.rfdetr.tensorrt import (
    list_rfdetr_tensorrt_output_names,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.application.runtime.support.detection import (
    ensure_cuda_success,
    get_tensorrt_logger,
    import_tensorrt_module,
    measure_cuda_event_elapsed_ms,
    normalize_tensor_shape,
    require_cuda_inference_imports,
    resolve_cuda_device_index,
    resolve_cuda_runtime_device_name,
    resolve_numpy_dtype,
    resolve_tensorrt_dtype_name,
    resolve_tensorrt_io_tensor_name,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class TensorRTRfdetrRuntimeSession:
    """已经加载完成并可重复推理的 TensorRT RF-DETR 会话。"""

    model_type = "rfdetr"
    model_label = "RF-DETR"
    task_type = "detection"

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
        all_output_names: tuple[str, ...],
        output_names: tuple[str, str],
        input_dtype_name: str,
        all_output_dtype_names: tuple[str, ...],
        output_dtype_names: tuple[str, str],
        stream: Any,
        execute_start_event: Any,
        execute_end_event: Any,
        postprocess_model: Any,
        input_size: tuple[int, int],
    ) -> None:
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
        self.all_output_names = all_output_names
        self.output_names = output_names
        self.input_dtype_name = input_dtype_name
        self.all_output_dtype_names = all_output_dtype_names
        self.output_dtype_names = output_dtype_names
        self.stream = stream
        self.execute_start_event = execute_start_event
        self.execute_end_event = execute_end_event
        self.postprocess_model = postprocess_model
        self.input_size = input_size

    def __del__(self) -> None:
        try:
            ensure_cuda_success(
                self.imports.cudart.cudaSetDevice(resolve_cuda_device_index(self.device_name)),
                operation_name="TensorRT RF-DETR runtime 释放前绑定 CUDA device",
                details={"device_name": self.device_name},
            )
        except Exception:
            return
        for event_name in ("execute_start_event", "execute_end_event"):
            event = getattr(self, event_name, None)
            if event is not None:
                try:
                    self.imports.cudart.cudaEventDestroy(event)
                except Exception:
                    pass
        stream = getattr(self, "stream", None)
        if stream is not None:
            try:
                self.imports.cudart.cudaStreamDestroy(stream)
            except Exception:
                pass

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
    ) -> "TensorRTRfdetrRuntimeSession":
        if runtime_target.runtime_backend != "tensorrt":
            raise InvalidRequestError(
                "RF-DETR predictor 仅支持 tensorrt",
                details={"runtime_backend": runtime_target.runtime_backend},
            )

        import torch

        cuda_imports = require_cuda_inference_imports()
        tensorrt_module = import_tensorrt_module()
        device_name = resolve_cuda_runtime_device_name(
            cudart_module=cuda_imports.cudart,
            requested_device_name=runtime_target.device_name,
        )
        ensure_cuda_success(
            cuda_imports.cudart.cudaSetDevice(resolve_cuda_device_index(device_name)),
            operation_name="TensorRT RF-DETR runtime 切换 CUDA device",
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
                "TensorRT RF-DETR engine 反序列化失败",
                details={"model_build_id": runtime_target.model_build_id},
            )
        context = engine.create_execution_context()
        if context is None:
            raise ServiceConfigurationError(
                "TensorRT RF-DETR engine 无法创建 execution context",
                details={"model_build_id": runtime_target.model_build_id},
            )
        stream = ensure_cuda_success(
            cuda_imports.cudart.cudaStreamCreate(),
            operation_name="TensorRT RF-DETR runtime 创建 CUDA stream",
            details={"device_name": device_name},
        )[0]
        execute_start_event = ensure_cuda_success(
            cuda_imports.cudart.cudaEventCreate(),
            operation_name="TensorRT RF-DETR runtime 创建执行起点 event",
            details={"device_name": device_name},
        )[0]
        execute_end_event = ensure_cuda_success(
            cuda_imports.cudart.cudaEventCreate(),
            operation_name="TensorRT RF-DETR runtime 创建执行终点 event",
            details={"device_name": device_name},
        )[0]
        input_name = resolve_tensorrt_io_tensor_name(
            engine=engine,
            tensorrt_module=tensorrt_module,
            io_mode=tensorrt_module.TensorIOMode.INPUT,
            fallback="images",
        )
        all_output_names = tuple(
            list_rfdetr_tensorrt_output_names(engine, tensorrt_module=tensorrt_module)
        )
        if len(all_output_names) < 2:
            raise ServiceConfigurationError(
                "TensorRT RF-DETR engine 输出数量不足",
                details={"output_count": len(all_output_names)},
            )
        output_names = resolve_rfdetr_runtime_output_names(
            task_type=runtime_target.task_type,
            output_names=all_output_names,
        )
        imports = type(
            "_RfdetrTensorRTPredictorImports",
            (),
            {
                "cv2": cuda_imports.cv2,
                "np": cuda_imports.np,
                "cudart": cuda_imports.cudart,
                "torch": torch,
            },
        )()
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
            all_output_names=all_output_names,
            output_names=output_names,
            input_dtype_name=resolve_tensorrt_dtype_name(
                tensorrt_module=tensorrt_module,
                tensor_dtype=engine.get_tensor_dtype(input_name),
                fallback="float32",
            ),
            all_output_dtype_names=tuple(
                resolve_tensorrt_dtype_name(
                    tensorrt_module=tensorrt_module,
                    tensor_dtype=engine.get_tensor_dtype(name),
                    fallback="float32",
                )
                for name in all_output_names
            ),
            output_dtype_names=tuple(
                resolve_tensorrt_dtype_name(
                    tensorrt_module=tensorrt_module,
                    tensor_dtype=engine.get_tensor_dtype(name),
                    fallback="float32",
                )
                for name in output_names
            ),
            stream=stream,
            execute_start_event=execute_start_event,
            execute_end_event=execute_end_event,
            postprocess_model=build_rfdetr_runtime_postprocess_model(
                task_type=runtime_target.task_type,
            ),
            input_size=resolve_rfdetr_runtime_input_size(
                task_type=runtime_target.task_type,
                model_scale=runtime_target.model_scale,
                input_size=runtime_target.input_size,
            ),
        )

    def predict(self, request: DetectionPredictionRequest) -> DetectionPredictionExecutionResult:
        return _predict_tensorrt(self, request)


def _predict_tensorrt(
    session_obj: TensorRTRfdetrRuntimeSession,
    request: DetectionPredictionRequest,
) -> DetectionPredictionExecutionResult:
    imports = session_obj.imports
    image, decode_ms = load_rfdetr_runtime_input_image(
        cv2_module=imports.cv2,
        np_module=imports.np,
        dataset_storage=session_obj.dataset_storage,
        request=request,
    )
    input_array, preprocess_ms = build_rfdetr_input_array(
        cv2_module=imports.cv2,
        np_module=imports.np,
        image=image,
        input_size=session_obj.input_size,
    )
    input_array = input_array.astype(
        resolve_numpy_dtype(np_module=imports.np, dtype_name=session_obj.input_dtype_name),
        copy=False,
    )
    requested_input_shape = tuple(int(dim) for dim in input_array.shape)

    input_device_ptr: int | None = None
    output_device_ptrs: list[int] = []
    output_arrays_by_name: dict[str, Any] = {}
    infer_started_at = perf_counter()
    try:
        ensure_cuda_success(
            imports.cudart.cudaSetDevice(resolve_cuda_device_index(session_obj.device_name)),
            operation_name="TensorRT RF-DETR runtime 绑定 CUDA device",
            details={"device_name": session_obj.device_name},
        )
        engine_input_shape = normalize_tensor_shape(
            session_obj.engine.get_tensor_shape(session_obj.input_name)
        )
        if any(dim < 0 for dim in engine_input_shape):
            if (
                session_obj.context.set_input_shape(
                    session_obj.input_name,
                    requested_input_shape,
                )
                is not True
            ):
                raise ServiceConfigurationError(
                    "TensorRT RF-DETR execution context 设置输入 shape 失败",
                    details={
                        "input_name": session_obj.input_name,
                        "requested_input_shape": list(requested_input_shape),
                    },
                )
        elif engine_input_shape != requested_input_shape:
            raise InvalidRequestError(
                "TensorRT RF-DETR 输入尺寸与 engine 不匹配",
                details={
                    "expected_input_shape": list(engine_input_shape),
                    "actual_input_shape": list(requested_input_shape),
                },
            )

        input_device_ptr = ensure_cuda_success(
            imports.cudart.cudaMalloc(int(input_array.nbytes)),
            operation_name="TensorRT RF-DETR 分配输入显存",
            details={"byte_size": int(input_array.nbytes)},
        )[0]
        ensure_cuda_success(
            imports.cudart.cudaMemcpyAsync(
                input_device_ptr,
                int(input_array.ctypes.data),
                int(input_array.nbytes),
                imports.cudart.cudaMemcpyKind.cudaMemcpyHostToDevice,
                session_obj.stream,
            ),
            operation_name="TensorRT RF-DETR 拷贝输入到显存",
            details={"byte_size": int(input_array.nbytes)},
        )
        if (
            session_obj.context.set_tensor_address(
                session_obj.input_name,
                int(input_device_ptr),
            )
            is not True
        ):
            raise ServiceConfigurationError(
                "TensorRT RF-DETR execution context 绑定输入张量失败",
                details={"input_name": session_obj.input_name},
            )

        for index, output_name in enumerate(session_obj.all_output_names):
            resolved_shape = normalize_tensor_shape(
                session_obj.context.get_tensor_shape(output_name)
            )
            if any(dim < 0 for dim in resolved_shape):
                raise ServiceConfigurationError(
                    "TensorRT RF-DETR 输出 shape 尚未解析完成",
                    details={"output_name": output_name, "shape": list(resolved_shape)},
                )
            output_array = imports.np.empty(
                resolved_shape,
                dtype=resolve_numpy_dtype(
                    np_module=imports.np,
                    dtype_name=session_obj.all_output_dtype_names[index],
                ),
            )
            output_arrays_by_name[output_name] = output_array
            output_device_ptr = ensure_cuda_success(
                imports.cudart.cudaMalloc(int(output_array.nbytes)),
                operation_name="TensorRT RF-DETR 分配输出显存",
                details={"output_name": output_name, "byte_size": int(output_array.nbytes)},
            )[0]
            output_device_ptrs.append(output_device_ptr)
            if (
                session_obj.context.set_tensor_address(output_name, int(output_device_ptr))
                is not True
            ):
                raise ServiceConfigurationError(
                    "TensorRT RF-DETR execution context 绑定输出张量失败",
                    details={"output_name": output_name},
                )

        ensure_cuda_success(
            imports.cudart.cudaEventRecord(
                session_obj.execute_start_event,
                session_obj.stream,
            ),
            operation_name="TensorRT RF-DETR 记录执行起点 event",
            details={"device_name": session_obj.device_name},
        )
        if session_obj.context.execute_async_v3(stream_handle=session_obj.stream) is not True:
            raise ServiceConfigurationError(
                "TensorRT RF-DETR execution context 执行推理失败",
                details={"model_build_id": session_obj.runtime_target.model_build_id},
            )
        ensure_cuda_success(
            imports.cudart.cudaEventRecord(
                session_obj.execute_end_event,
                session_obj.stream,
            ),
            operation_name="TensorRT RF-DETR 记录执行终点 event",
            details={"device_name": session_obj.device_name},
        )
        for output_name, output_device_ptr in zip(
            session_obj.all_output_names,
            output_device_ptrs,
            strict=True,
        ):
            output_array = output_arrays_by_name[output_name]
            ensure_cuda_success(
                imports.cudart.cudaMemcpyAsync(
                    int(output_array.ctypes.data),
                    output_device_ptr,
                    int(output_array.nbytes),
                    imports.cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost,
                    session_obj.stream,
                ),
                operation_name="TensorRT RF-DETR 拷贝输出到主存",
                details={"output_name": output_name, "byte_size": int(output_array.nbytes)},
            )
        ensure_cuda_success(
            imports.cudart.cudaStreamSynchronize(session_obj.stream),
            operation_name="TensorRT RF-DETR 同步 CUDA stream",
            details={"device_name": session_obj.device_name},
        )
        infer_execute_gpu_ms = measure_cuda_event_elapsed_ms(
            cudart_module=imports.cudart,
            start_event=session_obj.execute_start_event,
            end_event=session_obj.execute_end_event,
            device_name=session_obj.device_name,
        )
    finally:
        if input_device_ptr is not None:
            try:
                imports.cudart.cudaFree(input_device_ptr)
            except Exception:
                pass
        for output_device_ptr in output_device_ptrs:
            try:
                imports.cudart.cudaFree(output_device_ptr)
            except Exception:
                pass
    infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

    processed, postprocess_ms = postprocess_rfdetr_detection_outputs(
        torch_module=imports.torch,
        postprocess_model=session_obj.postprocess_model,
        raw_outputs={
            "pred_logits": output_arrays_by_name[session_obj.output_names[0]],
            "pred_boxes": output_arrays_by_name[session_obj.output_names[1]],
        },
        image_height=int(image.shape[0]),
        image_width=int(image.shape[1]),
    )
    detections = build_rfdetr_detections(
        processed=processed,
        labels=session_obj.runtime_target.labels,
        score_threshold=request.score_threshold,
    )
    return build_rfdetr_detection_result(
        session_obj=session_obj,
        image=image,
        detections=detections,
        request=request,
        decode_ms=decode_ms,
        preprocess_ms=preprocess_ms,
        infer_ms=infer_ms,
        postprocess_ms=postprocess_ms,
        input_name=session_obj.input_name,
        output_specs=tuple(
            DetectionRuntimeTensorSpec(
                name=output_name,
                shape=tuple(int(item) for item in output_arrays_by_name[output_name].shape),
                dtype=session_obj.output_dtype_names[index],
            )
            for index, output_name in enumerate(session_obj.output_names)
        ),
        metadata={
            "model_type": "rfdetr",
            "model_scale": session_obj.runtime_target.model_scale,
            "runtime_execution_mode": describe_runtime_execution_mode(
                runtime_backend="tensorrt",
                runtime_precision=session_obj.runtime_target.runtime_precision or "fp32",
                device_name=session_obj.device_name,
            ),
            "infer_execute_gpu_ms": infer_execute_gpu_ms,
            "engine_output_names": list(session_obj.all_output_names),
            "output_names": list(session_obj.output_names),
        },
    )
