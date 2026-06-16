"""RF-DETR detection PyTorch runtime session。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.rfdetr_core.detection import build_rfdetr_model
from backend.service.application.models.rfdetr_core.runtime import resolve_rfdetr_runtime_input_size
from backend.service.application.runtime.detection_runtime_contracts import (
    DetectionPredictionExecutionResult,
    DetectionPredictionRequest,
    DetectionRuntimeTensorSpec,
)
from backend.service.application.runtime.predictors.rfdetr_detection_result import (
    build_rfdetr_detection_result,
    build_rfdetr_detections,
    postprocess_rfdetr_detection_outputs,
)
from backend.service.application.runtime.predictors.rfdetr_io import (
    build_rfdetr_input_array,
    load_rfdetr_runtime_input_image,
)
from backend.service.application.runtime.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.application.runtime.support.detection import resolve_execution_device_name
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class PyTorchRfdetrRuntimeSession:
    """已经加载完成并可重复推理的 PyTorch RF-DETR 会话。"""

    model_type = "rfdetr"
    model_label = "RF-DETR"
    task_type = "detection"

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
    ) -> "PyTorchRfdetrRuntimeSession":
        if runtime_target.runtime_backend != "pytorch":
            raise InvalidRequestError(
                "RF-DETR predictor 仅支持 pytorch",
                details={"runtime_backend": runtime_target.runtime_backend},
            )

        import cv2
        import numpy as np
        import torch

        imports = type(
            "_RfdetrPredictorImports",
            (),
            {"cv2": cv2, "np": np, "torch": torch},
        )()
        model = build_rfdetr_model(
            model_scale=runtime_target.model_scale,
            num_classes=len(runtime_target.labels),
            pretrained_path=(
                str(runtime_target.runtime_artifact_path)
                if runtime_target.runtime_artifact_path
                else None
            ),
        )
        device_name = resolve_execution_device_name(
            torch_module=torch,
            requested_device_name=runtime_target.device_name or "cpu",
        )
        model.to(device_name)
        model.eval()
        return cls(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            imports=imports,
            model=model,
            device_name=device_name,
            runtime_precision=runtime_target.runtime_precision or "fp32",
            input_size=resolve_rfdetr_runtime_input_size(
                task_type=runtime_target.task_type,
                model_scale=runtime_target.model_scale,
                input_size=runtime_target.input_size,
            ),
        )

    def predict(self, request: DetectionPredictionRequest) -> DetectionPredictionExecutionResult:
        return _predict_pytorch(self, request)


def _predict_pytorch(
    session_obj: PyTorchRfdetrRuntimeSession,
    request: DetectionPredictionRequest,
) -> DetectionPredictionExecutionResult:
    imports = session_obj.imports
    image, decode_ms = load_rfdetr_runtime_input_image(
        cv2_module=imports.cv2,
        np_module=imports.np,
        dataset_storage=session_obj.dataset_storage,
        request=request,
    )
    input_array, preprocess_ms = build_rfdetr_input_array(
        cv2_module=imports.cv2,
        np_module=imports.np,
        image=image,
        input_size=session_obj.input_size,
    )
    input_tensor = imports.torch.from_numpy(input_array).to(session_obj.device_name)
    input_tensor = input_tensor.float()
    if (
        session_obj.runtime_precision == "fp16"
        and session_obj.device_name.startswith("cuda")
    ):
        input_tensor = input_tensor.half()

    infer_started_at = perf_counter()
    with imports.torch.no_grad():
        raw_outputs = session_obj.model(input_tensor)
    infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

    processed, postprocess_ms = postprocess_rfdetr_detection_outputs(
        torch_module=imports.torch,
        postprocess_model=session_obj.model,
        raw_outputs=raw_outputs,
        image_height=int(image.shape[0]),
        image_width=int(image.shape[1]),
    )
    detections = build_rfdetr_detections(
        processed=processed,
        labels=session_obj.runtime_target.labels,
        score_threshold=request.score_threshold,
    )
    return build_rfdetr_detection_result(
        session_obj=session_obj,
        image=image,
        detections=detections,
        request=request,
        decode_ms=decode_ms,
        preprocess_ms=preprocess_ms,
        infer_ms=infer_ms,
        postprocess_ms=postprocess_ms,
        input_name="images",
        output_specs=(
            DetectionRuntimeTensorSpec(
                name="pred_logits",
                shape=tuple(int(item) for item in raw_outputs["pred_logits"].shape),
                dtype="float16" if session_obj.runtime_precision == "fp16" else "float32",
            ),
            DetectionRuntimeTensorSpec(
                name="pred_boxes",
                shape=tuple(int(item) for item in raw_outputs["pred_boxes"].shape),
                dtype="float16" if session_obj.runtime_precision == "fp16" else "float32",
            ),
        ),
        metadata={
            "model_type": "rfdetr",
            "model_scale": session_obj.runtime_target.model_scale,
            "runtime_execution_mode": describe_runtime_execution_mode(
                runtime_backend="pytorch",
                runtime_precision=session_obj.runtime_precision,
                device_name=session_obj.device_name,
            ),
        },
    )
