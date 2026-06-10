"""YOLOE 文本提示检测节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.yoloe_open_vocab_nodes.backend.nodes._common import (
    build_regions_payload,
    build_text_prompt_summary_payload,
    get_or_create_yoloe_text_prompt_runtime_session,
    normalize_confidence_threshold,
    normalize_device,
    normalize_iou_threshold,
    normalize_max_detections,
    normalize_model_series,
    normalize_model_scale,
    normalize_precision,
    read_image_bytes,
    read_text_prompt_items,
)


NODE_TYPE_ID = "custom.yoloe.text-prompt-detect"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行 YOLOE 文本提示检测节点。"""

    image_payload, image_bytes = read_image_bytes(request, input_name="image")
    prompt_items = read_text_prompt_items(request.input_values.get("prompts"))
    model_series = normalize_model_series(request.parameters.get("model_series"))
    model_scale = normalize_model_scale(request.parameters.get("model_scale"))
    confidence_threshold = normalize_confidence_threshold(request.parameters.get("confidence_threshold"))
    iou_threshold = normalize_iou_threshold(request.parameters.get("iou_threshold"))
    max_detections = normalize_max_detections(request.parameters.get("max_detections"))
    device = normalize_device(request.parameters.get("device"))
    precision = normalize_precision(request.parameters.get("precision"))

    runtime_session = get_or_create_yoloe_text_prompt_runtime_session(
        model_series=model_series,
        model_scale=model_scale,
        device=device,
        precision=precision,
    )
    prediction = runtime_session.predict(
        image_bytes=image_bytes,
        prompts=prompt_items,
        confidence_threshold=confidence_threshold,
        iou_threshold=iou_threshold,
        max_detections=max_detections,
    )
    return {
        "detections": {
            "items": [dict(item) for item in prediction.detections],
            "count": len(prediction.detections),
        },
        "regions": build_regions_payload(
            request,
            prediction=prediction,
            image_payload=image_payload,
        ),
        "summary": build_text_prompt_summary_payload(
            prediction=prediction,
            prompts=prompt_items,
            image_payload=image_payload,
        ),
    }
