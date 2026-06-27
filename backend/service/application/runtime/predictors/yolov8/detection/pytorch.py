"""YOLOv8 detection PyTorch runtime session。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.postprocess.detection_postprocess import (
    DETECTION_POSTPROCESS_MODE_NMS,
)
from backend.service.application.models.yolov8_core import (
    build_yolov8_model,
    load_yolov8_checkpoint_file,
)
from backend.service.application.models.yolov8_core.postprocess import (
    build_yolov8_detection_records,
)
from backend.service.application.runtime.predictors.yolov8.detection.backend import (
    enable_yolov8_detection_cuda_fast_path,
    require_yolov8_detection_pytorch_imports,
    resolve_yolov8_detection_torch_device_name,
    yolov8_detection_prediction_to_numpy_array,
)
from backend.service.application.runtime.predictors.yolov8.detection.contracts import (
    DEFAULT_YOLOV8_DETECTION_NMS_THRESHOLD,
    YoloV8DetectionPredictionExecutionResult,
    YoloV8DetectionPredictionRequest,
    YoloV8DetectionRuntimeSessionInfo,
    YoloV8DetectionRuntimeTensorSpec,
    resolve_yolov8_detection_probability,
)
from backend.service.application.runtime.predictors.yolov8.detection.io import (
    load_yolov8_detection_prediction_image,
    preprocess_yolov8_detection_image,
)
from backend.service.application.runtime.predictors.yolov8.detection.preview import (
    render_yolov8_detection_preview_image_if_requested,
)
from backend.service.application.runtime.predictors.yolov8.detection.timing import (
    measure_yolov8_detection_stage_elapsed_ms,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class PyTorchYoloV8RuntimeSession:
    """已经加载完成并可重复推理的 PyTorch YOLOv8 detection 会话。"""

    model_type = "yolov8"
    model_label = "YOLOv8"

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
        """初始化 PyTorch YOLOv8 detection 会话。"""

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
    ) -> "PyTorchYoloV8RuntimeSession":
        """加载一套 PyTorch YOLOv8 detection 会话。"""

        if runtime_target.runtime_backend != "pytorch":
            raise InvalidRequestError(
                "当前 YOLOv8 detection predictor 仅支持 pytorch runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
            )

        imports = require_yolov8_detection_pytorch_imports()
        model = build_yolov8_model(
            task_type="detection",
            model_scale=runtime_target.model_scale,
            num_classes=len(runtime_target.labels),
        )
        load_yolov8_checkpoint_file(
            torch_module=imports.torch,
            model=model,
            checkpoint_path=runtime_target.runtime_artifact_path,
        )
        device_name = resolve_yolov8_detection_torch_device_name(
            torch_module=imports.torch,
            requested_device_name=runtime_target.device_name,
        )
        enable_yolov8_detection_cuda_fast_path(
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

    def predict(
        self,
        request: YoloV8DetectionPredictionRequest,
    ) -> YoloV8DetectionPredictionExecutionResult:
        """执行一次 PyTorch YOLOv8 detection 预测。"""

        decode_started_at = perf_counter()
        image = load_yolov8_detection_prediction_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = measure_yolov8_detection_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=decode_started_at,
        )

        preprocess_started_at = perf_counter()
        input_tensor, letterbox_transform = preprocess_yolov8_detection_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            image=image,
            input_size=self.runtime_target.input_size,
        )
        input_tensor = self.imports.torch.from_numpy(input_tensor).unsqueeze(0).to(self.device_name)
        input_tensor = input_tensor.float()
        if self.runtime_precision == "fp16":
            input_tensor = input_tensor.half()
        preprocess_ms = measure_yolov8_detection_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=preprocess_started_at,
        )

        nms_threshold = resolve_yolov8_detection_probability(
            value=request.extra_options.get("nms_threshold"),
            field_name="nms_threshold",
            default=DEFAULT_YOLOV8_DETECTION_NMS_THRESHOLD,
        )

        infer_started_at = perf_counter()
        inference_mode = getattr(self.imports.torch, "inference_mode", None)
        if callable(inference_mode):
            with inference_mode():
                outputs = self.model(input_tensor)
        else:
            with self.imports.torch.no_grad():
                outputs = self.model(input_tensor)
        infer_ms = measure_yolov8_detection_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=infer_started_at,
        )

        image_height = int(image.shape[0])
        image_width = int(image.shape[1])

        postprocess_started_at = perf_counter()
        prediction_array = yolov8_detection_prediction_to_numpy_array(
            prediction_tensor=outputs,
            np_module=self.imports.np,
        )
        detections = build_yolov8_detection_records(
            np_module=self.imports.np,
            prediction_array=prediction_array,
            labels=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            nms_threshold=nms_threshold,
            letterbox_transform=letterbox_transform,
        )
        postprocess_ms = measure_yolov8_detection_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=postprocess_started_at,
        )
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = render_yolov8_detection_preview_image_if_requested(
            cv2_module=self.imports.cv2,
            image=image,
            detections=detections,
            save_result_image=request.save_result_image,
        )

        return YoloV8DetectionPredictionExecutionResult(
            detections=detections,
            latency_ms=round(latency_ms, 3),
            image_width=image_width,
            image_height=image_height,
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=YoloV8DetectionRuntimeSessionInfo(
                backend_name=self.runtime_target.runtime_backend,
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=YoloV8DetectionRuntimeTensorSpec(
                    name="images",
                    shape=(1, 3, self.runtime_target.input_size[0], self.runtime_target.input_size[1]),
                    dtype="float16" if self.runtime_precision == "fp16" else "float32",
                ),
                output_spec=YoloV8DetectionRuntimeTensorSpec(
                    name="predictions",
                    shape=(-1, 4 + len(self.runtime_target.labels)),
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
                    "postprocess_mode": DETECTION_POSTPROCESS_MODE_NMS,
                    "max_detections": None,
                    "class_count": len(self.runtime_target.labels),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                },
            ),
        )


__all__ = ["PyTorchYoloV8RuntimeSession"]
