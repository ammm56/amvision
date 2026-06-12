"""视频 workflow 节点共享 helper 门面模块。"""

from __future__ import annotations

from backend.nodes.video_runtime_support_payloads import (
    RESPONSE_VIDEO_TRANSPORT_STORAGE_REF,
    VIDEO_TRANSPORT_LOCAL_PATH,
    VIDEO_TRANSPORT_STORAGE,
    build_local_video_payload,
    build_response_video_payload,
    build_runtime_video_object_key,
    build_storage_video_payload,
    materialize_video_storage_payload,
    require_dataset_storage,
    require_frame_window_payload,
    require_video_payload,
    resolve_video_path_from_request,
    resolve_video_source_path,
)
from backend.nodes.video_runtime_support_tools import (
    VIDEO_TOOL_FFMPEG,
    VIDEO_TOOL_FFPROBE,
    decode_video_frames_with_backend,
    encode_video_frames_with_backend,
    infer_video_media_type,
    infer_video_runtime_platform,
    probe_video_metadata,
    probe_video_metadata_with_backend,
    read_video_tool_summary,
    resolve_video_tool_path,
)


__all__ = [
    "RESPONSE_VIDEO_TRANSPORT_STORAGE_REF",
    "VIDEO_TOOL_FFMPEG",
    "VIDEO_TOOL_FFPROBE",
    "VIDEO_TRANSPORT_LOCAL_PATH",
    "VIDEO_TRANSPORT_STORAGE",
    "build_local_video_payload",
    "build_response_video_payload",
    "build_runtime_video_object_key",
    "build_storage_video_payload",
    "decode_video_frames_with_backend",
    "encode_video_frames_with_backend",
    "infer_video_media_type",
    "infer_video_runtime_platform",
    "materialize_video_storage_payload",
    "probe_video_metadata",
    "probe_video_metadata_with_backend",
    "read_video_tool_summary",
    "require_dataset_storage",
    "require_frame_window_payload",
    "require_video_payload",
    "resolve_video_path_from_request",
    "resolve_video_source_path",
    "resolve_video_tool_path",
]
