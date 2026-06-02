"""视频 core 节点与 payload contract 测试。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from backend.nodes import ExecutionImageRegistry
from backend.nodes.core_catalog import get_core_workflow_payload_contracts
from backend.nodes.core_nodes.video_decode_frames import _video_decode_frames_handler
from backend.nodes.core_nodes.video_frame_window_item_get import _video_frame_window_item_get_handler
from backend.nodes.core_nodes.video_load_local import _video_load_local_handler
from backend.nodes.video_runtime_support import (
    VIDEO_TRANSPORT_LOCAL_PATH,
    probe_video_metadata,
    probe_video_metadata_with_backend,
    require_video_payload,
    resolve_video_tool_path,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def test_core_catalog_contains_video_payload_contracts() -> None:
    """验证 core catalog 已公开视频相关 payload contract。"""

    payload_type_ids = {contract.payload_type_id for contract in get_core_workflow_payload_contracts()}

    assert "video-ref.v1" in payload_type_ids
    assert "frame-window.v1" in payload_type_ids
    assert "tracks.v1" in payload_type_ids


def test_require_video_payload_accepts_local_path_and_backfills_transport_kind(tmp_path: Path) -> None:
    """验证 video-ref 会接受 local_path 并补 transport_kind。"""

    video_path = _build_test_video_file(tmp_path / "sample.avi", frame_count=3)

    payload = require_video_payload({"local_path": str(video_path)})

    assert payload["transport_kind"] == VIDEO_TRANSPORT_LOCAL_PATH
    assert payload["local_path"] == str(video_path)
    assert str(payload["media_type"]).startswith("video/")


def test_video_load_local_handler_returns_video_ref_and_summary(tmp_path: Path) -> None:
    """验证本地视频载入节点会返回探测后的 video-ref。"""

    video_path = _build_test_video_file(tmp_path / "sample.avi", frame_count=4)
    ffprobe_path = resolve_video_tool_path("ffprobe")

    output = _video_load_local_handler(
        WorkflowNodeExecutionRequest(
            node_id="video-load",
            node_definition=object(),
            parameters={"local_path": str(video_path)},
            input_values={},
            execution_metadata={},
        )
    )

    assert output["video"]["transport_kind"] == VIDEO_TRANSPORT_LOCAL_PATH
    assert output["video"]["local_path"] == str(video_path.resolve())
    assert output["video"]["frame_count"] == 4
    assert output["summary"]["value"]["frame_count"] == 4
    assert output["summary"]["value"]["ffprobe_path"] == (str(ffprobe_path) if ffprobe_path is not None else None)
    if ffprobe_path is not None:
        assert output["summary"]["value"]["probe_backend"] == "ffprobe"


def test_video_decode_frames_handler_returns_frame_window_with_memory_images(tmp_path: Path) -> None:
    """验证视频解码节点会返回 frame-window，并把帧注册成 image-ref。"""

    video_path = _build_test_video_file(tmp_path / "sample.avi", frame_count=5)
    metadata = probe_video_metadata(video_path)
    ffmpeg_path = resolve_video_tool_path("ffmpeg")
    image_registry = ExecutionImageRegistry()

    output = _video_decode_frames_handler(
        WorkflowNodeExecutionRequest(
            node_id="video-decode",
            node_definition=object(),
            parameters={"start_frame": 1, "end_frame": 3, "step": 1, "max_frames": 8, "encode_format": "png"},
            input_values={
                "video": {
                    "transport_kind": VIDEO_TRANSPORT_LOCAL_PATH,
                    "local_path": str(video_path),
                    "media_type": "video/x-msvideo",
                    **metadata,
                }
            },
            execution_metadata={"execution_image_registry": image_registry},
        )
    )

    frames_payload = output["frames"]
    assert frames_payload["count"] == 3
    assert frames_payload["window_start_index"] == 1
    assert frames_payload["window_end_index"] == 3
    first_frame = frames_payload["items"][0]
    assert first_frame["frame_index"] == 1
    assert first_frame["image"]["transport_kind"] == "memory"
    assert first_frame["image"]["width"] == metadata["width"]
    assert first_frame["image"]["height"] == metadata["height"]
    assert output["summary"]["value"]["decoded_count"] == 3
    assert output["summary"]["value"]["ffmpeg_path"] == (str(ffmpeg_path) if ffmpeg_path is not None else None)
    if ffmpeg_path is not None:
        assert output["summary"]["value"]["decode_backend"] == "ffmpeg"


def test_video_frame_window_item_get_returns_selected_frame_and_meta(tmp_path: Path) -> None:
    """验证 frame-window-item-get 会返回单帧 image-ref 与帧元数据。"""

    video_path = _build_test_video_file(tmp_path / "sample.avi", frame_count=5)
    metadata = probe_video_metadata(video_path)
    image_registry = ExecutionImageRegistry()

    decoded_output = _video_decode_frames_handler(
        WorkflowNodeExecutionRequest(
            node_id="video-decode",
            node_definition=object(),
            parameters={"start_frame": 1, "end_frame": 3, "step": 1, "max_frames": 8, "encode_format": "png"},
            input_values={
                "video": {
                    "transport_kind": VIDEO_TRANSPORT_LOCAL_PATH,
                    "local_path": str(video_path),
                    "media_type": "video/x-msvideo",
                    **metadata,
                }
            },
            execution_metadata={"execution_image_registry": image_registry},
        )
    )

    output = _video_frame_window_item_get_handler(
        WorkflowNodeExecutionRequest(
            node_id="frame-get",
            node_definition=object(),
            parameters={"index": -1, "allow_negative": True},
            input_values={"frames": decoded_output["frames"]},
            execution_metadata={},
        )
    )

    assert output["image"]["transport_kind"] == "memory"
    assert output["frame_meta"]["value"]["frame_index"] == 3
    assert output["frame_meta"]["value"]["timestamp_ms"] >= 0
    assert output["frame_meta"]["value"]["selected_index"] == 2
    assert output["frame_meta"]["value"]["source_video"]["transport_kind"] == VIDEO_TRANSPORT_LOCAL_PATH


def test_probe_video_metadata_prefers_ffprobe_when_available(tmp_path: Path) -> None:
    """验证元数据探测在可用时优先走 ffprobe。"""

    video_path = _build_test_video_file(tmp_path / "sample.avi", frame_count=3)
    ffprobe_path = resolve_video_tool_path("ffprobe")

    metadata, backend_name = probe_video_metadata_with_backend(video_path)

    assert metadata["frame_count"] == 3
    if ffprobe_path is not None:
        assert backend_name == "ffprobe"


def _build_test_video_file(video_path: Path, *, frame_count: int) -> Path:
    """构造测试用本地 AVI 视频文件。"""

    video_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(video_path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        5.0,
        (48, 32),
    )
    assert writer.isOpened() is True
    for frame_index in range(frame_count):
        frame = np.full((32, 48, 3), frame_index * 20, dtype=np.uint8)
        writer.write(frame)
    writer.release()
    assert video_path.is_file() is True
    return video_path.resolve()
