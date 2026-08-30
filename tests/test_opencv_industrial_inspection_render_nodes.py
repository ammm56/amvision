"""工业检查、变化模型和结果绘制节点测试。"""

from __future__ import annotations

from pathlib import Path

import cv2
from jsonschema import Draft202012Validator
import numpy as np

from backend.nodes import ExecutionImageRegistry
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.region import require_regions_payload
from backend.nodes.runtime_support import register_image_matrix
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.industrial_inspection import (
    INDUSTRIAL_INSPECTION_NODE_HANDLERS,
    handle_bead_inspect,
    handle_blob_analysis,
    handle_contour_deviation,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.variation_model import (
    VARIATION_MODEL_NODE_HANDLERS,
    handle_variation_inspect,
    handle_variation_model_build,
)
from custom_nodes.opencv_nodes.categories.render.backend.nodes.industrial_render import (
    INDUSTRIAL_RENDER_NODE_HANDLERS,
    handle_draw_calibration_reprojection,
    handle_draw_ellipses,
    handle_draw_inspection_errors,
    handle_draw_localizations,
)
from custom_nodes.opencv_nodes.shared.workflow.payload_contracts import (
    load_shared_opencv_payload_contracts_payload,
)


def _request(
    registry: ExecutionImageRegistry,
    *,
    parameters: dict[str, object] | None = None,
    input_values: dict[str, object] | None = None,
    storage: LocalDatasetStorage | None = None,
) -> WorkflowNodeExecutionRequest:
    """构造共享 registry 和可选 ObjectStore 的节点请求。"""

    metadata: dict[str, object] = {"execution_image_registry": registry}
    if storage is not None:
        metadata["dataset_storage"] = storage
    return WorkflowNodeExecutionRequest(
        node_id="phase5-test",
        node_definition=object(),
        parameters=dict(parameters or {}),
        input_values=dict(input_values or {}),
        execution_metadata=metadata,
    )


def _register(registry: ExecutionImageRegistry, image: np.ndarray) -> dict[str, object]:
    """注册测试图片。"""

    return register_image_matrix(_request(registry), image_matrix=image)


def _points(items: list[list[float]]) -> dict[str, object]:
    """构建 points.v1 测试 payload。"""

    return {
        "coordinate_space": "source-image-pixels",
        "unit": "pixel",
        "count": len(items),
        "items": [
            {"point_id": f"point-{index}", "point_index": index - 1, "xy": item}
            for index, item in enumerate(items, start=1)
        ],
    }


def _contour(points: list[list[int]]) -> dict[str, object]:
    """构建单轮廓 contours.v1 测试 payload。"""

    xs = [item[0] for item in points]
    ys = [item[1] for item in points]
    return {
        "count": 1,
        "items": [
            {
                "contour_index": 1,
                "point_count": len(points),
                "bbox_xyxy": [min(xs), min(ys), max(xs) + 1, max(ys) + 1],
                "points": points,
            }
        ],
    }


def test_phase5_handler_sets_are_complete() -> None:
    """验证阶段 5 九个节点都已注册 handler。"""

    handlers = {
        *(item[0] for item in INDUSTRIAL_INSPECTION_NODE_HANDLERS),
        *(item[0] for item in VARIATION_MODEL_NODE_HANDLERS),
        *(item[0] for item in INDUSTRIAL_RENDER_NODE_HANDLERS),
    }
    assert handlers == {
        "custom.opencv.blob-analysis",
        "custom.opencv.bead-inspect",
        "custom.opencv.contour-deviation-inspect",
        "custom.opencv.variation-model-build",
        "custom.opencv.variation-inspect",
        "custom.opencv.draw-ellipses",
        "custom.opencv.draw-localizations",
        "custom.opencv.draw-calibration-reprojection",
        "custom.opencv.draw-inspection-errors",
    }


def test_blob_analysis_emits_regions_and_measurements() -> None:
    """验证 Blob 的面积、圆度、灰度和 canonical payload。"""

    registry = ExecutionImageRegistry()
    mask = np.zeros((100, 120), dtype=np.uint8)
    cv2.circle(mask, (30, 40), 10, 255, -1)
    cv2.rectangle(mask, (70, 20), (100, 60), 255, -1)
    gray = np.full(mask.shape, 30, dtype=np.uint8)
    gray[mask > 0] = 180
    result = handle_blob_analysis(
        _request(
            registry,
            parameters={"minimum_area": 100},
            input_values={"mask": _register(registry, mask), "image": _register(registry, gray)},
        )
    )
    assert result["regions"]["count"] == 2
    assert len(result["measurements"]["items"]) == 2
    assert all(
        item["values"]["mean_gray"] == 180.0
        for item in result["measurements"]["items"]
    )
    contracts = {
        item["payload_type_id"]: item
        for item in load_shared_opencv_payload_contracts_payload()
    }
    assert len(require_regions_payload(result["regions"], node_id="phase5-test")["items"]) == 2
    assert list(
        Draft202012Validator(contracts["measurements.v1"]["json_schema"]).iter_errors(
            result["measurements"]
        )
    ) == []


def test_bead_inspect_distinguishes_gap_overflow_and_offset() -> None:
    """验证缺失、过宽和偏移胶路不会互相误判。"""

    registry = ExecutionImageRegistry()
    image = np.zeros((100, 160), dtype=np.uint8)
    image[45:55, 10:150] = 255
    image[45:55, 60:75] = 0
    image[30:70, 100:118] = 255
    image[45:55, 20:36] = 0
    image[62:72, 20:36] = 255
    result = handle_bead_inspect(
        _request(
            registry,
            parameters={
                "expected_width": 10,
                "width_tolerance": 3,
                "center_tolerance": 4,
                "search_half_width": 30,
                "sample_spacing": 2,
            },
            input_values={
                "image": _register(registry, image),
                "reference_path": _points([[10.0, 50.0], [150.0, 50.0]]),
            },
        )
    )
    values = result["measurements"]["items"][0]["values"]
    assert values["missing_count"] > 0
    assert values["overflow_count"] > 0
    assert values["offset_count"] > 0
    assert {item["class_name"] for item in result["error_regions"]["items"]} >= {
        "missing",
        "overflow",
        "offset",
    }


def test_contour_deviation_uses_correct_signed_error_names() -> None:
    """验证参考外部为 burr、参考内部为 notch。"""

    registry = ExecutionImageRegistry()
    reference = _contour([[10, 10], [90, 10], [90, 90], [10, 90]])
    measured = _contour(
        [[10, 10], [90, 10], [105, 50], [90, 90], [50, 78], [10, 90]]
    )
    result = handle_contour_deviation(
        _request(
            registry,
            parameters={"positive_tolerance": 2, "negative_tolerance": 2},
            input_values={
                "reference_contours": reference,
                "measured_contours": measured,
            },
        )
    )
    assert {item["class_name"] for item in result["error_regions"]["items"]} == {
        "burr",
        "notch",
    }


def test_variation_model_object_store_round_trip(tmp_path: Path) -> None:
    """验证正常样本建模、hash 校验与异常区域输出。"""

    registry = ExecutionImageRegistry()
    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=tmp_path / "objects"))
    random = np.random.default_rng(7)
    normal_images = [
        np.clip(100 + random.normal(0, 1, (64, 80)), 0, 255).astype(np.uint8)
        for _ in range(4)
    ]
    image_refs = {
        "count": len(normal_images),
        "items": [_register(registry, image) for image in normal_images],
    }
    built = handle_variation_model_build(
        _request(
            registry,
            storage=storage,
            parameters={"save_location": "inspection/models", "standard_deviation_floor": 2},
            input_values={"images": image_refs},
        )
    )
    model = built["model"]["value"]
    assert storage.resolve(model["object_key"]).is_file()
    anomaly = normal_images[0].copy()
    anomaly[20:35, 30:50] = 220
    inspected = handle_variation_inspect(
        _request(
            registry,
            storage=storage,
            parameters={"z_score_threshold": 5, "minimum_area": 20},
            input_values={"image": _register(registry, anomaly), "model": built["model"]},
        )
    )
    assert inspected["statistics"]["value"]["anomaly_region_count"] == 1
    assert inspected["error_regions"]["count"] == 1
    heatmap = registry.read_matrix(str(inspected["heatmap"]["image_handle"]))
    assert int(heatmap[25, 35]) > int(heatmap[0, 0])


def test_render_nodes_draw_all_canonical_result_types() -> None:
    """验证椭圆、定位、标定残差和检查错误都能形成可见叠加。"""

    registry = ExecutionImageRegistry()
    blank = np.zeros((120, 160, 3), dtype=np.uint8)
    source = _register(registry, blank)
    identity_transform = {
        "transform_kind": "homography",
        "matrix_3x3": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "inverse_matrix_3x3": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "source_coordinate_space": "template-image-pixels",
        "target_coordinate_space": "source-image-pixels",
        "match_count": 1,
        "inlier_count": 1,
        "inlier_match_ids": ["match-1"],
    }
    results = [
        handle_draw_ellipses(
            _request(
                registry,
                input_values={
                    "image": source,
                    "ellipses": {
                        "coordinate_space": "source-image-pixels",
                        "unit": "pixel",
                        "count": 1,
                        "items": [
                            {
                                "ellipse_index": 1,
                                "center_xy": [80.0, 60.0],
                                "major_axis": 60.0,
                                "minor_axis": 30.0,
                                "angle_deg": 20.0,
                            }
                        ],
                    },
                },
            )
        ),
        handle_draw_localizations(
            _request(
                registry,
                input_values={
                    "image": source,
                    "localizations": {
                        "coordinate_space": "source-image-pixels",
                        "angle_unit": "degrees",
                        "count": 1,
                        "items": [
                            {
                                "localization_id": "location-1",
                                "method": "shape",
                                "center_xy": [80.0, 60.0],
                                "angle_degrees": 15.0,
                                "scale": 1.0,
                                "score": 0.95,
                                "transform": identity_transform,
                                "region": {
                                    "polygon_xy": [[50, 40], [110, 40], [110, 80], [50, 80]]
                                },
                            }
                        ],
                    },
                },
            )
        ),
        handle_draw_calibration_reprojection(
            _request(
                registry,
                input_values={
                    "image": source,
                    "diagnostics": build_value_payload(
                        {
                            "items": [
                                {
                                    "index": 1,
                                    "valid": True,
                                    "observed_points": [[50.0, 50.0], [90.0, 70.0]],
                                    "projected_points": [[53.0, 49.0], [87.0, 72.0]],
                                }
                            ]
                        }
                    ),
                },
            )
        ),
        handle_draw_inspection_errors(
            _request(
                registry,
                input_values={
                    "image": source,
                    "error_regions": {
                        "count": 1,
                        "items": [
                            {
                                "region_id": "error-1",
                                "class_id": 0,
                                "class_name": "missing",
                                "score": 1.0,
                                "bbox_xyxy": [40.0, 30.0, 90.0, 80.0],
                                "polygon_xy": [[40, 30], [90, 30], [90, 80], [40, 80]],
                                "area": 2500,
                                "error_kind": "missing",
                            }
                        ],
                    },
                },
            )
        ),
    ]
    for result in results:
        matrix = registry.read_matrix(str(result["image"]["image_handle"]))
        assert matrix.shape == blank.shape
        assert int(np.count_nonzero(matrix)) > 0
