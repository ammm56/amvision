"""YOLOX ONNXRuntime runtime session。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolox_core.postprocess import (
    build_yolox_detection_records,
    postprocess_yolox_prediction_array,
)
from backend.service.application.runtime.predictors.yolox.backend import (
    import_yolox_onnxruntime_module,
    normalize_yolox_onnxruntime_outputs,
    require_yolox_inference_imports,
    resolve_yolox_onnxruntime_providers,
)
from backend.service.application.runtime.predictors.yolox.contracts import (
    DEFAULT_YOLOX_NMS_THRESHOLD,
    RuntimeTensorSpec,
    YoloXPredictionDetection,
    YoloXPredictionExecutionResult,
    YoloXPredictionRequest,
    YoloXRuntimeSessionInfo,
    resolve_yolox_probability,
)
from backend.service.application.runtime.predictors.yolox.io import (
    load_yolox_prediction_image,
    preprocess_yolox_image,
)
from backend.service.application.runtime.predictors.yolox.preview import (
    render_yolox_preview_image_if_requested,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


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

        imports = require_yolox_inference_imports()
        onnxruntime_module = import_yolox_onnxruntime_module()
        providers = resolve_yolox_onnxruntime_providers(
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
        image = load_yolox_prediction_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = round((perf_counter() - decode_started_at) * 1000, 3)

        preprocess_started_at = perf_counter()
        input_tensor, resize_ratio = preprocess_yolox_image(
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

        nms_threshold = resolve_yolox_probability(
            value=request.extra_options.get("nms_threshold"),
            field_name="nms_threshold",
            default=DEFAULT_YOLOX_NMS_THRESHOLD,
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
        predictions = postprocess_yolox_prediction_array(
            prediction_array=normalize_yolox_onnxruntime_outputs(outputs=outputs, imports=self.imports),
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
