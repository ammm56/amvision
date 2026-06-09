"""USB / UVC 相机节点行为测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.nodes import ExecutionImageRegistry
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from custom_nodes.camera_usb_uvc_nodes.backend import support as camera_support
from custom_nodes.camera_usb_uvc_nodes.backend.nodes import (
    capture_frame,
    close_device,
    enumerate_devices,
    get_parameter,
    open_device,
    read_latest_frame,
    set_parameter,
)


class _FakeEncodedImage:
    """模拟 OpenCV imencode 返回值。"""

    def __init__(self, content: bytes) -> None:
        self._content = content

    def tobytes(self) -> bytes:
        """返回编码后的字节。"""

        return self._content


class _FakeCv2Module:
    """最小 fake OpenCV 模块。"""

    CAP_ANY = 0
    CAP_DSHOW = 700
    CAP_MSMF = 1400
    CAP_V4L2 = 200
    CAP_GSTREAMER = 1800
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_FPS = 5
    CAP_PROP_BRIGHTNESS = 10
    CAP_PROP_CONTRAST = 11
    CAP_PROP_SATURATION = 12
    CAP_PROP_HUE = 13
    CAP_PROP_GAIN = 14
    CAP_PROP_EXPOSURE = 15
    CAP_PROP_GAMMA = 16
    CAP_PROP_TEMPERATURE = 17
    CAP_PROP_SHARPNESS = 18
    CAP_PROP_FOCUS = 19
    CAP_PROP_ZOOM = 20
    CAP_PROP_BUFFERSIZE = 21
    CAP_PROP_AUTOFOCUS = 22
    IMWRITE_JPEG_QUALITY = 1

    @staticmethod
    def imencode(extension: str, frame: object, params: list[int] | None = None) -> tuple[bool, _FakeEncodedImage]:
        """返回固定图片头，便于验证输出格式。"""

        if extension == ".jpg":
            return True, _FakeEncodedImage(b"\xff\xd8\xffFAKEJPEG")
        return True, _FakeEncodedImage(b"\x89PNG\r\n\x1a\nFAKEPNG")


class _FakeCapture:
    """模拟 OpenCV VideoCapture。"""

    def __init__(
        self,
        *,
        opened: bool = True,
        frames: list[tuple[bool, object | None]] | None = None,
        backend_name: str = "MSMF",
        initial_width: float = 640.0,
        initial_height: float = 480.0,
        initial_fps: float = 30.0,
    ) -> None:
        self._opened = opened
        self._frames = list(frames or [])
        self._backend_name = backend_name
        self._properties = {
            _FakeCv2Module.CAP_PROP_FRAME_WIDTH: initial_width,
            _FakeCv2Module.CAP_PROP_FRAME_HEIGHT: initial_height,
            _FakeCv2Module.CAP_PROP_FPS: initial_fps,
        }
        self.released = False

    def isOpened(self) -> bool:
        """返回当前句柄是否已打开。"""

        return self._opened

    def release(self) -> None:
        """标记句柄已释放。"""

        self.released = True

    def read(self) -> tuple[bool, object | None]:
        """按预设顺序返回图像帧。"""

        if self._frames:
            return self._frames.pop(0)
        return False, None

    def get(self, property_id: int) -> float:
        """返回当前属性值。"""

        return float(self._properties.get(property_id, 0.0))

    def set(self, property_id: int, value: float) -> bool:
        """记录被设置的属性。"""

        self._properties[property_id] = float(value)
        return True

    def getBackendName(self) -> str:
        """返回当前 backend 名称。"""

        return self._backend_name


class _RuntimeScope:
    """模拟可跨 invoke 复用的 runtime_context。"""


def test_enumerate_devices_node_returns_detected_cameras(monkeypatch) -> None:
    """验证 enumerate-devices 会返回可打开设备的摘要。"""

    frame_a = np.zeros((48, 64, 3), dtype=np.uint8)
    frame_b = np.zeros((24, 32, 3), dtype=np.uint8)
    captures = {
        0: _FakeCapture(frames=[(True, frame_a)]),
        1: _FakeCapture(opened=False),
        2: _FakeCapture(frames=[(True, frame_b)]),
        3: _FakeCapture(opened=False),
    }

    monkeypatch.setattr(camera_support, "require_opencv_imports", lambda: (_FakeCv2Module, np))
    monkeypatch.setattr(
        camera_support,
        "create_video_capture",
        lambda *, source, api_preference: captures.get(int(source), _FakeCapture(opened=False)),
    )

    output = enumerate_devices.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="enumerate-camera-node",
            node_definition=SimpleNamespace(node_type_id=enumerate_devices.NODE_TYPE_ID),
            parameters={
                "start_index": 0,
                "device_count": 2,
                "backend_preference": "any",
                "probe_frame": False,
            },
            input_values={
                "request": {
                    "value": {
                        "device_count": 4,
                        "backend_preference": "dshow",
                        "probe_frame": True,
                    }
                }
            },
        )
    )

    result_value = output["result"]["value"]
    assert result_value["transport"] == "usb-uvc"
    assert result_value["operation"] == "enumerate_devices"
    assert result_value["backend_preference"] == "dshow"
    assert result_value["device_count"] == 4
    assert result_value["found_count"] == 2
    assert [item["device_index"] for item in result_value["items"]] == [0, 2]
    assert result_value["items"][0]["probe_frame_success"] is True
    assert result_value["items"][0]["observed_width"] == 64
    assert result_value["items"][0]["observed_height"] == 48
    assert result_value["items"][1]["channels"] == 3
    assert captures[0].released is True
    assert captures[1].released is True
    assert captures[2].released is True


def test_capture_frame_node_returns_memory_image(monkeypatch) -> None:
    """验证 capture-frame 可以输出 memory image-ref。"""

    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    capture = _FakeCapture(frames=[(True, frame), (True, frame)])
    image_registry = ExecutionImageRegistry()

    monkeypatch.setattr(camera_support, "require_opencv_imports", lambda: (_FakeCv2Module, np))
    monkeypatch.setattr(
        camera_support,
        "create_video_capture",
        lambda *, source, api_preference: capture,
    )

    output = capture_frame.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="capture-camera-node",
            node_definition=SimpleNamespace(node_type_id=capture_frame.NODE_TYPE_ID),
            parameters={
                "device_index": 1,
                "backend_preference": "msmf",
                "width": 320,
                "height": 240,
                "warmup_frame_count": 1,
                "retry_read_count": 1,
                "output_format": "png",
            },
            input_values={},
            execution_metadata={"execution_image_registry": image_registry},
        )
    )

    image_payload = output["image"]
    summary_value = output["summary"]["value"]

    assert image_payload["transport_kind"] == "memory"
    assert image_payload["media_type"] == "image/png"
    assert image_payload["width"] == 320
    assert image_payload["height"] == 240
    assert image_registry.read_bytes(str(image_payload["image_handle"])).startswith(b"\x89PNG\r\n\x1a\n")
    assert summary_value["transport"] == "usb-uvc"
    assert summary_value["operation"] == "capture_frame"
    assert summary_value["device_index"] == 1
    assert summary_value["backend_preference"] == "msmf"
    assert summary_value["frame_width"] == 320
    assert summary_value["frame_height"] == 240
    assert summary_value["transport_kind"] == "memory"
    assert capture.released is True


def test_capture_frame_node_supports_request_override_and_storage_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证 capture-frame 支持 request 覆盖参数并写入目标 object key。"""

    frame = np.zeros((32, 48, 3), dtype=np.uint8)
    capture = _FakeCapture(frames=[(True, frame)])
    dataset_storage = _create_dataset_storage(tmp_path)

    monkeypatch.setattr(camera_support, "require_opencv_imports", lambda: (_FakeCv2Module, np))
    monkeypatch.setattr(
        camera_support,
        "create_video_capture",
        lambda *, source, api_preference: capture,
    )

    output = capture_frame.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="capture-camera-storage-node",
            node_definition=SimpleNamespace(node_type_id=capture_frame.NODE_TYPE_ID),
            parameters={
                "device_index": 0,
                "output_format": "png",
            },
            input_values={
                "request": {
                    "value": {
                        "device_index": 2,
                        "output_format": "jpeg",
                        "output_object_key": "captures/line-a-camera-2.jpg",
                    }
                }
            },
            execution_metadata={"dataset_storage": dataset_storage},
        )
    )

    image_payload = output["image"]
    summary_value = output["summary"]["value"]

    assert image_payload["transport_kind"] == "storage"
    assert image_payload["object_key"] == "captures/line-a-camera-2.jpg"
    assert image_payload["media_type"] == "image/jpeg"
    assert dataset_storage.resolve("captures/line-a-camera-2.jpg").read_bytes().startswith(b"\xff\xd8\xff")
    assert summary_value["device_index"] == 2
    assert summary_value["output_format"] == "jpeg"
    assert summary_value["transport_kind"] == "storage"
    assert summary_value["output_object_key"] == "captures/line-a-camera-2.jpg"
    assert capture.released is True


def test_capture_frame_node_raises_when_camera_cannot_open(monkeypatch) -> None:
    """验证 capture-frame 在相机无法打开时返回明确错误。"""

    monkeypatch.setattr(camera_support, "require_opencv_imports", lambda: (_FakeCv2Module, np))
    monkeypatch.setattr(
        camera_support,
        "create_video_capture",
        lambda *, source, api_preference: _FakeCapture(opened=False),
    )

    with pytest.raises(InvalidRequestError, match="无法打开指定 USB / UVC 相机"):
        capture_frame.handle_node(
            WorkflowNodeExecutionRequest(
                node_id="capture-camera-failed-node",
                node_definition=SimpleNamespace(node_type_id=capture_frame.NODE_TYPE_ID),
                parameters={"device_index": 0},
                input_values={},
            )
        )


def test_usb_camera_session_nodes_reuse_runtime_scoped_session(monkeypatch) -> None:
    """验证 open/read/get/set/close 可以复用同一 runtime_context 中的会话。"""

    frame = np.zeros((72, 96, 3), dtype=np.uint8)
    capture = _FakeCapture(
        frames=[(True, frame), (True, frame), (True, frame)],
        backend_name="DSHOW",
    )
    runtime_scope = _RuntimeScope()
    created_sources: list[tuple[int | str, int]] = []

    monkeypatch.setattr(camera_support, "require_opencv_imports", lambda: (_FakeCv2Module, np))

    def _create_capture(*, source, api_preference):
        created_sources.append((source, api_preference))
        return capture

    monkeypatch.setattr(camera_support, "create_video_capture", _create_capture)

    open_output = open_device.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="open-camera-node",
            node_definition=SimpleNamespace(node_type_id=open_device.NODE_TYPE_ID),
            parameters={
                "device_index": 3,
                "backend_preference": "dshow",
                "width": 640,
                "height": 360,
                "fps": 25.0,
                "probe_frame": False,
            },
            input_values={},
            runtime_context=runtime_scope,
        )
    )
    opened_session = open_output["session"]

    set_output = set_parameter.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="set-camera-parameter-node",
            node_definition=SimpleNamespace(node_type_id=set_parameter.NODE_TYPE_ID),
            parameters={
                "parameter_values": {
                    "width": 800,
                    "height": 600,
                    "fps": 20.0,
                }
            },
            input_values={"session": opened_session},
            runtime_context=runtime_scope,
        )
    )
    updated_session = set_output["session"]
    set_result = set_output["result"]["value"]

    get_output = get_parameter.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="get-camera-parameter-node",
            node_definition=SimpleNamespace(node_type_id=get_parameter.NODE_TYPE_ID),
            parameters={
                "parameter_names": ["width", "height", "fps", "backend_name", "requested_width"]
            },
            input_values={"session": updated_session},
            runtime_context=runtime_scope,
        )
    )
    get_result = get_output["result"]["value"]

    image_registry = ExecutionImageRegistry()
    read_output = read_latest_frame.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="read-camera-frame-node",
            node_definition=SimpleNamespace(node_type_id=read_latest_frame.NODE_TYPE_ID),
            parameters={
                "warmup_frame_count": 0,
                "retry_read_count": 1,
                "output_format": "png",
            },
            input_values={"session": updated_session},
            execution_metadata={"execution_image_registry": image_registry},
            runtime_context=runtime_scope,
        )
    )
    read_session = read_output["session"]
    read_summary = read_output["summary"]["value"]

    close_output = close_device.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="close-camera-node",
            node_definition=SimpleNamespace(node_type_id=close_device.NODE_TYPE_ID),
            parameters={},
            input_values={"session": read_session},
            runtime_context=runtime_scope,
        )
    )
    close_result = close_output["result"]["value"]

    assert created_sources == [(3, _FakeCv2Module.CAP_DSHOW)]
    assert opened_session["session_handle"].startswith("usb-camera-session-")
    assert opened_session["device_index"] == 3
    assert opened_session["requested_width"] == 640
    assert set_result["requested_values"] == {"width": 800, "height": 600, "fps": 20.0}
    assert set_result["observed_values"] == {"width": 800, "height": 600, "fps": 20.0}
    assert updated_session["requested_width"] == 800
    assert updated_session["requested_height"] == 600
    assert updated_session["requested_fps"] == 20.0
    assert get_result["values"]["width"] == 800
    assert get_result["values"]["height"] == 600
    assert get_result["values"]["fps"] == 20.0
    assert get_result["values"]["backend_name"] == "DSHOW"
    assert get_result["values"]["requested_width"] == 800
    assert read_output["image"]["transport_kind"] == "memory"
    assert image_registry.read_bytes(str(read_output["image"]["image_handle"])).startswith(b"\x89PNG\r\n\x1a\n")
    assert read_summary["frame_width"] == 96
    assert read_summary["frame_height"] == 72
    assert read_summary["successful_reads_total"] == 1
    assert read_session["successful_reads_total"] == 1
    assert close_result["closed"] is True
    assert close_result["session_handle"] == opened_session["session_handle"]
    assert capture.released is True


def test_usb_camera_session_nodes_support_execution_scoped_registry(monkeypatch) -> None:
    """验证没有 runtime_context 时，也能在同一 execution_metadata 内复用会话。"""

    frame = np.zeros((40, 50, 3), dtype=np.uint8)
    capture = _FakeCapture(frames=[(True, frame)])
    execution_metadata: dict[str, object] = {"execution_image_registry": ExecutionImageRegistry()}

    monkeypatch.setattr(camera_support, "require_opencv_imports", lambda: (_FakeCv2Module, np))
    monkeypatch.setattr(camera_support, "create_video_capture", lambda *, source, api_preference: capture)

    opened_session = open_device.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="open-camera-execution-scope-node",
            node_definition=SimpleNamespace(node_type_id=open_device.NODE_TYPE_ID),
            parameters={"device_index": 0, "probe_frame": False},
            input_values={},
            execution_metadata=execution_metadata,
        )
    )["session"]

    read_output = read_latest_frame.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="read-camera-execution-scope-node",
            node_definition=SimpleNamespace(node_type_id=read_latest_frame.NODE_TYPE_ID),
            parameters={"retry_read_count": 1},
            input_values={"session": opened_session},
            execution_metadata=execution_metadata,
        )
    )

    close_output = close_device.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="close-camera-execution-scope-node",
            node_definition=SimpleNamespace(node_type_id=close_device.NODE_TYPE_ID),
            parameters={},
            input_values={"session": read_output["session"]},
            execution_metadata=execution_metadata,
        )
    )

    assert read_output["summary"]["value"]["successful_reads_total"] == 1
    assert close_output["result"]["value"]["closed"] is True
    assert capture.released is True


def test_read_latest_frame_raises_after_session_closed(monkeypatch) -> None:
    """验证相机会话关闭后再次读帧会返回明确错误。"""

    capture = _FakeCapture()
    runtime_scope = _RuntimeScope()

    monkeypatch.setattr(camera_support, "require_opencv_imports", lambda: (_FakeCv2Module, np))
    monkeypatch.setattr(camera_support, "create_video_capture", lambda *, source, api_preference: capture)

    opened_session = open_device.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="open-camera-close-then-read-node",
            node_definition=SimpleNamespace(node_type_id=open_device.NODE_TYPE_ID),
            parameters={"device_index": 1, "probe_frame": False},
            input_values={},
            runtime_context=runtime_scope,
        )
    )["session"]
    close_device.handle_node(
        WorkflowNodeExecutionRequest(
            node_id="close-camera-before-read-node",
            node_definition=SimpleNamespace(node_type_id=close_device.NODE_TYPE_ID),
            parameters={},
            input_values={"session": opened_session},
            runtime_context=runtime_scope,
        )
    )

    with pytest.raises(InvalidRequestError, match="相机会话不存在或已关闭"):
        read_latest_frame.handle_node(
            WorkflowNodeExecutionRequest(
                node_id="read-camera-after-close-node",
                node_definition=SimpleNamespace(node_type_id=read_latest_frame.NODE_TYPE_ID),
                parameters={"retry_read_count": 1},
                input_values={"session": opened_session},
                runtime_context=runtime_scope,
            )
        )


def _create_dataset_storage(tmp_path: Path) -> LocalDatasetStorage:
    """创建测试使用的本地对象存储。"""

    return LocalDatasetStorage(
        DatasetStorageSettings(
            root_dir=str(tmp_path / "storage"),
        )
    )
