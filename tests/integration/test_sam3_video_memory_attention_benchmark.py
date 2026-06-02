"""SAM3 video-interactive memory-attention 长窗口多对象 soak / benchmark。"""

from __future__ import annotations

import io
from types import SimpleNamespace

from PIL import Image, ImageDraw
import pytest
import torch

from backend.nodes import ExecutionImageRegistry, build_memory_image_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.sam3_segment_nodes.backend.nodes import video_interactive_segment
from tests.integration.test_yoloe_sam3_soak_benchmark import (
    CPU_MEMORY_DRIFT_LIMIT_BYTES,
    GPU_MEMORY_DRIFT_LIMIT_BYTES,
    _run_cpu_soak_benchmark,
    _run_cuda_soak_benchmark,
)


ATTENTION_VIDEO_CPU_SOAK_ITERATIONS = 1
ATTENTION_VIDEO_GPU_SOAK_ITERATIONS = 1


def test_sam3_video_interactive_attention_cpu_extended_benchmark() -> None:
    """验证 memory-attention 模式在长窗口多对象场景下的 CPU 稳定性。"""

    request = _build_attention_benchmark_request(
        device="cpu",
        precision="fp32",
    )
    warm_output = video_interactive_segment.handle_node(request)
    assert warm_output["summary"]["project_native"] is True
    assert warm_output["summary"]["frame_prompt_mode"] == "memory-attention-tracker"
    assert warm_output["summary"]["prompt_count"] == 4
    assert warm_output["summary"]["processed_frame_count"] == 6

    benchmark = _run_cpu_soak_benchmark(
        benchmark_name="sam3-video-interactive-attention-cpu-extended",
        iterations=ATTENTION_VIDEO_CPU_SOAK_ITERATIONS,
        predict_once=lambda: SimpleNamespace(summary=video_interactive_segment.handle_node(request)["summary"]),
    )
    assert benchmark["memory_drift_bytes"] <= CPU_MEMORY_DRIFT_LIMIT_BYTES


@pytest.mark.skipif(not torch.cuda.is_available(), reason="当前环境没有可用 CUDA")
def test_sam3_video_interactive_attention_cuda_extended_benchmark() -> None:
    """验证 memory-attention 模式在长窗口多对象场景下的 CUDA 稳定性。"""

    request = _build_attention_benchmark_request(
        device="cuda",
        precision="fp16",
    )
    warm_output = video_interactive_segment.handle_node(request)
    assert warm_output["summary"]["project_native"] is True
    assert warm_output["summary"]["frame_prompt_mode"] == "memory-attention-tracker"
    assert warm_output["summary"]["prompt_count"] == 4
    assert warm_output["summary"]["processed_frame_count"] == 6

    benchmark = _run_cuda_soak_benchmark(
        benchmark_name="sam3-video-interactive-attention-cuda-extended",
        iterations=ATTENTION_VIDEO_GPU_SOAK_ITERATIONS,
        predict_once=lambda: SimpleNamespace(summary=video_interactive_segment.handle_node(request)["summary"]),
    )
    assert benchmark["memory_drift_bytes"] <= GPU_MEMORY_DRIFT_LIMIT_BYTES


def _build_attention_benchmark_request(
    *,
    device: str,
    precision: str,
) -> WorkflowNodeExecutionRequest:
    """构造 memory-attention 长窗口多对象 benchmark 请求。"""

    frame_window_payload, image_registry = _build_attention_benchmark_frame_window_payload(
        frame_count=6,
        width=192,
        height=144,
    )
    return WorkflowNodeExecutionRequest(
        node_id=f"sam3-video-attention-benchmark-{device}",
        node_definition=SimpleNamespace(node_type_id=video_interactive_segment.NODE_TYPE_ID),
        parameters={
            "model_scale": "l",
            "device": device,
            "precision": precision,
            "tracking_mode": "memory-attention-tracker",
        },
        input_values={
            "frames": frame_window_payload,
            "prompts": {
                "items": [
                    {"prompt_id": "track-a", "prompt_kind": "box", "display_name": "Object A", "bbox_xyxy": [12, 18, 52, 74]},
                    {"prompt_id": "track-b", "prompt_kind": "box", "display_name": "Object B", "bbox_xyxy": [132, 18, 184, 66]},
                    {"prompt_id": "track-c", "prompt_kind": "box", "display_name": "Object C", "bbox_xyxy": [34, 88, 76, 134]},
                    {"prompt_id": "track-d", "prompt_kind": "box", "display_name": "Object D", "bbox_xyxy": [150, 92, 204, 142]},
                ]
            },
        },
        execution_metadata={"execution_image_registry": image_registry},
    )


def _build_attention_benchmark_frame_window_payload(
    *,
    frame_count: int,
    width: int,
    height: int,
) -> tuple[dict[str, object], ExecutionImageRegistry]:
    """构造长窗口多对象 benchmark 的 frame-window。"""

    image_registry = ExecutionImageRegistry()
    frame_items: list[dict[str, object]] = []
    for frame_index in range(frame_count):
        frame_bytes = _build_frame_png_bytes(
            width=width,
            height=height,
            rectangles=(
                {"bbox": (12 + frame_index * 10, 18 + frame_index * 2, 52 + frame_index * 10, 74 + frame_index * 2), "fill": (50, 50, 50), "outline": (255, 120, 0)},
                {"bbox": (132 - frame_index * 8, 18 + frame_index * 3, 184 - frame_index * 8, 66 + frame_index * 3), "fill": (80, 80, 80), "outline": (0, 220, 120)},
                {"bbox": (34 + frame_index * 9, 88 - frame_index * 3, 76 + frame_index * 9, 134 - frame_index * 3), "fill": (70, 70, 70), "outline": (90, 40, 255)},
                {"bbox": (150 - frame_index * 7, 92 - frame_index * 5, 204 - frame_index * 7, 142 - frame_index * 5), "fill": (60, 60, 60), "outline": (255, 70, 120)},
            ),
        )
        registered_image = image_registry.register_image_bytes(
            content=frame_bytes,
            media_type="image/png",
            width=width,
            height=height,
            created_by_node_id=f"fixture-sam3-attention-bench-{frame_index}",
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
    return {
        "source_video": {
            "transport_kind": "local-path",
            "local_path": "W:/videos/sam3-attention-benchmark.mp4",
            "media_type": "video/mp4",
            "frame_count": frame_count,
            "fps": 10.0,
            "width": width,
            "height": height,
            "duration_ms": float((frame_count - 1) * 100.0),
        },
        "count": frame_count,
        "window_start_index": 0,
        "window_end_index": frame_count - 1,
        "items": frame_items,
    }, image_registry


def _build_frame_png_bytes(
    *,
    width: int,
    height: int,
    rectangles: tuple[dict[str, object], ...],
) -> bytes:
    """构造带多对象矩形的测试帧。"""

    image = Image.new("RGB", (width, height), color=(242, 242, 242))
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
