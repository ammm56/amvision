"""YOLOv8 pose ONNXRuntime runtime session。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.predictors.yolov8.pose.backend import (
    import_yolov8_pose_onnxruntime_module,
    normalize_yolov8_pose_outputs_for_backend,
    require_yolov8_pose_inference_imports,
    resolve_yolov8_pose_onnxruntime_providers,
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
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class OnnxRuntimeYoloV8PoseRuntimeSession:
    """已经加载完成并可重复推理的 ONNXRuntime YOLOv8 pose 会话。"""

    model_type = "yolov8"
    model_label = "YOLOv8"
    task_type = "pose"

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
    ) -> None:
        """初始化 ONNXRuntime YOLOv8 pose 会话。"""

        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.session = session
        self.device_name = device_name
        self.input_name = input_name
        self.output_names = output_names

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
    ) -> "OnnxRuntimeYoloV8PoseRuntimeSession":
        """加载一套 ONNXRuntime YOLOv8 pose 会话。"""

        if runtime_target.runtime_backend != "onnxruntime":
            raise InvalidRequestError(
                "当前 YOLOv8 pose predictor 仅支持 onnxruntime runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(
                "当前 YOLOv8 pose predictor 收到了错误的 task_type",
                details={"task_type": runtime_target.task_type},
            )
        if runtime_target.runtime_precision != "fp32":
            raise InvalidRequestError(
                "当前 YOLOv8 pose onnxruntime session 仅支持 fp32 precision",
                details={"runtime_precision": runtime_target.runtime_precision},
            )
        imports = require_yolov8_pose_inference_imports()
        onnxruntime_module = import_yolov8_pose_onnxruntime_module()
        providers = resolve_yolov8_pose_onnxruntime_providers(
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
            output_names=tuple(item.name for item in session.get_outputs()),
        )

    def predict(self, request: YoloV8PosePredictionRequest) -> YoloV8PosePredictionExecutionResult:
        """执行一次 ONNXRuntime YOLOv8 pose 预测。"""

        decode_started_at = perf_counter()
        image = load_yolov8_pose_prediction_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = round((perf_counter() - decode_started_at) * 1000, 3)
        preprocess_started_at = perf_counter()
        input_tensor, letterbox_transform = preprocess_yolov8_pose_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            image=image,
        )
        input_tensor = self.imports.np.expand_dims(input_tensor, axis=0).astype(
            self.imports.np.float32,
            copy=False,
        )
        preprocess_ms = round((perf_counter() - preprocess_started_at) * 1000, 3)
        infer_started_at = perf_counter()
        outputs = self.session.run(list(self.output_names), {self.input_name: input_tensor})
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)
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
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms
        preview_image_bytes = render_yolov8_pose_preview_image_if_requested(
            cv2_module=self.imports.cv2,
            image=image,
            instances=instances,
            save_result_image=request.save_result_image,
        )
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
                    name=self.input_name,
                    shape=(1, 3, self.runtime_target.input_size[0], self.runtime_target.input_size[1]),
                    dtype="float32",
                ),
                output_specs=(
                    YoloV8PoseRuntimeTensorSpec(
                        name=self.output_names[0] if self.output_names else "predictions",
                        shape=tuple(int(item) for item in prediction_array.shape),
                        dtype="float32",
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
                    "keypoint_confidence_threshold": request.keypoint_confidence_threshold,
                    "class_count": len(self.runtime_target.labels),
                    "kpt_shape": list(kpt_shape),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                    "provider_names": list(self.session.get_providers()),
                    "output_names": list(self.output_names),
                },
            ),
        )


__all__ = ["OnnxRuntimeYoloV8PoseRuntimeSession"]
