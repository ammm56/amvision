"""OpenCV P0 原子节点执行测试。"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from backend.nodes import ExecutionImageRegistry
from backend.nodes.runtime_support import register_image_matrix
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.categories.basic.backend.nodes import (
    apply_mask,
    box_blur,
    brightness_contrast,
    channel_merge,
    channel_select,
    channel_split,
    color_convert,
    color_range_threshold,
    filter_2d,
    gabor_filter,
    gamma_correction,
    histogram,
    histogram_equalize,
    image_arithmetic,
    mask_logic,
    roi_intensity_statistics,
    scharr,
)
from custom_nodes.opencv_nodes.categories.calibration.backend.nodes import (
    camera_calibrate,
    chessboard_corners,
    solve_pnp,
)
from custom_nodes.opencv_nodes.categories.matching.backend.nodes import (
    ecc_align,
    multi_scale_template_match,
    phase_correlation,
    rotation_scale_template_match,
)
from custom_nodes.opencv_nodes.categories.shape.backend.nodes import (
    convexity_defects,
    hu_moments,
    image_moments,
    point_polygon_test,
    region_properties,
    shape_match,
)

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")


def test_p0_color_mask_statistics_and_filter_nodes_execute() -> None:
    """验证 17 个颜色、掩膜、统计和滤波原子节点均能执行。"""

    metadata = {"execution_image_registry": ExecutionImageRegistry()}
    image = np.zeros((64, 80, 3), dtype=np.uint8)
    image[12:52, 20:60] = (20, 180, 240)
    second = np.full_like(image, 25)
    image_payload = _register_image(metadata, image)
    second_payload = _register_image(metadata, second)

    gray = _execute(color_convert.handle_node, metadata, {"image": image_payload}, {"conversion": "bgr-to-gray"})["image"]
    mask = _execute(
        color_range_threshold.handle_node,
        metadata,
        {"image": image_payload},
        {"color_space": "hsv", "lower": [0, 80, 80], "upper": [179, 255, 255]},
    )["mask"]
    split = _execute(channel_split.handle_node, metadata, {"image": image_payload})
    merged = _execute(
        channel_merge.handle_node,
        metadata,
        {"channel_0": split["channel_0"], "channel_1": split["channel_1"], "channel_2": split["channel_2"]},
    )["image"]
    selected = _execute(channel_select.handle_node, metadata, {"image": image_payload}, {"channel_index": 1})["image"]
    inverted_mask = _execute(mask_logic.handle_node, metadata, {"mask_a": mask}, {"operation": "not"})["mask"]
    combined_mask = _execute(
        mask_logic.handle_node,
        metadata,
        {"mask_a": mask, "mask_b": inverted_mask},
        {"operation": "or"},
    )["mask"]
    masked = _execute(apply_mask.handle_node, metadata, {"image": image_payload, "mask": mask})["image"]
    arithmetic = _execute(
        image_arithmetic.handle_node,
        metadata,
        {"image_a": image_payload, "image_b": second_payload},
        {"operation": "absdiff"},
    )["image"]

    image_outputs = [
        gray,
        merged,
        selected,
        combined_mask,
        masked,
        arithmetic,
        _execute(gamma_correction.handle_node, metadata, {"image": image_payload}, {"gamma": 0.8})["image"],
        _execute(brightness_contrast.handle_node, metadata, {"image": image_payload}, {"alpha": 1.2, "beta": 5})["image"],
        _execute(histogram_equalize.handle_node, metadata, {"image": image_payload})["image"],
        _execute(box_blur.handle_node, metadata, {"image": image_payload}, {"kernel_width": 5, "kernel_height": 3})["image"],
        _execute(
            filter_2d.handle_node,
            metadata,
            {"image": image_payload},
            {"kernel": [[0, -1, 0], [-1, 5, -1], [0, -1, 0]]},
        )["image"],
        _execute(scharr.handle_node, metadata, {"image": image_payload}, {"direction": "magnitude"})["image"],
        _execute(gabor_filter.handle_node, metadata, {"image": image_payload}, {"kernel_size": 9})["image"],
    ]
    histogram_value = _execute(histogram.handle_node, metadata, {"image": image_payload}, {"bins": 16})["histogram"]["value"]
    statistics_value = _execute(roi_intensity_statistics.handle_node, metadata, {"image": image_payload})["statistics"]["value"]

    assert all(output["transport_kind"] == "memory" for output in image_outputs)
    assert len(histogram_value["items"]) == 3
    assert statistics_value["channel_count"] == 3


def test_p0_shape_feature_nodes_execute() -> None:
    """验证六个通用形状特征节点。"""

    metadata = {"execution_image_registry": ExecutionImageRegistry()}
    contour_payload = _contours_payload([[10, 10], [60, 10], [60, 50], [35, 30], [10, 50]])
    second_payload = _contours_payload([[12, 12], [58, 12], [58, 48], [35, 32], [12, 48]])

    properties = _execute(region_properties.handle_node, metadata, {"contours": contour_payload})["properties"]["value"]
    moments = _execute(image_moments.handle_node, metadata, {"contours": contour_payload})["moments"]["value"]
    hu = _execute(hu_moments.handle_node, metadata, {"contours": contour_payload})["hu_moments"]["value"]
    matched = _execute(
        shape_match.handle_node,
        metadata,
        {"contours_a": contour_payload, "contours_b": second_payload},
    )
    defects = _execute(convexity_defects.handle_node, metadata, {"contours": contour_payload})["defects"]["value"]
    point_result = _execute(
        point_polygon_test.handle_node,
        metadata,
        {"contours": contour_payload},
        {"points_xy": [[20, 20], [70, 70]]},
    )["result"]["value"]

    assert properties["items"][0]["area"] > 0
    assert moments["items"][0]["centroid_xy"] is not None
    assert len(hu["items"][0]["values"]) == 7
    assert matched["summary"]["value"]["lower_is_better"] is True
    assert defects["items"][0]["defect_count"] >= 1
    assert [item["relation"] for item in point_result["items"]] == ["inside", "outside"]


def test_p0_registration_and_template_nodes_execute() -> None:
    """验证稳健配准和尺度模板搜索节点。"""

    metadata = {"execution_image_registry": ExecutionImageRegistry()}
    reference = np.zeros((96, 112, 3), dtype=np.uint8)
    cv2.rectangle(reference, (30, 24), (58, 52), (255, 255, 255), -1)
    cv2.circle(reference, (44, 38), 6, (0, 0, 0), -1)
    moving = cv2.warpAffine(reference, np.float32([[1, 0, 4], [0, 1, 3]]), (112, 96))
    template = reference[24:53, 30:59].copy()
    reference_payload = _register_image(metadata, reference)
    moving_payload = _register_image(metadata, moving)
    template_payload = _register_image(metadata, template)

    phase = _execute(
        phase_correlation.handle_node,
        metadata,
        {"reference_image": reference_payload, "moving_image": moving_payload},
    )["transform"]["value"]
    ecc = _execute(
        ecc_align.handle_node,
        metadata,
        {"reference_image": reference_payload, "moving_image": moving_payload},
        {"motion": "translation", "iterations": 100},
    )
    multi_scale = _execute(
        multi_scale_template_match.handle_node,
        metadata,
        {"image": reference_payload, "template_image": template_payload},
        {"scale_min": 1.0, "scale_max": 1.0, "scale_step": 0.1, "score_threshold": 0.95},
    )
    rotation_scale = _execute(
        rotation_scale_template_match.handle_node,
        metadata,
        {"image": reference_payload, "template_image": template_payload},
        {
            "scale_min": 1.0,
            "scale_max": 1.0,
            "scale_step": 0.1,
            "angle_min_deg": 0.0,
            "angle_max_deg": 0.0,
            "angle_step_deg": 1.0,
            "score_threshold": 0.95,
        },
    )

    assert phase["response"] > 0
    assert ecc["transform"]["value"]["correlation"] > 0.9
    assert multi_scale["regions"]["count"] == 1
    assert rotation_scale["regions"]["count"] == 1


def test_p0_calibration_nodes_execute() -> None:
    """验证棋盘格检测、相机标定和 PnP 位姿估计闭环。"""

    metadata = {"execution_image_registry": ExecutionImageRegistry()}
    chessboard = _build_chessboard(columns=6, rows=4, square_pixels=36)
    chessboard_payload = _register_image(metadata, chessboard)
    observation = _execute(
        chessboard_corners.handle_node,
        metadata,
        {"image": chessboard_payload},
        {"columns": 6, "rows": 4, "square_size": 10.0, "use_sb": True},
    )["observation"]
    calibration = _execute(
        camera_calibrate.handle_node,
        metadata,
        {"images": {"items": [chessboard_payload], "count": 1}},
        {"columns": 6, "rows": 4, "square_size": 10.0, "min_views": 1, "use_sb": True},
    )["calibration"]

    camera_matrix = np.asarray([[800.0, 0.0, 320.0], [0.0, 800.0, 240.0], [0.0, 0.0, 1.0]])
    object_points = np.asarray([[0, 0, 0], [40, 0, 0], [40, 30, 0], [0, 30, 0]], dtype=np.float64)
    image_points, _ = cv2.projectPoints(
        object_points,
        np.asarray([0.05, -0.03, 0.02]),
        np.asarray([5.0, 3.0, 500.0]),
        camera_matrix,
        np.zeros(5),
    )
    pose = _execute(
        solve_pnp.handle_node,
        metadata,
        {
            "observation": {
                "value": {
                    "object_points": object_points.tolist(),
                    "image_points": image_points.reshape(-1, 2).tolist(),
                }
            },
            "calibration": {
                "value": {
                    "camera_matrix": camera_matrix.tolist(),
                    "distortion_coefficients": [0, 0, 0, 0, 0],
                }
            },
        },
        {"method": "iterative"},
    )["pose"]["value"]

    assert observation["value"]["point_count"] == 24
    assert calibration["value"]["view_count"] == 1
    assert len(calibration["value"]["distortion_coefficients"]) >= 4
    assert pose["mean_reprojection_error"] < 0.01
    assert len(pose["transform_matrix_4x4"]) == 4


def _execute(
    handler: Callable[[WorkflowNodeExecutionRequest], dict[str, object]],
    metadata: dict[str, object],
    inputs: dict[str, object],
    parameters: dict[str, object] | None = None,
) -> dict[str, object]:
    """执行单个原子节点处理器。"""

    request = WorkflowNodeExecutionRequest(
        node_id="p0-node",
        node_definition=object(),
        parameters=parameters or {},
        input_values=inputs,
        execution_metadata=metadata,
    )
    return handler(request)


def _register_image(metadata: dict[str, object], image: object) -> dict[str, object]:
    """把测试图片注册为 memory image-ref。"""

    request = WorkflowNodeExecutionRequest(
        node_id="image-source",
        node_definition=object(),
        execution_metadata=metadata,
    )
    return register_image_matrix(request, image_matrix=image)


def _contours_payload(points: list[list[int]]) -> dict[str, object]:
    """构造单轮廓测试 payload。"""

    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
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


def _build_chessboard(*, columns: int, rows: int, square_pixels: int) -> object:
    """生成具有指定内角点数量的棋盘格测试图片。"""

    board = np.full(((rows + 1) * square_pixels, (columns + 1) * square_pixels), 255, dtype=np.uint8)
    for row in range(rows + 1):
        for column in range(columns + 1):
            if (row + column) % 2 == 0:
                cv2.rectangle(
                    board,
                    (column * square_pixels, row * square_pixels),
                    ((column + 1) * square_pixels - 1, (row + 1) * square_pixels - 1),
                    0,
                    -1,
                )
    return cv2.copyMakeBorder(board, 24, 24, 24, 24, cv2.BORDER_CONSTANT, value=127)
