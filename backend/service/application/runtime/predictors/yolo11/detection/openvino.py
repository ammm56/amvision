"""YOLO11 detection OpenVINO runtime session。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentRuntimeConfiguration,
)
from backend.service.application.runtime.support.openvino_execution import (
    compile_openvino_model,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.postprocess.detection_postprocess import (
    DETECTION_POSTPROCESS_MODE_NMS,
)
from backend.service.application.models.yolo11_core.postprocess import (
    build_yolo11_detection_records,
)
from backend.service.application.runtime.contracts.detection.prediction import (
    DetectionPredictionExecutionResult,
    DetectionPredictionRequest,
    DetectionRuntimeSessionInfo,
    DetectionRuntimeTensorSpec,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.application.runtime.support.detection import (
    DEFAULT_DETECTION_NMS_THRESHOLD,
    build_openvino_compile_properties,
    import_openvino_module,
    load_prediction_image,
    normalize_openvino_outputs,
    preprocess_image,
    render_preview_image,
    require_inference_imports,
    resolve_openvino_compiled_runtime_precision,
    resolve_openvino_device_name,
    resolve_openvino_port_dtype,
    resolve_openvino_port_name,
    resolve_probability,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


class OpenVINOYolo11RuntimeSession:
    """已经加载完成并可重复推理的 OpenVINO YOLO11 detection 会话。"""

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
        input_port: Any,
        output_port: Any,
        compiled_device_name: str,
        compiled_runtime_precision: str,
    ) -> None:
        """初始化 OpenVINO YOLO11 detection 会话。"""

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
        runtime_configuration: DeploymentRuntimeConfiguration,
    ) -> "OpenVINOYolo11RuntimeSession":
        """加载一套 OpenVINO YOLO11 detection 会话。"""

        if runtime_target.runtime_backend != "openvino":
            raise InvalidRequestError(
                "当前 YOLO11 detection predictor 仅支持 openvino runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.model_type != "yolo11":
            raise InvalidRequestError(
                "YOLO11 detection predictor 只支持 yolo11 model_type",
                details={"model_type": runtime_target.model_type},
            )

        imports = require_inference_imports()
        openvino_module = import_openvino_module()
        compiled_device_name = resolve_openvino_device_name(
            requested_device_name=runtime_target.device_name,
        )
        compile_properties = build_openvino_compile_properties(
            openvino_module=openvino_module,
            runtime_precision=runtime_target.runtime_precision,
            requested_device_name=runtime_target.device_name,
        )
        session = compile_openvino_model(
            openvino_module=openvino_module,
            model_path=str(runtime_target.runtime_artifact_path),
            device_name=compiled_device_name,
            base_properties=compile_properties,
            runtime_configuration=runtime_configuration,
        )
        input_port = session.input(0)
        output_port = session.output(0)
        return cls(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            imports=imports,
            session=session,
            device_name=runtime_target.device_name,
            input_name=resolve_openvino_port_name(input_port, fallback="images"),
            output_name=resolve_openvino_port_name(output_port, fallback="predictions"),
            input_port=input_port,
            output_port=output_port,
            compiled_device_name=compiled_device_name,
            compiled_runtime_precision=resolve_openvino_compiled_runtime_precision(
                session=session,
                fallback_precision=runtime_target.runtime_precision,
            ),
        )

    def predict(
        self, request: DetectionPredictionRequest
    ) -> DetectionPredictionExecutionResult:
        """执行一次 OpenVINO YOLO11 detection 预测。"""

        decode_started_at = perf_counter()
        image = load_prediction_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = round((perf_counter() - decode_started_at) * 1000, 3)

        preprocess_started_at = perf_counter()
        input_tensor, letterbox_transform = preprocess_image(
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
        outputs = self.session.infer_new_request({self.input_port: input_tensor})
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        image_height = int(image.shape[0])
        image_width = int(image.shape[1])

        postprocess_started_at = perf_counter()
        prediction_array = normalize_openvino_outputs(
            outputs=outputs,
            output_port=self.output_port,
            output_name=self.output_name,
            imports=self.imports,
        )
        detections = build_yolo11_detection_records(
            np_module=self.imports.np,
            prediction_array=prediction_array,
            labels=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            nms_threshold=nms_threshold,
            letterbox_transform=letterbox_transform,
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
                    dtype=resolve_openvino_port_dtype(
                        self.input_port, fallback="float32"
                    ),
                ),
                output_spec=DetectionRuntimeTensorSpec(
                    name=self.output_name,
                    shape=(-1, 4 + len(self.runtime_target.labels)),
                    dtype=resolve_openvino_port_dtype(
                        self.output_port, fallback="float32"
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
                    "nms_threshold": nms_threshold,
                    "postprocess_mode": DETECTION_POSTPROCESS_MODE_NMS,
                    "max_detections": None,
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


__all__ = ["OpenVINOYolo11RuntimeSession"]
