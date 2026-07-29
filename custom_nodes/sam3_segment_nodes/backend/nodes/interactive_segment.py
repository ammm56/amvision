"""SAM3 交互分割节点实现。"""

from __future__ import annotations

from typing import cast

from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.inputs import (
    read_image_bytes,
    read_interactive_prompt_items,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.postprocess import (
    resolve_sam3_postprocess_options,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.results import (
    build_interactive_summary_payload,
    build_regions_payload,
)
from custom_nodes.sam3_segment_nodes.backend.runtime.workflow_session import (
    Sam3WorkflowModelSession,
    resolve_sam3_session_lease,
)


NODE_TYPE_ID = "custom.sam3.interactive-segment"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行 SAM3 交互分割节点。

    支持 box / point / polygon / mask prompt，并返回 regions.v1。
    """

    image_payload, image_bytes = read_image_bytes(request, input_name="image")
    prompt_items = read_interactive_prompt_items(
        request.input_values.get("prompts"),
        request=request,
        source_image_payload=image_payload,
        source_image_bytes=image_bytes,
    )
    postprocess_options = resolve_sam3_postprocess_options(request.parameters)
    lease = resolve_sam3_session_lease(request, capability="interactive")
    with lease.locked_session(capability="interactive") as workflow_session:
        prediction = cast(
            Sam3WorkflowModelSession, workflow_session
        ).require_interactive().predict(
            image_bytes=image_bytes,
            image_payload=image_payload,
            prompt_items=prompt_items,
            mask_threshold=postprocess_options.mask_threshold,
            stability_offset=postprocess_options.stability_offset,
            min_component_area=postprocess_options.min_component_area,
            polygon_simplify_ratio=postprocess_options.polygon_simplify_ratio,
        )
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
