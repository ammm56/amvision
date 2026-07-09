"""YOLOE prompt-free 检测节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.yoloe_open_vocab_nodes.backend.payloads.inputs import read_image_bytes
from custom_nodes.yoloe_open_vocab_nodes.backend.payloads.pretrained import (
    normalize_confidence_threshold,
    normalize_device,
    normalize_iou_threshold,
    normalize_max_detections,
    normalize_model_scale,
    normalize_model_series,
    normalize_precision,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.payloads.results import (
    build_regions_payload,
    build_prompt_free_summary_payload,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.runtime.access import (
    get_or_create_yoloe_prompt_free_runtime_session,
)


NODE_TYPE_ID = "custom.yoloe.prompt-free-detect"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行 YOLOE prompt-free 检测节点。"""

    image_payload, image_bytes = read_image_bytes(request, input_name="image")
    model_series = normalize_model_series(request.parameters.get("model_series"))
    model_scale = normalize_model_scale(request.parameters.get("model_scale"))
    confidence_threshold = normalize_confidence_threshold(request.parameters.get("confidence_threshold"))
    iou_threshold = normalize_iou_threshold(request.parameters.get("iou_threshold"))
    max_detections = normalize_max_detections(request.parameters.get("max_detections"))
    device = normalize_device(request.parameters.get("device"))
    precision = normalize_precision(request.parameters.get("precision"))

    runtime_session = get_or_create_yoloe_prompt_free_runtime_session(
        model_series=model_series,
        model_scale=model_scale,
        device=device,
        precision=precision,
    )
    prediction = runtime_session.predict(
        image_bytes=image_bytes,
        image_payload=image_payload,
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
        "summary": build_prompt_free_summary_payload(
            prediction=prediction,
            image_payload=image_payload,
        ),
    }
