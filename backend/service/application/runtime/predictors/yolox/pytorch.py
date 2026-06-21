"""YOLOX PyTorch runtime session。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolox_core.dependencies import (
    require_yolox_core_dependencies,
)
from backend.service.application.models.yolox_core.models import build_yolox_detection_model
from backend.service.application.models.yolox_core.postprocess import (
    build_yolox_detection_records,
)
from backend.service.application.models.yolox_core.utils import (
    enable_yolox_cuda_inference_fast_path,
    resolve_yolox_torch_device_name,
)
from backend.service.application.models.yolox_core.weights import load_yolox_warm_start_checkpoint
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
from backend.service.application.runtime.predictors.yolox.timing import (
    measure_yolox_stage_elapsed_ms,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


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

        imports = require_yolox_core_dependencies()
        model = build_yolox_detection_model(
            torch_module=imports.torch,
            model_scale=runtime_target.model_scale,
            num_classes=len(runtime_target.labels),
        )
        load_yolox_warm_start_checkpoint(
            torch_module=imports.torch,
            model=model,
            checkpoint_path=runtime_target.runtime_artifact_path,
            source_summary={
                "source_model_version_id": runtime_target.model_version_id,
                "runtime_artifact_file_id": runtime_target.runtime_artifact_file_id,
                "runtime_artifact_file_type": runtime_target.runtime_artifact_file_type,
                "source_model_build_id": runtime_target.model_build_id,
            },
        )
        device_name = resolve_yolox_torch_device_name(
            torch_module=imports.torch,
            requested_device_name=runtime_target.device_name,
        )
        enable_yolox_cuda_inference_fast_path(
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
        image = load_yolox_prediction_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = measure_yolox_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=decode_started_at,
        )

        preprocess_started_at = perf_counter()
        input_tensor, resize_ratio = preprocess_yolox_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            image=image,
            input_size=self.runtime_target.input_size,
        )
        input_tensor = self.imports.torch.from_numpy(input_tensor).unsqueeze(0).to(self.device_name)
        input_tensor = input_tensor.float()
        if self.runtime_precision == "fp16":
            input_tensor = input_tensor.half()
        preprocess_ms = measure_yolox_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=preprocess_started_at,
        )

        nms_threshold = resolve_yolox_probability(
            value=request.extra_options.get("nms_threshold"),
            field_name="nms_threshold",
            default=DEFAULT_YOLOX_NMS_THRESHOLD,
        )

        infer_started_at = perf_counter()
        inference_mode = getattr(self.imports.torch, "inference_mode", None)
        if callable(inference_mode):
            with inference_mode():
                outputs = self.model(input_tensor)
        else:
            with self.imports.torch.no_grad():
                outputs = self.model(input_tensor)
        infer_ms = measure_yolox_stage_elapsed_ms(
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
        detections = build_yolox_detection_records(
            np_module=self.imports.np,
            predictions=predictions,
            resize_ratio=resize_ratio,
            labels=self.runtime_target.labels,
            image_width=image_width,
            image_height=image_height,
            detection_factory=YoloXPredictionDetection,
        )
        postprocess_ms = measure_yolox_stage_elapsed_ms(
            imports=self.imports,
            device_name=self.device_name,
            started_at=postprocess_started_at,
        )
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
