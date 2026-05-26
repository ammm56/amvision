"""YOLOX 单图预测接口与多 runtime 实现。"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
import sys
from time import perf_counter
from typing import Any, Protocol

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.yolox_detection_training import (
    _build_yolox_model,
    _load_warm_start_checkpoint,
    _require_training_imports,
)
from backend.service.application.runtime.yolox_runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
    resolve_local_file_path,
)
from backend.service.settings import get_backend_service_settings
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.shared.yolox_runtime_contracts import RuntimeTensorSpec, YoloXRuntimeSessionInfo


_DEFAULT_NMS_THRESHOLD = 0.65
_TENSORRT_LOGGER: Any | None = None
_TENSORRT_LOGGER_SEVERITY: int | None = None


@dataclass(frozen=True)
class YoloXPredictionRequest:
    """描述一次 YOLOX 单图预测请求。

    字段：
    - input_uri：storage 模式下的输入图片 URI 或 object key。
    - input_image_bytes：memory 模式下直接提供的原始图片字节。
    - input_image_payload：跨进程 image-ref payload；deployment worker 会先解析为 uri 或 bytes。
    - score_threshold：预测阈值。
    - save_result_image：是否生成预览图。
    - extra_options：附加运行时选项。
    """

    score_threshold: float
    save_result_image: bool
    input_uri: str | None = None
    input_image_bytes: bytes | None = None
    input_image_payload: dict[str, object] | None = None
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXPredictionDetection:
    """描述单条 YOLOX detection 结果。

    字段：
    - bbox_xyxy：边界框坐标。
    - score：置信度。
    - class_id：类别 id。
    - class_name：类别名。
    """

    bbox_xyxy: tuple[float, float, float, float]
    score: float
    class_id: int
    class_name: str | None = None


@dataclass(frozen=True)
class YoloXPredictionExecutionResult:
    """描述一次 YOLOX 单图预测执行结果。

    字段：
    - detections：检测框列表。
    - latency_ms：decode、preprocess、infer、postprocess 四段总耗时。
    - image_width：原图宽度。
    - image_height：原图高度。
    - preview_image_bytes：可选预览图字节内容。
    - runtime_session_info：运行时摘要。
    """

    detections: tuple[YoloXPredictionDetection, ...]
    latency_ms: float | None
    image_width: int
    image_height: int
    preview_image_bytes: bytes | None
    runtime_session_info: YoloXRuntimeSessionInfo


@dataclass(frozen=True)
class _YoloXInferenceImports:
    """描述轻量推理路径所需的第三方依赖对象。

    字段：
    - cv2：OpenCV 模块。
    - np：NumPy 模块。
    """

    cv2: Any
    np: Any


@dataclass(frozen=True)
class _YoloXCudaInferenceImports:
    """描述 TensorRT/CUDA 推理路径所需的第三方依赖对象。

    字段：
    - cv2：OpenCV 模块。
    - np：NumPy 模块。
    - cudart：cuda-python 运行时 API 模块。
    """

    cv2: Any
    np: Any
    cudart: Any


class YoloXPredictor(Protocol):
    """定义 YOLOX 单图 predictor 接口。"""

    def predict(
        self,
        runtime_target: RuntimeTargetSnapshot,
        request: YoloXPredictionRequest,
    ) -> YoloXPredictionExecutionResult:
        """执行一次单图预测。

        参数：
        - runtime_target：运行时快照。
        - request：预测请求。

        返回：
        - YoloXPredictionExecutionResult：预测执行结果。
        """


class YoloXPredictionSession(Protocol):
    """定义可重复执行的 YOLOX runtime session 接口。"""

    def predict(self, request: YoloXPredictionRequest) -> YoloXPredictionExecutionResult:
        """使用已加载的模型会话执行一次预测。

        参数：
        - request：预测请求。

        返回：
        - YoloXPredictionExecutionResult：预测执行结果。
        """


class PyTorchYoloXRuntimeSession:
    """描述一个已经加载完成并可重复推理的 PyTorch YOLOX 会话。

    属性：
    - dataset_storage：本地文件存储服务。
    - runtime_target：当前会话绑定的运行时快照。
    - imports：YOLOX 推理依赖集合。
    - model：已经加载 checkpoint 的模型对象。
    - device_name：当前执行 device 名称。
    - runtime_precision：当前执行 precision。
    """

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
        """初始化一个已加载完成的 PyTorch runtime session。

        参数：
        - dataset_storage：本地文件存储服务。
        - runtime_target：当前会话绑定的运行时快照。
        - imports：YOLOX 推理依赖集合。
        - model：已经加载 checkpoint 的模型对象。
        - device_name：当前执行 device 名称。
        - runtime_precision：当前执行 precision。
        """

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
    ) -> PyTorchYoloXRuntimeSession:
        """加载一次 PyTorch runtime session。

        参数：
        - dataset_storage：本地文件存储服务。
        - runtime_target：待加载的运行时快照。

        返回：
        - PyTorchYoloXRuntimeSession：已完成模型加载的会话对象。
        """

        if runtime_target.runtime_backend != "pytorch":
            raise InvalidRequestError(
                "当前 predictor 仅支持 pytorch runtime_backend",
                details={
                    "runtime_backend": runtime_target.runtime_backend,
                    "model_build_id": runtime_target.model_build_id,
                },
            )

        imports = _require_training_imports()
        model = _build_yolox_model(
            imports=imports,
            model_scale=runtime_target.model_scale,
            num_classes=len(runtime_target.labels),
        )
        _load_warm_start_checkpoint(
            imports=imports,
            model=model,
            checkpoint_path=runtime_target.runtime_artifact_path,
            source_summary={
                "source_model_version_id": runtime_target.model_version_id,
                "runtime_artifact_file_id": runtime_target.runtime_artifact_file_id,
                "runtime_artifact_file_type": runtime_target.runtime_artifact_file_type,
                "source_model_build_id": runtime_target.model_build_id,
            },
        )
        device_name = _resolve_execution_device_name(
            torch_module=imports.torch,
            requested_device_name=runtime_target.device_name,
        )
        _enable_pytorch_cuda_inference_fast_path(
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

    def predict(self, request: YoloXPredictionRequest) -> YoloXPredictionExecutionResult:
        """使用当前常驻会话执行一次单图预测。

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
        input_tensor = self.imports.torch.from_numpy(input_tensor).unsqueeze(0).to(self.device_name)
        input_tensor = input_tensor.float()
        if self.runtime_precision == "fp16":
            input_tensor = input_tensor.half()
        preprocess_ms = _measure_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=preprocess_started_at,
        )

        nms_threshold = _resolve_probability(
            value=request.extra_options.get("nms_threshold"),
            field_name="nms_threshold",
            default=_DEFAULT_NMS_THRESHOLD,
        )

        infer_started_at = perf_counter()
        inference_mode = getattr(self.imports.torch, "inference_mode", None)
        if callable(inference_mode):
            with inference_mode():
                outputs = self.model(input_tensor)
        else:
            with self.imports.torch.no_grad():
                outputs = self.model(input_tensor)
        infer_ms = _measure_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=infer_started_at,
        )

        image_height = int(image.shape[0])
        image_width = int(image.shape[1])

        postprocess_started_at = perf_counter()
        predictions = self.imports.postprocess(
            outputs,
            len(self.runtime_target.labels),
            conf_thre=request.score_threshold,
            nms_thre=nms_threshold,
        )
        detections = _build_detection_records(
            np_module=self.imports.np,
            predictions=predictions,
            resize_ratio=resize_ratio,
            labels=self.runtime_target.labels,
            image_width=image_width,
            image_height=image_height,
        )
        postprocess_ms = _measure_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=postprocess_started_at,
        )
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = None
        if request.save_result_image:
            preview_image_bytes = _render_preview_image(
                cv2_module=self.imports.cv2,
                image=image,
                detections=detections,
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
                    name="images",
                    shape=(1, 3, self.runtime_target.input_size[0], self.runtime_target.input_size[1]),
                    dtype="float16" if self.runtime_precision == "fp16" else "float32",
                ),
                output_spec=RuntimeTensorSpec(
                    name="detections",
                    shape=(-1, 7),
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
                    "nms_threshold": nms_threshold,
                    "class_count": len(self.runtime_target.labels),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                },
            ),
        )


class PyTorchYoloXPredictor:
    """基于 PyTorch runtime artifact 的 YOLOX 单图 predictor。"""

    def __init__(self, *, dataset_storage: LocalDatasetStorage) -> None:
        """初始化 predictor。

        参数：
        - dataset_storage：本地文件存储服务。
        """

        self.dataset_storage = dataset_storage

    def predict(
        self,
        runtime_target: RuntimeTargetSnapshot,
        request: YoloXPredictionRequest,
    ) -> YoloXPredictionExecutionResult:
        """执行一次基于 RuntimeTargetSnapshot 的单图预测。

        参数：
        - runtime_target：运行时快照。
        - request：预测请求。

        返回：
        - YoloXPredictionExecutionResult：预测执行结果。
        """

        return PyTorchYoloXRuntimeSession.load(
            dataset_storage=self.dataset_storage,
            runtime_target=runtime_target,
        ).predict(request)


class OnnxRuntimeYoloXRuntimeSession:
    """描述一个已经加载完成并可重复推理的 ONNXRuntime YOLOX 会话。

    属性：
    - dataset_storage：本地文件存储服务。
    - runtime_target：当前会话绑定的运行时快照。
    - imports：YOLOX 推理依赖集合。
    - session：已经加载完成的 ONNXRuntime InferenceSession。
    - device_name：当前执行 device 名称。
    - input_name：模型输入张量名称。
    - output_name：模型输出张量名称。
    """

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
        """初始化一个已加载完成的 ONNXRuntime runtime session。

        参数：
        - dataset_storage：本地文件存储服务。
        - runtime_target：当前会话绑定的运行时快照。
        - imports：YOLOX 推理依赖集合。
        - session：已经加载完成的 ONNXRuntime InferenceSession。
        - device_name：当前执行 device 名称。
        - input_name：模型输入张量名称。
        - output_name：模型输出张量名称。
        """

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
    ) -> OnnxRuntimeYoloXRuntimeSession:
        """加载一次 ONNXRuntime runtime session。

        参数：
        - dataset_storage：本地文件存储服务。
        - runtime_target：待加载的运行时快照。

        返回：
        - OnnxRuntimeYoloXRuntimeSession：已完成模型加载的会话对象。
        """

        if runtime_target.runtime_backend != "onnxruntime":
            raise InvalidRequestError(
                "当前 predictor 仅支持 onnxruntime runtime_backend",
                details={
                    "runtime_backend": runtime_target.runtime_backend,
                    "model_build_id": runtime_target.model_build_id,
                },
            )
        if runtime_target.runtime_precision != "fp32":
            raise InvalidRequestError(
                "当前 onnxruntime runtime session 仅支持 fp32 precision",
                details={
                    "runtime_backend": runtime_target.runtime_backend,
                    "runtime_precision": runtime_target.runtime_precision,
                    "model_build_id": runtime_target.model_build_id,
                },
            )

        imports = _require_inference_imports()
        onnxruntime_module = _import_onnxruntime_module()
        providers = _resolve_onnxruntime_providers(
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

    def predict(self, request: YoloXPredictionRequest) -> YoloXPredictionExecutionResult:
        """使用当前常驻会话执行一次单图预测。

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
        decode_ms = round((perf_counter() - decode_started_at) * 1000, 3)

        preprocess_started_at = perf_counter()
        input_tensor, resize_ratio = _preprocess_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            image=image,
            input_size=self.runtime_target.input_size,
        )
        input_tensor = self.imports.np.expand_dims(input_tensor, axis=0).astype(self.imports.np.float32, copy=False)
        preprocess_ms = round((perf_counter() - preprocess_started_at) * 1000, 3)

        nms_threshold = _resolve_probability(
            value=request.extra_options.get("nms_threshold"),
            field_name="nms_threshold",
            default=_DEFAULT_NMS_THRESHOLD,
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
        predictions = _postprocess_prediction_array(
            prediction_array=_normalize_onnxruntime_outputs(outputs=outputs, imports=self.imports),
            np_module=self.imports.np,
            num_classes=len(self.runtime_target.labels),
            conf_thre=request.score_threshold,
            nms_thre=nms_threshold,
        )
        detections = _build_detection_records(
            np_module=self.imports.np,
            predictions=predictions,
            resize_ratio=resize_ratio,
            labels=self.runtime_target.labels,
            image_width=image_width,
            image_height=image_height,
        )
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = None
        if request.save_result_image:
            preview_image_bytes = _render_preview_image(
                cv2_module=self.imports.cv2,
                image=image,
                detections=detections,
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
                    shape=(1, 3, self.runtime_target.input_size[0], self.runtime_target.input_size[1]),
                    dtype="float32",
                ),
                output_spec=RuntimeTensorSpec(
                    name=self.output_name,
                    shape=(-1, 7),
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
                    "nms_threshold": nms_threshold,
                    "class_count": len(self.runtime_target.labels),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                    "provider_names": list(self.session.get_providers()),
                },
            ),
        )


class OpenVINOYoloXRuntimeSession:
    """描述一个已经加载完成并可重复推理的 OpenVINO YOLOX 会话。

    属性：
    - dataset_storage：本地文件存储服务。
    - runtime_target：当前会话绑定的运行时快照。
    - imports：轻量推理依赖集合。
    - session：已经加载完成的 OpenVINO CompiledModel。
    - device_name：当前执行 device 名称。
    - input_name：模型输入张量名称。
    - output_name：模型输出张量名称。
    - input_port：模型主输入端口对象。
    - output_port：模型主输出端口对象。
    - compiled_device_name：传给 OpenVINO 的实际 device 选择串。
    - compiled_runtime_precision：当前编译后实际采用的 runtime precision。
    """

    def __init__(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        imports: _YoloXInferenceImports,
        session: Any,
        device_name: str,
        input_name: str,
        output_name: str,
        input_port: Any,
        output_port: Any,
        compiled_device_name: str,
        compiled_runtime_precision: str,
    ) -> None:
        """初始化一个已加载完成的 OpenVINO runtime session。

        参数：
        - dataset_storage：本地文件存储服务。
        - runtime_target：当前会话绑定的运行时快照。
        - imports：轻量推理依赖集合。
        - session：已经加载完成的 OpenVINO CompiledModel。
        - device_name：当前执行 device 名称。
        - input_name：模型输入张量名称。
        - output_name：模型输出张量名称。
        - input_port：模型主输入端口对象。
        - output_port：模型主输出端口对象。
        - compiled_device_name：传给 OpenVINO 的实际 device 选择串。
        - compiled_runtime_precision：当前编译后实际采用的 runtime precision。
        """

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
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
    ) -> OpenVINOYoloXRuntimeSession:
        """加载一次 OpenVINO runtime session。

        参数：
        - dataset_storage：本地文件存储服务。
        - runtime_target：待加载的运行时快照。

        返回：
        - OpenVINOYoloXRuntimeSession：已完成模型加载的会话对象。
        """

        if runtime_target.runtime_backend != "openvino":
            raise InvalidRequestError(
                "当前 predictor 仅支持 openvino runtime_backend",
                details={
                    "runtime_backend": runtime_target.runtime_backend,
                    "model_build_id": runtime_target.model_build_id,
                },
            )

        imports = _require_inference_imports()
        openvino_module = _import_openvino_module()
        compiled_device_name = _resolve_openvino_device_name(
            requested_device_name=runtime_target.device_name,
        )
        compile_properties = _build_openvino_compile_properties(
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
            input_name=_resolve_openvino_port_name(input_port, fallback="images"),
            output_name=_resolve_openvino_port_name(output_port, fallback="predictions"),
            input_port=input_port,
            output_port=output_port,
            compiled_device_name=compiled_device_name,
            compiled_runtime_precision=_resolve_openvino_compiled_runtime_precision(
                session=session,
                fallback_precision=runtime_target.runtime_precision,
            ),
        )

    def predict(self, request: YoloXPredictionRequest) -> YoloXPredictionExecutionResult:
        """使用当前常驻会话执行一次单图预测。

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
        decode_ms = round((perf_counter() - decode_started_at) * 1000, 3)

        preprocess_started_at = perf_counter()
        input_tensor, resize_ratio = _preprocess_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            image=image,
            input_size=self.runtime_target.input_size,
        )
        input_tensor = self.imports.np.expand_dims(input_tensor, axis=0).astype(self.imports.np.float32, copy=False)
        preprocess_ms = round((perf_counter() - preprocess_started_at) * 1000, 3)

        nms_threshold = _resolve_probability(
            value=request.extra_options.get("nms_threshold"),
            field_name="nms_threshold",
            default=_DEFAULT_NMS_THRESHOLD,
        )

        infer_started_at = perf_counter()
        outputs = self.session.infer_new_request({self.input_port: input_tensor})
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        image_height = int(image.shape[0])
        image_width = int(image.shape[1])

        postprocess_started_at = perf_counter()
        predictions = _postprocess_prediction_array(
            prediction_array=_normalize_openvino_outputs(
                outputs=outputs,
                output_port=self.output_port,
                output_name=self.output_name,
                imports=self.imports,
            ),
            np_module=self.imports.np,
            num_classes=len(self.runtime_target.labels),
            conf_thre=request.score_threshold,
            nms_thre=nms_threshold,
        )
        detections = _build_detection_records(
            np_module=self.imports.np,
            predictions=predictions,
            resize_ratio=resize_ratio,
            labels=self.runtime_target.labels,
            image_width=image_width,
            image_height=image_height,
        )
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = None
        if request.save_result_image:
            preview_image_bytes = _render_preview_image(
                cv2_module=self.imports.cv2,
                image=image,
                detections=detections,
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
                    shape=(1, 3, self.runtime_target.input_size[0], self.runtime_target.input_size[1]),
                    dtype=_resolve_openvino_port_dtype(self.input_port, fallback="float32"),
                ),
                output_spec=RuntimeTensorSpec(
                    name=self.output_name,
                    shape=(-1, 7),
                    dtype=_resolve_openvino_port_dtype(self.output_port, fallback="float32"),
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
                    "compiled_device_name": self.compiled_device_name,
                    "compiled_runtime_precision": self.compiled_runtime_precision,
                },
            ),
        )


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
        predictions = _postprocess_prediction_array(
            prediction_array=_normalize_tensorrt_outputs(
                output_array=output_array,
                imports=self.imports,
            ),
            np_module=self.imports.np,
            num_classes=len(self.runtime_target.labels),
            conf_thre=request.score_threshold,
            nms_thre=nms_threshold,
        )
        detections = _build_detection_records(
            np_module=self.imports.np,
            predictions=predictions,
            resize_ratio=resize_ratio,
            labels=self.runtime_target.labels,
            image_width=image_width,
            image_height=image_height,
        )
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = None
        if request.save_result_image:
            preview_image_bytes = _render_preview_image(
                cv2_module=self.imports.cv2,
                image=image,
                detections=detections,
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


def _load_prediction_image(
    *,
    cv2_module: Any,
    np_module: Any,
    dataset_storage: LocalDatasetStorage,
    request: YoloXPredictionRequest,
) -> Any:
    """按 storage 或 memory 模式加载本次推理输入图片。

    参数：
    - cv2_module：OpenCV 模块。
    - np_module：NumPy 模块。
    - dataset_storage：本地文件存储服务。
    - request：推理请求。

    返回：
    - Any：OpenCV 读取后的图片矩阵。
    """

    has_input_uri = isinstance(request.input_uri, str) and request.input_uri.strip()
    has_input_image_bytes = isinstance(request.input_image_bytes, bytes) and bool(request.input_image_bytes)
    if has_input_uri == has_input_image_bytes:
        raise InvalidRequestError(
            "推理请求必须且只能提供 input_uri 或 input_image_bytes 其中一个",
            details={
                "provided_input_uri": bool(has_input_uri),
                "provided_input_image_bytes": bool(has_input_image_bytes),
            },
        )
    if has_input_uri:
        image_path = resolve_local_file_path(
            dataset_storage=dataset_storage,
            storage_uri=request.input_uri or "",
            field_name="input_uri",
        )
        image = cv2_module.imread(str(image_path))
        if image is None:
            raise InvalidRequestError(
                "input_uri 指向的图片无法读取",
                details={"input_uri": request.input_uri},
            )
        return image

    buffer = np_module.frombuffer(request.input_image_bytes or b"", dtype=np_module.uint8)
    image = cv2_module.imdecode(buffer, cv2_module.IMREAD_COLOR)
    if image is None:
        raise InvalidRequestError(
            "input_image_bytes 不是可读取的图片内容",
            details={"field": "input_image_bytes"},
        )
    return image


def serialize_detection(detection: YoloXPredictionDetection) -> dict[str, object]:
    """把 detection 记录转换为 JSON 字典。"""

    return {
        "bbox_xyxy": list(detection.bbox_xyxy),
        "score": detection.score,
        "class_id": detection.class_id,
        "class_name": detection.class_name,
    }


def serialize_runtime_session_info(session_info: YoloXRuntimeSessionInfo) -> dict[str, object]:
    """把 runtime session info 转换为 JSON 字典。"""

    return {
        "backend_name": session_info.backend_name,
        "model_uri": session_info.model_uri,
        "device_name": session_info.device_name,
        "input_spec": {
            "name": session_info.input_spec.name,
            "shape": list(session_info.input_spec.shape),
            "dtype": session_info.input_spec.dtype,
        },
        "output_spec": {
            "name": session_info.output_spec.name,
            "shape": list(session_info.output_spec.shape),
            "dtype": session_info.output_spec.dtype,
        },
        "metadata": dict(session_info.metadata),
    }


def _measure_stage_elapsed_ms(*, imports: Any, device_name: str, started_at: float) -> float:
    """测量单个推理阶段的耗时，并在 CUDA 设备上补齐同步边界。

    参数：
    - imports：YOLOX 运行时依赖集合。
    - device_name：当前执行 device 名称。
    - started_at：阶段开始时的 perf_counter 值。

    返回：
    - float：阶段耗时，单位毫秒。
    """

    _synchronize_device_for_timing(imports=imports, device_name=device_name)
    return round((perf_counter() - started_at) * 1000, 3)


def _require_inference_imports() -> _YoloXInferenceImports:
    """按需导入轻量推理路径所需依赖。

    参数：
    - 无。

    返回：
    - _YoloXInferenceImports：仅包含 OpenCV 与 NumPy 的依赖集合。
    """

    try:
        import cv2  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except ImportError as error:  # pragma: no cover - 依赖存在时不会进入该分支
        raise ServiceConfigurationError("当前运行环境缺少 opencv-python 或 numpy 依赖") from error
    return _YoloXInferenceImports(cv2=cv2, np=np)


def _require_cuda_inference_imports() -> _YoloXCudaInferenceImports:
    """按需导入 TensorRT/CUDA 推理路径所需依赖。

    参数：
    - 无。

    返回：
    - _YoloXCudaInferenceImports：包含 OpenCV、NumPy 与 cuda-python 的依赖集合。
    """

    inference_imports = _require_inference_imports()
    return _YoloXCudaInferenceImports(
        cv2=inference_imports.cv2,
        np=inference_imports.np,
        cudart=_import_cuda_runtime_module(),
    )


def _import_cuda_runtime_module() -> Any:
    """导入 cuda-python 的 cudart 模块并在缺失时抛出明确错误。"""

    try:
        from cuda import cudart
    except ImportError as error:  # pragma: no cover - 依赖存在时不会进入该分支
        raise ServiceConfigurationError("当前运行环境缺少 cuda-python 依赖") from error
    return cudart


def _import_onnxruntime_module() -> Any:
    """导入 ONNXRuntime 模块并在缺失时抛出明确错误。"""

    try:
        import onnxruntime
    except ImportError as error:  # pragma: no cover - 依赖存在时不会进入该分支
        raise ServiceConfigurationError("当前运行环境缺少 onnxruntime 依赖") from error
    return onnxruntime


def _import_openvino_module() -> Any:
    """导入 OpenVINO 模块并在缺失时抛出明确错误。

    参数：
    - 无。

    返回：
    - Any：OpenVINO 顶层模块对象。
    """

    try:
        import openvino
    except ImportError as error:  # pragma: no cover - 依赖存在时不会进入该分支
        raise ServiceConfigurationError("当前运行环境缺少 openvino 依赖") from error
    return openvino


def _import_tensorrt_module() -> Any:
    """导入 TensorRT 模块并在缺失时抛出明确错误。"""

    try:
        import tensorrt
    except ImportError as error:  # pragma: no cover - 依赖存在时不会进入该分支
        raise ServiceConfigurationError("当前运行环境缺少 tensorrt 依赖") from error
    return tensorrt


def _get_tensorrt_logger(*, tensorrt_module: Any, severity: Any) -> Any:
    """返回进程级复用的 TensorRT logger，避免重复注册 warning。"""

    global _TENSORRT_LOGGER
    global _TENSORRT_LOGGER_SEVERITY
    resolved_severity = int(severity)
    if _TENSORRT_LOGGER is None or _TENSORRT_LOGGER_SEVERITY != resolved_severity:
        _TENSORRT_LOGGER = tensorrt_module.Logger(severity)
        _TENSORRT_LOGGER_SEVERITY = resolved_severity
    return _TENSORRT_LOGGER


def _resolve_onnxruntime_providers(*, onnxruntime_module: Any, requested_device_name: str) -> list[object]:
    """按 device_name 解析 ONNXRuntime provider 列表。"""

    if requested_device_name != "cpu":
        raise InvalidRequestError(
            "当前 onnxruntime runtime session 仅支持 cpu device_name",
            details={"device_name": requested_device_name},
        )
    available_providers = set(onnxruntime_module.get_available_providers())
    if "CPUExecutionProvider" not in available_providers:
        raise ServiceConfigurationError(
            "当前运行环境缺少 CPUExecutionProvider，无法执行 onnxruntime 推理",
            details={"available_providers": sorted(available_providers)},
        )
    return ["CPUExecutionProvider"]


def _resolve_openvino_device_name(*, requested_device_name: str) -> str:
    """按 device_name 解析 OpenVINO 设备选择串。

    参数：
    - requested_device_name：运行时快照中的 device 名称。

    返回：
    - str：OpenVINO compile_model 使用的设备字符串。
    """

    device_name_map = {
        "auto": "AUTO",
        "cpu": "CPU",
        "gpu": "GPU",
        "npu": "NPU",
    }
    resolved = device_name_map.get(requested_device_name)
    if resolved is None:
        raise InvalidRequestError(
            "当前 openvino runtime session 仅支持 auto、cpu、gpu 或 npu device_name",
            details={"device_name": requested_device_name},
        )
    return resolved


def _build_openvino_compile_properties(
    *,
    openvino_module: Any,
    runtime_precision: str,
    requested_device_name: str,
) -> dict[object, object]:
    """按 runtime precision 构造 OpenVINO compile_model 属性。"""

    if runtime_precision == "fp32":
        return {}
    if runtime_precision == "fp16" and requested_device_name in {"gpu", "npu"}:
        return {openvino_module.properties.hint.inference_precision: openvino_module.Type.f16}
    raise InvalidRequestError(
        "openvino fp16 仅支持 gpu 或 npu device_name；auto/cpu 仍要求 fp32",
        details={
            "runtime_backend": "openvino",
            "runtime_precision": runtime_precision,
            "device_name": requested_device_name,
        },
    )


def _resolve_openvino_compiled_runtime_precision(*, session: Any, fallback_precision: str) -> str:
    """读取 OpenVINO 编译后实际采用的 runtime precision。"""

    try:
        resolved = session.get_property("INFERENCE_PRECISION_HINT")
    except Exception:
        return fallback_precision
    normalized = _normalize_openvino_type_name(resolved)
    precision_map = {
        "float16": "fp16",
        "float32": "fp32",
    }
    return precision_map.get(normalized, fallback_precision)


def _resolve_openvino_port_dtype(port: Any, *, fallback: str) -> str:
    """读取 OpenVINO 端口实际张量 dtype。"""

    element_type_getter = getattr(port, "get_element_type", None)
    if not callable(element_type_getter):
        return fallback
    try:
        return _normalize_openvino_type_name(element_type_getter()) or fallback
    except Exception:
        return fallback


def _normalize_openvino_type_name(value: object) -> str:
    """把 OpenVINO 类型对象归一化为稳定字符串。"""

    normalized = str(value).strip().lower()
    if normalized.startswith("<type: '") and normalized.endswith("'>"):
        normalized = normalized[len("<type: '") : -2]
    type_name_map = {
        "f16": "float16",
        "f32": "float32",
    }
    return type_name_map.get(normalized, normalized)


def _resolve_openvino_port_name(port: Any, *, fallback: str) -> str:
    """从 OpenVINO 端口对象提取稳定名称。

    参数：
    - port：OpenVINO 输入或输出端口对象。
    - fallback：端口未暴露名称时使用的回退值。

    返回：
    - str：端口名称或回退值。
    """

    for attribute_name in ("get_any_name", "any_name"):
        resolver = getattr(port, attribute_name, None)
        if resolver is None:
            continue
        try:
            resolved_name = resolver() if callable(resolver) else resolver
        except Exception:
            continue
        normalized_name = str(resolved_name).strip()
        if normalized_name:
            return normalized_name
    names_getter = getattr(port, "get_names", None)
    if callable(names_getter):
        try:
            resolved_names = tuple(
                sorted(str(item).strip() for item in names_getter() if str(item).strip())
            )
        except Exception:
            resolved_names = ()
        if resolved_names:
            return resolved_names[0]
    return fallback


def _resolve_tensorrt_io_tensor_name(*, engine: Any, tensorrt_module: Any, io_mode: Any, fallback: str) -> str:
    """返回 TensorRT engine 中首个匹配 I/O 类型的张量名称。"""

    for tensor_index in range(int(engine.num_io_tensors)):
        tensor_name = str(engine.get_tensor_name(tensor_index))
        if engine.get_tensor_mode(tensor_name) == io_mode:
            return tensor_name
    raise ServiceConfigurationError(
        "TensorRT engine 缺少期望的 I/O 张量",
        details={
            "io_mode": "input" if io_mode == tensorrt_module.TensorIOMode.INPUT else "output",
            "fallback": fallback,
        },
    )


def _normalize_tensor_shape(shape: object) -> tuple[int, ...]:
    """把后端返回的 shape 对象归一化为整数元组。"""

    try:
        return tuple(int(dim) for dim in shape)
    except TypeError:
        return ()


def _resolve_tensorrt_dtype_name(*, tensorrt_module: Any, tensor_dtype: Any, fallback: str) -> str:
    """把 TensorRT dtype 对象归一化为稳定字符串。"""

    normalized_name_map = {
        str(tensorrt_module.float32).strip().lower(): "float32",
        str(tensorrt_module.float16).strip().lower(): "float16",
        str(tensorrt_module.int32).strip().lower(): "int32",
    }
    normalized = str(tensor_dtype).strip().lower()
    return normalized_name_map.get(normalized, fallback)


def _resolve_numpy_dtype(*, np_module: Any, dtype_name: str) -> Any:
    """把稳定字符串 dtype 映射为 NumPy dtype。"""

    dtype_map = {
        "float32": np_module.float32,
        "float16": np_module.float16,
        "int32": np_module.int32,
    }
    resolved_dtype = dtype_map.get(dtype_name)
    if resolved_dtype is None:
        raise ServiceConfigurationError(
            "当前 TensorRT session 发现了不支持的张量 dtype",
            details={"dtype_name": dtype_name},
        )
    return resolved_dtype


def _resolve_tensor_byte_size(*, np_module: Any, shape: tuple[int, ...], dtype: Any) -> int:
    """根据张量 shape 和 dtype 计算连续缓冲需要的字节数。

    参数：
    - np_module：NumPy 模块。
    - shape：张量 shape。
    - dtype：NumPy dtype。

    返回：
    - int：当前张量连续存储所需字节数。
    """

    element_count = 1
    for dim in shape:
        element_count *= int(dim)
    return element_count * int(np_module.dtype(dtype).itemsize)


def _build_numpy_array_from_host_pointer(
    *,
    np_module: Any,
    host_ptr: int,
    byte_size: int,
    dtype: Any,
    shape: tuple[int, ...],
) -> Any:
    """把 host pointer 包装成指定 dtype 和 shape 的 NumPy 视图。

    参数：
    - np_module：NumPy 模块。
    - host_ptr：host pointer 整数地址。
    - byte_size：缓冲总字节数。
    - dtype：目标 NumPy dtype。
    - shape：目标数组 shape。

    返回：
    - Any：直接映射到既有 host memory 的 NumPy 数组视图。
    """

    if int(host_ptr) <= 0 or int(byte_size) <= 0:
        raise ServiceConfigurationError(
            "TensorRT pinned host buffer 参数不合法",
            details={"host_ptr": int(host_ptr), "byte_size": int(byte_size)},
        )
    raw_bytes = np_module.ctypeslib.as_array(
        (ctypes.c_ubyte * int(byte_size)).from_address(int(host_ptr))
    )
    return raw_bytes.view(dtype=dtype).reshape(shape)


def _resolve_cuda_device_index(device_name: str) -> int:
    """把 cuda:<index> 设备名解析为整数索引。"""

    if device_name == "cuda":
        return 0
    if device_name.startswith("cuda:"):
        raw_index = device_name.split(":", 1)[1]
        if raw_index.isdigit():
            return int(raw_index)
    raise InvalidRequestError(
        "device_name 必须是 cuda 或 cuda:<index>",
        details={"device_name": device_name},
    )


def _resolve_cuda_runtime_device_name(*, cudart_module: Any, requested_device_name: str) -> str:
    """在不依赖 torch 的前提下校验并返回 CUDA device 名称。"""

    device_name = requested_device_name.strip().lower() if requested_device_name.strip() else "cuda:0"
    if device_name == "cuda":
        device_name = "cuda:0"
    if not device_name.startswith("cuda:"):
        raise InvalidRequestError(
            "device_name 必须是 cuda 或 cuda:<index>",
            details={"device_name": requested_device_name},
        )
    device_index = _resolve_cuda_device_index(device_name)
    cuda_status, available_device_count = cudart_module.cudaGetDeviceCount()
    if int(cuda_status) != 0:
        raise ServiceConfigurationError(
            "当前运行环境无法读取 CUDA device 列表",
            details={"device_name": device_name, "status_code": int(cuda_status), "status_name": cuda_status.name},
        )
    if int(available_device_count) <= 0:
        raise InvalidRequestError(
            "当前运行环境没有可用 GPU，不能使用 CUDA 预测",
            details={"device_name": device_name},
        )
    if device_index >= int(available_device_count):
        raise InvalidRequestError(
            "指定的 CUDA device 超出了本机可用 GPU 范围",
            details={"device_name": device_name, "available_gpu_count": int(available_device_count)},
        )
    return device_name


def _ensure_cuda_success(
    result: object,
    *,
    operation_name: str,
    details: dict[str, object] | None = None,
) -> tuple[object, ...]:
    """校验 cuda-python API 返回值，并在失败时抛出明确错误。"""

    if not isinstance(result, tuple) or not result:
        raise ServiceConfigurationError(
            f"{operation_name} 返回值格式不合法",
            details={"result_repr": repr(result), **dict(details or {})},
        )
    status = result[0]
    if int(status) != 0:
        raise ServiceConfigurationError(
            f"{operation_name} 失败",
            details={
                "status_code": int(status),
                "status_name": getattr(status, "name", str(status)),
                **dict(details or {}),
            },
        )
    return tuple(result[1:])


def _release_cuda_resource(result: object) -> None:
    """释放 CUDA 资源时吞掉次级清理错误，避免覆盖主错误。"""

    if not isinstance(result, tuple) or not result:
        return
    status = result[0]
    if int(status) != 0:
        return


def _normalize_onnxruntime_outputs(*, outputs: Any, imports: Any) -> Any:
    """把 ONNXRuntime 输出转换为统一的预测数组。

    参数：
    - outputs：ONNXRuntime 原始输出列表。
    - imports：轻量推理依赖集合。

    返回：
    - Any：形状为 batch x boxes x channels 的 NumPy 数组。
    """

    if not isinstance(outputs, list) or not outputs:
        raise InvalidRequestError("onnxruntime 推理输出为空")
    return _ensure_prediction_array(
        prediction_value=outputs[0],
        np_module=imports.np,
        backend_name="onnxruntime",
    )


def _normalize_openvino_outputs(
    *,
    outputs: Any,
    output_port: Any,
    output_name: str,
    imports: Any,
) -> Any:
    """把 OpenVINO 输出转换为统一的预测数组。

    参数：
    - outputs：OpenVINO infer_new_request 返回的输出字典。
    - output_port：主输出端口对象。
    - output_name：主输出端口名称。
    - imports：轻量推理依赖集合。

    返回：
    - Any：形状为 batch x boxes x channels 的 NumPy 数组。
    """

    raw_output = None
    for output_key in (output_port, output_name):
        try:
            raw_output = outputs[output_key]
            break
        except Exception:
            continue
    if raw_output is None and hasattr(outputs, "values"):
        output_values = tuple(outputs.values())
        if output_values:
            raw_output = output_values[0]
    if raw_output is None:
        raise InvalidRequestError("openvino 推理输出为空")
    return _ensure_prediction_array(
        prediction_value=raw_output,
        np_module=imports.np,
        backend_name="openvino",
    )


def _normalize_tensorrt_outputs(*, output_array: Any, imports: _YoloXCudaInferenceImports) -> Any:
    """把 TensorRT 输出张量转换为统一的预测数组。"""

    return _ensure_prediction_array(
        prediction_value=_prediction_to_numpy_array(
            prediction_tensor=output_array,
            np_module=imports.np,
        ),
        np_module=imports.np,
        backend_name="tensorrt",
    )


def _ensure_prediction_array(*, prediction_value: Any, np_module: Any, backend_name: str) -> Any:
    """把后端原始输出规范化为预测数组。

    参数：
    - prediction_value：后端返回的原始主输出。
    - np_module：NumPy 模块。
    - backend_name：后端名称，用于错误消息。

    返回：
    - Any：形状为 batch x boxes x channels 的 NumPy 数组。
    """

    prediction_array = np_module.asarray(prediction_value, dtype=np_module.float32)
    if prediction_array.ndim == 2:
        prediction_array = np_module.expand_dims(prediction_array, axis=0)
    if prediction_array.ndim < 3:
        raise InvalidRequestError(
            f"{backend_name} 推理输出维度不合法",
            details={"shape": list(prediction_array.shape)},
        )
    return prediction_array


def _postprocess_prediction_array(
    *,
    prediction_array: Any,
    np_module: Any,
    num_classes: int,
    conf_thre: float,
    nms_thre: float,
) -> list[Any]:
    """使用 NumPy 版本 YOLOX 后处理把原始输出转换为候选检测框。

    参数：
    - prediction_array：后端原始输出数组。
    - np_module：NumPy 模块。
    - num_classes：类别数量。
    - conf_thre：置信度阈值。
    - nms_thre：NMS 阈值。

    返回：
    - list[Any]：每张图对应一组 shape 为 N x 7 的检测候选数组；无候选时为 None。
    """

    if int(prediction_array.shape[2]) < 5 + num_classes:
        raise InvalidRequestError(
            "推理输出通道数不足，无法执行 YOLOX 后处理",
            details={
                "channel_count": int(prediction_array.shape[2]),
                "required_channel_count": 5 + num_classes,
            },
        )
    working_prediction = np_module.asarray(prediction_array, dtype=np_module.float32).copy()
    working_prediction[:, :, 0] = prediction_array[:, :, 0] - prediction_array[:, :, 2] / 2
    working_prediction[:, :, 1] = prediction_array[:, :, 1] - prediction_array[:, :, 3] / 2
    working_prediction[:, :, 2] = prediction_array[:, :, 0] + prediction_array[:, :, 2] / 2
    working_prediction[:, :, 3] = prediction_array[:, :, 1] + prediction_array[:, :, 3] / 2

    output: list[Any] = [None for _ in range(len(working_prediction))]
    for index, image_prediction in enumerate(working_prediction):
        if int(image_prediction.shape[0]) <= 0:
            continue
        class_scores = image_prediction[:, 5 : 5 + num_classes]
        class_conf = np_module.max(class_scores, axis=1)
        class_pred = np_module.argmax(class_scores, axis=1).astype(np_module.float32, copy=False)
        combined_scores = image_prediction[:, 4] * class_conf
        conf_mask = combined_scores >= conf_thre
        detections = np_module.concatenate(
            (
                image_prediction[:, :5],
                class_conf[:, None],
                class_pred[:, None],
            ),
            axis=1,
        )
        detections = detections[conf_mask]
        combined_scores = combined_scores[conf_mask]
        if int(detections.shape[0]) <= 0:
            continue
        keep_indices = _batched_nms_indices(
            boxes=detections[:, :4],
            scores=combined_scores,
            class_ids=detections[:, 6].astype(np_module.int32, copy=False),
            nms_threshold=nms_thre,
            np_module=np_module,
        )
        if int(keep_indices.size) <= 0:
            continue
        output[index] = detections[keep_indices]
    return output


def _batched_nms_indices(
    *,
    boxes: Any,
    scores: Any,
    class_ids: Any,
    nms_threshold: float,
    np_module: Any,
) -> Any:
    """按类别执行 batched NMS 并返回保留索引。

    参数：
    - boxes：xyxy 边界框数组。
    - scores：候选框分数数组。
    - class_ids：候选框类别 id 数组。
    - nms_threshold：NMS 阈值。
    - np_module：NumPy 模块。

    返回：
    - Any：保留候选框的索引数组。
    """

    if int(boxes.shape[0]) <= 0:
        return np_module.asarray([], dtype=np_module.int64)

    keep_indices: list[int] = []
    for class_id in np_module.unique(class_ids):
        class_mask = class_ids == class_id
        candidate_indices = np_module.flatnonzero(class_mask)
        class_keep = _nms_indices(
            boxes=boxes[class_mask],
            scores=scores[class_mask],
            nms_threshold=nms_threshold,
            np_module=np_module,
        )
        keep_indices.extend(int(candidate_indices[index]) for index in class_keep.tolist())
    keep_indices.sort(key=lambda index: float(scores[index]), reverse=True)
    return np_module.asarray(keep_indices, dtype=np_module.int64)


def _nms_indices(*, boxes: Any, scores: Any, nms_threshold: float, np_module: Any) -> Any:
    """对单个类别的候选框执行标准 NMS。

    参数：
    - boxes：xyxy 边界框数组。
    - scores：候选框分数数组。
    - nms_threshold：NMS 阈值。
    - np_module：NumPy 模块。

    返回：
    - Any：当前类别保留的局部索引数组。
    """

    if int(boxes.shape[0]) <= 0:
        return np_module.asarray([], dtype=np_module.int64)
    order = np_module.argsort(scores)[::-1]
    keep_indices: list[int] = []
    while int(order.size) > 0:
        current_index = int(order[0])
        keep_indices.append(current_index)
        if int(order.size) == 1:
            break
        remaining_order = order[1:]
        iou_values = _compute_iou_array(
            box=boxes[current_index],
            boxes=boxes[remaining_order],
            np_module=np_module,
        )
        order = remaining_order[iou_values <= nms_threshold]
    return np_module.asarray(keep_indices, dtype=np_module.int64)


def _compute_iou_array(*, box: Any, boxes: Any, np_module: Any) -> Any:
    """计算单个边界框与一组边界框的 IoU。

    参数：
    - box：单个 xyxy 边界框。
    - boxes：待比较的多组 xyxy 边界框。
    - np_module：NumPy 模块。

    返回：
    - Any：逐框 IoU 数组。
    """

    x1 = np_module.maximum(box[0], boxes[:, 0])
    y1 = np_module.maximum(box[1], boxes[:, 1])
    x2 = np_module.minimum(box[2], boxes[:, 2])
    y2 = np_module.minimum(box[3], boxes[:, 3])
    intersection_width = np_module.maximum(0.0, x2 - x1)
    intersection_height = np_module.maximum(0.0, y2 - y1)
    intersection_area = intersection_width * intersection_height

    box_area = np_module.maximum(0.0, box[2] - box[0]) * np_module.maximum(0.0, box[3] - box[1])
    boxes_area = np_module.maximum(0.0, boxes[:, 2] - boxes[:, 0]) * np_module.maximum(
        0.0,
        boxes[:, 3] - boxes[:, 1],
    )
    union_area = np_module.maximum(box_area + boxes_area - intersection_area, 1e-12)
    return intersection_area / union_area


def _synchronize_device_for_timing(*, imports: Any, device_name: str) -> None:
    """在 CUDA 设备上执行同步，确保阶段耗时统计不会被异步 kernel 扰乱。

    参数：
    - imports：YOLOX 运行时依赖集合。
    - device_name：当前执行 device 名称。
    """

    if not device_name.startswith("cuda"):
        return
    torch_module = getattr(imports, "torch", None)
    if torch_module is None or not hasattr(torch_module, "cuda"):
        return
    try:
        torch_module.cuda.synchronize(device_name)
    except Exception:
        return


def _build_detection_records(
    *,
    np_module: Any,
    predictions: Any,
    resize_ratio: float,
    labels: tuple[str, ...],
    image_width: int,
    image_height: int,
) -> tuple[YoloXPredictionDetection, ...]:
    """把 YOLOX postprocess 输出归一成 detection 记录。"""

    if not isinstance(predictions, list) or not predictions:
        return ()
    prediction_tensor = predictions[0]
    if prediction_tensor is None:
        return ()

    prediction_array = _prediction_to_numpy_array(
        prediction_tensor=prediction_tensor,
        np_module=np_module,
    )
    detections: list[YoloXPredictionDetection] = []
    for prediction in prediction_array:
        if len(prediction) < 7:
            continue
        bbox = prediction[:4] / max(resize_ratio, 1e-8)
        x1 = float(max(0.0, min(float(bbox[0]), float(image_width))))
        y1 = float(max(0.0, min(float(bbox[1]), float(image_height))))
        x2 = float(max(0.0, min(float(bbox[2]), float(image_width))))
        y2 = float(max(0.0, min(float(bbox[3]), float(image_height))))
        class_id = int(prediction[6])
        class_name = labels[class_id] if 0 <= class_id < len(labels) else None
        score = float(prediction[4] * prediction[5])
        detections.append(
            YoloXPredictionDetection(
                bbox_xyxy=(round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)),
                score=round(score, 6),
                class_id=class_id,
                class_name=class_name,
            )
        )

    detections.sort(key=lambda item: item.score, reverse=True)
    return tuple(detections)


def _prediction_to_numpy_array(*, prediction_tensor: Any, np_module: Any) -> Any:
    """把 Tensor 或数组候选结果统一转换为 NumPy 数组。

    参数：
    - prediction_tensor：后处理后的单图候选结果。
    - np_module：NumPy 模块。

    返回：
    - Any：形状为 N x 7 的 NumPy 数组。
    """

    normalized_value = prediction_tensor
    if hasattr(normalized_value, "detach"):
        normalized_value = normalized_value.detach()
    if hasattr(normalized_value, "cpu"):
        normalized_value = normalized_value.cpu()
    if hasattr(normalized_value, "numpy"):
        normalized_value = normalized_value.numpy()
    return np_module.asarray(normalized_value, dtype=np_module.float32)


def _preprocess_image(
    *,
    cv2_module: Any,
    np_module: Any,
    image: Any,
    input_size: tuple[int, int],
) -> tuple[Any, float]:
    """按 YOLOX 预处理规则构造输入张量。"""

    target_height, target_width = input_size
    source_height, source_width = int(image.shape[0]), int(image.shape[1])
    resize_ratio = min(target_height / source_height, target_width / source_width)
    resized_width = max(1, int(round(source_width * resize_ratio)))
    resized_height = max(1, int(round(source_height * resize_ratio)))
    resized_image = cv2_module.resize(image, (resized_width, resized_height), interpolation=cv2_module.INTER_LINEAR)
    padded_image = np_module.full((target_height, target_width, 3), 114, dtype=np_module.uint8)
    padded_image[:resized_height, :resized_width] = resized_image
    tensor = padded_image[:, :, ::-1].transpose(2, 0, 1)
    return np_module.ascontiguousarray(tensor, dtype=np_module.float32), float(resize_ratio)


def _render_preview_image(
    *,
    cv2_module: Any,
    image: Any,
    detections: tuple[YoloXPredictionDetection, ...],
) -> bytes:
    """把 detection 结果叠加到原图并编码为 JPEG。"""

    preview = image.copy()
    for detection in detections:
        x1, y1, x2, y2 = (int(round(value)) for value in detection.bbox_xyxy)
        color = _select_detection_color(detection.class_id)
        cv2_module.rectangle(preview, (x1, y1), (x2, y2), color, 2)
        label_text = (
            f"{detection.class_name}:{detection.score:.2f}"
            if detection.class_name is not None
            else f"{detection.class_id}:{detection.score:.2f}"
        )
        text_origin_y = y1 - 6 if y1 > 18 else y1 + 18
        cv2_module.putText(
            preview,
            label_text,
            (x1, text_origin_y),
            cv2_module.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
            cv2_module.LINE_AA,
        )

    success, encoded = cv2_module.imencode(".jpg", preview)
    if success is not True:
        raise InvalidRequestError("预测预览图编码失败")
    return bytes(encoded.tobytes())


def _select_detection_color(class_id: int) -> tuple[int, int, int]:
    """根据类别 id 返回稳定的框颜色。"""

    palette = (
        (40, 110, 240),
        (40, 180, 120),
        (240, 170, 40),
        (210, 80, 80),
    )
    return palette[class_id % len(palette)]


def _resolve_execution_device_name(*, torch_module: Any, requested_device_name: str) -> str:
    """校验并返回本次预测实际使用的 device。"""

    if requested_device_name == "cpu":
        return "cpu"
    if requested_device_name == "cuda":
        requested_device_name = "cuda:0"
    if requested_device_name.startswith("cuda:"):
        if not torch_module.cuda.is_available():
            raise InvalidRequestError(
                "当前运行环境没有可用 GPU，不能使用 CUDA 预测",
                details={"device_name": requested_device_name},
            )
        raw_index = requested_device_name.split(":", 1)[1]
        if not raw_index.isdigit():
            raise InvalidRequestError(
                "device_name 必须是 cpu、cuda 或 cuda:<index>",
                details={"device_name": requested_device_name},
            )
        device_index = int(raw_index)
        available_count = int(torch_module.cuda.device_count())
        if device_index >= available_count:
            raise InvalidRequestError(
                "指定的 CUDA device 超出了本机可用 GPU 范围",
                details={
                    "device_name": requested_device_name,
                    "available_gpu_count": available_count,
                },
            )
        return requested_device_name
    raise InvalidRequestError(
        "device_name 必须是 cpu、cuda 或 cuda:<index>",
        details={"device_name": requested_device_name},
    )


def _enable_pytorch_cuda_inference_fast_path(*, torch_module: Any, device_name: str) -> None:
    """为固定尺寸 CUDA 推理打开 PyTorch 常用快路径。"""

    if not device_name.startswith("cuda"):
        return
    cudnn_backend = getattr(getattr(torch_module, "backends", None), "cudnn", None)
    if cudnn_backend is not None and hasattr(cudnn_backend, "benchmark"):
        cudnn_backend.benchmark = True


def _measure_elapsed_ms(started_at: float) -> float:
    """返回从 started_at 到当前时刻的毫秒耗时。"""

    return round((perf_counter() - started_at) * 1000, 3)


def _measure_cuda_event_elapsed_ms(
    *,
    cudart_module: Any,
    start_event: Any,
    end_event: Any,
    device_name: str,
) -> float | None:
    """返回两个 CUDA event 之间的纯 GPU 执行时间。"""

    try:
        elapsed_ms = _ensure_cuda_success(
            cudart_module.cudaEventElapsedTime(start_event, end_event),
            operation_name="TensorRT runtime 读取执行 event 耗时",
            details={"device_name": device_name},
        )[0]
    except Exception:
        return None
    return round(float(elapsed_ms), 3)


def _is_debugger_attached() -> bool:
    """返回当前 Python 进程是否挂着调试跟踪器。"""

    try:
        return sys.gettrace() is not None
    except Exception:
        return False


def _resolve_probability(*, value: object, field_name: str, default: float) -> float:
    """解析并校验概率型浮点值。"""

    resolved_value = float(value) if isinstance(value, int | float) else default
    if resolved_value < 0 or resolved_value > 1:
        raise InvalidRequestError(
            f"{field_name} 必须位于 0 到 1 之间",
            details={field_name: resolved_value},
        )
    return resolved_value
