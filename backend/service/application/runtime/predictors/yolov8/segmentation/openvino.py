"""YOLOv8 segmentation OpenVINO runtime session。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentRuntimeConfiguration,
)
from backend.service.application.runtime.support.openvino_execution import (
    compile_openvino_model,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.runtime.predictors.yolov8.segmentation.backend import (
    build_yolov8_segmentation_openvino_compile_properties,
    import_yolov8_segmentation_openvino_module,
    normalize_yolov8_segmentation_outputs_for_backend,
    require_yolov8_segmentation_inference_imports,
    resolve_yolov8_segmentation_openvino_compiled_runtime_precision,
    resolve_yolov8_segmentation_openvino_device_name,
    resolve_yolov8_segmentation_openvino_port_dtype,
    resolve_yolov8_segmentation_openvino_port_name,
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
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


class OpenVINOYoloV8SegmentationRuntimeSession:
    """已经加载完成并可重复推理的 OpenVINO YOLOv8 segmentation 会话。"""

    model_type = "yolov8"
    model_label = "YOLOv8"
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
        output_names: tuple[str, str],
        input_port: Any,
        prediction_port: Any,
        proto_port: Any,
        compiled_device_name: str,
        compiled_runtime_precision: str,
    ) -> None:
        """初始化 OpenVINO YOLOv8 segmentation 会话。"""

        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.session = session
        self.device_name = device_name
        self.input_name = input_name
        self.output_names = output_names
        self.input_port = input_port
        self.prediction_port = prediction_port
        self.proto_port = proto_port
        self.compiled_device_name = compiled_device_name
        self.compiled_runtime_precision = compiled_runtime_precision

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        runtime_configuration: DeploymentRuntimeConfiguration,
    ) -> "OpenVINOYoloV8SegmentationRuntimeSession":
        """加载一套 OpenVINO YOLOv8 segmentation 会话。"""

        if runtime_target.runtime_backend != "openvino":
            raise InvalidRequestError(
                "当前 YOLOv8 segmentation predictor 仅支持 openvino runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(
                "当前 YOLOv8 segmentation predictor 收到了错误的 task_type",
                details={"task_type": runtime_target.task_type},
            )

        imports = require_yolov8_segmentation_inference_imports()
        openvino_module = import_yolov8_segmentation_openvino_module()
        compiled_device_name = resolve_yolov8_segmentation_openvino_device_name(
            requested_device_name=runtime_target.device_name,
        )
        compile_properties = build_yolov8_segmentation_openvino_compile_properties(
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
        prediction_port = session.output(0)
        proto_port = session.output(1)
        prediction_name = resolve_yolov8_segmentation_openvino_port_name(
            prediction_port,
            fallback="predictions",
        )
        proto_name = resolve_yolov8_segmentation_openvino_port_name(
            proto_port,
            fallback="proto",
        )
        return cls(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            imports=imports,
            session=session,
            device_name=runtime_target.device_name,
            input_name=resolve_yolov8_segmentation_openvino_port_name(
                input_port, fallback="images"
            ),
            output_names=(prediction_name, proto_name),
            input_port=input_port,
            prediction_port=prediction_port,
            proto_port=proto_port,
            compiled_device_name=compiled_device_name,
            compiled_runtime_precision=resolve_yolov8_segmentation_openvino_compiled_runtime_precision(
                session=session,
                fallback_precision=runtime_target.runtime_precision,
            ),
        )

    def predict(
        self,
        request: YoloV8SegmentationPredictionRequest,
    ) -> YoloV8SegmentationPredictionExecutionResult:
        """执行一次 OpenVINO YOLOv8 segmentation 预测。"""

        decode_started_at = perf_counter()
        image = load_yolov8_segmentation_prediction_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = round((perf_counter() - decode_started_at) * 1000, 3)

        preprocess_started_at = perf_counter()
        input_tensor, letterbox_transform = preprocess_yolov8_segmentation_image(
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

        infer_started_at = perf_counter()
        outputs = self.session.infer_new_request({self.input_port: input_tensor})
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        postprocess_started_at = perf_counter()
        prediction_array, proto_array = (
            normalize_yolov8_segmentation_outputs_for_backend(
                outputs=self._resolve_openvino_outputs(outputs),
                np_module=self.imports.np,
            )
        )
        instances = build_yolov8_segmentation_runtime_instances(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            prediction_array=prediction_array,
            proto_array=proto_array,
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
                    shape=(
                        1,
                        3,
                        self.runtime_target.input_size[0],
                        self.runtime_target.input_size[1],
                    ),
                    dtype=resolve_yolov8_segmentation_openvino_port_dtype(
                        self.input_port,
                        fallback="float32",
                    ),
                ),
                output_specs=(
                    YoloV8SegmentationRuntimeTensorSpec(
                        name=self.output_names[0],
                        shape=tuple(int(item) for item in prediction_array.shape),
                        dtype=resolve_yolov8_segmentation_openvino_port_dtype(
                            self.prediction_port,
                            fallback="float32",
                        ),
                    ),
                    YoloV8SegmentationRuntimeTensorSpec(
                        name=self.output_names[1],
                        shape=tuple(int(item) for item in proto_array.shape),
                        dtype=resolve_yolov8_segmentation_openvino_port_dtype(
                            self.proto_port,
                            fallback="float32",
                        ),
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
                    "compiled_device_name": self.compiled_device_name,
                    "compiled_runtime_precision": self.compiled_runtime_precision,
                },
            ),
        )

    def _resolve_openvino_outputs(self, outputs: Any) -> tuple[Any, Any]:
        """从 OpenVINO 输出字典中取出 prediction 和 proto。"""

        prediction_array = outputs.get(self.prediction_port)
        if prediction_array is None:
            prediction_array = outputs.get(self.output_names[0])
        proto_array = outputs.get(self.proto_port)
        if proto_array is None:
            proto_array = outputs.get(self.output_names[1])
        if prediction_array is None or proto_array is None:
            raise ServiceConfigurationError(
                "OpenVINO segmentation session 缺少 prediction 或 proto 输出",
                details={"output_names": list(self.output_names)},
            )
        return prediction_array, proto_array


__all__ = ["OpenVINOYoloV8SegmentationRuntimeSession"]
