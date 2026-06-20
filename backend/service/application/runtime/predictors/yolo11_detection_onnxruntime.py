"""YOLO11 detection ONNXRuntime runtime session。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.detection_postprocess import (
    DETECTION_POSTPROCESS_MODE_NMS,
)
from backend.service.application.models.yolo11_core.postprocess import (
    build_yolo11_detection_records,
)
from backend.service.application.runtime.contracts.detection import (
    DetectionPredictionExecutionResult,
    DetectionPredictionRequest,
    DetectionRuntimeSessionInfo,
    DetectionRuntimeTensorSpec,
)
from backend.service.application.runtime.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.application.runtime.support.detection import (
    DEFAULT_DETECTION_NMS_THRESHOLD,
    import_onnxruntime_module,
    load_prediction_image,
    normalize_onnxruntime_outputs,
    preprocess_image,
    render_preview_image,
    require_inference_imports,
    resolve_onnxruntime_providers,
    resolve_probability,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


class OnnxRuntimeYolo11RuntimeSession:
    """已经加载完成并可重复推理的 ONNXRuntime YOLO11 detection 会话。"""

    model_type = "yolo11"
    model_label = "YOLO11"

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
        """初始化 ONNXRuntime YOLO11 detection 会话。"""

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
    ) -> "OnnxRuntimeYolo11RuntimeSession":
        """加载一套 ONNXRuntime YOLO11 detection 会话。"""

        if runtime_target.runtime_backend != "onnxruntime":
            raise InvalidRequestError(
                "当前 YOLO11 detection predictor 仅支持 onnxruntime runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.model_type != "yolo11":
            raise InvalidRequestError(
                "YOLO11 detection predictor 只支持 yolo11 model_type",
                details={"model_type": runtime_target.model_type},
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

    def predict(
        self, request: DetectionPredictionRequest
    ) -> DetectionPredictionExecutionResult:
        """执行一次 ONNXRuntime YOLO11 detection 预测。"""

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
        outputs = self.session.run(
            [self.output_name],
            {self.input_name: input_tensor},
        )
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        image_height = int(image.shape[0])
        image_width = int(image.shape[1])

        postprocess_started_at = perf_counter()
        prediction_array = normalize_onnxruntime_outputs(
            outputs=outputs, imports=self.imports
        )
        detections = build_yolo11_detection_records(
            np_module=self.imports.np,
            prediction_array=prediction_array,
            labels=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            nms_threshold=nms_threshold,
            resize_ratio=resize_ratio,
            image_width=image_width,
            image_height=image_height,
        )
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = None
        if request.save_result_image:
            preview_image_bytes = render_preview_image(
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
                    shape=(
                        1,
                        3,
                        self.runtime_target.input_size[0],
                        self.runtime_target.input_size[1],
                    ),
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
                    "nms_threshold": nms_threshold,
                    "postprocess_mode": DETECTION_POSTPROCESS_MODE_NMS,
                    "max_detections": None,
                    "class_count": len(self.runtime_target.labels),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                    "provider_names": list(self.session.get_providers()),
                },
            ),
        )


__all__ = ["OnnxRuntimeYolo11RuntimeSession"]
