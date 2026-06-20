"""YOLO26 segmentation ONNXRuntime runtime session。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.predictors.yolo26_segmentation_backend import (
    import_yolo26_segmentation_onnxruntime_module,
    normalize_yolo26_segmentation_outputs_for_backend,
    require_yolo26_segmentation_inference_imports,
    resolve_yolo26_segmentation_onnxruntime_providers,
)
from backend.service.application.runtime.predictors.yolo26_segmentation_contracts import (
    Yolo26SegmentationPredictionExecutionResult,
    Yolo26SegmentationPredictionRequest,
    Yolo26SegmentationRuntimeSessionInfo,
    Yolo26SegmentationRuntimeTensorSpec,
)
from backend.service.application.runtime.predictors.yolo26_segmentation_io import (
    load_yolo26_segmentation_prediction_image,
    preprocess_yolo26_segmentation_image,
)
from backend.service.application.runtime.predictors.yolo26_segmentation_postprocess import (
    build_yolo26_segmentation_runtime_instances,
)
from backend.service.application.runtime.predictors.yolo26_segmentation_preview import (
    render_yolo26_segmentation_preview_image_if_requested,
)
from backend.service.application.runtime.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


class OnnxRuntimeYolo26SegmentationRuntimeSession:
    """已经加载完成并可重复推理的 ONNXRuntime YOLO26 segmentation 会话。"""

    model_type = "yolo26"
    model_label = "YOLO26"
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
    ) -> None:
        """初始化 ONNXRuntime YOLO26 segmentation 会话。"""

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
    ) -> "OnnxRuntimeYolo26SegmentationRuntimeSession":
        """加载一套 ONNXRuntime YOLO26 segmentation 会话。"""

        if runtime_target.runtime_backend != "onnxruntime":
            raise InvalidRequestError(
                "当前 YOLO26 segmentation predictor 仅支持 onnxruntime runtime_backend",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(
                "当前 YOLO26 segmentation predictor 收到了错误的 task_type",
                details={"task_type": runtime_target.task_type},
            )
        if runtime_target.runtime_precision != "fp32":
            raise InvalidRequestError(
                "当前 YOLO26 segmentation onnxruntime session 仅支持 fp32 precision",
                details={"runtime_precision": runtime_target.runtime_precision},
            )

        imports = require_yolo26_segmentation_inference_imports()
        onnxruntime_module = import_yolo26_segmentation_onnxruntime_module()
        providers = resolve_yolo26_segmentation_onnxruntime_providers(
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

    def predict(
        self,
        request: Yolo26SegmentationPredictionRequest,
    ) -> Yolo26SegmentationPredictionExecutionResult:
        """执行一次 ONNXRuntime YOLO26 segmentation 预测。"""

        decode_started_at = perf_counter()
        image = load_yolo26_segmentation_prediction_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        decode_ms = round((perf_counter() - decode_started_at) * 1000, 3)

        preprocess_started_at = perf_counter()
        input_tensor, resize_ratio = preprocess_yolo26_segmentation_image(
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
        outputs = self.session.run(
            list(self.output_names),
            {self.input_name: input_tensor},
        )
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        image_height = int(image.shape[0])
        image_width = int(image.shape[1])

        postprocess_started_at = perf_counter()
        prediction_array, proto_array = (
            normalize_yolo26_segmentation_outputs_for_backend(
                outputs=outputs,
                np_module=self.imports.np,
            )
        )
        instances = build_yolo26_segmentation_runtime_instances(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            prediction_array=prediction_array,
            proto_array=proto_array,
            labels=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            mask_threshold=request.mask_threshold,
            resize_ratio=resize_ratio,
            image_width=image_width,
            image_height=image_height,
            input_size=self.runtime_target.input_size,
        )
        postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
        latency_ms = decode_ms + preprocess_ms + infer_ms + postprocess_ms

        preview_image_bytes = render_yolo26_segmentation_preview_image_if_requested(
            cv2_module=self.imports.cv2,
            image=image,
            instances=instances,
            save_result_image=request.save_result_image,
        )

        return Yolo26SegmentationPredictionExecutionResult(
            instances=instances,
            latency_ms=round(latency_ms, 3),
            image_width=image_width,
            image_height=image_height,
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=Yolo26SegmentationRuntimeSessionInfo(
                backend_name=self.runtime_target.runtime_backend,
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=Yolo26SegmentationRuntimeTensorSpec(
                    name=self.input_name,
                    shape=(
                        1,
                        3,
                        self.runtime_target.input_size[0],
                        self.runtime_target.input_size[1],
                    ),
                    dtype="float32",
                ),
                output_specs=tuple(
                    Yolo26SegmentationRuntimeTensorSpec(
                        name=self.output_names[index]
                        if index < len(self.output_names)
                        else f"output-{index}",
                        shape=tuple(int(item) for item in array.shape),
                        dtype="float32",
                    )
                    for index, array in enumerate((prediction_array, proto_array))
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
                    "provider_names": list(self.session.get_providers()),
                    "output_names": list(self.output_names),
                },
            ),
        )


__all__ = ["OnnxRuntimeYolo26SegmentationRuntimeSession"]
