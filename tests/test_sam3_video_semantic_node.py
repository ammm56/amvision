"""SAM3 video-semantic-segment 节点测试。"""

from __future__ import annotations

from types import SimpleNamespace

from PIL import Image

from backend.nodes import ExecutionImageRegistry, build_memory_image_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.sam3_segment_nodes.backend.nodes import video_semantic_segment


def test_video_semantic_segment_returns_tracks_and_summary(monkeypatch) -> None:
    """验证 video-semantic 节点会返回 tracks 与 summary。"""

    captured: dict[str, object] = {"predict_calls": 0, "prompt_groups": []}

    class _FakeSession:
        def predict(self, *, image_bytes: bytes, prompt_items):
            captured["predict_calls"] = int(captured["predict_calls"]) + 1
            history = list(captured["prompt_groups"])
            history.append(prompt_items)
            captured["prompt_groups"] = history
            return SimpleNamespace(
                regions=(
                    SimpleNamespace(
                        region_id="region-1",
                        score=0.84,
                        class_id=0,
                        class_name="缺陷区域",
                        bbox_xyxy=(8.0, 12.0, 44.0, 52.0),
                        polygon_xy=((8.0, 12.0), (44.0, 12.0), (44.0, 52.0), (8.0, 52.0)),
                        area=1440,
                        prompt_id="prompt-1",
                        source_prompt_text="defect || !background",
                        source_prompt_positive_texts=("defect",),
                        source_prompt_negative_texts=("background",),
                        mask_png_bytes=_build_test_png_bytes(width=64, height=64),
                        mask_width=64,
                        mask_height=64,
                    ),
                ),
                summary={
                    "project_native": True,
                    "model_scale": "l",
                    "variant_name": "default",
                    "checkpoint_path": "fake-sam3.pt",
                    "device": "cpu",
                    "precision": "fp32",
                    "prompt_count": 1,
                    "prompt_item_count": 2,
                    "prompt_group_count": 1,
                    "positive_prompt_count": 1,
                    "negative_prompt_count": 1,
                    "negative_prompt_weight": 0.5,
                    "prompt_texts": ["defect || !background"],
                    "region_count": 1,
                    "inference_mode": "semantic-segment",
                    "text_encoder": "checkpoint-language-backbone",
                    "postprocess_profile": "sam3-default-v2",
                    "prompt_groups": [
                        {
                            "prompt_id": "prompt-1",
                            "display_name": "缺陷区域",
                            "positive_texts": ["defect"],
                            "negative_texts": ["background"],
                            "languages": [],
                        }
                    ],
                },
            )

    monkeypatch.setattr(
        video_semantic_segment,
        "get_or_create_sam3_semantic_runtime_session",
        lambda **_: _FakeSession(),
    )

    frame_window_payload, image_registry = _build_test_frame_window_payload(frame_count=2, width=96, height=72)
    request = WorkflowNodeExecutionRequest(
        node_id="node-sam3-video-semantic",
        node_definition=SimpleNamespace(node_type_id=video_semantic_segment.NODE_TYPE_ID),
        parameters={"model_scale": "l", "device": "cpu", "precision": "fp32"},
        input_values={
            "frames": frame_window_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "prompt-1",
                        "text": "defect",
                        "display_name": "缺陷区域",
                    },
                    {
                        "prompt_id": "prompt-1",
                        "text": "background",
                        "display_name": "缺陷区域",
                        "negative": True,
                    },
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = video_semantic_segment.handle_node(request)

    assert captured["predict_calls"] == 2
    assert output["tracks"]["count"] == 2
    assert output["tracks"]["items"][0]["track_id"] == "prompt-1"
    assert output["tracks"]["items"][0]["state"] == "semantic"
    assert output["tracks"]["items"][0]["source_prompt_positive_texts"] == ["defect"]
    assert output["tracks"]["items"][0]["source_prompt_negative_texts"] == ["background"]
    assert output["summary"]["project_native"] is True
    assert output["summary"]["inference_mode"] == "video-semantic-segment"
    assert output["summary"]["processed_frame_count"] == 2
    assert output["summary"]["unique_track_count"] == 1
    assert output["summary"]["track_ids"] == ["prompt-1"]
    assert output["summary"]["frame_prompt_mode"] == "shared-text-prompts-across-window"
    assert output["summary"]["frame_region_counts"] == [1, 1]
    assert output["summary"]["prompt_count"] == 1
    assert output["summary"]["prompt_item_count"] == 2
    assert output["summary"]["positive_prompt_count"] == 1
    assert output["summary"]["negative_prompt_count"] == 1
    prompt_groups = captured["prompt_groups"]
    assert len(prompt_groups) == 2
    assert prompt_groups[0][0].positive_texts == ("defect",)
    assert prompt_groups[0][0].negative_texts == ("background",)


def test_video_semantic_segment_runs_project_native_smoke() -> None:
    """验证 video-semantic 节点会加载本地 project-native runtime。"""

    frame_window_payload, image_registry = _build_test_frame_window_payload(frame_count=1, width=128, height=96)
    request = WorkflowNodeExecutionRequest(
        node_id="node-sam3-video-semantic-real-smoke",
        node_definition=SimpleNamespace(node_type_id=video_semantic_segment.NODE_TYPE_ID),
        parameters={"model_scale": "l", "device": "cpu", "precision": "fp32"},
        input_values={
            "frames": frame_window_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "prompt-1",
                        "text": "object",
                        "display_name": "object",
                    }
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = video_semantic_segment.handle_node(request)

    assert output["summary"]["project_native"] is True
    assert output["summary"]["inference_mode"] == "video-semantic-segment"
    assert output["summary"]["processed_frame_count"] == 1
    assert output["summary"]["frame_prompt_mode"] == "shared-text-prompts-across-window"
    assert output["summary"]["postprocess_profile"] == "sam3-default-v2"
    assert output["tracks"]["count"] >= 0


def _build_test_frame_window_payload(
    *,
    frame_count: int,
    width: int,
    height: int,
) -> tuple[dict[str, object], ExecutionImageRegistry]:
    """构造测试 frame-window payload。"""

    image_registry = ExecutionImageRegistry()
    frame_items: list[dict[str, object]] = []
    for frame_index in range(frame_count):
        image_bytes = _build_test_png_bytes(width=width, height=height)
        registered_image = image_registry.register_image_bytes(
            content=image_bytes,
            media_type="image/png",
            width=width,
            height=height,
            created_by_node_id="fixture",
        )
        frame_items.append(
            {
                "frame_index": frame_index,
                "timestamp_ms": float(frame_index * 200),
                "image": build_memory_image_payload(
                    image_handle=registered_image.image_handle,
                    media_type="image/png",
                    width=width,
                    height=height,
                ),
            }
        )
    return (
        {
            "transport_kind": "memory-window",
            "count": frame_count,
            "window_start_index": 0,
            "window_end_index": max(0, frame_count - 1),
            "items": frame_items,
            "source_video": {
                "transport_kind": "local-path",
                "local_path": "W:/videos/test.mp4",
                "media_type": "video/mp4",
            },
        },
        image_registry,
    )


def _build_test_png_bytes(*, width: int = 96, height: int = 72) -> bytes:
    """构造测试 PNG 图片。"""

    import io

    image = Image.new("RGB", (width, height), color=(255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
