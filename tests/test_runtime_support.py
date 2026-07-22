"""runtime_support 多来源图片 helper 测试。"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import gc
from pathlib import Path
from threading import Event, Lock
import weakref

import pytest

import backend.nodes.runtime_support as runtime_support
from backend.nodes.runtime_support import (
    ExecutionImageRegistry,
    IMAGE_TRANSPORT_MEMORY,
    IMAGE_TRANSPORT_STORAGE,
    build_preview_response_image_payload,
    build_response_image_payload,
    build_memory_image_payload,
    build_storage_image_payload,
    copy_image_payload,
    load_image_bytes,
    load_image_matrix,
    register_image_bytes,
    register_image_matrix,
    require_image_payload,
    resolve_image_reference,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_require_image_payload_accepts_storage_payload_and_backfills_transport_kind() -> None:
    """验证 storage 模式 payload 仍兼容旧 object_key 写法。"""

    payload = require_image_payload({"object_key": "inputs/demo.png"})

    assert payload["transport_kind"] == IMAGE_TRANSPORT_STORAGE
    assert payload["object_key"] == "inputs/demo.png"
    assert payload["media_type"] == "image/png"


def test_require_image_payload_accepts_memory_payload() -> None:
    """验证 memory 模式 payload 会保留 image_handle。"""

    payload = require_image_payload(
        {
            "transport_kind": "memory",
            "image_handle": "img-1",
            "media_type": "image/png",
            "width": 64,
            "height": 32,
        }
    )

    assert payload["transport_kind"] == IMAGE_TRANSPORT_MEMORY
    assert payload["image_handle"] == "img-1"
    assert payload["width"] == 64
    assert payload["height"] == 32


def test_execution_image_registry_registers_reads_and_releases_bytes() -> None:
    """验证 execution image registry 可以管理单次执行中的图片字节。"""

    registry = ExecutionImageRegistry()
    entry = registry.register_image_bytes(
        content=b"png-bytes",
        media_type="image/png",
        width=10,
        height=20,
        created_by_node_id="decode",
    )

    assert entry.byte_length == len(b"png-bytes")
    assert registry.read_bytes(entry.image_handle) == b"png-bytes"

    registry.release(entry.image_handle)

    with pytest.raises(InvalidRequestError, match="图片句柄"):
        registry.read_bytes(entry.image_handle)


def test_register_image_matrix_keeps_raw_bgr24_in_memory_and_encodes_only_for_response(tmp_path: Path) -> None:
    """验证 raw BGR24 图片在节点内存中流转，对外响应时才编码为 JSON 安全图片。"""

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "files")))
    registry = ExecutionImageRegistry()
    request = _build_request(
        dataset_storage=dataset_storage,
        image_registry=registry,
        payload={"object_key": "inputs/source.png"},
    )
    image_matrix = np.zeros((2, 3, 3), dtype=np.uint8)
    image_matrix[:, :, 0] = 11
    image_matrix[:, :, 1] = 22
    image_matrix[:, :, 2] = 33

    memory_payload = register_image_matrix(request, image_matrix=image_matrix)
    request.input_values["image"] = memory_payload
    loaded_payload, loaded_matrix = load_image_matrix(
        request,
        cv2_module=cv2,
        np_module=np,
    )
    response_image = build_response_image_payload(request, image_payload=memory_payload)

    assert memory_payload["transport_kind"] == IMAGE_TRANSPORT_MEMORY
    assert memory_payload["media_type"] == "image/raw"
    assert memory_payload["shape"] == [2, 3, 3]
    assert memory_payload["dtype"] == "uint8"
    assert memory_payload["layout"] == "HWC"
    assert memory_payload["pixel_format"] == "bgr24"
    assert loaded_payload["media_type"] == "image/raw"
    assert np.array_equal(loaded_matrix, image_matrix)
    assert response_image["transport_kind"] == "inline-base64"
    assert response_image["media_type"] == "image/jpeg"
    assert base64.b64decode(response_image["image_base64"]).startswith(b"\xff\xd8\xff")
    assert response_image["width"] == 3
    assert response_image["height"] == 2
    assert "shape" not in response_image


def test_load_image_bytes_supports_storage_and_memory_modes(tmp_path: Path) -> None:
    """验证 load_image_bytes 可以统一读取 storage 与 memory 两种图片来源。"""

    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "files")))
    dataset_storage.write_bytes("inputs/source.png", b"storage-png")
    registry = ExecutionImageRegistry()
    memory_entry = registry.register_image_bytes(
        content=b"memory-png",
        media_type="image/png",
        width=8,
        height=8,
        created_by_node_id="decode",
    )

    storage_request = _build_request(
        dataset_storage=dataset_storage,
        image_registry=registry,
        payload={"object_key": "inputs/source.png"},
    )
    memory_request = _build_request(
        dataset_storage=dataset_storage,
        image_registry=registry,
        payload=build_memory_image_payload(
            image_handle=memory_entry.image_handle,
            media_type=memory_entry.media_type,
            width=memory_entry.width,
            height=memory_entry.height,
        ),
    )

    storage_payload, storage_bytes = load_image_bytes(storage_request)
    memory_payload, memory_bytes = load_image_bytes(memory_request)

    assert storage_payload["transport_kind"] == IMAGE_TRANSPORT_STORAGE
    assert storage_bytes == b"storage-png"
    assert memory_payload["transport_kind"] == IMAGE_TRANSPORT_MEMORY
    assert memory_bytes == b"memory-png"


def test_load_image_matrix_reuses_decoded_storage_image_within_one_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证多个节点读取同一张大图时只执行一次 bytes 解码。"""

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "files")))
    registry = ExecutionImageRegistry()
    image_matrix = np.full((24, 32, 3), 127, dtype=np.uint8)
    encoded, encoded_matrix = cv2.imencode(".png", image_matrix)
    assert encoded is True
    dataset_storage.write_bytes("inputs/source.png", encoded_matrix.tobytes())
    request = _build_request(
        dataset_storage=dataset_storage,
        image_registry=registry,
        payload={"object_key": "inputs/source.png", "media_type": "image/png"},
    )
    decode_count = 0
    original_decoder = runtime_support.decode_image_bytes_to_matrix

    def counting_decoder(**kwargs):
        """记录底层解码次数。"""

        nonlocal decode_count
        decode_count += 1
        return original_decoder(**kwargs)

    monkeypatch.setattr(runtime_support, "decode_image_bytes_to_matrix", counting_decoder)

    _, first_matrix = load_image_matrix(request, cv2_module=cv2, np_module=np)
    _, second_matrix = load_image_matrix(request, cv2_module=cv2, np_module=np)

    assert decode_count == 1
    assert first_matrix is second_matrix
    assert np.array_equal(first_matrix, image_matrix)
    assert first_matrix.flags.writeable is False
    assert registry.decoded_cache_entry_count == 1
    assert registry.decoded_cache_total_bytes == image_matrix.nbytes


def test_load_image_matrix_copy_raw_does_not_expose_cached_matrix(tmp_path: Path) -> None:
    """验证要求可写副本时不会让节点修改执行期共享解码缓存。"""

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "files")))
    registry = ExecutionImageRegistry()
    image_matrix = np.full((8, 10, 3), 64, dtype=np.uint8)
    encoded, encoded_matrix = cv2.imencode(".png", image_matrix)
    assert encoded is True
    dataset_storage.write_bytes("inputs/source.png", encoded_matrix.tobytes())
    request = _build_request(
        dataset_storage=dataset_storage,
        image_registry=registry,
        payload={"object_key": "inputs/source.png", "media_type": "image/png"},
    )

    _, shared_matrix = load_image_matrix(request, cv2_module=cv2, np_module=np)
    _, copied_matrix = load_image_matrix(
        request,
        cv2_module=cv2,
        np_module=np,
        copy_raw=True,
    )
    copied_matrix[0, 0] = 0

    assert copied_matrix is not shared_matrix
    assert copied_matrix.flags.writeable is True
    assert np.array_equal(shared_matrix, image_matrix)


def test_execution_image_registry_single_flight_decodes_once_for_parallel_readers() -> None:
    """验证并行分支同时读取同一输入时只允许一个 decoder 执行。"""

    np = pytest.importorskip("numpy")
    registry = ExecutionImageRegistry()
    decoder_started = Event()
    allow_decoder_finish = Event()
    counter_lock = Lock()
    decode_count = 0
    expected_matrix = np.full((16, 20, 3), 33, dtype=np.uint8)

    def decoder():
        """阻塞首个 decoder，使其他线程进入同一 flight。"""

        nonlocal decode_count
        with counter_lock:
            decode_count += 1
        decoder_started.set()
        assert allow_decoder_finish.wait(timeout=2.0)
        return expected_matrix

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(registry.get_or_decode_matrix, cache_key="same-image", decoder=decoder)
            for _ in range(4)
        ]
        assert decoder_started.wait(timeout=2.0)
        allow_decoder_finish.set()
        matrices = [future.result(timeout=2.0) for future in futures]

    assert decode_count == 1
    assert all(matrix is expected_matrix for matrix in matrices)
    assert expected_matrix.flags.writeable is False


def test_execution_image_registry_bounds_lru_cache_and_releases_matrices() -> None:
    """验证解码缓存按条目和字节软上限回收，clear 后立即断开矩阵引用。"""

    np = pytest.importorskip("numpy")
    registry = ExecutionImageRegistry(decoded_cache_max_entries=2, decoded_cache_max_bytes=24)

    first = registry.get_or_decode_matrix(
        cache_key="first",
        decoder=lambda: np.zeros((2, 2, 3), dtype=np.uint8),
    )
    registry.get_or_decode_matrix(
        cache_key="second",
        decoder=lambda: np.ones((2, 2, 3), dtype=np.uint8),
    )
    registry.get_or_decode_matrix(
        cache_key="third",
        decoder=lambda: np.full((2, 2, 3), 2, dtype=np.uint8),
    )

    assert registry.decoded_cache_entry_count == 2
    assert registry.decoded_cache_total_bytes == 24
    first_again = registry.get_or_decode_matrix(
        cache_key="first",
        decoder=lambda: np.full((2, 2, 3), 9, dtype=np.uint8),
    )
    assert first_again is not first
    assert int(first_again[0, 0, 0]) == 9

    registry.clear_decoded_matrices()

    assert registry.decoded_cache_entry_count == 0
    assert registry.decoded_cache_total_bytes == 0


def test_execution_image_registry_clear_releases_last_matrix_reference() -> None:
    """验证 clear 会真正断开 registry 对大矩阵的强引用。"""

    np = pytest.importorskip("numpy")
    registry = ExecutionImageRegistry()
    matrix = registry.get_or_decode_matrix(
        cache_key="large-image",
        decoder=lambda: np.zeros((128, 128, 3), dtype=np.uint8),
    )
    matrix_reference = weakref.ref(matrix)

    registry.clear_decoded_matrices()
    del matrix
    gc.collect()

    assert matrix_reference() is None


def test_execution_image_registry_clear_during_decode_does_not_repopulate_cache() -> None:
    """验证 Run 结束清理与在途 decode 竞争时不会把矩阵重新放回缓存。"""

    np = pytest.importorskip("numpy")
    registry = ExecutionImageRegistry()
    decoder_started = Event()
    allow_decoder_finish = Event()

    def decoder():
        """等待清理发生后再返回矩阵。"""

        decoder_started.set()
        assert allow_decoder_finish.wait(timeout=2.0)
        return np.zeros((8, 8, 3), dtype=np.uint8)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            registry.get_or_decode_matrix,
            cache_key="in-flight",
            decoder=decoder,
        )
        assert decoder_started.wait(timeout=2.0)
        registry.clear_decoded_matrices()
        allow_decoder_finish.set()
        result = future.result(timeout=2.0)

    assert result.flags.writeable is False
    assert registry.decoded_cache_entry_count == 0
    assert registry.decoded_cache_total_bytes == 0


def test_execution_image_registry_failed_decode_allows_clean_retry() -> None:
    """验证 decoder 异常不会留下永久 flight 或占用缓存容量。"""

    np = pytest.importorskip("numpy")
    registry = ExecutionImageRegistry()

    with pytest.raises(RuntimeError, match="decode failed"):
        registry.get_or_decode_matrix(
            cache_key="retry-image",
            decoder=lambda: (_ for _ in ()).throw(RuntimeError("decode failed")),
        )

    recovered = registry.get_or_decode_matrix(
        cache_key="retry-image",
        decoder=lambda: np.ones((4, 4, 3), dtype=np.uint8),
    )

    assert registry.decoded_cache_entry_count == 1
    assert int(recovered[0, 0, 0]) == 1


def test_load_image_matrix_invalidates_storage_cache_after_file_overwrite(tmp_path: Path) -> None:
    """验证同一 object key 在 Run 内被覆盖后不会继续返回旧矩阵。"""

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "files")))
    registry = ExecutionImageRegistry()
    request = _build_request(
        dataset_storage=dataset_storage,
        image_registry=registry,
        payload={"object_key": "inputs/source.png", "media_type": "image/png"},
    )
    first_source = np.zeros((8, 8, 3), dtype=np.uint8)
    second_source = np.full((9, 8, 3), 255, dtype=np.uint8)

    first_ok, first_encoded = cv2.imencode(".png", first_source)
    second_ok, second_encoded = cv2.imencode(".png", second_source)
    assert first_ok is True and second_ok is True
    dataset_storage.write_bytes("inputs/source.png", first_encoded.tobytes())
    _, first_matrix = load_image_matrix(request, cv2_module=cv2, np_module=np)
    dataset_storage.write_bytes("inputs/source.png", second_encoded.tobytes())
    _, second_matrix = load_image_matrix(request, cv2_module=cv2, np_module=np)

    assert first_matrix.shape == first_source.shape
    assert second_matrix.shape == second_source.shape
    assert np.array_equal(second_matrix, second_source)
    assert first_matrix is not second_matrix


def test_register_image_bytes_and_copy_image_payload_support_memory_source(tmp_path: Path) -> None:
    """验证 memory 模式图片可以注册后再显式保存到本地存储。"""

    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "files")))
    registry = ExecutionImageRegistry()
    request = _build_request(
        dataset_storage=dataset_storage,
        image_registry=registry,
        payload={"object_key": "inputs/source.png"},
    )

    memory_payload = register_image_bytes(
        request,
        content=b"memory-result",
        media_type="image/png",
        width=12,
        height=6,
    )
    saved_payload = copy_image_payload(
        request,
        source_payload=memory_payload,
        object_key="outputs/result.png",
        overwrite=True,
        variant_name="saved",
    )

    assert saved_payload == build_storage_image_payload(
        object_key="outputs/result.png",
        source_payload=memory_payload,
    )
    assert dataset_storage.resolve("outputs/result.png").read_bytes() == b"memory-result"


def test_resolve_image_reference_returns_unified_view_for_memory_payload() -> None:
    """验证 resolve_image_reference 会返回统一轻量视图。"""

    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir="./data/files"))
    registry = ExecutionImageRegistry()
    request = _build_request(
        dataset_storage=dataset_storage,
        image_registry=registry,
        payload={
            "transport_kind": "memory",
            "image_handle": "img-1",
            "media_type": "image/png",
            "width": 100,
            "height": 50,
        },
    )

    resolved_image = resolve_image_reference(request)

    assert resolved_image.transport_kind == IMAGE_TRANSPORT_MEMORY
    assert resolved_image.image_handle == "img-1"
    assert resolved_image.object_key is None
    assert resolved_image.width == 100
    assert resolved_image.height == 50


def test_build_response_image_payload_defaults_to_inline_base64(tmp_path: Path) -> None:
    """验证响应适配默认返回 inline-base64，不泄露内部图片引用。"""

    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "files")))
    dataset_storage.write_bytes("inputs/source.png", b"png-response")
    registry = ExecutionImageRegistry()
    request = _build_request(
        dataset_storage=dataset_storage,
        image_registry=registry,
        payload={"object_key": "inputs/source.png", "media_type": "image/png"},
    )

    response_image = build_response_image_payload(
        request,
        image_payload=request.input_values["image"],
    )

    assert response_image["transport_kind"] == "inline-base64"
    assert response_image["media_type"] == "image/png"
    assert response_image["image_base64"] == "cG5nLXJlc3BvbnNl"
    assert "object_key" not in response_image


def test_preview_detects_unknown_dimensions_before_selecting_high_resolution_transport(
    tmp_path: Path,
) -> None:
    """验证缺少尺寸的长边大图解码一次后才切换 source transport。"""

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "files")))
    registry = ExecutionImageRegistry()
    request = _build_request(
        dataset_storage=dataset_storage,
        image_registry=registry,
        payload={"object_key": "inputs/source.png"},
    )
    image_matrix = np.zeros((10, 1930, 3), dtype=np.uint8)
    encoded, encoded_matrix = cv2.imencode(".png", image_matrix)
    assert encoded is True
    memory_payload = register_image_bytes(
        request,
        content=encoded_matrix.tobytes(),
        media_type="image/png",
    )

    response_image = build_preview_response_image_payload(
        request,
        image_payload=memory_payload,
        response_transport_mode="inline-base64",
        object_key="outputs/source.png",
        display_object_key="outputs/display.jpg",
    )

    assert response_image["source_image"]["transport_kind"] == "storage-ref"
    assert response_image["source_width"] == 1930
    assert response_image["source_height"] == 10
    assert response_image["display_image"]["transport_kind"] == "inline-base64"
    assert response_image["display_width"] == 1920
    assert response_image["preview_image_kind"] == "display"


def test_build_response_image_payload_supports_explicit_storage_ref(tmp_path: Path) -> None:
    """验证响应适配在显式 storage-ref 模式下会返回 object_key。"""

    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "files")))
    registry = ExecutionImageRegistry()
    request = _build_request(
        dataset_storage=dataset_storage,
        image_registry=registry,
        payload={"object_key": "inputs/source.png", "media_type": "image/png"},
    )
    memory_payload = register_image_bytes(
        request,
        content=b"response-storage",
        media_type="image/png",
        width=9,
        height=5,
    )

    response_image = build_response_image_payload(
        request,
        image_payload=memory_payload,
        response_transport_mode="storage-ref",
        object_key="outputs/preview.png",
    )

    assert response_image["transport_kind"] == "storage-ref"
    assert response_image["object_key"] == "outputs/preview.png"
    assert dataset_storage.resolve("outputs/preview.png").read_bytes() == b"response-storage"


def _build_request(
    *,
    dataset_storage: LocalDatasetStorage,
    image_registry: ExecutionImageRegistry,
    payload: dict[str, object],
) -> WorkflowNodeExecutionRequest:
    """构造 runtime_support 测试使用的最小节点请求。"""

    return WorkflowNodeExecutionRequest(
        node_id="test-node",
        node_definition=object(),
        input_values={"image": payload},
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "runtime-support-test",
        },
    )
