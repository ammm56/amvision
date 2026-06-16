"""RF-DETR segmentation 推理实现。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.models.rfdetr_core.runtime import (
    build_rfdetr_runtime_postprocess_model,
    resolve_rfdetr_runtime_input_size,
    resolve_rfdetr_runtime_output_names,
)
from backend.service.application.models.rfdetr_core.segmentation import (
    build_rfdetr_segmentation_model,
)
from backend.service.application.runtime.predictors.rfdetr_io import (
    build_rfdetr_input_array,
    load_rfdetr_runtime_input_image,
)
from backend.service.application.runtime.predictors.rfdetr_segmentation_result import (
    build_rfdetr_segmentation_instances,
    postprocess_rfdetr_segmentation_outputs,
    render_rfdetr_segmentation_preview,
)
from backend.service.application.runtime.predictors.rfdetr_tensorrt import (
    list_rfdetr_tensorrt_output_names,
)
from backend.service.application.runtime.support.detection import (
    build_openvino_compile_properties,
    ensure_cuda_success,
    get_tensorrt_logger,
    import_onnxruntime_module,
    import_openvino_module,
    import_tensorrt_module,
    measure_cuda_event_elapsed_ms,
    normalize_tensor_shape,
    require_cuda_inference_imports,
    resolve_cuda_device_index,
    resolve_cuda_runtime_device_name,
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
    SegmentationPredictionRequest,
    SegmentationRuntimeSessionInfo,
    SegmentationRuntimeTensorSpec,
)
from backend.service.application.runtime.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


class PyTorchRfdetrSegmentationRuntimeSession:
    """PyTorch RF-DETR segmentation 会话。"""

    model_type = "rfdetr"
    model_label = "RF-DETR"
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
        input_size: tuple[int, int],
    ) -> None:
        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.model = model
        self.device_name = device_name
        self.runtime_precision = runtime_precision
        self.input_size = input_size

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
    ) -> "PyTorchRfdetrSegmentationRuntimeSession":
        if runtime_target.runtime_backend != "pytorch":
            raise InvalidRequestError(
                "RF-DETR segmentation 当前仅支持 pytorch",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(
                "RF-DETR segmentation predictor 收到了错误的 task_type",
                details={"task_type": runtime_target.task_type},
            )
        import cv2
        import numpy as np
        import torch

        imports = type(
            "_RfdetrSegmentationPredictorImports",
            (),
            {"cv2": cv2, "np": np, "torch": torch},
        )()
        input_size = resolve_rfdetr_runtime_input_size(
            task_type=runtime_target.task_type,
            model_scale=runtime_target.model_scale,
            input_size=runtime_target.input_size,
        )
        model = build_rfdetr_segmentation_model(
            model_scale=runtime_target.model_scale,
            num_classes=len(runtime_target.labels),
            pretrained_path=str(runtime_target.runtime_artifact_path)
            if runtime_target.runtime_artifact_path
            else None,
        )
        device_name = runtime_target.device_name or "cpu"
        if device_name == "cuda" and torch.cuda.is_available():
            device_name = "cuda:0"
        model.to(device_name)
        if runtime_target.runtime_precision == "fp16" and device_name.startswith("cuda"):
            model.half()
        model.eval()
        return cls(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            imports=imports,
            model=model,
            device_name=device_name,
            runtime_precision=runtime_target.runtime_precision or "fp32",
            input_size=input_size,
        )

    def predict(self, request: SegmentationPredictionRequest) -> SegmentationPredictionExecutionResult:
        imports = self.imports
        image, decode_ms = load_rfdetr_runtime_input_image(
            cv2_module=imports.cv2,
            np_module=imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        input_array, preprocess_ms = build_rfdetr_input_array(
            cv2_module=imports.cv2,
            np_module=imports.np,
            image=image,
            input_size=self.input_size,
        )
        input_tensor = imports.torch.from_numpy(input_array).to(self.device_name).float()
        if self.runtime_precision == "fp16" and self.device_name.startswith("cuda"):
            input_tensor = input_tensor.half()

        infer_started_at = perf_counter()
        inference_mode = getattr(imports.torch, "inference_mode", None)
        if callable(inference_mode):
            with inference_mode():
                outputs = self.model(input_tensor)
        else:
            with imports.torch.no_grad():
                outputs = self.model(input_tensor)
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        processed, postprocess_ms = postprocess_rfdetr_segmentation_outputs(
            torch_module=imports.torch,
            postprocess_model=self.model,
            raw_outputs=outputs,
            image_height=int(image.shape[0]),
            image_width=int(image.shape[1]),
        )
        instances = build_rfdetr_segmentation_instances(
            cv2_module=imports.cv2,
            scores=processed["scores"],
            labels=processed["labels"],
            boxes_xyxy=processed["boxes_xyxy"],
            masks=processed["masks"],
            label_names=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            mask_threshold=request.mask_threshold,
        )
        preview_image_bytes = render_rfdetr_segmentation_preview(
            cv2_module=imports.cv2,
            image=image,
            instances=instances,
            save_result_image=request.save_result_image,
        )
        return SegmentationPredictionExecutionResult(
            instances=instances,
            latency_ms=round(decode_ms + preprocess_ms + infer_ms + postprocess_ms, 3),
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=SegmentationRuntimeSessionInfo(
                backend_name=self.runtime_target.runtime_backend,
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=SegmentationRuntimeTensorSpec(
                    name="images",
                    shape=(1, 3, self.input_size[0], self.input_size[1]),
                    dtype="float16" if self.runtime_precision == "fp16" else "float32",
                ),
                output_specs=(
                    SegmentationRuntimeTensorSpec(
                        name="pred_logits",
                        shape=tuple(int(item) for item in outputs["pred_logits"].shape),
                        dtype="float16" if self.runtime_precision == "fp16" else "float32",
                    ),
                    SegmentationRuntimeTensorSpec(
                        name="pred_boxes",
                        shape=tuple(int(item) for item in outputs["pred_boxes"].shape),
                        dtype="float16" if self.runtime_precision == "fp16" else "float32",
                    ),
                    SegmentationRuntimeTensorSpec(
                        name="pred_masks",
                        shape=tuple(int(item) for item in outputs["pred_masks"].shape),
                        dtype="float16" if self.runtime_precision == "fp16" else "float32",
                    ),
                ),
                metadata={
                    "model_type": "rfdetr",
                    "model_scale": self.runtime_target.model_scale,
                    "runtime_execution_mode": describe_runtime_execution_mode(
                        runtime_backend=self.runtime_target.runtime_backend,
                        runtime_precision=self.runtime_precision,
                        device_name=self.device_name,
                    ),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                },
            ),
        )


class OnnxRuntimeRfdetrSegmentationRuntimeSession:
    """ONNX Runtime RF-DETR segmentation 会话。"""

    model_type = "rfdetr"
    model_label = "RF-DETR"
    task_type = "segmentation"

    def __init__(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        imports: Any,
        session: Any,
        input_name: str,
        output_names: tuple[str, ...],
        postprocess_model: Any,
        input_size: tuple[int, int],
    ) -> None:
        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.session = session
        self.input_name = input_name
        self.output_names = output_names
        self.postprocess_model = postprocess_model
        self.input_size = input_size
        self.device_name = runtime_target.device_name or "cpu"
        self.runtime_precision = runtime_target.runtime_precision or "fp32"

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
    ) -> "OnnxRuntimeRfdetrSegmentationRuntimeSession":
        if runtime_target.runtime_backend != "onnxruntime":
            raise InvalidRequestError(
                "RF-DETR segmentation predictor 仅支持 onnxruntime",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(
                "RF-DETR segmentation predictor 收到了错误的 task_type",
                details={"task_type": runtime_target.task_type},
            )
        if (runtime_target.runtime_precision or "fp32") != "fp32":
            raise InvalidRequestError(
                "当前 RF-DETR segmentation onnxruntime session 仅支持 fp32",
                details={"runtime_precision": runtime_target.runtime_precision},
            )
        import cv2
        import numpy as np
        import torch

        onnxruntime_module = import_onnxruntime_module()
        providers = resolve_onnxruntime_providers(
            onnxruntime_module=onnxruntime_module,
            requested_device_name=runtime_target.device_name,
        )
        session = onnxruntime_module.InferenceSession(
            str(runtime_target.runtime_artifact_path),
            providers=providers,
        )
        imports = type(
            "_RfdetrSegmentationOnnxImports",
            (),
            {"cv2": cv2, "np": np, "torch": torch},
        )()
        return cls(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            imports=imports,
            session=session,
            input_name=session.get_inputs()[0].name,
            output_names=resolve_rfdetr_runtime_output_names(
                task_type=runtime_target.task_type,
                output_names=tuple(item.name for item in session.get_outputs()),
            ),
            postprocess_model=build_rfdetr_runtime_postprocess_model(
                task_type=runtime_target.task_type,
            ),
            input_size=resolve_rfdetr_runtime_input_size(
                task_type=runtime_target.task_type,
                model_scale=runtime_target.model_scale,
                input_size=runtime_target.input_size,
            ),
        )

    def predict(self, request: SegmentationPredictionRequest) -> SegmentationPredictionExecutionResult:
        imports = self.imports
        image, decode_ms = load_rfdetr_runtime_input_image(
            cv2_module=imports.cv2,
            np_module=imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        input_array, preprocess_ms = build_rfdetr_input_array(
            cv2_module=imports.cv2,
            np_module=imports.np,
            image=image,
            input_size=self.input_size,
        )

        infer_started_at = perf_counter()
        raw_outputs = self.session.run(
            list(self.output_names),
            {self.input_name: input_array},
        )
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        processed, postprocess_ms = postprocess_rfdetr_segmentation_outputs(
            torch_module=imports.torch,
            postprocess_model=self.postprocess_model,
            raw_outputs={
                "pred_logits": raw_outputs[0],
                "pred_boxes": raw_outputs[1],
                "pred_masks": raw_outputs[2],
            },
            image_height=int(image.shape[0]),
            image_width=int(image.shape[1]),
        )
        instances = build_rfdetr_segmentation_instances(
            cv2_module=imports.cv2,
            scores=processed["scores"],
            labels=processed["labels"],
            boxes_xyxy=processed["boxes_xyxy"],
            masks=processed["masks"],
            label_names=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            mask_threshold=request.mask_threshold,
        )
        preview_image_bytes = render_rfdetr_segmentation_preview(
            cv2_module=imports.cv2,
            image=image,
            instances=instances,
            save_result_image=request.save_result_image,
        )
        return SegmentationPredictionExecutionResult(
            instances=instances,
            latency_ms=round(decode_ms + preprocess_ms + infer_ms + postprocess_ms, 3),
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=SegmentationRuntimeSessionInfo(
                backend_name="onnxruntime",
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=SegmentationRuntimeTensorSpec(
                    name=self.input_name,
                    shape=(1, 3, self.input_size[0], self.input_size[1]),
                    dtype="float32",
                ),
                output_specs=tuple(
                    SegmentationRuntimeTensorSpec(
                        name=name,
                        shape=tuple(int(item) for item in array.shape),
                        dtype="float32",
                    )
                    for name, array in zip(self.output_names, raw_outputs, strict=False)
                ),
                metadata={
                    "model_type": "rfdetr",
                    "model_scale": self.runtime_target.model_scale,
                    "runtime_execution_mode": describe_runtime_execution_mode(
                        runtime_backend="onnxruntime",
                        runtime_precision="fp32",
                        device_name=self.device_name,
                    ),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                    "provider_names": list(self.session.get_providers()),
                    "output_names": list(self.output_names),
                },
            ),
        )


class OpenVINORfdetrSegmentationRuntimeSession:
    """OpenVINO RF-DETR segmentation 会话。"""

    model_type = "rfdetr"
    model_label = "RF-DETR"
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
        input_port: Any,
        output_ports: tuple[Any, ...],
        compiled_device_name: str,
        compiled_runtime_precision: str,
        postprocess_model: Any,
        input_size: tuple[int, int],
    ) -> None:
        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.session = session
        self.device_name = device_name
        self.input_name = input_name
        self.output_names = output_names
        self.input_port = input_port
        self.output_ports = output_ports
        self.compiled_device_name = compiled_device_name
        self.compiled_runtime_precision = compiled_runtime_precision
        self.postprocess_model = postprocess_model
        self.input_size = input_size

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
    ) -> "OpenVINORfdetrSegmentationRuntimeSession":
        if runtime_target.runtime_backend != "openvino":
            raise InvalidRequestError(
                "RF-DETR segmentation predictor 仅支持 openvino",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(
                "RF-DETR segmentation predictor 收到了错误的 task_type",
                details={"task_type": runtime_target.task_type},
            )
        import cv2
        import numpy as np
        import torch

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
        all_output_ports = tuple(session.output(index) for index in range(len(session.outputs)))
        if len(all_output_ports) < 3:
            raise ServiceConfigurationError(
                "OpenVINO RF-DETR segmentation 模型输出数量不足",
                details={"output_count": len(all_output_ports)},
            )
        all_output_names = tuple(
            resolve_openvino_port_name(port, fallback=f"output-{index}")
            for index, port in enumerate(all_output_ports)
        )
        resolved_output_names = resolve_rfdetr_runtime_output_names(
            task_type=runtime_target.task_type,
            output_names=all_output_names,
        )
        output_ports = tuple(
            all_output_ports[all_output_names.index(output_name)]
            for output_name in resolved_output_names
        )
        imports = type(
            "_RfdetrSegmentationOpenVinoImports",
            (),
            {"cv2": cv2, "np": np, "torch": torch},
        )()
        return cls(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            imports=imports,
            session=session,
            device_name=runtime_target.device_name or "auto",
            input_name=resolve_openvino_port_name(input_port, fallback="images"),
            output_names=resolved_output_names,
            input_port=input_port,
            output_ports=output_ports,
            compiled_device_name=compiled_device_name,
            compiled_runtime_precision=resolve_openvino_compiled_runtime_precision(
                session=session,
                fallback_precision=runtime_target.runtime_precision,
            ),
            postprocess_model=build_rfdetr_runtime_postprocess_model(
                task_type=runtime_target.task_type,
            ),
            input_size=resolve_rfdetr_runtime_input_size(
                task_type=runtime_target.task_type,
                model_scale=runtime_target.model_scale,
                input_size=runtime_target.input_size,
            ),
        )

    def predict(self, request: SegmentationPredictionRequest) -> SegmentationPredictionExecutionResult:
        imports = self.imports
        image, decode_ms = load_rfdetr_runtime_input_image(
            cv2_module=imports.cv2,
            np_module=imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        input_array, preprocess_ms = build_rfdetr_input_array(
            cv2_module=imports.cv2,
            np_module=imports.np,
            image=image,
            input_size=self.input_size,
        )

        infer_started_at = perf_counter()
        outputs = self.session.infer_new_request({self.input_port: input_array})
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        raw_tensors = []
        for index, output_port in enumerate(self.output_ports):
            raw_tensor = outputs.get(output_port)
            if raw_tensor is None:
                raw_tensor = outputs.get(self.output_names[index])
            if raw_tensor is None:
                raise InvalidRequestError(
                    "OpenVINO segmentation 推理输出缺少必要张量",
                    details={"missing_output_name": self.output_names[index]},
                )
            raw_tensors.append(raw_tensor)
        processed, postprocess_ms = postprocess_rfdetr_segmentation_outputs(
            torch_module=imports.torch,
            postprocess_model=self.postprocess_model,
            raw_outputs={
                "pred_logits": raw_tensors[0],
                "pred_boxes": raw_tensors[1],
                "pred_masks": raw_tensors[2],
            },
            image_height=int(image.shape[0]),
            image_width=int(image.shape[1]),
        )
        instances = build_rfdetr_segmentation_instances(
            cv2_module=imports.cv2,
            scores=processed["scores"],
            labels=processed["labels"],
            boxes_xyxy=processed["boxes_xyxy"],
            masks=processed["masks"],
            label_names=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            mask_threshold=request.mask_threshold,
        )
        preview_image_bytes = render_rfdetr_segmentation_preview(
            cv2_module=imports.cv2,
            image=image,
            instances=instances,
            save_result_image=request.save_result_image,
        )
        return SegmentationPredictionExecutionResult(
            instances=instances,
            latency_ms=round(decode_ms + preprocess_ms + infer_ms + postprocess_ms, 3),
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=SegmentationRuntimeSessionInfo(
                backend_name="openvino",
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=SegmentationRuntimeTensorSpec(
                    name=self.input_name,
                    shape=(1, 3, self.input_size[0], self.input_size[1]),
                    dtype=resolve_openvino_port_dtype(self.input_port, fallback="float32"),
                ),
                output_specs=tuple(
                    SegmentationRuntimeTensorSpec(
                        name=self.output_names[index],
                        shape=tuple(int(item) for item in raw_tensors[index].shape),
                        dtype=resolve_openvino_port_dtype(output_port, fallback="float32"),
                    )
                    for index, output_port in enumerate(self.output_ports)
                ),
                metadata={
                    "model_type": "rfdetr",
                    "model_scale": self.runtime_target.model_scale,
                    "runtime_execution_mode": describe_runtime_execution_mode(
                        runtime_backend="openvino",
                        runtime_precision=self.runtime_target.runtime_precision,
                        device_name=self.device_name,
                    ),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                    "compiled_device_name": self.compiled_device_name,
                    "compiled_runtime_precision": self.compiled_runtime_precision,
                },
            ),
        )


class TensorRTRfdetrSegmentationRuntimeSession:
    """TensorRT RF-DETR segmentation 会话。"""

    model_type = "rfdetr"
    model_label = "RF-DETR"
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
        all_output_names: tuple[str, ...],
        output_names: tuple[str, ...],
        input_dtype_name: str,
        all_output_dtype_names: tuple[str, ...],
        output_dtype_names: tuple[str, ...],
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
                operation_name="TensorRT RF-DETR segmentation runtime 释放前绑定 CUDA device",
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
        pinned_output_buffer_enabled: bool | None = None,
        pinned_output_buffer_max_bytes: int | None = None,
    ) -> "TensorRTRfdetrSegmentationRuntimeSession":
        del pinned_output_buffer_enabled, pinned_output_buffer_max_bytes
        if runtime_target.runtime_backend != "tensorrt":
            raise InvalidRequestError(
                "RF-DETR segmentation predictor 仅支持 tensorrt",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(
                "RF-DETR segmentation predictor 收到了错误的 task_type",
                details={"task_type": runtime_target.task_type},
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
            operation_name="TensorRT RF-DETR segmentation runtime 切换 CUDA device",
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
                "TensorRT RF-DETR segmentation engine 反序列化失败",
                details={"model_build_id": runtime_target.model_build_id},
            )
        context = engine.create_execution_context()
        if context is None:
            raise ServiceConfigurationError(
                "TensorRT RF-DETR segmentation engine 无法创建 execution context",
                details={"model_build_id": runtime_target.model_build_id},
            )
        stream = ensure_cuda_success(
            cuda_imports.cudart.cudaStreamCreate(),
            operation_name="TensorRT RF-DETR segmentation runtime 创建 CUDA stream",
            details={"device_name": device_name},
        )[0]
        execute_start_event = ensure_cuda_success(
            cuda_imports.cudart.cudaEventCreate(),
            operation_name="TensorRT RF-DETR segmentation runtime 创建执行起点 event",
            details={"device_name": device_name},
        )[0]
        execute_end_event = ensure_cuda_success(
            cuda_imports.cudart.cudaEventCreate(),
            operation_name="TensorRT RF-DETR segmentation runtime 创建执行终点 event",
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
        if len(all_output_names) < 3:
            raise ServiceConfigurationError(
                "TensorRT RF-DETR segmentation engine 输出数量不足",
                details={"output_count": len(all_output_names)},
            )
        output_names = resolve_rfdetr_runtime_output_names(
            task_type=runtime_target.task_type,
            output_names=all_output_names,
        )
        imports = type(
            "_RfdetrSegmentationTensorRTImports",
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

    def predict(self, request: SegmentationPredictionRequest) -> SegmentationPredictionExecutionResult:
        imports = self.imports
        image, decode_ms = load_rfdetr_runtime_input_image(
            cv2_module=imports.cv2,
            np_module=imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        input_array, preprocess_ms = build_rfdetr_input_array(
            cv2_module=imports.cv2,
            np_module=imports.np,
            image=image,
            input_size=self.input_size,
        )
        input_array = input_array.astype(
            resolve_numpy_dtype(np_module=imports.np, dtype_name=self.input_dtype_name),
            copy=False,
        )
        requested_input_shape = tuple(int(dim) for dim in input_array.shape)

        input_device_ptr: int | None = None
        output_device_ptrs: list[int] = []
        output_arrays_by_name: dict[str, Any] = {}
        infer_started_at = perf_counter()
        try:
            ensure_cuda_success(
                imports.cudart.cudaSetDevice(resolve_cuda_device_index(self.device_name)),
                operation_name="TensorRT RF-DETR segmentation runtime 绑定 CUDA device",
                details={"device_name": self.device_name},
            )
            engine_input_shape = normalize_tensor_shape(self.engine.get_tensor_shape(self.input_name))
            if any(dim < 0 for dim in engine_input_shape):
                if self.context.set_input_shape(self.input_name, requested_input_shape) is not True:
                    raise ServiceConfigurationError(
                        "TensorRT RF-DETR segmentation execution context 设置输入 shape 失败",
                        details={
                            "input_name": self.input_name,
                            "requested_input_shape": list(requested_input_shape),
                        },
                    )
            elif engine_input_shape != requested_input_shape:
                raise InvalidRequestError(
                    "TensorRT RF-DETR segmentation 输入尺寸与 engine 不匹配",
                    details={
                        "expected_input_shape": list(engine_input_shape),
                        "actual_input_shape": list(requested_input_shape),
                    },
                )

            input_device_ptr = ensure_cuda_success(
                imports.cudart.cudaMalloc(int(input_array.nbytes)),
                operation_name="TensorRT RF-DETR segmentation 分配输入显存",
                details={"byte_size": int(input_array.nbytes)},
            )[0]
            ensure_cuda_success(
                imports.cudart.cudaMemcpyAsync(
                    input_device_ptr,
                    int(input_array.ctypes.data),
                    int(input_array.nbytes),
                    imports.cudart.cudaMemcpyKind.cudaMemcpyHostToDevice,
                    self.stream,
                ),
                operation_name="TensorRT RF-DETR segmentation 拷贝输入到显存",
                details={"byte_size": int(input_array.nbytes)},
            )
            if self.context.set_tensor_address(self.input_name, int(input_device_ptr)) is not True:
                raise ServiceConfigurationError(
                    "TensorRT RF-DETR segmentation execution context 绑定输入张量失败",
                    details={"input_name": self.input_name},
                )

            for index, output_name in enumerate(self.all_output_names):
                resolved_shape = normalize_tensor_shape(self.context.get_tensor_shape(output_name))
                if any(dim < 0 for dim in resolved_shape):
                    raise ServiceConfigurationError(
                        "TensorRT RF-DETR segmentation 输出 shape 尚未解析完成",
                        details={"output_name": output_name, "shape": list(resolved_shape)},
                    )
                output_dtype = resolve_numpy_dtype(
                    np_module=imports.np,
                    dtype_name=self.all_output_dtype_names[index],
                )
                output_array = imports.np.empty(resolved_shape, dtype=output_dtype)
                output_arrays_by_name[output_name] = output_array
                output_device_ptr = ensure_cuda_success(
                    imports.cudart.cudaMalloc(int(output_array.nbytes)),
                    operation_name="TensorRT RF-DETR segmentation 分配输出显存",
                    details={"output_name": output_name, "byte_size": int(output_array.nbytes)},
                )[0]
                output_device_ptrs.append(output_device_ptr)
                if self.context.set_tensor_address(output_name, int(output_device_ptr)) is not True:
                    raise ServiceConfigurationError(
                        "TensorRT RF-DETR segmentation execution context 绑定输出张量失败",
                        details={"output_name": output_name},
                    )

            ensure_cuda_success(
                imports.cudart.cudaEventRecord(self.execute_start_event, self.stream),
                operation_name="TensorRT RF-DETR segmentation 记录执行起点 event",
                details={"device_name": self.device_name},
            )
            if self.context.execute_async_v3(stream_handle=self.stream) is not True:
                raise ServiceConfigurationError(
                    "TensorRT RF-DETR segmentation execution context 执行推理失败",
                    details={"model_build_id": self.runtime_target.model_build_id},
                )
            ensure_cuda_success(
                imports.cudart.cudaEventRecord(self.execute_end_event, self.stream),
                operation_name="TensorRT RF-DETR segmentation 记录执行终点 event",
                details={"device_name": self.device_name},
            )
            for output_name, output_device_ptr in zip(
                self.all_output_names,
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
                        self.stream,
                    ),
                    operation_name="TensorRT RF-DETR segmentation 拷贝输出到主存",
                    details={"output_name": output_name, "byte_size": int(output_array.nbytes)},
                )
            ensure_cuda_success(
                imports.cudart.cudaStreamSynchronize(self.stream),
                operation_name="TensorRT RF-DETR segmentation 同步 CUDA stream",
                details={"device_name": self.device_name},
            )
            infer_execute_gpu_ms = measure_cuda_event_elapsed_ms(
                cudart_module=imports.cudart,
                start_event=self.execute_start_event,
                end_event=self.execute_end_event,
                device_name=self.device_name,
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

        processed, postprocess_ms = postprocess_rfdetr_segmentation_outputs(
            torch_module=imports.torch,
            postprocess_model=self.postprocess_model,
            raw_outputs={
                "pred_logits": output_arrays_by_name[self.output_names[0]],
                "pred_boxes": output_arrays_by_name[self.output_names[1]],
                "pred_masks": output_arrays_by_name[self.output_names[2]],
            },
            image_height=int(image.shape[0]),
            image_width=int(image.shape[1]),
        )
        instances = build_rfdetr_segmentation_instances(
            cv2_module=imports.cv2,
            scores=processed["scores"],
            labels=processed["labels"],
            boxes_xyxy=processed["boxes_xyxy"],
            masks=processed["masks"],
            label_names=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            mask_threshold=request.mask_threshold,
        )
        preview_image_bytes = render_rfdetr_segmentation_preview(
            cv2_module=imports.cv2,
            image=image,
            instances=instances,
            save_result_image=request.save_result_image,
        )
        return SegmentationPredictionExecutionResult(
            instances=instances,
            latency_ms=round(decode_ms + preprocess_ms + infer_ms + postprocess_ms, 3),
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=SegmentationRuntimeSessionInfo(
                backend_name="tensorrt",
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=SegmentationRuntimeTensorSpec(
                    name=self.input_name,
                    shape=requested_input_shape,
                    dtype=self.input_dtype_name,
                ),
                output_specs=tuple(
                    SegmentationRuntimeTensorSpec(
                        name=output_name,
                        shape=tuple(
                            int(item) for item in output_arrays_by_name[output_name].shape
                        ),
                        dtype=self.output_dtype_names[index],
                    )
                    for index, output_name in enumerate(self.output_names)
                ),
                metadata={
                    "model_type": "rfdetr",
                    "model_scale": self.runtime_target.model_scale,
                    "runtime_execution_mode": describe_runtime_execution_mode(
                        runtime_backend="tensorrt",
                        runtime_precision=self.runtime_target.runtime_precision,
                        device_name=self.device_name,
                    ),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "infer_execute_gpu_ms": infer_execute_gpu_ms,
                    "postprocess_ms": postprocess_ms,
                    "engine_output_names": list(self.all_output_names),
                    "output_names": list(self.output_names),
                },
            ),
        )




