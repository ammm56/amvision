"""Image Encode core node 回归测试。"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

import backend.nodes.runtime_support as runtime_support_module
from backend.nodes import ExecutionImageRegistry, register_image_matrix
from backend.nodes.core_nodes.io.image.image_encode import CORE_NODE_SPEC
from backend.nodes.runtime_support import (
    load_image_matrix_from_payload,
    prepare_workflow_image_access_timings,
    read_workflow_image_access_timings,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


@pytest.mark.parametrize(
    ("image_format", "media_type"),
    (
        ("jpeg", "image/jpeg"),
        ("png", "image/png"),
        ("bmp", "image/bmp"),
        ("webp", "image/webp"),
    ),
)
def test_image_encode_outputs_decodable_image_ref(
    image_format: str,
    media_type: str,
) -> None:
    """四种正式格式都保持 image-ref，并能还原原始尺寸。"""

    registry = ExecutionImageRegistry()
    matrix = np.zeros((5, 7, 3), dtype=np.uint8)
    matrix[:, :, 0] = 17
    matrix[:, :, 1] = 91
    matrix[:, :, 2] = 203
    source_request = _build_request(registry=registry, image=None)
    source_payload = register_image_matrix(source_request, image_matrix=matrix)
    request = _build_request(
        registry=registry,
        image=source_payload,
        parameters={"format": image_format},
    )

    output = CORE_NODE_SPEC.handler(request)["image"]

    assert output["transport_kind"] == "memory"
    assert output["media_type"] == media_type
    assert output["width"] == 7
    assert output["height"] == 5
    encoded = registry.read_bytes(str(output["image_handle"]))
    assert encoded is not None and len(encoded) > 0
    _, decoded = load_image_matrix_from_payload(
        request,
        image_payload=output,
        cv2_module=cv2,
        np_module=np,
    )
    assert decoded.shape == matrix.shape


def test_image_encode_reuses_execution_decode_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一编码输入被多个 Image Encode 节点消费时只解码一次。"""

    registry = ExecutionImageRegistry()
    source = np.full((4, 6, 3), 121, dtype=np.uint8)
    success, encoded = cv2.imencode(".png", source)
    assert success is True
    entry = registry.register_image_bytes(
        content=encoded.tobytes(),
        media_type="image/png",
        width=6,
        height=4,
    )
    source_payload = {
        "transport_kind": "memory",
        "image_handle": entry.image_handle,
        "media_type": "image/png",
        "width": 6,
        "height": 4,
    }
    original_imdecode = cv2.imdecode
    decode_count = 0

    def counted_imdecode(*args: object, **kwargs: object) -> object:
        nonlocal decode_count
        decode_count += 1
        return original_imdecode(*args, **kwargs)

    monkeypatch.setattr(cv2, "imdecode", counted_imdecode)
    for node_id, image_format in (("encode-jpeg", "jpeg"), ("encode-png", "png")):
        CORE_NODE_SPEC.handler(
            _build_request(
                registry=registry,
                image=source_payload,
                parameters={"format": image_format},
                node_id=node_id,
            )
        )

    assert decode_count == 1


def test_image_encode_rejects_unknown_format() -> None:
    """节点不根据未知扩展名猜测格式。"""

    registry = ExecutionImageRegistry()
    request = _build_request(
        registry=registry,
        image={"transport_kind": "storage", "object_key": "unused.png", "media_type": "image/png"},
        parameters={"format": "tiff"},
    )

    with pytest.raises(InvalidRequestError, match="只支持"):
        CORE_NODE_SPEC.handler(request)


def test_workflow_image_access_timings_split_raw_view_and_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """诊断模式区分 raw mmap/view 路径和 encoded 首次解码，cache hit 不重复计时。"""

    fake_clock = 0.0

    def fake_monotonic() -> float:
        """使用确定性时钟避免亚毫秒路径被三位小数舍入为零。"""

        nonlocal fake_clock
        fake_clock += 0.001
        return fake_clock

    monkeypatch.setattr(runtime_support_module, "monotonic", fake_monotonic)

    registry = ExecutionImageRegistry()
    request = _build_request(registry=registry, image=None)
    request.execution_metadata["return_timing_metadata_enabled"] = True
    prepare_workflow_image_access_timings(request.execution_metadata)

    raw_payload = register_image_matrix(
        request,
        image_matrix=np.zeros((3, 4, 3), dtype=np.uint8),
    )
    load_image_matrix_from_payload(
        request,
        image_payload=raw_payload,
        cv2_module=cv2,
        np_module=np,
    )
    raw_timings = read_workflow_image_access_timings(request.execution_metadata)
    assert raw_timings["workflow_raw_view_ms"] >= 0
    assert raw_timings["workflow_image_decode_ms"] == 0

    success, encoded = cv2.imencode(
        ".png", np.zeros((1024, 1024, 3), dtype=np.uint8)
    )
    assert success is True
    entry = registry.register_image_bytes(
        content=encoded.tobytes(),
        media_type="image/png",
    )
    encoded_payload = {
        "transport_kind": "memory",
        "image_handle": entry.image_handle,
        "media_type": "image/png",
    }
    load_image_matrix_from_payload(
        request,
        image_payload=encoded_payload,
        cv2_module=cv2,
        np_module=np,
    )
    decoded_timings = read_workflow_image_access_timings(request.execution_metadata)
    assert decoded_timings["workflow_image_decode_ms"] > 0, decoded_timings
    load_image_matrix_from_payload(
        request,
        image_payload=encoded_payload,
        cv2_module=cv2,
        np_module=np,
    )
    assert read_workflow_image_access_timings(request.execution_metadata)[
        "workflow_image_decode_ms"
    ] == decoded_timings["workflow_image_decode_ms"]


def _build_request(
    *,
    registry: ExecutionImageRegistry,
    image: object,
    parameters: dict[str, object] | None = None,
    node_id: str = "image-encode",
) -> WorkflowNodeExecutionRequest:
    """构造最小节点执行请求。"""

    return WorkflowNodeExecutionRequest(
        node_id=node_id,
        node_definition=CORE_NODE_SPEC.node_definition,
        parameters=dict(parameters or {}),
        input_values={"image": image},
        execution_metadata={"execution_image_registry": registry},
    )
