"""YOLO 主线 obb 单图推理实现。"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.yolo_primary_detection_model import load_yolo_primary_checkpoint
from backend.service.application.models.yolo_primary_detection_training import _require_training_imports
from backend.service.application.models.yolo_primary_model_configs import build_yolo_primary_model
from backend.service.application.runtime.detection_runtime_support import (
    batched_nms_indices, build_openvino_compile_properties, ensure_cuda_success,
    enable_pytorch_cuda_inference_fast_path, get_tensorrt_logger,
    import_onnxruntime_module, import_openvino_module, import_tensorrt_module,
    load_prediction_image, measure_cuda_event_elapsed_ms, normalize_tensor_shape,
    preprocess_image, render_preview_image,
    require_cuda_inference_imports, require_inference_imports,
    resolve_cuda_device_index, resolve_cuda_runtime_device_name, resolve_execution_device_name,
    resolve_numpy_dtype, resolve_onnxruntime_providers,
    resolve_openvino_compiled_runtime_precision, resolve_openvino_device_name,
    resolve_openvino_port_dtype, resolve_openvino_port_name,
    resolve_tensorrt_dtype_name, resolve_tensorrt_io_tensor_name,
)
from backend.service.application.runtime.obb_runtime_contracts import (
    ObbPredictionExecutionResult, ObbPredictionInstance,
    ObbPredictionRequest, ObbRuntimeSessionInfo, ObbRuntimeTensorSpec,
)
from backend.service.application.runtime.runtime_target import RuntimeTargetSnapshot, describe_runtime_execution_mode
from backend.service.settings import get_backend_service_settings
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


_DEFAULT_NMS_THRESHOLD = 0.65


class PyTorchYoloPrimaryObbRuntimeSession:
    """PyTorch YOLO 主线 obb 会话。"""

    model_type = "yolo-primary"
    model_label = "YOLO primary"
    task_type = "obb"

    def __init__(self, *, dataset_storage, runtime_target, imports, model, device_name, runtime_precision):
        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.model = model
        self.device_name = device_name
        self.runtime_precision = runtime_precision

    @classmethod
    def load(cls, *, dataset_storage, runtime_target):
        if runtime_target.runtime_backend != "pytorch":
            raise InvalidRequestError(f"当前 {cls.model_label} obb predictor 仅支持 pytorch", details={"runtime_backend": runtime_target.runtime_backend})
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(f"当前 {cls.model_label} obb predictor 收到了错误的 task_type", details={"task_type": runtime_target.task_type})
        imports = _require_training_imports()
        model = build_yolo_primary_model(model_type=_require_primary_model_type(cls.model_type, cls.model_label), task_type=cls.task_type, model_scale=runtime_target.model_scale, num_classes=len(runtime_target.labels))
        load_yolo_primary_checkpoint(imports=imports, model=model, checkpoint_path=runtime_target.runtime_artifact_path)
        device_name = resolve_execution_device_name(torch_module=imports.torch, requested_device_name=runtime_target.device_name)
        enable_pytorch_cuda_inference_fast_path(torch_module=imports.torch, device_name=device_name)
        model.to(device_name)
        if runtime_target.runtime_precision == "fp16":
            model.half()
        model.eval()
        return cls(dataset_storage=dataset_storage, runtime_target=runtime_target, imports=imports, model=model, device_name=device_name, runtime_precision=runtime_target.runtime_precision)

    def predict(self, request: ObbPredictionRequest) -> ObbPredictionExecutionResult:
        return _predict_pytorch(self, request)


class OnnxRuntimeYoloPrimaryObbRuntimeSession:
    """ONNXRuntime YOLO 主线 obb 会话。"""

    model_type = "yolo-primary"
    model_label = "YOLO primary"
    task_type = "obb"

    def __init__(self, *, dataset_storage, runtime_target, imports, session, device_name, input_name, output_names):
        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.session = session
        self.device_name = device_name
        self.input_name = input_name
        self.output_names = output_names

    @classmethod
    def load(cls, *, dataset_storage, runtime_target):
        if runtime_target.runtime_backend != "onnxruntime":
            raise InvalidRequestError(f"当前 {cls.model_label} obb predictor 仅支持 onnxruntime", details={"runtime_backend": runtime_target.runtime_backend})
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(f"当前 {cls.model_label} obb predictor 收到了错误的 task_type", details={"task_type": runtime_target.task_type})
        if runtime_target.runtime_precision != "fp32":
            raise InvalidRequestError("当前 obb onnxruntime session 仅支持 fp32", details={"runtime_precision": runtime_target.runtime_precision})
        imports = require_inference_imports()
        onnxruntime_module = import_onnxruntime_module()
        providers = resolve_onnxruntime_providers(onnxruntime_module=onnxruntime_module, requested_device_name=runtime_target.device_name)
        session = onnxruntime_module.InferenceSession(str(runtime_target.runtime_artifact_path), providers=providers)
        return cls(dataset_storage=dataset_storage, runtime_target=runtime_target, imports=imports, session=session, device_name=runtime_target.device_name, input_name=session.get_inputs()[0].name, output_names=tuple(item.name for item in session.get_outputs()))

    def predict(self, request: ObbPredictionRequest) -> ObbPredictionExecutionResult:
        return _predict_onnx(self, request)


class OpenVINOYoloPrimaryObbRuntimeSession:
    """OpenVINO YOLO 主线 obb 会话。"""

    model_type = "yolo-primary"
    model_label = "YOLO primary"
    task_type = "obb"

    def __init__(self, *, dataset_storage, runtime_target, imports, session, device_name, input_name, output_name, input_port, output_port, compiled_device_name, compiled_runtime_precision):
        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.session = session
        self.device_name = device_name
        self.input_name = input_name
        self.output_name = output_name
        self.input_port = input_port
        self.output_port = output_port
        self.compiled_device_name = compiled_device_name
        self.compiled_runtime_precision = compiled_runtime_precision

    @classmethod
    def load(cls, *, dataset_storage, runtime_target):
        if runtime_target.runtime_backend != "openvino":
            raise InvalidRequestError(f"当前 {cls.model_label} obb predictor 仅支持 openvino", details={"runtime_backend": runtime_target.runtime_backend})
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(f"当前 {cls.model_label} obb predictor 收到了错误的 task_type", details={"task_type": runtime_target.task_type})
        imports = require_inference_imports()
        openvino_module = import_openvino_module()
        compiled_device_name = resolve_openvino_device_name(requested_device_name=runtime_target.device_name)
        compile_properties = build_openvino_compile_properties(openvino_module=openvino_module, runtime_precision=runtime_target.runtime_precision, requested_device_name=runtime_target.device_name)
        session = openvino_module.Core().compile_model(str(runtime_target.runtime_artifact_path), compiled_device_name, compile_properties)
        input_port = session.input(0)
        output_port = session.output(0)
        return cls(dataset_storage=dataset_storage, runtime_target=runtime_target, imports=imports, session=session, device_name=runtime_target.device_name, input_name=resolve_openvino_port_name(input_port, fallback="images"), output_name=resolve_openvino_port_name(output_port, fallback="predictions"), input_port=input_port, output_port=output_port, compiled_device_name=compiled_device_name, compiled_runtime_precision=resolve_openvino_compiled_runtime_precision(session=session, fallback_precision=runtime_target.runtime_precision))

    def predict(self, request: ObbPredictionRequest) -> ObbPredictionExecutionResult:
        return _predict_openvino(self, request)


class TensorRTYoloPrimaryObbRuntimeSession:
    """TensorRT YOLO 主线 obb 会话。"""

    model_type = "yolo-primary"
    model_label = "YOLO primary"
    task_type = "obb"

    def __init__(self, *, dataset_storage, runtime_target, imports, tensorrt_module, logger, runtime, engine, context, device_name, input_name, output_name, input_dtype_name, output_dtype_name, stream, execute_start_event, execute_end_event, pinned_output_buffer_enabled=None, pinned_output_buffer_max_bytes=None):
        deployment_settings = get_backend_service_settings().deployment_process_supervisor
        if pinned_output_buffer_enabled is None:
            pinned_output_buffer_enabled = bool(deployment_settings.tensorrt_pinned_output_buffer_enabled)
        if pinned_output_buffer_max_bytes is None:
            pinned_output_buffer_max_bytes = int(deployment_settings.tensorrt_pinned_output_buffer_max_bytes)
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
        self.input_device_ptr = self.output_device_ptr = None
        self.input_capacity_bytes = self.output_capacity_bytes = 0
        self.output_host_ptr = None
        self.output_host_capacity_bytes = 0
        self.output_host_memory_kind = "pageable"
        self.output_host_array = None

    @classmethod
    def load(cls, *, dataset_storage, runtime_target, pinned_output_buffer_enabled=None, pinned_output_buffer_max_bytes=None):
        if runtime_target.runtime_backend != "tensorrt":
            raise InvalidRequestError(f"当前 {cls.model_label} obb predictor 仅支持 tensorrt", details={"runtime_backend": runtime_target.runtime_backend})
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(f"当前 {cls.model_label} obb predictor 收到了错误的 task_type", details={"task_type": runtime_target.task_type})
        imports = require_cuda_inference_imports()
        tensorrt_module = import_tensorrt_module()
        device_name = resolve_cuda_runtime_device_name(cudart_module=imports.cudart, requested_device_name=runtime_target.device_name)
        ensure_cuda_success(imports.cudart.cudaSetDevice(resolve_cuda_device_index(device_name)), operation_name="TensorRT obb runtime 切换 CUDA device", details={"device_name": device_name})
        logger = get_tensorrt_logger(tensorrt_module=tensorrt_module, severity=tensorrt_module.Logger.WARNING)
        runtime = tensorrt_module.Runtime(logger)
        engine = runtime.deserialize_cuda_engine(runtime_target.runtime_artifact_path.read_bytes())
        if engine is None:
            raise ServiceConfigurationError("TensorRT obb engine 反序列化失败", details={"model_build_id": runtime_target.model_build_id})
        context = engine.create_execution_context()
        if context is None:
            raise ServiceConfigurationError("TensorRT obb engine 无法创建 execution context", details={"model_build_id": runtime_target.model_build_id})
        stream = ensure_cuda_success(imports.cudart.cudaStreamCreate(), operation_name="TensorRT obb runtime 创建 CUDA stream", details={"device_name": device_name})[0]
        execute_start_event = ensure_cuda_success(imports.cudart.cudaEventCreate(), operation_name="TensorRT obb runtime 创建执行起点 event", details={"device_name": device_name})[0]
        execute_end_event = ensure_cuda_success(imports.cudart.cudaEventCreate(), operation_name="TensorRT obb runtime 创建执行终点 event", details={"device_name": device_name})[0]
        input_name = resolve_tensorrt_io_tensor_name(engine=engine, tensorrt_module=tensorrt_module, io_mode=tensorrt_module.TensorIOMode.INPUT, fallback="images")
        output_name = resolve_tensorrt_io_tensor_name(engine=engine, tensorrt_module=tensorrt_module, io_mode=tensorrt_module.TensorIOMode.OUTPUT, fallback="predictions")
        return cls(dataset_storage=dataset_storage, runtime_target=runtime_target, imports=imports, tensorrt_module=tensorrt_module, logger=logger, runtime=runtime, engine=engine, context=context, device_name=device_name, input_name=input_name, output_name=output_name, input_dtype_name=resolve_tensorrt_dtype_name(tensorrt_module=tensorrt_module, tensor_dtype=engine.get_tensor_dtype(input_name), fallback="float32"), output_dtype_name=resolve_tensorrt_dtype_name(tensorrt_module=tensorrt_module, tensor_dtype=engine.get_tensor_dtype(output_name), fallback="float32"), stream=stream, execute_start_event=execute_start_event, execute_end_event=execute_end_event, pinned_output_buffer_enabled=pinned_output_buffer_enabled, pinned_output_buffer_max_bytes=pinned_output_buffer_max_bytes)

    def predict(self, request: ObbPredictionRequest) -> ObbPredictionExecutionResult:
        return _predict_tensorrt(self, request)

    def close(self):
        try:
            ensure_cuda_success(self.imports.cudart.cudaSetDevice(resolve_cuda_device_index(self.device_name)), operation_name="TensorRT obb runtime 清理前绑定 CUDA device", details={"device_name": self.device_name})
        except Exception:
            return
        if self.input_device_ptr is not None:
            self.imports.cudart.cudaFree(self.input_device_ptr)
            self.input_device_ptr = None
            self.input_capacity_bytes = 0
        if self.output_device_ptr is not None:
            self.imports.cudart.cudaFree(self.output_device_ptr)
            self.output_device_ptr = None
            self.output_capacity_bytes = 0
        if self.output_host_ptr is not None:
            self.imports.cudart.cudaFreeHost(self.output_host_ptr)
            self.output_host_ptr = None
            self.output_host_capacity_bytes = 0
            self.output_host_array = None
        self.output_host_memory_kind = "pageable"
        if self.stream is not None:
            self.imports.cudart.cudaStreamDestroy(self.stream)
            self.stream = None
        if self.execute_start_event is not None:
            self.imports.cudart.cudaEventDestroy(self.execute_start_event)
            self.execute_start_event = None
        if self.execute_end_event is not None:
            self.imports.cudart.cudaEventDestroy(self.execute_end_event)
            self.execute_end_event = None
        self.output_host_array = None

    def describe_memory_usage(self):
        b = 0
        if self.output_host_array is not None:
            b = int(self.output_host_array.nbytes)
        p = 0
        if self.output_host_memory_kind == "pinned" and self.output_host_ptr is not None:
            p = int(self.output_host_capacity_bytes)
        return {"output_host_memory_kind": self.output_host_memory_kind, "output_host_buffer_bytes": b, "output_host_pinned_bytes": p, "output_host_pinned_enabled": self.pinned_output_buffer_enabled, "output_host_pinned_max_bytes": self.pinned_output_buffer_max_bytes}

    def _ensure_io_buffers(self, *, input_array, resolved_output_shape):
        output_dtype = resolve_numpy_dtype(np_module=self.imports.np, dtype_name=self.output_dtype_name)
        input_nbytes = int(input_array.nbytes)
        output_nbytes = int(self.imports.np.empty(resolved_output_shape, dtype=output_dtype).nbytes)
        if self.input_device_ptr is None or input_nbytes > self.input_capacity_bytes:
            if self.input_device_ptr is not None:
                self.imports.cudart.cudaFree(self.input_device_ptr)
            self.input_device_ptr = ensure_cuda_success(self.imports.cudart.cudaMalloc(input_nbytes), operation_name="TensorRT obb runtime 分配输入显存", details={"byte_size": input_nbytes})[0]
            self.input_capacity_bytes = input_nbytes
        if self.output_device_ptr is None or output_nbytes > self.output_capacity_bytes:
            if self.output_device_ptr is not None:
                self.imports.cudart.cudaFree(self.output_device_ptr)
            self.output_device_ptr = ensure_cuda_success(self.imports.cudart.cudaMalloc(output_nbytes), operation_name="TensorRT obb runtime 分配输出显存", details={"byte_size": output_nbytes})[0]
            self.output_capacity_bytes = output_nbytes
        if self._should_use_pinned_output_buffer(output_nbytes):
            if self.output_host_ptr is None or output_nbytes > self.output_host_capacity_bytes:
                if self.output_host_ptr is not None:
                    self.imports.cudart.cudaFreeHost(self.output_host_ptr)
                self.output_host_ptr = ensure_cuda_success(self.imports.cudart.cudaMallocHost(output_nbytes), operation_name="TensorRT obb runtime 分配 pinned 输出主存", details={"byte_size": output_nbytes})[0]
                self.output_host_capacity_bytes = output_nbytes
                self.output_host_array = None
            if self.output_host_array is None or self.output_host_memory_kind != "pinned" or tuple(int(d) for d in self.output_host_array.shape) != resolved_output_shape or self.output_host_array.dtype != output_dtype:
                self.output_host_array = self.imports.np.ctypeslib.as_array((self.imports.np.ctypeslib.as_ctypes_type(output_dtype) * int(self.imports.np.prod(resolved_output_shape))).from_address(int(self.output_host_ptr))).reshape(resolved_output_shape)
            self.output_host_memory_kind = "pinned"
            return self.output_host_array
        if self.output_host_ptr is not None:
            self.imports.cudart.cudaFreeHost(self.output_host_ptr)
            self.output_host_ptr = None
            self.output_host_capacity_bytes = 0
            self.output_host_array = None
        if self.output_host_array is None or self.output_host_memory_kind != "pageable" or tuple(int(d) for d in self.output_host_array.shape) != resolved_output_shape or self.output_host_array.dtype != output_dtype:
            self.output_host_array = self.imports.np.empty(resolved_output_shape, dtype=output_dtype)
        self.output_host_memory_kind = "pageable"
        return self.output_host_array

    def _should_use_pinned_output_buffer(self, output_nbytes):
        if not self.pinned_output_buffer_enabled:
            return False
        if output_nbytes <= 0:
            return False
        return output_nbytes <= self.pinned_output_buffer_max_bytes


def _predict_pytorch(session, request):
    decode_started_at = perf_counter()
    image = load_prediction_image(cv2_module=session.imports.cv2, np_module=session.imports.np, dataset_storage=session.dataset_storage, request=request)
    decode_ms = round((perf_counter() - decode_started_at) * 1000, 3)
    preprocess_started_at = perf_counter()
    input_tensor, resize_ratio = preprocess_image(cv2_module=session.imports.cv2, np_module=session.imports.np, image=image, input_size=session.runtime_target.input_size)
    input_tensor = session.imports.torch.from_numpy(input_tensor).unsqueeze(0).to(session.device_name).float()
    if session.runtime_precision == "fp16":
        input_tensor = input_tensor.half()
    preprocess_ms = round((perf_counter() - preprocess_started_at) * 1000, 3)
    infer_started_at = perf_counter()
    inference_mode = getattr(session.imports.torch, "inference_mode", None)
    if callable(inference_mode):
        with inference_mode():
            outputs = session.model(input_tensor)
    else:
        with session.imports.torch.no_grad():
            outputs = session.model(input_tensor)
    infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)
    prediction_array = _normalize_pytorch_prediction(outputs, np_module=session.imports.np)
    instances = _build_obb_instances(np_module=session.imports.np, prediction_array=prediction_array, labels=session.runtime_target.labels, score_threshold=request.score_threshold, resize_ratio=resize_ratio, image_width=int(image.shape[1]), image_height=int(image.shape[0]))
    postprocess_ms = round((perf_counter() - perf_counter()) * 0 + (perf_counter() - infer_started_at) * 0, 3)
    latency_ms = decode_ms + preprocess_ms + infer_ms
    preview_image_bytes = None
    if request.save_result_image:
        preview_detections = tuple(_as_preview_detection(inst) for inst in instances)
        preview_image_bytes = render_preview_image(cv2_module=session.imports.cv2, image=image, detections=preview_detections)
    output_dtype = "float16" if session.runtime_precision == "fp16" else "float32"
    return ObbPredictionExecutionResult(
        instances=instances, latency_ms=round(latency_ms, 3), image_width=int(image.shape[1]), image_height=int(image.shape[0]),
        preview_image_bytes=preview_image_bytes,
        runtime_session_info=ObbRuntimeSessionInfo(
            backend_name=session.runtime_target.runtime_backend, model_uri=session.runtime_target.runtime_artifact_storage_uri, device_name=session.device_name,
            input_spec=ObbRuntimeTensorSpec(name="images", shape=(1, 3, session.runtime_target.input_size[0], session.runtime_target.input_size[1]), dtype=output_dtype),
            output_specs=(ObbRuntimeTensorSpec(name="predictions", shape=tuple(int(d) for d in prediction_array.shape), dtype=output_dtype),),
            metadata={"model_version_id": session.runtime_target.model_version_id, "runtime_precision": session.runtime_precision, "score_threshold": request.score_threshold, "class_count": len(session.runtime_target.labels), "decode_ms": decode_ms, "preprocess_ms": preprocess_ms, "infer_ms": infer_ms},
        ),
    )


def _predict_onnx(session, request):
    decode_started_at = perf_counter()
    image = load_prediction_image(cv2_module=session.imports.cv2, np_module=session.imports.np, dataset_storage=session.dataset_storage, request=request)
    decode_ms = round((perf_counter() - decode_started_at) * 1000, 3)
    preprocess_started_at = perf_counter()
    input_tensor, resize_ratio = preprocess_image(cv2_module=session.imports.cv2, np_module=session.imports.np, image=image, input_size=session.runtime_target.input_size)
    input_tensor = session.imports.np.expand_dims(input_tensor, axis=0).astype(session.imports.np.float32, copy=False)
    preprocess_ms = round((perf_counter() - preprocess_started_at) * 1000, 3)
    infer_started_at = perf_counter()
    outputs = session.session.run(list(session.output_names), {session.input_name: input_tensor})
    infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)
    prediction_array = _normalize_onnx_prediction(outputs, np_module=session.imports.np)
    instances = _build_obb_instances(np_module=session.imports.np, prediction_array=prediction_array, labels=session.runtime_target.labels, score_threshold=request.score_threshold, resize_ratio=resize_ratio, image_width=int(image.shape[1]), image_height=int(image.shape[0]))
    latency_ms = decode_ms + preprocess_ms + infer_ms
    preview_image_bytes = None
    if request.save_result_image:
        preview_detections = tuple(_as_preview_detection(inst) for inst in instances)
        preview_image_bytes = render_preview_image(cv2_module=session.imports.cv2, image=image, detections=preview_detections)
    return ObbPredictionExecutionResult(
        instances=instances, latency_ms=round(latency_ms, 3), image_width=int(image.shape[1]), image_height=int(image.shape[0]),
        preview_image_bytes=preview_image_bytes,
        runtime_session_info=ObbRuntimeSessionInfo(
            backend_name=session.runtime_target.runtime_backend, model_uri=session.runtime_target.runtime_artifact_storage_uri, device_name=session.device_name,
            input_spec=ObbRuntimeTensorSpec(name=session.input_name, shape=(1, 3, session.runtime_target.input_size[0], session.runtime_target.input_size[1]), dtype="float32"),
            output_specs=(ObbRuntimeTensorSpec(name=session.output_names[0] if session.output_names else "predictions", shape=tuple(int(d) for d in prediction_array.shape), dtype="float32"),),
            metadata={"model_version_id": session.runtime_target.model_version_id, "runtime_precision": session.runtime_target.runtime_precision, "score_threshold": request.score_threshold, "class_count": len(session.runtime_target.labels), "decode_ms": decode_ms, "preprocess_ms": preprocess_ms, "infer_ms": infer_ms, "provider_names": list(session.session.get_providers()), "output_names": list(session.output_names)},
        ),
    )


def _predict_openvino(session, request):
    decode_started_at = perf_counter()
    image = load_prediction_image(cv2_module=session.imports.cv2, np_module=session.imports.np, dataset_storage=session.dataset_storage, request=request)
    decode_ms = round((perf_counter() - decode_started_at) * 1000, 3)
    preprocess_started_at = perf_counter()
    input_tensor, resize_ratio = preprocess_image(cv2_module=session.imports.cv2, np_module=session.imports.np, image=image, input_size=session.runtime_target.input_size)
    input_tensor = session.imports.np.expand_dims(input_tensor, axis=0).astype(session.imports.np.float32, copy=False)
    preprocess_ms = round((perf_counter() - preprocess_started_at) * 1000, 3)
    infer_started_at = perf_counter()
    outputs = session.session.infer_new_request({session.input_port: input_tensor})
    infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)
    raw_output = outputs.get(session.output_port) or outputs.get(session.output_name)
    if raw_output is None and hasattr(outputs, "values"):
        values = tuple(outputs.values())
        raw_output = values[0] if values else None
    if raw_output is None:
        raise InvalidRequestError("openvino obb 推理输出为空")
    prediction_array = _normalize_onnx_prediction([raw_output], np_module=session.imports.np)
    instances = _build_obb_instances(np_module=session.imports.np, prediction_array=prediction_array, labels=session.runtime_target.labels, score_threshold=request.score_threshold, resize_ratio=resize_ratio, image_width=int(image.shape[1]), image_height=int(image.shape[0]))
    latency_ms = decode_ms + preprocess_ms + infer_ms
    preview_image_bytes = None
    if request.save_result_image:
        preview_detections = tuple(_as_preview_detection(inst) for inst in instances)
        preview_image_bytes = render_preview_image(cv2_module=session.imports.cv2, image=image, detections=preview_detections)
    return ObbPredictionExecutionResult(
        instances=instances, latency_ms=round(latency_ms, 3), image_width=int(image.shape[1]), image_height=int(image.shape[0]),
        preview_image_bytes=preview_image_bytes,
        runtime_session_info=ObbRuntimeSessionInfo(
            backend_name=session.runtime_target.runtime_backend, model_uri=session.runtime_target.runtime_artifact_storage_uri, device_name=session.device_name,
            input_spec=ObbRuntimeTensorSpec(name=session.input_name, shape=(1, 3, session.runtime_target.input_size[0], session.runtime_target.input_size[1]), dtype=resolve_openvino_port_dtype(session.input_port, fallback="float32")),
            output_specs=(ObbRuntimeTensorSpec(name=session.output_name, shape=tuple(int(d) for d in prediction_array.shape), dtype=resolve_openvino_port_dtype(session.output_port, fallback="float32")),),
            metadata={"model_version_id": session.runtime_target.model_version_id, "runtime_precision": session.runtime_target.runtime_precision, "score_threshold": request.score_threshold, "class_count": len(session.runtime_target.labels), "decode_ms": decode_ms, "preprocess_ms": preprocess_ms, "infer_ms": infer_ms, "compiled_device_name": session.compiled_device_name, "compiled_runtime_precision": session.compiled_runtime_precision},
        ),
    )


def _predict_tensorrt(session, request):
    decode_started_at = perf_counter()
    image = load_prediction_image(cv2_module=session.imports.cv2, np_module=session.imports.np, dataset_storage=session.dataset_storage, request=request)
    decode_ms = round((perf_counter() - decode_started_at) * 1000, 3)
    preprocess_started_at = perf_counter()
    input_tensor, resize_ratio = preprocess_image(cv2_module=session.imports.cv2, np_module=session.imports.np, image=image, input_size=session.runtime_target.input_size)
    input_array = session.imports.np.expand_dims(input_tensor, axis=0).astype(resolve_numpy_dtype(np_module=session.imports.np, dtype_name=session.input_dtype_name), copy=False)
    requested_input_shape = tuple(int(d) for d in input_array.shape)
    preprocess_ms = round((perf_counter() - preprocess_started_at) * 1000, 3)
    infer_started_at = perf_counter()
    ensure_cuda_success(session.imports.cudart.cudaSetDevice(resolve_cuda_device_index(session.device_name)), operation_name="TensorRT obb runtime 绑定 CUDA device", details={"device_name": session.device_name})
    engine_input_shape = normalize_tensor_shape(session.engine.get_tensor_shape(session.input_name))
    if any(d < 0 for d in engine_input_shape):
        if session.context.set_input_shape(session.input_name, requested_input_shape) is not True:
            raise ServiceConfigurationError("TensorRT obb execution context 设置输入 shape 失败")
    elif engine_input_shape != requested_input_shape:
        raise InvalidRequestError("TensorRT obb engine 输入尺寸不一致")
    resolved_output_shape = normalize_tensor_shape(session.context.get_tensor_shape(session.output_name))
    if not resolved_output_shape or any(d <= 0 for d in resolved_output_shape):
        raise ServiceConfigurationError("TensorRT obb execution context 返回了无效输出 shape")
    output_array = session._ensure_io_buffers(input_array=input_array, resolved_output_shape=resolved_output_shape)
    ensure_cuda_success(session.imports.cudart.cudaMemcpyAsync(session.input_device_ptr, int(input_array.ctypes.data), int(input_array.nbytes), session.imports.cudart.cudaMemcpyKind.cudaMemcpyHostToDevice, session.stream), operation_name="TensorRT obb runtime 拷贝输入到显存")
    if session.context.set_tensor_address(session.input_name, int(session.input_device_ptr)) is not True:
        raise ServiceConfigurationError("TensorRT obb 绑定输入张量失败")
    if session.context.set_tensor_address(session.output_name, int(session.output_device_ptr)) is not True:
        raise ServiceConfigurationError("TensorRT obb 绑定输出张量失败")
    ensure_cuda_success(session.imports.cudart.cudaEventRecord(session.execute_start_event, session.stream), operation_name="TensorRT obb runtime 记录执行起点 event")
    if session.context.execute_async_v3(stream_handle=session.stream) is not True:
        raise ServiceConfigurationError("TensorRT obb execution context 执行推理失败")
    ensure_cuda_success(session.imports.cudart.cudaEventRecord(session.execute_end_event, session.stream), operation_name="TensorRT obb runtime 记录执行终点 event")
    ensure_cuda_success(session.imports.cudart.cudaMemcpyAsync(int(output_array.ctypes.data), session.output_device_ptr, int(output_array.nbytes), session.imports.cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost, session.stream), operation_name="TensorRT obb runtime 拷贝输出到主存")
    ensure_cuda_success(session.imports.cudart.cudaStreamSynchronize(session.stream), operation_name="TensorRT obb runtime 同步 CUDA stream")
    infer_execute_gpu_ms = measure_cuda_event_elapsed_ms(cudart_module=session.imports.cudart, start_event=session.execute_start_event, end_event=session.execute_end_event, device_name=session.device_name)
    infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)
    prediction_array = _normalize_onnx_prediction([output_array], np_module=session.imports.np)
    instances = _build_obb_instances(np_module=session.imports.np, prediction_array=prediction_array, labels=session.runtime_target.labels, score_threshold=request.score_threshold, resize_ratio=resize_ratio, image_width=int(image.shape[1]), image_height=int(image.shape[0]))
    latency_ms = decode_ms + preprocess_ms + infer_ms
    preview_image_bytes = None
    if request.save_result_image:
        preview_detections = tuple(_as_preview_detection(inst) for inst in instances)
        preview_image_bytes = render_preview_image(cv2_module=session.imports.cv2, image=image, detections=preview_detections)
    return ObbPredictionExecutionResult(
        instances=instances, latency_ms=round(latency_ms, 3), image_width=int(image.shape[1]), image_height=int(image.shape[0]),
        preview_image_bytes=preview_image_bytes,
        runtime_session_info=ObbRuntimeSessionInfo(
            backend_name=session.runtime_target.runtime_backend, model_uri=session.runtime_target.runtime_artifact_storage_uri, device_name=session.device_name,
            input_spec=ObbRuntimeTensorSpec(name=session.input_name, shape=requested_input_shape, dtype=session.input_dtype_name),
            output_specs=(ObbRuntimeTensorSpec(name=session.output_name, shape=resolved_output_shape, dtype=session.output_dtype_name),),
            metadata={"model_version_id": session.runtime_target.model_version_id, "runtime_precision": session.runtime_target.runtime_precision, "score_threshold": request.score_threshold, "class_count": len(session.runtime_target.labels), "decode_ms": decode_ms, "preprocess_ms": preprocess_ms, "infer_ms": infer_ms, "infer_execute_gpu_ms": infer_execute_gpu_ms, **session.describe_memory_usage()},
        ),
    )


def _normalize_pytorch_prediction(outputs, *, np_module):
    if hasattr(outputs, "detach"):
        outputs = outputs.detach()
    if hasattr(outputs, "cpu"):
        outputs = outputs.cpu()
    if hasattr(outputs, "numpy"):
        outputs = outputs.numpy()
    p = np_module.asarray(outputs, dtype=np_module.float32)
    if p.ndim == 2:
        p = np_module.expand_dims(p, axis=0)
    return p


def _normalize_onnx_prediction(outputs, *, np_module):
    if not isinstance(outputs, list) or not outputs:
        raise InvalidRequestError("onnxruntime obb 推理输出为空")
    p = np_module.asarray(outputs[0], dtype=np_module.float32)
    if p.ndim == 2:
        p = np_module.expand_dims(p, axis=0)
    return p


def _build_obb_instances(*, np_module, prediction_array, labels, score_threshold, resize_ratio, image_width, image_height):
    p = np_module.asarray(prediction_array, dtype=np_module.float32)
    if p.ndim == 2:
        p = np_module.expand_dims(p, axis=0)
    nc = len(labels)
    if int(p.shape[2]) < 4 + nc + 1:
        raise InvalidRequestError("obb 推理输出通道数不足")
    results = []
    for image_prediction in p:
        boxes = image_prediction[:, :4]
        class_scores = image_prediction[:, 4:4 + nc]
        angles = image_prediction[:, 4 + nc]
        best_scores = np_module.max(class_scores, axis=1)
        best_class_ids = np_module.argmax(class_scores, axis=1).astype(np_module.int32, copy=False)
        keep_mask = best_scores >= score_threshold
        boxes = boxes[keep_mask]
        best_scores = best_scores[keep_mask]
        best_class_ids = best_class_ids[keep_mask]
        angles = angles[keep_mask]
        if int(boxes.shape[0]) <= 0:
            continue
        keep_indices = batched_nms_indices(boxes=boxes, scores=best_scores, class_ids=best_class_ids, nms_threshold=_DEFAULT_NMS_THRESHOLD, np_module=np_module)
        if int(keep_indices.size) <= 0:
            continue
        for box, score, cls_id, angle in zip(boxes[keep_indices], best_scores[keep_indices], best_class_ids[keep_indices], angles[keep_indices], strict=True):
            scaled_box = box / max(resize_ratio, 1e-8)
            x1 = float(max(0.0, min(float(scaled_box[0]), float(image_width))))
            y1 = float(max(0.0, min(float(scaled_box[1]), float(image_height))))
            x2 = float(max(0.0, min(float(scaled_box[2]), float(image_width))))
            y2 = float(max(0.0, min(float(scaled_box[3]), float(image_height))))
            rc = int(cls_id)
            cn = labels[rc] if 0 <= rc < len(labels) else None
            results.append(ObbPredictionInstance(bbox_xyxy=(round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)), score=round(float(score), 6), class_id=rc, class_name=cn, angle=round(float(angle), 6)))
    results.sort(key=lambda i: i.score, reverse=True)
    return tuple(results)


def _as_preview_detection(instance):
    from backend.service.application.runtime.detection_runtime_contracts import DetectionPredictionDetection
    return DetectionPredictionDetection(bbox_xyxy=instance.bbox_xyxy, score=instance.score, class_id=instance.class_id, class_name=instance.class_name)


def _require_primary_model_type(model_type, model_label):
    n = model_type.strip().lower()
    if not n or n == "yolo-primary":
        raise ServiceConfigurationError(f"当前 {model_label} obb predictor 缺少正式 model_type 配置", details={"model_type": model_type})
    return n
