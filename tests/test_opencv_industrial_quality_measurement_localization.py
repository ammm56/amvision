"""工业图片质量、二维量测和统一定位节点测试。"""

from __future__ import annotations

from pathlib import Path
from threading import Event

import cv2
from jsonschema import Draft202012Validator
import numpy as np
import pytest

from backend.nodes import ExecutionImageRegistry
from backend.nodes.runtime_support import register_image_matrix
from backend.service.application.errors import OperationCancelledError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.categories.basic.backend.nodes.image_quality_metrics import (
    handle_node as handle_image_quality_metrics,
)
from custom_nodes.opencv_nodes.categories.matching.backend.nodes.industrial_localization import (
    INDUSTRIAL_LOCALIZATION_NODE_HANDLERS,
    handle_feature_locate,
    handle_shape_locate,
)
from custom_nodes.opencv_nodes.categories.measurement.backend.nodes.industrial_measurement import (
    INDUSTRIAL_MEASUREMENT_NODE_HANDLERS,
    handle_edge_pair_measure,
    handle_ellipse_measure,
    handle_gray_profile_measure,
    handle_line_measure,
    handle_radial_line_search,
    handle_rectangle_measure,
)
from custom_nodes.opencv_nodes.shared.workflow.payload_contracts import (
    load_shared_opencv_payload_contracts_payload,
)


def _request(
    registry: ExecutionImageRegistry,
    *,
    parameters: dict[str, object] | None = None,
    input_values: dict[str, object] | None = None,
) -> WorkflowNodeExecutionRequest:
    """构造共享图片 registry 的节点请求。"""

    return WorkflowNodeExecutionRequest(
        node_id="phase3-test",
        node_definition=object(),
        parameters=dict(parameters or {}),
        input_values=dict(input_values or {}),
        execution_metadata={"execution_image_registry": registry},
    )


def _register(registry: ExecutionImageRegistry, matrix: np.ndarray) -> dict[str, object]:
    """注册 uint8 测试图片。"""

    return register_image_matrix(_request(registry), image_matrix=matrix)


def test_phase3_catalog_sources_and_handler_sets_are_complete() -> None:
    """验证阶段 3 九个节点都有源定义和 handler。"""

    repository_root = Path(__file__).resolve().parents[1]
    planned = {
        "custom.opencv.image-quality-metrics",
        "custom.opencv.line-measure",
        "custom.opencv.ellipse-measure",
        "custom.opencv.rectangle-measure",
        "custom.opencv.edge-pair-measure",
        "custom.opencv.gray-profile-measure",
        "custom.opencv.radial-line-search",
        "custom.opencv.feature-locate",
        "custom.opencv.shape-locate",
    }
    fragments = {
        f'custom.opencv.{path.stem.replace("_", "-")}'
        for path in repository_root.glob(
            "custom_nodes/opencv_nodes/categories/*/workflow/catalog_sources/nodes/*.json"
        )
        if path.stem
        in {
            "image_quality_metrics",
            "line_measure",
            "ellipse_measure",
            "rectangle_measure",
            "edge_pair_measure",
            "gray_profile_measure",
            "radial_line_search",
            "feature_locate",
            "shape_locate",
        }
    }
    handlers = {
        "custom.opencv.image-quality-metrics",
        *(node_type_id for node_type_id, _ in INDUSTRIAL_MEASUREMENT_NODE_HANDLERS),
        *(node_type_id for node_type_id, _ in INDUSTRIAL_LOCALIZATION_NODE_HANDLERS),
    }
    assert fragments == planned
    assert handlers == planned


def test_image_quality_metrics_are_monotonic_for_blur_and_noise() -> None:
    """验证清晰度随模糊下降、稳健噪声估计随噪声上升。"""

    registry = ExecutionImageRegistry()
    checker = (
        (np.indices((128, 128))[0] // 8 + np.indices((128, 128))[1] // 8) % 2
    ) * 255
    checker = checker.astype(np.uint8)
    blurred = cv2.GaussianBlur(checker, (15, 15), 4.0)
    random = np.random.default_rng(42)
    noisy = np.clip(
        blurred.astype(np.int16) + random.normal(0, 20, blurred.shape),
        0,
        255,
    ).astype(np.uint8)
    sharp_metrics = handle_image_quality_metrics(
        _request(registry, input_values={"image": _register(registry, checker)})
    )["metrics"]["value"]
    blurred_metrics = handle_image_quality_metrics(
        _request(registry, input_values={"image": _register(registry, blurred)})
    )["metrics"]["value"]
    noisy_metrics = handle_image_quality_metrics(
        _request(registry, input_values={"image": _register(registry, noisy)})
    )["metrics"]["value"]
    assert sharp_metrics["laplacian_variance"] > blurred_metrics["laplacian_variance"]
    assert sharp_metrics["tenengrad"] > blurred_metrics["tenengrad"]
    assert noisy_metrics["noise_sigma_robust"] > blurred_metrics["noise_sigma_robust"]


def test_gray_profile_edge_pair_and_line_measure() -> None:
    """验证剖面、边缘对和卡尺阵列直线拟合。"""

    registry = ExecutionImageRegistry()
    image = np.zeros((100, 120), dtype=np.uint8)
    image[:, 35:75] = 220
    payload = _register(registry, image)
    profile = handle_gray_profile_measure(
        _request(
            registry,
            parameters={"start_xy": [0, 50], "end_xy": [119, 50], "band_width": 5},
            input_values={"image": payload},
        )
    )["profile"]["value"]
    gradient = np.asarray(profile["gradient"])
    assert int(np.argmax(gradient)) == pytest.approx(35, abs=1)
    assert int(np.argmin(gradient)) == pytest.approx(75, abs=1)

    edge_pair = handle_edge_pair_measure(
        _request(
            registry,
            parameters={
                "start_xy": [0, 50],
                "end_xy": [119, 50],
                "band_width": 5,
                "pair_polarity": "opposite",
                "gradient_threshold": 20,
                "minimum_spacing": 30,
                "maximum_spacing": 50,
            },
            input_values={"image": payload},
        )
    )
    pair_values = edge_pair["measurements"]["items"][0]["values"]
    assert pair_values["found"] is True
    assert pair_values["spacing"] == pytest.approx(40.0, abs=1.5)
    contracts = {
        item["payload_type_id"]: item
        for item in load_shared_opencv_payload_contracts_payload()
    }
    measurement_validator = Draft202012Validator(
        contracts["measurements.v1"]["json_schema"]
    )
    assert list(measurement_validator.iter_errors(edge_pair["measurements"])) == []

    line = handle_line_measure(
        _request(
            registry,
            parameters={
                "start_xy": [35, 10],
                "end_xy": [35, 90],
                "caliper_length": 20,
                "caliper_count": 20,
                "gradient_threshold": 20,
            },
            input_values={"image": payload},
        )
    )
    fitted = line["lines"]["items"][0]
    assert fitted["start_xy"][0] == pytest.approx(35.0, abs=1.0)
    assert fitted["end_xy"][0] == pytest.approx(35.0, abs=1.0)
    assert fitted["residual_rms"] < 0.25
    assert list(measurement_validator.iter_errors(line["measurements"])) == []


def test_radial_ellipse_and_rectangle_measurement() -> None:
    """验证圆、椭圆和矩形的合成几何量测。"""

    registry = ExecutionImageRegistry()
    circle_image = np.zeros((160, 160), dtype=np.uint8)
    cv2.circle(circle_image, (80, 80), 35, 255, thickness=-1)
    radial = handle_radial_line_search(
        _request(
            registry,
            parameters={
                "center_xy": [80, 80],
                "inner_radius": 20,
                "outer_radius": 50,
                "ray_count": 72,
                "edge_polarity": "bright-to-dark",
                "gradient_threshold": 20,
                "fit_kind": "circle",
            },
            input_values={"image": _register(registry, circle_image)},
        )
    )
    circle = radial["circles"]["items"][0]
    assert circle["center_xy"] == pytest.approx([80, 80], abs=0.5)
    assert circle["radius"] == pytest.approx(35, abs=1.0)
    assert radial["measurements"]["items"][0]["values"]["coverage_ratio"] > 0.95

    ellipse_image = np.zeros((180, 200), dtype=np.uint8)
    cv2.ellipse(ellipse_image, (100, 90), (50, 30), 20, 0, 360, 255, thickness=-1)
    nominal_ellipse = {
        "coordinate_space": "source-image-pixels",
        "unit": "pixel",
        "count": 1,
        "items": [
            {
                "ellipse_index": 1,
                "center_xy": [100, 90],
                "major_axis": 100,
                "minor_axis": 60,
                "angle_deg": 20,
            }
        ],
    }
    ellipse = handle_ellipse_measure(
        _request(
            registry,
            parameters={"sample_count": 72, "search_length": 16, "gradient_threshold": 20},
            input_values={
                "image": _register(registry, ellipse_image),
                "ellipse": nominal_ellipse,
            },
        )
    )["ellipses"]["items"][0]
    assert ellipse["center_xy"] == pytest.approx([100, 90], abs=1.0)
    assert ellipse["major_axis"] == pytest.approx(100, abs=2.0)
    assert ellipse["minor_axis"] == pytest.approx(60, abs=2.0)
    assert ellipse["coverage_ratio"] > 0.9

    rectangle_image = np.zeros((180, 220), dtype=np.uint8)
    box = cv2.boxPoints(((110, 90), (100, 60), 15)).astype(np.int32)
    cv2.fillConvexPoly(rectangle_image, box, 255)
    rectangle = handle_rectangle_measure(
        _request(
            registry,
            parameters={
                "center_xy": [110, 90],
                "width": 100,
                "height": 60,
                "angle_degrees": 15,
                "caliper_length": 16,
                "calipers_per_side": 14,
                "gradient_threshold": 20,
            },
            input_values={"image": _register(registry, rectangle_image)},
        )
    )["measurements"]["items"][0]["values"]
    measured_sides = sorted([rectangle["width"], rectangle["height"]])
    assert measured_sides == pytest.approx([60, 100], abs=2.0)
    assert rectangle["rectangularity_error_degrees"] < 3.0


def test_feature_and_shape_localization_emit_unified_payload() -> None:
    """验证两类定位工具都输出统一 localizations.v1。"""

    registry = ExecutionImageRegistry()
    random = np.random.default_rng(20260830)
    template = random.integers(0, 256, size=(120, 140), dtype=np.uint8)
    cv2.circle(template, (45, 40), 20, 0, 3)
    cv2.line(template, (20, 100), (120, 20), 255, 3)
    source = np.zeros((260, 320), dtype=np.uint8)
    source[70:190, 90:230] = template
    feature = handle_feature_locate(
        _request(
            registry,
            parameters={"detector": "orb", "minimum_matches": 8},
            input_values={
                "image": _register(registry, source),
                "template_image": _register(registry, template),
            },
        )
    )["localizations"]
    feature_item = feature["items"][0]
    assert feature_item["center_xy"] == pytest.approx([160, 130], abs=2.0)
    assert feature_item["angle_degrees"] == pytest.approx(0.0, abs=2.0)
    assert feature_item["scale"] == pytest.approx(1.0, abs=0.05)

    shape_template = np.zeros((80, 90), dtype=np.uint8)
    cv2.rectangle(shape_template, (10, 10), (75, 65), 255, 3)
    cv2.circle(shape_template, (30, 35), 8, 255, 2)
    shape_source = np.zeros((200, 240), dtype=np.uint8)
    shape_source[55:135, 100:190] = shape_template
    shape = handle_shape_locate(
        _request(
            registry,
            parameters={"minimum_score": 0.7},
            input_values={
                "image": _register(registry, shape_source),
                "template_image": _register(registry, shape_template),
            },
        )
    )["localizations"]
    shape_item = shape["items"][0]
    assert shape_item["center_xy"] == pytest.approx([145, 95], abs=1.0)
    assert shape_item["scale"] == pytest.approx(1.0, abs=0.01)

    contracts = {
        item["payload_type_id"]: item
        for item in load_shared_opencv_payload_contracts_payload()
    }
    validator = Draft202012Validator(contracts["localizations.v1"]["json_schema"])
    assert list(validator.iter_errors(feature)) == []
    assert list(validator.iter_errors(shape)) == []


def test_long_measurement_loop_observes_workflow_cancellation() -> None:
    """验证工业量测长循环在进入计算前响应 Workflow 取消。"""

    cancellation_event = Event()
    cancellation_event.set()
    with pytest.raises(OperationCancelledError):
        handle_radial_line_search(
            WorkflowNodeExecutionRequest(
                node_id="cancelled-radial-search",
                node_definition=object(),
                parameters={"center_xy": [32, 32]},
                input_values={},
                node_cancellation_event=cancellation_event,
            )
        )
