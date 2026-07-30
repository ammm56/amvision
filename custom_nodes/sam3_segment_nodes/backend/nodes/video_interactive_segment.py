"""SAM3.1 Multiplex 视频交互分割节点实现。"""

from __future__ import annotations

from typing import cast

import torch

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.sam3_segment_nodes.backend.core.postprocess.masks import (
    postprocess_sam3_interactive_masks,
)
from custom_nodes.sam3_segment_nodes.backend.core.state.multiplex import (
    build_sam3_multiplex_state,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.inputs import (
    read_frame_window_items,
    read_interactive_prompt_items,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.postprocess import (
    resolve_sam3_postprocess_options,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.results import (
    build_tracks_payload,
    build_video_interactive_summary_payload,
)
from custom_nodes.sam3_segment_nodes.backend.runtime.workflow_session import (
    Sam3WorkflowModelSession,
    resolve_sam3_session_lease,
)


NODE_TYPE_ID = "custom.sam3.video-interactive-segment"


def _resolve_refine_iterations(raw_value: object) -> int:
    """规整首帧 Interactive decoder 的 refine 次数。"""

    try:
        resolved = int(raw_value or 2)
    except (TypeError, ValueError) as error:
        raise InvalidRequestError(
            "SAM3 video-interactive 的 refine_iterations 必须是整数"
        ) from error
    if resolved < 1 or resolved > 3:
        raise InvalidRequestError(
            "SAM3 video-interactive 的 refine_iterations 必须在 1 到 3 之间"
        )
    return resolved


@torch.inference_mode()
def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """用首帧交互结果初始化 Multiplex memory 并传播后续帧。"""

    frame_window_payload = request.input_values.get("frames")
    frame_items = read_frame_window_items(
        frame_window_payload,
        request=request,
    )
    first_frame = frame_items[0]
    prompt_items = read_interactive_prompt_items(
        request.input_values.get("prompts"),
        request=request,
        source_image_payload=first_frame.image_payload,
        source_image_bytes=first_frame.image_bytes,
    )
    postprocess_options = resolve_sam3_postprocess_options(
        request.parameters
    )
    refine_iterations = _resolve_refine_iterations(
        request.parameters.get("refine_iterations")
    )
    lease = resolve_sam3_session_lease(
        request,
        capability="video-interactive",
    )

    with lease.locked_session(
        capability="video-interactive"
    ) as workflow_session:
        session = cast(Sam3WorkflowModelSession, workflow_session)
        interactive = session.require_interactive()
        multiplex = session.require_multiplex()
        interactive_context = interactive.prepare_frame_context(
            image_bytes=first_frame.image_bytes,
            image_payload=first_frame.image_payload,
        )
        seed = interactive.build_propagation_seed(
            frame_context=interactive_context,
            prompt_items=prompt_items,
            refine_iterations=refine_iterations,
        )
        first_multiplex_context = multiplex.prepare_frame_context(
            image_bytes=first_frame.image_bytes,
            image_payload=first_frame.image_payload,
        )
        multiplex_state = build_sam3_multiplex_state(
            object_ids=seed.prompt_ids,
            device=seed.mask_logits.device,
            dtype=first_multiplex_context.features.pixel_feature.dtype,
            multiplex_count=multiplex.model.multiplex_count,
        )
        object_pointers = multiplex.model.project_interactive_object_tokens(
            seed.object_tokens.to(
                dtype=first_multiplex_context.features.pixel_feature.dtype
            )
        )
        object_score_logits = seed.mask_logits.new_full(
            (len(seed.prompt_ids), 1),
            10.0,
        )
        first_memory = multiplex.model.encode_memory(
            frame_index=first_frame.frame_index,
            frame_features=first_multiplex_context.features,
            multiplex_state=multiplex_state,
            mask_logits=seed.mask_logits,
            object_score_logits=object_score_logits,
            object_pointers=multiplex_state.mux(object_pointers),
            conditioning=True,
        )
        memory_entries = [first_memory]
        first_regions = postprocess_sam3_interactive_masks(
            seed.mask_logits,
            source_width=first_frame.width,
            source_height=first_frame.height,
            prompt_items=prompt_items,
            threshold=postprocess_options.mask_threshold,
            stability_offset=postprocess_options.stability_offset,
            min_component_area=postprocess_options.min_component_area,
            polygon_simplify_ratio=(
                postprocess_options.polygon_simplify_ratio
            ),
        )
        runtime_summary = {
            **multiplex.diagnostics(),
            "inference_mode": "video-interactive-segment",
            "propagation_branch": "sam3.1-multiplex",
            "bucketized_decoder": True,
            "multiplex": multiplex_state.diagnostics(),
            "refine_iterations": refine_iterations,
            "timings_ms": {
                "first_frame_preprocess": (
                    first_multiplex_context.preprocess_ms
                ),
                "first_frame_backbone": (
                    first_multiplex_context.backbone_ms
                ),
            },
        }
        frame_predictions: list[dict[str, object]] = [
            {
                "frame_index": first_frame.frame_index,
                "timestamp_ms": first_frame.timestamp_ms,
                "regions": first_regions,
                "summary": runtime_summary,
                "region_states": ["seeded"] * len(first_regions),
            }
        ]
        for frame_item in frame_items[1:]:
            frame_context = multiplex.prepare_frame_context(
                image_bytes=frame_item.image_bytes,
                image_payload=frame_item.image_payload,
            )
            propagation = multiplex.model.propagate(
                frame_index=frame_item.frame_index,
                frame_features=frame_context.features,
                multiplex_state=multiplex_state,
                memory_entries=tuple(memory_entries),
                total_frame_count=len(frame_items),
            )
            regions = postprocess_sam3_interactive_masks(
                propagation.mask_logits,
                source_width=frame_item.width,
                source_height=frame_item.height,
                prompt_items=prompt_items,
                scores=propagation.iou_scores,
                threshold=postprocess_options.mask_threshold,
                stability_offset=postprocess_options.stability_offset,
                min_component_area=postprocess_options.min_component_area,
                polygon_simplify_ratio=(
                    postprocess_options.polygon_simplify_ratio
                ),
            )
            memory_entries.append(propagation.memory_entry)
            if len(memory_entries) > 16:
                memory_entries = [
                    memory_entries[0],
                    *memory_entries[-15:],
                ]
            frame_predictions.append(
                {
                    "frame_index": frame_item.frame_index,
                    "timestamp_ms": frame_item.timestamp_ms,
                    "regions": regions,
                    "summary": {
                        **runtime_summary,
                        "frame_preprocess_ms": frame_context.preprocess_ms,
                        "frame_backbone_ms": frame_context.backbone_ms,
                    },
                    "region_states": ["propagated"] * len(regions),
                }
            )

    frame_predictions_tuple = tuple(frame_predictions)
    source_video = (
        frame_window_payload.get("source_video")
        if isinstance(frame_window_payload, dict)
        else {}
    )
    return {
        "tracks": build_tracks_payload(
            request,
            source_video=source_video,
            frame_predictions=frame_predictions_tuple,
        ),
        "summary": build_video_interactive_summary_payload(
            source_video=source_video,
            prompt_items=prompt_items,
            frame_items=frame_items,
            frame_predictions=frame_predictions_tuple,
            tracking_mode="sam3.1-multiplex-propagation",
            propagated_prompt_counts=tuple(
                0 if index == 0 else len(prompt_items)
                for index in range(len(frame_items))
            ),
            object_memory_history_lengths={
                prompt_id: min(
                    len(frame_items),
                    multiplex.model.num_mask_memory,
                )
                for prompt_id in seed.prompt_ids
            },
            tracking_config={
                "request_state_scope": "node-execution",
                "session_serialized": True,
                "bucketized_decoder": True,
                "multiplex_count": multiplex.model.multiplex_count,
            },
        ),
    }
