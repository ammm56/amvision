"""Circle Measure 共享圆定位算法回归测试。"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from custom_nodes._opencv_shared.backend.runtime.circle_measurement import (
    fit_circle_robust,
    sample_radial_edges,
)
from custom_nodes._opencv_shared.backend.runtime.search_roi import (
    ResolvedSearchRoi,
    build_search_roi_overlay,
)
from custom_nodes.opencv_shape_nodes.backend.nodes.hough_circles import (
    _build_circle_interaction,
)


def test_circle_measurement_refines_noisy_reference_circle_to_subpixel_result() -> None:
    """验证径向采样与 robust fitting 能从有偏差的参考圆恢复真实圆。"""

    image = np.full((240, 260), 30, dtype=np.uint8)
    cv2.circle(image, (132, 117), 46, 220, thickness=3, lineType=cv2.LINE_AA)
    cv2.line(image, (80, 90), (185, 150), 180, thickness=1, lineType=cv2.LINE_AA)
    samples = sample_radial_edges(
        image,
        center_x=129.5,
        center_y=119.0,
        reference_radius_px=44.0,
        radius_tolerance_px=8.0,
        sample_count=240,
        gradient_threshold=8.0,
        edge_polarity="bright-to-dark",
        cv2_module=cv2,
        np_module=np,
    )
    fitted = fit_circle_robust(
        samples.points_xy,
        np_module=np,
        robust_loss="tukey",
        inlier_threshold_px=2.5,
    )

    assert fitted.center_x == pytest.approx(132.0, abs=0.8)
    assert fitted.center_y == pytest.approx(117.0, abs=0.8)
    # bright-to-dark 明确选择亮圆环的外侧边缘，避免 any 极性在内外边缘间跳变。
    assert fitted.radius == pytest.approx(48.0, abs=1.2)
    assert fitted.arc_coverage >= 0.8
    assert fitted.fit_rmse_px <= 1.5


def test_circle_measurement_ransac_rejects_unrelated_outlier_points() -> None:
    """验证有界 RANSAC 能在异常边缘点存在时恢复主圆。"""

    random_generator = np.random.default_rng(20260720)
    angles = np.linspace(0.0, 2.0 * np.pi, 180, endpoint=False)
    circle_points = np.column_stack(
        (
            80.0 + np.cos(angles) * 32.0,
            65.0 + np.sin(angles) * 32.0,
        )
    )
    circle_points += random_generator.normal(0.0, 0.2, size=circle_points.shape)
    outliers = random_generator.uniform([10.0, 10.0], [150.0, 120.0], size=(45, 2))
    fitted = fit_circle_robust(
        np.vstack((circle_points, outliers)),
        np_module=np,
        robust_loss="tukey",
        inlier_threshold_px=1.2,
        ransac_iterations=96,
    )

    assert fitted.center_x == pytest.approx(80.0, abs=0.25)
    assert fitted.center_y == pytest.approx(65.0, abs=0.25)
    assert fitted.radius == pytest.approx(32.0, abs=0.25)
    assert fitted.ransac_inlier_count >= 175
    assert fitted.inlier_count >= 175


def test_hough_circle_tool_keeps_search_roi_independent() -> None:
    """验证 Reference Circle 工具不会再写回或覆盖 Search ROI。"""

    interaction = _build_circle_interaction(
        accumulator_resolution_ratio=1.0,
        minimum_center_distance_px=20.0,
        canny_high_threshold=100.0,
        center_vote_threshold=20.0,
        minimum_radius_px=10,
        maximum_radius_px=60,
        median_blur_kernel_size=5,
        processing_max_long_edge=2048,
        reference_radius_px=30.0,
        radius_tolerance_px=8.0,
        maximum_refinement_center_shift_px=12.0,
        refine_candidates=True,
        edge_polarity="any",
        radial_sample_count=180,
        gradient_threshold=12.0,
        robust_loss="huber",
        ransac_iterations=32,
        fit_inlier_threshold_px=2.0,
        minimum_arc_coverage=0.55,
        minimum_edge_support_ratio=0.5,
        minimum_polarity_consistency=0.55,
        minimum_quality_score=0.35,
        maximum_fit_error_px=3.0,
        illumination_normalization="clahe",
        clahe_clip_limit=2.0,
        clahe_tile_grid_size=8,
        show_rejected_candidates=False,
        sort_by="quality_score",
        descending=True,
        max_results=10,
        maximum_candidates=40,
        image_width=640,
        image_height=480,
    )
    tools = {item["tool"]: item for item in interaction["tools"]}

    assert tools["rect"]["target_parameters"] == ["search_bbox_xyxy"]
    assert "search_bbox_xyxy" not in tools["circle"]["target_parameters"]
    assert tools["circle"]["target_parameters"] == [
        "reference_radius_px",
        "radius_tolerance_px",
    ]


def test_search_roi_overlay_has_distinct_semantic_kind() -> None:
    """验证持久化 Search ROI 使用独立 overlay kind，避免与检测圆共色。"""

    search_roi = ResolvedSearchRoi(
        image_matrix=np.zeros((40, 50), dtype=np.uint8),
        offset_x=10,
        offset_y=20,
        bbox_xyxy=[10, 20, 60, 60],
        source="parameter",
        roi_id=None,
        roi_kind=None,
        polygon_bbox_only=False,
    )

    overlay = build_search_roi_overlay(search_roi)

    assert overlay is not None
    assert overlay["kind"] == "search-roi"
