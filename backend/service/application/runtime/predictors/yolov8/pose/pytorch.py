"""YOLOv8 pose PyTorch runtime session。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolov8_core import (
    build_yolov8_model,
    load_yolov8_checkpoint_file,
)
from backend.service.application.runtime.predictors.yolov8.pose.backend import (
    enable_yolov8_pose_cuda_fast_path,
    normalize_yolov8_pose_outputs_for_backend,
    require_yolov8_pose_pytorch_imports,
    resolve_yolov8_pose_torch_device_name,
)
from backend.service.application.runtime.predictors.yolov8.pose.contracts import (
    YoloV8PosePredictionExecutionResult,
    YoloV8PosePredictionRequest,
    YoloV8PoseRuntimeSessionInfo,
    YoloV8PoseRuntimeTensorSpec,
)
from backend.service.application.runtime.predictors.yolov8.pose.io import (
    load_yolov8_pose_prediction_image,
    preprocess_yolov8_pose_image,
)
from backend.service.application.runtime.predictors.yolov8.pose.postprocess import (
    build_yolov8_pose_runtime_instances,
    infer_yolov8_pose_keypoint_shape,
)
from backend.service.application.runtime.predictors.yolov8.pose.preview import (
    render_yolov8_pose_preview_image_if_requested,
)
from backend.service.application.runtime.predictors.yolov8.pose.timing import (
    measure_yolov8_pose_stage_elapsed_ms,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class PyTorchYoloV8PoseRuntimeSession:
    """已经加载完成并可重复推理的 PyTorch YOLOv8 pose 会话。"""

    model_type = "yolov8"
    model_label = "YOLOv8"
    task_type = "pose"

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
        """初始化 PyTorch YOLOv8 pose 会话。"""

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
    ) -> "PyTorchYoloV8PoseRuntimeSession":
        """加载一套 PyTorch YOLOv8 pose 会话。"""

        if runtime_target.runtime_backend != "pytorch":
            raise InvalidRequestError(
                "当前 YOLOv8 pose predictor 仅支持 pytorch runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(
                "当前 YOLOv8 pose predictor 收到了错误的 task_type",
                details={"task_type": runtime_target.task_type},
            )

        imports = require_yolov8_pose_pytorch_imports()
        model = build_yolov8_model(
            task_type=cls.task_type,
            model_scale=runtime_target.model_scale,
            num_classes=len(runtime_target.labels),
            model_config_overrides={
                "kpt_shape": infer_yolov8_pose_keypoint_shape(runtime_target),
            },
        )
        load_yolov8_checkpoint_file(
            torch_module=imports.torch,
            model=model,
            checkpoint_path=runtime_target.runtime_artifact_path,
        )
        device_name = resolve_yolov8_pose_torch_device_name(
            torch_module=imports.torch,
            requested_device_name=runtime_target.device_name,
        )
        enable_yolov8_pose_cuda_fast_path(torch_module=imports.torch, device_name=device_name)
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

    def predict(self, request: YoloV8PosePredictionRequest) -> YoloV8PosePredictionExecutionResult:
        """执行一次 PyTorch YOLOv8 pose 预测。"""

        decode_started_at = perf_counter()
        image = load_yolov8_pose_prediction_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = measure_yolov8_pose_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=decode_started_at,
        )

        preprocess_started_at = perf_counter()
        input_tensor, letterbox_transform = preprocess_yolov8_pose_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            image=image,
        )
        input_tensor = self.imports.torch.from_numpy(input_tensor).unsqueeze(0).to(self.device_name)
        input_tensor = input_tensor.float()
        if self.runtime_precision == "fp16":
            input_tensor = input_tensor.half()
        preprocess_ms = measure_yolov8_pose_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=preprocess_started_at,
        )

        infer_started_at = perf_counter()
        inference_mode = getattr(self.imports.torch, "inference_mode", None)
        if callable(inference_mode):
            with inference_mode():
                outputs = self.model(input_tensor)
        else:
            with self.imports.torch.no_grad():
                outputs = self.model(input_tensor)
        infer_ms = measure_yolov8_pose_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=infer_started_at,
        )

        prediction_array = normalize_yolov8_pose_outputs_for_backend(
            outputs=outputs,
            np_module=self.imports.np,
        )
        postprocess_started_at = perf_counter()
        instances, kpt_shape = build_yolov8_pose_runtime_instances(
            np_module=self.imports.np,
            prediction_array=prediction_array,
            labels=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            keypoint_confidence_threshold=request.keypoint_confidence_threshold,
            letterbox_transform=letterbox_transform,
            default_kpt_shape=infer_yolov8_pose_keypoint_shape(self.runtime_target),
        )
        postprocess_ms = measure_yolov8_pose_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=postprocess_started_at,
        )
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms
        preview_image_bytes = render_yolov8_pose_preview_image_if_requested(
            cv2_module=self.imports.cv2,
            image=image,
            instances=instances,
            save_result_image=request.save_result_image,
        )
        output_dtype = "float16" if self.runtime_precision == "fp16" else "float32"
        return YoloV8PosePredictionExecutionResult(
            instances=instances,
            latency_ms=round(latency_ms, 3),
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=YoloV8PoseRuntimeSessionInfo(
                backend_name=self.runtime_target.runtime_backend,
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=YoloV8PoseRuntimeTensorSpec(
                    name="images",
                    shape=(1, 3, self.runtime_target.input_size[0], self.runtime_target.input_size[1]),
                    dtype=output_dtype,
                ),
                output_specs=(
                    YoloV8PoseRuntimeTensorSpec(
                        name="predictions",
                        shape=tuple(int(item) for item in prediction_array.shape),
                        dtype=output_dtype,
                    ),
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
                    "keypoint_confidence_threshold": request.keypoint_confidence_threshold,
                    "class_count": len(self.runtime_target.labels),
                    "kpt_shape": list(kpt_shape),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                },
            ),
        )


__all__ = ["PyTorchYoloV8PoseRuntimeSession"]
