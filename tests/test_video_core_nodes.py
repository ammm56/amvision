"""视频 core 节点与 payload 规则 测试。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from backend.nodes import ExecutionImageRegistry
from backend.nodes.core_catalog import get_core_workflow_payload_contracts
from backend.nodes.core_nodes.tracks_filter import _tracks_filter_handler
from backend.nodes.core_nodes.tracks_to_regions import _tracks_to_regions_handler
from backend.nodes.core_nodes.video_decode_frames import _video_decode_frames_handler
from backend.nodes.core_nodes.video_body import _video_body_handler
from backend.nodes.core_nodes.video_frame_window_item_get import _video_frame_window_item_get_handler
from backend.nodes.core_nodes.frame_window_preview import _frame_window_preview_handler
from backend.nodes.core_nodes.video_load_local import _video_load_local_handler
from backend.nodes.core_nodes.video_overlay_render import _video_overlay_render_handler
from backend.nodes.core_nodes.video_save import _video_save_handler
from backend.nodes.runtime_support import build_memory_image_payload
from backend.nodes.video_runtime_support import (
    VIDEO_TRANSPORT_LOCAL_PATH,
    VIDEO_TRANSPORT_STORAGE,
    probe_video_metadata,
    probe_video_metadata_with_backend,
    require_video_payload,
    resolve_video_tool_path,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_core_catalog_contains_video_payload_contracts() -> None:
    """验证 core catalog 已公开视频相关 payload 规则。"""

    payload_type_ids = {contract.payload_type_id for contract in get_core_workflow_payload_contracts()}

    assert "video-ref.v1" in payload_type_ids
    assert "frame-window.v1" in payload_type_ids
    assert "tracks.v1" in payload_type_ids
    assert "regions.v1" in payload_type_ids


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


def test_frame_window_preview_handler_returns_gallery_preview_body(tmp_path: Path) -> None:
    """验证 frame-window-preview 会把帧窗口整理成 gallery-preview body。"""

    video_path = _build_test_video_file(tmp_path / "sample.avi", frame_count=5)
    metadata = probe_video_metadata(video_path)
    image_registry = ExecutionImageRegistry()
    decoded_output = _video_decode_frames_handler(
        WorkflowNodeExecutionRequest(
            node_id="video-decode",
            node_definition=object(),
            parameters={"start_frame": 0, "end_frame": 4, "step": 1, "max_frames": 8, "encode_format": "png"},
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

    output = _frame_window_preview_handler(
        WorkflowNodeExecutionRequest(
            node_id="frame-window-preview",
            node_definition=object(),
            parameters={"title": "Decoded Frames", "sample_mode": "uniform", "max_items": 3},
            input_values={"frames": decoded_output["frames"]},
            execution_metadata={"execution_image_registry": image_registry},
        )
    )

    body = output["body"]
    assert body["type"] == "gallery-preview"
    assert body["title"] == "Decoded Frames"
    assert body["total_count"] == 5
    assert body["sample_count"] == 3
    assert len(body["items"]) == 3
    assert body["items"][0]["frame_index"] == 0
    assert body["items"][-1]["frame_index"] == 4
    assert body["items"][0]["image"]["transport_kind"] == "inline-base64"


def test_video_body_handler_returns_storage_ref_response_body(tmp_path: Path) -> None:
    """验证 video-body 会把 video-ref 转成正式可播放响应结构。"""

    video_path = _build_test_video_file(tmp_path / "sample.avi", frame_count=4)
    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "dataset-storage")))

    output = _video_body_handler(
        WorkflowNodeExecutionRequest(
            node_id="video-body",
            node_definition=object(),
            parameters={"title": "Saved Video"},
            input_values={
                "video": {
                    "transport_kind": VIDEO_TRANSPORT_LOCAL_PATH,
                    "local_path": str(video_path),
                    "media_type": "video/x-msvideo",
                    "frame_count": 4,
                    "fps": 5.0,
                    "width": 48,
                    "height": 32,
                    "duration_ms": 800.0,
                }
            },
            execution_metadata={
                "dataset_storage": dataset_storage,
                "workflow_run_id": "run-video-body",
            },
        )
    )

    body = output["body"]
    assert body["type"] == "video"
    assert body["title"] == "Saved Video"
    assert body["video"]["transport_kind"] == "storage-ref"
    assert body["video"]["object_key"].startswith("workflows/runtime/run-video-body/video-body/")
    assert dataset_storage.resolve(body["video"]["object_key"]).is_file() is True


def test_probe_video_metadata_prefers_ffprobe_when_available(tmp_path: Path) -> None:
    """验证元数据探测在可用时优先走 ffprobe。"""

    video_path = _build_test_video_file(tmp_path / "sample.avi", frame_count=3)
    ffprobe_path = resolve_video_tool_path("ffprobe")

    metadata, backend_name = probe_video_metadata_with_backend(video_path)

    assert metadata["frame_count"] == 3
    if ffprobe_path is not None:
        assert backend_name == "ffprobe"


def test_tracks_filter_handler_filters_by_score_state_and_class_name() -> None:
    """验证 tracks-filter 会按参数过滤 tracks.v1。"""

    output = _tracks_filter_handler(
        WorkflowNodeExecutionRequest(
            node_id="tracks-filter",
            node_definition=object(),
            parameters={
                "min_score": 0.7,
                "states": ["tracked"],
                "class_names": ["part-a"],
            },
            input_values={"tracks": _build_tracks_payload()},
            execution_metadata={},
        )
    )

    tracks_payload = output["tracks"]
    assert tracks_payload["count"] == 1
    assert tracks_payload["items"][0]["track_id"] == "track-1"
    assert output["summary"]["value"]["original_count"] == 3
    assert output["summary"]["value"]["filtered_count"] == 1


def test_tracks_to_regions_handler_defaults_to_latest_frame() -> None:
    """验证 tracks-to-regions 默认提取最新帧。"""

    output = _tracks_to_regions_handler(
        WorkflowNodeExecutionRequest(
            node_id="tracks-to-regions",
            node_definition=object(),
            parameters={},
            input_values={"tracks": _build_tracks_payload()},
            execution_metadata={},
        )
    )

    regions_payload = output["regions"]
    assert regions_payload["count"] == 1
    assert regions_payload["selected_frame_index"] == 8
    assert regions_payload["items"][0]["track_id"] == "track-3"
    assert output["summary"]["value"]["selection_mode"] == "latest-frame"


def test_tracks_to_regions_handler_accepts_explicit_frame_index_input() -> None:
    """验证 tracks-to-regions 会按输入端口选择指定帧。"""

    output = _tracks_to_regions_handler(
        WorkflowNodeExecutionRequest(
            node_id="tracks-to-regions",
            node_definition=object(),
            parameters={},
            input_values={
                "tracks": _build_tracks_payload(),
                "frame_index": {"value": 7},
            },
            execution_metadata={},
        )
    )

    regions_payload = output["regions"]
    assert regions_payload["count"] == 2
    assert regions_payload["selected_frame_index"] == 7
    assert {item["track_id"] for item in regions_payload["items"]} == {"track-1", "track-2"}
    assert output["summary"]["value"]["selection_mode"] == "explicit-frame"


def test_video_overlay_render_handler_renders_tracks_back_to_frame_window(tmp_path: Path) -> None:
    """验证 video-overlay-render 会把 tracks 渲染回新 frame-window。"""

    video_path = _build_test_video_file(tmp_path / "sample.avi", frame_count=2)
    metadata = probe_video_metadata(video_path)
    image_registry = ExecutionImageRegistry()
    decoded_output = _video_decode_frames_handler(
        WorkflowNodeExecutionRequest(
            node_id="video-decode",
            node_definition=object(),
            parameters={"start_frame": 0, "end_frame": 1, "encode_format": "png"},
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
    mask_payload_0 = _register_test_mask_payload(image_registry, width=48, height=32, x1=4, y1=4, x2=18, y2=18)
    mask_payload_1 = _register_test_mask_payload(image_registry, width=48, height=32, x1=6, y1=6, x2=22, y2=22)

    output = _video_overlay_render_handler(
        WorkflowNodeExecutionRequest(
            node_id="video-overlay",
            node_definition=object(),
            parameters={"draw_masks": True, "draw_labels": True, "output_format": "png"},
            input_values={
                "frames": decoded_output["frames"],
                "tracks": {
                    "source_video": decoded_output["frames"]["source_video"],
                    "count": 2,
                    "items": [
                        {
                            "track_id": "track-a",
                            "frame_index": 0,
                            "timestamp_ms": 0.0,
                            "score": 0.91,
                            "class_id": 1,
                            "class_name": "part-a",
                            "bbox_xyxy": [4.0, 4.0, 18.0, 18.0],
                            "polygon_xy": [[4.0, 4.0], [18.0, 4.0], [18.0, 18.0], [4.0, 18.0]],
                            "mask_image": mask_payload_0,
                            "region_id": "region-a0",
                            "state": "tracked",
                            "area": 196,
                        },
                        {
                            "track_id": "track-a",
                            "frame_index": 1,
                            "timestamp_ms": 200.0,
                            "score": 0.88,
                            "class_id": 1,
                            "class_name": "part-a",
                            "bbox_xyxy": [6.0, 6.0, 22.0, 22.0],
                            "polygon_xy": [[6.0, 6.0], [22.0, 6.0], [22.0, 22.0], [6.0, 22.0]],
                            "mask_image": mask_payload_1,
                            "region_id": "region-a1",
                            "state": "tracked",
                            "area": 256,
                        },
                    ],
                },
            },
            execution_metadata={"execution_image_registry": image_registry},
        )
    )

    rendered_frames = output["frames"]
    assert rendered_frames["count"] == 2
    assert output["summary"]["value"]["overlay_item_count"] == 2
    first_source_handle = decoded_output["frames"]["items"][0]["image"]["image_handle"]
    first_rendered_handle = rendered_frames["items"][0]["image"]["image_handle"]
    assert image_registry.read_bytes(first_source_handle) != image_registry.read_bytes(first_rendered_handle)


def test_video_save_handler_writes_local_video_file(tmp_path: Path) -> None:
    """验证 video-save 可以把 frame-window 保存为本地视频。"""

    video_path = _build_test_video_file(tmp_path / "sample.avi", frame_count=3)
    metadata = probe_video_metadata(video_path)
    image_registry = ExecutionImageRegistry()
    decoded_output = _video_decode_frames_handler(
        WorkflowNodeExecutionRequest(
            node_id="video-decode",
            node_definition=object(),
            parameters={"start_frame": 0, "end_frame": 2, "encode_format": "png"},
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
    output_path = tmp_path / "rendered-video.mp4"

    output = _video_save_handler(
        WorkflowNodeExecutionRequest(
            node_id="video-save",
            node_definition=object(),
            parameters={
                "output_transport_kind": VIDEO_TRANSPORT_LOCAL_PATH,
                "local_path": str(output_path),
                "container": "mp4",
                "overwrite": True,
            },
            input_values={"frames": decoded_output["frames"]},
            execution_metadata={"execution_image_registry": image_registry},
        )
    )

    assert output_path.is_file() is True
    assert output["video"]["transport_kind"] == VIDEO_TRANSPORT_LOCAL_PATH
    assert output["summary"]["value"]["output_transport_kind"] == VIDEO_TRANSPORT_LOCAL_PATH
    assert output["video"]["frame_count"] >= 1


def test_video_save_handler_writes_storage_video_ref(tmp_path: Path) -> None:
    """验证 video-save 可以把 frame-window 保存到 storage video-ref。"""

    video_path = _build_test_video_file(tmp_path / "sample.avi", frame_count=3)
    metadata = probe_video_metadata(video_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "dataset-storage")))
    decoded_output = _video_decode_frames_handler(
        WorkflowNodeExecutionRequest(
            node_id="video-decode",
            node_definition=object(),
            parameters={"start_frame": 0, "end_frame": 2, "encode_format": "png"},
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

    output = _video_save_handler(
        WorkflowNodeExecutionRequest(
            node_id="video-save",
            node_definition=object(),
            parameters={"output_transport_kind": VIDEO_TRANSPORT_STORAGE, "container": "avi"},
            input_values={"frames": decoded_output["frames"]},
            execution_metadata={
                "execution_image_registry": image_registry,
                "dataset_storage": dataset_storage,
                "workflow_run_id": "run-test-video-save",
            },
        )
    )

    assert output["video"]["transport_kind"] == VIDEO_TRANSPORT_STORAGE
    object_key = output["video"]["object_key"]
    assert dataset_storage.resolve(object_key).is_file() is True
    assert output["summary"]["value"]["output_transport_kind"] == VIDEO_TRANSPORT_STORAGE


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


def _build_tracks_payload() -> dict[str, object]:
    """构造测试用 tracks.v1 payload。"""

    return {
        "source_video": {
            "transport_kind": VIDEO_TRANSPORT_LOCAL_PATH,
            "local_path": "W:/videos/sample.mp4",
            "media_type": "video/mp4",
        },
        "count": 3,
        "items": [
            {
                "track_id": "track-1",
                "frame_index": 7,
                "timestamp_ms": 1400.0,
                "score": 0.92,
                "class_id": 1,
                "class_name": "part-a",
                "bbox_xyxy": [1.0, 2.0, 11.0, 12.0],
                "polygon_xy": [[1.0, 2.0], [11.0, 2.0], [11.0, 12.0], [1.0, 12.0]],
                "mask_image": {
                    "transport_kind": "memory",
                    "image_handle": "mask-1",
                    "media_type": "image/png",
                    "width": 48,
                    "height": 32,
                },
                "region_id": "region-1",
                "state": "tracked",
                "prompt_id": "prompt-a",
                "area": 110,
                "source_prompt_text": "part a",
                "source_prompt_positive_texts": ["part a"],
                "source_prompt_negative_texts": [],
            },
            {
                "track_id": "track-2",
                "frame_index": 7,
                "timestamp_ms": 1400.0,
                "score": 0.63,
                "class_id": 2,
                "class_name": "part-b",
                "bbox_xyxy": [5.0, 6.0, 15.0, 16.0],
                "polygon_xy": [[5.0, 6.0], [15.0, 6.0], [15.0, 16.0], [5.0, 16.0]],
                "mask_image": {
                    "transport_kind": "memory",
                    "image_handle": "mask-2",
                    "media_type": "image/png",
                    "width": 48,
                    "height": 32,
                },
                "region_id": "region-2",
                "state": "candidate",
                "prompt_id": "prompt-b",
                "area": 96,
            },
            {
                "track_id": "track-3",
                "frame_index": 8,
                "timestamp_ms": 1600.0,
                "score": 0.74,
                "class_id": 3,
                "class_name": "part-c",
                "bbox_xyxy": [9.0, 10.0, 19.0, 20.0],
                "polygon_xy": [[9.0, 10.0], [19.0, 10.0], [19.0, 20.0], [9.0, 20.0]],
                "mask_image": {
                    "transport_kind": "memory",
                    "image_handle": "mask-3",
                    "media_type": "image/png",
                    "width": 48,
                    "height": 32,
                },
                "region_id": "region-3",
                "state": "tracked",
                "prompt_id": "prompt-c",
                "area": 120,
            },
        ],
    }


def _register_test_mask_payload(
    image_registry: ExecutionImageRegistry,
    *,
    width: int,
    height: int,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
) -> dict[str, object]:
    """构造测试用二值 mask image-ref。"""

    mask_matrix = np.zeros((height, width), dtype=np.uint8)
    mask_matrix[y1:y2, x1:x2] = 255
    encode_success, encoded_mask = cv2.imencode(".png", mask_matrix)
    assert encode_success is True
    image_entry = image_registry.register_image_bytes(
        content=encoded_mask.tobytes(),
        media_type="image/png",
        width=width,
        height=height,
        created_by_node_id="test-mask",
    )
    return build_memory_image_payload(
        image_handle=image_entry.image_handle,
        media_type="image/png",
        width=width,
        height=height,
    )
