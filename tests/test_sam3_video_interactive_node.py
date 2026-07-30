"""SAM3.1 Multiplex video-interactive 节点测试。"""

from __future__ import annotations

import io
from types import SimpleNamespace

import numpy as np
from PIL import Image
import torch

from backend.nodes import ExecutionImageRegistry, build_memory_image_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.sam3_segment_nodes.backend.nodes import (
    video_interactive_segment,
)
from tests.sam3_workflow_session_test_support import patch_video_sessions


def test_video_interactive_uses_seed_once_and_multiplex_for_later_frames(
    monkeypatch,
) -> None:
    """验证首帧只初始化一次，后续帧全部进入 Multiplex propagation。"""

    interactive = _FakeInteractiveSession()
    multiplex = _FakeMultiplexSession()
    patch_video_sessions(
        monkeypatch,
        video_interactive_segment,
        interactive=interactive,
        multiplex=multiplex,
    )
    frame_window, registry = _build_frame_window(frame_count=4)
    request = WorkflowNodeExecutionRequest(
        node_id="sam3-video-interactive",
        node_definition=SimpleNamespace(
            node_type_id=video_interactive_segment.NODE_TYPE_ID
        ),
        parameters={"refine_iterations": 2},
        input_values={
            "frames": frame_window,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "object-a",
                        "prompt_kind": "box",
                        "display_name": "Object A",
                        "bbox_xyxy": [8, 8, 40, 40],
                    },
                    {
                        "prompt_id": "object-b",
                        "prompt_kind": "box",
                        "display_name": "Object B",
                        "bbox_xyxy": [44, 16, 80, 56],
                    },
                ]
            },
        },
        execution_metadata={"execution_image_registry": registry},
    )

    output = video_interactive_segment.handle_node(request)

    assert interactive.seed_calls == 1
    assert multiplex.prepare_calls == 4
    assert multiplex.model.propagate_calls == 3
    assert output["tracks"]["count"] == 8
    assert output["summary"]["frame_prompt_mode"] == (
        "sam3.1-multiplex-propagation"
    )
    assert output["summary"]["processed_frame_count"] == 4
    assert output["summary"]["tracking_config"] == {
        "request_state_scope": "node-execution",
        "session_serialized": True,
        "bucketized_decoder": True,
        "multiplex_count": 16,
    }


class _FakeInteractiveSession:
    def __init__(self) -> None:
        self.seed_calls = 0

    def prepare_frame_context(self, **_kwargs):
        return object()

    def build_propagation_seed(
        self,
        *,
        prompt_items,
        refine_iterations,
        **_kwargs,
    ):
        self.seed_calls += 1
        assert refine_iterations == 2
        object_count = len(prompt_items)
        return SimpleNamespace(
            mask_logits=torch.full(
                (object_count, 1, 8, 8),
                8.0,
                dtype=torch.float32,
            ),
            object_tokens=torch.ones(
                (object_count, 256),
                dtype=torch.float32,
            ),
            prompt_ids=tuple(item.prompt_id for item in prompt_items),
        )


class _FakeMultiplexModel:
    multiplex_count = 16
    num_mask_memory = 7

    def __init__(self) -> None:
        self.propagate_calls = 0

    def project_interactive_object_tokens(self, tokens):
        return tokens

    def encode_memory(self, **kwargs):
        return SimpleNamespace(
            frame_index=kwargs["frame_index"],
            conditioning=kwargs["conditioning"],
        )

    def propagate(self, *, multiplex_state, frame_index, **_kwargs):
        self.propagate_calls += 1
        object_count = multiplex_state.total_valid_entries
        return SimpleNamespace(
            mask_logits=torch.full(
                (object_count, 1, 8, 8),
                8.0,
                dtype=torch.float32,
            ),
            iou_scores=torch.full(
                (object_count,),
                0.9,
                dtype=torch.float32,
            ),
            memory_entry=SimpleNamespace(
                frame_index=frame_index,
                conditioning=False,
            ),
        )


class _FakeMultiplexSession:
    def __init__(self) -> None:
        self.model = _FakeMultiplexModel()
        self.prepare_calls = 0

    def prepare_frame_context(self, **_kwargs):
        self.prepare_calls += 1
        return SimpleNamespace(
            prepared_image=SimpleNamespace(
                target_width=8,
                target_height=8,
            ),
            features=SimpleNamespace(
                pixel_feature=torch.ones(
                    (1, 256, 4, 4),
                    dtype=torch.float32,
                )
            ),
            preprocess_ms=1.0,
            backbone_ms=2.0,
        )

    def diagnostics(self):
        return {
            "project_native": True,
            "runtime": "sam3.1-multiplex-propagation",
        }


def _build_frame_window(
    *,
    frame_count: int,
    width: int = 96,
    height: int = 72,
) -> tuple[dict[str, object], ExecutionImageRegistry]:
    registry = ExecutionImageRegistry()
    items: list[dict[str, object]] = []
    for frame_index in range(frame_count):
        image_bytes = _build_png(width=width, height=height)
        registered = registry.register_image_bytes(
            content=image_bytes,
            media_type="image/png",
            width=width,
            height=height,
            created_by_node_id=f"frame-{frame_index}",
        )
        items.append(
            {
                "frame_index": frame_index,
                "timestamp_ms": float(frame_index * 100),
                "image": build_memory_image_payload(
                    image_handle=registered.image_handle,
                    media_type="image/png",
                    width=width,
                    height=height,
                ),
            }
        )
    return (
        {
            "source_video": {"media_type": "video/mp4"},
            "count": frame_count,
            "items": items,
        },
        registry,
    )


def _build_png(*, width: int, height: int) -> bytes:
    image = Image.fromarray(
        np.full((height, width, 3), 255, dtype=np.uint8)
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
