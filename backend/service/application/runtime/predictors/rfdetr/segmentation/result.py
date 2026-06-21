"""RF-DETR segmentation runtime 结果组装。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.models.rfdetr_core.runtime import (
    build_rfdetr_single_channel_mask_array,
    postprocess_rfdetr_segmentation_runtime_outputs,
)
from backend.service.application.runtime.contracts.segmentation.prediction import (
    SegmentationPredictionInstance,
)
from backend.service.application.runtime.support.detection import render_preview_image


def postprocess_rfdetr_segmentation_outputs(
    *,
    torch_module: Any,
    postprocess_model: Any,
    raw_outputs: dict[str, Any],
    image_height: int,
    image_width: int,
) -> tuple[dict[str, Any], float]:
    """执行 RF-DETR segmentation 后处理，并返回耗时。"""

    postprocess_started_at = perf_counter()
    processed = postprocess_rfdetr_segmentation_runtime_outputs(
        torch_module=torch_module,
        postprocess_model=postprocess_model,
        raw_outputs=raw_outputs,
        image_height=image_height,
        image_width=image_width,
    )
    postprocess_ms = round((perf_counter() - postprocess_started_at) * 1000, 3)
    return processed, postprocess_ms


def render_rfdetr_segmentation_preview(
    *,
    cv2_module: Any,
    image: Any,
    instances: tuple[SegmentationPredictionInstance, ...],
    save_result_image: bool,
) -> bytes | None:
    """按请求生成 RF-DETR segmentation 调试预览图。"""

    if save_result_image is not True or not instances:
        return None
    return render_preview_image(
        cv2_module=cv2_module,
        image=image,
        detections=tuple(_as_preview_detection(item) for item in instances),
    )


def build_rfdetr_segmentation_instances(
    *,
    cv2_module: Any,
    scores: Any,
    labels: Any,
    boxes_xyxy: Any,
    masks: Any,
    label_names: tuple[str, ...],
    score_threshold: float,
    mask_threshold: float,
) -> tuple[SegmentationPredictionInstance, ...]:
    """把 RF-DETR segmentation 后处理输出整理成 segmentation runtime 结果。"""

    result: list[SegmentationPredictionInstance] = []
    if scores is None or labels is None or boxes_xyxy is None or masks is None:
        return ()
    for index in range(int(scores.shape[1])):
        score = float(scores[0, index].item())
        if score < score_threshold:
            continue
        class_id = int(labels[0, index].item())
        if class_id < 0 or class_id >= len(label_names):
            continue
        box = boxes_xyxy[0, index]
        binary_mask = build_rfdetr_single_channel_mask_array(
            mask_tensor=masks[0, index],
            mask_threshold=mask_threshold,
        )
        contours, _ = cv2_module.findContours(
            binary_mask,
            cv2_module.RETR_EXTERNAL,
            cv2_module.CHAIN_APPROX_SIMPLE,
        )
        segments = []
        for contour in contours:
            if contour.shape[0] < 3:
                continue
            polygon = tuple(
                (round(float(point[0][0]), 4), round(float(point[0][1]), 4))
                for point in contour
            )
            if len(polygon) >= 3:
                segments.append(polygon)
        result.append(
            SegmentationPredictionInstance(
                bbox_xyxy=(
                    round(float(box[0].item()), 4),
                    round(float(box[1].item()), 4),
                    round(float(box[2].item()), 4),
                    round(float(box[3].item()), 4),
                ),
                score=round(score, 6),
                class_id=class_id,
                class_name=label_names[class_id],
                segments=tuple(segments),
                mask_area=float(binary_mask.sum()),
            )
        )
    return tuple(result)


def _as_preview_detection(instance: SegmentationPredictionInstance) -> dict[str, object]:
    """把 segmentation instance 转成通用预览绘制所需的 detection 结构。"""

    return {
        "bbox_xyxy": list(instance.bbox_xyxy),
        "score": instance.score,
        "class_id": instance.class_id,
        "class_name": instance.class_name,
    }
