"""SAM3 语义分割节点实现。"""

from __future__ import annotations

from time import perf_counter
from typing import cast

from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.inputs import (
    merge_text_prompt_items,
    read_image_bytes,
    read_text_prompt_items,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.postprocess import (
    resolve_sam3_postprocess_options,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.results import (
    build_regions_payload,
    build_semantic_summary_payload,
)
from custom_nodes.sam3_segment_nodes.backend.runtime.workflow_session import (
    Sam3WorkflowModelSession,
    resolve_sam3_session_lease,
)


NODE_TYPE_ID = "custom.sam3.semantic-segment"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行 SAM3 语义分割节点。"""

    node_started_at = perf_counter()
    image_payload, image_bytes = read_image_bytes(request, input_name="image")
    prompt_items = read_text_prompt_items(request.input_values.get("prompts"))
    prompt_groups = merge_text_prompt_items(prompt_items)
    postprocess_options = resolve_sam3_postprocess_options(request.parameters)
    lease = resolve_sam3_session_lease(request, capability="semantic")
    session_wait_started_at = perf_counter()
    with lease.locked_session(capability="semantic") as workflow_session:
        session_wait_ms = round(
            (perf_counter() - session_wait_started_at) * 1000,
            3,
        )
        prediction = (
            cast(Sam3WorkflowModelSession, workflow_session)
            .require_semantic()
            .predict(
                image_bytes=image_bytes,
                image_payload=image_payload,
                prompt_items=prompt_groups,
                mask_threshold=postprocess_options.mask_threshold,
                stability_offset=postprocess_options.stability_offset,
                min_component_area=postprocess_options.min_component_area,
                polygon_simplify_ratio=postprocess_options.polygon_simplify_ratio,
            )
        )
    prediction.summary["runtime_coordination"] = {
        "policy": "single-session-serial",
        "session_wait_ms": session_wait_ms,
        "node_total_ms": round((perf_counter() - node_started_at) * 1000, 3),
    }
    return {
        "regions": build_regions_payload(
            request,
            prediction=prediction,
            image_payload=image_payload,
        ),
        "summary": build_semantic_summary_payload(
            prediction=prediction,
            image_payload=image_payload,
            prompt_items=prompt_items,
            prompt_groups=prompt_groups,
        ),
    }
