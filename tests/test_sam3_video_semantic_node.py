"""SAM3.1 Multiplex video-semantic 节点测试。"""

from __future__ import annotations

import io
from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image
import torch

from backend.nodes import ExecutionImageRegistry, build_memory_image_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.sam3_segment_nodes.backend.core.postprocess.masks import (
    Sam3RegionItem,
)
from custom_nodes.sam3_segment_nodes.backend.nodes import (
    video_semantic_segment,
)
from tests.sam3_workflow_session_test_support import patch_video_sessions


def test_video_semantic_detects_first_frame_then_propagates(
    monkeypatch,
) -> None:
    """验证文本检测只跑首帧，后续帧复用 Multiplex memory。"""

    semantic = _FakeSemanticSession()
    interactive = _FakeInteractiveSession()
    multiplex = _FakeMultiplexSession()
    patch_video_sessions(
        monkeypatch,
        video_semantic_segment,
        interactive=interactive,
        semantic=semantic,
        multiplex=multiplex,
    )
    frame_window, registry = _build_frame_window(frame_count=3)
    request = WorkflowNodeExecutionRequest(
        node_id="sam3-video-semantic",
        node_definition=SimpleNamespace(
            node_type_id=video_semantic_segment.NODE_TYPE_ID
        ),
        parameters={},
        input_values={
            "frames": frame_window,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "defect",
                        "text": "defect",
                        "display_name": "Defect",
                    }
                ]
            },
        },
        execution_metadata={"execution_image_registry": registry},
    )

    output = video_semantic_segment.handle_node(request)

    assert semantic.predict_calls == 1
    assert interactive.seed_calls == 1
    assert multiplex.model.propagate_calls == 2
    assert output["tracks"]["count"] == 3
    assert output["summary"]["propagation_branch"] == "sam3.1-multiplex"
    assert output["summary"]["processed_frame_count"] == 3
    assert output["summary"]["frame_prompt_mode"] == (
        "sam3.1-multiplex-propagation"
    )


class _FakeSemanticSession:
    def __init__(self) -> None:
        self.predict_calls = 0

    def predict(self, **_kwargs):
        self.predict_calls += 1
        mask = np.ones((72, 96), dtype=np.uint8)
        encoded, buffer = cv2.imencode(".png", mask * 255)
        assert encoded
        return SimpleNamespace(
            regions=(
                Sam3RegionItem(
                    region_id="region-defect",
                    score=0.95,
                    class_id=0,
                    class_name="Defect",
                    bbox_xyxy=(0.0, 0.0, 95.0, 71.0),
                    polygon_xy=(
                        (0.0, 0.0),
                        (95.0, 0.0),
                        (95.0, 71.0),
                        (0.0, 71.0),
                    ),
                    area=int(mask.sum()),
                    prompt_id="defect",
                    mask_array=mask,
                    mask_png_bytes=buffer.tobytes(),
                    mask_width=96,
                    mask_height=72,
                    source_prompt_text="defect",
                    source_prompt_positive_texts=("defect",),
                    source_prompt_negative_texts=(),
                ),
            ),
            summary={
                "project_native": True,
                "inference_mode": "semantic-segment",
            },
        )


class _FakeInteractiveSession:
    def __init__(self) -> None:
        self.seed_calls = 0

    def prepare_frame_context(self, **_kwargs):
        return object()

    def build_propagation_seed(self, *, prompt_items, **_kwargs):
        self.seed_calls += 1
        return SimpleNamespace(
            mask_logits=torch.full((1, 1, 8, 8), 8.0),
            object_tokens=torch.ones((1, 256)),
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

    def propagate(self, *, frame_index, **_kwargs):
        self.propagate_calls += 1
        return SimpleNamespace(
            mask_logits=torch.full((1, 1, 8, 8), 8.0),
            iou_scores=torch.tensor([0.9]),
            memory_entry=SimpleNamespace(
                frame_index=frame_index,
                conditioning=False,
            ),
        )


class _FakeMultiplexSession:
    def __init__(self) -> None:
        self.model = _FakeMultiplexModel()

    def prepare_frame_context(self, **_kwargs):
        return SimpleNamespace(
            prepared_image=SimpleNamespace(
                target_width=8,
                target_height=8,
            ),
            features=SimpleNamespace(
                pixel_feature=torch.ones((1, 256, 4, 4))
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
) -> tuple[dict[str, object], ExecutionImageRegistry]:
    registry = ExecutionImageRegistry()
    items: list[dict[str, object]] = []
    for frame_index in range(frame_count):
        content = _build_png()
        registered = registry.register_image_bytes(
            content=content,
            media_type="image/png",
            width=96,
            height=72,
            created_by_node_id=f"frame-{frame_index}",
        )
        items.append(
            {
                "frame_index": frame_index,
                "timestamp_ms": float(frame_index * 100),
                "image": build_memory_image_payload(
                    image_handle=registered.image_handle,
                    media_type="image/png",
                    width=96,
                    height=72,
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


def _build_png() -> bytes:
    image = Image.fromarray(np.full((72, 96, 3), 255, dtype=np.uint8))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
