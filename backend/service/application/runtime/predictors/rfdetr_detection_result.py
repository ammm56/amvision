"""RF-DETR detection runtime 结果组装。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.models.rfdetr_core.runtime import (
    postprocess_rfdetr_runtime_outputs,
)
from backend.service.application.runtime.detection_runtime_contracts import (
    DetectionPredictionDetection,
    DetectionPredictionExecutionResult,
    DetectionPredictionRequest,
    DetectionRuntimeSessionInfo,
    DetectionRuntimeTensorSpec,
)
from backend.service.application.runtime.support.detection import render_preview_image


def postprocess_rfdetr_detection_outputs(
    *,
    torch_module: Any,
    postprocess_model: Any,
    raw_outputs: dict[str, Any],
    image_height: int,
    image_width: int,
) -> tuple[dict[str, Any], float]:
    """执行 RF-DETR detection 后处理，并返回耗时。"""

    postprocess_started_at = perf_counter()
    processed = postprocess_rfdetr_runtime_outputs(
        torch_module=torch_module,
        postprocess_model=postprocess_model,
        raw_outputs=raw_outputs,
        image_height=image_height,
        image_width=image_width,
    )
    postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
    return processed, postprocess_ms


def build_rfdetr_detections(
    *,
    processed: dict[str, Any],
    labels: tuple[str, ...],
    score_threshold: float,
) -> tuple[DetectionPredictionDetection, ...]:
    """把 RF-DETR core 后处理输出整理成 detection runtime 统一结果。"""

    scores = processed.get("scores")
    class_ids = processed.get("labels")
    boxes_xyxy = processed.get("boxes_xyxy")
    if scores is None or class_ids is None or boxes_xyxy is None:
        return ()
    detections: list[DetectionPredictionDetection] = []
    for index in range(int(scores.shape[1])):
        score = float(scores[0, index])
        if score < score_threshold:
            continue
        class_id = int(class_ids[0, index])
        if class_id < 0 or class_id >= len(labels):
            continue
        detections.append(
            DetectionPredictionDetection(
                bbox_xyxy=(
                    round(float(boxes_xyxy[0, index, 0]), 4),
                    round(float(boxes_xyxy[0, index, 1]), 4),
                    round(float(boxes_xyxy[0, index, 2]), 4),
                    round(float(boxes_xyxy[0, index, 3]), 4),
                ),
                score=round(score, 6),
                class_id=class_id,
                class_name=labels[class_id],
            )
        )
    return tuple(detections)


def build_rfdetr_detection_result(
    *,
    session_obj: Any,
    image: Any,
    detections: tuple[DetectionPredictionDetection, ...],
    request: DetectionPredictionRequest,
    decode_ms: float,
    preprocess_ms: float,
    infer_ms: float,
    postprocess_ms: float,
    input_name: str,
    output_specs: tuple[DetectionRuntimeTensorSpec, ...],
    metadata: dict[str, object],
) -> DetectionPredictionExecutionResult:
    """组装 detection runtime 统一响应和可选预览图。"""

    preview_image_bytes = None
    if request.save_result_image and detections:
        preview_image_bytes = render_preview_image(
            cv2_module=session_obj.imports.cv2,
            image=image,
            detections=detections,
        )
    input_height, input_width = session_obj.input_size
    return DetectionPredictionExecutionResult(
        detections=detections,
        latency_ms=round(decode_ms + preprocess_ms + infer_ms + postprocess_ms, 3),
        image_width=int(image.shape[1]),
        image_height=int(image.shape[0]),
        preview_image_bytes=preview_image_bytes,
        runtime_session_info=DetectionRuntimeSessionInfo(
            backend_name=session_obj.runtime_target.runtime_backend,
            model_uri=session_obj.runtime_target.runtime_artifact_storage_uri,
            device_name=session_obj.device_name,
            input_spec=DetectionRuntimeTensorSpec(
                name=input_name,
                shape=(1, 3, input_height, input_width),
                dtype=getattr(session_obj, "input_dtype_name", "float32"),
            ),
            output_spec=output_specs[0],
            metadata={
                **metadata,
                "output_specs": [
                    {
                        "name": output_spec.name,
                        "shape": list(output_spec.shape),
                        "dtype": output_spec.dtype,
                    }
                    for output_spec in output_specs
                ],
                "decode_ms": decode_ms,
                "preprocess_ms": preprocess_ms,
                "infer_ms": infer_ms,
                "postprocess_ms": postprocess_ms,
            },
        ),
    )
