"""SAM3 交互分割节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.sam3_segment_nodes.backend.nodes._common import (
    build_interactive_summary_payload,
    build_regions_payload,
    get_or_create_sam3_interactive_runtime_session,
    normalize_device,
    normalize_model_scale,
    normalize_precision,
    read_image_bytes,
    read_interactive_prompt_items,
)


NODE_TYPE_ID = "custom.sam3.interactive-segment"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行 SAM3 交互分割节点。

    当前阶段支持 box / point / polygon prompt，并返回 regions.v1。
    """

    image_payload, image_bytes = read_image_bytes(request, input_name="image")
    prompt_items = read_interactive_prompt_items(
        request.input_values.get("prompts"),
        request=request,
        source_image_payload=image_payload,
        source_image_bytes=image_bytes,
    )
    model_scale = normalize_model_scale(request.parameters.get("model_scale"))
    device = normalize_device(request.parameters.get("device"))
    precision = normalize_precision(request.parameters.get("precision"))
    runtime_session = get_or_create_sam3_interactive_runtime_session(
        model_scale=model_scale,
        device=device,
        precision=precision,
    )
    prediction = runtime_session.predict(image_bytes=image_bytes, prompt_items=prompt_items)
    return {
        "regions": build_regions_payload(
            request,
            prediction=prediction,
            image_payload=image_payload,
        ),
        "summary": build_interactive_summary_payload(
            prediction=prediction,
            image_payload=image_payload,
            prompt_items=prompt_items,
        ),
    }
