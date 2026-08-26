"""模型 predictor 对零拷贝图片 buffer 的兼容性测试。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from backend.contracts.buffers import BufferLease, BufferRef
from backend.service.application.local_buffers import (
    DirectMmapLocalBufferReader,
    DirectMmapLocalBufferWriter,
    LocalBufferBrokerSettings,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.local_buffers.local_buffer_arena_pool import (
    LocalBufferArenaPool,
)
from backend.service.infrastructure.local_buffers.mmap_buffer_arena import (
    MmapBufferArenaConfig,
)
from backend.nodes.runtime_support import (
    ExecutionImageRegistry,
    build_memory_image_payload,
    load_image_bytes,
    load_image_content,
)
from backend.service.application.runtime.deployment.deployment_process_worker import (
    _LocalBufferBrokerRuntimeHealth,
    _RoutedLocalBufferAccess,
    _build_prediction_request,
)
from backend.service.application.runtime.tasks.task_prediction_runtime import (
    deserialize_prediction_execution_result,
)
from backend.service.application.runtime.predictors.common.yolo_runtime_io import (
    load_yolo_runtime_prediction_image,
)
from backend.service.application.runtime.predictors.yolo26.classification.io import (
    load_yolo26_classification_prediction_image,
)
from backend.service.application.runtime.predictors.yolov8.detection.io import (
    load_yolov8_detection_prediction_image,
)
from backend.service.application.runtime.predictors.yolox.io import (
    load_yolox_prediction_image,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


@pytest.mark.parametrize(
    "loader",
    (
        load_yolo_runtime_prediction_image,
        load_yolox_prediction_image,
        load_yolov8_detection_prediction_image,
        load_yolo26_classification_prediction_image,
    ),
)
def test_prediction_image_loaders_accept_raw_memoryview(
    tmp_path: Path,
    loader,
) -> None:
    """验证所有现行 YOLO predictor 都接受 daemon mmap 返回的 memoryview。"""

    source = np.arange(18, dtype=np.uint8).reshape((2, 3, 3))
    request = SimpleNamespace(
        input_uri=None,
        input_image_bytes=memoryview(source).cast("B").toreadonly(),
        input_image_payload={
            "transport_kind": "buffer",
            "media_type": "image/raw",
            "shape": [2, 3, 3],
            "dtype": "uint8",
            "layout": "HWC",
            "pixel_format": "bgr24",
            "width": 3,
            "height": 2,
        },
    )
    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "objects"))
    )

    image = loader(
        cv2_module=cv2,
        np_module=np,
        dataset_storage=storage,
        request=request,
    )

    assert image.shape == (2, 3, 3)
    assert np.array_equal(image, source)


def test_prediction_image_loader_accepts_bytearray(tmp_path: Path) -> None:
    """验证通用 predictor 同时接受标准可变 bytes-like 输入。"""

    image = np.full((3, 4, 3), 127, dtype=np.uint8)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    request = SimpleNamespace(
        input_uri=None,
        input_image_bytes=bytearray(encoded.tobytes()),
        input_image_payload={
            "transport_kind": "memory",
            "media_type": "image/png",
        },
    )
    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "objects"))
    )

    decoded = load_yolo_runtime_prediction_image(
        cv2_module=cv2,
        np_module=np,
        dataset_storage=storage,
        request=request,
    )

    assert decoded.shape == image.shape
    assert np.array_equal(decoded, image)


def test_custom_model_image_content_borrows_encoded_buffer_view() -> None:
    """验证 YOLOE/SAM3 共用入口对编码图片也直接借用 mmap view。"""

    encoded = bytearray(b"encoded-image-content")
    reader = _BorrowedViewReader(encoded)
    request = SimpleNamespace(
        node_id="custom-model-node",
        input_values={
            "image": {
                "transport_kind": "buffer",
                "media_type": "image/png",
                "buffer_ref": _buffer_ref_payload(
                    content_length=len(encoded),
                    media_type="image/png",
                ),
            }
        },
        execution_metadata={"local_buffer_reader": reader},
    )

    payload, content = load_image_content(request)

    assert payload["transport_kind"] == "buffer"
    assert isinstance(content, memoryview)
    assert content.readonly is True
    assert content.tobytes() == bytes(encoded)
    assert reader.copied_read_count == 0


def test_image_bytes_helper_keeps_explicit_bytes_contract() -> None:
    """验证 bytes helper 显式复制 reader 返回的 view。"""

    encoded = bytearray(b"encoded-image-content")
    reader = _MemoryviewCopyReader(encoded)
    request = SimpleNamespace(
        node_id="bytes-image-node",
        input_values={
            "image": {
                "transport_kind": "buffer",
                "media_type": "image/png",
                "buffer_ref": _buffer_ref_payload(
                    content_length=len(encoded),
                    media_type="image/png",
                ),
            }
        },
        execution_metadata={"local_buffer_reader": reader},
    )

    _payload, content = load_image_bytes(request)

    assert isinstance(content, bytes)
    assert content == bytes(encoded)


def test_memory_raw_image_content_borrows_registry_matrix() -> None:
    """验证相机/OpenCV raw memory image 不先复制成 bytes 再写 broker。"""

    matrix = np.arange(36, dtype=np.uint8).reshape((3, 4, 3))
    registry = ExecutionImageRegistry()
    entry = registry.register_image_matrix(
        matrix=matrix,
        width=4,
        height=3,
        created_by_node_id="camera-node",
    )
    request = SimpleNamespace(
        node_id="model-node",
        input_values={
            "image": build_memory_image_payload(
                image_handle=entry.image_handle,
                media_type="image/raw",
                width=4,
                height=3,
                shape=(3, 4, 3),
                dtype="uint8",
                layout="HWC",
                pixel_format="bgr24",
            )
        },
        execution_metadata={"execution_image_registry": registry},
    )

    _payload, content = load_image_content(request)

    assert isinstance(content, memoryview)
    assert content.readonly is True
    assert np.shares_memory(np.frombuffer(content, dtype=np.uint8), matrix)


@pytest.mark.parametrize(
    "task_type,task_options",
    (
        ("detection", {"score_threshold": 0.3}),
        ("classification", {"top_k": 1}),
        (
            "segmentation",
            {"score_threshold": 0.3, "mask_threshold": 0.5},
        ),
        (
            "pose",
            {
                "score_threshold": 0.3,
                "keypoint_confidence_threshold": 0.3,
            },
        ),
        ("obb", {"score_threshold": 0.3}),
    ),
)
def test_deployment_worker_preserves_mmap_view_for_every_task(
    task_type: str,
    task_options: dict[str, object],
) -> None:
    """验证五类核心模型节点经 daemon worker 后仍保留零拷贝 view。"""

    content = bytearray(range(18))
    reader = _DirectReader(content)
    with _build_prediction_request(
        payload={
            "task_type": task_type,
            "prediction_request": {
                "save_result_image": False,
                "input_uri": None,
                "input_image_payload": {
                    "transport_kind": "buffer",
                    "media_type": "image/raw",
                    "width": 3,
                    "height": 2,
                    "shape": [2, 3, 3],
                    "dtype": "uint8",
                    "layout": "HWC",
                    "pixel_format": "bgr24",
                    "buffer_ref": _buffer_ref_payload(
                        content_length=len(content),
                        media_type="image/raw",
                        shape=(2, 3, 3),
                        dtype="uint8",
                        layout="HWC",
                        pixel_format="BGR24",
                    ),
                },
                "extra_options": {},
                **task_options,
            },
        },
        local_buffer_reader=reader,
        local_buffer_health=_LocalBufferBrokerRuntimeHealth(
            connected=True,
            channel_id="direct-readonly-mmap",
        ),
    ) as prediction_request:
        assert prediction_request.input_uri is None
        assert isinstance(prediction_request.input_image_bytes, memoryview)
        assert prediction_request.input_image_bytes.tobytes() == bytes(content)
        assert prediction_request.input_image_payload["transport_kind"] == "buffer"


def test_deployment_worker_rejects_non_localbuffer_image_reference(
    tmp_path: Path,
) -> None:
    """验证 deployment worker 不保留 storage/local-path 图片旁路。"""

    source_path = tmp_path / "现场图片" / "治具空盘.bmp"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"bmp-image-bytes")

    with pytest.raises(InvalidRequestError, match="不支持的 image-ref"):
        with _build_prediction_request(
            payload={
                "task_type": "classification",
                "prediction_request": {
                    "save_result_image": False,
                    "input_uri": None,
                    "input_image_payload": {
                        "transport_kind": "local-path",
                        "local_path": str(source_path),
                        "media_type": "image/bmp",
                    },
                    "top_k": 1,
                    "extra_options": {},
                },
            },
            local_buffer_reader=None,
            local_buffer_health=_LocalBufferBrokerRuntimeHealth(
                connected=False,
                channel_id=None,
            ),
        ):
            pass


def test_prediction_ipc_rejects_removed_base64_image_fields() -> None:
    """验证当前 IPC 契约不会重新接受已删除的图片 Base64 旁路。"""

    with pytest.raises(InvalidRequestError, match="不支持图片 Base64"):
        with _build_prediction_request(
            payload={
                "task_type": "detection",
                "prediction_request": {
                    "input_image_bytes_base64": "aW1hZ2U=",
                    "score_threshold": 0.3,
                    "save_result_image": False,
                    "extra_options": {},
                },
            },
            local_buffer_reader=None,
            local_buffer_health=_LocalBufferBrokerRuntimeHealth(
                connected=True,
                channel_id="direct-readonly-mmap",
            ),
        ):
            pass

    with pytest.raises(InvalidRequestError, match="不支持结果图片 Base64"):
        deserialize_prediction_execution_result(
            task_type="detection",
            payload={
                "detections": [],
                "latency_ms": 1.0,
                "image_width": 1,
                "image_height": 1,
                "preview_image_bytes_base64": "aW1hZ2U=",
                "runtime_session_info": {},
            },
        )


def test_deployment_worker_routes_backend_and_daemon_local_buffers(
    tmp_path: Path,
) -> None:
    """验证 worker 按 arena id 路由主 Broker 与 daemon 私有 Broker。"""

    settings = LocalBufferBrokerSettings(
        root_dir=str(tmp_path / "backend-buffers"),
        arena_size_bytes=16 * 1024 * 1024,
        min_block_size_bytes=1024 * 1024,
        max_allocation_bytes=8 * 1024 * 1024,
        reader_guard_slots=4,
    )
    pool = LocalBufferArenaPool(
        MmapBufferArenaConfig(
            root_dir=Path(settings.root_dir),
            arena_id=settings.arena_id,
            arena_size_bytes=settings.arena_size_bytes,
            min_block_size_bytes=settings.min_block_size_bytes,
            max_allocation_bytes=settings.max_allocation_bytes,
            reader_guard_slots=settings.reader_guard_slots,
        )
    )
    active_lease = pool.allocate(
        content_length=7,
        owner_kind="workflow-runtime",
        owner_id="run-1",
    )
    pool.write_lease_bytes(lease=active_lease, content=memoryview(b"backend"))
    backend_result = pool.commit_lease(
        lease=active_lease,
        media_type="image/png",
    )
    writing_lease = pool.allocate(
        content_length=7,
        owner_kind="deployment-preview",
        owner_id="request-1",
    )
    broker = _PrivateBufferBroker()
    access = _RoutedLocalBufferAccess(
        broker_client=broker,
        direct_reader=DirectMmapLocalBufferReader(settings),
        direct_writer=DirectMmapLocalBufferWriter(settings),
    )
    daemon_ref = backend_result.buffer_ref.model_copy(
        update={
            "buffer_id": "daemon-buffer",
            "lease_id": "daemon-lease",
            "arena_id": "inference-daemon-private",
            "broker_epoch": "2" * 32,
        }
    )
    daemon_lease = writing_lease.model_copy(
        update={
            "lease_id": "daemon-lease",
            "buffer_id": "daemon-buffer",
            "arena_id": "inference-daemon-private",
            "broker_epoch": "2" * 32,
        }
    )

    try:
        assert bytes(access.read_buffer_ref(backend_result.buffer_ref)) == b"backend"
        assert access.read_buffer_ref(daemon_ref) == b"daemon"
        access.write_lease_bytes(lease=writing_lease, content=b"updated")
        access.write_lease_bytes(lease=daemon_lease, content=b"preview")
        with pytest.raises(InvalidRequestError):
            access.write_lease_bytes(
                lease=writing_lease.model_copy(
                    update={
                        "offset": (
                            writing_lease.offset
                            + writing_lease.allocation_capacity_bytes
                        )
                    }
                ),
                content=b"outside",
            )

        committed = pool.commit_lease(
            lease=writing_lease,
            media_type="image/png",
        )
        assert pool.read_buffer_ref(committed.buffer_ref) == b"updated"
        assert broker.read_count == 1
        assert broker.writes == [("daemon-lease", b"preview")]
    finally:
        access.close()
        pool.close()


def _buffer_ref_payload(
    *,
    content_length: int,
    media_type: str,
    shape: tuple[int, ...] = (),
    dtype: str | None = None,
    layout: str | None = None,
    pixel_format: str | None = None,
) -> dict[str, object]:
    """构造不暴露文件路径的当前 BufferRef.v1 测试载荷。"""

    return BufferRef(
        buffer_id="local-buffer-main:0",
        lease_id="lease-1",
        arena_id="local-buffer-main",
        descriptor_index=0,
        descriptor_generation=1,
        broker_epoch="1" * 32,
        offset=0,
        content_length=content_length,
        allocation_capacity_bytes=max(content_length, 1024 * 1024),
        shape=shape,
        dtype=dtype,
        layout=layout,
        pixel_format=pixel_format,
        media_type=media_type,
        readonly=True,
    ).model_dump(mode="json")


class _BorrowedViewReader:
    """只允许 borrowed view 读取的测试 reader。"""

    def __init__(self, content: bytearray) -> None:
        """保存测试内容并初始化复制读取计数。"""

        self.content = content
        self.copied_read_count = 0

    def read_buffer_ref_view(self, _buffer_ref) -> memoryview:
        """返回只读共享视图。"""

        return memoryview(self.content).toreadonly()

    def read_buffer_ref(self, _buffer_ref) -> bytes:
        """记录不应发生的复制读取。"""

        self.copied_read_count += 1
        return bytes(self.content)

    def read_frame_ref(self, _frame_ref) -> bytes:
        """提供运行时上下文要求的 FrameRef 读取接口。"""

        return bytes(self.content)


class _PrivateBufferBroker:
    """模拟 daemon 私有 LocalBufferBroker client。"""

    def __init__(self) -> None:
        """初始化调用记录。"""

        self.channel = SimpleNamespace(channel_id="daemon-private-channel")
        self.read_count = 0
        self.writes: list[tuple[str, bytes]] = []

    def read_buffer_ref(self, _buffer_ref: BufferRef) -> bytes:
        """返回私有池图片。"""

        self.read_count += 1
        return b"daemon"

    def read_frame_ref(self, _frame_ref) -> bytes:
        """返回私有池帧。"""

        self.read_count += 1
        return b"daemon-frame"

    def write_lease_bytes(
        self,
        *,
        lease: BufferLease,
        content: bytes | bytearray | memoryview,
    ) -> None:
        """记录私有池结果写入。"""

        self.writes.append((lease.lease_id, bytes(content)))

    def get_health_summary(self) -> dict[str, object]:
        """返回测试健康摘要。"""

        return {"connected": True, "channel_id": self.channel.channel_id}

    def close(self) -> None:
        """关闭测试 client。"""


class _DirectReader:
    """模拟 inference daemon deployment worker 的 direct mmap reader。"""

    def __init__(self, content: bytearray) -> None:
        """保存 worker 应借用的共享内容。"""

        self.content = content

    def read_buffer_ref(self, _buffer_ref) -> memoryview:
        """返回零拷贝只读图片 view。"""

        return memoryview(self.content).toreadonly()

    def read_frame_ref(self, _frame_ref) -> memoryview:
        """返回零拷贝只读帧 view。"""

        return memoryview(self.content).toreadonly()

    @contextmanager
    def acquire_buffer_ref_view(self, _buffer_ref):
        """让测试 view 生命周期覆盖完整预测调用。"""

        view = memoryview(self.content).toreadonly()
        try:
            yield view
        finally:
            view.release()

    @contextmanager
    def acquire_frame_ref_view(self, _frame_ref):
        """让测试 frame view 生命周期覆盖完整预测调用。"""

        view = memoryview(self.content).toreadonly()
        try:
            yield view
        finally:
            view.release()


class _MemoryviewCopyReader:
    """模拟旧读取 API 收到 memoryview 的兼容场景。"""

    def __init__(self, content: bytearray) -> None:
        """保存测试内容。"""

        self.content = content

    def read_buffer_ref(self, _buffer_ref) -> memoryview:
        """返回只读共享视图。"""

        return memoryview(self.content).toreadonly()

    def read_frame_ref(self, _frame_ref) -> memoryview:
        """返回只读共享帧视图。"""

        return memoryview(self.content).toreadonly()
