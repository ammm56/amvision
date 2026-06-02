"""SAM3 视频链路显式 integration 闭环回归。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from backend.nodes import ExecutionImageRegistry
from backend.nodes.core_nodes.video_body import _video_body_handler
from backend.nodes.core_nodes.video_decode_frames import _video_decode_frames_handler
from backend.nodes.core_nodes.video_load_local import _video_load_local_handler
from backend.nodes.core_nodes.video_overlay_render import _video_overlay_render_handler
from backend.nodes.core_nodes.video_save import _video_save_handler
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from custom_nodes.sam3_segment_nodes.backend.nodes import (
    video_interactive_segment,
    video_semantic_segment,
)


def test_sam3_video_semantic_closure_smoke(tmp_path: Path) -> None:
    """验证本地视频经 decode -> video-semantic -> overlay -> save -> video-body 可以闭环。"""

    execution_metadata = _build_execution_metadata(tmp_path, workflow_run_id="sam3-video-semantic-closure")
    local_video_path = _write_test_video_file(tmp_path / "sam3-video-semantic-closure.avi")

    loaded_video = _video_load_local_handler(
        WorkflowNodeExecutionRequest(
            node_id="video-load-local",
            node_definition=object(),
            parameters={"local_path": str(local_video_path)},
            input_values={},
            execution_metadata=execution_metadata,
        )
    )
    decoded_frames = _video_decode_frames_handler(
        WorkflowNodeExecutionRequest(
            node_id="video-decode-frames",
            node_definition=object(),
            parameters={"start_frame": 0, "end_frame": 3, "step": 1, "max_frames": 4, "encode_format": "png"},
            input_values={"video": loaded_video["video"]},
            execution_metadata=execution_metadata,
        )
    )
    tracked_output = video_semantic_segment.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="sam3-video-semantic",
            node_definition=object(),
            parameters={"model_scale": "l", "device": "cpu", "precision": "fp32"},
            input_values={
                "frames": decoded_frames["frames"],
                "prompts": {
                    "items": [
                        {"prompt_id": "foreground", "display_name": "Foreground", "text": "foreground object"},
                        {"prompt_id": "foreground", "display_name": "Foreground", "text": "background clutter", "negative": True},
                    ]
                },
            },
            execution_metadata=execution_metadata,
        )
    )
    rendered_frames = _video_overlay_render_handler(
        WorkflowNodeExecutionRequest(
            node_id="video-overlay-render",
            node_definition=object(),
            parameters={"draw_masks": True, "draw_labels": True, "output_format": "png"},
            input_values={
                "frames": decoded_frames["frames"],
                "tracks": tracked_output["tracks"],
            },
            execution_metadata=execution_metadata,
        )
    )
    saved_video = _video_save_handler(
        WorkflowNodeExecutionRequest(
            node_id="video-save",
            node_definition=object(),
            parameters={"output_transport_kind": "storage", "container": "mp4", "overwrite": True},
            input_values={"frames": rendered_frames["frames"]},
            execution_metadata=execution_metadata,
        )
    )
    body_output = _video_body_handler(
        WorkflowNodeExecutionRequest(
            node_id="video-body",
            node_definition=object(),
            parameters={"title": "SAM3 Video Semantic Closure"},
            input_values={"video": saved_video["video"]},
            execution_metadata=execution_metadata,
        )
    )

    assert tracked_output["summary"]["project_native"] is True
    assert tracked_output["summary"]["inference_mode"] == "video-semantic-segment"
    assert tracked_output["summary"]["frame_prompt_mode"] == "shared-text-prompts-across-window"
    assert tracked_output["summary"]["processed_frame_count"] == 4
    assert rendered_frames["summary"]["value"]["frame_count"] == 4
    assert saved_video["summary"]["value"]["output_transport_kind"] == "storage"
    assert body_output["body"]["type"] == "video"
    assert body_output["body"]["video"]["transport_kind"] == "storage-ref"
    dataset_storage = execution_metadata["dataset_storage"]
    assert dataset_storage.resolve(body_output["body"]["video"]["object_key"]).is_file() is True


def test_sam3_video_interactive_closure_smoke(tmp_path: Path) -> None:
    """验证本地视频经 decode -> video-interactive -> overlay -> save -> video-body 可以闭环。"""

    execution_metadata = _build_execution_metadata(tmp_path, workflow_run_id="sam3-video-interactive-closure")
    local_video_path = _write_test_video_file(tmp_path / "sam3-video-interactive-closure.avi")

    loaded_video = _video_load_local_handler(
        WorkflowNodeExecutionRequest(
            node_id="video-load-local",
            node_definition=object(),
            parameters={"local_path": str(local_video_path)},
            input_values={},
            execution_metadata=execution_metadata,
        )
    )
    decoded_frames = _video_decode_frames_handler(
        WorkflowNodeExecutionRequest(
            node_id="video-decode-frames",
            node_definition=object(),
            parameters={"start_frame": 0, "end_frame": 3, "step": 1, "max_frames": 4, "encode_format": "png"},
            input_values={"video": loaded_video["video"]},
            execution_metadata=execution_metadata,
        )
    )
    tracked_output = video_interactive_segment.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="sam3-video-interactive",
            node_definition=object(),
            parameters={"model_scale": "l", "device": "cpu", "precision": "fp32"},
            input_values={
                "frames": decoded_frames["frames"],
                "prompts": {
                    "items": [
                        {
                            "prompt_id": "track-1",
                            "prompt_kind": "box",
                            "display_name": "Moving Object",
                            "bbox_xyxy": [12, 20, 54, 82],
                        }
                    ]
                },
            },
            execution_metadata=execution_metadata,
        )
    )
    rendered_frames = _video_overlay_render_handler(
        WorkflowNodeExecutionRequest(
            node_id="video-overlay-render",
            node_definition=object(),
            parameters={"draw_masks": True, "draw_labels": True, "output_format": "png"},
            input_values={
                "frames": decoded_frames["frames"],
                "tracks": tracked_output["tracks"],
            },
            execution_metadata=execution_metadata,
        )
    )
    saved_video = _video_save_handler(
        WorkflowNodeExecutionRequest(
            node_id="video-save",
            node_definition=object(),
            parameters={"output_transport_kind": "storage", "container": "mp4", "overwrite": True},
            input_values={"frames": rendered_frames["frames"]},
            execution_metadata=execution_metadata,
        )
    )
    body_output = _video_body_handler(
        WorkflowNodeExecutionRequest(
            node_id="video-body",
            node_definition=object(),
            parameters={"title": "SAM3 Video Interactive Closure"},
            input_values={"video": saved_video["video"]},
            execution_metadata=execution_metadata,
        )
    )

    assert tracked_output["summary"]["project_native"] is True
    assert tracked_output["summary"]["inference_mode"] == "video-interactive-segment"
    assert tracked_output["summary"]["frame_prompt_mode"] == "memory-prototype-state"
    assert tracked_output["summary"]["processed_frame_count"] == 4
    assert rendered_frames["summary"]["value"]["frame_count"] == 4
    assert saved_video["summary"]["value"]["output_transport_kind"] == "storage"
    assert body_output["body"]["type"] == "video"
    assert body_output["body"]["video"]["transport_kind"] == "storage-ref"
    dataset_storage = execution_metadata["dataset_storage"]
    assert dataset_storage.resolve(body_output["body"]["video"]["object_key"]).is_file() is True


def _build_execution_metadata(tmp_path: Path, *, workflow_run_id: str) -> dict[str, object]:
    """构造视频闭环 integration 需要的执行元数据。"""

    return {
        "execution_image_registry": ExecutionImageRegistry(),
        "dataset_storage": LocalDatasetStorage(
            DatasetStorageSettings(root_dir=str(tmp_path / "dataset-storage"))
        ),
        "workflow_run_id": workflow_run_id,
    }


def _write_test_video_file(video_path: Path, *, frame_count: int = 4, width: int = 160, height: int = 112) -> Path:
    """写入一段本地测试视频。"""

    video_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(video_path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        5.0,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"无法创建测试视频: {video_path}")
    for frame_index in range(frame_count):
        frame = np.full((height, width, 3), 235, dtype=np.uint8)
        x_offset = 12 + frame_index * 16
        cv2.rectangle(frame, (x_offset, 20), (x_offset + 42, 82), (30, 30, 30), thickness=-1)
        cv2.circle(frame, (width - 32 - frame_index * 6, 48 + frame_index * 4), 14, (50, 160, 70), thickness=-1)
        writer.write(frame)
    writer.release()
    return video_path.resolve()
