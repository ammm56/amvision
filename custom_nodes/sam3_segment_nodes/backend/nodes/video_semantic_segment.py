"""SAM3.1 Multiplex 视频语义分割节点实现。"""

from __future__ import annotations

from typing import cast

import torch
import torch.nn.functional as F

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
    merge_text_prompt_items,
    read_frame_window_items,
    read_text_prompt_items,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.postprocess import (
    resolve_sam3_postprocess_options,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.results import (
    build_tracks_payload,
    build_video_semantic_summary_payload,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.types import (
    Sam3InteractivePromptItem,
)
from custom_nodes.sam3_segment_nodes.backend.runtime.workflow_session import (
    Sam3WorkflowModelSession,
    resolve_sam3_session_lease,
)


NODE_TYPE_ID = "custom.sam3.video-semantic-segment"


@torch.inference_mode()
def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """用首帧文本检测 Mask 初始化 Multiplex propagation。"""

    frame_window_payload = request.input_values.get("frames")
    frame_items = read_frame_window_items(
        frame_window_payload,
        request=request,
    )
    first_frame = frame_items[0]
    prompt_items = read_text_prompt_items(
        request.input_values.get("prompts")
    )
    prompt_groups = merge_text_prompt_items(prompt_items)
    postprocess_options = resolve_sam3_postprocess_options(
        request.parameters
    )
    lease = resolve_sam3_session_lease(
        request,
        capability="video-semantic",
    )

    with lease.locked_session(
        capability="video-semantic"
    ) as workflow_session:
        session = cast(Sam3WorkflowModelSession, workflow_session)
        semantic = session.require_semantic()
        interactive = session.require_interactive()
        multiplex = session.require_multiplex()
        first_prediction = semantic.predict(
            image_bytes=first_frame.image_bytes,
            image_payload=first_frame.image_payload,
            prompt_items=prompt_groups,
            mask_threshold=postprocess_options.mask_threshold,
            stability_offset=postprocess_options.stability_offset,
            min_component_area=postprocess_options.min_component_area,
            polygon_simplify_ratio=(
                postprocess_options.polygon_simplify_ratio
            ),
        )
        if not first_prediction.regions:
            raise InvalidRequestError(
                "SAM3 video-semantic 首帧没有检测到可传播对象"
            )
        prompt_group_by_id = {
            group.prompt_id: group for group in prompt_groups
        }
        active_prompt_groups = tuple(
            prompt_group_by_id[region.prompt_id]
            for region in first_prediction.regions
            if region.prompt_id in prompt_group_by_id
        )
        mask_prompt_items = tuple(
            Sam3InteractivePromptItem(
                prompt_id=region.prompt_id,
                prompt_kind="mask",
                display_name=region.class_name,
                prompt_mask=region.mask_array,
            )
            for region in first_prediction.regions
            if region.prompt_id in prompt_group_by_id
        )
        if len(active_prompt_groups) != len(mask_prompt_items):
            raise RuntimeError("SAM3 semantic propagation prompt 对齐失败")
        interactive_context = interactive.prepare_frame_context(
            image_bytes=first_frame.image_bytes,
            image_payload=first_frame.image_payload,
        )
        pointer_seed = interactive.build_propagation_seed(
            frame_context=interactive_context,
            prompt_items=mask_prompt_items,
            refine_iterations=1,
        )
        first_multiplex_context = multiplex.prepare_frame_context(
            image_bytes=first_frame.image_bytes,
            image_payload=first_frame.image_payload,
        )
        device = first_multiplex_context.features.pixel_feature.device
        dtype = first_multiplex_context.features.pixel_feature.dtype
        hard_mask_tensor = torch.stack(
            [
                torch.from_numpy(region.mask_array)
                for region in first_prediction.regions
                if region.prompt_id in prompt_group_by_id
            ],
            dim=0,
        ).unsqueeze(1)
        hard_mask_logits = (
            F.interpolate(
                hard_mask_tensor.to(
                    device=device,
                    dtype=torch.float32,
                ),
                size=(
                    first_multiplex_context.prepared_image.target_height,
                    first_multiplex_context.prepared_image.target_width,
                ),
                mode="nearest",
            )
            * 20.0
            - 10.0
        )
        multiplex_state = build_sam3_multiplex_state(
            object_ids=pointer_seed.prompt_ids,
            device=device,
            dtype=dtype,
            multiplex_count=multiplex.model.multiplex_count,
        )
        object_pointers = multiplex.model.project_interactive_object_tokens(
            pointer_seed.object_tokens.to(dtype=dtype)
        )
        object_score_logits = hard_mask_logits.new_full(
            (len(pointer_seed.prompt_ids), 1),
            10.0,
        )
        first_memory = multiplex.model.encode_memory(
            frame_index=first_frame.frame_index,
            frame_features=first_multiplex_context.features,
            multiplex_state=multiplex_state,
            mask_logits=hard_mask_logits,
            object_score_logits=object_score_logits,
            object_pointers=multiplex_state.mux(object_pointers),
            conditioning=True,
        )
        memory_entries = [first_memory]
        runtime_summary = {
            **first_prediction.summary,
            **multiplex.diagnostics(),
            "inference_mode": "video-semantic-segment",
            "first_frame_detector": "sam3.1-semantic",
            "propagation_branch": "sam3.1-multiplex",
            "bucketized_decoder": True,
            "multiplex": multiplex_state.diagnostics(),
            "semantic_seed_count": len(active_prompt_groups),
        }
        frame_predictions: list[dict[str, object]] = [
            {
                "frame_index": first_frame.frame_index,
                "timestamp_ms": first_frame.timestamp_ms,
                "regions": first_prediction.regions,
                "summary": runtime_summary,
                "region_states": ["semantic-seed"]
                * len(first_prediction.regions),
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
                prompt_items=active_prompt_groups,
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
                    "summary": runtime_summary,
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
        "summary": build_video_semantic_summary_payload(
            source_video=source_video,
            prompt_items=prompt_items,
            prompt_groups=prompt_groups,
            frame_items=frame_items,
            frame_predictions=frame_predictions_tuple,
        ),
    }
