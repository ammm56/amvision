"""SAM3 video-interactive-segment 节点测试。"""

from __future__ import annotations

from types import SimpleNamespace

from PIL import Image
import torch

from backend.nodes import ExecutionImageRegistry, build_memory_image_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.sam3_segment_nodes.backend.nodes import video_interactive_segment


def test_video_interactive_segment_returns_tracks_and_summary(monkeypatch) -> None:
    """验证 video-interactive 节点会返回 tracks 与 summary。"""

    captured: dict[str, object] = {"predict_calls": 0, "prompt_history": []}

    class _FakeSession:
        def prepare_frame_context(self, *, image_bytes: bytes):
            return _build_fake_frame_context(width=96, height=72)

        def predict_from_frame_context(self, *, frame_context, prompt_items):
            captured["predict_calls"] = int(captured["predict_calls"]) + 1
            cast_history = list(captured["prompt_history"])
            cast_history.append(prompt_items)
            captured["prompt_history"] = cast_history
            return SimpleNamespace(
                regions=(
                    SimpleNamespace(
                        region_id="region-1",
                        score=0.91,
                        class_id=0,
                        class_name="tracked-object",
                        bbox_xyxy=(8.0, 12.0, 44.0, 52.0),
                        polygon_xy=((8.0, 12.0), (44.0, 12.0), (44.0, 52.0), (8.0, 52.0)),
                        area=1440,
                        prompt_id="track-1",
                        source_prompt_text=None,
                        source_prompt_positive_texts=None,
                        source_prompt_negative_texts=None,
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
                    "prompt_kinds": ["box"],
                    "region_count": 1,
                    "inference_mode": "interactive-segment",
                    "postprocess_profile": "sam3-default-v2",
                },
            )

    monkeypatch.setattr(
        video_interactive_segment,
        "get_or_create_sam3_interactive_runtime_session",
        lambda **_: _FakeSession(),
    )

    frame_window_payload, image_registry = _build_test_frame_window_payload(frame_count=2, width=96, height=72)
    request = WorkflowNodeExecutionRequest(
        node_id="node-sam3-video-interactive",
        node_definition=SimpleNamespace(node_type_id=video_interactive_segment.NODE_TYPE_ID),
        parameters={"model_scale": "l", "device": "cpu", "precision": "fp32"},
        input_values={
            "frames": frame_window_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "track-1",
                        "prompt_kind": "box",
                        "display_name": "Tracked ROI",
                        "bbox_xyxy": [8, 12, 44, 52],
                    }
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = video_interactive_segment.handle_node(request)

    assert captured["predict_calls"] == 2
    assert output["tracks"]["count"] == 2
    assert output["tracks"]["items"][0]["track_id"] == "track-1"
    assert output["tracks"]["items"][0]["frame_index"] == 0
    assert output["tracks"]["items"][1]["frame_index"] == 1
    assert output["summary"]["project_native"] is True
    assert output["summary"]["inference_mode"] == "video-interactive-segment"
    assert output["summary"]["processed_frame_count"] == 2
    assert output["summary"]["unique_track_count"] == 1
    assert output["summary"]["track_ids"] == ["track-1"]
    assert output["summary"]["frame_prompt_mode"] == "memory-prototype-state"
    assert output["summary"]["propagated_prompt_counts"] == [0, 1]
    assert output["summary"]["memory_tracked_prompt_count"] == 1
    assert output["summary"]["memory_track_history_lengths"]["track-1"] == 2
    prompt_history = captured["prompt_history"]
    assert len(prompt_history) == 2
    assert prompt_history[0][0].prompt_kind == "box"
    assert prompt_history[1][0].prompt_kind == "mask"
    assert output["tracks"]["items"][0]["state"] == "seeded"
    assert output["tracks"]["items"][1]["state"] == "propagated"


def test_video_interactive_segment_runs_project_native_smoke() -> None:
    """验证 video-interactive 节点会加载本地 project-native runtime。"""

    frame_window_payload, image_registry = _build_test_frame_window_payload(frame_count=2, width=128, height=96)
    request = WorkflowNodeExecutionRequest(
        node_id="node-sam3-video-real-smoke",
        node_definition=SimpleNamespace(node_type_id=video_interactive_segment.NODE_TYPE_ID),
        parameters={"model_scale": "l", "device": "cpu", "precision": "fp32"},
        input_values={
            "frames": frame_window_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "box-1",
                        "prompt_kind": "box",
                        "display_name": "测试框",
                        "bbox_xyxy": [24, 20, 96, 76],
                    }
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = video_interactive_segment.handle_node(request)

    assert output["summary"]["project_native"] is True
    assert output["summary"]["inference_mode"] == "video-interactive-segment"
    assert output["summary"]["processed_frame_count"] == 2
    assert output["summary"]["postprocess_profile"] == "sam3-default-v2"
    assert output["summary"]["frame_prompt_mode"] == "memory-prototype-state"
    assert output["tracks"]["count"] >= 1


def test_video_interactive_segment_supports_explicit_shared_prompt_mode(monkeypatch) -> None:
    """验证 video-interactive 节点允许显式回退到 shared prompt 模式。"""

    captured: dict[str, object] = {"prompt_history": []}

    class _FakeSession:
        def prepare_frame_context(self, *, image_bytes: bytes):
            return _build_fake_frame_context(width=96, height=72)

        def predict_from_frame_context(self, *, frame_context, prompt_items):
            cast_history = list(captured["prompt_history"])
            cast_history.append(prompt_items)
            captured["prompt_history"] = cast_history
            return SimpleNamespace(
                regions=(
                    SimpleNamespace(
                        region_id="region-1",
                        score=0.88,
                        class_id=0,
                        class_name="tracked-object",
                        bbox_xyxy=(8.0, 12.0, 44.0, 52.0),
                        polygon_xy=((8.0, 12.0), (44.0, 12.0), (44.0, 52.0), (8.0, 52.0)),
                        area=1440,
                        prompt_id="track-1",
                        source_prompt_text=None,
                        source_prompt_positive_texts=None,
                        source_prompt_negative_texts=None,
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
                    "prompt_kinds": ["box"],
                    "region_count": 1,
                    "inference_mode": "interactive-segment",
                    "postprocess_profile": "sam3-default-v2",
                },
            )

    monkeypatch.setattr(
        video_interactive_segment,
        "get_or_create_sam3_interactive_runtime_session",
        lambda **_: _FakeSession(),
    )

    frame_window_payload, image_registry = _build_test_frame_window_payload(frame_count=2, width=96, height=72)
    request = WorkflowNodeExecutionRequest(
        node_id="node-sam3-video-interactive-shared",
        node_definition=SimpleNamespace(node_type_id=video_interactive_segment.NODE_TYPE_ID),
        parameters={
            "model_scale": "l",
            "device": "cpu",
            "precision": "fp32",
            "tracking_mode": "shared-prompts-across-window",
        },
        input_values={
            "frames": frame_window_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "track-1",
                        "prompt_kind": "box",
                        "display_name": "Tracked ROI",
                        "bbox_xyxy": [8, 12, 44, 52],
                    }
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = video_interactive_segment.handle_node(request)

    assert output["summary"]["frame_prompt_mode"] == "shared-prompts-across-window"
    assert output["summary"]["propagated_prompt_counts"] == [0, 0]
    prompt_history = captured["prompt_history"]
    assert prompt_history[0][0].prompt_kind == "box"
    assert prompt_history[1][0].prompt_kind == "box"


def test_video_interactive_segment_memory_mode_supports_longer_window(monkeypatch) -> None:
    """验证默认 memory 模式可以稳定处理更长窗口。"""

    captured: dict[str, object] = {"prompt_history": []}

    class _FakeSession:
        def prepare_frame_context(self, *, image_bytes: bytes):
            return _build_fake_frame_context(width=96, height=72)

        def predict_from_frame_context(self, *, frame_context, prompt_items):
            cast_history = list(captured["prompt_history"])
            cast_history.append(prompt_items)
            captured["prompt_history"] = cast_history
            return SimpleNamespace(
                regions=(
                    _build_fake_region(
                        prompt_id="track-1",
                        class_name="long-window-track",
                    ),
                ),
                summary=_build_fake_summary(),
            )

    monkeypatch.setattr(
        video_interactive_segment,
        "get_or_create_sam3_interactive_runtime_session",
        lambda **_: _FakeSession(),
    )

    frame_window_payload, image_registry = _build_test_frame_window_payload(frame_count=6, width=96, height=72)
    request = WorkflowNodeExecutionRequest(
        node_id="node-sam3-video-interactive-long-window",
        node_definition=SimpleNamespace(node_type_id=video_interactive_segment.NODE_TYPE_ID),
        parameters={"model_scale": "l", "device": "cpu", "precision": "fp32"},
        input_values={
            "frames": frame_window_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "track-1",
                        "prompt_kind": "box",
                        "display_name": "Tracked ROI",
                        "bbox_xyxy": [8, 12, 44, 52],
                    }
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = video_interactive_segment.handle_node(request)

    assert output["summary"]["processed_frame_count"] == 6
    assert output["summary"]["frame_prompt_mode"] == "memory-prototype-state"
    assert output["summary"]["propagated_prompt_counts"] == [0, 1, 1, 1, 1, 1]
    assert output["summary"]["memory_track_history_lengths"]["track-1"] == 4
    prompt_history = captured["prompt_history"]
    assert prompt_history[0][0].prompt_kind == "box"
    for prompt_items in prompt_history[1:]:
        assert prompt_items[0].prompt_kind == "mask"


def test_video_interactive_segment_memory_mode_supports_multiple_objects(monkeypatch) -> None:
    """验证默认 memory 模式可以同时维护多个对象状态。"""

    captured: dict[str, object] = {"prompt_history": []}

    class _FakeSession:
        def prepare_frame_context(self, *, image_bytes: bytes):
            return _build_fake_frame_context(width=120, height=80)

        def predict_from_frame_context(self, *, frame_context, prompt_items):
            cast_history = list(captured["prompt_history"])
            cast_history.append(prompt_items)
            captured["prompt_history"] = cast_history
            regions = tuple(
                _build_fake_region(
                    prompt_id=item.prompt_id,
                    class_name=item.display_name,
                )
                for item in prompt_items
            )
            return SimpleNamespace(
                regions=regions,
                summary=_build_fake_summary(prompt_count=len(prompt_items), region_count=len(regions)),
            )

    monkeypatch.setattr(
        video_interactive_segment,
        "get_or_create_sam3_interactive_runtime_session",
        lambda **_: _FakeSession(),
    )

    frame_window_payload, image_registry = _build_test_frame_window_payload(frame_count=3, width=120, height=80)
    request = WorkflowNodeExecutionRequest(
        node_id="node-sam3-video-interactive-multi-object",
        node_definition=SimpleNamespace(node_type_id=video_interactive_segment.NODE_TYPE_ID),
        parameters={"model_scale": "l", "device": "cpu", "precision": "fp32"},
        input_values={
            "frames": frame_window_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "track-1",
                        "prompt_kind": "box",
                        "display_name": "Object A",
                        "bbox_xyxy": [8, 12, 44, 52],
                    },
                    {
                        "prompt_id": "track-2",
                        "prompt_kind": "point",
                        "display_name": "Object B",
                        "point_xy": [70, 22],
                        "point_label": "positive",
                    },
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = video_interactive_segment.handle_node(request)

    assert output["summary"]["processed_frame_count"] == 3
    assert output["summary"]["unique_track_count"] == 2
    assert output["summary"]["track_ids"] == ["track-1", "track-2"]
    assert output["summary"]["memory_tracked_prompt_count"] == 2
    assert output["summary"]["memory_track_history_lengths"]["track-1"] == 3
    assert output["summary"]["memory_track_history_lengths"]["track-2"] == 3
    assert output["tracks"]["count"] == 6
    prompt_history = captured["prompt_history"]
    assert tuple(item.prompt_kind for item in prompt_history[0]) == ("box", "point")
    for prompt_items in prompt_history[1:]:
        assert tuple(item.prompt_kind for item in prompt_items) == ("mask", "mask")


def test_video_interactive_segment_supports_explicit_memory_attention_mode(monkeypatch) -> None:
    """验证 video-interactive 节点允许显式切到 memory-attention-tracker。"""

    captured: dict[str, object] = {"prompt_history": []}

    class _FakeSession:
        def prepare_frame_context(self, *, image_bytes: bytes):
            return _build_fake_frame_context(width=104, height=76)

        def predict_from_frame_context(self, *, frame_context, prompt_items):
            cast_history = list(captured["prompt_history"])
            cast_history.append(prompt_items)
            captured["prompt_history"] = cast_history
            return SimpleNamespace(
                regions=(
                    _build_fake_region(
                        prompt_id="track-1",
                        class_name="attention-track",
                    ),
                ),
                summary=_build_fake_summary(),
            )

    monkeypatch.setattr(
        video_interactive_segment,
        "get_or_create_sam3_interactive_runtime_session",
        lambda **_: _FakeSession(),
    )

    frame_window_payload, image_registry = _build_test_frame_window_payload(frame_count=3, width=104, height=76)
    request = WorkflowNodeExecutionRequest(
        node_id="node-sam3-video-interactive-attention",
        node_definition=SimpleNamespace(node_type_id=video_interactive_segment.NODE_TYPE_ID),
        parameters={
            "model_scale": "l",
            "device": "cpu",
            "precision": "fp32",
            "tracking_mode": "memory-attention-tracker",
        },
        input_values={
            "frames": frame_window_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "track-1",
                        "prompt_kind": "box",
                        "display_name": "Tracked ROI",
                        "bbox_xyxy": [8, 12, 44, 52],
                    }
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = video_interactive_segment.handle_node(request)

    assert output["summary"]["frame_prompt_mode"] == "memory-attention-tracker"
    assert output["summary"]["propagated_prompt_counts"] == [0, 1, 1]
    assert output["summary"]["memory_tracked_prompt_count"] == 1
    assert output["summary"]["memory_track_history_lengths"]["track-1"] == 3
    assert "memory_attention_peaks" in output["summary"]
    prompt_history = captured["prompt_history"]
    assert prompt_history[0][0].prompt_kind == "box"
    assert prompt_history[1][0].prompt_kind == "mask"
    assert prompt_history[2][0].prompt_kind == "mask"


def test_video_interactive_segment_memory_attention_runs_project_native_smoke() -> None:
    """验证 video-interactive 节点可以加载本地 memory-attention-tracker 模式。"""

    frame_window_payload, image_registry = _build_test_frame_window_payload(frame_count=2, width=128, height=96)
    request = WorkflowNodeExecutionRequest(
        node_id="node-sam3-video-attention-real-smoke",
        node_definition=SimpleNamespace(node_type_id=video_interactive_segment.NODE_TYPE_ID),
        parameters={
            "model_scale": "l",
            "device": "cpu",
            "precision": "fp32",
            "tracking_mode": "memory-attention-tracker",
        },
        input_values={
            "frames": frame_window_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "box-1",
                        "prompt_kind": "box",
                        "display_name": "测试框",
                        "bbox_xyxy": [24, 20, 96, 76],
                    }
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = video_interactive_segment.handle_node(request)

    assert output["summary"]["project_native"] is True
    assert output["summary"]["inference_mode"] == "video-interactive-segment"
    assert output["summary"]["processed_frame_count"] == 2
    assert output["summary"]["frame_prompt_mode"] == "memory-attention-tracker"
    assert output["tracks"]["count"] >= 1


def _build_fake_frame_context(*, width: int, height: int):
    """构造满足视频 memory/state 跟踪测试的假帧上下文。"""

    return SimpleNamespace(
        prepared_image=SimpleNamespace(
            original_width=width,
            original_height=height,
        ),
        low_res_feature_map=torch.ones((1, 8, 8, 8), dtype=torch.float32),
    )


def _build_fake_region(*, prompt_id: str, class_name: str):
    """构造测试用 fake region。"""

    return SimpleNamespace(
        region_id=f"region-{prompt_id}",
        score=0.91,
        class_id=0,
        class_name=class_name,
        bbox_xyxy=(8.0, 12.0, 44.0, 52.0),
        polygon_xy=((8.0, 12.0), (44.0, 12.0), (44.0, 52.0), (8.0, 52.0)),
        area=1440,
        prompt_id=prompt_id,
        source_prompt_text=None,
        source_prompt_positive_texts=None,
        source_prompt_negative_texts=None,
        mask_png_bytes=_build_test_png_bytes(width=64, height=64),
        mask_width=64,
        mask_height=64,
    )


def _build_fake_summary(*, prompt_count: int = 1, region_count: int = 1) -> dict[str, object]:
    """构造测试用 fake summary。"""

    return {
        "project_native": True,
        "model_scale": "l",
        "variant_name": "default",
        "checkpoint_path": "fake-sam3.pt",
        "device": "cpu",
        "precision": "fp32",
        "prompt_count": prompt_count,
        "prompt_kinds": ["box"],
        "region_count": region_count,
        "inference_mode": "interactive-segment",
        "postprocess_profile": "sam3-default-v2",
    }


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
            created_by_node_id=f"fixture-frame-{frame_index}",
        )
        frame_items.append(
            {
                "frame_index": frame_index,
                "timestamp_ms": float(frame_index * 100),
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
            "source_video": {
                "transport_kind": "local-path",
                "local_path": "W:/videos/demo.mp4",
                "media_type": "video/mp4",
                "frame_count": frame_count,
                "fps": 10.0,
                "width": width,
                "height": height,
                "duration_ms": float(frame_count * 100),
            },
            "count": frame_count,
            "window_start_index": 0,
            "window_end_index": frame_count - 1,
            "items": frame_items,
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
