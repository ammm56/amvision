"""工业二维图片创建、转换、组合和拼接节点测试。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.nodes import ExecutionImageRegistry
from backend.nodes.runtime_support import register_image_matrix
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.categories.basic.backend.nodes.industrial_image import (
    INDUSTRIAL_IMAGE_NODE_HANDLERS,
    handle_image_composite,
    handle_image_concat,
    handle_image_create,
    handle_image_stitch,
    handle_image_translate,
    handle_image_type_convert,
)
from custom_nodes.opencv_nodes.categories.basic.workflow.catalog_builder import (
    build_custom_node_catalog_payload,
)

INDUSTRIAL_IMAGE_NODE_IDS = {
    "custom.opencv.image-create",
    "custom.opencv.image-type-convert",
    "custom.opencv.image-translate",
    "custom.opencv.image-composite",
    "custom.opencv.image-concat",
    "custom.opencv.image-stitch",
}


def _request(
    registry: ExecutionImageRegistry,
    *,
    parameters: dict[str, object] | None = None,
    input_values: dict[str, object] | None = None,
) -> WorkflowNodeExecutionRequest:
    """构造共享同一图片 registry 的节点请求。"""

    return WorkflowNodeExecutionRequest(
        node_id="industrial-image-test",
        node_definition=object(),
        parameters=dict(parameters or {}),
        input_values=dict(input_values or {}),
        execution_metadata={"execution_image_registry": registry},
    )


def _register(
    registry: ExecutionImageRegistry,
    matrix: np.ndarray,
) -> dict[str, object]:
    """注册一张 uint8 测试图片。"""

    return register_image_matrix(
        _request(registry),
        image_matrix=matrix,
    )


def _matrix(registry: ExecutionImageRegistry, payload: dict[str, object]) -> np.ndarray:
    """从输出 payload 读取执行期矩阵。"""

    value = registry.read_matrix(str(payload["image_handle"]))
    assert isinstance(value, np.ndarray)
    return value


def test_industrial_image_catalog_and_handlers_are_in_parity() -> None:
    """验证六个源定义和运行时 handler 一一对应。"""

    repository_root = Path(__file__).resolve().parents[1]
    workflow_dir = (
        repository_root
        / "custom_nodes"
        / "opencv_nodes"
        / "categories"
        / "basic"
        / "workflow"
    )
    catalog = build_custom_node_catalog_payload(workflow_dir=workflow_dir)
    catalog_ids = {
        str(item["node_type_id"])
        for item in catalog["node_definitions"]
        if str(item["node_type_id"]) in INDUSTRIAL_IMAGE_NODE_IDS
    }
    handler_ids = {item[0] for item in INDUSTRIAL_IMAGE_NODE_HANDLERS}
    assert catalog_ids == INDUSTRIAL_IMAGE_NODE_IDS
    assert handler_ids == INDUSTRIAL_IMAGE_NODE_IDS


def test_image_create_and_type_convert_preserve_requested_dtype() -> None:
    """验证创建和数值转换不会被 image-ref 隐式降为 uint8。"""

    registry = ExecutionImageRegistry()
    created = handle_image_create(
        _request(
            registry,
            parameters={
                "width": 4,
                "height": 3,
                "channels": 1,
                "dtype": "uint16",
                "fill_value": 1000,
            },
        )
    )["image"]
    created_matrix = _matrix(registry, created)
    assert created["dtype"] == "uint16"
    assert created["pixel_format"] == "gray16"
    assert created_matrix.dtype == np.uint16
    assert created_matrix.shape == (3, 4)
    assert np.all(created_matrix == 1000)

    source = np.asarray([[0, 64], [128, 255]], dtype=np.uint8)
    converted = handle_image_type_convert(
        _request(
            registry,
            parameters={
                "target_dtype": "float32",
                "range_mode": "normalize",
            },
            input_values={"image": _register(registry, source)},
        )
    )["image"]
    converted_matrix = _matrix(registry, converted)
    assert converted["dtype"] == "float32"
    assert converted["pixel_format"] == "gray32f"
    assert converted_matrix.dtype == np.float32
    assert float(converted_matrix.min()) == pytest.approx(0.0)
    assert float(converted_matrix.max()) == pytest.approx(1.0)


def test_image_type_convert_identity_reuses_contiguous_run_matrix() -> None:
    """验证无类型变化时不为大图制造无必要的整图副本。"""

    registry = ExecutionImageRegistry()
    source = np.zeros((1080, 1920, 3), dtype=np.uint8)
    converted = handle_image_type_convert(
        _request(
            registry,
            parameters={
                "target_dtype": "uint8",
                "channel_layout": "keep",
                "range_mode": "preserve",
            },
            input_values={"image": _register(registry, source)},
        )
    )["image"]

    assert _matrix(registry, converted) is source
    assert converted["transport_kind"] == "memory"
    assert "image_base64" not in converted


def test_translate_composite_and_concat_have_deterministic_geometry() -> None:
    """验证平移、负偏移组合和对齐拼接的空间规则。"""

    registry = ExecutionImageRegistry()
    source = np.zeros((4, 5), dtype=np.uint8)
    source[1, 1] = 200
    translated = handle_image_translate(
        _request(
            registry,
            parameters={
                "offset_x": 2,
                "offset_y": 1,
                "interpolation": "nearest",
                "border_value": 7,
            },
            input_values={"image": _register(registry, source)},
        )
    )["image"]
    translated_matrix = _matrix(registry, translated)
    assert int(translated_matrix[2, 3]) == 200
    assert int(translated_matrix[0, 0]) == 7

    base = np.zeros((4, 5), dtype=np.uint8)
    overlay = np.full((3, 3), 100, dtype=np.uint8)
    mask = np.full((3, 3), 255, dtype=np.uint8)
    mask[0, 0] = 0
    composited = handle_image_composite(
        _request(
            registry,
            parameters={"offset_x": -1, "offset_y": 1, "alpha": 0.5},
            input_values={
                "base_image": _register(registry, base),
                "overlay_image": _register(registry, overlay),
                "mask": _register(registry, mask),
            },
        )
    )["image"]
    composited_matrix = _matrix(registry, composited)
    assert composited_matrix.shape == base.shape
    assert int(composited_matrix[1, 0]) == 50
    assert int(composited_matrix[3, 1]) == 50

    first = np.full((2, 2), 10, dtype=np.uint8)
    second = np.full((4, 1), 20, dtype=np.uint8)
    concatenated = handle_image_concat(
        _request(
            registry,
            parameters={
                "axis": "horizontal",
                "alignment": "end",
                "gap": 1,
                "fill_value": 3,
            },
            input_values={
                "images": {
                    "items": [
                        _register(registry, first),
                        _register(registry, second),
                    ]
                }
            },
        )
    )["image"]
    concatenated_matrix = _matrix(registry, concatenated)
    assert concatenated_matrix.shape == (4, 4)
    assert np.all(concatenated_matrix[:2, :2] == 3)
    assert np.all(concatenated_matrix[2:, :2] == 10)
    assert np.all(concatenated_matrix[:, 3] == 20)


def test_composite_rejects_incompatible_image_types() -> None:
    """验证组合节点不会隐式猜测 dtype 或通道转换。"""

    registry = ExecutionImageRegistry()
    with pytest.raises(InvalidRequestError, match="dtype 和通道数必须一致"):
        handle_image_composite(
            _request(
                registry,
                input_values={
                    "base_image": _register(
                        registry,
                        np.zeros((4, 4), dtype=np.uint8),
                    ),
                    "overlay_image": _register(
                        registry,
                        np.zeros((2, 2, 3), dtype=np.uint8),
                    ),
                },
            )
        )


def test_image_stitch_real_feature_smoke() -> None:
    """使用有稳定重叠纹理的真实 OpenCV 路径验证拼接输出。"""

    registry = ExecutionImageRegistry()
    random = np.random.default_rng(20260830)
    panorama = random.integers(0, 256, size=(240, 520, 3), dtype=np.uint8)
    cv2.putText(
        panorama,
        "AMVISION",
        (90, 130),
        cv2.FONT_HERSHEY_SIMPLEX,
        2.0,
        (0, 0, 0),
        5,
        cv2.LINE_AA,
    )
    left = panorama[:, :340].copy()
    right = panorama[:, 180:].copy()
    result = handle_image_stitch(
        _request(
            registry,
            parameters={"mode": "scans", "confidence_threshold": 0.3},
            input_values={
                "images": {
                    "items": [
                        _register(registry, left),
                        _register(registry, right),
                    ]
                }
            },
        )
    )
    output = _matrix(registry, result["image"])
    assert output.shape[1] >= 500
    assert output.shape[0] >= 230
    diagnostics = result["diagnostics"]["value"]
    assert diagnostics["status"] == "ok"
    assert diagnostics["image_count"] == 2
