"""runtime_support 多来源图片 helper 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.nodes.runtime_support import (
    ExecutionImageRegistry,
    IMAGE_TRANSPORT_MEMORY,
    IMAGE_TRANSPORT_STORAGE,
    build_response_image_payload,
    build_memory_image_payload,
    build_storage_image_payload,
    copy_image_payload,
    load_image_bytes,
    register_image_bytes,
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