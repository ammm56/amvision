"""RF-DETR segmentation PyTorch runtime session。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.rfdetr_core.runtime import resolve_rfdetr_runtime_input_size
from backend.service.application.models.rfdetr_core.segmentation import build_rfdetr_segmentation_model
from backend.service.application.runtime.predictors.rfdetr.io import (
    build_rfdetr_input_array,
    load_rfdetr_runtime_input_image,
)
from backend.service.application.runtime.predictors.rfdetr.segmentation.result import (
    build_rfdetr_segmentation_instances,
    postprocess_rfdetr_segmentation_outputs,
    render_rfdetr_segmentation_preview,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.application.runtime.contracts.segmentation import (
    SegmentationPredictionExecutionResult,
    SegmentationPredictionRequest,
    SegmentationRuntimeSessionInfo,
    SegmentationRuntimeTensorSpec,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class PyTorchRfdetrSegmentationRuntimeSession:
    """PyTorch RF-DETR segmentation 会话。"""

    model_type = "rfdetr"
    model_label = "RF-DETR"
    task_type = "segmentation"

    def __init__(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        imports: Any,
        model: Any,
        device_name: str,
        runtime_precision: str,
        input_size: tuple[int, int],
    ) -> None:
        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.model = model
        self.device_name = device_name
        self.runtime_precision = runtime_precision
        self.input_size = input_size

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
    ) -> "PyTorchRfdetrSegmentationRuntimeSession":
        if runtime_target.runtime_backend != "pytorch":
            raise InvalidRequestError(
                "RF-DETR segmentation 当前仅支持 pytorch",
                details={"runtime_backend": runtime_target.runtime_backend},
            )
        if runtime_target.task_type != cls.task_type:
            raise InvalidRequestError(
                "RF-DETR segmentation predictor 收到了错误的 task_type",
                details={"task_type": runtime_target.task_type},
            )
        import cv2
        import numpy as np
        import torch

        imports = type(
            "_RfdetrSegmentationPredictorImports",
            (),
            {"cv2": cv2, "np": np, "torch": torch},
        )()
        input_size = resolve_rfdetr_runtime_input_size(
            task_type=runtime_target.task_type,
            model_scale=runtime_target.model_scale,
            input_size=runtime_target.input_size,
        )
        model = build_rfdetr_segmentation_model(
            model_scale=runtime_target.model_scale,
            num_classes=len(runtime_target.labels),
            pretrained_path=str(runtime_target.runtime_artifact_path)
            if runtime_target.runtime_artifact_path
            else None,
        )
        device_name = runtime_target.device_name or "cpu"
        if device_name == "cuda" and torch.cuda.is_available():
            device_name = "cuda:0"
        model.to(device_name)
        if runtime_target.runtime_precision == "fp16" and device_name.startswith("cuda"):
            model.half()
        model.eval()
        return cls(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            imports=imports,
            model=model,
            device_name=device_name,
            runtime_precision=runtime_target.runtime_precision or "fp32",
            input_size=input_size,
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
        input_tensor = imports.torch.from_numpy(input_array).to(self.device_name).float()
        if self.runtime_precision == "fp16" and self.device_name.startswith("cuda"):
            input_tensor = input_tensor.half()

        infer_started_at = perf_counter()
        inference_mode = getattr(imports.torch, "inference_mode", None)
        if callable(inference_mode):
            with inference_mode():
                outputs = self.model(input_tensor)
        else:
            with imports.torch.no_grad():
                outputs = self.model(input_tensor)
        infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

        processed, postprocess_ms = postprocess_rfdetr_segmentation_outputs(
            torch_module=imports.torch,
            postprocess_model=self.model,
            raw_outputs=outputs,
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
                backend_name=self.runtime_target.runtime_backend,
                model_uri=self.runtime_target.runtime_artifact_storage_uri,
                device_name=self.device_name,
                input_spec=SegmentationRuntimeTensorSpec(
                    name="images",
                    shape=(1, 3, self.input_size[0], self.input_size[1]),
                    dtype="float16" if self.runtime_precision == "fp16" else "float32",
                ),
                output_specs=(
                    SegmentationRuntimeTensorSpec(
                        name="pred_logits",
                        shape=tuple(int(item) for item in outputs["pred_logits"].shape),
                        dtype="float16" if self.runtime_precision == "fp16" else "float32",
                    ),
                    SegmentationRuntimeTensorSpec(
                        name="pred_boxes",
                        shape=tuple(int(item) for item in outputs["pred_boxes"].shape),
                        dtype="float16" if self.runtime_precision == "fp16" else "float32",
                    ),
                    SegmentationRuntimeTensorSpec(
                        name="pred_masks",
                        shape=tuple(int(item) for item in outputs["pred_masks"].shape),
                        dtype="float16" if self.runtime_precision == "fp16" else "float32",
                    ),
                ),
                metadata={
                    "model_type": "rfdetr",
                    "model_scale": self.runtime_target.model_scale,
                    "runtime_execution_mode": describe_runtime_execution_mode(
                        runtime_backend=self.runtime_target.runtime_backend,
                        runtime_precision=self.runtime_precision,
                        device_name=self.device_name,
                    ),
                    "decode_ms": decode_ms,
                    "preprocess_ms": preprocess_ms,
                    "infer_ms": infer_ms,
                    "postprocess_ms": postprocess_ms,
                },
            ),
        )
