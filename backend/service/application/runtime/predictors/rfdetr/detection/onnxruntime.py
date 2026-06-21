"""RF-DETR detection ONNX Runtime session。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.rfdetr_core.runtime import (
    build_rfdetr_runtime_postprocess_model,
    resolve_rfdetr_runtime_input_size,
    resolve_rfdetr_runtime_output_names,
)
from backend.service.application.runtime.contracts.detection import (
    DetectionPredictionExecutionResult,
    DetectionPredictionRequest,
    DetectionRuntimeTensorSpec,
)
from backend.service.application.runtime.predictors.rfdetr.detection.result import (
    build_rfdetr_detection_result,
    build_rfdetr_detections,
    postprocess_rfdetr_detection_outputs,
)
from backend.service.application.runtime.predictors.rfdetr.io import (
    build_rfdetr_input_array,
    load_rfdetr_runtime_input_image,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
    describe_runtime_execution_mode,
)
from backend.service.application.runtime.support.detection import (
    import_onnxruntime_module,
    resolve_onnxruntime_providers,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class OnnxRuntimeRfdetrRuntimeSession:
    """已经加载完成并可重复推理的 ONNX Runtime RF-DETR 会话。"""

    model_type = "rfdetr"
    model_label = "RF-DETR"
    task_type = "detection"

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
        postprocess_model: Any,
        input_size: tuple[int, int],
    ) -> None:
        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.session = session
        self.device_name = device_name
        self.input_name = input_name
        self.output_names = output_names
        self.postprocess_model = postprocess_model
        self.input_size = input_size

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
    ) -> "OnnxRuntimeRfdetrRuntimeSession":
        if runtime_target.runtime_backend != "onnxruntime":
            raise InvalidRequestError(
                "RF-DETR predictor 仅支持 onnxruntime",
                details={"runtime_backend": runtime_target.runtime_backend},
            )

        import cv2
        import numpy as np
        import torch

        imports = type(
            "_RfdetrOnnxPredictorImports",
            (),
            {"cv2": cv2, "np": np, "torch": torch},
        )()
        onnxruntime_module = import_onnxruntime_module()
        providers = resolve_onnxruntime_providers(
            onnxruntime_module=onnxruntime_module,
            requested_device_name=runtime_target.device_name,
        )
        session = onnxruntime_module.InferenceSession(
            str(runtime_target.runtime_artifact_path),
            providers=providers,
        )
        output_names = resolve_rfdetr_runtime_output_names(
            task_type=runtime_target.task_type,
            output_names=tuple(item.name for item in session.get_outputs()),
        )
        return cls(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            imports=imports,
            session=session,
            device_name=runtime_target.device_name or "cpu",
            input_name=session.get_inputs()[0].name,
            output_names=output_names,
            postprocess_model=build_rfdetr_runtime_postprocess_model(
                task_type=runtime_target.task_type,
            ),
            input_size=resolve_rfdetr_runtime_input_size(
                task_type=runtime_target.task_type,
                model_scale=runtime_target.model_scale,
                input_size=runtime_target.input_size,
            ),
        )

    def predict(self, request: DetectionPredictionRequest) -> DetectionPredictionExecutionResult:
        return _predict_onnx(self, request)


def _predict_onnx(
    session_obj: OnnxRuntimeRfdetrRuntimeSession,
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

    infer_started_at = perf_counter()
    raw_outputs = session_obj.session.run(
        list(session_obj.output_names),
        {session_obj.input_name: input_array},
    )
    infer_ms = round((perf_counter() - infer_started_at) * 1000, 3)

    processed, postprocess_ms = postprocess_rfdetr_detection_outputs(
        torch_module=imports.torch,
        postprocess_model=session_obj.postprocess_model,
        raw_outputs={
            "pred_logits": raw_outputs[0],
            "pred_boxes": raw_outputs[1],
        },
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
        input_name=session_obj.input_name,
        output_specs=tuple(
            DetectionRuntimeTensorSpec(
                name=output_name,
                shape=tuple(int(item) for item in output_array.shape),
                dtype="float32",
            )
            for output_name, output_array in zip(
                session_obj.output_names,
                raw_outputs,
                strict=True,
            )
        ),
        metadata={
            "model_type": "rfdetr",
            "model_scale": session_obj.runtime_target.model_scale,
            "runtime_execution_mode": describe_runtime_execution_mode(
                runtime_backend="onnxruntime",
                runtime_precision="fp32",
                device_name=session_obj.device_name,
            ),
            "provider_names": list(session_obj.session.get_providers()),
            "output_names": list(session_obj.output_names),
        },
    )
