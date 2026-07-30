"""SAM3 交互分割节点实现。"""

from __future__ import annotations

from time import perf_counter
from typing import cast

from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from backend.service.application.errors import InvalidRequestError
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

    node_started_at = perf_counter()
    image_payload, image_bytes = read_image_bytes(request, input_name="image")
    prompt_items = read_interactive_prompt_items(
        request.input_values.get("prompts"),
        request=request,
        source_image_payload=image_payload,
        source_image_bytes=image_bytes,
    )
    postprocess_options = resolve_sam3_postprocess_options(request.parameters)
    refine_iterations = _read_refine_iterations(
        request.parameters.get("refine_iterations")
    )
    lease = resolve_sam3_session_lease(request, capability="interactive")
    session_wait_started_at = perf_counter()
    with lease.locked_session(capability="interactive") as workflow_session:
        session_wait_ms = round(
            (perf_counter() - session_wait_started_at) * 1000,
            3,
        )
        prediction = (
            cast(Sam3WorkflowModelSession, workflow_session)
            .require_interactive()
            .predict(
                image_bytes=image_bytes,
                image_payload=image_payload,
                prompt_items=prompt_items,
                refine_iterations=refine_iterations,
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
        "summary": build_interactive_summary_payload(
            prediction=prediction,
            image_payload=image_payload,
            prompt_items=prompt_items,
        ),
    }


def _read_refine_iterations(value: object) -> int:
    """读取并限制 Interactive Mask Decoder 的总执行轮数。"""

    if value is None:
        return 2
    if isinstance(value, bool):
        raise InvalidRequestError("SAM3 refine_iterations 必须是 1 到 3 的整数")
    try:
        normalized_value = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError(
            "SAM3 refine_iterations 必须是 1 到 3 的整数"
        ) from exc
    if normalized_value < 1 or normalized_value > 3:
        raise InvalidRequestError("SAM3 refine_iterations 必须在 1 到 3 之间")
    return normalized_value
