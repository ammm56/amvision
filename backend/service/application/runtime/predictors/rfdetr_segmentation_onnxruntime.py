"""RF-DETR segmentation ONNX Runtime session。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.rfdetr_core.runtime import (
    build_rfdetr_runtime_postprocess_model,
    resolve_rfdetr_runtime_input_size,
    resolve_rfdetr_runtime_output_names,
)
from backend.service.application.runtime.predictors.rfdetr_io import (
    build_rfdetr_input_array,
    load_rfdetr_runtime_input_image,
)
from backend.service.application.runtime.predictors.rfdetr_segmentation_result import (
    build_rfdetr_segmentation_instances,
    postprocess_rfdetr_segmentation_outputs,
    render_rfdetr_segmentation_preview,
)
from backend.service.application.runtime.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.application.runtime.segmentation_runtime_contracts import (
    SegmentationPredictionExecutionResult,
    SegmentationPredictionRequest,
    SegmentationRuntimeSessionInfo,
    SegmentationRuntimeTensorSpec,
)
from backend.service.application.runtime.support.detection import (
    import_onnxruntime_module,
    resolve_onnxruntime_providers,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class OnnxRuntimeRfdetrSegmentationRuntimeSession:
    """ONNX Runtime RF-DETR segmentation 会话。"""

    model_type = "rfdetr"
    model_label = "RF-DETR"
    task_type = "segmentation"

    def __init__(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        imports: Any,
        session: Any,
        input_name: str,
        output_names: tuple[str, ...],
        postprocess_model: Any,
        input_size: tuple[int, int],
    ) -> None:
        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.session = session
        self.input_name = input_name
        self.output_names = output_names
        self.postprocess_model = postprocess_model
        self.input_size = input_size
        self.device_name = runtime_target.device_name or "cpu"
        self.runtime_precision = runtime_target.runtime_precision or "fp32"

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
    ) -> "OnnxRuntimeRfdetrSegmentationRuntimeSession":
        if runtime_target.runtime_backend != "onnxruntime":
            raise InvalidRequestError(
                "RF-DETR segmentation predictor 仅支持 onnxruntime",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(
                "RF-DETR segmentation predictor 收到了错误的 task_type",
                details={"task_type": runtime_target.task_type},
            )
        if (runtime_target.runtime_precision or "fp32") != "fp32":
            raise InvalidRequestError(
                "当前 RF-DETR segmentation onnxruntime session 仅支持 fp32",
                details={"runtime_precision": runtime_target.runtime_precision},
            )
        import cv2
        import numpy as np
        import torch

        onnxruntime_module = import_onnxruntime_module()
        providers = resolve_onnxruntime_providers(
            onnxruntime_module=onnxruntime_module,
            requested_device_name=runtime_target.device_name,
        )
        session = onnxruntime_module.InferenceSession(
            str(runtime_target.runtime_artifact_path),
            providers=providers,
        )
        imports = type(
            "_RfdetrSegmentationOnnxImports",
            (),
            {"cv2": cv2, "np": np, "torch": torch},
        )()
        return cls(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            imports=imports,
            session=session,
            input_name=session.get_inputs()[0].name,
            output_names=resolve_rfdetr_runtime_output_names(
                task_type=runtime_target.task_type,
                output_names=tuple(item.name for item in session.get_outputs()),
            ),
            postprocess_model=build_rfdetr_runtime_postprocess_model(
                task_type=runtime_target.task_type,
            ),
            input_size=resolve_rfdetr_runtime_input_size(
                task_type=runtime_target.task_type,
                model_scale=runtime_target.model_scale,
                input_size=runtime_target.input_size,
            ),
        )

    def predict(self, request: SegmentationPredictionRequest) -> SegmentationPredictionExecutionResult:
        imports = self.imports
        image, decode_ms = load_rfdetr_runtime_input_image(
            cv2_module=imports.cv2,
            np_module=imports.np,
            dataset_storage=self.dataset_storage,
            request=request,
        )
        input_array, preprocess_ms = build_rfdetr_input_array(
            cv2_module=imports.cv2,
            np_module=imports.np,
            image=image,
            input_size=self.input_size,
        )

        infer_started_at = perf_counter()
        raw_outputs = self.session.run(
            list(self.output_names),
            {self.input_name: input_array},
        )
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        processed, postprocess_ms = postprocess_rfdetr_segmentation_outputs(
            torch_module=imports.torch,
            postprocess_model=self.postprocess_model,
            raw_outputs={
                "pred_logits": raw_outputs[0],
                "pred_boxes": raw_outputs[1],
                "pred_masks": raw_outputs[2],
            },
            image_height=int(image.shape[0]),
            image_width=int(image.shape[1]),
        )
        instances = build_rfdetr_segmentation_instances(
            cv2_module=imports.cv2,
            scores=processed["scores"],
            labels=processed["labels"],
            boxes_xyxy=processed["boxes_xyxy"],
            masks=processed["masks"],
            label_names=self.runtime_target.labels,
            score_threshold=request.score_threshold,
            mask_threshold=request.mask_threshold,
        )
        preview_image_bytes = render_rfdetr_segmentation_preview(
            cv2_module=imports.cv2,
            image=image,
            instances=instances,
            save_result_image=request.save_result_image,
        )
        return SegmentationPredictionExecutionResult(
            instances=instances,
            latency_ms=round(decode_ms + preprocess_ms + infer_ms + postprocess_ms, 3),
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=SegmentationRuntimeSessionInfo(
                backend_name="onnxruntime",
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=SegmentationRuntimeTensorSpec(
                    name=self.input_name,
                    shape=(1, 3, self.input_size[0], self.input_size[1]),
                    dtype="float32",
                ),
                output_specs=tuple(
                    SegmentationRuntimeTensorSpec(
                        name=name,
                        shape=tuple(int(item) for item in array.shape),
                        dtype="float32",
                    )
                    for name, array in zip(self.output_names, raw_outputs, strict=False)
                ),
                metadata={
                    "model_type": "rfdetr",
                    "model_scale": self.runtime_target.model_scale,
                    "runtime_execution_mode": describe_runtime_execution_mode(
                        runtime_backend="onnxruntime",
                        runtime_precision="fp32",
                        device_name=self.device_name,
                    ),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                    "provider_names": list(self.session.get_providers()),
                    "output_names": list(self.output_names),
                },
            ),
        )
