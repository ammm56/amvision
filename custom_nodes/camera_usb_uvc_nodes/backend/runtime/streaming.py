"""USB / UVC 相机会话采流和帧窗口读取。"""

from __future__ import annotations

from collections import deque
from threading import Event, Thread
from time import monotonic
from typing import Any

from backend.nodes.runtime_support import register_image_bytes
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.camera_usb_uvc_nodes.backend.runtime.capture import (
    encode_frame_bytes,
    get_frame_dimensions,
    read_last_frame,
)
from custom_nodes.camera_usb_uvc_nodes.backend.runtime.payloads import build_camera_session_summary
from custom_nodes.camera_usb_uvc_nodes.backend.runtime.types import (
    UsbCameraBufferedFrame,
    UsbCameraReadWindowConfig,
    UsbCameraSessionEntry,
    UsbCameraSessionReadConfig,
    UsbCameraStartStreamConfig,
)
from custom_nodes.camera_usb_uvc_nodes.backend.runtime.validators import now_isoformat


def start_camera_session_stream(
    entry: UsbCameraSessionEntry,
    *,
    config: UsbCameraStartStreamConfig,
) -> dict[str, object]:
    """启动或重启当前相机会话的后台采流线程。"""

    was_active = is_camera_session_stream_active(entry)
    if was_active and not config.restart_if_active:
        summary = build_camera_session_summary(entry, operation="start_stream")
        summary["started"] = False
        summary["already_active"] = True
        return summary

    if was_active:
        stop_camera_session_stream(entry, clear_buffer=True)

    stop_event = Event()
    thread = Thread(
        target=_camera_session_stream_worker,
        kwargs={
            "entry": entry,
            "stop_event": stop_event,
        },
        daemon=True,
        name=f"usb-camera-stream-{entry.session_handle}",
    )
    with entry.stream_condition:
        entry.stream_buffer_capacity = config.buffer_capacity
        entry.stream_buffer = deque(maxlen=config.buffer_capacity)
        entry.stream_target_fps = config.target_fps
        entry.stream_failure_retry_delay_ms = config.failure_retry_delay_ms
        entry.stream_started_at = now_isoformat()
        entry.stream_started_monotonic = monotonic()
        entry.stream_last_frame_index = None
        entry.stream_last_timestamp_ms = None
        entry.stream_last_error = None
        entry.stream_stop_event = stop_event
        entry.stream_thread = thread
        entry.stream_active = True
        entry.stream_condition.notify_all()
    thread.start()

    summary = build_camera_session_summary(entry, operation="start_stream")
    summary["started"] = True
    summary["already_active"] = False
    summary["restarted"] = was_active
    return summary


def stop_camera_session_stream(
    entry: UsbCameraSessionEntry,
    *,
    clear_buffer: bool,
) -> bool:
    """停止当前相机会话的后台采流线程。"""

    with entry.stream_condition:
        stop_event = entry.stream_stop_event
        thread = entry.stream_thread
        was_active = bool(
            entry.stream_active
            or (thread is not None and thread.is_alive())
            or stop_event is not None
        )
        entry.stream_stop_event = None
        entry.stream_thread = None
        entry.stream_active = False
        entry.stream_condition.notify_all()

    if stop_event is not None:
        stop_event.set()
    if thread is not None and thread.is_alive():
        thread.join(timeout=2.0)

    with entry.stream_condition:
        if clear_buffer:
            entry.stream_buffer.clear()
        entry.stream_condition.notify_all()
    return was_active


def is_camera_session_stream_active(entry: UsbCameraSessionEntry) -> bool:
    """判断当前会话的后台采流线程是否仍处于活动状态。"""

    with entry.stream_condition:
        thread = entry.stream_thread
        stop_event = entry.stream_stop_event
        is_active = bool(
            entry.stream_active
            and thread is not None
            and thread.is_alive()
            and stop_event is not None
            and not stop_event.is_set()
        )
        if not is_active and entry.stream_active:
            entry.stream_active = False
        return is_active


def read_camera_session_latest_frame(
    request: WorkflowNodeExecutionRequest,
    *,
    entry: UsbCameraSessionEntry,
    config: UsbCameraSessionReadConfig,
) -> tuple[Any, int, bool]:
    """优先从流缓冲读取最新一帧；没有缓冲时再直接读 capture。"""

    buffered_frame = get_camera_session_latest_buffered_frame(entry)
    if buffered_frame is not None:
        return buffered_frame.frame, 0, True

    with entry.capture_lock:
        frame, successful_reads = read_last_frame(
            entry.capture,
            warmup_frame_count=config.warmup_frame_count,
            retry_read_count=config.retry_read_count,
            node_id=request.node_id,
            source_details={"session_handle": entry.session_handle},
        )
    return frame, successful_reads, False


def read_camera_session_window(
    request: WorkflowNodeExecutionRequest,
    *,
    entry: UsbCameraSessionEntry,
    config: UsbCameraReadWindowConfig,
    cv2_module: Any,
) -> tuple[dict[str, object], dict[str, object]]:
    """从当前采流缓冲中读取一段 frame-window.v1。"""

    if not is_camera_session_stream_active(entry):
        raise InvalidRequestError(
            "read-window 需要先启动 start-stream",
            details={"node_id": request.node_id, "session_handle": entry.session_handle},
        )

    buffered_frames = wait_for_camera_session_frames(
        entry,
        min_frames=config.wait_for_min_frames,
        timeout_seconds=config.wait_timeout_seconds,
    )
    selected_frames = select_camera_buffered_frames(
        buffered_frames,
        max_frames=config.max_frames,
        sample_mode=config.sample_mode,
    )
    if not selected_frames:
        raise InvalidRequestError(
            "当前相机会话缓冲中没有可读取的视频帧",
            details={"node_id": request.node_id, "session_handle": entry.session_handle},
        )

    frame_items: list[dict[str, object]] = []
    for buffered_frame in selected_frames:
        encoded_frame, media_type = encode_frame_bytes(
            frame=buffered_frame.frame,
            output_format=config.output_format,
            jpeg_quality=config.jpeg_quality,
            cv2_module=cv2_module,
        )
        image_payload = register_image_bytes(
            request,
            content=encoded_frame,
            media_type=media_type,
            width=buffered_frame.width,
            height=buffered_frame.height,
        )
        frame_items.append(
            {
                "frame_index": buffered_frame.frame_index,
                "timestamp_ms": round(float(buffered_frame.timestamp_ms), 4),
                "image": image_payload,
            }
        )

    frame_window_payload = {
        "count": len(frame_items),
        "window_start_index": frame_items[0]["frame_index"],
        "window_end_index": frame_items[-1]["frame_index"],
        "items": frame_items,
    }
    summary = build_camera_session_summary(entry, operation="read_window")
    summary.update(
        {
            "sample_mode": config.sample_mode,
            "count": len(frame_items),
            "wait_for_min_frames": config.wait_for_min_frames,
            "wait_timeout_seconds": round(float(config.wait_timeout_seconds), 4),
            "output_format": config.output_format,
            "frame_indexes": [item["frame_index"] for item in frame_items],
            "timestamp_range_ms": [
                frame_items[0]["timestamp_ms"],
                frame_items[-1]["timestamp_ms"],
            ],
        }
    )
    return frame_window_payload, summary


def get_camera_session_latest_buffered_frame(
    entry: UsbCameraSessionEntry,
) -> UsbCameraBufferedFrame | None:
    """返回缓冲中最新的一帧拷贝。"""

    with entry.stream_condition:
        if not entry.stream_buffer:
            return None
        return _copy_buffered_frame(entry.stream_buffer[-1])


def wait_for_camera_session_frames(
    entry: UsbCameraSessionEntry,
    *,
    min_frames: int,
    timeout_seconds: float,
) -> list[UsbCameraBufferedFrame]:
    """等待缓冲至少达到指定帧数，并返回当前缓冲快照。"""

    deadline = monotonic() + timeout_seconds
    with entry.stream_condition:
        while len(entry.stream_buffer) < min_frames:
            thread = entry.stream_thread
            stop_event = entry.stream_stop_event
            if (
                thread is None
                or not thread.is_alive()
                or stop_event is None
                or stop_event.is_set()
            ):
                break
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            entry.stream_condition.wait(timeout=remaining)

        buffered_frames = [_copy_buffered_frame(item) for item in entry.stream_buffer]

    if len(buffered_frames) < min_frames:
        raise InvalidRequestError(
            "等待相机采流缓冲超时，未能拿到足够帧数",
            details={
                "session_handle": entry.session_handle,
                "required_frame_count": min_frames,
                "available_frame_count": len(buffered_frames),
                "timeout_seconds": round(float(timeout_seconds), 4),
            },
        )
    return buffered_frames


def select_camera_buffered_frames(
    buffered_frames: list[UsbCameraBufferedFrame],
    *,
    max_frames: int,
    sample_mode: str,
) -> list[UsbCameraBufferedFrame]:
    """按指定采样策略从缓冲快照中选出一段帧窗口。"""

    if len(buffered_frames) <= max_frames:
        return buffered_frames
    if sample_mode == "head":
        return buffered_frames[:max_frames]
    if sample_mode == "tail":
        return buffered_frames[-max_frames:]

    if max_frames == 1:
        return [buffered_frames[-1]]

    selected_indices: list[int] = []
    max_index = len(buffered_frames) - 1
    step = max_index / float(max_frames - 1)
    for index in range(max_frames):
        candidate_index = int(round(step * index))
        if selected_indices and candidate_index <= selected_indices[-1]:
            candidate_index = min(max_index, selected_indices[-1] + 1)
        selected_indices.append(candidate_index)
    return [buffered_frames[index] for index in selected_indices]


def update_camera_session_read_state(
    entry: UsbCameraSessionEntry,
    *,
    frame: object,
    successful_reads: int,
) -> tuple[int, int, int]:
    """把一次读帧结果回写到会话条目。"""

    frame_width, frame_height, channels = get_frame_dimensions(frame)
    entry.successful_reads_total += int(successful_reads)
    entry.last_read_at = now_isoformat()
    entry.last_frame_width = frame_width
    entry.last_frame_height = frame_height
    entry.last_frame_channels = channels
    return frame_width, frame_height, channels


def _camera_session_stream_worker(
    *,
    entry: UsbCameraSessionEntry,
    stop_event: Event,
) -> None:
    """后台线程持续从 OpenCV capture 读取图像帧并写入环形缓冲。"""

    target_interval_seconds = (
        1.0 / float(entry.stream_target_fps)
        if entry.stream_target_fps is not None and entry.stream_target_fps > 0
        else None
    )
    retry_delay_seconds = max(0.0, float(entry.stream_failure_retry_delay_ms) / 1000.0)
    try:
        while not stop_event.is_set():
            read_started = monotonic()
            with entry.capture_lock:
                success, frame = entry.capture.read()
            if success is True and frame is not None:
                cloned_frame = _clone_frame(frame)
                frame_width, frame_height, channels = update_camera_session_read_state(
                    entry,
                    frame=cloned_frame,
                    successful_reads=1,
                )
                with entry.stream_condition:
                    started_monotonic = entry.stream_started_monotonic or read_started
                    frame_index = 0 if entry.stream_last_frame_index is None else entry.stream_last_frame_index + 1
                    timestamp_ms = max(0.0, (read_started - started_monotonic) * 1000.0)
                    entry.stream_last_frame_index = frame_index
                    entry.stream_last_timestamp_ms = timestamp_ms
                    entry.stream_last_error = None
                    entry.stream_buffer.append(
                        UsbCameraBufferedFrame(
                            frame_index=frame_index,
                            timestamp_ms=timestamp_ms,
                            frame=cloned_frame,
                            width=frame_width,
                            height=frame_height,
                            channels=channels,
                            captured_at=entry.last_read_at or now_isoformat(),
                        )
                    )
                    entry.stream_condition.notify_all()
                if target_interval_seconds is not None:
                    elapsed_seconds = monotonic() - read_started
                    remaining_seconds = target_interval_seconds - elapsed_seconds
                    if remaining_seconds > 0 and stop_event.wait(remaining_seconds):
                        break
                continue

            with entry.stream_condition:
                entry.stream_last_error = "read_failed"
                entry.stream_condition.notify_all()
            if stop_event.wait(retry_delay_seconds):
                break
    finally:
        with entry.stream_condition:
            if entry.stream_stop_event is stop_event:
                entry.stream_active = False
            entry.stream_condition.notify_all()


def _copy_buffered_frame(buffered_frame: UsbCameraBufferedFrame) -> UsbCameraBufferedFrame:
    """复制缓冲帧，避免把内部可变对象直接暴露到外部调用方。"""

    return UsbCameraBufferedFrame(
        frame_index=buffered_frame.frame_index,
        timestamp_ms=buffered_frame.timestamp_ms,
        frame=_clone_frame(buffered_frame.frame),
        width=buffered_frame.width,
        height=buffered_frame.height,
        channels=buffered_frame.channels,
        captured_at=buffered_frame.captured_at,
    )


def _clone_frame(frame: object) -> object:
    """尽量复制单帧对象，避免底层缓冲复用影响上层。"""

    frame_copy = getattr(frame, "copy", None)
    if callable(frame_copy):
        try:
            return frame_copy()
        except Exception:  # pragma: no cover - 第三方数组实现异常防御
            return frame
    return frame
