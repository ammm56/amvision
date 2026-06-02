"""SAM3 video-interactive 更长窗口/更大位移/更多对象数显式回归。"""

from __future__ import annotations

import io
from types import SimpleNamespace

from PIL import Image, ImageDraw

from backend.nodes import ExecutionImageRegistry, build_memory_image_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.sam3_segment_nodes.backend.nodes import video_interactive_segment


def test_sam3_video_interactive_long_window_large_displacement_smoke() -> None:
    """验证真实 project-native runtime 可以处理更长窗口与更大位移。"""

    frame_window_payload, image_registry = _build_moving_object_frame_window_payload(
        frame_count=6,
        width=192,
        height=128,
        object_box_sequence=((12, 20, 64, 88), (28, 20, 80, 88), (52, 20, 104, 88), (84, 20, 136, 88), (112, 20, 164, 88), (128, 20, 180, 88)),
    )
    request = WorkflowNodeExecutionRequest(
        node_id="node-sam3-video-long-window-regression",
        node_definition=SimpleNamespace(node_type_id=video_interactive_segment.NODE_TYPE_ID),
        parameters={"model_scale": "l", "device": "cpu", "precision": "fp32"},
        input_values={
            "frames": frame_window_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "track-1",
                        "prompt_kind": "box",
                        "display_name": "Moving Object",
                        "bbox_xyxy": [12, 20, 64, 88],
                    }
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = video_interactive_segment.handle_node(request)

    assert output["summary"]["project_native"] is True
    assert output["summary"]["inference_mode"] == "video-interactive-segment"
    assert output["summary"]["processed_frame_count"] == 6
    assert output["summary"]["frame_prompt_mode"] == "memory-prototype-state"
    assert output["tracks"]["count"] >= 1


def test_sam3_video_interactive_multi_object_smoke() -> None:
    """验证真实 project-native runtime 可以处理多对象 prompt。"""

    frame_window_payload, image_registry = _build_two_object_frame_window_payload(
        frame_count=4,
        width=192,
        height=128,
    )
    request = WorkflowNodeExecutionRequest(
        node_id="node-sam3-video-multi-object-regression",
        node_definition=SimpleNamespace(node_type_id=video_interactive_segment.NODE_TYPE_ID),
        parameters={"model_scale": "l", "device": "cpu", "precision": "fp32"},
        input_values={
            "frames": frame_window_payload,
            "prompts": {
                "items": [
                    {
                        "prompt_id": "track-a",
                        "prompt_kind": "box",
                        "display_name": "Object A",
                        "bbox_xyxy": [12, 18, 52, 74],
                    },
                    {
                        "prompt_id": "track-b",
                        "prompt_kind": "box",
                        "display_name": "Object B",
                        "bbox_xyxy": [118, 40, 170, 106],
                    },
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )

    output = video_interactive_segment.handle_node(request)

    assert output["summary"]["project_native"] is True
    assert output["summary"]["processed_frame_count"] == 4
    assert output["summary"]["prompt_count"] == 2
    assert output["summary"]["frame_prompt_mode"] == "memory-prototype-state"
    assert output["tracks"]["count"] >= 1


def _build_moving_object_frame_window_payload(
    *,
    frame_count: int,
    width: int,
    height: int,
    object_box_sequence: tuple[tuple[int, int, int, int], ...],
) -> tuple[dict[str, object], ExecutionImageRegistry]:
    """构造单对象大位移测试视频帧窗口。"""

    image_registry = ExecutionImageRegistry()
    frame_items: list[dict[str, object]] = []
    for frame_index in range(frame_count):
        frame_bytes = _build_frame_png_bytes(
            width=width,
            height=height,
            rectangles=(
                {
                    "bbox": object_box_sequence[frame_index],
                    "fill": (30, 30, 30),
                    "outline": (0, 180, 255),
                },
            ),
        )
        registered_image = image_registry.register_image_bytes(
            content=frame_bytes,
            media_type="image/png",
            width=width,
            height=height,
            created_by_node_id=f"fixture-sam3-long-{frame_index}",
        )
        frame_items.append(
            {
                "frame_index": frame_index,
                "timestamp_ms": float(frame_index * 120),
                "image": build_memory_image_payload(
                    image_handle=registered_image.image_handle,
                    media_type="image/png",
                    width=width,
                    height=height,
                ),
            }
        )
    return _wrap_frame_window_payload(
        frame_items=frame_items,
        width=width,
        height=height,
        fps=8.3333,
        local_path="W:/videos/sam3-long-window-regression.mp4",
    ), image_registry


def _build_two_object_frame_window_payload(
    *,
    frame_count: int,
    width: int,
    height: int,
) -> tuple[dict[str, object], ExecutionImageRegistry]:
    """构造双对象视频帧窗口。"""

    image_registry = ExecutionImageRegistry()
    frame_items: list[dict[str, object]] = []
    object_a_sequence = ((12, 18, 52, 74), (24, 20, 64, 76), (36, 24, 76, 80), (48, 28, 88, 84))
    object_b_sequence = ((118, 40, 170, 106), (110, 34, 162, 100), (102, 28, 154, 94), (94, 24, 146, 90))
    for frame_index in range(frame_count):
        frame_bytes = _build_frame_png_bytes(
            width=width,
            height=height,
            rectangles=(
                {
                    "bbox": object_a_sequence[frame_index],
                    "fill": (60, 60, 60),
                    "outline": (255, 120, 0),
                },
                {
                    "bbox": object_b_sequence[frame_index],
                    "fill": (90, 90, 90),
                    "outline": (0, 220, 120),
                },
            ),
        )
        registered_image = image_registry.register_image_bytes(
            content=frame_bytes,
            media_type="image/png",
            width=width,
            height=height,
            created_by_node_id=f"fixture-sam3-multi-{frame_index}",
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
    return _wrap_frame_window_payload(
        frame_items=frame_items,
        width=width,
        height=height,
        fps=10.0,
        local_path="W:/videos/sam3-multi-object-regression.mp4",
    ), image_registry


def _wrap_frame_window_payload(
    *,
    frame_items: list[dict[str, object]],
    width: int,
    height: int,
    fps: float,
    local_path: str,
) -> dict[str, object]:
    """把帧列表封装成 frame-window.v1。"""

    return {
        "source_video": {
            "transport_kind": "local-path",
            "local_path": local_path,
            "media_type": "video/mp4",
            "frame_count": len(frame_items),
            "fps": float(fps),
            "width": width,
            "height": height,
            "duration_ms": float((len(frame_items) - 1) * (1000.0 / max(fps, 0.0001))),
        },
        "count": len(frame_items),
        "window_start_index": 0,
        "window_end_index": len(frame_items) - 1,
        "items": frame_items,
    }


def _build_frame_png_bytes(
    *,
    width: int,
    height: int,
    rectangles: tuple[dict[str, object], ...],
) -> bytes:
    """构造带简单目标形状的测试帧。"""

    image = Image.new("RGB", (width, height), color=(245, 245, 245))
    draw = ImageDraw.Draw(image)
    for rectangle in rectangles:
        x1_value, y1_value, x2_value, y2_value = rectangle["bbox"]
        draw.rectangle(
            [(x1_value, y1_value), (x2_value, y2_value)],
            fill=rectangle["fill"],
            outline=rectangle["outline"],
            width=3,
        )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
