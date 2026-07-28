"""OpenCV 标定、特征、分割和特殊变换节点执行测试。"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from pathlib import Path

import pytest

from backend.nodes import ExecutionImageRegistry
from backend.nodes.runtime_support import register_image_matrix
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.categories.calibration.backend.nodes import (
    camera_calibrate,
    chessboard_corners,
    circle_grid_detect,
    corner_subpix,
    fisheye_calibrate,
    hand_eye_calibrate,
    project_points,
    undistort_points,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes import (
    clear_border,
    flood_fill,
    grabcut,
    kmeans_segment,
    morphology_hitmiss,
    region_difference,
    region_intersection,
    region_union,
    remove_small_components,
    watershed_markers,
)
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes import (
    flip,
    get_rect_subpix,
    pad_border,
    transpose,
    warp_polar,
)
from custom_nodes.opencv_nodes.categories.matching.backend.nodes import (
    akaze_keypoints,
    brisk_keypoints,
    fast_corners,
    flann_match,
    good_features_to_track,
    line_segment_detect,
    sift_keypoints,
)

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

EXTENDED_NODE_MODULES = (
    circle_grid_detect,
    corner_subpix,
    fisheye_calibrate,
    hand_eye_calibrate,
    project_points,
    undistort_points,
    akaze_keypoints,
    brisk_keypoints,
    fast_corners,
    flann_match,
    good_features_to_track,
    line_segment_detect,
    sift_keypoints,
    clear_border,
    flood_fill,
    grabcut,
    kmeans_segment,
    morphology_hitmiss,
    region_difference,
    region_intersection,
    region_union,
    remove_small_components,
    watershed_markers,
    flip,
    get_rect_subpix,
    pad_border,
    transpose,
    warp_polar,
)


def test_extended_nodes_own_their_handler_implementation() -> None:
    """固定一节点一实现文件，禁止退化为入口转发或聚合算法模块。"""

    for module in EXTENDED_NODE_MODULES:
        module_path = Path(module.__file__).resolve()
        handler_path = Path(inspect.getsourcefile(module.handle_node) or "").resolve()
        assert handler_path == module_path
        syntax_tree = ast.parse(module_path.read_text(encoding="utf-8"))
        assert any(
            isinstance(item, ast.FunctionDef) and item.name == "handle_node"
            for item in syntax_tree.body
        )

    repository_root = Path(__file__).resolve().parents[1]
    removed_aggregates = (
        "custom_nodes/opencv_nodes/categories/calibration/backend/nodes/"
        "calibration_operations.py",
        "custom_nodes/opencv_nodes/categories/matching/backend/nodes/"
        "feature_operations.py",
        "custom_nodes/opencv_nodes/categories/defect/backend/nodes/"
        "segmentation_operations.py",
        "custom_nodes/opencv_nodes/categories/geometry/backend/nodes/"
        "special_transform_operations.py",
    )
    assert all(not (repository_root / path).exists() for path in removed_aggregates)


def test_calibration_and_pose_nodes_execute() -> None:
    """验证圆点阵、亚像素点、fisheye、投影、点矫正和 hand-eye 链路。"""

    metadata = {"execution_image_registry": ExecutionImageRegistry()}
    circle_grid = _build_asymmetric_circle_grid(columns=4, rows=5, spacing=34)
    circle_payload = _register_image(metadata, circle_grid)
    observation = _execute(
        circle_grid_detect.handle_node,
        metadata,
        {"image": circle_payload},
        {"columns": 4, "rows": 5, "spacing": 2.0, "asymmetric": True},
    )["observation"]
    refined = _execute(
        corner_subpix.handle_node,
        metadata,
        {"image": circle_payload, "points": observation},
        {"window_size": 3},
    )["points"]["value"]

    calibration = {
        "value": {
            "model": "pinhole",
            "camera_matrix": [
                [500.0, 0.0, 160.0],
                [0.0, 500.0, 120.0],
                [0.0, 0.0, 1.0],
            ],
            "distortion_coefficients": [0.01, -0.005, 0.0, 0.0, 0.0],
        }
    }
    pose = {
        "value": {
            "rotation_vector": [0.02, -0.01, 0.03],
            "translation_vector": [0.0, 0.0, 400.0],
        }
    }
    projected = _execute(
        project_points.handle_node,
        metadata,
        {
            "object_points": {
                "value": [[0, 0, 0], [20, 0, 0], [20, 20, 0], [0, 20, 0]]
            },
            "pose": pose,
            "calibration": calibration,
        },
    )["image_points"]
    corrected = _execute(
        undistort_points.handle_node,
        metadata,
        {"points": projected, "calibration": calibration},
    )["points"]["value"]

    robot_poses, target_poses = _build_hand_eye_pose_sequences()
    hand_eye = _execute(
        hand_eye_calibrate.handle_node,
        metadata,
        {
            "robot_poses": {"value": {"items": robot_poses}},
            "target_poses": {"value": {"items": target_poses}},
        },
        {"method": "tsai"},
    )["hand_eye"]["value"]

    fisheye_images = [
        _register_image(metadata, image)
        for image in _build_calibration_views(
            columns=6,
            rows=4,
            square_pixels=32,
        )
    ]
    calibration_observations = [
        _execute(
            chessboard_corners.handle_node,
            metadata,
            {"image": image_payload},
            {"columns": 6, "rows": 4, "square_size": 10.0, "use_sb": False},
        )["observation"]["value"]
        for image_payload in fisheye_images
    ]
    pinhole = _execute(
        camera_calibrate.handle_node,
        metadata,
        {"observations": {"value": {"items": calibration_observations}}},
        {"min_views": 3},
    )["calibration"]["value"]
    fisheye = _execute(
        fisheye_calibrate.handle_node,
        metadata,
        {"observations": {"value": {"items": calibration_observations}}},
        {"min_views": 3},
    )["calibration"]["value"]

    assert refined["point_count"] == 20
    assert corrected["point_count"] == 4
    assert len(hand_eye["transform_matrix_4x4"]) == 4
    assert pinhole["input_kind"] == "observations"
    assert fisheye["model"] == "fisheye"
    assert fisheye["input_kind"] == "observations"
    assert fisheye["view_count"] >= 3


def test_feature_and_geometric_detection_nodes_execute() -> None:
    """验证 SIFT、AKAZE、BRISK、FLANN、角点和 LSD。"""

    metadata = {"execution_image_registry": ExecutionImageRegistry()}
    image = _build_feature_image()
    shifted = cv2.warpAffine(
        image, np.float32([[1, 0, 4], [0, 1, 3]]), (image.shape[1], image.shape[0])
    )
    image_payload = _register_image(metadata, image)
    shifted_payload = _register_image(metadata, shifted)
    sift_a = _execute(sift_keypoints.handle_node, metadata, {"image": image_payload})[
        "features"
    ]
    sift_b = _execute(sift_keypoints.handle_node, metadata, {"image": shifted_payload})[
        "features"
    ]
    akaze = _execute(akaze_keypoints.handle_node, metadata, {"image": image_payload})[
        "features"
    ]
    akaze_shifted = _execute(
        akaze_keypoints.handle_node,
        metadata,
        {"image": shifted_payload},
    )["features"]
    brisk = _execute(brisk_keypoints.handle_node, metadata, {"image": image_payload})[
        "features"
    ]
    matches = _execute(
        flann_match.handle_node,
        metadata,
        {"features_a": sift_a, "features_b": sift_b},
        {"ratio_test_threshold": 0.85},
    )["matches"]
    binary_matches = _execute(
        flann_match.handle_node,
        metadata,
        {"features_a": akaze, "features_b": akaze_shifted},
        {"ratio_test_threshold": 0.9},
    )["matches"]
    good = _execute(
        good_features_to_track.handle_node, metadata, {"image": image_payload}
    )["points"]["value"]
    fast = _execute(
        fast_corners.handle_node, metadata, {"image": image_payload}, {"threshold": 5}
    )["points"]["value"]
    lines = _execute(
        line_segment_detect.handle_node,
        metadata,
        {"image": image_payload},
        {"min_length": 8.0},
    )["lines"]

    assert sift_a["descriptor_dtype"] == "float32"
    assert sift_a["count"] > 0
    assert akaze["count"] > 0
    assert brisk["count"] > 0
    assert matches["count"] > 0
    assert binary_matches["matcher_kind"] == "flann-lsh"
    assert binary_matches["count"] > 0
    assert good["point_count"] > 0
    assert fast["point_count"] > 0
    assert lines["count"] > 0


def test_segmentation_and_region_nodes_execute() -> None:
    """验证分割、marker watershed、连通域清理和区域集合运算。"""

    metadata = {"execution_image_registry": ExecutionImageRegistry()}
    image = np.zeros((96, 112, 3), dtype=np.uint8)
    image[:] = (20, 20, 20)
    cv2.rectangle(image, (15, 18), (50, 72), (30, 180, 230), -1)
    cv2.circle(image, (78, 48), 22, (210, 80, 30), -1)
    image_payload = _register_image(metadata, image)

    flood = _execute(
        flood_fill.handle_node,
        metadata,
        {"image": image_payload},
        {"seed_x": 25, "seed_y": 30, "lo_diff": 5.0, "up_diff": 5.0},
    )["mask"]
    grab = _execute(
        grabcut.handle_node,
        metadata,
        {"image": image_payload},
        {"x": 8, "y": 10, "width": 94, "height": 76, "iterations": 2},
    )
    kmeans = _execute(
        kmeans_segment.handle_node,
        metadata,
        {"image": image_payload},
        {"cluster_count": 3, "attempts": 1},
    )

    binary_a = np.zeros((96, 112), dtype=np.uint8)
    binary_a[0:10, 0:10] = 255
    binary_a[20:70, 20:60] = 255
    binary_a[80:83, 80:83] = 255
    binary_b = np.zeros_like(binary_a)
    binary_b[45:85, 45:90] = 255
    payload_a = _register_image(metadata, binary_a)
    payload_b = _register_image(metadata, binary_b)
    removed = _execute(
        remove_small_components.handle_node,
        metadata,
        {"image": payload_a},
        {"min_area": 20},
    )["mask"]
    cleared = _execute(clear_border.handle_node, metadata, {"image": payload_a})["mask"]
    union = _execute(
        region_union.handle_node,
        metadata,
        {"region_a": payload_a, "region_b": payload_b},
    )["mask"]
    intersection = _execute(
        region_intersection.handle_node,
        metadata,
        {"region_a": payload_a, "region_b": payload_b},
    )["mask"]
    difference = _execute(
        region_difference.handle_node,
        metadata,
        {"region_a": payload_a, "region_b": payload_b},
    )["mask"]
    hitmiss = _execute(morphology_hitmiss.handle_node, metadata, {"image": payload_a})[
        "mask"
    ]

    markers = np.zeros_like(binary_a)
    markers[0:5, :] = 1
    markers[30:40, 30:40] = 2
    markers[45:55, 72:82] = 3
    watershed = _execute(
        watershed_markers.handle_node,
        metadata,
        {"image": image_payload, "markers": _register_image(metadata, markers)},
    )

    assert flood["transport_kind"] == "memory"
    assert grab["mask"]["transport_kind"] == "memory"
    assert kmeans["clusters"]["value"]["cluster_count"] == 3
    assert all(
        output["transport_kind"] == "memory"
        for output in [removed, cleared, union, intersection, difference, hitmiss]
    )
    assert watershed["summary"]["value"]["region_count"] >= 1


def test_special_geometry_transform_nodes_execute() -> None:
    """验证亚像素裁剪、极坐标展开、翻转、转置和边界扩展。"""

    metadata = {"execution_image_registry": ExecutionImageRegistry()}
    image = _build_feature_image(width=120, height=96)
    image_payload = _register_image(metadata, image)
    outputs = [
        _execute(
            get_rect_subpix.handle_node,
            metadata,
            {"image": image_payload},
            {"center_x": 60.5, "center_y": 48.25, "width": 40, "height": 32},
        )["image"],
        _execute(
            warp_polar.handle_node,
            metadata,
            {"image": image_payload},
            {
                "center_x": 60.0,
                "center_y": 48.0,
                "max_radius": 40.0,
                "output_width": 40,
                "output_height": 180,
            },
        )["image"],
        _execute(
            flip.handle_node, metadata, {"image": image_payload}, {"direction": "both"}
        )["image"],
        _execute(transpose.handle_node, metadata, {"image": image_payload})["image"],
        _execute(
            pad_border.handle_node,
            metadata,
            {"image": image_payload},
            {"top": 3, "bottom": 4, "left": 5, "right": 6, "border_mode": "reflect"},
        )["image"],
    ]

    assert all(output["transport_kind"] == "memory" for output in outputs)


def _execute(
    handler: Callable[[WorkflowNodeExecutionRequest], dict[str, object]],
    metadata: dict[str, object],
    inputs: dict[str, object],
    parameters: dict[str, object] | None = None,
) -> dict[str, object]:
    """执行一个节点处理器。"""

    return handler(
        WorkflowNodeExecutionRequest(
            node_id="extended-node",
            node_definition=object(),
            parameters=parameters or {},
            input_values=inputs,
            execution_metadata=metadata,
        )
    )


def _register_image(metadata: dict[str, object], image: object) -> dict[str, object]:
    """把 ndarray 注册为 memory image-ref。"""

    return register_image_matrix(
        WorkflowNodeExecutionRequest(
            node_id="image-source",
            node_definition=object(),
            execution_metadata=metadata,
        ),
        image_matrix=image,
    )


def _build_feature_image(*, width: int = 160, height: int = 128) -> object:
    """生成带丰富角点、线段和纹理的测试图。"""

    image = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(8, height - 8, 16):
        for x in range(8, width - 8, 16):
            color = 230 if ((x + y) // 16) % 2 == 0 else 60
            cv2.rectangle(
                image,
                (x, y),
                (min(width - 1, x + 8), min(height - 1, y + 8)),
                (color, 255 - color, 180),
                -1,
            )
    cv2.line(image, (5, height - 10), (width - 5, 8), (255, 255, 255), 2)
    cv2.circle(
        image, (width // 2, height // 2), min(width, height) // 5, (0, 255, 255), 2
    )
    cv2.putText(
        image,
        "AM",
        (15, height // 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (255, 255, 255),
        2,
    )
    return image


def _build_asymmetric_circle_grid(*, columns: int, rows: int, spacing: int) -> object:
    """生成黑圆白底的非对称圆点阵。"""

    width = (2 * columns + 2) * spacing
    height = (rows + 2) * spacing
    image = np.full((height, width), 255, dtype=np.uint8)
    for row in range(rows):
        for column in range(columns):
            center = ((2 * column + row % 2 + 1) * spacing, (row + 1) * spacing)
            cv2.circle(image, center, max(5, spacing // 5), 0, -1, lineType=cv2.LINE_AA)
    return image


def _build_calibration_views(
    *, columns: int, rows: int, square_pixels: int
) -> list[object]:
    """生成多视角棋盘格图片。"""

    board = np.full(
        ((rows + 1) * square_pixels, (columns + 1) * square_pixels), 255, dtype=np.uint8
    )
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
    source = np.float32(
        [
            [0, 0],
            [board.shape[1] - 1, 0],
            [board.shape[1] - 1, board.shape[0] - 1],
            [0, board.shape[0] - 1],
        ]
    )
    targets = [
        np.float32([[45, 35], [285, 28], [300, 210], [38, 220]]),
        np.float32([[55, 22], [278, 42], [292, 225], [30, 202]]),
        np.float32([[38, 48], [295, 35], [280, 215], [52, 228]]),
        np.float32([[62, 40], [275, 20], [305, 205], [42, 230]]),
    ]
    views = []
    for target in targets:
        transform = cv2.getPerspectiveTransform(source, target)
        views.append(cv2.warpPerspective(board, transform, (340, 260), borderValue=127))
    return views


def _build_hand_eye_pose_sequences() -> tuple[
    list[dict[str, object]], list[dict[str, object]]
]:
    """生成可用于 hand-eye 求解的多组非退化位姿。"""

    robot_items: list[dict[str, object]] = []
    target_items: list[dict[str, object]] = []
    for index in range(6):
        robot_items.append(
            {
                "rotation_vector": [0.03 * index, -0.02 * (index + 1), 0.015 * index],
                "translation_vector": [
                    20.0 * index,
                    8.0 * index * index,
                    300.0 + 5.0 * index,
                ],
            }
        )
        target_items.append(
            {
                "rotation_vector": [-0.02 * index, 0.025 * (index + 1), -0.01 * index],
                "translation_vector": [
                    120.0 - 6.0 * index,
                    30.0 + 9.0 * index,
                    500.0 + 12.0 * index,
                ],
            }
        )
    return robot_items, target_items
